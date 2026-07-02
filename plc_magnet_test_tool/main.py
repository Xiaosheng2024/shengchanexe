import configparser
import os
import shutil
import sys
import threading
from datetime import datetime
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt5.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from plc_magnet_test_tool.logic import (
    MagnetAddresses,
    MagnetConfig,
    MagnetFlowController,
    evaluate_magnet_result,
    format_word,
)
from shared.s7_plc_client import S7PlcClient


def runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return CURRENT_DIR


BASE_DIR = runtime_dir()
CONFIG_PATH = BASE_DIR / "config.ini"
EXAMPLE_CONFIG_PATH = (
    Path(getattr(sys, "_MEIPASS", CURRENT_DIR))
    / "config.example.ini"
)


def ensure_config_file() -> Path:
    if not CONFIG_PATH.exists():
        source = (
            EXAMPLE_CONFIG_PATH
            if EXAMPLE_CONFIG_PATH.exists()
            else CURRENT_DIR / "config.example.ini"
        )
        shutil.copyfile(source, CONFIG_PATH)
    return CONFIG_PATH


def load_parser() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(ensure_config_file(), encoding="utf-8")
    return parser


class TaskRunner(QObject):
    log = pyqtSignal(str)
    connection_state = pyqtSignal(str, str)
    snapshot = pyqtSignal(dict)
    operation_done = pyqtSignal(str, object)
    busy_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.client = None
        self.controller = None
        self.busy = False
        self.cancel_event = threading.Event()
        self._lock = threading.Lock()

    def submit(self, name, action):
        with self._lock:
            if self.busy:
                self.log.emit("已有PLC操作正在执行，请稍候")
                return False
            self.busy = True
        self.cancel_event.clear()
        self.busy_changed.emit(True)

        def run():
            try:
                result = action()
                self.operation_done.emit(name, result)
            except Exception as exc:
                self.log.emit(f"{name}失败：{exc}")
                self.operation_done.emit(
                    name,
                    {"ok": False, "error": str(exc)},
                )
            finally:
                with self._lock:
                    self.busy = False
                self.busy_changed.emit(False)

        threading.Thread(target=run, daemon=True).start()
        return True

    def connect_plc(self, settings, magnet_config):
        def action():
            self.connection_state.emit("连接中", "")
            if self.client:
                self.client.disconnect()
            self.client = S7PlcClient(
                settings["ip"],
                settings["rack"],
                settings["slot"],
                settings["timeout_seconds"],
            )
            self.client.connect()
            self.controller = MagnetFlowController(
                self.client,
                magnet_config,
                log=self.log.emit,
                cancelled=self.cancel_event.is_set,
            )
            self.connection_state.emit("已连接", "")
            self.log.emit(f"已连接 PLC {settings['ip']}")
            return {"ok": True}

        return self.submit("连接PLC", action)

    def test_connection(self, settings):
        def action():
            client = S7PlcClient(
                settings["ip"],
                settings["rack"],
                settings["slot"],
                settings["timeout_seconds"],
            )
            try:
                client.connect()
                self.log.emit(f"测试连接成功：{settings['ip']}")
                return {"ok": True}
            finally:
                client.disconnect()

        return self.submit("测试连接", action)

    def disconnect_plc(self):
        self.cancel_event.set()
        with self._lock:
            if self.busy:
                return False

        def action():
            if self.client:
                self.client.disconnect()
            self.client = None
            self.controller = None
            self.connection_state.emit("未连接", "")
            self.log.emit("PLC已断开")
            return {"ok": True}

        return self.submit("断开PLC", action)

    def require_controller(self):
        if not self.controller or not self.client or not self.client.is_connected():
            raise RuntimeError("PLC未连接")
        return self.controller

    def run_controller(self, name, action):
        return self.submit(name, lambda: action(self.require_controller()))

    def stop(self):
        self.cancel_event.set()
        if self.client:
            try:
                self.client.disconnect()
            except Exception:
                pass


