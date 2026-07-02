from dataclasses import dataclass
from time import monotonic, sleep
from typing import Callable, Dict


WRITE_ONE_OFFSETS = {0, 4, 8}
VERIFY_WARNING = (
    "未读回 1，可能写入失败或 PLC 已快速复位，请结合 PLC 在线监控确认。"
)


@dataclass
class MagnetAddresses:
    barcode_ok: int = 0
    cylinder_clamped: int = 2
    screw_complete: int = 4
    magnet_complete: int = 6
    mes_read_done: int = 8
    left_flux: int = 10
    left_polarity: int = 14
    left_result: int = 16
    right_flux: int = 18
    right_polarity: int = 22
    right_result: int = 24


@dataclass
class MagnetConfig:
    db_number: int = 221
    poll_interval_ms: int = 800
    timeout_seconds: float = 30.0
    write_verify_retry_count: int = 3
    write_verify_interval_ms: int = 100
    addresses: MagnetAddresses = None

    def __post_init__(self):
        if self.addresses is None:
            self.addresses = MagnetAddresses()


def format_word(value: int) -> str:
    value = int(value) & 0xFFFF
    return f"{value} / 16#{value:04X}"


def evaluate_magnet_result(left_result: int, right_result: int) -> str:
    if left_result == 1 and right_result == 1:
        return "OK"
    if left_result == 0 or right_result == 0:
        return "NG"
    return "UNKNOWN"


class MagnetFlowController:
    def __init__(
        self,
        client,
        config: MagnetConfig,
        log: Callable[[str], None] = None,
        sleep_func: Callable[[float], None] = sleep,
        monotonic_func: Callable[[], float] = monotonic,
        cancelled: Callable[[], bool] = None,
    ):
        self.client = client
        self.config = config
        self.log = log or (lambda message: None)
        self.sleep = sleep_func
        self.monotonic = monotonic_func
        self.cancelled = cancelled or (lambda: False)

    def read_word(self, offset: int) -> int:
        value = self.client.read_word(self.config.db_number, offset)
        self.log(
            f"读取 DB{self.config.db_number}.DBW{offset} = {format_word(value)}"
        )
        return value

    def write_one_and_verify(self, offset: int) -> Dict:
        if offset not in WRITE_ONE_OFFSETS:
            raise ValueError("MES只允许向DBW0、DBW4、DBW8写入整数1")
        self.client.write_word(self.config.db_number, offset, 1)
        self.log(f"写 DB{self.config.db_number}.DBW{offset} = 1")
        values = []
        for attempt in range(1, self.config.write_verify_retry_count + 1):
            value = self.client.read_word(self.config.db_number, offset)
            values.append(value)
            self.log(
                f"第{attempt}次读回 DB{self.config.db_number}.DBW{offset} = {value}"
            )
            if value == 1:
                self.log(f"DBW{offset} 写入确认成功")
                return {
                    "confirmed": True,
                    "attempts": attempt,
                    "values": values,
                    "message": f"DBW{offset} 写入确认成功",
                }
            if attempt < self.config.write_verify_retry_count:
                self.sleep(self.config.write_verify_interval_ms / 1000.0)
        self.log(VERIFY_WARNING)
        return {
            "confirmed": False,
            "attempts": len(values),
            "values": values,
            "message": VERIFY_WARNING,
        }

    def wait_word(
        self,
        offset: int,
        expected: int,
        success_message: str,
        timeout_message: str,
    ) -> Dict:
        deadline = self.monotonic() + self.config.timeout_seconds
        while self.monotonic() <= deadline:
            if self.cancelled():
                return {"ok": False, "cancelled": True, "message": "操作已取消"}
            value = self.read_word(offset)
            if value == expected:
                self.log(success_message)
                return {"ok": True, "value": value, "message": success_message}
            self.sleep(max(self.config.poll_interval_ms, 50) / 1000.0)
        self.log(timeout_message)
        return {"ok": False, "timeout": True, "message": timeout_message}

    def read_all(self, flux_mode: str = "REAL") -> Dict:
        address = self.config.addresses
        values = {
            "barcode_ok": self.read_word(address.barcode_ok),
            "cylinder_clamped": self.read_word(address.cylinder_clamped),
            "screw_complete": self.read_word(address.screw_complete),
            "magnet_complete": self.read_word(address.magnet_complete),
            "mes_read_done": self.read_word(address.mes_read_done),
            "left_polarity": self.read_word(address.left_polarity),
            "left_result": self.read_word(address.left_result),
            "right_polarity": self.read_word(address.right_polarity),
            "right_result": self.read_word(address.right_result),
        }
        if flux_mode.upper() == "DWORD":
            values["left_flux"] = self.client.read_dword(
                self.config.db_number, address.left_flux
            )
            values["right_flux"] = self.client.read_dword(
                self.config.db_number, address.right_flux
            )
        else:
            values["left_flux"] = self.client.read_real(
                self.config.db_number, address.left_flux
            )
            values["right_flux"] = self.client.read_real(
                self.config.db_number, address.right_flux
            )
        values["flux_mode"] = flux_mode.upper()
        values["overall_result"] = evaluate_magnet_result(
            values["left_result"], values["right_result"]
        )
        self.log(
            "左磁通量={:.4f}，左结果={}；右磁通量={:.4f}，右结果={}；判定={}".format(
                values["left_flux"],
                values["left_result"],
                values["right_flux"],
                values["right_result"],
                values["overall_result"],
            )
        )
        return values

    def run_flow(self, flux_mode: str = "REAL") -> Dict:
        address = self.config.addresses
        steps = []
        first = self.write_one_and_verify(address.barcode_ok)
        steps.append(("write_dbw0", first))
        if not first["confirmed"]:
            return {"ok": False, "stage": "write_dbw0", "steps": steps}

        clamped = self.wait_word(
            address.cylinder_clamped,
            1,
            "气缸夹紧成功。",
            "气缸夹紧超时。",
        )
        steps.append(("wait_dbw2", clamped))
        if not clamped["ok"]:
            return {"ok": False, "stage": "wait_dbw2", "steps": steps}

        screw = self.write_one_and_verify(address.screw_complete)
        steps.append(("write_dbw4", screw))
        if not screw["confirmed"]:
            return {"ok": False, "stage": "write_dbw4", "steps": steps}

        magnet_done = self.wait_word(
            address.magnet_complete,
            1,
            "磁吸检测完成。",
            "磁吸检测超时。",
        )
        steps.append(("wait_dbw6", magnet_done))
        if not magnet_done["ok"]:
            return {"ok": False, "stage": "wait_dbw6", "steps": steps}

        values = self.read_all(flux_mode)
        steps.append(("read_result", values))
        if values["overall_result"] != "OK":
            self.log("磁吸检测 NG，不通知解锁")
            return {
                "ok": False,
                "stage": "magnet_ng",
                "values": values,
                "steps": steps,
            }

        unlock = self.write_one_and_verify(address.mes_read_done)
        steps.append(("write_dbw8", unlock))
        if not unlock["confirmed"]:
            return {"ok": False, "stage": "write_dbw8", "steps": steps}
        self.log("流程完成，已通知 PLC 解锁")
        return {
            "ok": True,
            "stage": "completed",
            "values": values,
            "steps": steps,
        }
