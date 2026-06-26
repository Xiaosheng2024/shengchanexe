from dataclasses import dataclass, field
from typing import List, Optional


SCAN = "扫码"
SCREW = "螺丝"
PLC = "PLC接收"


@dataclass
class ProcessStep:
    name: str
    step_type: str
    required_count: int = 0
    barcode_start: int = 1
    barcode_end: int = 7
    expected_content: str = ""
    is_main_barcode: bool = False
    plc_ip: str = "10.162.86.65"
    plc_rack: int = 0
    plc_slot: int = 1
    plc_barcode_db: int = 201
    plc_barcode_offset: int = 800
    plc_barcode_length: int = 40
    plc_barcode1_db: Optional[int] = None
    plc_barcode1_offset: Optional[int] = None
    plc_barcode1_length: Optional[int] = None
    plc_barcode2_db: int = 201
    plc_barcode2_offset: int = 840
    plc_barcode2_length: int = 40
    plc_parts_ok_db: int = 221
    plc_parts_ok_offset: int = 358
    plc_parts_ok_type: str = "int"
    plc_trigger_mode: str = "barcode_changed_then_parts_ok_increment"
    plc_use_barcode_index: int = 1
    plc_barcode_encoding: str = "ascii"
    plc_barcode_strip_null: bool = True
    plc_barcode_strip_space: bool = True
    plc_timeout_seconds: int = 3
    plc_poll_interval_ms: int = 500
    plc_barcode_wait_ok_timeout_seconds: int = 30
    completed_count: int = 0
    done: bool = False

    def __post_init__(self):
        if self.plc_barcode1_db is not None:
            self.plc_barcode_db = self.plc_barcode1_db
        if self.plc_barcode1_offset is not None:
            self.plc_barcode_offset = self.plc_barcode1_offset
        if self.plc_barcode1_length is not None:
            self.plc_barcode_length = self.plc_barcode1_length
        self.plc_barcode1_db = self.plc_barcode_db
        self.plc_barcode1_offset = self.plc_barcode_offset
        self.plc_barcode1_length = self.plc_barcode_length

    def reset(self):
        self.completed_count = 0
        self.done = False

    @property
    def display_status(self) -> str:
        if self.step_type == SCREW:
            if self.done:
                return f"{self.name}（已完成{self.required_count}/{self.required_count}）"
            return f"{self.name}（{self.completed_count}/{self.required_count}）"
        if self.done:
            return f"{self.name}（已完成）"
        return self.name


@dataclass
class ProductConfig:
    name: str
    steps: List[ProcessStep] = field(default_factory=list)

    def reset(self):
        for step in self.steps:
            step.reset()


@dataclass
class StationConfig:
    name: str
    product: ProductConfig


@dataclass
class ProjectConfig:
    name: str
    stations: List[StationConfig] = field(default_factory=list)
