import logging
from dataclasses import dataclass
from time import monotonic, sleep
from typing import Tuple

from PyQt5.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

from desktop_app.tool_client import ToolModbusClient


@dataclass
class ToolPollConfig:
    host: str
    port: int
    unit_id: int
    status_register: int
    trigger_register: int
    direction_register: int
    timeout_seconds: float
    poll_interval_ms: int
    lock_register: int = 4
    lock_value: int = 2
    unlock_value: int = 1
    command_delay_ms: int = 50
    reconnect_interval_seconds: float = 2.0
    pending_status_values: Tuple[int, ...] = (1, 4)
    final_status_values: Tuple[int, ...] = (2, 3)
    final_status_poll_ms: int = 100
    active_poll_interval_ms: int = 100
    transitional_direction_values: Tuple[int, ...] = (1,)


class ToolPollWorker(QObject):
    result = pyqtSignal(int, int, int)
    error = pyqtSignal(str)
    write_succeeded = pyqtSignal(int, int)
    write_error = pyqtSignal(int, int, str)
    connection_state = pyqtSignal(str)
    bypass_changed = pyqtSignal(bool, bool, str)
    stopped = pyqtSignal()

    def __init__(self, config: ToolPollConfig):
        super().__init__()
        self.config = config
        self.client = ToolModbusClient(
            host=config.host,
            port=config.port,
            unit_id=config.unit_id,
            timeout=config.timeout_seconds,
        )
        self.timer = None
        self.polling = False
        self.reading = False
        self.next_reconnect_at = 0.0
        self.reconnecting = False
        self.bypass = False
        self.pending_result_active = False
        self.active_polling = True

    @pyqtSlot()
    def start(self):
        if self.polling:
            return
        self.polling = True
        self.timer = QTimer(self)
        self.timer.setInterval(max(self.config.active_poll_interval_ms, 50))
        self.timer.timeout.connect(self.poll_once)
        self.timer.start()
        self.poll_once()

    def mark_connection_failed(self, message: str):
        self.client.disconnect()
        self.next_reconnect_at = monotonic() + max(self.config.reconnect_interval_seconds, 1.0)
        if not self.reconnecting:
            logging.warning("螺钉枪自动重连开始：%s", message)
        self.reconnecting = True
        self.connection_state.emit("reconnecting")

    def ensure_connection_for_poll(self) -> bool:
        if self.client.is_connected():
            return True
        if monotonic() < self.next_reconnect_at:
            return False
        self.connection_state.emit("reconnecting")
        try:
            self.client.ensure_connected()
        except Exception as exc:
            logging.warning("螺钉枪自动重连失败：%s", exc)
            self.mark_connection_failed(str(exc))
            self.error.emit(str(exc))
            return False
        if self.reconnecting:
            logging.info("螺钉枪自动重连成功")
        self.reconnecting = False
        self.next_reconnect_at = 0.0
        self.connection_state.emit("connected")
        return True

    @pyqtSlot()
    def stop(self):
        self._stop(lock_before_disconnect=True)

    @pyqtSlot()
    def stop_without_lock(self):
        self._stop(lock_before_disconnect=False)

    def _stop(self, lock_before_disconnect: bool):
        self.polling = False
        self.bypass = False
        self.pending_result_active = False
        if self.timer is not None:
            self.timer.stop()
            self.timer.deleteLater()
            self.timer = None
        if lock_before_disconnect and self.client.is_connected():
            try:
                self.write_register_with_delay(
                    self.config.lock_register,
                    self.config.lock_value,
                    "主动断开前锁枪",
                )
            except Exception as exc:
                logging.warning("断开前锁定螺钉枪失败：%s", exc)
        self.client.disconnect()
        self.connection_state.emit("disconnected")
        self.stopped.emit()

    @pyqtSlot()
    def poll_once(self):
        if not self.polling or self.reading or self.bypass:
            return
        self.reading = True
        try:
            if not self.ensure_connection_for_poll():
                return
            trigger = self.client.read_register(self.config.trigger_register)
            direction = self.client.read_register(self.config.direction_register)
            status = self.client.read_register(self.config.status_register)
            transitional_directions = set(
                self.config.transitional_direction_values
            )
            final_statuses = set(self.config.final_status_values)
            if (
                trigger == 1
                and (
                    status in set(self.config.pending_status_values)
                    or direction in transitional_directions
                    or status not in final_statuses
                )
            ):
                self.pending_result_active = True
            elif (
                trigger != 1
                or (
                    status in final_statuses
                    and direction not in transitional_directions
                )
            ):
                self.pending_result_active = False
            pending_result = self.pending_result_active and trigger == 1
            if self.timer is not None:
                interval = (
                    self.config.final_status_poll_ms
                    if pending_result
                    else (
                        self.config.active_poll_interval_ms
                        if self.active_polling
                        else self.config.poll_interval_ms
                    )
                )
                self.timer.setInterval(max(int(interval), 50))
            if trigger == 1:
                logging.info(
                    "螺钉枪事件快照：direction=%s status=%s trigger=%s",
                    direction,
                    status,
                    trigger,
                )
            self.result.emit(status, trigger, direction)
        except Exception as exc:
            logging.error("螺钉枪读取53/54/100失败：%s", exc)
            self.mark_connection_failed(str(exc))
            self.error.emit(str(exc))
        finally:
            self.reading = False

    @pyqtSlot(bool)
    def set_active_polling(self, enabled: bool):
        self.active_polling = bool(enabled)
        if self.timer is None or self.pending_result_active:
            return
        interval = (
            self.config.active_poll_interval_ms
            if self.active_polling
            else self.config.poll_interval_ms
        )
        self.timer.setInterval(max(int(interval), 50))

    @pyqtSlot(bool)
    def set_bypass(self, enabled: bool):
        if not self.polling:
            self.bypass_changed.emit(
                enabled,
                False,
                "螺钉枪 worker 未运行",
            )
            return
        if enabled:
            self.bypass = True
            if self.timer is not None:
                self.timer.stop()
            try:
                if not self.ensure_connection_for_poll():
                    raise ConnectionError("螺钉枪通讯断开")
                self.write_register_with_delay(
                    self.config.lock_register,
                    self.config.unlock_value,
                    "进入降级模式开锁",
                )
                logging.info("降级模式已写地址%s=%s", self.config.lock_register, self.config.unlock_value)
                self.bypass_changed.emit(True, True, "")
            except Exception as exc:
                logging.error("降级模式开锁失败：%s", exc)
                self.bypass_changed.emit(True, False, str(exc))
            return
        self.bypass = False
        if self.timer is not None:
            self.timer.start()
        self.bypass_changed.emit(False, True, "")
        QTimer.singleShot(0, self.poll_once)

    @pyqtSlot(int, int)
    def write_register(self, register_address: int, value: int):
        if not self.polling:
            return
        if not self.ensure_connection_for_poll():
            self.write_error.emit(register_address, value, "螺钉枪通讯断开，正在重连")
            return
        try:
            self.write_register_with_delay(register_address, value, "业务指令")
            self.write_succeeded.emit(register_address, value)
        except Exception as exc:
            logging.error(
                "螺钉枪写寄存器失败 address=%s value=%s：%s",
                register_address,
                value,
                exc,
            )
            self.mark_connection_failed(str(exc))
            self.write_error.emit(register_address, value, str(exc))

    def write_register_with_delay(self, register_address: int, value: int, reason: str):
        delay_ms = max(int(self.config.command_delay_ms), 0)
        if delay_ms:
            logging.info(
                "螺钉枪%s：延迟%sms后写寄存器 address=%s value=%s",
                reason,
                delay_ms,
                register_address,
                value,
            )
            sleep(delay_ms / 1000.0)
        self.client.write_register(register_address, value)
        logging.info(
            "延迟%sms后写寄存器成功 address=%s value=%s",
            delay_ms,
            register_address,
            value,
        )
