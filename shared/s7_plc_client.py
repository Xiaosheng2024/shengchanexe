from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class S7BarcodeAddress:
    db_number: int
    offset: int
    length: int
    encoding: str = "ascii"
    strip_null: bool = True
    strip_space: bool = True


@dataclass
class S7Snapshot:
    parts_ok: int
    main_barcode: str
    main_barcode_hex: str

    @property
    def barcode1(self) -> str:
        return self.main_barcode

    @property
    def barcode1_hex(self) -> str:
        return self.main_barcode_hex


def parse_barcode(raw_bytes: bytes, encoding: str = "ascii", strip_null: bool = True, strip_space: bool = True) -> Tuple[str, str]:
    hex_text = raw_bytes.hex(" ").upper()
    text = raw_bytes.decode(encoding, errors="ignore")
    if strip_null:
        text = text.replace("\x00", "")
    text = text.replace("\r", "").replace("\n", "").replace("\t", "")
    if strip_space:
        text = text.strip()
    return text, hex_text


class S7PlcClient:
    def __init__(self, ip: str, rack: int = 0, slot: int = 1, timeout_seconds: float = 3.0):
        self.ip = ip
        self.rack = rack
        self.slot = slot
        self.timeout_ms = int(max(timeout_seconds, 0.1) * 1000)
        self.client = None
        self.snap7 = None
        self.snap7_util = None

    def connect(self):
        try:
            import snap7
            from snap7 import util as snap7_util
        except Exception as exc:
            raise RuntimeError("未安装 python-snap7，请先安装依赖") from exc

        self.snap7 = snap7
        self.snap7_util = snap7_util
        self.client = snap7.client.Client()
        self._try_set_timeout()
        self.client.connect(self.ip, self.rack, self.slot)
        if not self.is_connected():
            raise RuntimeError("PLC连接失败：检查 IP、网线、PLC PUT/GET、Rack/Slot。")

    def _try_set_timeout(self):
        if not self.client or not self.snap7:
            return
        try:
            parameter = getattr(getattr(self.snap7, "types", object), "Parameter", None)
            if parameter and hasattr(parameter, "RecvTimeout"):
                self.client.set_param(parameter.RecvTimeout, self.timeout_ms)
            if parameter and hasattr(parameter, "SendTimeout"):
                self.client.set_param(parameter.SendTimeout, self.timeout_ms)
        except Exception:
            pass

    def disconnect(self):
        if not self.client:
            return
        try:
            self.client.disconnect()
        finally:
            self.client = None

    def is_connected(self) -> bool:
        if not self.client:
            return False
        try:
            return bool(self.client.get_connected())
        except Exception:
            return False

    def read_bytes(self, db_number: int, offset: int, length: int) -> bytes:
        if not self.client or not self.is_connected():
            raise RuntimeError("PLC未连接")
        return bytes(self.client.db_read(db_number, offset, length))

    def read_int(self, db_number: int, offset: int) -> int:
        raw = self.read_bytes(db_number, offset, 2)
        if self.snap7_util:
            return int(self.snap7_util.get_int(raw, 0))
        return int.from_bytes(raw, byte_order="big", signed=True)

    def read_snapshot(
        self,
        barcode: S7BarcodeAddress,
        parts_ok_db: int,
        parts_ok_offset: int,
        parts_ok_type: str = "int",
    ) -> S7Snapshot:
        if parts_ok_type.lower() != "int":
            raise ValueError("当前仅支持 PARTS_OK 类型 int")
        parts_ok = self.read_int(parts_ok_db, parts_ok_offset)
        raw = self.read_bytes(barcode.db_number, barcode.offset, barcode.length)
        barcode_text, barcode_hex = parse_barcode(raw, barcode.encoding, barcode.strip_null, barcode.strip_space)
        return S7Snapshot(parts_ok, barcode_text, barcode_hex)


# Backward-friendly alias for the standalone test tool.
S7ClientWrapper = S7PlcClient
