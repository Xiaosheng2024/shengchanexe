import shutil
import subprocess
import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime
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
from shared.models import ProcessStep, ProductConfig, ProjectConfig, StationConfig, SCAN, SCREW


class QualityControlWindow(QMainWindow):
    tool_worker_write_requested = pyqtSignal(int, int)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("生产工艺过程质量控制系统")
        self.resize(1280, 820)

        self.projects = self.default_projects()
        self.current_project: ProjectConfig = self.projects[0]
        self.current_station: StationConfig = self.current_project.stations[0]
        self.products = [station.product for station in self.current_project.stations]
        self.current_product: ProductConfig = self.current_station.product
        self.current_step_index = 0
        self.online_mode = False
        self.current_barcode = ""
        self.screw_blocks: List[QLabel] = []
        self.warning_dialogs: List[QMessageBox] = []
        self.finished_part_count = 0
        self.scan_error_count = 0
        self.history_records = []
        self.step_started_at = datetime.now()
        self.settings_dialog: Optional[QDialog] = None
        self.history_dialog: Optional[QDialog] = None
        self.last_voice_step_key = None
        self.say_command = shutil.which("say")
        self.tool_thread: Optional[QThread] = None
        self.tool_worker: Optional[ToolPollWorker] = None
        self.processing_tool_signal = False
        self.waiting_tool_trigger_reset = False

        self.build_ui()
        self.refresh_project_station_selectors()
        self.load_station(self.current_project.name, self.current_station.name)

    def default_projects(self) -> List[ProjectConfig]:
        stations = []
        for index in range(1, 10):
            stations.append(
                StationConfig(
                    f"工位{index}",
                    ProductConfig(
                        f"汽车前中控面板X04C 灰色 - 工位{index}",
                        [
                            ProcessStep("扫码A零件", SCAN, barcode_start=1, barcode_end=1, expected_content="A", is_main_barcode=True),
                            ProcessStep("扫码B零件条码", SCAN, barcode_start=1, barcode_end=1, expected_content="B"),
                            ProcessStep("打螺丝10颗", SCREW, required_count=10),
                            ProcessStep("扫码C零件", SCAN, barcode_start=1, barcode_end=1, expected_content="C"),
                        ],
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
        reset_btn = QPushButton("重新开始当前产品")
        reset_btn.clicked.connect(self.reset_current_product)
        action_row.addWidget(self.screw_ok_btn)
        action_row.addWidget(reset_btn)
        right_layout.addLayout(action_row)

        tool_box = QGroupBox("螺钉枪TCP OK信号")
        tool_layout = QHBoxLayout(tool_box)
        self.tool_ip_input = QLineEdit("192.168.1.100")
        self.tool_ip_input.setPlaceholderText("设备IP")
        self.tool_port_input = QSpinBox()
        self.tool_port_input.setRange(1, 65535)
        self.tool_port_input.setValue(502)
        self.tool_unit_input = QSpinBox()
        self.tool_unit_input.setRange(1, 247)
        self.tool_unit_input.setValue(1)
        self.tool_status_register_input = QSpinBox()
        self.tool_status_register_input.setRange(0, 65535)
        self.tool_status_register_input.setValue(100)
        self.tool_ok_value_input = QSpinBox()
        self.tool_ok_value_input.setRange(0, 65535)
        self.tool_ok_value_input.setValue(2)
        self.tool_ng_value_input = QSpinBox()
        self.tool_ng_value_input.setRange(0, 65535)
        self.tool_ng_value_input.setValue(3)
        self.tool_trigger_register_input = QSpinBox()
        self.tool_trigger_register_input.setRange(0, 65535)
        self.tool_trigger_register_input.setValue(53)
        self.tool_trigger_value_input = QSpinBox()
        self.tool_trigger_value_input.setRange(0, 65535)
        self.tool_trigger_value_input.setValue(1)
        self.tool_trigger_reset_value_input = QSpinBox()
        self.tool_trigger_reset_value_input.setRange(0, 65535)
        self.tool_trigger_reset_value_input.setValue(0)
        self.tool_control_register_input = QSpinBox()
        self.tool_control_register_input.setRange(0, 65535)
        self.tool_control_register_input.setValue(4)
        self.tool_on_value_input = QSpinBox()
        self.tool_on_value_input.setRange(0, 65535)
        self.tool_on_value_input.setValue(2)
        self.tool_off_value_input = QSpinBox()
        self.tool_off_value_input.setRange(0, 65535)
        self.tool_off_value_input.setValue(1)
        self.tool_poll_interval_input = QSpinBox()
        self.tool_poll_interval_input.setRange(200, 5000)
        self.tool_poll_interval_input.setSingleStep(100)
        self.tool_poll_interval_input.setValue(800)
        self.tool_timeout_input = QSpinBox()
        self.tool_timeout_input.setRange(1, 10)
        self.tool_timeout_input.setValue(1)
        self.disable_tool_auto_listen_checkbox = QCheckBox("禁用螺钉枪自动监听")
        self.disable_tool_auto_listen_checkbox.setToolTip("现场临时保护：勾选后不启动螺钉枪后台监听，可用模拟OK按钮测试流程")
        self.tool_connect_btn = QPushButton("连接")
        self.tool_connect_btn.clicked.connect(self.toggle_tool_connection)
        self.tool_status_label = QLabel("未连接")
        self.tool_status_label.setStyleSheet("font-size: 16px; color: #6b7280;")
        for label_text, widget in [
            ("IP", self.tool_ip_input),
            ("端口", self.tool_port_input),
            ("站号", self.tool_unit_input),
            ("状态地址", self.tool_status_register_input),
            ("OK值", self.tool_ok_value_input),
            ("NG值", self.tool_ng_value_input),
            ("触发地址", self.tool_trigger_register_input),
            ("开关地址", self.tool_control_register_input),
            ("轮询ms", self.tool_poll_interval_input),
            ("超时秒", self.tool_timeout_input),
        ]:
            tool_layout.addWidget(QLabel(label_text))
            tool_layout.addWidget(widget)
        tool_layout.addWidget(self.disable_tool_auto_listen_checkbox)
        tool_layout.addWidget(self.tool_connect_btn)
        tool_layout.addWidget(self.tool_status_label, 1)
        right_layout.addWidget(tool_box)

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
        self.message_label.setText("在线模式：请先下载配置" if self.online_mode else "离线模式：使用本地配置")

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
        project = next((item for item in self.projects if item.name == project_name), None)
        if project is None:
            return
        self.current_project = project
        self.current_station = project.stations[0]
        self.refresh_station_selector()
        self.load_station(project.name, self.current_station.name)

    def on_station_selected(self, station_name: str):
        if station_name:
            self.load_station(self.current_project.name, station_name)

    def load_station(self, project_name: str, station_name: str):
        if self.is_tool_worker_running():
            self.stop_tool_worker()
        project = next((item for item in self.projects if item.name == project_name), None)
        if project is None:
            return
        station = next((item for item in project.stations if item.name == station_name), None)
        if station is None:
            return
        self.current_project = project
        self.current_station = station
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
        self.reset_current_product(update_table=True)

    def download_online_config(self):
        if not self.online_mode:
            self.message_label.setText("当前是离线模式，不需要下载配置")
            return
        project_name = self.project_combo.currentText().strip()
        station_name = self.station_combo.currentText().strip()
        if not project_name or not station_name:
            self.message_label.setText("请先选择项目和工位")
            return
        try:
            data = self.api_get(f"/api/projects/{urllib.parse.quote(project_name)}/stations/{urllib.parse.quote(station_name)}/config")
            product = self.product_from_api(data)
        except Exception as exc:
            QMessageBox.warning(self, "下载配置失败", str(exc))
            return
        self.current_station.product = product
        self.load_station(project_name, station_name)
        self.message_label.setText("在线配置已下载")

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
                    is_main_barcode=bool(item.get("is_main_barcode", False)),
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
        self.barcode_input.clear()
        self.message_label.setText("等待第1工序条码进入")
        if update_table:
            self.populate_step_table()
        self.refresh_work_area()
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
            self.barcode_input.setEnabled(True)
        else:
            self.current_step_label.setText(f"当前工序：{current_step.name}")
            self.screw_ok_btn.setEnabled(current_step.step_type == SCREW)
            self.barcode_input.setEnabled(current_step.step_type == SCAN)
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
            if step.step_type == SCAN and step.is_main_barcode:
                return step
        return next((step for step in self.current_product.steps if step.step_type == SCAN), None)

    def ensure_main_barcode(self, product: ProductConfig, notify: bool = False):
        scan_steps = [step for step in product.steps if step.step_type == SCAN]
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
        step = self.current_step()
        if step is None:
            self.reset_current_product()
            step = self.current_step()
        if step is None or step.step_type != SCAN:
            self.message_label.setText("当前工序需要等待螺钉枪OK信号")
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

        if self.disable_tool_auto_listen_checkbox.isChecked():
            self.message_label.setText("已禁用螺钉枪自动监听，可使用模拟OK按钮测试流程")
            self.tool_status_label.setText("自动监听已禁用")
            self.tool_status_label.setStyleSheet("font-size: 16px; color: #6b7280;")
            return

        config = ToolPollConfig(
            host=self.tool_ip_input.text().strip(),
            port=self.tool_port_input.value(),
            unit_id=self.tool_unit_input.value(),
            status_register=self.tool_status_register_input.value(),
            trigger_register=self.tool_trigger_register_input.value(),
            timeout_seconds=float(self.tool_timeout_input.value()),
            poll_interval_ms=self.tool_poll_interval_input.value(),
        )
        self.tool_thread = QThread(self)
        self.tool_worker = ToolPollWorker(config)
        self.tool_worker.moveToThread(self.tool_thread)
        self.tool_thread.started.connect(self.tool_worker.start)
        self.tool_worker_write_requested.connect(self.tool_worker.write_register)
        self.tool_worker.result.connect(self.on_tool_poll_result)
        self.tool_worker.error.connect(self.on_tool_poll_error)
        self.tool_worker.write_error.connect(self.on_tool_write_error)
        self.tool_worker.stopped.connect(self.tool_thread.quit)
        self.tool_thread.finished.connect(self.tool_worker.deleteLater)
        self.tool_thread.finished.connect(self.cleanup_tool_worker)
        self.tool_thread.start()
        self.tool_connect_btn.setText("断开")
        self.tool_status_label.setText("已启动轮询")
        self.tool_status_label.setStyleSheet("font-size: 16px; color: #2563eb;")

    def is_tool_worker_running(self) -> bool:
        return self.tool_thread is not None and self.tool_thread.isRunning()

    def stop_tool_worker(self):
        if self.tool_thread is not None:
            if self.tool_worker is not None and self.tool_thread.isRunning():
                QMetaObject.invokeMethod(self.tool_worker, "stop", Qt.BlockingQueuedConnection)
            self.tool_thread.quit()
            self.tool_thread.wait(2500)
        self.cleanup_tool_worker()

    def cleanup_tool_worker(self):
        self.tool_worker = None
        self.tool_thread = None
        self.processing_tool_signal = False
        self.waiting_tool_trigger_reset = False
        if hasattr(self, "tool_connect_btn"):
            self.tool_connect_btn.setText("连接")
        if hasattr(self, "tool_status_label"):
            self.tool_status_label.setText("未连接")
            self.tool_status_label.setStyleSheet("font-size: 16px; color: #6b7280;")

    def on_tool_poll_error(self, message: str):
        logging.error("螺钉枪通讯异常：%s", message)
        self.tool_status_label.setText(f"螺钉枪通讯异常：{message}")
        self.tool_status_label.setStyleSheet("font-size: 16px; color: #dc2626;")

    def on_tool_write_error(self, message: str):
        logging.error("螺钉枪写入异常：%s", message)
        self.tool_status_label.setText(f"螺钉枪写入异常：{message}")
        self.tool_status_label.setStyleSheet("font-size: 16px; color: #dc2626;")

    def on_tool_poll_result(self, status: int, trigger: int):
        if self.processing_tool_signal:
            return
        self.processing_tool_signal = True
        try:
            self.process_tool_poll_result(status, trigger)
        finally:
            self.processing_tool_signal = False

    def process_tool_poll_result(self, status: int, trigger: int):

        ok_value = self.tool_ok_value_input.value()
        ng_value = self.tool_ng_value_input.value()
        trigger_value = self.tool_trigger_value_input.value()
        trigger_reset_value = self.tool_trigger_reset_value_input.value()
        status_text = self.tightening_status_text(status)
        self.tool_status_label.setText(
            f"触发：{trigger}，状态：{status}-{status_text}，OK={'是' if status == ok_value else '否'}"
        )
        self.tool_status_label.setStyleSheet("font-size: 16px; color: #16a34a;")

        if trigger == trigger_reset_value:
            self.waiting_tool_trigger_reset = False
            return
        if trigger != trigger_value:
            return
        if self.waiting_tool_trigger_reset:
            return

        if status == ok_value:
            self.waiting_tool_trigger_reset = True
            self.reset_tool_trigger()
            self.handle_screw_ok()
            return

        if status == ng_value:
            self.waiting_tool_trigger_reset = True
            self.add_screw_ng_record()
            self.speak("螺丝NG，请重新打当前这颗")
            self.show_auto_close_warning("螺丝NG", "螺丝NG，请重新打当前这颗")
            self.reset_tool_trigger()
            return

        if status == 4:
            self.message_label.setText("螺钉枪暂停")
            return

    def write_tool_register(self, register_address: int, value: int):
        if not self.is_tool_worker_running():
            return
        self.tool_worker_write_requested.emit(register_address, value)

    def reset_tool_trigger(self):
        self.write_tool_register(self.tool_trigger_register_input.value(), self.tool_trigger_reset_value_input.value())

    def add_screw_ng_record(self):
        step = self.current_step()
        if step is None or step.step_type != SCREW:
            return
        self.add_history_record(step, "NG", "螺钉枪NG", "螺丝NG，请重新打当前这颗", completed=False)
        self.message_label.setText("螺丝NG，请重新打当前这颗")

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
        super().closeEvent(event)

    def prompt_current_step_start(self):
        step = self.current_step()
        if step is None:
            return
        step_key = (self.current_product.name, self.current_step_index, step.name)
        if self.last_voice_step_key == step_key:
            return
        self.last_voice_step_key = step_key
        if step.step_type == SCREW:
            self.enter_tool_screw_step(step)
            self.speak(f"请打螺丝{step.required_count}颗")
        else:
            self.speak("请扫码")

    def enter_tool_screw_step(self, step: ProcessStep):
        if not self.is_tool_worker_running():
            return
        try:
            self.reset_tool_trigger()
            self.write_tool_register(self.tool_control_register_input.value(), self.tool_on_value_input.value())
        except Exception as exc:
            self.tool_status_label.setText(f"螺钉枪初始化异常：{exc}")
            self.tool_status_label.setStyleSheet("font-size: 16px; color: #dc2626;")

    def close_tool_for_screw_step(self):
        if not self.is_tool_worker_running():
            return
        try:
            self.write_tool_register(self.tool_control_register_input.value(), self.tool_off_value_input.value())
            self.reset_tool_trigger()
        except Exception as exc:
            self.tool_status_label.setText(f"螺钉枪关闭异常：{exc}")
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
            self.post_scan_record_to_server(step, result, barcode, note, now)
        if self.history_dialog is not None and self.history_dialog.isVisible():
            self.refresh_history_tables()

    def post_scan_record_to_server(self, step: ProcessStep, result: str, barcode: str, note: str, created_at: datetime):
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
