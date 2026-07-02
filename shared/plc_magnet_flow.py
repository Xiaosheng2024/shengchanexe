from dataclasses import dataclass
import struct
from time import monotonic, sleep
from typing import Callable, Dict


@dataclass
class PlcMagnetConfig:
    plc_enabled: bool = True
    plc_ip: str = "192.168.111.50"
    plc_rack: int = 0
    plc_slot: int = 1
    plc_db: int = 221
    plc_poll_interval_ms: int = 300
    plc_timeout_seconds: int = 30
    barcode_ok_offset: int = 0
    cylinder_clamped_offset: int = 2
    screw_complete_offset: int = 4
    magnet_complete_offset: int = 6
    mes_read_done_offset: int = 8
    left_flux_offset: int = 10
    left_polarity_offset: int = 14
    left_result_offset: int = 16
    right_flux_offset: int = 18
    right_polarity_offset: int = 22
    right_result_offset: int = 24
    ok_value: int = 1
    read_block_start: int = 0
    read_block_size: int = 26
    write_verify_retry_count: int = 3
    write_verify_interval_ms: int = 100

    @classmethod
    def from_dict(cls, values):
        source = dict(values or {})
        defaults = cls()
        return cls(
            **{
                key: source.get(key, getattr(defaults, key))
                for key in cls.__dataclass_fields__
            }
        )


def parse_plc_magnet_block(raw: bytes, config: PlcMagnetConfig) -> Dict:
    data = bytes(raw)
    start = int(config.read_block_start)

    def point(offset, length):
        relative = int(offset) - start
        if relative < 0 or relative + length > len(data):
            raise ValueError(
                f"DB{config.plc_db}数据长度不足，无法解析offset={offset}"
            )
        return data[relative:relative + length]

    def word(offset):
        return int.from_bytes(point(offset, 2), "big", signed=False)

    def real(offset):
        return float(struct.unpack(">f", point(offset, 4))[0])

    return {
        "left_flux": real(config.left_flux_offset),
        "left_polarity": word(config.left_polarity_offset),
        "left_result": word(config.left_result_offset),
        "right_flux": real(config.right_flux_offset),
        "right_polarity": word(config.right_polarity_offset),
        "right_result": word(config.right_result_offset),
        "raw_hex": data.hex(" ").upper(),
    }


class PlcMagnetFlowController:
    def __init__(
        self,
        client,
        config: PlcMagnetConfig,
        progress: Callable[[str, Dict], None] = None,
        cancelled: Callable[[], bool] = None,
        sleep_func: Callable[[float], None] = sleep,
        monotonic_func: Callable[[], float] = monotonic,
    ):
        self.client = client
        self.config = config
        self.progress = progress or (lambda stage, data: None)
        self.cancelled = cancelled or (lambda: False)
        self.sleep = sleep_func
        self.monotonic = monotonic_func

    def emit(self, stage, **data):
        self.progress(stage, data)

    def ensure_not_cancelled(self):
        if self.cancelled():
            raise RuntimeError("PLC磁通检测已取消")

    def write_one_and_verify(self, offset: int, stage: str):
        self.ensure_not_cancelled()
        self.client.write_word(self.config.plc_db, offset, 1)
        self.emit(stage, status="已写入1，正在读回确认", value=1)
        for attempt in range(1, self.config.write_verify_retry_count + 1):
            value = self.client.read_word(self.config.plc_db, offset)
            if value == 1:
                self.emit(
                    stage,
                    status="写入并读回确认成功",
                    value=value,
                    attempt=attempt,
                )
                return
            if attempt < self.config.write_verify_retry_count:
                self.sleep(self.config.write_verify_interval_ms / 1000.0)
        raise RuntimeError(
            f"DBW{offset}（{stage}）写入失败或读回不是1"
        )

    def wait_word(self, offset: int, stage: str, timeout_message: str):
        deadline = self.monotonic() + self.config.plc_timeout_seconds
        while self.monotonic() <= deadline:
            self.ensure_not_cancelled()
            value = self.client.read_word(self.config.plc_db, offset)
            self.emit(stage, status="等待中", value=value)
            if value == self.config.ok_value:
                self.emit(stage, status="完成", value=value)
                return
            self.sleep(max(self.config.plc_poll_interval_ms, 50) / 1000.0)
        raise TimeoutError(timeout_message)

    def run(self):
        if not self.config.plc_enabled:
            raise RuntimeError("PLC磁通检测工序未启用")
        if self.config.read_block_size < 26:
            raise ValueError("DB221原始块读取长度不能小于26字节")
        started_at = self.monotonic()
        self.client.connect()
        try:
            self.emit("connection", status="已连接", ip=self.config.plc_ip)
            self.write_one_and_verify(
                self.config.barcode_ok_offset,
                "barcode_ok",
            )
            self.wait_word(
                self.config.cylinder_clamped_offset,
                "cylinder_clamped",
                "气缸夹紧超时，请检查 PLC / 气缸 / 夹紧信号。",
            )
            self.write_one_and_verify(
                self.config.screw_complete_offset,
                "screw_complete",
            )
            self.wait_word(
                self.config.magnet_complete_offset,
                "magnet_complete",
                "磁通量检测完成信号超时，请检查 PLC 磁通检测流程。",
            )
            self.ensure_not_cancelled()
            raw = self.client.read_bytes(
                self.config.plc_db,
                self.config.read_block_start,
                self.config.read_block_size,
            )
            if len(raw) < self.config.read_block_size:
                raise RuntimeError(
                    f"DB221块长度不足：请求{self.config.read_block_size}字节，"
                    f"实际{len(raw)}字节"
                )
            values = parse_plc_magnet_block(raw, self.config)
            self.emit("magnet_result", status="已读取", **values)
            passed = (
                values["left_result"] == self.config.ok_value
                and values["right_result"] == self.config.ok_value
            )
            if not passed:
                return {
                    "ok": False,
                    "result": "NG",
                    "error_message": "左右磁通判定未全部合格",
                    **values,
                }
            self.write_one_and_verify(
                self.config.mes_read_done_offset,
                "mes_read_done",
            )
            return {
                "ok": True,
                "result": "OK",
                "elapsed_seconds": self.monotonic() - started_at,
                **values,
            }
        finally:
            self.client.disconnect()
