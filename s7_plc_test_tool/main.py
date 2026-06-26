import configparser
import csv
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import (
    QApplication,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from shared.s7_plc_client import S7PlcClient, parse_barcode


CONFIG_PATH = BASE_DIR / "config.ini"


@dataclass
class BarcodeConfig:
    enabled: bool
    db_number: int
    offset: int
    length: int
    encoding: str
    remove_null: bool
    strip_space: bool


@dataclass
class ToolConfig:
    ip: str
    rack: int
    slot: int
    timeout_ms: int
    connect_retry_seconds: int
    poll_interval_ms: int
    parts_enabled: bool
    parts_db_number: int
    parts_offset: int
    parts_data_type: str
    parts_byte_order: str
    reset_when_decrease: bool
    barcode1: BarcodeConfig
    barcode2: BarcodeConfig
    trigger_mode: str
    record_on_startup: bool
    ignore_duplicate_barcode_pair: bool
    allow_empty_barcode: bool
    show_raw_bytes: bool
    show_hex: bool
    log_level: str
    save_csv: bool
    csv_file: Path
    log_file: Path


class QTextEditLogHandler(logging.Handler):
    def __init__(self, text_edit: QTextEdit):
        super().__init__()
        self.text_edit = text_edit

    def emit(self, record):
        message = self.format(record)
        self.text_edit.append(message)
        self.text_edit.moveCursor(self.text_edit.textCursor().End)


class S7ClientWrapper(S7PlcClient):
    def __init__(self, ip: str, rack: int, slot: int, timeout_ms: int):
        super().__init__(ip, rack, slot, timeout_ms / 1000)


def parse_bool(config: configparser.ConfigParser, section: str, key: str, fallback: bool) -> bool:
    return config.getboolean(section, key, fallback=fallback)


def load_config() -> ToolConfig:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"未找到配置文件：{CONFIG_PATH}")
    parser = configparser.ConfigParser()
    parser.read(CONFIG_PATH, encoding="utf-8")

    def barcode(section: str) -> BarcodeConfig:
        return BarcodeConfig(
            enabled=parse_bool(parser, section, "enabled", True),
            db_number=parser.getint(section, "db_number"),
            offset=parser.getint(section, "offset"),
            length=parser.getint(section, "length"),
            encoding=parser.get(section, "encoding", fallback="ascii"),
            remove_null=parse_bool(parser, section, "remove_null", True),
            strip_space=parse_bool(parser, section, "strip_space", True),
        )

    csv_file = BASE_DIR / parser.get("LOG", "csv_file", fallback="data/plc_records.csv")
    log_file = BASE_DIR / parser.get("LOG", "log_file", fallback="logs/plc_test.log")
    return ToolConfig(
        ip=parser.get("PLC", "ip"),
        rack=parser.getint("PLC", "rack"),
        slot=parser.getint("PLC", "slot"),
        timeout_ms=parser.getint("PLC", "timeout_ms", fallback=3000),
        connect_retry_seconds=parser.getint("PLC", "connect_retry_seconds", fallback=3),
        poll_interval_ms=parser.getint("PLC", "poll_interval_ms", fallback=500),
        parts_enabled=parse_bool(parser, "PARTS_OK", "enabled", True),
        parts_db_number=parser.getint("PARTS_OK", "db_number"),
        parts_offset=parser.getint("PARTS_OK", "offset"),
        parts_data_type=parser.get("PARTS_OK", "data_type", fallback="int"),
        parts_byte_order=parser.get("PARTS_OK", "byte_order", fallback="big"),
        reset_when_decrease=parse_bool(parser, "PARTS_OK", "reset_when_decrease", True),
        barcode1=barcode("BARCODE_1"),
        barcode2=barcode("BARCODE_2"),
        trigger_mode=parser.get("TRIGGER", "mode", fallback="parts_ok_increment"),
        record_on_startup=parse_bool(parser, "TRIGGER", "record_on_startup", False),
        ignore_duplicate_barcode_pair=parse_bool(parser, "TRIGGER", "ignore_duplicate_barcode_pair", True),
        allow_empty_barcode=parse_bool(parser, "TRIGGER", "allow_empty_barcode", False),
        show_raw_bytes=parse_bool(parser, "DISPLAY", "show_raw_bytes", True),
        show_hex=parse_bool(parser, "DISPLAY", "show_hex", True),
        log_level=parser.get("LOG", "log_level", fallback="INFO").upper(),
        save_csv=parse_bool(parser, "LOG", "save_csv", True),
        csv_file=csv_file,
        log_file=log_file,
    )