class MagnetTestWindow(QMainWindow):
    WORD_ROWS = [
        ("barcode_ok", "DBW0", "条码校验合格 / 准备完成"),
        ("cylinder_clamped", "DBW2", "气缸夹紧信号"),
        ("screw_complete", "DBW4", "拧紧合格完成信号"),
        ("magnet_complete", "DBW6", "磁通量检测完成信号"),
        ("mes_read_done", "DBW8", "MES读取磁通量结果完成信号"),
        ("left_polarity", "DBW14", "左极性"),
        ("left_result", "DBW16", "左判定结果"),
        ("right_polarity", "DBW22", "右极性"),
        ("right_result", "DBW24", "右判定结果"),
    ]
    FLUX_ROWS = [
        ("left_flux", "DBD10", "左磁通量"),
        ("right_flux", "DBD18", "右磁通量"),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PLC磁吸流程调试工具")
        self.resize(1280, 900)
        self.parser = load_parser()
        self.runner = TaskRunner()
        self.last_snapshot = {}
        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self.read_all)
        self.build_ui()
        self.load_config_to_ui()
        self.connect_runner()

    def build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        self.setCentralWidget(root)

        notice = QLabel(
            "现场确认：1. MES只写1，不写0；2. DBW0、DBW4、DBW8由PLC复位；"
            "3. MES写1后立即读回确认；4. 未读回1时需结合PLC在线监控，"
            "可能写入失败或PLC已快速复位；5. DBD10、DBD18按Siemens REAL读取；"
            "6. DBW16、DBW24按1=合格、0=不合格判断。"
        )
        notice.setWordWrap(True)
        notice.setStyleSheet(
            "font-size:16px;font-weight:700;color:#9a3412;"
            "background:#fff7ed;padding:10px;border:1px solid #fdba74;"
        )
        layout.addWidget(notice)

        connection = QGroupBox("PLC连接配置")
        connection_grid = QGridLayout(connection)
        self.ip_input = QLineEdit()
        self.rack_input = QSpinBox()
        self.slot_input = QSpinBox()
        self.db_input = QSpinBox()
        self.poll_input = QSpinBox()
        self.timeout_input = QSpinBox()
        self.retry_input = QSpinBox()
        self.verify_interval_input = QSpinBox()
        self.rack_input.setRange(0, 10)
        self.slot_input.setRange(0, 10)
        self.db_input.setRange(1, 65535)
        self.poll_input.setRange(50, 10000)
        self.timeout_input.setRange(1, 300)
        self.retry_input.setRange(1, 20)
        self.verify_interval_input.setRange(10, 5000)
        fields = [
            ("PLC IP", self.ip_input),
            ("Rack", self.rack_input),
            ("Slot", self.slot_input),
            ("DB号", self.db_input),
            ("轮询周期ms", self.poll_input),
            ("超时时间秒", self.timeout_input),
            ("写入读回次数", self.retry_input),
            ("读回间隔ms", self.verify_interval_input),
        ]
        for index, (label, widget) in enumerate(fields):
            connection_grid.addWidget(QLabel(label), index // 4 * 2, index % 4)
            connection_grid.addWidget(widget, index // 4 * 2 + 1, index % 4)
        button_row = QHBoxLayout()
        self.connect_btn = QPushButton("连接PLC")
        self.disconnect_btn = QPushButton("断开PLC")
        self.test_btn = QPushButton("测试连接")
        self.read_btn = QPushButton("读取全部DB221")
        self.auto_start_btn = QPushButton("开始自动刷新")
        self.auto_stop_btn = QPushButton("停止自动刷新")
        for button in (
            self.connect_btn,
            self.disconnect_btn,
            self.test_btn,
            self.read_btn,
            self.auto_start_btn,
            self.auto_stop_btn,
        ):
            button_row.addWidget(button)
        connection_grid.addLayout(button_row, 4, 0, 1, 4)
        self.connection_label = QLabel("未连接")
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color:#dc2626;")
        connection_grid.addWidget(QLabel("连接状态"), 5, 0)
        connection_grid.addWidget(self.connection_label, 5, 1)
        connection_grid.addWidget(QLabel("最近错误"), 5, 2)
        connection_grid.addWidget(self.error_label, 5, 3)
        layout.addWidget(connection)

        write_group = QGroupBox("MES写PLC（只写1）")
        write_row = QHBoxLayout(write_group)
        self.write_dbw0_btn = QPushButton("写 条码校验合格 / 准备完成")
        self.write_dbw4_btn = QPushButton("写 拧紧合格完成")
        self.write_dbw8_btn = QPushButton("写 MES读取结果完成 / 通知PLC解锁")
        for button in (
            self.write_dbw0_btn,
            self.write_dbw4_btn,
            self.write_dbw8_btn,
        ):
            button.setMinimumHeight(44)
            write_row.addWidget(button)
        layout.addWidget(write_group)

        content = QHBoxLayout()
        read_group = QGroupBox("PLC读取显示")
        read_layout = QVBoxLayout(read_group)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("磁通量解析"))
        self.flux_mode_combo = QComboBox()
        self.flux_mode_combo.addItems(["REAL", "DWord整数"])
        mode_row.addWidget(self.flux_mode_combo)
        mode_row.addStretch(1)
        self.overall_label = QLabel("磁吸判定：未读取")
        self.overall_label.setStyleSheet("font-size:18px;font-weight:700;")
        mode_row.addWidget(self.overall_label)
        read_layout.addLayout(mode_row)
        self.value_table = QTableWidget(0, 3)
        self.value_table.setHorizontalHeaderLabels(["地址", "说明", "当前值"])
        self.value_table.horizontalHeader().setStretchLastSection(True)
        self.value_items = {}
        for key, address, description in self.WORD_ROWS + self.FLUX_ROWS:
            row = self.value_table.rowCount()
            self.value_table.insertRow(row)
            self.value_table.setItem(row, 0, QTableWidgetItem(f"DB221.{address}"))
            self.value_table.setItem(row, 1, QTableWidgetItem(description))
            value_item = QTableWidgetItem("未读取")
            self.value_table.setItem(row, 2, value_item)
            self.value_items[key] = value_item
        read_layout.addWidget(self.value_table)
        content.addWidget(read_group, 3)

        step_group = QGroupBox("单步 / 一键流程测试")
        step_layout = QVBoxLayout(step_group)
        self.step1_btn = QPushButton("第一步：写 DBW0=1，并读回确认")
        self.step2_btn = QPushButton("第二步：等待气缸夹紧 DBW2=1")
        self.step3_btn = QPushButton("第三步：写 DBW4=1，并读回确认")
        self.step4_btn = QPushButton("第四步：等待磁吸检测完成 DBW6=1")
        self.step5_btn = QPushButton("第五步：读取磁吸结果")
        self.step6_btn = QPushButton("第六步：磁吸OK后写 DBW8=1")
        self.flow_btn = QPushButton("一键流程测试")
        self.flow_btn.setStyleSheet(
            "font-size:18px;font-weight:700;background:#2563eb;color:white;"
        )
        for button in (
            self.step1_btn,
            self.step2_btn,
            self.step3_btn,
            self.step4_btn,
            self.step5_btn,
            self.step6_btn,
            self.flow_btn,
        ):
            button.setMinimumHeight(45)
            step_layout.addWidget(button)
        step_layout.addStretch(1)
        content.addWidget(step_group, 2)
        layout.addLayout(content, 1)

        log_group = QGroupBox("操作日志")
        log_layout = QVBoxLayout(log_group)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        log_layout.addWidget(self.log_edit)
        layout.addWidget(log_group, 1)

        self.connect_btn.clicked.connect(self.connect_plc)
        self.disconnect_btn.clicked.connect(self.disconnect_plc)
        self.test_btn.clicked.connect(self.test_connection)
        self.read_btn.clicked.connect(self.read_all)
        self.auto_start_btn.clicked.connect(self.start_auto_refresh)
        self.auto_stop_btn.clicked.connect(self.stop_auto_refresh)
        self.write_dbw0_btn.clicked.connect(lambda: self.write_one(0))
        self.write_dbw4_btn.clicked.connect(lambda: self.write_one(4))
        self.write_dbw8_btn.clicked.connect(lambda: self.write_one(8))
        self.step1_btn.clicked.connect(lambda: self.write_one(0))
        self.step2_btn.clicked.connect(self.wait_cylinder)
        self.step3_btn.clicked.connect(lambda: self.write_one(4))
        self.step4_btn.clicked.connect(self.wait_magnet)
        self.step5_btn.clicked.connect(self.read_results)
        self.step6_btn.clicked.connect(self.finish_if_ok)
        self.flow_btn.clicked.connect(self.run_full_flow)

    def connect_runner(self):
        self.runner.log.connect(self.append_log)
        self.runner.connection_state.connect(self.set_connection_state)
        self.runner.snapshot.connect(self.render_snapshot)
        self.runner.operation_done.connect(self.operation_done)
        self.runner.busy_changed.connect(self.set_busy)

    def load_config_to_ui(self):
        parser = self.parser
        self.ip_input.setText(
            parser.get("PLC", "ip", fallback="192.168.111.50")
        )
        self.rack_input.setValue(parser.getint("PLC", "rack", fallback=0))
        self.slot_input.setValue(parser.getint("PLC", "slot", fallback=1))
        self.db_input.setValue(parser.getint("PLC", "db", fallback=221))
        self.poll_input.setValue(
            parser.getint("PLC", "poll_interval_ms", fallback=800)
        )
        self.timeout_input.setValue(
            parser.getint("PLC", "timeout_seconds", fallback=30)
        )
        self.retry_input.setValue(
            parser.getint("PLC", "write_verify_retry_count", fallback=3)
        )
        self.verify_interval_input.setValue(
            parser.getint("PLC", "write_verify_interval_ms", fallback=100)
        )

    def settings(self):
        return {
            "ip": self.ip_input.text().strip(),
            "rack": self.rack_input.value(),
            "slot": self.slot_input.value(),
            "timeout_seconds": self.timeout_input.value(),
        }

    def magnet_config(self):
        parser = self.parser
        address = lambda key, fallback: parser.getint(
            "ADDRESS", key, fallback=fallback
        )
        return MagnetConfig(
            db_number=self.db_input.value(),
            poll_interval_ms=self.poll_input.value(),
            timeout_seconds=self.timeout_input.value(),
            write_verify_retry_count=self.retry_input.value(),
            write_verify_interval_ms=self.verify_interval_input.value(),
            addresses=MagnetAddresses(
                barcode_ok=address("barcode_ok_offset", 0),
                cylinder_clamped=address("cylinder_clamped_offset", 2),
                screw_complete=address("screw_complete_offset", 4),
                magnet_complete=address("magnet_complete_offset", 6),
                mes_read_done=address("mes_read_done_offset", 8),
                left_flux=address("left_flux_offset", 10),
                left_polarity=address("left_polarity_offset", 14),
                left_result=address("left_result_offset", 16),
                right_flux=address("right_flux_offset", 18),
                right_polarity=address("right_polarity_offset", 22),
                right_result=address("right_result_offset", 24),
            ),
        )

    def flux_mode(self):
        return "DWORD" if self.flux_mode_combo.currentIndex() == 1 else "REAL"

    def connect_plc(self):
        self.runner.connect_plc(self.settings(), self.magnet_config())

    def test_connection(self):
        self.runner.test_connection(self.settings())

    def disconnect_plc(self):
        self.stop_auto_refresh()
        self.runner.cancel_event.set()
        if not self.runner.disconnect_plc():
            QTimer.singleShot(100, self.disconnect_plc)

    def write_one(self, offset):
        self.runner.run_controller(
            f"写DBW{offset}=1并读回",
            lambda controller: controller.write_one_and_verify(offset),
        )

    def wait_cylinder(self):
        self.runner.run_controller(
            "等待气缸夹紧",
            lambda controller: controller.wait_word(
                controller.config.addresses.cylinder_clamped,
                1,
                "气缸夹紧成功。",
                "气缸夹紧超时。",
            ),
        )

    def wait_magnet(self):
        self.runner.run_controller(
            "等待磁吸检测完成",
            lambda controller: controller.wait_word(
                controller.config.addresses.magnet_complete,
                1,
                "磁吸检测完成。",
                "磁吸检测超时。",
            ),
        )

    def read_all(self):
        self.runner.run_controller(
            "读取全部DB221",
            lambda controller: controller.read_all(self.flux_mode()),
        )

    def read_results(self):
        self.runner.run_controller(
            "读取磁吸结果",
            lambda controller: controller.read_all(self.flux_mode()),
        )

    def finish_if_ok(self):
        if evaluate_magnet_result(
            self.last_snapshot.get("left_result"),
            self.last_snapshot.get("right_result"),
        ) != "OK":
            self.append_log("磁吸检测 NG 或结果未知，不写DBW8，不通知解锁")
            return
        self.write_one(8)

    def run_full_flow(self):
        self.runner.run_controller(
            "一键流程测试",
            lambda controller: controller.run_flow(self.flux_mode()),
        )

    def start_auto_refresh(self):
        self.auto_timer.start(self.poll_input.value())
        self.append_log("已开始自动刷新")

    def stop_auto_refresh(self):
        self.auto_timer.stop()
        self.append_log("已停止自动刷新")

    def append_log(self, message):
        self.log_edit.append(
            f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        )

    def set_connection_state(self, state, error):
        self.connection_label.setText(state)
        self.error_label.setText(error)
        if state == "已连接":
            self.connection_label.setStyleSheet(
                "color:#16a34a;font-weight:700;"
            )
        elif state in {"连接失败", "未连接"}:
            self.connection_label.setStyleSheet("color:#dc2626;")

    def set_busy(self, busy):
        self.flow_btn.setEnabled(not busy)

    def operation_done(self, name, result):
        if isinstance(result, dict) and result.get("error"):
            self.error_label.setText(result["error"])
            self.connection_label.setText("连接失败")
        if name in {"读取全部DB221", "读取磁吸结果"} and isinstance(result, dict):
            if "left_result" in result:
                self.render_snapshot(result)
        if name == "一键流程测试" and isinstance(result, dict):
            values = result.get("values")
            if values:
                self.render_snapshot(values)
            if result.get("ok"):
                self.append_log("流程完成，已通知 PLC 解锁")
            elif result.get("stage") == "magnet_ng":
                self.append_log("磁吸检测 NG，不通知解锁")

    def render_snapshot(self, values):
        self.last_snapshot = dict(values)
        for key, _, _ in self.WORD_ROWS:
            if key not in values:
                continue
            value = values[key]
            text = format_word(value)
            if key in {"left_result", "right_result"}:
                meaning = "合格" if value == 1 else "不合格" if value == 0 else "未知状态"
                text += f"（{meaning}）"
            self.value_items[key].setText(text)
        for key, _, _ in self.FLUX_ROWS:
            if key in values:
                mode = values.get("flux_mode", self.flux_mode())
                text = (
                    str(int(values[key]))
                    if mode == "DWORD"
                    else f"{float(values[key]):.4f}"
                )
                self.value_items[key].setText(text)
        result = values.get("overall_result", "UNKNOWN")
        text = {
            "OK": "磁吸判定：OK",
            "NG": "磁吸判定：NG",
            "UNKNOWN": "磁吸判定：未知状态",
        }.get(result, f"磁吸判定：{result}")
        self.overall_label.setText(text)
        color = "#16a34a" if result == "OK" else "#dc2626"
        self.overall_label.setStyleSheet(
            f"font-size:18px;font-weight:700;color:{color};"
        )

    def closeEvent(self, event):
        self.auto_timer.stop()
        self.runner.stop()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    window = MagnetTestWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
