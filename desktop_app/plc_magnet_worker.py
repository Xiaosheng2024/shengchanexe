from threading import Event

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

from shared.plc_magnet_flow import PlcMagnetConfig, PlcMagnetFlowController
from shared.s7_plc_client import S7PlcClient


class PlcMagnetWorker(QObject):
    progress = pyqtSignal(str, dict)
    completed = pyqtSignal(dict)
    error = pyqtSignal(str, dict)
    stopped = pyqtSignal()

    def __init__(self, config: PlcMagnetConfig):
        super().__init__()
        self.config = config
        self.cancel_event = Event()
        self.client = None

    @pyqtSlot()
    def start(self):
        details = {}
        try:
            self.client = S7PlcClient(
                self.config.plc_ip,
                self.config.plc_rack,
                self.config.plc_slot,
                min(float(self.config.plc_timeout_seconds), 1.0),
            )
            controller = PlcMagnetFlowController(
                self.client,
                self.config,
                progress=self.progress.emit,
                cancelled=self.cancel_event.is_set,
            )
            details = controller.run()
            self.completed.emit(details)
        except Exception as exc:
            details = {
                **details,
                "ok": False,
                "result": "ERROR",
                "error_message": str(exc),
            }
            self.error.emit(str(exc), details)
        finally:
            self.stopped.emit()

    @pyqtSlot()
    def stop(self):
        self.cancel_event.set()
        if self.client is not None:
            try:
                self.client.disconnect()
            except Exception:
                pass
