from dataclasses import dataclass

from PyQt5.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

from desktop_app.tool_client import ToolModbusClient


@dataclass
class ToolPollConfig:
    host: str
    port: int
    unit_id: int
    status_register: int
    trigger_register: int
    timeout_seconds: float
    poll_interval_ms: int


class ToolPollWorker(QObject):
    result = pyqtSignal(int, int)
    error = pyqtSignal(str)
    write_error = pyqtSignal(str)
    stopped = pyqtSignal()

    def __init__(self, config: ToolPollConfig):
        super().__init__()
        self.config = config
        self.client = ToolModbusClient(timeout=config.timeout_seconds)
        self.timer = None
        self.polling = False
        self.reading = False

    @pyqtSlot()
    def start(self):
        if self.polling:
            return
        self.polling = True
        self.timer = QTimer(self)
        self.timer.setInterval(max(self.config.poll_interval_ms, 200))
        self.timer.timeout.connect(self.poll_once)
        self.timer.start()

    @pyqtSlot()
    def stop(self):
        self.polling = False
        if self.timer is not None:
            self.timer.stop()
            self.timer.deleteLater()
            self.timer = None
        self.stopped.emit()

    @pyqtSlot()
    def poll_once(self):
        if not self.polling or self.reading:
            return
        self.reading = True
        try:
            status = self.client.read_register(
                self.config.host,
                self.config.port,
                self.config.unit_id,
                self.config.status_register,
            )
            trigger = self.client.read_register(
                self.config.host,
                self.config.port,
                self.config.unit_id,
                self.config.trigger_register,
            )
            self.result.emit(status, trigger)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.reading = False

    @pyqtSlot(int, int)
    def write_register(self, register_address: int, value: int):
        try:
            self.client.write_register(
                self.config.host,
                self.config.port,
                self.config.unit_id,
                register_address,
                value,
            )
        except Exception as exc:
            self.write_error.emit(str(exc))
