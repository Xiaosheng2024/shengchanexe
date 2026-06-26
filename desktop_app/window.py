import configparser
import socket
import shutil
import subprocess
import json
import logging
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from time import monotonic
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import QDateTime, QMetaObject, QThread, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop_app.tool_worker import ToolPollConfig, ToolPollWorker
from desktop_app.plc_worker import PlcPollConfig, PlcPollWorker
from shared.models import ProcessStep, ProductConfig, ProjectConfig, StationConfig, PLC, SCAN, SCREW


APP_VERSION = "v0.8.1"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    filename=str(LOG_DIR / "app.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "yes", "是")


class QualityControlWindow(QMainWindow):
    tool_worker_write_requested = pyqtSignal(int, int)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"生产工艺过程质量控制系统 {APP_VERSION}")
        self.resize(1280, 820)

        self.projects = self.default_projects()
        self.current_project: ProjectConfig = self.projects[0]
        self.current_station: StationConfig = self.current_project.stations[0]
        self.products = [station.product for station in self.current_project.stations]
        self.current_product: ProductConfig = self.current_station.product
        self.current_step_index = 0
        self.online_mode = False
        self.is_switching_station = False
        self.current_project_id = self.current_project.name
        self.current_station_id = self.current_station.name
        self.station_session_id = None
        self.station_config_loaded = True
        self.current_barcode = ""
        self.production_enabled = True
        self.screw_blocks: List[QLabel] = []
        self.warning_dialogs: List[QMessageBox] = []
        self.finished_part_count = 0
        self.scan_error_count = 0
        self.history_records = []
        self.step_started_at = datetime.now()
        self.settings_dialog: Optional[QDialog] = None
        self.history_dialog: Optional[QDialog] = None
        self.tool_settings_dialog: Optional[QDialog] = None
        self.local_device_dialog: Optional[QDialog] = None
        self.app_config_path = Path(__file__).resolve().parent.parent / "config.ini"
        self.last_voice_step_key = None
        self.say_command = shutil.which("say")
        self.tool_thread: Optional[QThread] = None
        self.tool_worker: Optional[ToolPollWorker] = None
        self.plc_thread: Optional[QThread] = None
        self.plc_worker: Optional[PlcPollWorker] = None
        self.plc_worker_generation = 0
        self.tool_worker_generation = 0
        self.plc_last_main_barcode = ""
        self.plc_last_parts_ok: Optional[int] = None
        self.plc_pending_main_barcode = ""
        self.plc_pending_barcode_time: Optional[datetime] = None
        self.plc_waiting_parts_ok = False
        self.station_session_acquired = False
        self.station_session_client_id = self.load_station_session_client_id()
        self.station_heartbeat_timer = QTimer(self)
        self.station_heartbeat_timer.setInterval(10000)
        self.station_heartbeat_timer.timeout.connect(self.send_station_session_heartbeat)
        self.processing_tool_signal = False
        self.waiting_tool_trigger_reset = False
        self.tool_ng_locked = False
        self.tool_ng_dialog_open = False
        self.tool_lock_state = None

        self.build_ui()
        self.load_tool_settings()
        self.load_local_device_settings()
        self.refresh_project_station_selectors()
        self.load_station(self.current_project.name, self.current_station.name)

    def default_projects(self) -> List[ProjectConfig]:
        stations = []
        for index in range(1, 10):
            if index == 1:
                steps = [ProcessStep("PLC接收主条码", PLC, is_main_barcode=True)]
            else:
                steps = [
                    ProcessStep("扫码A零件", SCAN, barcode_start=1, barcode_end=1, expected_content="A", is_main_barcode=True),
                    ProcessStep("扫码B零件条码", SCAN, barcode_start=1, barcode_end=1, expected_content="B"),
                    ProcessStep("打螺丝10颗", SCREW, required_count=10),
                    ProcessStep("扫码C零件", SCAN, barcode_start=1, barcode_end=1, expected_content="C"),
                ]
            stations.append(
                StationConfig(
                    f"工位{index}",
                    ProductConfig(
                        f"汽车前中控面板X04C 灰色 - 工位{index}",
                        steps,
                    ),
                )
            )
        return [ProjectConfig("默认项目", stations)]

    def build_ui(self):
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(12)
        self.setCentralWidget(root)

        title = QLabel("生产工艺过程质量控制系统")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 26px; font-weight: 700; padding: 8px;")
        root_layout.addWidget(title)

        mode_box = QGroupBox("运行模式 / 工位选择")
        mode_layout = QHBoxLayout(mode_box)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["离线模式", "在线模式"])
        self.mode_combo.currentTextChanged.connect(self.change_mode)
        self.api_base_input = QLineEdit("http://127.0.0.1:8000")
        self.api_base_input.setPlaceholderText("网页端接口地址")
        self.project_combo = QComboBox()
        self.project_combo.currentTextChanged.connect(self.on_project_selected)
        self.station_combo = QComboBox()
        self.station_combo.currentTextChanged.connect(self.on_station_selected)
        sync_projects_btn = QPushButton("同步项目工位")
        sync_projects_btn.clicked.connect(self.sync_online_projects)
        download_btn = QPushButton("下载配置")
        download_btn.clicked.connect(self.download_online_config)
        local_device_btn = QPushButton("本机设置")
        local_device_btn.clicked.connect(self.open_local_device_dialog)
        self.degraded_mode_checkbox = QCheckBox("降级模式（跳过上道工位校验）")
        self.degraded_mode_checkbox.setToolTip("勾选后不检查上道工位是否完成，只检测当前工位自己的工序")
        self.degraded_mode_checkbox.stateChanged.connect(self.change_degraded_mode)
        for label_text, widget in [
            ("模式", self.mode_combo),
            ("接口", self.api_base_input),
            ("项目", self.project_combo),
            ("工位", self.station_combo),
        ]:
            mode_layout.addWidget(QLabel(label_text))
            mode_layout.addWidget(widget)
        mode_layout.addWidget(sync_projects_btn)
        mode_layout.addWidget(download_btn)
        mode_layout.addWidget(local_device_btn)
        mode_layout.addStretch(1)
        mode_layout.addWidget(self.degraded_mode_checkbox)
        root_layout.addWidget(mode_box)

        content = QHBoxLayout()
        content.setSpacing(14)
        root_layout.addLayout(content, 1)

        self.step_list = QListWidget()
        self.step_list.setMinimumWidth(360)
        self.step_list.setStyleSheet(
            "QListWidget { font-size: 18px; }"
            "QListWidget::item { padding: 14px 10px; border-bottom: 1px solid #e5e7eb; }"
        )
        left_box = QGroupBox("工作区域展示")
        left_layout = QVBoxLayout(left_box)
        left_layout.addWidget(self.step_list)
        content.addWidget(left_box, 1)

        right_box = QGroupBox("当前生产状态")
        right_layout = QVBoxLayout(right_box)
        right_layout.setSpacing(14)
        content.addWidget(right_box, 2)

        self.product_label = QLabel()
        self.product_label.setStyleSheet("font-size: 28px; font-weight: 700; color: #111827;")
        right_layout.addWidget(self.product_label)

        self.current_step_label = QLabel()
        self.current_step_label.setStyleSheet("font-size: 22px; color: #2563eb;")
        right_layout.addWidget(self.current_step_label)

        self.main_barcode_label = QLabel("当前主条码：未扫描")
        self.main_barcode_label.setAlignment(Qt.AlignCenter)
        self.main_barcode_label.setStyleSheet(
            "font-size: 24px; font-weight: 700; padding: 14px;"
            "background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; color: #1d4ed8;"
        )
        right_layout.addWidget(self.main_barcode_label)

        stats_row = QHBoxLayout()
        self.finished_count_label = QLabel("已生成零件数：0")
        self.scan_error_count_label = QLabel("扫码错误总数：0")
        for label in [self.finished_count_label, self.scan_error_count_label]:
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(
                "font-size: 22px; font-weight: 700; padding: 14px;"
                "background: #f3f4f6; border-radius: 8px; color: #111827;"
            )
            stats_row.addWidget(label)
        right_layout.addLayout(stats_row)

        scanner_row = QHBoxLayout()
        self.barcode_input = QLineEdit()
        self.barcode_input.setPlaceholderText("输入或扫码条码，按回车提交")
        self.barcode_input.setStyleSheet("font-size: 20px; padding: 10px;")
        self.barcode_input.returnPressed.connect(self.handle_scan)
        scan_btn = QPushButton("扫码确认")
        scan_btn.clicked.connect(self.handle_scan)
        scanner_row.addWidget(self.barcode_input, 1)
        scanner_row.addWidget(scan_btn)
        right_layout.addLayout(scanner_row)

        self.screw_box = QGroupBox("螺丝数量提示")
        self.screw_grid = QGridLayout(self.screw_box)
        self.screw_grid.setSpacing(16)
        self.screw_box.setMinimumHeight(260)
        right_layout.addWidget(self.screw_box, 1)

        action_row = QHBoxLayout()
        self.screw_ok_btn = QPushButton("模拟螺钉枪OK信号")
        self.screw_ok_btn.clicked.connect(self.handle_screw_ok)
        self.tool_admin_unlock_btn = QPushButton("管理员解锁")
        self.tool_admin_unlock_btn.setEnabled(False)
        self.tool_admin_unlock_btn.clicked.connect(self.reopen_tool_ng_unlock_dialog)
        reset_btn = QPushButton("重新开始当前产品")
        reset_btn.clicked.connect(self.reset_current_product)
        action_row.addWidget(self.screw_ok_btn)
        action_row.addWidget(self.tool_admin_unlock_btn)
        action_row.addWidget(reset_btn)
        right_layout.addLayout(action_row)

        self.tool_box = QGroupBox("螺钉枪TCP OK信号")
        tool_layout = QHBoxLayout(self.tool_box)
        tool_layout.setSpacing(8)
        self.tool_ip_input = QLineEdit("127.0.0.1")
        self.tool_ip_input.setPlaceholderText("设备IP")
        self.tool_ip_input.setFixedWidth(120)
        self.tool_port_input = QSpinBox()
        self.tool_port_input.setRange(1, 65535)
        self.tool_port_input.setValue(502)
        self.tool_port_input.setFixedWidth(60)
        self.tool_unit_input = QSpinBox()
        self.tool_unit_input.setRange(1, 247)
        self.tool_unit_input.setValue(1)
        self.tool_unit_input.setFixedWidth(50)
        self.tool_status_register_input = QSpinBox()
        self.tool_status_register_input.setRange(0, 65535)
        self.tool_status_register_input.setValue(100)
        self.tool_status_register_input.setFixedWidth(60)
        self.tool_ok_value_input = QSpinBox()
        self.tool_ok_value_input.setRange(0, 65535)
        self.tool_ok_value_input.setValue(2)
        self.tool_ok_value_input.setFixedWidth(60)
        self.tool_ng_value_input = QSpinBox()
        self.tool_ng_value_input.setRange(0, 65535)
        self.tool_ng_value_input.setValue(3)
        self.tool_ng_value_input.setFixedWidth(60)
        self.tool_trigger_register_input = QSpinBox()
        self.tool_trigger_register_input.setRange(0, 65535)
        self.tool_trigger_register_input.setValue(53)
        self.tool_trigger_register_input.setFixedWidth(60)
        self.tool_trigger_value_input = QSpinBox()
        self.tool_trigger_value_input.setRange(0, 65535)
        self.tool_trigger_value_input.setValue(1)
        self.tool_trigger_value_input.setFixedWidth(60)
        self.tool_trigger_reset_value_input = QSpinBox()
        self.tool_trigger_reset_value_input.setRange(0, 65535)
        self.tool_trigger_reset_value_input.setValue(0)
        self.tool_trigger_reset_value_input.setFixedWidth(60)
        self.tool_control_register_input = QSpinBox()
        self.tool_control_register_input.setRange(0, 65535)
        self.tool_control_register_input.setValue(4)
        self.tool_control_register_input.setFixedWidth(60)
        self.tool_lock_value_input = QSpinBox()
        self.tool_lock_value_input.setRange(0, 65535)
        self.tool_lock_value_input.setValue(2)
        self.tool_lock_value_input.setFixedWidth(60)
        self.tool_unlock_value_input = QSpinBox()
        self.tool_unlock_value_input.setRange(0, 65535)
        self.tool_unlock_value_input.setValue(1)
        self.tool_unlock_value_input.setFixedWidth(60)
        self.tool_direction_register_input = QSpinBox()
        self.tool_direction_register_input.setRange(0, 65535)
        self.tool_direction_register_input.setValue(54)
        self.tool_direction_register_input.setFixedWidth(60)
        self.tool_forward_value_input = QSpinBox()
        self.tool_forward_value_input.setRange(0, 65535)
        self.tool_forward_value_input.setValue(0)
        self.tool_forward_value_input.setFixedWidth(60)
        self.tool_reverse_value_input = QSpinBox()
        self.tool_reverse_value_input.setRange(0, 65535)
        self.tool_reverse_value_input.setValue(1)
        self.tool_reverse_value_input.setFixedWidth(60)
        self.tool_poll_interval_input = QSpinBox()
        self.tool_poll_interval_input.setRange(200, 5000)
        self.tool_poll_interval_input.setSingleStep(100)
        self.tool_poll_interval_input.setValue(800)
        self.tool_poll_interval_input.setFixedWidth(70)
        self.tool_timeout_input = QSpinBox()
        self.tool_timeout_input.setRange(1, 10)
        self.tool_timeout_input.setValue(1)
        self.tool_timeout_input.setFixedWidth(60)
        self.disable_tool_auto_listen_checkbox = QCheckBox("禁用螺钉枪自动监听")
        self.disable_tool_auto_listen_checkbox.setToolTip("现场临时保护：勾选后不启动螺钉枪后台监听，可用模拟OK按钮测试流程")
        self.tool_connect_btn = QPushButton("连接")
        self.tool_connect_btn.setFixedWidth(80)
        self.tool_connect_btn.clicked.connect(self.toggle_tool_connection)
        self.tool_disconnect_btn = QPushButton("断开")
        self.tool_disconnect_btn.setFixedWidth(80)
        self.tool_disconnect_btn.setEnabled(False)
        self.tool_disconnect_btn.clicked.connect(self.stop_tool_worker)
        self.tool_settings_btn = QPushButton("设置")
        self.tool_settings_btn.setFixedWidth(80)
        self.tool_settings_btn.clicked.connect(self.open_tool_settings_dialog)
        self.tool_enable_dedup_checkbox = QCheckBox("启用防重复触发")
        self.tool_enable_dedup_checkbox.setChecked(True)
        self.tool_verbose_log_checkbox = QCheckBox("显示详细通讯日志")
        self.tool_clear_trigger_when_reverse_checkbox = QCheckBox("反向触发时自动清53")
        self.tool_clear_trigger_when_reverse_checkbox.setChecked(True)
        self.tool_admin_password_input = QLineEdit("0000")
        self.tool_admin_password_input.setEchoMode(QLineEdit.Password)
        self.tool_admin_password_input.setFixedWidth(120)
        self.tool_status_label = QLabel("未连接")
        self.tool_status_label.setFixedWidth(90)
        self.tool_status_label.setAlignment(Qt.AlignCenter)
        self.tool_status_label.setStyleSheet("font-size: 16px; color: #6b7280;")
        main_tool_fields = [
            ("IP", self.tool_ip_input),
            ("端口", self.tool_port_input),
            ("站号", self.tool_unit_input),
            ("状态地址", self.tool_status_register_input),
            ("OK值", self.tool_ok_value_input),
            ("NG值", self.tool_ng_value_input),
        ]
        for label_text, widget in main_tool_fields:
            tool_layout.addWidget(QLabel(label_text))
            tool_layout.addWidget(widget)
        tool_layout.addWidget(self.tool_connect_btn)
        tool_layout.addWidget(self.tool_disconnect_btn)
        tool_layout.addWidget(self.tool_settings_btn)
        tool_layout.addWidget(self.disable_tool_auto_listen_checkbox)
        tool_layout.addWidget(QLabel("状态"))
        tool_layout.addWidget(self.tool_status_label)
        tool_layout.addStretch(1)
        right_layout.addWidget(self.tool_box)
        self.build_tool_settings_dialog()

        self.message_label = QLabel("等待第1工序条码进入")
        self.message_label.setStyleSheet("font-size: 18px; color: #374151;")
        right_layout.addWidget(self.message_label)
        right_layout.addStretch(1)

        window_row = QHBoxLayout()
        settings_btn = QPushButton("设置功能")
        settings_btn.clicked.connect(self.open_settings_dialog)
        history_btn = QPushButton("历史记录 / 统计报表")
        history_btn.clicked.connect(self.open_history_dialog)
        window_row.addStretch(1)
        window_row.addWidget(settings_btn)
        window_row.addWidget(history_btn)
        root_layout.addLayout(window_row)

        self.build_settings_dialog()
        self.build_local_device_dialog()

        self.setStyleSheet(
            "QGroupBox { font-size: 16px; font-weight: 600; border: 1px solid #d1d5db;"
            " border-radius: 8px; margin-top: 10px; padding: 12px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
            "QPushButton { font-size: 16px; padding: 9px 14px; }"
            "QListWidget::item:selected { background: #2563eb; color: white; }"
            "QTableWidget::item:selected { background: #2563eb; color: white; }"
        )

    def build_settings_dialog(self):
        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle("设置功能区")
        self.settings_dialog.resize(1160, 560)
        settings_layout = QHBoxLayout(self.settings_dialog)
        settings_layout.setSpacing(12)

        craft_box = QGroupBox("已添加工艺名称")
        craft_layout = QVBoxLayout(craft_box)
        self.product_list = QListWidget()
        self.product_list.setMinimumWidth(280)
        self.product_list.currentTextChanged.connect(self.load_product)
        self.product_list.setStyleSheet(
            "QListWidget { font-size: 16px; }"
            "QListWidget::item { padding: 10px; border-bottom: 1px solid #e5e7eb; }"
            "QListWidget::item:selected { background: #2563eb; color: white; }"
        )
        craft_layout.addWidget(self.product_list)
        settings_layout.addWidget(craft_box, 1)

        step_editor = QGroupBox("添加工序")
        step_editor_layout = QVBoxLayout(step_editor)
        settings_layout.addWidget(step_editor, 3)

        form = QFormLayout()
        self.product_combo = QComboBox()
        self.product_combo.currentTextChanged.connect(self.load_product)
        self.product_name_input = QLineEdit()
        save_product_btn = QPushButton("保存产品中文名称")
        save_product_btn.clicked.connect(self.save_product_name)
        new_product_btn = QPushButton("新增产品")
        new_product_btn.clicked.connect(self.add_product)
        name_row = QHBoxLayout()
        name_row.addWidget(self.product_name_input)
        name_row.addWidget(save_product_btn)
        name_row.addWidget(new_product_btn)
        form.addRow("选择产品", self.product_combo)
        form.addRow("产品中文名称维护", name_row)
        step_editor_layout.addLayout(form)

        self.step_table = QTableWidget(0, 6)
        self.step_table.setHorizontalHeaderLabels(
            ["工序名称", "功能", "螺丝数量", "截取起始位", "截取结束位", "检测内容"]
        )
        self.step_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.step_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.step_table.setStyleSheet("QTableWidget::item:selected { background: #2563eb; color: white; }")
        step_editor_layout.addWidget(self.step_table)

        edit_row = QHBoxLayout()
        add_scan_btn = QPushButton("添加扫码工序")
        add_scan_btn.clicked.connect(lambda: self.add_step(SCAN))
        add_screw_btn = QPushButton("添加螺丝工序")
        add_screw_btn.clicked.connect(lambda: self.add_step(SCREW))
        remove_btn = QPushButton("删除选中工序")
        remove_btn.clicked.connect(self.remove_selected_step)
        up_btn = QPushButton("上移工序")
        up_btn.clicked.connect(lambda: self.move_selected_step(-1))
        down_btn = QPushButton("下移工序")
        down_btn.clicked.connect(lambda: self.move_selected_step(1))
        save_steps_btn = QPushButton("保存工序参数配置")
        save_steps_btn.clicked.connect(self.save_steps_from_table)
        for btn in [add_scan_btn, add_screw_btn, remove_btn, up_btn, down_btn, save_steps_btn]:
            edit_row.addWidget(btn)
        step_editor_layout.addLayout(edit_row)

        self.product_combo.addItems([product.name for product in self.products])
        self.refresh_product_list()

    def change_mode(self, text: str):
        self.online_mode = text == "在线模式"
        self.station_config_loaded = not self.online_mode
        self.station_session_acquired = not self.online_mode
        self.recompute_production_enabled()
        self.message_label.setText("在线模式：请先下载配置并占用工位" if self.online_mode else "离线模式：使用本地配置")
        self.refresh_work_area()

    def change_degraded_mode(self):
        if self.degraded_mode_checkbox.isChecked():
            self.message_label.setText("降级模式已开启：不检查上道工位，只检测当前工位")
        else:
            self.message_label.setText("降级模式已关闭")

    def refresh_project_station_selectors(self):
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItems([project.name for project in self.projects])
        self.project_combo.setCurrentText(self.current_project.name)
        self.project_combo.blockSignals(False)
        self.refresh_station_selector()

    def refresh_station_selector(self):
        self.station_combo.blockSignals(True)
        self.station_combo.clear()
        self.station_combo.addItems([station.name for station in self.current_project.stations])
        self.station_combo.setCurrentText(self.current_station.name)
        self.station_combo.blockSignals(False)

    def on_project_selected(self, project_name: str):
        if not project_name:
            return
        if self.is_switching_station:
            return
        project = next((item for item in self.projects if item.name == project_name), None)
        if project is None:
            return
        self.current_project = project
        self.current_station = project.stations[0]
        self.refresh_station_selector()
        self.load_station(project.name, self.current_station.name)

    def on_station_selected(self, station_name: str):
        if not station_name or self.is_switching_station:
            return
        self.switch_station(self.current_project.name, station_name)

    def log_step_duration(self, step_name: str, start_time: float):
        duration = monotonic() - start_time
        if duration > 1:
            logging.warning("%s 耗时 %.2f 秒", step_name, duration)
        else:
            logging.info("%s 完成，耗时 %.2f 秒", step_name, duration)

    def switch_station(self, project_name: str, station_name: str, auto_download: bool = True):
        if self.is_switching_station:
            return
        old_project = self.current_project.name if self.current_project else ""
        old_station = self.current_station.name if self.current_station else ""
        logging.info("开始切换工位：%s/%s -> %s/%s", old_project, old_station, project_name, station_name)
        self.is_switching_station = True
        if hasattr(self, "station_combo"):
            self.station_combo.setEnabled(False)
        try:
            self.production_enabled = False
            self.station_session_acquired = False
            self.station_config_loaded = not self.online_mode
            self.stop_station_heartbeat()

            start = monotonic()
            self.stop_plc_worker()
            self.log_step_duration("停止 PLC worker", start)

            start = monotonic()
            self.try_lock_tool_nonblocking()
            self.stop_tool_worker()
            self.log_step_duration("停止螺钉枪 worker", start)

            start = monotonic()
            self.release_station_session()
            self.log_step_duration("release 旧工位", start)

            if not self.set_current_station(project_name, station_name):
                raise ValueError("未找到项目或工位")
            self.clear_station_runtime_state(update_table=True)

            if self.online_mode and auto_download:
                start = monotonic()
                if not self.download_config_for_current_station():
                    self.log_step_duration("下载新工位配置失败", start)
                    return
                self.log_step_duration("下载新工位配置", start)

                start = monotonic()
                if self.acquire_station_session():
                    self.log_step_duration("acquire 新工位", start)
                    self.message_label.setText("在线配置已下载，工位占用成功，可以开始生产。")
                    self.refresh_work_area()
                    self.prompt_current_step_start()
                    logging.info("切换完成：%s/%s", project_name, station_name)
                else:
                    self.log_step_duration("acquire 新工位失败", start)
                    self.disable_production("在线配置已下载，但当前工位被其他设备占用，禁止生产。请释放工位或选择其它工位。")
                    logging.warning("切换失败：新工位占用失败 %s/%s", project_name, station_name)
            else:
                self.recompute_production_enabled()
                self.refresh_work_area()
                if self.production_enabled:
                    self.prompt_current_step_start()
                logging.info("切换完成：%s/%s", project_name, station_name)
        except Exception as exc:
            self.production_enabled = False
            self.station_session_acquired = False
            self.recompute_production_enabled()
            logging.exception("切换失败：%s", exc)
            self.message_label.setText(f"切换工位失败：{exc}")
        finally:
            self.is_switching_station = False
            if hasattr(self, "station_combo"):
                self.station_combo.setEnabled(True)

    def load_station(self, project_name: str, station_name: str):
        self.set_current_station(project_name, station_name)
        self.clear_station_runtime_state(update_table=True)
        if self.online_mode:
            self.message_label.setText("请下载在线配置并申请工位占用后开始生产")

    def set_current_station(self, project_name: str, station_name: str) -> bool:
        project = next((item for item in self.projects if item.name == project_name), None)
        if project is None:
            return False
        station = next((item for item in project.stations if item.name == station_name), None)
        if station is None:
            return False
        self.current_project = project
        self.current_station = station
        self.current_project_id = getattr(project, "id", None) or project.name
        self.current_station_id = getattr(station, "id", None) or station.name
        self.current_product = station.product
        self.ensure_main_barcode(self.current_product, notify=True)
        self.products = [station.product for station in project.stations]
        if hasattr(self, "product_combo"):
            self.product_combo.blockSignals(True)
            self.product_combo.clear()
            self.product_combo.addItems([product.name for product in self.products])
            self.product_combo.setCurrentText(self.current_product.name)
            self.product_combo.blockSignals(False)
            self.product_name_input.setText(self.current_product.name)
            self.refresh_product_list()
        return True

    def clear_station_runtime_state(self, update_table: bool = False):
        self.station_session_id = None
        self.station_config_loaded = not self.online_mode
        self.station_session_acquired = not self.online_mode
        self.recompute_production_enabled()
        self.reset_current_product(update_table=update_table)

    def download_config_for_current_station(self) -> bool:
        project_name = self.current_project.name
        station_name = self.current_station.name
        try:
            data = self.api_get(f"/api/projects/{urllib.parse.quote(project_name)}/stations/{urllib.parse.quote(station_name)}/config")
            product = self.product_from_api(data)
        except Exception as exc:
            QMessageBox.warning(self, "下载配置失败", str(exc))
            self.station_config_loaded = False
            self.recompute_production_enabled()
            return False
        self.current_station.product = product
        self.current_product = product
        self.station_config_loaded = True
        self.reset_current_product(update_table=True)
        logging.info("在线配置已下载：%s/%s", project_name, station_name)
        return True

    def download_online_config(self):
        if not self.online_mode:
            self.message_label.setText("当前是离线模式，不需要下载配置")
            return
        project_name = self.project_combo.currentText().strip()
        station_name = self.station_combo.currentText().strip()
        if not project_name or not station_name:
            self.message_label.setText("请先选择项目和工位")
            return
        if self.is_switching_station:
            return
        self.switch_station(project_name, station_name, auto_download=True)

    def sync_online_projects(self):
        if not self.online_mode:
            self.message_label.setText("当前是离线模式，不需要同步项目工位")
            return
        try:
            data = self.api_get("/api/projects")
            projects = []
            for project_item in data.get("projects", []):
                stations = []
                for station_name in project_item.get("stations", []):
                    stations.append(
                        StationConfig(
                            station_name,
                            ProductConfig(
                                f"{project_item.get('name', '项目')} - {station_name}",
                                [ProcessStep("扫码首件条码", SCAN, is_main_barcode=True)],
                            ),
                        )
                    )
                if stations:
                    projects.append(ProjectConfig(project_item.get("name", "未命名项目"), stations))
        except Exception as exc:
            QMessageBox.warning(self, "同步失败", str(exc))
            return
        if not projects:
            QMessageBox.warning(self, "同步失败", "接口未返回项目工位")
            return
        self.projects = projects
        self.current_project = projects[0]
        self.current_station = projects[0].stations[0]
        self.refresh_project_station_selectors()
        self.load_station(self.current_project.name, self.current_station.name)
        self.message_label.setText("项目工位已同步，请选择工位后下载配置")

    def product_from_api(self, data: dict) -> ProductConfig:
        steps = []
        for item in data.get("steps", []):
            step_type = item.get("type", SCAN)
            steps.append(
                ProcessStep(
                    name=item.get("name", "未命名工序"),
                    step_type=step_type,
                    required_count=int(item.get("required_count", 0)),
                    barcode_start=int(item.get("barcode_start", 1)),
                    barcode_end=int(item.get("barcode_end", 7)),
                    expected_content=item.get("expected_content", ""),
                    is_main_barcode=as_bool(item.get("is_main_barcode", False)),
                    plc_ip=item.get("plc_ip", "10.162.86.65"),
                    plc_rack=int(item.get("plc_rack", 0)),
                    plc_slot=int(item.get("plc_slot", 1)),
                    plc_barcode_db=int(item.get("plc_barcode_db", item.get("plc_barcode1_db", 201))),
                    plc_barcode_offset=int(item.get("plc_barcode_offset", item.get("plc_barcode1_offset", 800))),
                    plc_barcode_length=int(item.get("plc_barcode_length", item.get("plc_barcode1_length", 40))),
                    plc_parts_ok_db=int(item.get("plc_parts_ok_db", 221)),
                    plc_parts_ok_offset=int(item.get("plc_parts_ok_offset", 358)),
                    plc_parts_ok_type=item.get("plc_parts_ok_type", "int"),
                    plc_trigger_mode=item.get("plc_trigger_mode", "barcode_changed_then_parts_ok_increment"),
                    plc_use_barcode_index=int(item.get("plc_use_barcode_index", 1)),
                    plc_barcode_encoding=item.get("plc_barcode_encoding", "ascii"),
                    plc_barcode_strip_null=as_bool(item.get("plc_barcode_strip_null", True), True),
                    plc_barcode_strip_space=as_bool(item.get("plc_barcode_strip_space", True), True),
                    plc_timeout_seconds=int(item.get("plc_timeout_seconds", 3)),
                    plc_poll_interval_ms=int(item.get("plc_poll_interval_ms", 500)),
                    plc_barcode_wait_ok_timeout_seconds=int(item.get("plc_barcode_wait_ok_timeout_seconds", 30)),
                )
            )
        if not steps:
            raise ValueError("接口未返回工序 steps")
        product = ProductConfig(data.get("product_name", self.current_product.name), steps)
        self.ensure_main_barcode(product, notify=True)
        return product

    def api_url(self, path: str) -> str:
        base = self.api_base_input.text().strip().rstrip("/")
        if not base:
            raise ValueError("网页端接口地址为空")
        return base + path

    def api_get(self, path: str) -> dict:
        with urllib.request.urlopen(self.api_url(path), timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def api_post(self, path: str, payload: dict) -> dict:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.api_url(path),
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8") or "{}")

    def load_station_session_client_id(self) -> str:
        config = configparser.ConfigParser()
        if self.app_config_path.exists():
            config.read(self.app_config_path, encoding="utf-8")
        if "LOCAL_DEVICE" not in config:
            config["LOCAL_DEVICE"] = {}
        client_id = config["LOCAL_DEVICE"].get("client_id", "").strip()
        if client_id:
            return client_id
        client_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:12]}"
        config["LOCAL_DEVICE"]["client_id"] = client_id
        with self.app_config_path.open("w", encoding="utf-8") as file:
            config.write(file)
        return client_id

    def recompute_production_enabled(self):
        self.production_enabled = (not self.online_mode) or (self.station_config_loaded and self.station_session_acquired)
        return self.production_enabled

    def production_disabled_message(self) -> str:
        if self.online_mode and not self.station_config_loaded:
            return "当前工位未下载在线配置，禁止生产"
        return "当前工位未占用成功，禁止生产"

    def ensure_production_enabled(self) -> bool:
        self.recompute_production_enabled()
        if self.production_enabled:
            return True
        message = self.production_disabled_message()
        self.message_label.setText(message)
        self.show_auto_close_warning("禁止生产", message)
        return False

    def disable_production(self, message: str):
        self.station_session_acquired = False
        self.recompute_production_enabled()
        self.stop_plc_worker()
        self.lock_tool()
        self.stop_tool_worker()
        self.barcode_input.setEnabled(False)
        self.screw_ok_btn.setEnabled(False)
        self.message_label.setText(message)
        self.show_auto_close_warning("禁止生产", message)

    def station_session_payload(self) -> dict:
        project_id = getattr(self.current_project, "id", None) or self.current_project.name
        station_id = getattr(self.current_station, "id", None) or self.current_station.name
        try:
            ip_address = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip_address = ""
        return {
            "project_id": project_id,
            "station_id": station_id,
            "project": self.current_project.name,
            "station": self.current_station.name,
            "client_id": self.station_session_client_id,
            "computer_name": socket.gethostname(),
            "ip_address": ip_address,
        }

    def acquire_station_session(self):
        if not self.online_mode:
            self.station_session_acquired = True
            self.recompute_production_enabled()
            return True
        try:
            data = self.api_post("/api/station-session/acquire", self.station_session_payload())
        except Exception as exc:
            self.station_session_acquired = False
            self.recompute_production_enabled()
            self.message_label.setText(f"工位占用申请失败：{exc}")
            return False
        self.station_session_acquired = bool(data.get("ok"))
        if not self.station_session_acquired:
            conflict = data.get("conflict") or {}
            message = (
                f"工位已被占用：项目 {self.current_project.name}，工位 {self.current_station.name}，"
                f"client_id {conflict.get('client_id', '')}，电脑 {conflict.get('computer_name', '')}，IP {conflict.get('ip_address', '')}，"
                f"最后心跳 {conflict.get('last_heartbeat_at', '')}"
            )
            self.message_label.setText(message)
            self.show_station_conflict_dialog(conflict, message)
        else:
            self.station_session_id = data.get("session_id")
            self.start_station_heartbeat()
        self.recompute_production_enabled()
        return self.station_session_acquired

    def release_station_session(self):
        if not self.online_mode:
            self.station_session_acquired = False
            self.station_session_id = None
            return
        try:
            self.api_post("/api/station-session/release", self.station_session_payload())
            logging.info("release 旧工位成功：%s/%s", self.current_project.name, self.current_station.name)
        except Exception as exc:
            logging.warning("release 旧工位失败，继续切换：%s", exc)
        self.station_session_acquired = False
        self.station_session_id = None
        self.recompute_production_enabled()
        self.stop_station_heartbeat()

    def stop_station_heartbeat(self):
        if self.station_heartbeat_timer.isActive():
            logging.info("停止 heartbeat")
        self.station_heartbeat_timer.stop()

    def start_station_heartbeat(self):
        if self.online_mode and self.station_session_acquired and not self.station_heartbeat_timer.isActive():
            self.station_heartbeat_timer.start()
            logging.info("启动 heartbeat")

    def send_station_session_heartbeat(self):
        if not self.online_mode or not self.station_session_acquired:
            return
        try:
            data = self.api_post("/api/station-session/heartbeat", self.station_session_payload())
        except Exception as exc:
            self.message_label.setText(f"工位占用心跳失败：{exc}")
            return
        if data.get("ok"):
            return
        self.station_session_acquired = False
        self.station_session_id = None
        self.recompute_production_enabled()
        self.stop_station_heartbeat()
        self.stop_plc_worker()
        self.stop_tool_worker()
        self.lock_tool()
        message = "当前工位占用已失效或被其他电脑接管，已停止生产"
        self.message_label.setText(message)
        self.show_auto_close_warning("工位占用失效", message)

    def ensure_station_session_for_production(self) -> bool:
        return self.ensure_production_enabled()

    def show_station_conflict_dialog(self, conflict: dict, message: str):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("工位占用冲突")
        detail = (
            f"{message}\n\n"
            f"项目：{self.current_project.name}\n"
            f"工位：{self.current_station.name}\n"
            f"占用电脑：{conflict.get('computer_name', '')}\n"
            f"client_id：{conflict.get('client_id', '')}\n"
            f"ip_address：{conflict.get('ip_address', '')}\n"
            f"last_heartbeat_at：{conflict.get('last_heartbeat_at', '')}\n"
            f"状态：{conflict.get('status', '')}"
        )
        dialog.setText(detail)
        back_btn = dialog.addButton("返回重新选择", QMessageBox.RejectRole)
        refresh_btn = dialog.addButton("刷新", QMessageBox.ActionRole)
        force_btn = dialog.addButton("管理员强制接管", QMessageBox.DestructiveRole)
        dialog.exec_()
        clicked = dialog.clickedButton()
        if clicked == refresh_btn:
            QTimer.singleShot(0, self.download_online_config)
        elif clicked == force_btn:
            QTimer.singleShot(0, self.force_acquire_station_session)
        elif clicked == back_btn:
            self.message_label.setText("请重新选择项目工位")

    def force_acquire_station_session(self):
        password, ok = self.prompt_admin_password("管理员强制接管工位")
        if not ok:
            return
        payload = self.station_session_payload()
        payload["admin_password"] = password
        try:
            data = self.api_post("/api/station-session/force-acquire", payload)
        except Exception as exc:
            QMessageBox.warning(self, "强制接管失败", str(exc))
            return
        self.station_session_acquired = bool(data.get("ok"))
        self.station_session_id = data.get("session_id")
        self.recompute_production_enabled()
        if self.production_enabled:
            self.start_station_heartbeat()
            self.message_label.setText("在线配置已下载，工位占用成功，可以开始生产。")
            self.refresh_work_area()
            self.prompt_current_step_start()
        else:
            self.disable_production("当前工位未占用成功，禁止生产")

    def prompt_admin_password(self, title: str):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("请输入管理员密码"))
        password_input = QLineEdit()
        password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(password_input)
        row = QHBoxLayout()
        ok_btn = QPushButton("确认")
        cancel_btn = QPushButton("取消")
        row.addStretch(1)
        row.addWidget(ok_btn)
        row.addWidget(cancel_btn)
        layout.addLayout(row)
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        password_input.returnPressed.connect(dialog.accept)
        accepted = dialog.exec_() == QDialog.Accepted
        return password_input.text(), accepted

    def open_settings_dialog(self):
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def open_history_dialog(self):
        if self.history_dialog is None:
            self.build_history_dialog()
        self.refresh_history_tables()
        self.history_dialog.show()
        self.history_dialog.raise_()
        self.history_dialog.activateWindow()

    def build_history_dialog(self):
        self.history_dialog = QDialog(self)
        self.history_dialog.setWindowTitle("历史记录 / 工序时间统计报表")
        self.history_dialog.resize(1100, 640)
        layout = QVBoxLayout(self.history_dialog)

        filter_row = QHBoxLayout()
        self.history_start_edit = QDateTimeEdit()
        self.history_start_edit.setCalendarPopup(True)
        self.history_start_edit.setDateTime(QDateTime.currentDateTime().addDays(-1))
        self.history_start_edit.dateTimeChanged.connect(self.refresh_history_tables)
        self.history_end_edit = QDateTimeEdit()
        self.history_end_edit.setCalendarPopup(True)
        self.history_end_edit.setDateTime(QDateTime.currentDateTime())
        self.history_end_edit.dateTimeChanged.connect(self.refresh_history_tables)
        self.history_barcode_input = QLineEdit()
        self.history_barcode_input.setPlaceholderText("输入条码搜索")
        self.history_barcode_input.textChanged.connect(self.refresh_history_tables)
        filter_row.addWidget(QLabel("开始时间"))
        filter_row.addWidget(self.history_start_edit)
        filter_row.addWidget(QLabel("结束时间"))
        filter_row.addWidget(self.history_end_edit)
        filter_row.addWidget(QLabel("条码"))
        filter_row.addWidget(self.history_barcode_input)
        refresh_btn = QPushButton("刷新查询")
        refresh_btn.clicked.connect(self.refresh_history_tables)
        filter_row.addWidget(refresh_btn)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        history_box = QGroupBox("历史记录")
        history_layout = QVBoxLayout(history_box)
        self.history_table = QTableWidget(0, 11)
        self.history_table.setHorizontalHeaderLabels(
            ["时间", "项目", "工位", "产品", "工序", "功能", "结果", "条码", "信号", "耗时秒", "说明"]
        )
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        history_layout.addWidget(self.history_table)
        layout.addWidget(history_box, 2)

        report_box = QGroupBox("工序时间统计报表")
        report_layout = QVBoxLayout(report_box)
        self.report_table = QTableWidget(0, 7)
        self.report_table.setHorizontalHeaderLabels(
            ["项目", "工位", "产品", "工序", "完成次数", "总耗时秒", "平均耗时秒"]
        )
        self.report_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.report_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        report_layout.addWidget(self.report_table)
        layout.addWidget(report_box, 1)

    def build_tool_settings_dialog(self):
        self.tool_settings_dialog = QDialog(self)
        self.tool_settings_dialog.setWindowTitle("螺钉枪高级设置")
        self.tool_settings_dialog.resize(560, 460)
        layout = QVBoxLayout(self.tool_settings_dialog)

        note = QLabel(
            "地址4控制螺钉枪锁定/解锁：\n"
            "- 地址4 = 2：锁定螺钉枪，禁止启动\n"
            "- 地址4 = 0 或 1：解锁螺钉枪，允许启动\n"
            "默认使用：锁定值 = 2，解锁值 = 1\n"
            "地址54控制方向：0=正向允许计数，1=反向不计数"
        )
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 15px; color: #374151; padding: 8px; background: #f3f4f6; border-radius: 6px;")
        layout.addWidget(note)

        form = QFormLayout()
        form.addRow("触发地址", self.tool_trigger_register_input)
        form.addRow("触发值", self.tool_trigger_value_input)
        form.addRow("触发复位值", self.tool_trigger_reset_value_input)
        form.addRow("锁定地址", self.tool_control_register_input)
        form.addRow("锁定值", self.tool_lock_value_input)
        form.addRow("解锁值", self.tool_unlock_value_input)
        form.addRow("方向地址", self.tool_direction_register_input)
        form.addRow("正向值", self.tool_forward_value_input)
        form.addRow("反向值", self.tool_reverse_value_input)
        form.addRow("反向触发是否自动清53", self.tool_clear_trigger_when_reverse_checkbox)
        form.addRow("轮询间隔ms", self.tool_poll_interval_input)
        form.addRow("通讯超时秒", self.tool_timeout_input)
        form.addRow("管理员密码", self.tool_admin_password_input)
        form.addRow("是否启用防重复触发", self.tool_enable_dedup_checkbox)
        form.addRow("是否显示详细通讯日志", self.tool_verbose_log_checkbox)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        save_btn = QPushButton("保存")
        cancel_btn = QPushButton("取消")
        default_btn = QPushButton("恢复默认")
        save_btn.clicked.connect(self.save_tool_settings_from_dialog)
        cancel_btn.clicked.connect(self.tool_settings_dialog.reject)
        default_btn.clicked.connect(self.restore_default_tool_settings)
        button_row.addStretch(1)
        button_row.addWidget(save_btn)
        button_row.addWidget(cancel_btn)
        button_row.addWidget(default_btn)
        layout.addLayout(button_row)

    def open_tool_settings_dialog(self):
        self.tool_settings_dialog.show()
        self.tool_settings_dialog.raise_()
        self.tool_settings_dialog.activateWindow()

    def restore_default_tool_settings(self):
        self.tool_trigger_register_input.setValue(53)
        self.tool_trigger_value_input.setValue(1)
        self.tool_trigger_reset_value_input.setValue(0)
        self.tool_control_register_input.setValue(4)
        self.tool_lock_value_input.setValue(2)
        self.tool_unlock_value_input.setValue(1)
        self.tool_direction_register_input.setValue(54)
        self.tool_forward_value_input.setValue(0)
        self.tool_reverse_value_input.setValue(1)
        self.tool_clear_trigger_when_reverse_checkbox.setChecked(True)
        self.tool_poll_interval_input.setValue(800)
        self.tool_timeout_input.setValue(1)
        self.tool_admin_password_input.setText("0000")
        self.tool_enable_dedup_checkbox.setChecked(True)
        self.tool_verbose_log_checkbox.setChecked(False)

    def load_tool_settings(self):
        if not self.app_config_path.exists():
            return
        config = configparser.ConfigParser()
        config.read(self.app_config_path, encoding="utf-8")
        if "TOOL" not in config:
            return
        tool = config["TOOL"]
        self.tool_ip_input.setText(tool.get("ip", self.tool_ip_input.text()))
        self.tool_port_input.setValue(tool.getint("port", fallback=self.tool_port_input.value()))
        self.tool_unit_input.setValue(tool.getint("unit_id", fallback=self.tool_unit_input.value()))
        self.tool_status_register_input.setValue(tool.getint("status_address", fallback=self.tool_status_register_input.value()))
        self.tool_ok_value_input.setValue(tool.getint("ok_value", fallback=self.tool_ok_value_input.value()))
        self.tool_ng_value_input.setValue(tool.getint("ng_value", fallback=self.tool_ng_value_input.value()))
        self.tool_trigger_register_input.setValue(tool.getint("trigger_address", fallback=self.tool_trigger_register_input.value()))
        self.tool_trigger_value_input.setValue(tool.getint("trigger_value", fallback=self.tool_trigger_value_input.value()))
        self.tool_trigger_reset_value_input.setValue(tool.getint("trigger_reset_value", fallback=self.tool_trigger_reset_value_input.value()))
        self.tool_control_register_input.setValue(tool.getint("lock_address", fallback=self.tool_control_register_input.value()))
        self.tool_lock_value_input.setValue(tool.getint("lock_value", fallback=self.tool_lock_value_input.value()))
        self.tool_unlock_value_input.setValue(tool.getint("unlock_value", fallback=self.tool_unlock_value_input.value()))
        self.tool_direction_register_input.setValue(tool.getint("direction_address", fallback=self.tool_direction_register_input.value()))
        self.tool_forward_value_input.setValue(tool.getint("forward_value", fallback=self.tool_forward_value_input.value()))
        self.tool_reverse_value_input.setValue(tool.getint("reverse_value", fallback=self.tool_reverse_value_input.value()))
        self.tool_clear_trigger_when_reverse_checkbox.setChecked(tool.getboolean("clear_trigger_when_reverse", fallback=True))
        self.tool_poll_interval_input.setValue(tool.getint("poll_interval_ms", fallback=self.tool_poll_interval_input.value()))
        self.tool_timeout_input.setValue(tool.getint("timeout_seconds", fallback=self.tool_timeout_input.value()))
        self.tool_admin_password_input.setText(tool.get("admin_unlock_password", self.tool_admin_password_input.text()))
        self.tool_enable_dedup_checkbox.setChecked(tool.getboolean("enable_dedup", fallback=True))
        self.tool_verbose_log_checkbox.setChecked(tool.getboolean("verbose_log", fallback=False))

    def save_tool_settings(self):
        config = configparser.ConfigParser()
        if self.app_config_path.exists():
            config.read(self.app_config_path, encoding="utf-8")
        if "TOOL" not in config:
            config["TOOL"] = {}
        config["TOOL"].update(
            {
                "ip": self.tool_ip_input.text().strip(),
                "port": str(self.tool_port_input.value()),
                "unit_id": str(self.tool_unit_input.value()),
                "status_address": str(self.tool_status_register_input.value()),
                "ok_value": str(self.tool_ok_value_input.value()),
                "ng_value": str(self.tool_ng_value_input.value()),
                "trigger_address": str(self.tool_trigger_register_input.value()),
                "trigger_value": str(self.tool_trigger_value_input.value()),
                "trigger_reset_value": str(self.tool_trigger_reset_value_input.value()),
                "lock_address": str(self.tool_control_register_input.value()),
                "lock_value": str(self.tool_lock_value_input.value()),
                "unlock_value": str(self.tool_unlock_value_input.value()),
                "direction_address": str(self.tool_direction_register_input.value()),
                "forward_value": str(self.tool_forward_value_input.value()),
                "reverse_value": str(self.tool_reverse_value_input.value()),
                "clear_trigger_when_reverse": str(self.tool_clear_trigger_when_reverse_checkbox.isChecked()).lower(),
                "poll_interval_ms": str(self.tool_poll_interval_input.value()),
                "timeout_seconds": str(self.tool_timeout_input.value()),
                "admin_unlock_password": self.tool_admin_password_input.text(),
                "enable_dedup": str(self.tool_enable_dedup_checkbox.isChecked()).lower(),
                "verbose_log": str(self.tool_verbose_log_checkbox.isChecked()).lower(),
            }
        )
        with self.app_config_path.open("w", encoding="utf-8") as file:
            config.write(file)

    def save_tool_settings_from_dialog(self):
        self.save_tool_settings()
        if self.is_tool_worker_running():
            message = "设置已保存，重新连接后生效"
        else:
            message = "螺钉枪高级设置已保存"
        self.message_label.setText(message)
        QMessageBox.information(self, "提示", message)
        self.tool_settings_dialog.accept()

    def build_local_device_dialog(self):
        self.local_device_dialog = QDialog(self)
        self.local_device_dialog.setWindowTitle("本机设备设置")
        self.local_device_dialog.resize(520, 360)
        layout = QVBoxLayout(self.local_device_dialog)
        note = QLabel("正式生产优先使用网页端工序配置；本机PLC覆盖只用于现场临时调试或网络变更应急。")
        note.setWordWrap(True)
        layout.addWidget(note)

        form = QFormLayout()
        self.local_mes_server_label = QLabel(self.api_base_input.text())
        self.local_project_station_label = QLabel(f"{self.current_project.name} / {self.current_station.name}")
        self.local_auto_sync_checkbox = QCheckBox("启动后允许手动同步网页端配置")
        self.local_auto_sync_checkbox.setChecked(True)
        self.local_plc_override_checkbox = QCheckBox("启用PLC本地覆盖")
        self.local_plc_ip_input = QLineEdit("10.162.86.65")
        self.local_plc_ip_input.setFixedWidth(160)
        self.local_plc_timeout_input = QSpinBox()
        self.local_plc_timeout_input.setRange(1, 30)
        self.local_plc_timeout_input.setValue(3)
        self.local_plc_poll_interval_input = QSpinBox()
        self.local_plc_poll_interval_input.setRange(200, 10000)
        self.local_plc_poll_interval_input.setSingleStep(100)
        self.local_plc_poll_interval_input.setValue(500)
        form.addRow("MES接口地址", self.local_mes_server_label)
        form.addRow("当前项目/工位", self.local_project_station_label)
        form.addRow("自动同步", self.local_auto_sync_checkbox)
        form.addRow("PLC本地覆盖", self.local_plc_override_checkbox)
        form.addRow("PLC覆盖IP", self.local_plc_ip_input)
        form.addRow("PLC超时秒", self.local_plc_timeout_input)
        form.addRow("PLC轮询ms", self.local_plc_poll_interval_input)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        save_btn = QPushButton("保存")
        cancel_btn = QPushButton("取消")
        save_btn.clicked.connect(self.save_local_device_settings_from_dialog)
        cancel_btn.clicked.connect(self.local_device_dialog.reject)
        button_row.addStretch(1)
        button_row.addWidget(save_btn)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)

    def open_local_device_dialog(self):
        self.local_mes_server_label.setText(self.api_base_input.text())
        self.local_project_station_label.setText(f"{self.current_project.name} / {self.current_station.name}")
        self.local_device_dialog.show()
        self.local_device_dialog.raise_()
        self.local_device_dialog.activateWindow()

    def load_local_device_settings(self):
        if not self.app_config_path.exists():
            return
        config = configparser.ConfigParser()
        config.read(self.app_config_path, encoding="utf-8")
        if "LOCAL_DEVICE" not in config:
            return
        local = config["LOCAL_DEVICE"]
        self.local_auto_sync_checkbox.setChecked(local.getboolean("auto_sync_config", fallback=True))
        self.local_plc_override_checkbox.setChecked(local.getboolean("plc_override_enabled", fallback=False))
        self.local_plc_ip_input.setText(local.get("plc_ip", self.local_plc_ip_input.text()))
        self.local_plc_timeout_input.setValue(local.getint("plc_timeout_seconds", fallback=self.local_plc_timeout_input.value()))
        self.local_plc_poll_interval_input.setValue(local.getint("plc_poll_interval_ms", fallback=self.local_plc_poll_interval_input.value()))

    def save_local_device_settings(self):
        config = configparser.ConfigParser()
        if self.app_config_path.exists():
            config.read(self.app_config_path, encoding="utf-8")
        if "LOCAL_DEVICE" not in config:
            config["LOCAL_DEVICE"] = {}
        config["LOCAL_DEVICE"].update(
            {
                "mes_server": self.api_base_input.text().strip(),
                "client_id": self.station_session_client_id,
                "project": self.current_project.name,
                "station": self.current_station.name,
                "auto_sync_config": str(self.local_auto_sync_checkbox.isChecked()).lower(),
                "plc_override_enabled": str(self.local_plc_override_checkbox.isChecked()).lower(),
                "plc_ip": self.local_plc_ip_input.text().strip(),
                "plc_timeout_seconds": str(self.local_plc_timeout_input.value()),
                "plc_poll_interval_ms": str(self.local_plc_poll_interval_input.value()),
            }
        )
        with self.app_config_path.open("w", encoding="utf-8") as file:
            config.write(file)

    def save_local_device_settings_from_dialog(self):
        self.save_local_device_settings()
        self.message_label.setText("本机设备设置已保存")
        QMessageBox.information(self, "提示", "本机设备设置已保存；PLC覆盖参数将在下次进入PLC工序时生效")
        self.local_device_dialog.accept()

    def load_product(self, product_name: str):
        if not product_name:
            return
        product = next((item for item in self.products if item.name == product_name), None)
        if product is None:
            return
        project, station = self.find_station_by_product(product)
        if station is not None:
            self.current_project = project
            self.current_station = station
            self.refresh_project_station_selectors()
            self.load_station(project.name, station.name)
            return
        self.current_product = product
        self.ensure_main_barcode(self.current_product, notify=True)
        self.product_name_input.setText(product.name)
        self.sync_product_selectors(product.name)
        self.reset_current_product(update_table=True)

    def find_station_by_product(self, product: ProductConfig):
        for project in self.projects:
            for station in project.stations:
                if station.product is product:
                    return project, station
        return None, None

    def sync_product_selectors(self, product_name: str):
        combo_index = self.product_combo.findText(product_name)
        if combo_index >= 0 and self.product_combo.currentIndex() != combo_index:
            self.product_combo.blockSignals(True)
            self.product_combo.setCurrentIndex(combo_index)
            self.product_combo.blockSignals(False)

        matching_items = self.product_list.findItems(product_name, Qt.MatchExactly)
        if matching_items and self.product_list.currentItem() != matching_items[0]:
            self.product_list.blockSignals(True)
            self.product_list.setCurrentItem(matching_items[0])
            self.product_list.blockSignals(False)

    def refresh_product_list(self):
        current_name = self.current_product.name
        self.product_list.blockSignals(True)
        self.product_list.clear()
        for product in self.products:
            self.product_list.addItem(product.name)
        self.product_list.blockSignals(False)
        self.sync_product_selectors(current_name)

    def reset_current_product(self, update_table: bool = False):
        self.current_product.reset()
        self.current_step_index = 0
        self.step_started_at = datetime.now()
        self.last_voice_step_key = None
        self.current_barcode = ""
        self.waiting_tool_trigger_reset = False
        self.tool_ng_locked = False
        self.tool_ng_dialog_open = False
        if hasattr(self, "tool_admin_unlock_btn"):
            self.tool_admin_unlock_btn.setEnabled(False)
        self.barcode_input.clear()
        self.message_label.setText("等待第1工序条码进入")
        if update_table:
            self.populate_step_table()
        self.refresh_work_area()
        if self.production_enabled:
            self.prompt_current_step_start()

    def populate_step_table(self):
        self.step_table.setRowCount(0)
        for step in self.current_product.steps:
            row = self.step_table.rowCount()
            self.step_table.insertRow(row)
            self.step_table.setItem(row, 0, QTableWidgetItem(step.name))
            type_item = QTableWidgetItem(step.step_type)
            type_item.setFlags(type_item.flags() & ~Qt.ItemIsEditable)
            self.step_table.setItem(row, 1, type_item)
            self.step_table.setItem(row, 2, QTableWidgetItem(str(step.required_count)))
            self.step_table.setItem(row, 3, QTableWidgetItem(str(step.barcode_start)))
            self.step_table.setItem(row, 4, QTableWidgetItem(str(step.barcode_end)))
            self.step_table.setItem(row, 5, QTableWidgetItem(step.expected_content))

    def refresh_work_area(self):
        self.step_list.clear()
        for index, step in enumerate(self.current_product.steps):
            item = QListWidgetItem(f"{index + 1}.{step.display_status}")
            if step.done:
                item.setForeground(QColor("#16a34a"))
            elif index == self.current_step_index:
                item.setForeground(QColor("#2563eb"))
            self.step_list.addItem(item)

        self.product_label.setText(self.current_product.name)
        self.main_barcode_label.setText(f"当前主条码：{self.current_barcode or '未扫描'}")
        self.finished_count_label.setText(f"已生成零件数：{self.finished_part_count}")
        self.scan_error_count_label.setText(f"扫码错误总数：{self.scan_error_count}")
        current_step = self.current_step()
        if current_step is None:
            self.current_step_label.setText("全部工序已完成，等待再次第1工序条码进入")
            self.screw_ok_btn.setEnabled(False)
            self.barcode_input.setEnabled(self.production_enabled)
        else:
            self.current_step_label.setText(f"当前工序：{current_step.name}")
            self.screw_ok_btn.setEnabled(self.production_enabled and current_step.step_type == SCREW)
            self.barcode_input.setEnabled(self.production_enabled and current_step.step_type == SCAN)
        self.render_screw_blocks(current_step)

    def render_screw_blocks(self, step: Optional[ProcessStep]):
        while self.screw_grid.count():
            child = self.screw_grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.screw_blocks = []

        if step is None or step.step_type != SCREW:
            label = QLabel("当前不是螺丝工序")
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("font-size: 24px; color: #6b7280; padding: 48px;")
            self.screw_grid.addWidget(label, 0, 0)
            return

        for number in range(step.required_count):
            block = QLabel(str(number + 1))
            block.setAlignment(Qt.AlignCenter)
            block.setFixedSize(86, 86)
            color = "#22c55e" if number < step.completed_count else "#d1d5db"
            block.setStyleSheet(
                f"background: {color}; border-radius: 8px; font-size: 28px; font-weight: 700;"
                " color: #111827;"
            )
            self.screw_grid.addWidget(block, number // 8, number % 8)
            self.screw_blocks.append(block)

    def current_step(self) -> Optional[ProcessStep]:
        if self.current_step_index >= len(self.current_product.steps):
            return None
        return self.current_product.steps[self.current_step_index]

    def get_main_barcode_step(self) -> Optional[ProcessStep]:
        for step in self.current_product.steps:
            if step.step_type in (SCAN, PLC) and step.is_main_barcode:
                return step
        return next((step for step in self.current_product.steps if step.step_type in (SCAN, PLC)), None)

    def ensure_main_barcode(self, product: ProductConfig, notify: bool = False):
        scan_steps = [step for step in product.steps if step.step_type in (SCAN, PLC)]
        if not scan_steps:
            return
        main_steps = [step for step in scan_steps if step.is_main_barcode]
        if len(main_steps) == 1:
            return
        first_scan = main_steps[0] if main_steps else scan_steps[0]
        for step in scan_steps:
            step.is_main_barcode = step is first_scan
        if notify and not main_steps:
            message = "当前工位未配置主条码，已临时使用第一道扫码工序作为主条码"
            self.message_label.setText(message)
            if hasattr(self, "warning_dialogs"):
                self.show_auto_close_warning("主条码临时配置", message)

    def handle_scan(self):
        if not self.ensure_station_session_for_production():
            return
        step = self.current_step()
        if step is None:
            self.reset_current_product()
            step = self.current_step()
        if step is None or step.step_type != SCAN:
            self.message_label.setText("当前工序不接受扫码")
            return

        barcode = self.barcode_input.text().strip()
        if not barcode:
            self.message_label.setText("请先输入或扫描条码")
            return

        start = max(step.barcode_start - 1, 0)
        end = max(step.barcode_end, start)
        captured = barcode[start:end]
        if step.expected_content and captured != step.expected_content:
            message = (
                f"条码复核失败：第{step.barcode_start}-{step.barcode_end}位为“{captured}”，"
                f"应为“{step.expected_content}”"
            )
            self.scan_error_count += 1
            self.add_history_record(step, "扫码错误", barcode, message, completed=False)
            self.message_label.setText(message)
            self.refresh_work_area()
            self.speak("条码错误")
            self.show_auto_close_warning("扫码错误", message)
            return

        main_barcode_step = self.get_main_barcode_step()
        is_main_barcode_step = step is main_barcode_step
        if is_main_barcode_step:
            if self.should_check_previous_station() and not self.verify_previous_station_complete(barcode):
                return
            self.current_barcode = barcode

        self.add_history_record(step, "完成", barcode, "扫码复核通过", completed=True)
        self.play_ok_sound()
        step.done = True
        self.message_label.setText(f"{step.name} 已完成")
        self.barcode_input.clear()
        self.advance_step()

    def handle_screw_ok(self):
        if not self.ensure_station_session_for_production():
            return
        step = self.current_step()
        if step is None or step.step_type != SCREW:
            self.message_label.setText("当前不是螺丝工序")
            return

        step.completed_count += 1
        if step.completed_count >= step.required_count:
            step.completed_count = step.required_count
            step.done = True
            self.add_history_record(step, "完成", "螺钉枪OK", "螺丝数量已满足", completed=True)
            self.close_tool_for_screw_step()
            self.speak("螺丝已完成")
            self.message_label.setText(f"{step.name} 已完成 {step.required_count}/{step.required_count}")
            self.advance_step(prompt_delay_ms=1600)
        else:
            self.message_label.setText(f"收到螺钉枪OK信号：{step.completed_count}/{step.required_count}")
            self.refresh_work_area()

    def toggle_tool_connection(self):
        if self.is_tool_worker_running():
            self.stop_tool_worker()
            return
        if not self.ensure_production_enabled():
            return

        if self.disable_tool_auto_listen_checkbox.isChecked():
            self.message_label.setText("已禁用螺钉枪自动监听，可使用模拟OK按钮测试流程")
            self.tool_status_label.setText("未连接")
            self.tool_status_label.setStyleSheet("font-size: 16px; color: #6b7280;")
            return

        config = ToolPollConfig(
            host=self.tool_ip_input.text().strip(),
            port=self.tool_port_input.value(),
            unit_id=self.tool_unit_input.value(),
            status_register=self.tool_status_register_input.value(),
            trigger_register=self.tool_trigger_register_input.value(),
            direction_register=self.tool_direction_register_input.value(),
            timeout_seconds=float(self.tool_timeout_input.value()),
            poll_interval_ms=self.tool_poll_interval_input.value(),
        )
        self.tool_thread = QThread(self)
        self.tool_worker = ToolPollWorker(config)
        generation = self.tool_worker_generation
        self.tool_worker.moveToThread(self.tool_thread)
        self.tool_thread.started.connect(self.tool_worker.start)
        self.tool_worker_write_requested.connect(self.tool_worker.write_register, Qt.QueuedConnection)
        self.tool_worker.result.connect(lambda status, trigger, direction, gen=generation: self.on_tool_poll_result_for_generation(gen, status, trigger, direction))
        self.tool_worker.error.connect(self.on_tool_poll_error)
        self.tool_worker.write_error.connect(self.on_tool_write_error)
        self.tool_worker.stopped.connect(self.tool_thread.quit)
        self.tool_thread.finished.connect(self.tool_worker.deleteLater)
        self.tool_thread.finished.connect(self.cleanup_tool_worker)
        self.tool_thread.start()
        self.tool_connect_btn.setEnabled(False)
        self.tool_disconnect_btn.setEnabled(True)
        self.tool_status_label.setText("已连接")
        self.tool_status_label.setStyleSheet("font-size: 16px; color: #2563eb;")
        self.sync_tool_lock_for_current_step()

    def is_tool_worker_running(self) -> bool:
        return self.tool_thread is not None and self.tool_thread.isRunning()

    def stop_tool_worker(self):
        if self.tool_thread is not None:
            if self.tool_worker is not None and self.tool_thread.isRunning():
                try:
                    self.tool_worker.polling = False
                    QMetaObject.invokeMethod(self.tool_worker, "stop", Qt.QueuedConnection)
                except Exception as exc:
                    logging.warning("停止螺钉枪 worker 通知失败：%s", exc)
            self.tool_thread.quit()
            if not self.tool_thread.wait(1500):
                logging.warning("停止螺钉枪 worker 超时")
        self.cleanup_tool_worker()
        self.tool_worker_generation += 1

    def cleanup_tool_worker(self):
        self.tool_worker = None
        self.tool_thread = None
        self.processing_tool_signal = False
        self.waiting_tool_trigger_reset = False
        self.tool_ng_locked = False
        self.tool_ng_dialog_open = False
        self.tool_lock_state = None
        if hasattr(self, "tool_connect_btn"):
            self.tool_connect_btn.setText("连接")
            self.tool_connect_btn.setEnabled(True)
        if hasattr(self, "tool_disconnect_btn"):
            self.tool_disconnect_btn.setEnabled(False)
        if hasattr(self, "tool_status_label"):
            self.tool_status_label.setText("未连接")
            self.tool_status_label.setStyleSheet("font-size: 16px; color: #6b7280;")

    def start_plc_worker(self, step: ProcessStep):
        if not self.ensure_station_session_for_production():
            return
        if self.plc_thread is not None and self.plc_thread.isRunning():
            return
        self.reset_plc_state()
        plc_ip = step.plc_ip
        timeout_seconds = step.plc_timeout_seconds
        poll_interval_ms = step.plc_poll_interval_ms
        if self.local_plc_override_checkbox.isChecked():
            plc_ip = self.local_plc_ip_input.text().strip() or plc_ip
            timeout_seconds = self.local_plc_timeout_input.value()
            poll_interval_ms = self.local_plc_poll_interval_input.value()
        config = PlcPollConfig(
            ip=plc_ip,
            rack=step.plc_rack,
            slot=step.plc_slot,
            barcode_db=step.plc_barcode_db,
            barcode_offset=step.plc_barcode_offset,
            barcode_length=step.plc_barcode_length,
            parts_ok_db=step.plc_parts_ok_db,
            parts_ok_offset=step.plc_parts_ok_offset,
            parts_ok_type=step.plc_parts_ok_type,
            barcode_encoding=step.plc_barcode_encoding,
            strip_null=step.plc_barcode_strip_null,
            strip_space=step.plc_barcode_strip_space,
            timeout_seconds=timeout_seconds,
            poll_interval_ms=poll_interval_ms,
        )
        self.plc_thread = QThread(self)
        self.plc_worker = PlcPollWorker(config)
        generation = self.plc_worker_generation
        self.plc_worker.moveToThread(self.plc_thread)
        self.plc_thread.started.connect(self.plc_worker.start)
        self.plc_worker.snapshot.connect(lambda parts_ok, main_barcode, main_barcode_hex, gen=generation: self.on_plc_snapshot_for_generation(gen, parts_ok, main_barcode, main_barcode_hex))
        self.plc_worker.error.connect(self.on_plc_error)
        self.plc_worker.stopped.connect(self.plc_thread.quit)
        self.plc_thread.finished.connect(self.plc_worker.deleteLater)
        self.plc_thread.finished.connect(self.cleanup_plc_worker)
        self.plc_thread.start()
        if self.local_plc_override_checkbox.isChecked():
            self.message_label.setText(f"当前启用了 PLC 本地覆盖，实际使用 IP：{plc_ip}；长期修改必须走 Web 后台")
        else:
            self.message_label.setText(f"PLC接收工序已启动，连接 {plc_ip}")

    def stop_plc_worker(self):
        if self.plc_thread is not None:
            if self.plc_worker is not None and self.plc_thread.isRunning():
                try:
                    self.plc_worker.polling = False
                    QMetaObject.invokeMethod(self.plc_worker, "stop", Qt.QueuedConnection)
                except Exception as exc:
                    logging.warning("停止 PLC worker 通知失败：%s", exc)
            self.plc_thread.quit()
            if not self.plc_thread.wait(1500):
                logging.warning("停止 PLC worker 超时")
        self.cleanup_plc_worker()
        self.plc_worker_generation += 1

    def cleanup_plc_worker(self):
        self.plc_worker = None
        self.plc_thread = None

    def reset_plc_state(self):
        self.plc_last_main_barcode = ""
        self.plc_last_parts_ok = None
        self.plc_pending_main_barcode = ""
        self.plc_pending_barcode_time = None
        self.plc_waiting_parts_ok = False

    def on_plc_error(self, message: str):
        self.message_label.setText(f"PLC通讯异常：{message}")

    def on_plc_snapshot_for_generation(self, generation: int, parts_ok: int, main_barcode: str, main_barcode_hex: str = ""):
        if generation != self.plc_worker_generation:
            logging.info("忽略旧 PLC worker 信号 generation=%s current=%s", generation, self.plc_worker_generation)
            return
        self.on_plc_snapshot(parts_ok, main_barcode, main_barcode_hex)

    def on_plc_snapshot(self, parts_ok: int, main_barcode: str, main_barcode_hex: str = ""):
        step = self.current_step()
        if step is None or step.step_type != PLC:
            return
        if not self.ensure_station_session_for_production():
            return
        if self.plc_last_parts_ok is None:
            self.plc_last_parts_ok = parts_ok
            self.plc_last_main_barcode = main_barcode
            self.message_label.setText("PLC首次读取，仅建立条码和PARTS_OK基准")
            return
        if main_barcode and main_barcode != self.plc_last_main_barcode:
            self.plc_pending_main_barcode = main_barcode
            self.plc_pending_barcode_time = datetime.now()
            self.plc_waiting_parts_ok = True
            self.plc_last_main_barcode = main_barcode
            self.message_label.setText("已检测到新条码，等待PLC完成OK")
        if parts_ok == self.plc_last_parts_ok:
            if self.plc_waiting_parts_ok and self.plc_pending_barcode_time:
                elapsed = (datetime.now() - self.plc_pending_barcode_time).total_seconds()
                if elapsed > step.plc_barcode_wait_ok_timeout_seconds:
                    self.message_label.setText("已检测到条码，但长时间未收到PARTS_OK递增")
                else:
                    self.message_label.setText("已检测到条码，等待PARTS_OK递增")
            return
        if parts_ok < self.plc_last_parts_ok:
            self.plc_last_parts_ok = parts_ok
            self.plc_pending_main_barcode = ""
            self.plc_waiting_parts_ok = False
            self.message_label.setText("PLC完成计数变小，已重新建立基准")
            return
        old_parts_ok = self.plc_last_parts_ok
        self.plc_last_parts_ok = parts_ok
        if parts_ok - old_parts_ok > 1:
            self.message_label.setText("PARTS_OK跳变超过1，可能漏采")
            self.add_history_record(
                step,
                "警告",
                main_barcode,
                f"PARTS_OK从{old_parts_ok}跳到{parts_ok}，可能漏采",
                completed=False,
            )
        if not self.plc_waiting_parts_ok or not self.plc_pending_main_barcode:
            self.add_history_record(step, "异常", main_barcode, "PARTS_OK递增，但未检测到新条码，无法确认OK对应哪个条码", completed=False)
            return
        self.complete_plc_step(step, self.plc_pending_main_barcode, main_barcode_hex, old_parts_ok, parts_ok)

    def complete_plc_step(self, step: ProcessStep, main_barcode: str, main_barcode_hex: str, parts_ok_before: int, parts_ok_after: int):
        if step.is_main_barcode:
            if self.should_check_previous_station() and not self.verify_previous_station_complete(main_barcode):
                self.add_history_record(step, "异常", main_barcode, "上一工位未完成，PLC主条码不能进入当前工位", completed=False)
                self.plc_pending_main_barcode = ""
                self.plc_waiting_parts_ok = False
                self.plc_last_main_barcode = ""
                return
            self.current_barcode = main_barcode
        elif not self.current_barcode:
            message = "缺少主条码，PLC普通工序不能完成"
            self.message_label.setText(message)
            self.show_auto_close_warning("主条码缺失", message)
            self.add_history_record(step, "异常", main_barcode, message, completed=False)
            self.plc_pending_main_barcode = ""
            self.plc_waiting_parts_ok = False
            self.plc_last_main_barcode = ""
            return
        elif main_barcode and main_barcode != self.current_barcode:
            message = "PLC主条码与当前产品主条码不一致"
            self.message_label.setText(message)
            self.show_auto_close_warning("PLC条码不一致", message)
            self.add_history_record(step, "异常", main_barcode, message, completed=False)
            self.plc_pending_main_barcode = ""
            self.plc_waiting_parts_ok = False
            self.plc_last_main_barcode = ""
            return
        step.done = True
        self.refresh_work_area()
        note = "PARTS_OK递增完成，PLC主条码作为流转主条码" if step.is_main_barcode else "PARTS_OK递增完成，PLC条码与当前主条码一致"
        self.add_history_record(step, "OK", main_barcode, note, completed=True)
        self.post_plc_step_record(step, main_barcode, main_barcode_hex, parts_ok_before, parts_ok_after)
        self.plc_pending_main_barcode = ""
        self.plc_waiting_parts_ok = False
        self.stop_plc_worker()
        self.message_label.setText(f"PLC接收完成：{main_barcode}")
        self.advance_step()

    def post_plc_step_record(self, step: ProcessStep, main_barcode: str, main_barcode_hex: str, parts_ok_before: int, parts_ok_after: int):
        if not self.online_mode or not self.production_enabled:
            return
        flow_barcode = self.current_barcode or main_barcode
        payload = {
            "project": self.current_project.name,
            "station": self.current_station.name,
            "main_barcode": flow_barcode,
            "step_name": step.name,
            "step_type": PLC,
            "step_order": self.current_step_index + 1,
            "start_time": self.step_started_at.isoformat(timespec="seconds"),
            "end_time": datetime.now().isoformat(timespec="seconds"),
            "duration_seconds": int((datetime.now() - self.step_started_at).total_seconds()),
            "barcode": main_barcode,
            "scan_result": "OK",
            "result": "OK",
            "note": f"plc_main_barcode_hex={main_barcode_hex}; parts_ok_before={parts_ok_before}; parts_ok_after={parts_ok_after}",
        }
        try:
            self.api_post("/api/step-records", payload)
        except Exception:
            pass

    def on_tool_poll_error(self, message: str):
        logging.error("螺钉枪通讯异常：%s", message)
        self.tool_status_label.setText("通讯异常")
        self.tool_status_label.setStyleSheet("font-size: 16px; color: #dc2626;")
        self.message_label.setText(f"螺钉枪通讯异常：{message}")

    def on_tool_write_error(self, message: str):
        logging.error("螺钉枪写入异常：%s", message)
        self.tool_status_label.setText("通讯异常")
        self.tool_status_label.setStyleSheet("font-size: 16px; color: #dc2626;")
        self.message_label.setText(f"螺钉枪写入异常：{message}")

    def on_tool_poll_result_for_generation(self, generation: int, status: int, trigger: int, direction: int):
        if generation != self.tool_worker_generation:
            logging.info("忽略旧螺钉枪 worker 信号 generation=%s current=%s", generation, self.tool_worker_generation)
            return
        self.on_tool_poll_result(status, trigger, direction)

    def on_tool_poll_result(self, status: int, trigger: int, direction: int):
        if self.processing_tool_signal:
            return
        self.processing_tool_signal = True
        try:
            self.process_tool_poll_result(status, trigger, direction)
        finally:
            self.processing_tool_signal = False

    def process_tool_poll_result(self, status: int, trigger: int, direction: Optional[int] = None):
        if not self.ensure_station_session_for_production():
            return
        step = self.current_step()
        if step is None or step.step_type != SCREW:
            self.lock_tool()
            self.tool_status_label.setText("已连接")
            self.message_label.setText(
                f"非螺丝工序，螺钉枪锁定；触发：{trigger}，状态：{status}-{self.tightening_status_text(status)}"
            )
            self.tool_status_label.setStyleSheet("font-size: 16px; color: #6b7280;")
            return

        if self.tool_ng_locked:
            self.lock_tool()
            self.tool_status_label.setText("NG锁定")
            self.message_label.setText("NG锁定：等待管理员解锁")
            self.tool_status_label.setStyleSheet("font-size: 16px; color: #dc2626;")
            return

        if direction is None:
            direction = self.tool_forward_value_input.value()
        ok_value = self.tool_ok_value_input.value()
        ng_value = self.tool_ng_value_input.value()
        trigger_value = self.tool_trigger_value_input.value()
        trigger_reset_value = self.tool_trigger_reset_value_input.value()
        forward_value = self.tool_forward_value_input.value()
        reverse_value = self.tool_reverse_value_input.value()
        dedup_enabled = self.tool_enable_dedup_checkbox.isChecked()
        status_text = self.tightening_status_text(status)
        if self.tool_verbose_log_checkbox.isChecked():
            logging.info("螺钉枪读取：direction=%s trigger=%s status=%s-%s", direction, trigger, status, status_text)
        self.tool_status_label.setText("已连接")
        self.message_label.setText(
            f"螺钉枪方向：{direction}，触发：{trigger}，状态：{status}-{status_text}，OK={'是' if status == ok_value else '否'}"
        )
        self.tool_status_label.setStyleSheet("font-size: 16px; color: #16a34a;")

        if direction == reverse_value:
            self.tool_status_label.setText("反向")
            self.message_label.setText("反向状态，不计数")
            self.tool_status_label.setStyleSheet("font-size: 16px; color: #f59e0b;")
            if trigger == trigger_value and self.tool_clear_trigger_when_reverse_checkbox.isChecked():
                self.reset_tool_trigger()
                logging.info("反向动作触发已忽略并清53")
                if dedup_enabled:
                    self.waiting_tool_trigger_reset = True
            return

        if direction != forward_value:
            self.message_label.setText(f"未知方向值 {direction}，不计数")
            return

        if trigger == trigger_reset_value:
            if dedup_enabled:
                self.waiting_tool_trigger_reset = False
            return
        if trigger != trigger_value:
            return
        if dedup_enabled and self.waiting_tool_trigger_reset:
            return

        if status == ok_value:
            if dedup_enabled:
                self.waiting_tool_trigger_reset = True
            self.reset_tool_trigger()
            self.handle_screw_ok()
            return

        if status == ng_value:
            if dedup_enabled:
                self.waiting_tool_trigger_reset = True
            self.handle_screw_ng()
            return

        if status == 4:
            self.message_label.setText("螺钉枪暂停")
            return

    def write_tool_register(self, register_address: int, value: int):
        if not self.is_tool_worker_running():
            return False
        self.tool_worker_write_requested.emit(register_address, value)
        return True

    def try_lock_tool_nonblocking(self):
        try:
            if self.is_tool_worker_running():
                self.write_tool_register(self.tool_control_register_input.value(), self.tool_lock_value_input.value())
                logging.info("已发送锁枪指令")
        except Exception as exc:
            logging.warning("切换工位时锁枪失败，继续切换：%s", exc)

    def reset_tool_trigger(self):
        self.write_tool_register(self.tool_trigger_register_input.value(), self.tool_trigger_reset_value_input.value())

    def lock_tool(self):
        if self.tool_lock_state == "locked":
            return
        if self.write_tool_register(self.tool_control_register_input.value(), self.tool_lock_value_input.value()):
            self.tool_lock_state = "locked"

    def unlock_tool(self):
        if self.tool_lock_state == "unlocked":
            return
        if self.write_tool_register(self.tool_control_register_input.value(), self.tool_unlock_value_input.value()):
            self.tool_lock_state = "unlocked"

    def sync_tool_lock_for_current_step(self):
        step = self.current_step()
        if step is not None and step.step_type == SCREW:
            self.reset_tool_trigger()
            self.unlock_tool()
            return
        self.lock_tool()

    def add_screw_ng_record(self):
        step = self.current_step()
        if step is None or step.step_type != SCREW:
            return
        self.add_history_record(step, "NG", "螺钉枪NG", "螺丝NG，请重新打当前这颗", completed=False)
        self.message_label.setText("螺丝NG，请重新打当前这颗")

    def handle_screw_ng(self):
        self.add_screw_ng_record()
        self.tool_ng_locked = True
        self.tool_admin_unlock_btn.setEnabled(True)
        self.lock_tool()
        self.reset_tool_trigger()
        self.speak("螺丝NG，请管理员解锁")
        self.tool_status_label.setText("NG锁定")
        self.tool_status_label.setStyleSheet("font-size: 16px; color: #dc2626;")
        self.message_label.setText("检测到螺丝NG，螺钉枪已锁定，请管理员输入密码解锁")
        self.show_tool_ng_unlock_dialog()

    def reopen_tool_ng_unlock_dialog(self):
        if self.tool_ng_locked and not self.tool_ng_dialog_open:
            self.show_tool_ng_unlock_dialog()

    def show_tool_ng_unlock_dialog(self):
        if self.tool_ng_dialog_open:
            return
        self.tool_ng_dialog_open = True
        dialog = QDialog(self)
        dialog.setWindowTitle("螺丝NG确认 / 管理解锁")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        prompt = QLabel("检测到螺丝NG，螺钉枪已锁定，请管理员输入密码解锁")
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        password_input = QLineEdit()
        password_input.setEchoMode(QLineEdit.Password)
        password_input.setPlaceholderText("请输入管理员密码")
        layout.addWidget(password_input)

        keypad = QGridLayout()
        for index, digit in enumerate("123456789"):
            button = QPushButton(digit)
            button.clicked.connect(lambda _, value=digit: password_input.setText(password_input.text() + value))
            keypad.addWidget(button, index // 3, index % 3)
        clear_btn = QPushButton("清除")
        zero_btn = QPushButton("0")
        backspace_btn = QPushButton("退格")
        clear_btn.clicked.connect(password_input.clear)
        zero_btn.clicked.connect(lambda: password_input.setText(password_input.text() + "0"))
        backspace_btn.clicked.connect(lambda: password_input.setText(password_input.text()[:-1]))
        keypad.addWidget(clear_btn, 3, 0)
        keypad.addWidget(zero_btn, 3, 1)
        keypad.addWidget(backspace_btn, 3, 2)
        layout.addLayout(keypad)

        button_row = QHBoxLayout()
        confirm_btn = QPushButton("确认")
        cancel_btn = QPushButton("取消")
        button_row.addStretch(1)
        button_row.addWidget(confirm_btn)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)

        def confirm_unlock():
            if self.unlock_tool_after_ng(password_input.text()):
                dialog.accept()
                return
            password_input.clear()
            QMessageBox.warning(dialog, "密码错误", "密码错误")

        confirm_btn.clicked.connect(confirm_unlock)
        cancel_btn.clicked.connect(dialog.reject)
        password_input.returnPressed.connect(confirm_unlock)
        dialog.finished.connect(lambda _: self._tool_ng_dialog_finished())
        dialog.exec_()

    def _tool_ng_dialog_finished(self):
        self.tool_ng_dialog_open = False
        if self.tool_ng_locked:
            self.lock_tool()
            self.tool_status_label.setText("NG锁定")
            self.message_label.setText("NG锁定：等待管理员解锁")

    def unlock_tool_after_ng(self, password: str) -> bool:
        if password != self.tool_admin_password_input.text():
            self.lock_tool()
            return False
        self.unlock_tool()
        self.reset_tool_trigger()
        self.tool_ng_locked = False
        self.tool_ng_dialog_open = False
        self.tool_admin_unlock_btn.setEnabled(False)
        self.waiting_tool_trigger_reset = False
        self.tool_status_label.setText("已解锁")
        self.tool_status_label.setStyleSheet("font-size: 16px; color: #16a34a;")
        self.message_label.setText("已解锁，请重新打当前这颗螺丝")
        return True

    def tightening_status_text(self, value: int) -> str:
        status_map = {
            0: "准备",
            1: "作业中",
            2: "OK",
            3: "NG",
            4: "暂停",
            5: "正转",
            6: "反转",
        }
        return status_map.get(value, "未知")

    def advance_step(self, prompt_delay_ms: int = 0):
        if not self.ensure_production_enabled():
            return
        self.current_step_index += 1
        if self.current_step_index >= len(self.current_product.steps):
            if not self.report_station_complete():
                self.current_step_index = max(len(self.current_product.steps) - 1, 0)
                self.refresh_work_area()
                return
            self.finished_part_count += 1
            self.message_label.setText("所有工序完成，系统已重新开始等待第1工序条码进入")
            self.current_product.reset()
            self.current_step_index = 0
            self.current_barcode = ""
            self.waiting_tool_trigger_reset = False
            self.tool_ng_locked = False
            self.tool_ng_dialog_open = False
            if hasattr(self, "tool_admin_unlock_btn"):
                self.tool_admin_unlock_btn.setEnabled(False)
        self.step_started_at = datetime.now()
        self.last_voice_step_key = None
        self.refresh_work_area()
        if prompt_delay_ms:
            QTimer.singleShot(prompt_delay_ms, self.prompt_current_step_start)
        else:
            self.prompt_current_step_start()

    def station_number(self, station_name: str) -> int:
        digits = "".join(ch for ch in station_name if ch.isdigit())
        return int(digits) if digits else 1

    def previous_station_name(self) -> str:
        number = self.station_number(self.current_station.name)
        return f"工位{max(number - 1, 1)}"

    def verify_previous_station_complete(self, barcode: str) -> bool:
        if self.station_number(self.current_station.name) <= 1:
            return True
        try:
            query = urllib.parse.urlencode(
                {
                    "project": self.current_project.name,
                    "barcode": barcode,
                    "previous_station": self.previous_station_name(),
                }
            )
            data = self.api_get(f"/api/station-completions/check?{query}")
        except Exception as exc:
            message = f"前工位完成状态查询失败：{exc}"
            self.message_label.setText(message)
            self.show_auto_close_warning("工位验证失败", message)
            return False
        if data.get("completed"):
            return True
        message = "上一工位未完成，不能进行当前工位"
        self.message_label.setText(message)
        self.show_auto_close_warning("前工位未完成", message)
        return False

    def should_check_previous_station(self) -> bool:
        return self.online_mode and not self.degraded_mode_checkbox.isChecked()

    def report_station_complete(self):
        if not self.ensure_station_session_for_production():
            return False
        if not self.online_mode:
            return True
        if not self.current_barcode:
            message = "缺少主条码，无法完成工位流转"
            self.message_label.setText(message)
            self.show_auto_close_warning("主条码缺失", message)
            return False
        payload = {
            "project": self.current_project.name,
            "station": self.current_station.name,
            "barcode": self.current_barcode,
            "completed_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            self.api_post("/api/station-completions", payload)
        except Exception as exc:
            self.message_label.setText(f"工位完成上报失败：{exc}")
        return True

    def closeEvent(self, event):
        self.stop_tool_worker()
        self.stop_plc_worker()
        self.release_station_session()
        super().closeEvent(event)

    def prompt_current_step_start(self):
        if not self.ensure_production_enabled():
            return
        step = self.current_step()
        if step is None:
            return
        step_key = (self.current_product.name, self.current_step_index, step.name)
        if self.last_voice_step_key == step_key:
            return
        self.last_voice_step_key = step_key
        if step.step_type == SCREW:
            self.stop_plc_worker()
            self.enter_tool_screw_step(step)
            self.speak(f"请打螺丝{step.required_count}颗")
        elif step.step_type == PLC:
            self.lock_tool()
            if self.online_mode:
                self.start_plc_worker(step)
            else:
                self.message_label.setText("PLC接收工序需要在线模式和服务端工位占用")
        else:
            self.stop_plc_worker()
            self.lock_tool()
            self.speak("请扫码")

    def enter_tool_screw_step(self, step: ProcessStep):
        if not self.is_tool_worker_running():
            return
        try:
            self.reset_tool_trigger()
            self.unlock_tool()
        except Exception as exc:
            self.tool_status_label.setText("通讯异常")
            self.message_label.setText(f"螺钉枪初始化异常：{exc}")
            self.tool_status_label.setStyleSheet("font-size: 16px; color: #dc2626;")

    def close_tool_for_screw_step(self):
        if not self.is_tool_worker_running():
            return
        try:
            self.lock_tool()
            self.reset_tool_trigger()
        except Exception as exc:
            self.tool_status_label.setText("通讯异常")
            self.message_label.setText(f"螺钉枪关闭异常：{exc}")
            self.tool_status_label.setStyleSheet("font-size: 16px; color: #dc2626;")

    def speak(self, text: str):
        if self.say_command:
            subprocess.Popen(
                [self.say_command, text],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            QApplication.beep()

    def play_ok_sound(self):
        QApplication.beep()

    def add_history_record(self, step: ProcessStep, result: str, source: str, note: str, completed: bool):
        now = datetime.now()
        duration = (now - self.step_started_at).total_seconds()
        barcode = source if step.step_type == SCAN else self.current_barcode
        self.history_records.append(
            {
                "time": now,
                "project": self.current_project.name,
                "station": self.current_station.name,
                "product": self.current_product.name,
                "step": step.name,
                "type": step.step_type,
                "result": result,
                "source": source,
                "barcode": barcode,
                "duration": duration,
                "note": note,
                "completed": completed,
            }
        )
        if self.online_mode and barcode:
            if not self.production_enabled:
                return
            self.post_scan_record_to_server(step, result, barcode, note, now)
        if self.history_dialog is not None and self.history_dialog.isVisible():
            self.refresh_history_tables()

    def post_scan_record_to_server(self, step: ProcessStep, result: str, barcode: str, note: str, created_at: datetime):
        if not self.production_enabled:
            return
        payload = {
            "project": self.current_project.name,
            "station": self.current_station.name,
            "barcode": barcode,
            "step": step.name,
            "result": result,
            "note": note,
            "created_at": created_at.isoformat(timespec="seconds"),
        }
        try:
            self.api_post("/api/scan-records", payload)
        except Exception:
            pass

    def refresh_history_tables(self):
        if self.history_dialog is None:
            return
        start_time = self.history_start_edit.dateTime().toPyDateTime()
        end_time = self.history_end_edit.dateTime().toPyDateTime()
        barcode_keyword = self.history_barcode_input.text().strip()
        records = [
            record
            for record in self.history_records
            if start_time <= record["time"] <= end_time
            and (not barcode_keyword or barcode_keyword in record.get("barcode", ""))
        ]

        self.history_table.setRowCount(0)
        for record in records:
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            values = [
                record["time"].strftime("%Y-%m-%d %H:%M:%S"),
                record["project"],
                record["station"],
                record["product"],
                record["step"],
                record["type"],
                record["result"],
                record.get("barcode", ""),
                record["source"],
                f"{record['duration']:.1f}",
                record["note"],
            ]
            for column, value in enumerate(values):
                self.history_table.setItem(row, column, QTableWidgetItem(str(value)))

        stats = {}
        for record in records:
            if not record["completed"]:
                continue
            key = (record["project"], record["station"], record["product"], record["step"])
            if key not in stats:
                stats[key] = {"count": 0, "duration": 0.0}
            stats[key]["count"] += 1
            stats[key]["duration"] += record["duration"]

        self.report_table.setRowCount(0)
        for (project, station, product, step_name), stat in stats.items():
            row = self.report_table.rowCount()
            self.report_table.insertRow(row)
            avg = stat["duration"] / stat["count"] if stat["count"] else 0
            values = [project, station, product, step_name, stat["count"], f"{stat['duration']:.1f}", f"{avg:.1f}"]
            for column, value in enumerate(values):
                self.report_table.setItem(row, column, QTableWidgetItem(str(value)))

    def show_auto_close_warning(self, title: str, message: str):
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle(title)
        dialog.setText(message)
        dialog.setStandardButtons(QMessageBox.NoButton)
        dialog.setStyleSheet("QLabel { font-size: 20px; } QMessageBox { min-width: 420px; }")
        dialog.finished.connect(lambda: self.warning_dialogs.remove(dialog) if dialog in self.warning_dialogs else None)
        self.warning_dialogs.append(dialog)
        QTimer.singleShot(5000, dialog.accept)
        dialog.open()

    def save_product_name(self):
        new_name = self.product_name_input.text().strip()
        if not new_name:
            QMessageBox.warning(self, "提示", "产品中文名称不能为空")
            return
        old_name = self.current_product.name
        self.current_product.name = new_name
        index = self.product_combo.findText(old_name)
        if index >= 0:
            self.product_combo.setItemText(index, new_name)
            self.product_combo.setCurrentIndex(index)
        list_items = self.product_list.findItems(old_name, Qt.MatchExactly)
        if list_items:
            list_items[0].setText(new_name)
            self.product_list.setCurrentItem(list_items[0])
        self.refresh_work_area()

    def add_product(self):
        base_name = self.product_name_input.text().strip() or "新产品"
        new_name = base_name
        sequence = 2
        existing_names = {product.name for product in self.products}
        while new_name in existing_names:
            new_name = f"{base_name}{sequence}"
            sequence += 1
        product = ProductConfig(new_name, [ProcessStep("扫码首件条码", SCAN, is_main_barcode=True)])
        self.products.append(product)
        self.product_combo.addItem(product.name)
        self.refresh_product_list()
        self.product_combo.setCurrentText(product.name)

    def add_step(self, step_type: str):
        row = self.step_table.rowCount()
        self.step_table.insertRow(row)
        default_name = "扫码新零件" if step_type == SCAN else "打螺丝"
        values = [default_name, step_type, "0" if step_type == SCAN else "10", "1", "7", ""]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 1:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.step_table.setItem(row, column, item)

    def remove_selected_step(self):
        rows = sorted({item.row() for item in self.step_table.selectedItems()}, reverse=True)
        for row in rows:
            self.step_table.removeRow(row)

    def move_selected_step(self, direction: int):
        selected_rows = sorted({item.row() for item in self.step_table.selectedItems()})
        if len(selected_rows) != 1:
            QMessageBox.information(self, "提示", "请选择一行工序进行移动")
            return
        source = selected_rows[0]
        target = source + direction
        if target < 0 or target >= self.step_table.rowCount():
            return

        values = [self.table_text(source, column) for column in range(self.step_table.columnCount())]
        self.step_table.removeRow(source)
        self.step_table.insertRow(target)
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 1:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.step_table.setItem(target, column, item)
        self.step_table.selectRow(target)

    def save_steps_from_table(self):
        steps = []
        for row in range(self.step_table.rowCount()):
            name = self.table_text(row, 0) or f"工序{row + 1}"
            step_type = self.table_text(row, 1) or SCAN
            required_count = self.to_int(self.table_text(row, 2), 0)
            barcode_start = self.to_int(self.table_text(row, 3), 1)
            barcode_end = self.to_int(self.table_text(row, 4), barcode_start)
            expected_content = self.table_text(row, 5)
            if step_type == SCREW and required_count <= 0:
                QMessageBox.warning(self, "提示", f"第{row + 1}步螺丝数量必须大于0")
                return
            steps.append(
                ProcessStep(
                    name=name,
                    step_type=step_type,
                    required_count=required_count,
                    barcode_start=barcode_start,
                    barcode_end=barcode_end,
                    expected_content=expected_content,
                    is_main_barcode=step_type == SCAN and not any(item.step_type == SCAN for item in steps),
                )
            )

        if not steps:
            QMessageBox.warning(self, "提示", "至少需要一个工序")
            return
        self.current_product.steps = steps
        self.reset_current_product(update_table=True)
        self.message_label.setText("工序参数配置已保存，等待第1工序条码进入")

    def table_text(self, row: int, column: int) -> str:
        item = self.step_table.item(row, column)
        return item.text().strip() if item else ""

    def to_int(self, value: str, default: int) -> int:
        try:
            return int(value)
        except ValueError:
            return default
