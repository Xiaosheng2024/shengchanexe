import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QLabel

import desktop_app.window as window_module
from desktop_app.window import APP_VERSION, QualityControlWindow
from shared.models import PLC, ProcessStep, ProductConfig, SCAN, SCREW


class DesktopMainBarcodeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self):
        window_module.shutil.which = lambda command: None
        window = QualityControlWindow()
        window.speak = lambda text: None
        window.play_ok_sound = lambda: None
        window.show_auto_close_warning = lambda title, message: None
        return window

    def set_current_step_to_screw(self, window):
        window.current_product = ProductConfig("螺丝测试", [ProcessStep("打螺丝1颗", SCREW, required_count=1)])
        window.current_station.product = window.current_product
        window.current_step_index = 0

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
        self.assertEqual(window.current_barcode, "")
        self.assertEqual(window.main_barcode_label.text(), "当前主条码：未扫描")
        self.assertEqual(window.current_step_index, 0)

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
        self.assertIn(APP_VERSION, window.windowTitle())

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
            "正向值",
            "反向值",
            "轮询间隔ms",
            "通讯超时秒",
        ]:
            self.assertNotIn(text, main_labels)
        self.assertEqual(window.tool_settings_dialog.windowTitle(), "螺钉枪高级设置")
        self.assertEqual(window.tool_control_register_input.value(), 4)
        self.assertEqual(window.tool_lock_value_input.value(), 2)
        self.assertEqual(window.tool_unlock_value_input.value(), 1)
        self.assertEqual(window.tool_direction_register_input.value(), 54)
        self.assertEqual(window.tool_forward_value_input.value(), 0)
        self.assertEqual(window.tool_reverse_value_input.value(), 1)

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
            window.tool_clear_trigger_when_reverse_checkbox.setChecked(False)
            window.tool_poll_interval_input.setValue(1200)
            window.tool_timeout_input.setValue(2)
            window.tool_admin_password_input.setText("1234")
            window.tool_enable_dedup_checkbox.setChecked(False)
            window.tool_verbose_log_checkbox.setChecked(True)

            window.save_tool_settings()

            loaded = self.make_window()
            loaded.app_config_path = config_path
            loaded.load_tool_settings()

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

        window.process_tool_poll_result(status=2, trigger=1, direction=0)
        window.process_tool_poll_result(status=2, trigger=1, direction=0)
        self.assertEqual(count["ok"], 1)

        window.process_tool_poll_result(status=2, trigger=0, direction=0)
        window.process_tool_poll_result(status=2, trigger=1, direction=0)
        self.assertEqual(count["ok"], 2)
        self.assertIn((53, 0), count["writes"])

    def test_tool_trigger_lock_releases_only_after_trigger_reset_zero(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        count = {"ok": 0}
        window.handle_screw_ok = lambda: count.__setitem__("ok", count["ok"] + 1)
        window.write_tool_register = lambda register, value: None

        window.process_tool_poll_result(status=2, trigger=1, direction=0)
        window.process_tool_poll_result(status=2, trigger=2, direction=0)
        window.process_tool_poll_result(status=2, trigger=1, direction=0)
        self.assertEqual(count["ok"], 1)

        window.process_tool_poll_result(status=2, trigger=0, direction=0)
        window.process_tool_poll_result(status=2, trigger=1, direction=0)
        self.assertEqual(count["ok"], 2)

    def test_tool_dedup_can_be_disabled_from_advanced_settings(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        window.tool_enable_dedup_checkbox.setChecked(False)
        count = {"ok": 0}
        window.handle_screw_ok = lambda: count.__setitem__("ok", count["ok"] + 1)
        window.write_tool_register = lambda register, value: None

        window.process_tool_poll_result(status=2, trigger=1, direction=0)
        window.process_tool_poll_result(status=2, trigger=1, direction=0)

        self.assertEqual(count["ok"], 2)

    def test_reverse_direction_ok_does_not_count(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        count = {"ok": 0, "writes": []}
        window.handle_screw_ok = lambda: count.__setitem__("ok", count["ok"] + 1)
        window.write_tool_register = lambda register, value: count["writes"].append((register, value)) or True

        window.process_tool_poll_result(status=2, trigger=1, direction=1)

        self.assertEqual(count["ok"], 0)
        self.assertIn((53, 0), count["writes"])
        self.assertEqual(window.message_label.text(), "反向状态，不计数")

    def test_reverse_direction_ng_does_not_lock_or_show_ng(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        calls = {"dialog": 0, "writes": []}
        window.show_tool_ng_unlock_dialog = lambda: calls.__setitem__("dialog", calls["dialog"] + 1)
        window.write_tool_register = lambda register, value: calls["writes"].append((register, value)) or True

        window.process_tool_poll_result(status=3, trigger=1, direction=1)

        self.assertFalse(window.tool_ng_locked)
        self.assertEqual(calls["dialog"], 0)
        self.assertNotIn((4, 2), calls["writes"])

    def test_forward_direction_ng_locks_tool_and_opens_admin_unlock(self):
        window = self.make_window()
        self.set_current_step_to_screw(window)
        calls = {"dialog": 0, "writes": []}
        window.show_tool_ng_unlock_dialog = lambda: calls.__setitem__("dialog", calls["dialog"] + 1)
        window.write_tool_register = lambda register, value: calls["writes"].append((register, value)) or True

        window.process_tool_poll_result(status=3, trigger=1, direction=0)

        self.assertTrue(window.tool_ng_locked)
        self.assertEqual(calls["dialog"], 1)
        self.assertIn((4, 2), calls["writes"])
        self.assertIn((53, 0), calls["writes"])

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

        window.process_tool_poll_result(status=2, trigger=1, direction=1)
        window.process_tool_poll_result(status=2, trigger=1, direction=0)
        self.assertEqual(count["ok"], 0)

        window.process_tool_poll_result(status=2, trigger=0, direction=0)
        window.process_tool_poll_result(status=2, trigger=1, direction=0)
        self.assertEqual(count["ok"], 1)

    def test_non_screw_step_locks_tool_and_never_counts(self):
        window = self.make_window()
        count = {"ok": 0, "writes": []}
        window.handle_screw_ok = lambda: count.__setitem__("ok", count["ok"] + 1)
        window.write_tool_register = lambda register, value: count["writes"].append((register, value)) or True

        window.process_tool_poll_result(status=2, trigger=1, direction=0)

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


if __name__ == "__main__":
    unittest.main()
