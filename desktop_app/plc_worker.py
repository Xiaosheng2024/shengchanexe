from dataclasses import dataclass

from PyQt5.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

from shared.s7_plc_client import S7BarcodeAddress, S7PlcClient


@dataclass
class PlcPollConfig:
    ip: str
    rack: int
    slot: int
    barcode1_db: int
    barcode1_offset: int
    barcode1_length: int
    barcode2_db: int
    barcode2_offset: int
    barcode2_length: int
    parts_ok_db: int
    parts_ok_offset: int
    parts_ok_type: str
    barcode_encoding: str
    strip_null: bool
    strip_space: bool
    timeout_seconds: int
    poll_interval_ms: int


class PlcPollWorker(QObject):
    snapshot = pyqtSignal(int, str, str, str, str)
    error = pyqtSignal(str)
    stopped = pyqtSignal()

    def __init__(self, config: PlcPollConfig):
        super().__init__()
        self.config = config
        self.client = None
        self.timer = None
        self.polling = False
        self.reading = False

    @pyqtSlot()
    def start(self):
        if self.polling:
            return
        self.polling = True
        try:
            self.client = S7PlcClient(self.config.ip, self.config.rack, self.config.slot, self.config.timeout_seconds)
            self.client.connect()
        except Exception as exc:
            self.error.emit(str(exc))
            return
        self.timer = QTimer(self)
        self.timer.setInterval(max(self.config.poll_interval_ms, 200))
        self.timer.timeout.connect(self.poll_once)
        self.timer.start()
        self.poll_once()

    @pyqtSlot()
    def stop(self):
        self.polling = False
        if self.timer is not None:
            self.timer.stop()
            self.timer.deleteLater()
            self.timer = None
        if self.client is not None:
            self.client.disconnect()
            self.client = None
        self.stopped.emit()

    @pyqtSlot()
    def poll_once(self):
        if not self.polling or self.reading or self.client is None:
            return
        self.reading = True
        try:
            barcode1 = S7BarcodeAddress(
                self.config.barcode1_db,
                self.config.barcode1_offset,
                self.config.barcode1_length,
                self.config.barcode_encoding,
                self.config.strip_null,
                self.config.strip_space,
            )
            barcode2 = S7BarcodeAddress(
                self.config.barcode2_db,
                self.config.barcode2_offset,
                self.config.barcode2_length,
                self.config.barcode_encoding,
                self.config.strip_null,
                self.config.strip_space,
            )
            snapshot = self.client.read_snapshot(barcode1, barcode2, self.config.parts_ok_db, self.config.parts_ok_offset, self.config.parts_ok_type)
            self.snapshot.emit(snapshot.parts_ok, snapshot.barcode1, snapshot.barcode2, snapshot.barcode1_hex, snapshot.barcode2_hex)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.reading = False