class S7PlcTestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("S7 PLC 条码读取测试工具")
        self.resize(1320, 860)
        self.config: Optional[ToolConfig] = None
        self.client: Optional[S7ClientWrapper] = None
        self.last_parts_ok: Optional[int] = None
        self.last_read_time = ""
        self.last_record_time = ""
        self.recorded_pairs = set()
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll_once)

        self.build_ui()
        self.load_config_to_ui()

    def build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        self.setCentralWidget(root)

        self.build_connection_group(layout)
        self.build_realtime_group(layout)
        self.build_barcode_group(layout)
        self.build_record_table(layout)
        self.build_log_group(layout)

    def build_connection_group(self, parent):
        group = QGroupBox("PLC连接区")
        grid = QGridLayout(group)
        self.ip_input = QLineEdit()
        self.rack_input = QLineEdit()
        self.slot_input = QLineEdit()
        self.status_label = QLabel("未连接")
        self.status_label.setStyleSheet("font-weight: 700; color: #6b7280;")
        self.connect_btn = QPushButton("连接PLC")
        self.disconnect_btn = QPushButton("断开PLC")
        self.start_btn = QPushButton("开始监听")
        self.stop_btn = QPushButton("停止监听")
        self.reload_btn = QPushButton("重新加载配置")
        self.connect_btn.clicked.connect(self.connect_plc)
        self.disconnect_btn.clicked.connect(self.disconnect_plc)
        self.start_btn.clicked.connect(self.start_listen)
        self.stop_btn.clicked.connect(self.stop_listen)
        self.reload_btn.clicked.connect(self.reload_config)

        widgets = [
            ("PLC IP", self.ip_input),
            ("Rack", self.rack_input),
            ("Slot", self.slot_input),
            ("连接状态", self.status_label),
        ]
        for col, (text, widget) in enumerate(widgets):
            grid.addWidget(QLabel(text), 0, col * 2)
            grid.addWidget(widget, 0, col * 2 + 1)
        for col, button in enumerate([self.connect_btn, self.disconnect_btn, self.start_btn, self.stop_btn, self.reload_btn]):
            grid.addWidget(button, 1, col)
        parent.addWidget(group)

    def build_realtime_group(self, parent):
        group = QGroupBox("实时数据区")
        grid = QGridLayout(group)
        self.parts_label = QLabel("-")
        self.last_parts_label = QLabel("-")
        self.increment_label = QLabel("-")
        self.last_read_label = QLabel("-")
        self.last_record_label = QLabel("-")
        self.process_status_label = QLabel("等待连接")
        for row, (text, widget) in enumerate(
            [
                ("当前 PARTS_OK", self.parts_label),
                ("上一次 PARTS_OK", self.last_parts_label),
                ("是否递增", self.increment_label),
                ("最近读取时间", self.last_read_label),
                ("最近记录时间", self.last_record_label),
                ("当前处理状态", self.process_status_label),
            ]
        ):
            grid.addWidget(QLabel(text), row // 3, (row % 3) * 2)
            grid.addWidget(widget, row // 3, (row % 3) * 2 + 1)
        parent.addWidget(group)

    def build_barcode_group(self, parent):
        group = QGroupBox("条码显示区")
        grid = QGridLayout(group)
        self.barcode1_addr_label = QLabel("-")
        self.barcode1_text_label = QLabel("-")
        self.barcode1_hex_text = QTextEdit()
        self.barcode1_hex_text.setReadOnly(True)
        self.barcode1_hex_text.setFixedHeight(58)
        self.barcode2_addr_label = QLabel("-")
        self.barcode2_text_label = QLabel("-")
        self.barcode2_hex_text = QTextEdit()
        self.barcode2_hex_text.setReadOnly(True)
        self.barcode2_hex_text.setFixedHeight(58)
        grid.addWidget(QLabel("条码1地址"), 0, 0)
        grid.addWidget(self.barcode1_addr_label, 0, 1)
        grid.addWidget(QLabel("条码1解析结果"), 1, 0)
        grid.addWidget(self.barcode1_text_label, 1, 1)
        grid.addWidget(QLabel("条码1原始HEX"), 2, 0)
        grid.addWidget(self.barcode1_hex_text, 2, 1)
        grid.addWidget(QLabel("条码2地址"), 0, 2)
        grid.addWidget(self.barcode2_addr_label, 0, 3)
        grid.addWidget(QLabel("条码2解析结果"), 1, 2)
        grid.addWidget(self.barcode2_text_label, 1, 3)
        grid.addWidget(QLabel("条码2原始HEX"), 2, 2)
        grid.addWidget(self.barcode2_hex_text, 2, 3)
        parent.addWidget(group)

    def build_record_table(self, parent):
        group = QGroupBox("记录表格区")
        layout = QVBoxLayout(group)
        self.record_table = QTableWidget(0, 8)
        self.record_table.setHorizontalHeaderLabels(
            ["时间", "PARTS_OK", "上一次PARTS_OK", "条码1", "条码2", "是否新记录", "结果", "说明"]
        )
        self.record_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.record_table)
        parent.addWidget(group, 1)

    def build_log_group(self, parent):
        group = QGroupBox("日志区")
        layout = QVBoxLayout(group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)
        parent.addWidget(group, 1)

    def load_config_to_ui(self):
        self.config = load_config()
        self.config.csv_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.configure_logging()
        self.ip_input.setText(self.config.ip)
        self.rack_input.setText(str(self.config.rack))
        self.slot_input.setText(str(self.config.slot))
        self.barcode1_addr_label.setText(
            f"DB{self.config.barcode1.db_number}.DBB{self.config.barcode1.offset} 长度{self.config.barcode1.length}"
        )
        self.barcode2_addr_label.setText(
            f"DB{self.config.barcode2.db_number}.DBB{self.config.barcode2.offset} 长度{self.config.barcode2.length}"
        )
        logging.info("配置已加载：%s", CONFIG_PATH)

    def configure_logging(self):
        logging.getLogger().handlers.clear()
        level = getattr(logging, self.config.log_level, logging.INFO)
        logging.getLogger().setLevel(level)
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        file_handler = logging.FileHandler(self.config.log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        ui_handler = QTextEditLogHandler(self.log_text)
        ui_handler.setFormatter(formatter)
        logging.getLogger().addHandler(file_handler)
        logging.getLogger().addHandler(ui_handler)

    def reload_config(self):
        was_listening = self.poll_timer.isActive()
        if was_listening:
            self.stop_listen()
        try:
            self.load_config_to_ui()
            self.last_parts_ok = None
            self.recorded_pairs.clear()
            self.set_process_status("配置已重新加载")
        except Exception as exc:
            self.show_error("重新加载配置失败", str(exc))

    def connect_plc(self):
        if self.client and self.client.is_connected():
            self.log_and_status("PLC已经连接")
            return
        self.config.ip = self.ip_input.text().strip()
        self.config.rack = int(self.rack_input.text().strip() or self.config.rack)
        self.config.slot = int(self.slot_input.text().strip() or self.config.slot)
        self.client = S7ClientWrapper(self.config.ip, self.config.rack, self.config.slot, self.config.timeout_ms)
        try:
            self.client.connect()
            self.status_label.setText("已连接")
            self.status_label.setStyleSheet("font-weight: 700; color: #16a34a;")
            self.log_and_status("PLC连接成功")
        except Exception as exc:
            self.status_label.setText("连接失败")
            self.status_label.setStyleSheet("font-weight: 700; color: #dc2626;")
            self.show_error("PLC连接失败", self.format_exception_message(exc))

    def disconnect_plc(self):
        self.stop_listen()
        if self.client:
            self.client.disconnect()
        self.status_label.setText("未连接")
        self.status_label.setStyleSheet("font-weight: 700; color: #6b7280;")
        self.log_and_status("PLC已断开")

    def start_listen(self):
        if not self.client or not self.client.is_connected():
            self.show_error("不能开始监听", "PLC未连接，请先点击“连接PLC”。")
            return
        self.poll_timer.start(self.config.poll_interval_ms)
        self.log_and_status(f"开始监听，周期 {self.config.poll_interval_ms} ms")

    def stop_listen(self):
        if self.poll_timer.isActive():
            self.poll_timer.stop()
            self.log_and_status("监听已停止")

    def poll_once(self):
        try:
            parts_ok = self.read_parts_ok()
            barcode1_text, barcode1_hex = self.read_barcode(self.config.barcode1)
            barcode2_text, barcode2_hex = self.read_barcode(self.config.barcode2)
            self.handle_poll_result(parts_ok, barcode1_text, barcode2_text, barcode1_hex, barcode2_hex)
        except Exception as exc:
            message = self.format_exception_message(exc)
            logging.exception("通讯异常：%s", message)
            self.set_process_status("通讯异常")
            QMessageBox.warning(self, "通讯异常", message)

    def read_parts_ok(self) -> int:
        if not self.config.parts_enabled:
            return 0
        if self.config.parts_data_type.lower() != "int":
            raise ValueError("当前工具只支持 PARTS_OK data_type = int")
        if self.config.parts_byte_order.lower() == "big":
            return self.client.read_int(self.config.parts_db_number, self.config.parts_offset)
        raw = self.client.read_bytes(self.config.parts_db_number, self.config.parts_offset, 2)
        return int.from_bytes(raw, byte_order=self.config.parts_byte_order.lower(), signed=True)

    def read_barcode(self, config: BarcodeConfig) -> Tuple[str, str]:
        if not config.enabled:
            return "", ""
        raw = self.client.read_bytes(config.db_number, config.offset, config.length)
        text, hex_text = parse_barcode(raw, config.encoding, config.remove_null, config.strip_space)
        return text, hex_text

    def handle_poll_result(self, parts_ok: int, barcode1: str, barcode2: str, barcode1_hex: str, barcode2_hex: str):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        old_last = self.last_parts_ok
        increment = old_last is not None and parts_ok > old_last
        self.update_realtime_display(parts_ok, old_last, increment, now, barcode1, barcode2, barcode1_hex, barcode2_hex)

        if old_last is None:
            if self.config.record_on_startup:
                self.record_success(now, parts_ok, old_last, barcode1, barcode2, barcode1_hex, barcode2_hex, "启动记录")
            else:
                self.set_process_status("首次读取，仅建立基准值")
                logging.info("首次读取，仅建立基准值：PARTS_OK=%s", parts_ok)
            self.last_parts_ok = parts_ok
            return

        if parts_ok == old_last:
            self.set_process_status("计数未变化，继续监听")
            return

        if parts_ok > old_last:
            self.set_process_status("检测到 PARTS_OK 递增")
            pair = (barcode1, barcode2)
            if not self.config.allow_empty_barcode and not barcode1 and not barcode2:
                self.add_table_row(now, parts_ok, old_last, barcode1, barcode2, False, "忽略", "条码为空，不记录")
                self.last_parts_ok = parts_ok
                self.log_and_status("条码为空，不记录")
                return
            if self.config.ignore_duplicate_barcode_pair and pair in self.recorded_pairs:
                self.add_table_row(now, parts_ok, old_last, barcode1, barcode2, False, "忽略", "重复条码组合，忽略")
                self.last_parts_ok = parts_ok
                self.log_and_status("重复条码组合，忽略")
                return
            self.record_success(now, parts_ok, old_last, barcode1, barcode2, barcode1_hex, barcode2_hex, "记录成功")
            self.last_parts_ok = parts_ok
            return

        if parts_ok < old_last:
            if self.config.reset_when_decrease:
                self.last_parts_ok = parts_ok
                self.add_table_row(now, parts_ok, old_last, barcode1, barcode2, False, "基准更新", "计数降低，已更新基准，不补记录")
                self.log_and_status("计数降低，已更新基准，不补记录")
            else:
                self.add_table_row(now, parts_ok, old_last, barcode1, barcode2, False, "警告", "PARTS_OK 降低，未更新基准")
                self.log_and_status("PARTS_OK 降低，PLC计数可能清零，按配置未更新基准")

    def update_realtime_display(
        self,
        parts_ok: int,
        last_parts_ok: Optional[int],
        increment: bool,
        now: str,
        barcode1: str,
        barcode2: str,
        barcode1_hex: str,
        barcode2_hex: str,
    ):
        self.last_read_time = now
        self.parts_label.setText(str(parts_ok))
        self.last_parts_label.setText("-" if last_parts_ok is None else str(last_parts_ok))
        self.increment_label.setText("是" if increment else "否")
        self.last_read_label.setText(now)
        self.last_record_label.setText(self.last_record_time or "-")
        self.barcode1_text_label.setText(barcode1 or "(空)")
        self.barcode2_text_label.setText(barcode2 or "(空)")
        self.barcode1_hex_text.setPlainText(barcode1_hex if self.config.show_hex else "")
        self.barcode2_hex_text.setPlainText(barcode2_hex if self.config.show_hex else "")

    def record_success(
        self,
        now: str,
        parts_ok: int,
        old_last: Optional[int],
        barcode1: str,
        barcode2: str,
        barcode1_hex: str,
        barcode2_hex: str,
        message: str,
    ):
        self.recorded_pairs.add((barcode1, barcode2))
        self.last_record_time = now
        self.last_record_label.setText(now)
        if self.config.save_csv:
            self.append_csv(now, parts_ok, old_last, barcode1, barcode2, barcode1_hex, barcode2_hex, "新记录", message)
        self.add_table_row(now, parts_ok, old_last, barcode1, barcode2, True, "新记录", message)
        self.log_and_status(message)

    def append_csv(
        self,
        now: str,
        parts_ok: int,
        old_last: Optional[int],
        barcode1: str,
        barcode2: str,
        barcode1_hex: str,
        barcode2_hex: str,
        result: str,
        message: str,
    ):
        file_exists = self.config.csv_file.exists()
        with self.config.csv_file.open("a", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=[
                    "time",
                    "plc_ip",
                    "parts_ok",
                    "last_parts_ok",
                    "barcode1",
                    "barcode2",
                    "barcode1_hex",
                    "barcode2_hex",
                    "result",
                    "message",
                ],
            )
            if not file_exists:
                writer.writeheader()
            writer.writerow(
                {
                    "time": now,
                    "plc_ip": self.config.ip,
                    "parts_ok": parts_ok,
                    "last_parts_ok": "" if old_last is None else old_last,
                    "barcode1": barcode1,
                    "barcode2": barcode2,
                    "barcode1_hex": barcode1_hex,
                    "barcode2_hex": barcode2_hex,
                    "result": result,
                    "message": message,
                }
            )

    def add_table_row(
        self,
        now: str,
        parts_ok: int,
        old_last: Optional[int],
        barcode1: str,
        barcode2: str,
        is_new: bool,
        result: str,
        message: str,
    ):
        row = self.record_table.rowCount()
        self.record_table.insertRow(row)
        values = [
            now,
            parts_ok,
            "" if old_last is None else old_last,
            barcode1,
            barcode2,
            "是" if is_new else "否",
            result,
            message,
        ]
        for col, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.record_table.setItem(row, col, item)
        self.record_table.scrollToBottom()

    def set_process_status(self, text: str):
        self.process_status_label.setText(text)

    def log_and_status(self, text: str):
        self.set_process_status(text)
        logging.info(text)

    def show_error(self, title: str, message: str):
        logging.error("%s：%s", title, message)
        self.set_process_status(title)
        QMessageBox.warning(self, title, message)

    def format_exception_message(self, exc: Exception) -> str:
        text = str(exc)
        lower_text = text.lower()
        suggestions = []
        if "function refused" in lower_text or "refused by cpu" in lower_text:
            suggestions.append(
                "S7-1200 function refused by CPU：请检查 TIA Portal 是否允许 PUT/GET Communication；"
                "DB201、DB221 是否关闭 Optimized Block Access；修改后是否重新编译并下载到PLC。"
            )
        if "db" in lower_text or "address" in lower_text or "out of range" in lower_text:
            suggestions.append("DB读取失败：请检查 DB号、offset、length。")
        if "codec" in lower_text or "decode" in lower_text:
            suggestions.append("条码乱码：尝试修改 config.ini 的 encoding 为 utf-8、gbk 或 latin1。")
        if "connect" in lower_text or "tcp" in lower_text or "timeout" in lower_text:
            suggestions.append("PLC连接失败：检查 IP、网线、PLC是否允许外部访问、Rack/Slot。")
        if not suggestions:
            suggestions.append("通讯中断或读取异常：程序已停止本次处理，不会崩溃。")
        return text + "\n\n" + "\n".join(suggestions)


def main():
    app = QApplication(sys.argv)
    window = S7PlcTestWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
