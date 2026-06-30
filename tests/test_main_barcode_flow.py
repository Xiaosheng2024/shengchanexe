import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from web_admin_app import database, services
from web_admin_app.server import AdminHandler, load_server_config


class ServerConfigTest(unittest.TestCase):
    def test_server_config_defaults_to_all_interfaces(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "missing.ini"
            self.assertEqual(load_server_config(config_path), {"host": "0.0.0.0", "port": 8000})

    def test_server_config_reads_host_and_port(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.ini"
            config_path.write_text("[SERVER]\nhost = 0.0.0.0\nport = 8123\n", encoding="utf-8")
            self.assertEqual(load_server_config(config_path), {"host": "0.0.0.0", "port": 8123})


class MainBarcodeFlowTest(unittest.TestCase):
    def setUp(self):
        self.old_db_path = database.DB_PATH
        self.old_config_path = database.CONFIG_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_dir.name) / "quality_control.db"
        database.CONFIG_PATH = Path(self.temp_dir.name) / "config.ini"
        database.CONFIG_PATH.write_text(f"[DATABASE]\ntype = sqlite\npath = {database.DB_PATH}\n", encoding="utf-8")
        database.init_db()
        self.project = services.list_projects_full()[0]
        self.station1 = self.project["stations"][0]
        self.station2 = self.project["stations"][1]

    def tearDown(self):
        database.DB_PATH = self.old_db_path
        database.CONFIG_PATH = self.old_config_path
        self.temp_dir.cleanup()

    def main_steps(self, station_id):
        return [step for step in services.list_steps(station_id) if step["is_main_barcode"]]

    def test_station_has_exactly_one_main_barcode(self):
        self.assertEqual(len(self.main_steps(self.station1["id"])), 1)
        self.assertEqual(self.main_steps(self.station1["id"])[0]["type"], "PLC接收")
        self.assertEqual(self.main_steps(self.station1["id"])[0]["plc_ip"], "10.162.86.65")

    def test_setting_new_main_barcode_clears_old_main(self):
        services.add_step(
            {
                "station_id": self.station1["id"],
                "name": "扫码新主条码",
                "type": "扫码",
                "step_order": 1,
                "barcode_start": 1,
                "barcode_end": 7,
                "is_main_barcode": True,
            }
        )
        main_steps = self.main_steps(self.station1["id"])
        self.assertEqual(len(main_steps), 1)
        self.assertEqual(main_steps[0]["name"], "扫码新主条码")

    def test_main_barcode_must_be_first_step(self):
        with self.assertRaisesRegex(ValueError, "非第一工位的主条码工序必须是当前工位第1道工序"):
            services.add_step(
                {
                    "station_id": self.station2["id"],
                    "name": "扫码后置主条码",
                    "type": "扫码",
                    "step_order": 9,
                    "barcode_start": 1,
                    "barcode_end": 7,
                    "is_main_barcode": True,
                }
            )

    def test_first_station_plc_main_barcode_can_be_moved(self):
        main_step = self.main_steps(self.station1["id"])[0]
        services.update_step(
            main_step["id"],
            {
                "station_id": self.station1["id"],
                "name": main_step["name"],
                "type": "PLC接收",
                "step_order": 3,
                "is_main_barcode": True,
            },
        )
        self.assertEqual(self.main_steps(self.station1["id"])[0]["step_order"], 3)

    def test_plc_main_barcode_config_uses_new_field_names(self):
        steps = services.list_steps(self.station1["id"])
        plc_step = steps[0]
        self.assertIn("plc_barcode_db", plc_step)
        self.assertEqual(plc_step["plc_barcode_db"], 201)
        config = services.get_station_config(f"/api/projects/{self.project['name']}/stations/{self.station1['name']}/config")
        self.assertIn("plc_barcode_db", config["steps"][0])
        self.assertEqual(config["steps"][0]["plc_barcode_db"], 201)

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
        with self.assertRaisesRegex(ValueError, "只有扫码工序或PLC接收工序可以设置为主条码"):
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

    def test_traceability_records_are_saved_and_paginated_by_barcode(self):
        barcode = "TRACE-001"
        production = services.add_production_record(
            {
                "project_id": self.project["id"],
                "station_id": self.station1["id"],
                "main_barcode": barcode,
                "product_name": "测试产品",
                "station_name": self.station1["name"],
                "start_time": "2026-06-26T10:00:00",
                "end_time": "2026-06-26T10:01:00",
                "work_duration_seconds": 60,
                "total_steps": 2,
                "completed_steps": 2,
                "result": "OK",
            }
        )
        step = services.add_step_record(
            {
                "station_work_id": production["id"],
                "project_id": self.project["id"],
                "station_id": self.station1["id"],
                "main_barcode": barcode,
                "step_name": "打螺丝",
                "step_type": "螺丝",
                "step_order": 1,
                "start_time": "2026-06-26T10:00:20",
                "result": "OK",
            }
        )
        services.add_screw_record(
            {
                "station_work_id": production["id"],
                "step_work_id": step["id"],
                "project_id": self.project["id"],
                "station_id": self.station1["id"],
                "main_barcode": barcode,
                "step_name": "打螺丝",
                "screw_index": 1,
                "required_count": 1,
                "status_value": 2,
                "trigger_value": 1,
                "direction_value": 0,
                "result": "OK",
                "is_counted": True,
            }
        )

        production_records = services.list_production_records({"main_barcode": [barcode], "page_size": ["1"]})
        trace = services.get_trace({"barcode": [barcode]})

        self.assertEqual(production_records["page_size"], 1)
        self.assertEqual(len(production_records["records"]), 1)
        self.assertEqual(trace["production_records"][0]["main_barcode"], barcode)
        self.assertEqual(trace["step_records"][0]["step_name"], "打螺丝")
        self.assertEqual(trace["screw_records"][0]["result"], "OK")

    def test_station_session_conflict_and_force_acquire(self):
        payload1 = {
            "project_id": self.project["id"],
            "station_id": self.station1["id"],
            "client_id": "client-a",
            "computer_name": "PC-A",
            "ip_address": "10.0.0.1",
        }
        payload2 = {
            "project_id": self.project["id"],
            "station_id": self.station1["id"],
            "client_id": "client-b",
            "computer_name": "PC-B",
            "ip_address": "10.0.0.2",
        }
        self.assertTrue(services.acquire_station_session(payload1)["ok"])
        conflict = services.acquire_station_session(payload2)
        self.assertFalse(conflict["ok"])
        self.assertEqual(conflict["conflict"]["computer_name"], "PC-A")
        with self.assertRaisesRegex(ValueError, "管理员密码错误"):
            services.acquire_station_session(dict(payload2, admin_password="1111"), force=True)
        self.assertTrue(services.acquire_station_session(dict(payload2, admin_password="0000"), force=True)["ok"])

    def test_admin_release_station_session_marks_offline(self):
        payload = {
            "project_id": self.project["id"],
            "station_id": self.station1["id"],
            "client_id": "client-a",
            "computer_name": "PC-A",
            "ip_address": "10.0.0.1",
        }
        self.assertTrue(services.acquire_station_session(payload)["ok"])
        session = services.list_station_sessions()["sessions"][0]
        with self.assertRaisesRegex(ValueError, "管理员密码错误"):
            services.admin_release_station_session({"session_id": session["id"], "admin_password": "bad"})
        self.assertTrue(services.admin_release_station_session({"session_id": session["id"], "admin_password": "0000"})["ok"])
        self.assertEqual(services.list_station_sessions()["sessions"], [])

    def test_station_session_same_client_refreshes_and_stale_session_releases(self):
        payload = {
            "project_id": self.project["id"],
            "station_id": self.station1["id"],
            "client_id": "client-a",
            "computer_name": "PC-A",
            "ip_address": "10.0.0.1",
        }
        first = services.acquire_station_session(payload)
        second = services.acquire_station_session(payload)
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual(first["session_id"], second["session_id"])
        sessions = services.list_station_sessions()["sessions"]
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["client_id"], "client-a")

        stale_time = (datetime.now() - timedelta(seconds=180)).isoformat(timespec="seconds")
        with database.get_conn() as conn:
            conn.execute("UPDATE station_sessions SET last_heartbeat_at = ? WHERE client_id = ?", (stale_time, "client-a"))
        payload2 = dict(payload, client_id="client-b", computer_name="PC-B", ip_address="10.0.0.2")
        self.assertTrue(services.acquire_station_session(payload2)["ok"])
        sessions = services.list_station_sessions()["sessions"]
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["client_id"], "client-b")

    def test_release_station_session_is_idempotent(self):
        payload = {
            "project_id": self.project["id"],
            "station_id": self.station1["id"],
            "client_id": "client-idempotent",
            "computer_name": "PC-A",
            "ip_address": "10.0.0.1",
        }
        self.assertTrue(services.release_station_session(payload)["ok"])
        self.assertTrue(services.acquire_station_session(payload)["ok"])
        self.assertTrue(services.release_station_session(payload)["ok"])
        self.assertTrue(services.release_station_session(payload)["ok"])
        self.assertEqual(services.list_station_sessions()["sessions"], [])

    def test_station_session_accepts_legacy_device_payload_names(self):
        payload = {
            "project_id": self.project["id"],
            "station_id": self.station1["id"],
            "device_id": "legacy-client",
            "device_name": "Legacy-PC",
            "ip_address": "10.0.0.9",
        }
        self.assertTrue(services.acquire_station_session(payload)["ok"])
        sessions = services.list_station_sessions()["sessions"]
        self.assertEqual(sessions[0]["client_id"], "legacy-client")
        self.assertEqual(sessions[0]["computer_name"], "Legacy-PC")
        self.assertFalse(
            services.check_station_completion(
                {
                    "project": [self.project["name"]],
                    "previous_station": [self.station1["name"]],
                    "barcode": ["PART-ONLY"],
                }
            )["completed"]
        )

    def test_station_session_query_does_not_create_or_update_sessions(self):
        with database.get_conn() as conn:
            conn.execute("DELETE FROM station_sessions WHERE station_id = ?", (self.station1["id"],))
            before_sessions = conn.execute("SELECT COUNT(*) AS total FROM station_sessions").fetchone()["total"]
            before_logs = conn.execute("SELECT COUNT(*) AS total FROM station_session_logs").fetchone()["total"]

        self.assertEqual(services.list_station_sessions({"status": ["online"]})["sessions"], [])

        with database.get_conn() as conn:
            after_sessions = conn.execute("SELECT COUNT(*) AS total FROM station_sessions").fetchone()["total"]
            after_logs = conn.execute("SELECT COUNT(*) AS total FROM station_session_logs").fetchone()["total"]
        self.assertEqual(after_sessions, before_sessions)
        self.assertEqual(after_logs, before_logs)

    def test_web_admin_online_session_api_does_not_create_sessions(self):
        with database.get_conn() as conn:
            conn.execute("DELETE FROM station_sessions")

        server = ThreadingHTTPServer(("127.0.0.1", 0), AdminHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            with self.assertRaises(HTTPError) as raised:
                urlopen(f"http://127.0.0.1:{port}/api/station-sessions?status=online", timeout=3)
            self.assertEqual(raised.exception.code, 401)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

        with database.get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) AS total FROM station_sessions").fetchone()["total"]
        self.assertEqual(total, 0)

    def test_client_release_latest_and_report_logging(self):
        services.upsert_client_release(
            {
                "version": "v0.8.4",
                "title": "旧版本",
                "release_notes": ["old"],
                "release_date": "2026-06-27 10:00:00",
                "stable": True,
                "force_update": False,
                "min_required_version": "v0.8.0",
            }
        )
        services.upsert_client_release(
            {
                "version": "v0.8.5",
                "title": "新版本",
                "release_notes": ["new"],
                "release_date": "2026-06-28 10:00:00",
                "stable": True,
                "force_update": False,
                "min_required_version": "v0.8.0",
            }
        )
        latest = services.latest_client_release({"client_version": ["v0.8.4"], "channel": ["stable"]})
        self.assertTrue(latest["data"]["has_update"])
        self.assertEqual(latest["data"]["latest_version"], "v0.8.5")
        self.assertIn("/api/client-update/download/v0.8.5/release", latest["data"]["download_url"])

        services.report_client_update(
            {
                "client_id": "client-1",
                "computer_name": "PC-1",
                "ip_address": "127.0.0.1",
                "current_version": "v0.8.4",
                "target_version": "v0.8.5",
                "action": "download",
                "result": "success",
                "message": "下载完成",
            }
        )
        logs = services.list_client_update_logs({"page": ["1"], "page_size": ["10"]})["records"]
        self.assertEqual(logs[0]["client_id"], "client-1")
        self.assertEqual(logs[0]["target_version"], "v0.8.5")


