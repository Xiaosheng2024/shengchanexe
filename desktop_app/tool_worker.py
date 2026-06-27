import logging
from dataclasses import dataclass
from time import monotonic

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
    reconnect_interval_seconds: float = 2.0


class ToolPollWorker(QObject):
    result = pyqtSignal(int, int, int)
    error = pyqtSignal(str)
    write_error = pyqtSignal(str)
    connection_state = pyqtSignal(str)
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

    @pyqtSlot()
    def start(self):
        if self.polling:
            return
        self.polling = True
        self.timer = QTimer(self)
        self.timer.setInterval(max(self.config.poll_interval_ms, 200))
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
        self.polling = False
        if self.timer is not None:
            self.timer.stop()
            self.timer.deleteLater()
            self.timer = None
        if self.client.is_connected():
            try:
                self.client.write_register(self.config.lock_register, self.config.lock_value)
            except Exception as exc:
                logging.warning("断开前锁定螺钉枪失败：%s", exc)
        self.client.disconnect()
        self.connection_state.emit("disconnected")
        self.stopped.emit()

    @pyqtSlot()
    def poll_once(self):
        if not self.polling or self.reading:
            return
        self.reading = True
        try:
            if not self.ensure_connection_for_poll():
                return
            direction = self.client.read_register(self.config.direction_register)
            trigger = self.client.read_register(self.config.trigger_register)
            status = self.client.read_register(self.config.status_register)
            self.result.emit(status, trigger, direction)
        except Exception as exc:
            logging.error("螺钉枪读寄存器失败：%s", exc)
            self.mark_connection_failed(str(exc))
            self.error.emit(str(exc))
        finally:
            self.reading = False

    @pyqtSlot(int, int)
    def write_register(self, register_address: int, value: int):
        if not self.polling:
            return
        if not self.ensure_connection_for_poll():
            self.write_error.emit("螺钉枪通讯中断，正在重连")
            return
        try:
            self.client.write_register(register_address, value)
        except Exception as exc:
            logging.error("螺钉枪写寄存器失败：%s", exc)
            self.mark_connection_failed(str(exc))
            self.write_error.emit(str(exc))
