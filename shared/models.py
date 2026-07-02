from dataclasses import dataclass, field
from typing import List, Optional


SCAN = "扫码"
SCREW = "螺丝"
PLC = "PLC接收"
PLC_MAGNET = "plc_magnet_check"
PLC_MAGNET_LEGACY = "PLC磁通检测获取"
BARCODE_SWITCH = "主条码切换"
MATERIAL_BIND = "子物料绑定"


def normalize_step_type(value: str) -> str:
    if value == PLC_MAGNET_LEGACY:
        return PLC_MAGNET
    return value


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
    plc_magnet_config: dict = field(default_factory=dict)
    step_id: Optional[int] = None
    switch_require_old: bool = True
    switch_require_new: bool = True
    switch_set_current: bool = True
    switch_disable_old: bool = True
    bind_child_project_id: Optional[int] = None
    bind_child_material_type: str = ""
    bind_child_route: str = ""
    bind_required_count: int = 1
    bind_required_station_ids: List[int] = field(default_factory=list)
    bind_require_parent_switch: bool = True
    bind_allow_duplicate: bool = False
    bind_allow_unbind: bool = False
    completed_count: int = 0
    done: bool = False

    def __post_init__(self):
        self.step_type = normalize_step_type(self.step_type)
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
    id: Optional[int] = None
    route_name: str = "A主线"
    route_order: int = 0
    station_role: str = "普通工位"
    material_type: str = ""


@dataclass
class ProjectConfig:
    name: str
    stations: List[StationConfig] = field(default_factory=list)
    id: Optional[int] = None
    material_code: str = ""
    product_type: str = ""
