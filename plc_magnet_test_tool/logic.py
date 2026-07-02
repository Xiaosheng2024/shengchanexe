from dataclasses import dataclass
from time import monotonic, sleep
from typing import Callable, Dict


WRITE_ONE_OFFSETS = {0, 4, 8}
VERIFY_WARNING = (
    "未读回 1，可能写入失败或 PLC 已快速复位，请结合 PLC 在线监控确认。"
)
DB_ACCESS_GUIDANCE = (
    "PLC连接成功，但DB读取失败。S7-1200请检查 PUT/GET 是否开启、"
    "DB221 是否关闭优化块访问、DB221 是否已下载、DB号是否正确。"
)
REAL_ACCESS_GUIDANCE = (
    "Word读取成功，REAL读取失败，请检查 DBD10 地址、DB长度、REAL类型。"
)
DB_LENGTH_GUIDANCE = "DB221 块长度不足或外部访问失败。"

POINT_DEFINITIONS = (
    ("barcode_ok", "barcode_ok", "DBW", "WORD", 2),
    ("cylinder_clamped", "cylinder_clamped", "DBW", "WORD", 2),
    ("screw_complete", "screw_complete", "DBW", "WORD", 2),
    ("magnet_complete", "magnet_complete", "DBW", "WORD", 2),
    ("mes_read_done", "mes_read_done", "DBW", "WORD", 2),
    ("left_flux", "left_flux", "DBD", "FLUX", 4),
    ("left_polarity", "left_polarity", "DBW", "WORD", 2),
    ("left_result", "left_result", "DBW", "WORD", 2),
    ("right_flux", "right_flux", "DBD", "FLUX", 4),
    ("right_polarity", "right_polarity", "DBW", "WORD", 2),
    ("right_result", "right_result", "DBW", "WORD", 2),
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

    def _point_definition(self, key: str):
        for definition in POINT_DEFINITIONS:
            if definition[0] == key:
                return definition
        raise ValueError(f"未知读取点：{key}")

    def _read_failure_text(
        self,
        address_label: str,
        length: int,
        exc: Exception,
    ) -> str:
        return (
            f"读取失败 PLC IP={getattr(self.client, 'ip', '未知')} "
            f"Rack={getattr(self.client, 'rack', '未知')} "
            f"Slot={getattr(self.client, 'slot', '未知')} "
            f"DB={self.config.db_number} 地址={address_label} "
            f"读取长度={length} 错误原文={exc}"
        )

    def read_point(self, key: str, flux_mode: str = "REAL") -> Dict:
        _, address_attr, prefix, point_type, length = self._point_definition(key)
        offset = int(getattr(self.config.addresses, address_attr))
        address_label = f"DB{self.config.db_number}.{prefix}{offset}"
        try:
            if point_type == "WORD":
                value = self.client.read_word(self.config.db_number, offset)
                display_value = format_word(value)
            elif flux_mode.upper() == "DWORD":
                value = self.client.read_dword(self.config.db_number, offset)
                display_value = str(value)
            else:
                value = self.client.read_real(self.config.db_number, offset)
                display_value = f"{value:.4f}"
            self.log(f"读取 {address_label} = {display_value}")
            return {
                "ok": True,
                "key": key,
                "value": value,
                "address": address_label,
                "length": length,
                "flux_mode": flux_mode.upper(),
            }
        except Exception as exc:
            failure = self._read_failure_text(address_label, length, exc)
            self.log(failure)
            guidance = DB_ACCESS_GUIDANCE if key == "barcode_ok" else ""
            if key == "left_flux":
                guidance = REAL_ACCESS_GUIDANCE
            if guidance:
                self.log(guidance)
            return {
                "ok": False,
                "key": key,
                "address": address_label,
                "length": length,
                "error": str(exc),
                "message": guidance or failure,
                "flux_mode": flux_mode.upper(),
            }

    def precheck_db_length(self) -> Dict:
        address_label = f"DB{self.config.db_number}.DBB0-25"
        try:
            raw = self.client.read_bytes(self.config.db_number, 0, 26)
            if len(raw) < 26:
                raise ValueError(f"实际只读取到 {len(raw)} 字节")
            self.log(
                f"DB长度预检成功 PLC IP={getattr(self.client, 'ip', '未知')} "
                f"Rack={getattr(self.client, 'rack', '未知')} "
                f"Slot={getattr(self.client, 'slot', '未知')} "
                f"DB={self.config.db_number} 地址={address_label} 读取长度=26"
            )
            return {
                "ok": True,
                "address": address_label,
                "length": len(raw),
                "message": f"DB{self.config.db_number} 长度预检成功，可读取0-25字节。",
            }
        except Exception as exc:
            failure = self._read_failure_text(address_label, 26, exc)
            self.log(failure)
            self.log(DB_LENGTH_GUIDANCE)
            return {
                "ok": False,
                "address": address_label,
                "length": 26,
                "error": str(exc),
                "message": DB_LENGTH_GUIDANCE,
            }

    def read_all_diagnostic(self, flux_mode: str = "REAL") -> Dict:
        values = {}
        errors = {}
        for key, _, _, _, _ in POINT_DEFINITIONS:
            result = self.read_point(key, flux_mode)
            if result["ok"]:
                values[key] = result["value"]
            else:
                errors[key] = {
                    "error": result["error"],
                    "address": result["address"],
                    "length": result["length"],
                }

        values["flux_mode"] = flux_mode.upper()
        if "left_result" in values and "right_result" in values:
            values["overall_result"] = evaluate_magnet_result(
                values["left_result"],
                values["right_result"],
            )
        else:
            values["overall_result"] = "UNKNOWN"

        guidance = ""
        if "barcode_ok" in errors:
            guidance = DB_ACCESS_GUIDANCE
        elif "left_flux" in errors and "barcode_ok" in values:
            guidance = REAL_ACCESS_GUIDANCE
        if guidance:
            self.log(guidance)
        values["read_errors"] = errors
        values["diagnostic_message"] = guidance
        return values

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
