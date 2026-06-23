import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

import desktop_app.window as window_module
from desktop_app.window import QualityControlWindow
from shared.models import ProcessStep, ProductConfig, SCAN, SCREW


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

        window.barcode_input.setText("MAIN-001")
        window.handle_scan()
        self.assertEqual(window.current_barcode, "MAIN-001")

        window.barcode_input.setText("PART-001")
        window.handle_scan()
        self.assertEqual(window.current_barcode, "MAIN-001")

        window.handle_screw_ok()
        self.assertEqual(window.current_barcode, "")
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


if __name__ == "__main__":
    unittest.main()
