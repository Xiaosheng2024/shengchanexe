import configparser
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QApplication, QLabel

import desktop_app.window as window_module
from desktop_app.window import (
    APP_VERSION,
    DEFAULT_MES_SERVER_URL,
    QualityControlWindow,
    SYSTEM_NAME,
)
from shared.models import (
    BARCODE_SWITCH,
    MATERIAL_BIND,
    PLC,
    SCAN,
    SCREW,
    ProcessStep,
    ProductConfig,
)


class DesktopMainBarcodeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self):
        window_module.shutil.which = lambda command: None
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        window = QualityControlWindow(Path(temp_dir.name) / "config.ini")
        window.speak = lambda text: None
        window.play_ok_sound = lambda: None
        window.show_auto_close_warning = lambda title, message: None
        window.disable_tool_auto_listen_checkbox.setChecked(True)
        window.station_session_id = 1
        self.addCleanup(window.close)
        return window

    def set_current_step_to_screw(self, window):
        window.current_product = ProductConfig("螺丝测试", [ProcessStep("打螺丝1颗", SCREW, required_count=1)])
        window.current_station.product = window.current_product
        window.current_step_index = 0
        window.tool_forward_value_input.setValue(3)
        window.tool_reverse_value_input.setValue(2)

    def test_main_barcode_sets_current_barcode_and_part_barcode_does_not_overwrite(self):
        window = self.make_window()
        window.online_mode = False
        window.current_product = ProductConfig(
            "测试产品",
            [
                ProcessStep("扫码主条码", SCAN, barcode_start=1, barcode_end=4, expected_content="MAIN", is_main_barcode=True),
                ProcessStep("扫码普通零件", SCAN, barcode_start=1, barcode_end=4, expected_content="PART"),
                ProcessStep("打螺丝1颗", SCREW, required_count=1),
            ],
        )
        window.current_station.product = window.current_product
        window.reset_current_product(update_table=True)
        self.assertEqual(window.main_barcode_label.text(), "当前主条码：未扫描")

        window.barcode_input.setText("MAIN-001")
        window.handle_scan()
        self.assertEqual(window.current_barcode, "MAIN-001")
        self.assertEqual(window.main_barcode_label.text(), "当前主条码：MAIN-001")

        window.barcode_input.setText("PART-001")
        window.handle_scan()
        self.assertEqual(window.current_barcode, "MAIN-001")
        self.assertEqual(window.main_barcode_label.text(), "当前主条码：MAIN-001")

        window.handle_screw_ok()
        self.assertEqual(window.current_product.steps[2].completed_count, 1)
        self.assertTrue(window.current_product.steps[2].done)
        self.assertEqual(window.screw_progress_label.text(), "已完成：1 / 1")

        window.advance_step()
        self.assertEqual(window.current_barcode, "")
        self.assertEqual(window.main_barcode_label.text(), "当前主条码：未扫描")
        self.assertEqual(window.current_step_index, 0)

    def test_global_scanner_capture_handles_fast_barcode_once(self):
        window = self.make_window()
        captured = []
        window.scanner_capture_paused = lambda: False
        window.handle_scanned_barcode = (
            lambda barcode, source="input": captured.append((barcode, source))
        )
        times = iter([1000, 1010, 1020, 1030, 1040, 1050, 1060, 1070])
        window.scanner_now_ms = lambda: next(times)

        for character in "ABC1234":
            handled = window._capture_scanner_key_event(
                QKeyEvent(QEvent.KeyPress, ord(character), Qt.NoModifier, character)
            )
            self.assertTrue(handled)
        handled = window._capture_scanner_key_event(
            QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, "\r")
        )

        self.assertTrue(handled)
        self.assertEqual(captured, [("ABC1234", "global")])
        self.assertEqual(window.scan_buffer, "")

    def test_slow_manual_typing_is_not_misclassified_as_scanner(self):
        window = self.make_window()
        captured = []
        window.scanner_capture_paused = lambda: False
        window.handle_scanned_barcode = (
            lambda barcode, source="input": captured.append((barcode, source))
        )
        times = iter([1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700])
        window.scanner_now_ms = lambda: next(times)

        for character in "ABC1234":
            window._capture_scanner_key_event(
                QKeyEvent(QEvent.KeyPress, ord(character), Qt.NoModifier, character)
            )
        handled = window._capture_scanner_key_event(
            QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, "\r")
        )

        self.assertFalse(handled)
        self.assertEqual(captured, [])

    def test_slow_manual_input_is_replayed_to_barcode_field(self):
        window = self.make_window()
        captured = []
        window.scanner_capture_paused = lambda: False
        window.handle_scanned_barcode = (
            lambda barcode, source="input": captured.append((barcode, source))
        )
        window.barcode_input.setEnabled(True)
        times = iter([1000, 1100, 1200, 1300] + [1400] * 10)
        window.scanner_now_ms = lambda: next(times)

        for character in "ABCD":
            QApplication.sendEvent(
                window.barcode_input,
                QKeyEvent(
                    QEvent.KeyPress,
                    ord(character),
                    Qt.NoModifier,
                    character,
                ),
            )
        self.assertEqual(window.barcode_input.text(), "ABCD")
        window.handle_scan()

        self.assertEqual(captured, [("ABCD", "input")])

    def test_duplicate_barcode_is_ignored_across_scan_sources(self):
        window = self.make_window()
        processed = []
        window._process_scanned_barcode = (
            lambda: processed.append(window.barcode_input.text())
        )
        times = iter([1000, 1200])
        window.scanner_now_ms = lambda: next(times)

        self.assertTrue(window.handle_scanned_barcode("ABC123", source="global"))
        self.assertFalse(window.handle_scanned_barcode("ABC123", source="input"))

        self.assertEqual(processed, ["ABC123"])

    def test_chinese_barcode_is_rejected_before_business_processing(self):
        window = self.make_window()
        processed = []
        window._process_scanned_barcode = lambda: processed.append(True)

        self.assertFalse(window.handle_scanned_barcode("ABC中文123"))

        self.assertEqual(processed, [])
        self.assertIn("包含中文字符", window.message_label.text())

    def test_scanner_capture_pauses_while_dialog_guard_is_active(self):
        window = self.make_window()
        captured = []
        window.scanner_capture_paused = lambda: True
        window.handle_scanned_barcode = (
            lambda barcode, source="input": captured.append((barcode, source))
        )
        event = QKeyEvent(QEvent.KeyPress, ord("A"), Qt.NoModifier, "A")

        self.assertFalse(window._capture_scanner_key_event(event))
        self.assertEqual(captured, [])
        self.assertEqual(window.scan_buffer, "")

    def test_scan_input_disables_input_method(self):
        window = self.make_window()
        self.assertFalse(
            window.barcode_input.testAttribute(Qt.WA_InputMethodEnabled)
        )

    def test_online_station_two_blocks_when_previous_station_is_not_complete(self):
        window = self.make_window()
        window.current_station.name = "工位2"
        window.current_product = ProductConfig(
            "测试产品",
            [ProcessStep("扫码主条码", SCAN, barcode_start=1, barcode_end=4, expected_content="MAIN", is_main_barcode=True)],
        )
        window.current_station.product = window.current_product
        window.reset_current_product(update_table=True)
        window.online_mode = True
        window.degraded_mode_checkbox.setChecked(False)
        window.api_get = lambda path: {"completed": False}

        window.barcode_input.setText("MAIN-002")
        window.handle_scan()

        self.assertEqual(window.current_barcode, "")
        self.assertEqual(window.main_barcode_label.text(), "当前主条码：未扫描")
        self.assertEqual(window.current_step_index, 0)
        self.assertEqual(window.message_label.text(), "上一工位未完成，不能进行当前工位")

    def test_route_start_uses_station_material_type_for_new_product(self):
        window = self.make_window()
        window.online_mode = True
        window.current_project.id = 7
        window.current_project.product_type = "A物料"
        window.current_station.id = 70
        window.current_station.route_name = "B子线"
        window.current_station.station_role = "起点工位"
        window.current_station.material_type = "B物料"
        payloads = []

        def api_post(path, payload):
            payloads.append((path, payload))
            if path == "/api/product-flow/resolve-barcode":
                return {
                    "found": True,
                    "allowed_production": True,
                    "project_id": 7,
                    "product_instance_id": 700,
                    "current_barcode": "B001",
                }
            return {"allowed": True}

        window.api_post = api_post
        self.assertTrue(window.resolve_and_verify_main_barcode("B001"))
        resolve_payload = next(
            payload
            for path, payload in payloads
            if path == "/api/product-flow/resolve-barcode"
        )
        self.assertTrue(resolve_payload["create_if_missing"])
        self.assertEqual(resolve_payload["product_type"], "B物料")

    def test_online_requests_use_ids_while_preserving_special_character_names(self):
        window = self.make_window()
        window.online_mode = True
        window.current_project.id = 81
        window.current_project.name = "项目/A&B"
        previous_station = window.current_project.stations[0]
        current_station = window.current_project.stations[1]
        previous_station.id = 91
        previous_station.name = "中饰板预装-中出风口/磁吸"
        current_station.id = 92
        current_station.name = "工位?测试"
        window.current_station = current_station
        window.current_product = current_station.product
        calls = []

        def api_get(path):
            calls.append(path)
            if path.startswith("/api/client/station-config?"):
                return {
                    "code": 1,
                    "msg": "ok",
                    "data": {
                        "project_id": 81,
                        "station_id": 92,
                        "product_name": "测试产品",
                        "steps": [{"name": "主条码", "type": "扫码", "is_main_barcode": True}],
                    },
                }
            return {"completed": True}

        window.api_get = api_get
        self.assertTrue(window.download_config_for_current_station())
        self.assertTrue(window.verify_previous_station_complete("MAIN/?#"))
        self.assertIn(
            "/api/client/station-config?project_id=81&station_id=92",
            calls,
        )
        completion_path = next(
            path for path in calls if path.startswith("/api/station-completions/check?")
        )
        self.assertIn("project_id=81", completion_path)
        self.assertIn("previous_station_id=91", completion_path)
        self.assertNotIn("中饰板", completion_path)

    def test_old_config_without_main_barcode_temporarily_uses_first_scan(self):
        window = self.make_window()
        product = ProductConfig(
            "旧配置",
            [
                ProcessStep("旧扫码1", SCAN),
                ProcessStep("旧扫码2", SCAN),
            ],
        )
        window.ensure_main_barcode(product, notify=True)
        self.assertTrue(product.steps[0].is_main_barcode)
        self.assertFalse(product.steps[1].is_main_barcode)

    def test_barcode_switch_updates_current_barcode_without_changing_instance(self):
        window = self.make_window()
        window.online_mode = True
        window.current_project.id = 1
        window.current_station.id = 3
        window.current_barcode = "AOLD001"
        window.current_product_instance_id = 88
        switch_step = ProcessStep(
            "切换主条码",
            BARCODE_SWITCH,
            step_id=301,
        )
        window.current_product = ProductConfig(
            "A产品",
            [
                switch_step,
                ProcessStep("扫码后续件", SCAN),
                ProcessStep("后续螺丝", SCREW, required_count=1),
            ],
        )
        window.current_station.product = window.current_product
        calls = []

        def api_post(path, payload):
            calls.append((path, payload))
            if path == "/api/product-flow/switch-barcode":
                return {
                    "ok": True,
                    "product_instance_id": 88,
                    "current_barcode": "ANEW001",
                }
            return {"ok": True, "product_instance_id": 88}

        window.api_post = api_post
        window.barcode_input.setText("AOLD001")
        window.handle_scan()
        self.assertEqual(window.pending_switch_old_barcode, "AOLD001")
        window.barcode_input.setText("ANEW001")
        window.handle_scan()
        self.assertEqual(window.current_barcode, "ANEW001")
        self.assertEqual(window.current_product_instance_id, 88)
        self.assertTrue(switch_step.done)
        self.assertEqual(window.current_step_index, 1)
        self.assertTrue(
            any(path == "/api/product-flow/switch-barcode" for path, _ in calls)
        )
        window.barcode_input.setText("PART-001")
        window.handle_scan()
        self.assertEqual(window.current_barcode, "ANEW001")

    def test_material_binding_scans_parent_then_child(self):
        window = self.make_window()
        window.online_mode = True
        window.current_project.id = 1
        window.current_station.id = 4
        window.current_barcode = "ANEW001"
        window.current_product_instance_id = 88
        bind_step = ProcessStep(
            "绑定B物料",
            MATERIAL_BIND,
            step_id=401,
            bind_child_project_id=2,
            bind_child_material_type="B",
            bind_required_count=1,
            bind_required_station_ids=[21, 22],
        )
        window.current_product = ProductConfig(
            "A产品",
            [bind_step, ProcessStep("扫码后续件", SCAN)],
        )
        window.current_station.product = window.current_product
        calls = []
        window.api_post = lambda path, payload: (
            calls.append((path, payload))
            or {"ok": True, "binding_id": 1}
        )
        window.barcode_input.setText("ANEW001")
        window.handle_scan()
        self.assertEqual(window.pending_bind_parent_barcode, "ANEW001")
        window.barcode_input.setText("B001")
        window.handle_scan()
        self.assertTrue(bind_step.done)
        self.assertEqual(window.current_step_index, 1)
        bind_payload = next(
            payload
            for path, payload in calls
            if path == "/api/product-flow/bind-material"
        )
        self.assertEqual(bind_payload["required_station_ids"], [21, 22])
        self.assertEqual(bind_payload["child_barcode"], "B001")

    def test_old_main_barcode_is_rejected_before_station_entry_check(self):
        window = self.make_window()
        window.online_mode = True
        window.current_project.id = 1
        window.current_station.id = 4
        window.current_product = ProductConfig(
            "A产品",
            [ProcessStep("扫码主条码", SCAN, is_main_barcode=True)],
        )
        window.current_station.product = window.current_product
        calls = []

        def api_post(path, payload):
            calls.append(path)
            return {
                "ok": True,
                "found": True,
                "allowed_production": False,
                "current_barcode": "ANEW001",
                "message": "该条码已切换为新主条码 ANEW001，请扫描当前主条码",
            }

        window.api_post = api_post
        window.barcode_input.setText("AOLD001")
        window.handle_scan()
        self.assertEqual(window.current_barcode, "")
        self.assertEqual(window.current_step_index, 0)
        self.assertIn("ANEW001", window.message_label.text())
        self.assertNotIn("/api/product-flow/verify-entry", calls)

    def test_settings_product_selection_syncs_main_station_selector(self):
        window = self.make_window()
        target_station = window.current_project.stations[1]

        window.load_product(target_station.product.name)

        self.assertIs(window.current_station, target_station)
        self.assertIs(window.current_product, target_station.product)
        self.assertEqual(window.station_combo.currentText(), target_station.name)
        self.assertEqual(window.current_step_index, 0)
        self.assertEqual(window.product_label.text(), target_station.product.name)

    def test_default_tool_ip_is_localhost(self):
        window = self.make_window()
        self.assertEqual(window.tool_ip_input.text(), "127.0.0.1")
        self.assertEqual(window.windowTitle(), SYSTEM_NAME)

    def test_station_client_id_is_persisted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.ini"
            window = self.make_window()
            window.app_config_path = config_path
            first_id = window.load_station_session_client_id()
            second = self.make_window()
            second.app_config_path = config_path
            second_id = second.load_station_session_client_id()
            self.assertEqual(first_id, second_id)

    def test_server_url_moves_to_server_section_without_changing_client_id(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.ini"
            config_path.write_text(
                "[LOCAL_DEVICE]\n"
                "client_id = fixed-client-id\n"
                "mes_server = http://old-mes:8000\n",
                encoding="utf-8",
            )
            window = QualityControlWindow(config_path)
            self.assertEqual(window.api_base_input.text(), "http://old-mes:8000")

            window.persist_server_url("mes.company.local:8000")

            saved = configparser.ConfigParser()
            saved.read(config_path, encoding="utf-8")
            self.assertEqual(saved.get("SERVER", "url"), "http://mes.company.local:8000")
            self.assertEqual(saved.get("LOCAL_DEVICE", "client_id"), "fixed-client-id")
            self.assertFalse(saved.has_option("LOCAL_DEVICE", "mes_server"))
            self.assertEqual(
                window.api_url("/api/client-update/download/v0.8.5/release"),
                "http://mes.company.local:8000/api/client-update/download/v0.8.5/release",
            )

    def test_missing_server_url_uses_packaged_default_and_persists_it(self):
        window = self.make_window()
        self.assertEqual(window.api_base_input.text(), DEFAULT_MES_SERVER_URL)
        saved = configparser.ConfigParser()
        saved.read(window.app_config_path, encoding="utf-8")
        self.assertEqual(saved.get("SERVER", "url"), DEFAULT_MES_SERVER_URL)
        self.assertTrue(saved.get("LOCAL_DEVICE", "client_id"))

    def test_existing_server_url_is_not_overwritten_by_packaged_default(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.ini"
            config_path.write_text(
                "[SERVER]\n"
                "url = http://mes.company.local:8000\n"
                "[LOCAL_DEVICE]\n"
                "client_id = fixed-client-id\n",
                encoding="utf-8",
            )
            window = QualityControlWindow(config_path)
            self.addCleanup(window.close)
            self.assertEqual(
                window.api_base_input.text(), "http://mes.company.local:8000"
            )
            saved = configparser.ConfigParser()
            saved.read(config_path, encoding="utf-8")
            self.assertEqual(
                saved.get("SERVER", "url"), "http://mes.company.local:8000"
            )
            self.assertEqual(
                saved.get("LOCAL_DEVICE", "client_id"), "fixed-client-id"
            )

    def test_online_config_download_without_station_session_disables_production(self):
        window = self.make_window()
        window.online_mode = True
        window.station_config_loaded = True
        window.station_session_acquired = False
        window.station_session_id = None
        window.recompute_production_enabled()
        window.current_product = ProductConfig(
            "测试产品",
            [ProcessStep("扫码主条码", SCAN, barcode_start=1, barcode_end=4, expected_content="MAIN", is_main_barcode=True)],
        )
        window.current_station.product = window.current_product
        posts = []
        window.api_post = lambda *args, **kwargs: posts.append(args)

        window.barcode_input.setText("MAIN-001")
        window.handle_scan()
        window.handle_screw_ok()
        window.on_plc_snapshot(1, "MAIN-001", "")
        self.assertFalse(window.report_station_complete())

        self.assertEqual(window.current_barcode, "")
        self.assertFalse(window.current_product.steps[0].done)
        self.assertEqual(posts, [])
        self.assertEqual(
            window.message_label.text(),
            "当前工位未占用成功，请重新下载配置",
        )

    def test_barcode_request_payload_contains_station_session_context(self):
        window = self.make_window()
        window.online_mode = True
        window.current_project.id = 12
        window.current_station.id = 34
        window.station_session_client_id = "fixed-client"
        window.station_session_id = 56

        payload = window.with_station_session(
            {
                "barcode": "MAIN-SESSION-001",
                "step_id": 78,
                "is_main_barcode": True,
            }
        )

        self.assertEqual(payload["client_id"], "fixed-client")
        self.assertEqual(payload["project_id"], 12)
        self.assertEqual(payload["station_id"], 34)
        self.assertEqual(payload["station_session_id"], 56)

    def test_barcode_request_without_station_session_is_not_sent(self):
        window = self.make_window()
        window.online_mode = True
        window.station_session_id = None

        with self.assertRaisesRegex(
            RuntimeError, "当前工位未占用成功，请重新下载配置"
        ):
            window.with_station_session({"barcode": "MAIN-001"})

    def test_switch_station_downloads_config_and_acquires_without_reentry(self):
        window = self.make_window()
        window.online_mode = True
        window.station_config_loaded = True
        window.station_session_acquired = True
        window.production_enabled = True
        calls = []
        window.show_station_conflict_dialog = lambda *args, **kwargs: None

        def fake_get(path):
            calls.append(("GET", path))
            return {
                "product_name": "在线工位2产品",
                "steps": [
                    {
                        "name": "扫码主条码",
                        "type": SCAN,
                        "barcode_start": 1,
                        "barcode_end": 4,
                        "expected_content": "MAIN",
                        "is_main_barcode": True,
                    }
                ],
            }

        def fake_post(path, payload):
            calls.append(("POST", path, payload.get("station")))
            if path.endswith("/release"):
                return {"ok": True}
            if path.endswith("/acquire"):
                return {"ok": True, "session_id": 66, "client_id": payload["client_id"]}
            return {"ok": True}

        window.api_get = fake_get
        window.api_post = fake_post
        window.switch_station(window.current_project.name, "工位2")

        self.assertFalse(window.is_switching_station)
        self.assertTrue(window.station_combo.isEnabled())
        self.assertTrue(window.production_enabled)
        self.assertTrue(window.station_config_loaded)
        self.assertTrue(window.station_session_acquired)
        self.assertEqual(window.station_session_id, 66)
        self.assertEqual(window.current_station.name, "工位2")
        self.assertEqual(window.current_product.name, "在线工位2产品")
        self.assertEqual(calls[0][1], "/api/station-session/release")
        self.assertTrue(any(item[0] == "GET" and ("%E5%B7%A5%E4%BD%8D2" in item[1] or "工位2" in item[1]) for item in calls))
        self.assertTrue(any(item[0] == "POST" and item[1] == "/api/station-session/acquire" for item in calls))

    def test_switch_station_conflict_keeps_production_disabled(self):
        window = self.make_window()
        window.online_mode = True
        window.station_config_loaded = True
        window.station_session_acquired = True
        window.production_enabled = True
        window.show_station_conflict_dialog = lambda *args, **kwargs: None
        window.api_get = lambda path: {
            "product_name": "在线工位2产品",
            "steps": [{"name": "扫码主条码", "type": SCAN, "is_main_barcode": True}],
        }
        window.api_post = lambda path, payload: {"ok": False, "conflict": {"computer_name": "PC-B"}} if path.endswith("/acquire") else {"ok": True}

        window.switch_station(window.current_project.name, "工位2")

        self.assertFalse(window.production_enabled)
        self.assertFalse(window.station_session_acquired)
        self.assertFalse(window.screw_ok_btn.isEnabled())
        self.assertFalse(window.barcode_input.isEnabled())

    def test_old_worker_generation_signals_are_ignored_after_switch(self):
        window = self.make_window()
        window.current_product = ProductConfig("PLC测试", [ProcessStep("PLC接收主条码", PLC, is_main_barcode=True)])
        window.current_station.product = window.current_product
        window.current_step_index = 0
        window.plc_worker_generation = 2
        window.tool_worker_generation = 2

        window.on_plc_snapshot_for_generation(1, 10, "OLD", "")
        window.on_tool_poll_result_for_generation(1, 2, 1, 0)

        self.assertEqual(window.current_barcode, "")
        self.assertEqual(window.current_product.steps[0].completed_count, 0)

    def test_plc_step_waits_for_barcode_change_then_parts_ok_increment(self):
        window = self.make_window()
        step = ProcessStep("PLC接收主条码", PLC, is_main_barcode=True)
        window.current_product = ProductConfig("PLC测试", [step])
        window.current_station.product = window.current_product
        window.current_step_index = 0
        window.stop_plc_worker = lambda: None
        advances = {"count": 0}
        window.advance_step = lambda *args, **kwargs: advances.__setitem__("count", advances["count"] + 1)
        records = []
        window.add_history_record = lambda *args, **kwargs: records.append((args, kwargs))
        window.post_plc_step_record = lambda *args, **kwargs: None

        window.on_plc_snapshot(10, "OLD", "")
        self.assertFalse(step.done)
        window.on_plc_snapshot(10, "MAIN-PLC-001", "")
        self.assertFalse(step.done)
        self.assertEqual(window.current_barcode, "")
        window.on_plc_snapshot(11, "MAIN-PLC-001", "")

        self.assertTrue(step.done)
        self.assertEqual(window.current_barcode, "MAIN-PLC-001")
        self.assertEqual(advances["count"], 1)
        self.assertEqual(len(records), 1)

    def test_plc_parts_ok_increment_without_barcode_change_is_abnormal(self):
        window = self.make_window()
        step = ProcessStep("PLC接收主条码", PLC, is_main_barcode=True)
        window.current_product = ProductConfig("PLC测试", [step])
        window.current_station.product = window.current_product
        window.current_step_index = 0
        window.advance_step = lambda *args, **kwargs: self.fail("不应该进入下一工序")
        records = []
        window.add_history_record = lambda *args, **kwargs: records.append((args, kwargs))

        window.on_plc_snapshot(10, "MAIN-PLC-001", "")
        window.on_plc_snapshot(11, "MAIN-PLC-001", "")

        self.assertFalse(step.done)
        self.assertEqual(window.current_barcode, "")
        self.assertIn("未检测到新条码", records[0][0][3])

    def test_plc_barcode_change_without_parts_ok_waits(self):
        window = self.make_window()
        step = ProcessStep("PLC接收主条码", PLC, is_main_barcode=True)
        window.current_product = ProductConfig("PLC测试", [step])
        window.current_station.product = window.current_product
        window.current_step_index = 0

        window.on_plc_snapshot(10, "OLD", "")
        window.on_plc_snapshot(10, "MAIN-PLC-001", "")

        self.assertFalse(step.done)
        self.assertEqual(window.current_barcode, "")
        self.assertEqual(window.message_label.text(), "已检测到条码，等待PARTS_OK递增")

    def test_plc_parts_ok_decrease_resets_baseline(self):
        window = self.make_window()
        step = ProcessStep("PLC接收主条码", PLC, is_main_barcode=True)
        window.current_product = ProductConfig("PLC测试", [step])
        window.current_station.product = window.current_product
        window.current_step_index = 0

        window.on_plc_snapshot(10, "OLD", "")
        window.on_plc_snapshot(8, "OLD", "")

        self.assertFalse(step.done)
        self.assertEqual(window.plc_last_parts_ok, 8)
        self.assertEqual(window.message_label.text(), "PLC完成计数变小，已重新建立基准")

    def test_plc_parts_ok_jump_records_warning_but_completes_pending_barcode(self):
        window = self.make_window()
        step = ProcessStep("PLC接收主条码", PLC, is_main_barcode=True)
        window.current_product = ProductConfig("PLC测试", [step])
        window.current_station.product = window.current_product
        window.current_step_index = 0
        window.stop_plc_worker = lambda: None
        window.advance_step = lambda *args, **kwargs: None
        window.post_plc_step_record = lambda *args, **kwargs: None
        records = []
        window.add_history_record = lambda *args, **kwargs: records.append((args, kwargs))

        window.on_plc_snapshot(10, "OLD", "")
        window.on_plc_snapshot(10, "MAIN-PLC-001", "")
        window.on_plc_snapshot(13, "MAIN-PLC-001", "")

        self.assertTrue(step.done)
        self.assertTrue(any(item[0][1] == "警告" for item in records))
        self.assertEqual(window.current_barcode, "MAIN-PLC-001")

    def test_plc_ok_does_not_report_station_complete_until_all_steps_done(self):
        window = self.make_window()
        plc_step = ProcessStep("PLC接收主条码", PLC, is_main_barcode=True)
        scan_step = ProcessStep("扫码普通零件", SCAN, barcode_start=1, barcode_end=4, expected_content="PART")
        window.current_product = ProductConfig("PLC测试", [plc_step, scan_step])
        window.current_station.product = window.current_product
        window.current_step_index = 0
        window.stop_plc_worker = lambda: None
        window.post_plc_step_record = lambda *args, **kwargs: None
        reports = {"count": 0}
        window.report_station_complete = lambda: reports.__setitem__("count", reports["count"] + 1) or True

        window.on_plc_snapshot(10, "OLD", "")
        window.on_plc_snapshot(10, "MAIN-PLC-001", "")
        window.on_plc_snapshot(11, "MAIN-PLC-001", "")

        self.assertTrue(plc_step.done)
        self.assertFalse(scan_step.done)
        self.assertEqual(window.current_step_index, 1)
        self.assertEqual(reports["count"], 0)

    def test_plc_normal_step_cannot_overwrite_current_barcode(self):
        window = self.make_window()
        step = ProcessStep("PLC接收普通确认", PLC, is_main_barcode=False)
        window.current_product = ProductConfig("PLC测试", [step])
        window.current_station.product = window.current_product
        window.current_step_index = 0
        window.current_barcode = "MAIN-PLC-001"
        window.stop_plc_worker = lambda: None
        window.advance_step = lambda *args, **kwargs: None
        records = []
        window.add_history_record = lambda *args, **kwargs: records.append((args, kwargs))

        window.on_plc_snapshot(10, "OLD", "")
        window.on_plc_snapshot(10, "OTHER-PLC-001", "")
        window.on_plc_snapshot(11, "OTHER-PLC-001", "")

        self.assertFalse(step.done)
        self.assertEqual(window.current_barcode, "MAIN-PLC-001")
        self.assertEqual(window.message_label.text(), "PLC主条码与当前产品主条码不一致")

    def test_tool_main_panel_hides_advanced_settings(self):
        window = self.make_window()
        window.restore_default_tool_settings()
        main_labels = [label.text() for label in window.tool_box.findChildren(QLabel)]

        for text in ["IP", "端口", "站号", "状态地址", "OK值", "NG值", "状态"]:
            self.assertIn(text, main_labels)
        for text in [
            "触发地址",
            "触发值",
            "触发复位值",
            "锁定地址",
            "锁定值",
            "解锁值",
            "方向地址",
            "正转值",
            "反转值",
            "轮询间隔ms",
            "通讯超时秒",
            "写指令延迟",
        ]:
            self.assertNotIn(text, main_labels)
        self.assertEqual(window.tool_settings_dialog.windowTitle(), "螺钉枪高级设置")
        self.assertEqual(window.tool_control_register_input.value(), 4)
        self.assertEqual(window.tool_lock_value_input.value(), 2)
        self.assertEqual(window.tool_unlock_value_input.value(), 1)
        self.assertEqual(window.tool_direction_register_input.value(), 54)
        self.assertEqual(window.tool_forward_value_input.value(), 3)
        self.assertEqual(window.tool_reverse_value_input.value(), 2)

    def test_missing_config_uses_and_generates_new_direction_defaults(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.ini"
            self.assertFalse(config_path.exists())

            window = QualityControlWindow(config_path)

            self.assertEqual(window.tool_direction_register_input.value(), 54)
            self.assertEqual(window.tool_forward_value_input.value(), 3)
            self.assertEqual(window.tool_reverse_value_input.value(), 2)
            self.assertEqual(window.tool_command_delay_input.value(), 50)
            self.assertEqual(window.tool_poll_interval_input.value(), 100)
            self.assertTrue(config_path.exists())
            generated = configparser.ConfigParser()
            generated.read(config_path, encoding="utf-8")
            self.assertEqual(generated.getint("TOOL", "direction_address"), 54)
            self.assertEqual(generated.getint("TOOL", "forward_value"), 3)
            self.assertEqual(generated.getint("TOOL", "reverse_value"), 2)
            self.assertEqual(generated.getint("TOOL", "command_delay_ms"), 50)
            self.assertEqual(generated.getint("TOOL", "poll_interval_ms"), 100)

    def test_restore_defaults_uses_new_direction_protocol(self):
        window = self.make_window()
        window.tool_direction_register_input.setValue(99)
        window.tool_forward_value_input.setValue(0)
        window.tool_reverse_value_input.setValue(1)
        window.tool_command_delay_input.setValue(0)
        window.tool_poll_interval_input.setValue(800)

        window.restore_default_tool_settings()

        self.assertEqual(window.tool_direction_register_input.value(), 54)
        self.assertEqual(window.tool_forward_value_input.value(), 3)
        self.assertEqual(window.tool_reverse_value_input.value(), 2)
        self.assertEqual(window.tool_command_delay_input.value(), 50)
        self.assertEqual(window.tool_poll_interval_input.value(), 100)

    def test_old_tool_config_gets_command_delay_without_overwriting_values(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.ini"
            config_path.write_text(
                "[TOOL]\nforward_value = 9\nreverse_value = 8\n"
                "[LOCAL_DEVICE]\nclient_id = fixed-client\n",
                encoding="utf-8",
            )

            window = QualityControlWindow(config_path)

            self.assertEqual(window.tool_forward_value_input.value(), 9)
            self.assertEqual(window.tool_reverse_value_input.value(), 8)
            self.assertEqual(window.tool_command_delay_input.value(), 50)
            updated = configparser.ConfigParser()
            updated.read(config_path, encoding="utf-8")
            self.assertEqual(updated.getint("TOOL", "command_delay_ms"), 50)
            self.assertEqual(updated.getint("TOOL", "forward_value"), 9)
            self.assertEqual(updated.getint("TOOL", "reverse_value"), 8)

    def test_tool_settings_are_saved_and_loaded_from_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.ini"
            window = self.make_window()
            window.app_config_path = config_path
            window.tool_ip_input.setText("192.168.1.50")
            window.tool_port_input.setValue(1502)
            window.tool_unit_input.setValue(2)
            window.tool_status_register_input.setValue(101)
            window.tool_ok_value_input.setValue(20)
            window.tool_ng_value_input.setValue(30)
            window.tool_trigger_register_input.setValue(54)
            window.tool_trigger_value_input.setValue(9)
            window.tool_trigger_reset_value_input.setValue(8)
            window.tool_control_register_input.setValue(5)
            window.tool_lock_value_input.setValue(6)
            window.tool_unlock_value_input.setValue(7)
            window.tool_direction_register_input.setValue(55)
            window.tool_forward_value_input.setValue(10)
            window.tool_reverse_value_input.setValue(11)
            window.tool_command_delay_input.setValue(75)
            window.tool_clear_trigger_when_reverse_checkbox.setChecked(False)
            window.tool_poll_interval_input.setValue(1200)
            window.tool_timeout_input.setValue(2)
            window.tool_admin_password_input.setText("1234")
            window.tool_enable_dedup_checkbox.setChecked(False)
            window.tool_verbose_log_checkbox.setChecked(True)

            window.save_tool_settings()

            loaded = QualityControlWindow(config_path)

            self.assertEqual(loaded.tool_ip_input.text(), "192.168.1.50")
            self.assertEqual(loaded.tool_port_input.value(), 1502)
            self.assertEqual(loaded.tool_unit_input.value(), 2)
            self.assertEqual(loaded.tool_status_register_input.value(), 101)
            self.assertEqual(loaded.tool_ok_value_input.value(), 20)
            self.assertEqual(loaded.tool_ng_value_input.value(), 30)
            self.assertEqual(loaded.tool_trigger_register_input.value(), 54)
            self.assertEqual(loaded.tool_trigger_value_input.value(), 9)
            self.assertEqual(loaded.tool_trigger_reset_value_input.value(), 8)
            self.assertEqual(loaded.tool_control_register_input.value(), 5)
            self.assertEqual(loaded.tool_lock_value_input.value(), 6)
            self.assertEqual(loaded.tool_unlock_value_input.value(), 7)
            self.assertEqual(loaded.tool_direction_register_input.value(), 55)
            self.assertEqual(loaded.tool_forward_value_input.value(), 10)
            self.assertEqual(loaded.tool_reverse_value_input.value(), 11)
            self.assertEqual(loaded.tool_command_delay_input.value(), 75)
            self.assertFalse(loaded.tool_clear_trigger_when_reverse_checkbox.isChecked())
            self.assertEqual(loaded.tool_poll_interval_input.value(), 1200)
            self.assertEqual(loaded.tool_timeout_input.value(), 2)
            self.assertEqual(loaded.tool_admin_password_input.text(), "1234")
            self.assertFalse(loaded.tool_enable_dedup_checkbox.isChecked())
            self.assertTrue(loaded.tool_verbose_log_checkbox.isChecked())

    def test_forward_tool_trigger_one_is_counted_once_until_reset_seen(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        count = {"ok": 0, "writes": []}
        window.handle_screw_ok = lambda: count.__setitem__("ok", count["ok"] + 1)
        window.write_tool_register = lambda register, value: count["writes"].append((register, value))

        window.process_tool_poll_result(status=2, trigger=1, direction=3)
        window.process_tool_poll_result(status=2, trigger=1, direction=3)
        self.assertEqual(count["ok"], 1)

        window.process_tool_poll_result(status=2, trigger=0, direction=3)
        window.process_tool_poll_result(status=2, trigger=1, direction=3)
        self.assertEqual(count["ok"], 2)
        self.assertIn((53, 0), count["writes"])

    def test_tool_trigger_lock_releases_only_after_trigger_reset_zero(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        count = {"ok": 0}
        window.handle_screw_ok = lambda: count.__setitem__("ok", count["ok"] + 1)
        window.write_tool_register = lambda register, value: None

        window.process_tool_poll_result(status=2, trigger=1, direction=3)
        window.process_tool_poll_result(status=2, trigger=2, direction=3)
        window.process_tool_poll_result(status=2, trigger=1, direction=3)
        self.assertEqual(count["ok"], 1)

        window.process_tool_poll_result(status=2, trigger=0, direction=3)
        window.process_tool_poll_result(status=2, trigger=1, direction=3)
        self.assertEqual(count["ok"], 2)

    def test_tool_dedup_can_be_disabled_from_advanced_settings(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        window.tool_enable_dedup_checkbox.setChecked(False)
        count = {"ok": 0}
        window.handle_screw_ok = lambda: count.__setitem__("ok", count["ok"] + 1)
        window.write_tool_register = lambda register, value: None

        window.process_tool_poll_result(status=2, trigger=1, direction=3)
        window.process_tool_poll_result(status=2, trigger=1, direction=3)

        self.assertEqual(count["ok"], 1)

    def test_reverse_direction_ok_does_not_count(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        count = {"ok": 0, "writes": []}
        window.handle_screw_ok = lambda: count.__setitem__("ok", count["ok"] + 1)
        window.write_tool_register = lambda register, value: count["writes"].append((register, value)) or True

        window.process_tool_poll_result(status=2, trigger=1, direction=2)

        self.assertEqual(count["ok"], 0)
        self.assertIn((4, 2), count["writes"])
        self.assertIn((53, 0), count["writes"])
        self.assertEqual(
            window.message_label.text(),
            "螺钉枪反转状态，已强制锁定，禁止作业。",
        )

    def test_reverse_direction_ng_locks_without_showing_ng_dialog(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        calls = {"dialog": 0, "writes": []}
        window.show_tool_ng_unlock_dialog = lambda: calls.__setitem__("dialog", calls["dialog"] + 1)
        window.write_tool_register = lambda register, value: calls["writes"].append((register, value)) or True

        window.process_tool_poll_result(status=3, trigger=1, direction=2)

        self.assertFalse(window.tool_ng_locked)
        self.assertEqual(calls["dialog"], 0)
        self.assertIn((4, 2), calls["writes"])

    def test_unknown_direction_does_not_count_or_process_ng(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        calls = {"ok": 0, "ng": 0}
        window.handle_screw_ok = lambda: calls.__setitem__("ok", calls["ok"] + 1)
        window.handle_screw_ng = lambda: calls.__setitem__("ng", calls["ng"] + 1)

        window.process_tool_poll_result(status=2, trigger=1, direction=9)
        window.process_tool_poll_result(status=3, trigger=1, direction=9)

        self.assertEqual(calls, {"ok": 0, "ng": 0})
        self.assertEqual(window.message_label.text(), "未知方向值 9，不计数")

    def test_forward_direction_ng_locks_tool_and_opens_admin_unlock(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        calls = {"dialog": 0, "writes": []}
        window.show_tool_ng_unlock_dialog = lambda: calls.__setitem__("dialog", calls["dialog"] + 1)
        window.write_tool_register = lambda register, value: calls["writes"].append((register, value)) or True

        window.process_tool_poll_result(status=3, trigger=1, direction=3)

        self.assertTrue(window.tool_ng_locked)
        self.assertEqual(calls["dialog"], 1)
        self.assertIn((4, 2), calls["writes"])
        self.assertIn((53, 0), calls["writes"])

    def test_forward_direction_status_four_is_also_ng(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        calls = {"dialog": 0, "writes": []}
        window.show_tool_ng_unlock_dialog = lambda: calls.__setitem__(
            "dialog", calls["dialog"] + 1
        )
        window.write_tool_register = (
            lambda register, value: calls["writes"].append((register, value))
            or True
        )

        window.process_tool_poll_result(status=4, trigger=1, direction=3)

        self.assertTrue(window.tool_ng_locked)
        self.assertEqual(calls["dialog"], 1)
        self.assertIn((4, 2), calls["writes"])
        self.assertIn((53, 0), calls["writes"])

    def test_reverse_direction_blocks_admin_unlock(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        writes = []
        window.write_tool_register = (
            lambda register, value: writes.append((register, value)) or True
        )
        window.tool_ng_locked = True
        window.tool_direction_value = 2

        self.assertFalse(window.unlock_tool_after_ng("0000"))
        self.assertTrue(window.tool_ng_locked)
        self.assertIn((4, 2), writes)
        self.assertIn("反转状态", window.message_label.text())

    def test_degraded_mode_stops_workers_and_ignores_tool_signals(self):
        window = self.make_window()
        window.degrade_mode_requires_admin = False
        calls = {"tool_stop": 0, "plc_stop": 0, "ok": 0}
        window.stop_tool_worker = lambda *args, **kwargs: calls.__setitem__(
            "tool_stop", calls["tool_stop"] + 1
        )
        window.stop_plc_worker = lambda: calls.__setitem__(
            "plc_stop", calls["plc_stop"] + 1
        )
        window.handle_screw_ok = lambda: calls.__setitem__("ok", calls["ok"] + 1)

        window.degraded_mode_checkbox.setChecked(True)
        window.process_tool_poll_result(status=2, trigger=1, direction=3)

        self.assertGreaterEqual(calls["tool_stop"], 1)
        self.assertGreaterEqual(calls["plc_stop"], 1)
        self.assertEqual(calls["ok"], 0)
        self.assertIn("不进行防错控制", window.message_label.text())

    def test_station_worker_sync_connects_only_when_screw_step_exists(self):
        window = self.make_window()
        window.disable_tool_auto_listen_checkbox.setChecked(False)
        calls = {"connect": 0, "stop": 0}
        running = {"value": False}
        window.is_tool_worker_running = lambda: running["value"]
        window.toggle_tool_connection = lambda: calls.__setitem__(
            "connect", calls["connect"] + 1
        )
        window.stop_tool_worker = lambda *args, **kwargs: calls.__setitem__(
            "stop", calls["stop"] + 1
        )
        window.current_product = ProductConfig(
            "含螺丝", [ProcessStep("打螺丝", SCREW, required_count=1)]
        )
        window.sync_workers_for_station()
        self.assertEqual(calls["connect"], 1)

        running["value"] = True
        window.current_product = ProductConfig(
            "无螺丝", [ProcessStep("扫码", SCAN, is_main_barcode=True)]
        )
        window.sync_workers_for_station()
        self.assertEqual(calls["stop"], 1)

    def test_cancelcode_enters_mode_and_cancels_next_main_barcode(self):
        window = self.make_window()
        window.cancel_requires_admin = False
        window.online_mode = True
        window.station_config_loaded = True
        window.station_session_acquired = True
        window.production_enabled = True
        window.current_project.id = 1
        window.current_station.id = 2
        window.current_barcode = "MAIN-CANCEL"
        window.current_product_instance_id = 3
        window.prompt_current_step_start = lambda *args, **kwargs: None
        posted = []
        window.api_post = lambda path, payload: (
            posted.append((path, payload))
            or {"ok": True, "cancel_type": "main_barcode"}
        )

        self.assertTrue(window.handle_scanned_barcode("cancelcode"))
        self.assertTrue(window.cancel_mode_active)
        self.assertTrue(window.handle_scanned_barcode("MAIN-CANCEL"))

        self.assertFalse(window.cancel_mode_active)
        self.assertEqual(window.current_barcode, "")
        self.assertEqual(posted[0][0], "/api/client/barcode/cancel")
        self.assertTrue(posted[0][1]["is_main_barcode"])

    def test_cancelcode_mode_expires(self):
        window = self.make_window()
        window.cancel_requires_admin = False
        values = iter([1000.0, 32000.0])
        window.scanner_now_ms = lambda: next(values)
        window.enter_cancel_barcode_mode()
        window.expire_cancel_barcode_mode()
        self.assertFalse(window.cancel_mode_active)
        self.assertIn("超时", window.message_label.text())

    def test_first_plc_step_starts_worker_and_advances_only_that_step(self):
        window = self.make_window()
        plc_step = ProcessStep("PLC接收", PLC, is_main_barcode=True)
        scan_step = ProcessStep("后续扫码", SCAN)
        window.current_product = ProductConfig("PLC首工序", [plc_step, scan_step])
        window.current_station.product = window.current_product
        window.current_step_index = 0
        window.online_mode = True
        window.station_config_loaded = True
        window.station_session_acquired = True
        window.production_enabled = True
        starts = []
        window.sync_workers_for_station = lambda: None
        window.start_plc_worker = lambda step: starts.append(step)

        window.prompt_current_step_start()

        self.assertEqual(starts, [plc_step])
        self.assertFalse(scan_step.done)

    def test_ng_correct_password_unlocks_tool(self):
        window = self.make_window()
        window.tool_ng_locked = True
        window.tool_lock_state = "locked"
        writes = []
        window.write_tool_register = lambda register, value: writes.append((register, value)) or True

        self.assertTrue(window.unlock_tool_after_ng("0000"))

        self.assertFalse(window.tool_ng_locked)
        self.assertIn((4, 1), writes)
        self.assertIn((53, 0), writes)
        self.assertEqual(window.message_label.text(), "已解锁，请重新打当前这颗螺丝")

    def test_ng_wrong_password_keeps_tool_locked(self):
        window = self.make_window()
        window.tool_ng_locked = True
        writes = []
        window.write_tool_register = lambda register, value: writes.append((register, value)) or True

        self.assertFalse(window.unlock_tool_after_ng("9999"))

        self.assertTrue(window.tool_ng_locked)
        self.assertIn((4, 2), writes)
        self.assertNotIn((4, 1), writes)

    def test_reverse_trigger_does_not_count_when_direction_returns_forward_until_reset_seen(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        count = {"ok": 0}
        window.handle_screw_ok = lambda: count.__setitem__("ok", count["ok"] + 1)
        window.write_tool_register = lambda register, value: True

        window.process_tool_poll_result(status=2, trigger=1, direction=2)
        window.process_tool_poll_result(status=2, trigger=1, direction=3)
        self.assertEqual(count["ok"], 0)

        window.process_tool_poll_result(status=2, trigger=0, direction=3)
        window.process_tool_poll_result(status=2, trigger=1, direction=3)
        self.assertEqual(count["ok"], 1)

    def test_non_screw_step_locks_tool_and_never_counts(self):
        window = self.make_window()
        count = {"ok": 0, "writes": []}
        window.handle_screw_ok = lambda: count.__setitem__("ok", count["ok"] + 1)
        window.write_tool_register = lambda register, value: count["writes"].append((register, value)) or True

        window.process_tool_poll_result(status=2, trigger=1, direction=3)

        self.assertEqual(count["ok"], 0)
        self.assertIn((4, 2), count["writes"])

    def test_enter_and_leave_screw_step_use_unlock_and_lock_values(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        writes = []
        window.is_tool_worker_running = lambda: True
        window.write_tool_register = lambda register, value: writes.append((register, value)) or True

        window.enter_tool_screw_step(window.current_step())
        self.assertIn((53, 0), writes)
        self.assertIn((4, 1), writes)

        writes.clear()
        window.close_tool_for_screw_step()
        self.assertIn((4, 2), writes)
        self.assertIn((53, 0), writes)

    def test_start_listener_while_in_screw_step_unlocks_tool(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        writes = []
        window.write_tool_register = lambda register, value: writes.append((register, value)) or True

        window.sync_tool_lock_for_current_step()

        self.assertIn((53, 0), writes)
        self.assertIn((4, 1), writes)

    def test_enter_screw_step_starts_long_connection_when_auto_listen_enabled(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        calls = {"connect": 0}
        window.is_tool_worker_running = lambda: False
        window.toggle_tool_connection = lambda: calls.__setitem__("connect", calls["connect"] + 1)
        window.disable_tool_auto_listen_checkbox.setChecked(False)

        window.enter_tool_screw_step(window.current_step())

        self.assertEqual(calls["connect"], 1)

    def test_reconnect_requires_trigger_zero_before_next_forward_count(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        calls = {"ok": 0, "writes": []}
        window.handle_screw_ok = lambda: calls.__setitem__("ok", calls["ok"] + 1)
        window.write_tool_register = (
            lambda register, value: calls["writes"].append((register, value)) or True
        )

        window.on_tool_connection_state("connected")
        self.assertIn((53, 0), calls["writes"])
        self.assertIn((4, 1), calls["writes"])

        window.process_tool_poll_result(status=2, trigger=1, direction=3)
        self.assertEqual(calls["ok"], 0)
        self.assertTrue(window.tool_connection_rearming)

        window.process_tool_poll_result(status=2, trigger=0, direction=3)
        self.assertFalse(window.tool_connection_rearming)
        window.process_tool_poll_result(status=2, trigger=1, direction=3)
        self.assertEqual(calls["ok"], 1)

    def test_trigger_still_one_while_waiting_retries_clear_without_duplicate_count(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        calls = {"ok": 0, "writes": []}
        window.handle_screw_ok = lambda: calls.__setitem__("ok", calls["ok"] + 1)
        window.write_tool_register = (
            lambda register, value: calls["writes"].append((register, value)) or True
        )
        window.waiting_tool_trigger_reset = True

        window.process_tool_poll_result(status=2, trigger=1, direction=3)

        self.assertEqual(calls["ok"], 0)
        self.assertIn((53, 0), calls["writes"])
        self.assertTrue(window.waiting_tool_trigger_reset)

    def test_trigger_reset_write_success_releases_waiting_lock(self):
        window = self.make_window()
        window.waiting_tool_trigger_reset = True
        window.tool_connection_rearming = True

        window.on_tool_write_succeeded_for_generation(
            window.tool_worker_generation,
            window.tool_trigger_register_input.value(),
            window.tool_trigger_reset_value_input.value(),
        )

        self.assertFalse(window.waiting_tool_trigger_reset)
        self.assertFalse(window.tool_connection_rearming)

    def test_trigger_reset_write_failure_keeps_waiting_for_retry(self):
        window = self.make_window()
        window.waiting_tool_trigger_reset = False

        window.on_tool_write_error_for_generation(
            window.tool_worker_generation,
            window.tool_trigger_register_input.value(),
            window.tool_trigger_reset_value_input.value(),
            "write failed",
        )

        self.assertTrue(window.waiting_tool_trigger_reset)

    def test_tenth_ok_turns_green_and_queues_clear_before_lock(self):
        window = self.make_window()
        step = ProcessStep("打螺丝10颗", SCREW, required_count=10, completed_count=9)
        window.current_product = ProductConfig("十颗螺丝测试", [step])
        window.current_station.product = window.current_product
        window.current_step_index = 0
        window.tool_forward_value_input.setValue(3)
        window.tool_reverse_value_input.setValue(2)
        writes = []
        window.is_tool_worker_running = lambda: True
        window.write_tool_register = lambda register, value: writes.append((register, value)) or True

        window.process_tool_poll_result(status=2, trigger=1, direction=3)

        self.assertEqual(step.completed_count, 10)
        self.assertTrue(step.done)
        self.assertEqual(window.screw_progress_label.text(), "已完成：10 / 10")
        self.assertTrue(all("#22c55e" in block.styleSheet() for block in window.screw_blocks))
        self.assertEqual(writes[:3], [(53, 0), (4, 2), (53, 0)])
        self.assertTrue(window.waiting_tool_trigger_reset)

        window.on_tool_write_succeeded_for_generation(
            window.tool_worker_generation,
            53,
            0,
        )
        window.process_tool_poll_result(status=2, trigger=1, direction=3)
        self.assertEqual(step.completed_count, 10)

    def test_ng_lock_is_preserved_when_connection_recovers(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        window.tool_ng_locked = True
        writes = []
        window.write_tool_register = lambda register, value: writes.append((register, value)) or True

        window.on_tool_connection_state("connected")

        self.assertTrue(window.tool_ng_locked)
        self.assertIn((53, 0), writes)
        self.assertIn((4, 2), writes)
        self.assertNotIn((4, 1), writes)

    def test_non_screw_step_is_locked_when_connection_recovers(self):
        window = self.make_window()
        writes = []
        window.write_tool_register = lambda register, value: writes.append((register, value)) or True

        window.on_tool_connection_state("connected")

        self.assertIn((53, 0), writes)
        self.assertIn((4, 2), writes)
        self.assertNotIn((4, 1), writes)

    def test_manual_disconnect_does_not_clear_ng_business_lock(self):
        window = self.make_window()
        window.tool_ng_locked = True

        window.cleanup_tool_worker()

        self.assertTrue(window.tool_ng_locked)

    def test_screw_progress_uses_large_clear_blocks(self):
        window = self.make_window()
        step = ProcessStep("打螺丝5颗", SCREW, required_count=5, completed_count=3)

        window.render_screw_blocks(step)

        self.assertEqual(len(window.screw_blocks), 5)
        self.assertEqual((window.screw_blocks[0].width(), window.screw_blocks[0].height()), (80, 72))
        self.assertEqual(window.screw_progress_label.text(), "已完成：3 / 5")
        self.assertIn("#22c55e", window.screw_blocks[2].styleSheet())
        self.assertIn("#d1d5db", window.screw_blocks[3].styleSheet())

    def test_ten_screw_blocks_render_as_two_rows_of_five(self):
        window = self.make_window()
        step = ProcessStep("打螺丝10颗", SCREW, required_count=10)

        window.render_screw_blocks(step)

        positions = [window.screw_grid.getItemPosition(index + 1) for index in range(10)]
        self.assertEqual([position[0] for position in positions[:5]], [1] * 5)
        self.assertEqual([position[0] for position in positions[5:]], [2] * 5)
        self.assertEqual([position[1] for position in positions[:5]], list(range(5)))
        self.assertIn("4px solid #2563eb", window.screw_blocks[0].styleSheet())

    def test_scan_input_is_compact_single_row(self):
        window = self.make_window()

        self.assertEqual(window.barcode_input.height(), 40)
        self.assertEqual(window.scan_btn.height(), 40)


if __name__ == "__main__":
    unittest.main()
