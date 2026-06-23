from dataclasses import dataclass, field
from typing import List


SCAN = "扫码"
SCREW = "螺丝"


@dataclass
class ProcessStep:
    name: str
    step_type: str
    required_count: int = 0
    barcode_start: int = 1
    barcode_end: int = 7
    expected_content: str = ""
    is_main_barcode: bool = False
    completed_count: int = 0
    done: bool = False

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
