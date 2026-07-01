import tempfile
import unittest
from pathlib import Path

from web_admin_app import database, product_flow, services


class BarcodeSafetyTest(unittest.TestCase):
    def setUp(self):
        self.old_db_path = database.DB_PATH
        self.old_config_path = database.CONFIG_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_dir.name) / "quality_control.db"
        database.CONFIG_PATH = Path(self.temp_dir.name) / "config.ini"
        database.CONFIG_PATH.write_text(
            f"[DATABASE]\ntype = sqlite\npath = {database.DB_PATH}\n",
            encoding="utf-8",
        )
        database.init_db()
        self.project = services.add_project(
            {"name": "防错项目", "product_type": "A物料"}
        )
        self.station1 = services.add_station(
            {"project_id": self.project["id"], "name": "工位1"}
        )
        self.station2 = services.add_station(
            {"project_id": self.project["id"], "name": "工位2"}
        )
        self.product = product_flow.resolve_barcode(
            {
                "project_id": self.project["id"],
                "barcode": "MAIN001",
                "product_type": "A物料",
                "create_if_missing": True,
            }
        )

    def tearDown(self):
        database.DB_PATH = self.old_db_path
        database.CONFIG_PATH = self.old_config_path
        self.temp_dir.cleanup()

    def scan_payload(self, station, barcode, is_main, step_id=1):
        return {
            "project_id": self.project["id"],
            "station_id": station["id"],
            "product_instance_id": self.product["product_instance_id"],
            "barcode": barcode,
            "barcode_used": barcode,
            "step_id": step_id,
            "step": f"工序{step_id}",
            "step_type": "扫码",
            "is_main_barcode": is_main,
            "enforce_barcode_unique": True,
            "result": "完成",
        }

    def test_main_barcode_is_unique_per_station_but_allowed_next_station(self):
        payload = self.scan_payload(self.station1, "MAIN001", True)
        self.assertTrue(services.validate_barcode_use(payload)["allowed"])
        services.add_scan_record(payload)
        blocked = services.validate_barcode_use(payload)
        self.assertFalse(blocked["allowed"])
        self.assertIn("当前主条码已在本工位", blocked["message"])
        next_station = self.scan_payload(self.station2, "MAIN001", True)
        self.assertTrue(services.validate_barcode_use(next_station)["allowed"])

    def test_non_main_barcode_cannot_be_reused_then_can_after_cancel(self):
        first = self.scan_payload(self.station1, "PART001", False, step_id=2)
        services.add_scan_record(first)
        second = self.scan_payload(self.station2, "PART001", False, step_id=2)
        blocked = services.validate_barcode_use(second)
        self.assertFalse(blocked["allowed"])
        self.assertIn("该条码已在其他位置使用", blocked["message"])
        result = services.cancel_barcode_record(
            {
                **first,
                "operator": "管理员",
            }
        )
        self.assertEqual(result["cancel_type"], "non_main_barcode")
        self.assertTrue(services.validate_barcode_use(second)["allowed"])

    def test_cancel_main_only_removes_current_station_records(self):
        payload = self.scan_payload(self.station1, "MAIN001", True)
        services.add_scan_record(payload)
        services.add_station_completion(
            {
                "project_id": self.project["id"],
                "station_id": self.station1["id"],
                "product_instance_id": self.product["product_instance_id"],
                "barcode": "MAIN001",
            }
        )
        result = services.cancel_barcode_record({**payload, "operator": "管理员"})
        self.assertEqual(result["cancel_type"], "main_barcode")
        self.assertTrue(services.validate_barcode_use(payload)["allowed"])
        with self.assertRaisesRegex(ValueError, "当前工位没有可取消记录"):
            services.cancel_barcode_record(
                {
                    **payload,
                    "station_id": self.station2["id"],
                    "operator": "管理员",
                }
            )
        resolved = product_flow.resolve_barcode({"barcode": "MAIN001"})
        self.assertTrue(resolved["found"])

    def test_degrade_mode_log_and_migration_are_available(self):
        database.init_db()
        result = services.report_degrade_mode(
            {
                "project_id": self.project["id"],
                "station_id": self.station1["id"],
                "client_id": "client-1",
                "operator": "管理员",
                "action": "enabled",
                "reason": "现场人工放行",
            }
        )
        self.assertTrue(result["id"])
        with database.get_conn() as conn:
            scan_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(scan_records)").fetchall()
            }
            cancel_count = conn.execute(
                "SELECT COUNT(*) AS total FROM barcode_cancel_logs"
            ).fetchone()["total"]
            degrade_count = conn.execute(
                "SELECT COUNT(*) AS total FROM degrade_mode_logs"
            ).fetchone()["total"]
        self.assertTrue(
            {"step_id", "is_main_barcode", "is_cancelled", "cancelled_at"}
            <= scan_columns
        )
        self.assertEqual(cancel_count, 0)
        self.assertEqual(degrade_count, 1)


if __name__ == "__main__":
    unittest.main()
