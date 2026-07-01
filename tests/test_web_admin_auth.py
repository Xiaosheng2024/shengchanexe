import http.cookiejar
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from web_admin_app import auth, database, services
from web_admin_app.server import AdminHandler


class WebAdminAuthTest(unittest.TestCase):
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
        auth.ensure_session_secret()
        auth.bootstrap_builtin_accounts("AdminInitial9!", "SuperInitial9!")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), AdminHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        database.DB_PATH = self.old_db_path
        database.CONFIG_PATH = self.old_config_path
        self.temp_dir.cleanup()

    def opener(self):
        return build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def test_postgresql_user_insert_returns_created_id(self):
        self.assertTrue(
            database.needs_returning_id(
                "INSERT INTO web_admin_users (username, password_hash) VALUES (?, ?)"
            )
        )

    def login(self, username, password):
        opener = self.opener()
        request = Request(
            self.base + "/login",
            data=urlencode({"username": username, "password": password}).encode("utf-8"),
            method="POST",
        )
        with opener.open(request, timeout=3) as response:
            self.assertEqual(response.geturl(), self.base + "/")
        return opener

    def json_request(self, opener, path, method="GET", payload=None):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self.base + path, data=data, headers=headers, method=method)
        with opener.open(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def acquire_session(self, project_id, station_id, client_id):
        payload = {
            "project_id": project_id,
            "station_id": station_id,
            "client_id": client_id,
            "computer_name": "test",
        }
        status, acquired = self.json_request(
            self.opener(),
            "/api/station-session/acquire",
            method="POST",
            payload=payload,
        )
        self.assertEqual(status, 200)
        self.assertTrue(acquired["ok"])
        payload["station_session_id"] = acquired["session_id"]
        return payload

    def test_unauthenticated_admin_is_redirected_and_api_returns_401(self):
        with urlopen(self.base + "/", timeout=3) as response:
            self.assertEqual(response.geturl(), self.base + "/login")
        with self.assertRaises(HTTPError) as raised:
            urlopen(self.base + "/api/projects/full", timeout=3)
        self.assertEqual(raised.exception.code, 401)
        with self.assertRaises(HTTPError) as projects_error:
            urlopen(self.base + "/api/projects", timeout=3)
        self.assertEqual(projects_error.exception.code, 401)

    def test_production_client_api_remains_public(self):
        with urlopen(self.base + "/api/client/projects", timeout=3) as response:
            self.assertEqual(response.status, 200)
        project = database.fetch_one("SELECT id, name FROM projects ORDER BY id LIMIT 1")
        station = database.fetch_one("SELECT id, name FROM stations ORDER BY id LIMIT 1")
        status, data = self.json_request(
            self.opener(),
            "/api/station-session/acquire",
            method="POST",
            payload={
                "project_id": project["id"],
                "station_id": station["id"],
                "client_id": "auth-client-test",
                "computer_name": "test",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])

    def test_client_barcode_apis_use_station_session_instead_of_web_login(self):
        project = database.fetch_one(
            "SELECT id, name FROM projects ORDER BY id LIMIT 1"
        )
        station = database.fetch_one(
            "SELECT id, name FROM stations WHERE project_id = ? ORDER BY id LIMIT 1",
            (project["id"],),
        )
        missing_session_payload = {
            "project_id": project["id"],
            "station_id": station["id"],
            "client_id": "barcode-client",
            "barcode": "PART-SESSION-001",
            "step_id": 1,
            "is_main_barcode": False,
        }
        with self.assertRaises(HTTPError) as missing_error:
            self.json_request(
                self.opener(),
                "/api/client/barcode/validate",
                method="POST",
                payload=missing_session_payload,
            )
        self.assertEqual(missing_error.exception.code, 400)
        missing_body = json.loads(
            missing_error.exception.read().decode("utf-8")
        )
        self.assertIn("当前工位未占用成功", missing_body["error"])
        self.assertNotIn("未登录", missing_body["error"])

        session_payload = self.acquire_session(
            project["id"], station["id"], "barcode-client"
        )
        status, validation = self.json_request(
            self.opener(),
            "/api/client/barcode/validate",
            method="POST",
            payload=dict(
                session_payload,
                barcode="PART-SESSION-001",
                step_id=1,
                is_main_barcode=False,
            ),
        )
        self.assertEqual(status, 200)
        self.assertTrue(validation["allowed"])

        services.add_scan_record(
            {
                "project_id": project["id"],
                "station_id": station["id"],
                "barcode": "PART-CANCEL-001",
                "step": "零件扫码",
                "step_id": 1,
                "result": "完成",
                "is_main_barcode": False,
            }
        )
        status, cancelled = self.json_request(
            self.opener(),
            "/api/client/barcode/cancel",
            method="POST",
            payload=dict(
                session_payload,
                barcode="PART-CANCEL-001",
                step_id=1,
                is_main_barcode=False,
                operator="管理员",
            ),
        )
        self.assertEqual(status, 200)
        self.assertEqual(cancelled["cancel_type"], "non_main_barcode")

        status, degraded = self.json_request(
            self.opener(),
            "/api/client/tool/degrade-mode/report",
            method="POST",
            payload=dict(
                session_payload,
                operator="管理员",
                action="enabled",
                reason="测试",
            ),
        )
        self.assertEqual(status, 200)
        self.assertTrue(degraded["ok"])

    def test_station_session_rejects_mismatched_station_without_web_401(self):
        project = database.fetch_one(
            "SELECT id FROM projects ORDER BY id LIMIT 1"
        )
        stations = database.fetch_all(
            "SELECT id FROM stations WHERE project_id = ? ORDER BY id LIMIT 2",
            (project["id"],),
        )
        self.assertGreaterEqual(len(stations), 2)
        session_payload = self.acquire_session(
            project["id"], stations[0]["id"], "mismatch-client"
        )
        session_payload["station_id"] = stations[1]["id"]
        session_payload.update(
            {
                "barcode": "MISMATCH-001",
                "step_id": 1,
                "is_main_barcode": False,
            }
        )
        with self.assertRaises(HTTPError) as mismatch_error:
            self.json_request(
                self.opener(),
                "/api/client/barcode/validate",
                method="POST",
                payload=session_payload,
            )
        self.assertEqual(mismatch_error.exception.code, 400)
        body = json.loads(mismatch_error.exception.read().decode("utf-8"))
        self.assertIn("工位占用信息不匹配", body["error"])

    def test_product_flow_client_apis_are_public_and_dependency_admin_api_is_protected(self):
        project = database.fetch_one("SELECT id, name FROM projects ORDER BY id LIMIT 1")
        station = database.fetch_one(
            "SELECT id, name FROM stations WHERE project_id = ? ORDER BY id LIMIT 1",
            (project["id"],),
        )
        session_payload = self.acquire_session(
            project["id"], station["id"], "product-flow-client"
        )
        status, identity = self.json_request(
            self.opener(),
            "/api/product-flow/resolve-barcode",
            method="POST",
            payload=dict(session_payload, **{
                "project_id": project["id"],
                "barcode": "FLOW-HTTP-001",
                "product_type": "A",
                "create_if_missing": True,
            }),
        )
        self.assertEqual(status, 200)
        self.assertTrue(identity["allowed_production"])
        status, verification = self.json_request(
            self.opener(),
            "/api/product-flow/verify-entry",
            method="POST",
            payload=dict(session_payload, **{
                "product_instance_id": identity["product_instance_id"],
                "station_id": station["id"],
            }),
        )
        self.assertEqual(status, 200)
        self.assertTrue(verification["allowed"])
        with self.assertRaises(HTTPError) as dependency_error:
            self.json_request(
                self.opener(),
                f"/api/stations/{station['id']}/dependencies",
            )
        self.assertEqual(dependency_error.exception.code, 401)

        opener = self.login("admin", "AdminInitial9!")
        status, dependency = self.json_request(
            opener,
            f"/api/stations/{station['id']}/dependencies",
            method="PUT",
            payload={
                "require_previous_station": False,
                "require_barcode_switch": True,
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(dependency["dependency"]["require_barcode_switch"])

    def test_station_config_query_supports_special_characters(self):
        project = services.add_project({"name": "A/B & C"})
        station = services.add_station({"project_id": project["id"], "name": "工位/特殊"})
        services.add_step(
            {
                "station_id": station["id"],
                "name": "主条码",
                "type": "扫码",
                "step_order": 1,
                "is_main_barcode": True,
            }
        )
        admin_opener = self.login("admin", "AdminInitial9!")
        query = urlencode({"project": "A/B & C", "station": "工位/特殊"})
        with admin_opener.open(
            self.base + "/api/station-config?" + query, timeout=3
        ) as response:
            data = json.loads(response.read().decode("utf-8"))
        self.assertEqual(data["product_name"], "A/B & C - 工位/特殊")
        self.assertEqual(data["steps"][0]["name"], "主条码")

        legacy_project = services.add_project({"name": "Legacy"})
        legacy_station = services.add_station({"project_id": legacy_project["id"], "name": "工位/特殊"})
        services.add_step(
            {
                "station_id": legacy_station["id"],
                "name": "旧客户端主条码",
                "type": "扫码",
                "step_order": 1,
                "is_main_barcode": True,
            }
        )
        legacy_path = f"/api/projects/Legacy/stations/{quote('工位/特殊')}/config"
        with admin_opener.open(self.base + legacy_path, timeout=3) as response:
            legacy_data = json.loads(response.read().decode("utf-8"))
        self.assertEqual(legacy_data["product_name"], "Legacy - 工位/特殊")

        encoded_path = (
            f"/api/projects/{quote('A/B & C', safe='')}/stations/"
            f"{quote('工位/特殊', safe='')}/config"
        )
        with admin_opener.open(self.base + encoded_path, timeout=3) as response:
            encoded_data = json.loads(response.read().decode("utf-8"))
        self.assertEqual(encoded_data["project_id"], project["id"])
        self.assertEqual(encoded_data["station_id"], station["id"])

    def test_id_based_client_flow_supports_all_station_name_characters(self):
        names = [
            "中饰板预装-中出风口/磁吸",
            "A/B测试工位",
            "工位#1",
            "左&右工位",
            "工位?测试",
            "工位%测试",
            "工位 空格 测试",
            "工位(测试)",
            r"工位\反斜杠",
            "中文-英文_A1",
        ]
        project = services.add_project({"name": "特殊/项目?# &"})
        stations = []
        for name in names:
            station = services.add_station({"project_id": project["id"], "name": name})
            services.add_step(
                {
                    "station_id": station["id"],
                    "name": "主条码/扫码",
                    "type": "扫码",
                    "step_order": 1,
                    "is_main_barcode": True,
                }
            )
            stations.append(station)

        _, project_data = self.json_request(
            self.opener(), "/api/client/projects"
        )
        listed = next(item for item in project_data["projects"] if item["id"] == project["id"])
        self.assertEqual([item["name"] for item in listed["station_items"]], names)

        for index, station in enumerate(stations):
            barcode = f"SPECIAL-{index:02d}"
            query = urlencode({"project_id": project["id"], "station_id": station["id"]})
            status, config_response = self.json_request(
                self.opener(),
                f"/api/client/station-config?{query}",
            )
            self.assertEqual(status, 200)
            self.assertEqual(config_response["code"], 1)
            self.assertEqual(config_response["data"]["station_name"], names[index])

            session_payload = {
                "project_id": project["id"],
                "station_id": station["id"],
                "client_id": f"special-client-{index}",
                "computer_name": "特殊字符测试电脑",
            }
            _, acquired = self.json_request(
                self.opener(), "/api/station-session/acquire", "POST", session_payload
            )
            self.assertTrue(acquired["ok"])
            session_payload["station_session_id"] = acquired["session_id"]
            _, heartbeat = self.json_request(
                self.opener(), "/api/station-session/heartbeat", "POST", session_payload
            )
            self.assertTrue(heartbeat["ok"])
            self.json_request(
                self.opener(),
                "/api/scan-records",
                "POST",
                dict(session_payload, barcode=barcode, step="主条码/扫码", result="OK"),
            )
            self.json_request(
                self.opener(),
                "/api/step-records",
                "POST",
                dict(
                    session_payload,
                    main_barcode=barcode,
                    step_name="PLC?接收",
                    step_type="PLC接收",
                    step_order=1,
                    result="OK",
                ),
            )
            self.json_request(
                self.opener(),
                "/api/screw-records",
                "POST",
                dict(
                    session_payload,
                    main_barcode=barcode,
                    step_name="螺丝#1",
                    result="OK",
                    is_counted=True,
                ),
            )
            self.json_request(
                self.opener(),
                "/api/station-completions",
                "POST",
                dict(session_payload, barcode=barcode),
            )
            check_query = urlencode(
                {
                    "project_id": project["id"],
                    "previous_station_id": station["id"],
                    "barcode": barcode,
                    "station_id": station["id"],
                    "client_id": session_payload["client_id"],
                    "station_session_id": session_payload[
                        "station_session_id"
                    ],
                }
            )
            _, completion = self.json_request(
                self.opener(), f"/api/station-completions/check?{check_query}"
            )
            self.assertTrue(completion["completed"])
            _, released = self.json_request(
                self.opener(), "/api/station-session/release", "POST", session_payload
            )
            self.assertTrue(released["ok"])

    def test_id_station_config_returns_structured_client_errors(self):
        with self.assertRaises(HTTPError) as missing_error:
            urlopen(self.base + "/api/client/station-config", timeout=3)
        self.assertEqual(missing_error.exception.code, 400)
        missing = json.loads(missing_error.exception.read().decode("utf-8"))
        self.assertEqual(missing["msg"], "缺少 project_id 或 station_id")

        query = urlencode({"project_id": 999999, "station_id": 999999})
        with self.assertRaises(HTTPError) as not_found_error:
            urlopen(self.base + "/api/client/station-config?" + query, timeout=3)
        self.assertEqual(not_found_error.exception.code, 404)
        not_found = json.loads(not_found_error.exception.read().decode("utf-8"))
        self.assertEqual(not_found["msg"], "未找到指定工位配置")

    def test_station_config_export_tolerates_missing_optional_fields(self):
        exported = services.station_config_step({"name": "旧扫码", "type": "扫码"})
        self.assertEqual(exported["required_count"], 0)
        self.assertEqual(exported["barcode_start"], 1)
        self.assertFalse(exported["is_main_barcode"])

    def test_admin_login_user_response_has_no_password_hash(self):
        opener = self.login("admin", "AdminInitial9!")
        status, data = self.json_request(opener, "/api/admin/users")
        self.assertEqual(status, 200)
        self.assertEqual({user["username"] for user in data["users"]}, {"admin", "super_admin"})
        self.assertTrue(all("password_hash" not in user for user in data["users"]))

    def test_admin_can_change_own_password_and_old_password_stops_working(self):
        opener = self.login("admin", "AdminInitial9!")
        status, data = self.json_request(
            opener,
            "/api/auth/change-password",
            method="POST",
            payload={"old_password": "AdminInitial9!", "new_password": "AdminChanged9!"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        with self.assertRaises(HTTPError):
            self.login("admin", "AdminInitial9!")
        self.login("admin", "AdminChanged9!")

    def test_super_admin_cannot_be_changed_or_deleted_through_web(self):
        opener = self.login("super_admin", "SuperInitial9!")
        super_user = auth.get_user_by_username("super_admin")
        with self.assertRaises(HTTPError) as update_error:
            self.json_request(
                opener,
                f"/api/admin/users/{super_user['id']}",
                method="PUT",
                payload={"username": "changed", "is_active": False},
            )
        self.assertEqual(update_error.exception.code, 400)
        with self.assertRaises(HTTPError) as delete_error:
            self.json_request(
                opener,
                f"/api/admin/users/{super_user['id']}",
                method="DELETE",
            )
        self.assertEqual(delete_error.exception.code, 400)
        protected = auth.get_user_by_username("super_admin")
        self.assertEqual(protected["username"], "super_admin")
        self.assertTrue(protected["is_active"])

    def test_failed_login_is_logged(self):
        request = Request(
            self.base + "/login",
            data=urlencode({"username": "admin", "password": "wrong"}).encode("utf-8"),
            method="POST",
        )
        with self.assertRaises(HTTPError) as raised:
            self.opener().open(request, timeout=3)
        self.assertEqual(raised.exception.code, 401)
        logs = auth.list_login_logs()
        self.assertFalse(logs[0]["success"])
        self.assertEqual(logs[0]["username"], "admin")

    def test_five_consecutive_failures_lock_login_for_five_minutes(self):
        for _ in range(5):
            user, _message = auth.authenticate("admin", "wrong", "10.0.0.8", "test")
            self.assertIsNone(user)
        user, message = auth.authenticate("admin", "AdminInitial9!", "10.0.0.8", "test")
        self.assertIsNone(user)
        self.assertIn("5分钟", message)

    def test_super_admin_cannot_change_password_through_web(self):
        opener = self.login("super_admin", "SuperInitial9!")
        with self.assertRaises(HTTPError) as raised:
            self.json_request(
                opener,
                "/api/auth/change-password",
                method="POST",
                payload={"old_password": "SuperInitial9!", "new_password": "SuperChanged9!"},
            )
        self.assertEqual(raised.exception.code, 400)
        self.login("super_admin", "SuperInitial9!")


if __name__ == "__main__":
    unittest.main()
