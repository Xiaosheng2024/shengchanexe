import sqlite3
import tempfile
import unittest
from pathlib import Path

from web_admin_app import database, services


class MainBarcodeFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_dir.name) / "quality_control.db"
        database.init_db()
        self.project = services.list_projects_full()[0]
        self.station1 = self.project["stations"][0]
        self.station2 = self.project["stations"][1]

    def tearDown(self):
        self.temp_dir.cleanup()

    def main_steps(self, station_id):
        return [step for step in services.list_steps(station_id) if step["is_main_barcode"]]

    def test_station_has_exactly_one_main_barcode(self):
        self.assertEqual(len(self.main_steps(self.station1["id"])), 1)
        self.assertEqual(self.main_steps(self.station1["id"])[0]["type"], "扫码")

    def test_setting_new_main_barcode_clears_old_main(self):
        services.add_step(
            {
                "station_id": self.station1["id"],
                "name": "扫码新主条码",
                "type": "扫码",
                "step_order": 9,
                "barcode_start": 1,
                "barcode_end": 7,
                "is_main_barcode": True,
            }
        )
        main_steps = self.main_steps(self.station1["id"])
        self.assertEqual(len(main_steps), 1)
        self.assertEqual(main_steps[0]["name"], "扫码新主条码")

    def test_zero_main_barcode_is_rejected_on_save(self):
        main_step = self.main_steps(self.station1["id"])[0]
        with self.assertRaisesRegex(ValueError, "必须配置一个主条码"):
            services.update_step(
                main_step["id"],
                {
                    "station_id": self.station1["id"],
                    "name": main_step["name"],
                    "type": "扫码",
                    "step_order": main_step["step_order"],
                    "barcode_start": main_step["barcode_start"],
                    "barcode_end": main_step["barcode_end"],
                    "expected_content": main_step["expected_content"],
                    "is_main_barcode": False,
                },
            )
        self.assertEqual(len(self.main_steps(self.station1["id"])), 1)

    def test_screw_step_cannot_be_main_barcode(self):
        with self.assertRaisesRegex(ValueError, "只有扫码工序可以设置为主条码"):
            services.add_step(
                {
                    "station_id": self.station1["id"],
                    "name": "错误主螺丝",
                    "type": "螺丝",
                    "step_order": 10,
                    "required_count": 8,
                    "is_main_barcode": True,
                }
            )

    def test_previous_station_completion_uses_main_barcode_value(self):
        barcode = "MAIN-001"
        services.add_station_completion(
            {
                "project": self.project["name"],
                "station": self.station1["name"],
                "barcode": barcode,
                "completed_at": "2026-06-23T10:00:00",
            }
        )
        self.assertTrue(
            services.check_station_completion(
                {
                    "project": [self.project["name"]],
                    "previous_station": [self.station1["name"]],
                    "barcode": [barcode],
                }
            )["completed"]
        )
        self.assertFalse(
            services.check_station_completion(
                {
                    "project": [self.project["name"]],
                    "previous_station": [self.station1["name"]],
                    "barcode": ["PART-ONLY"],
                }
            )["completed"]
        )


class OldDatabaseMigrationTest(unittest.TestCase):
    def test_old_steps_table_gets_main_barcode_column_and_default_main(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = Path(temp_dir) / "old.db"
            with sqlite3.connect(database.DB_PATH) as conn:
                conn.executescript(
                    """
                    CREATE TABLE projects (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE stations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        project_id INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE steps (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        station_id INTEGER NOT NULL,
                        step_order INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        type TEXT NOT NULL,
                        required_count INTEGER NOT NULL DEFAULT 0,
                        barcode_start INTEGER NOT NULL DEFAULT 1,
                        barcode_end INTEGER NOT NULL DEFAULT 7,
                        expected_content TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL
                    );
                    INSERT INTO projects (name, created_at) VALUES ('旧项目', '2026-06-23T10:00:00');
                    INSERT INTO stations (project_id, name, created_at) VALUES (1, '工位1', '2026-06-23T10:00:00');
                    INSERT INTO steps
                    (station_id, step_order, name, type, required_count, barcode_start, barcode_end, expected_content, created_at)
                    VALUES
                    (1, 1, '旧扫码A', '扫码', 0, 1, 7, '', '2026-06-23T10:00:00'),
                    (1, 2, '旧螺丝', '螺丝', 8, 1, 7, '', '2026-06-23T10:00:00');
                    """
                )
            database.init_db()
            with database.get_conn() as conn:
                columns = [row["name"] for row in conn.execute("PRAGMA table_info(steps)").fetchall()]
                self.assertIn("is_main_barcode", columns)
                main_count = conn.execute(
                    "SELECT COUNT(*) AS total FROM steps WHERE station_id = 1 AND is_main_barcode = 1"
                ).fetchone()["total"]
                self.assertEqual(main_count, 1)


if __name__ == "__main__":
    unittest.main()