class OldDatabaseMigrationTest(unittest.TestCase):
    def test_old_steps_table_gets_main_barcode_column_and_default_main(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_db_path = database.DB_PATH
            old_config_path = database.CONFIG_PATH
            database.DB_PATH = Path(temp_dir) / "old.db"
            database.CONFIG_PATH = Path(temp_dir) / "config.ini"
            database.CONFIG_PATH.write_text(f"[DATABASE]\ntype = sqlite\npath = {database.DB_PATH}\n", encoding="utf-8")
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
                self.assertIn("plc_barcode_db", columns)
                self.assertIn("plc_barcode_offset", columns)
                self.assertIn("plc_barcode_length", columns)
                self.assertIn("switch_disable_old", columns)
                self.assertIn("bind_required_station_ids", columns)
                main_count = conn.execute(
                    "SELECT COUNT(*) AS total FROM steps WHERE station_id = 1 AND is_main_barcode = 1"
                ).fetchone()["total"]
                self.assertEqual(main_count, 1)
                flow_tables = {
                    row["name"]
                    for row in conn.execute(
                        """
                        SELECT name FROM sqlite_master
                        WHERE type = 'table'
                        """
                    ).fetchall()
                }
                self.assertTrue(
                    {
                        "product_instances",
                        "barcode_aliases",
                        "barcode_switch_records",
                        "material_bindings",
                        "station_dependencies",
                    }.issubset(flow_tables)
                )
            database.DB_PATH = old_db_path
            database.CONFIG_PATH = old_config_path


if __name__ == "__main__":
    unittest.main()
