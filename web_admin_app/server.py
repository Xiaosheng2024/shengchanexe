import cgi
import configparser
import json
import logging
import shutil
import tempfile
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


from web_admin_app import auth, product_flow
from web_admin_app.admin_page import HTML
from web_admin_app.database import CONFIG_PATH, get_database_type, init_db, load_database_config
from web_admin_app.login_page import render_login_page
from web_admin_app.services import (
    ClientValidationError,
    add_project,
    add_production_record,
    add_scan_record,
    cancel_barcode_record,
    add_screw_record,
    add_station,
    add_station_completion,
    add_step_record,
    add_step,
    acquire_station_session,
    delete_client_release,
    admin_release_station_session,
    archive_old_records,
    backup_database,
    check_station_completion,
    db_status,
    delete_project,
    delete_scan_record,
    delete_station,
    delete_step,
    delete_old_records,
    heartbeat_station_session,
    maintenance_logs,
    release_station_session,
    get_station_config,
    get_station_config_by_ids,
    get_route_config,
    create_route_template,
    latest_client_release,
    get_trace,
    list_projects,
    list_projects_full,
    list_client_releases,
    list_client_update_logs,
    list_production_records,
    list_scan_records,
    list_screw_records,
    list_station_sessions,
    list_steps,
    list_step_records,
    update_project,
    update_scan_record,
    update_station,
    update_step,
    upsert_client_release,
    report_client_update,
    report_degrade_mode,
    validate_station_session,
    validate_barcode_use,
    download_client_release,
    ensure_client_updates_dir,
    vacuum_or_analyze,
)

MAX_CLIENT_UPDATE_REQUEST_BYTES = 222 * 1024 * 1024

CLIENT_SESSION_ENDPOINTS = {
    "/api/station-completions",
    "/api/scan-records",
    "/api/production-records",
    "/api/step-records",
    "/api/screw-records",
    "/api/product-flow/resolve-barcode",
    "/api/product-flow/verify-entry",
    "/api/product-flow/switch-barcode",
    "/api/product-flow/bind-material",
    "/api/client/barcode/validate",
    "/api/client/barcode/cancel",
    "/api/client/tool/degrade-mode/report",
}

STATION_SESSION_LIFECYCLE_ENDPOINTS = {
    "/api/station-session/acquire",
    "/api/station-session/force-acquire",
    "/api/station-session/heartbeat",
    "/api/station-session/release",
}


def json_response(handler, payload, status=200, extra_headers=None):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    for key, value in (extra_headers or {}).items():
        handler.send_header(key, value)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def html_response(handler):
    data = HTML.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def login_html_response(handler, error="", status=200):
    data = render_login_page(error).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def redirect_response(handler, location, cookie=None):
    handler.send_response(302)
    handler.send_header("Location", location)
    if cookie:
        handler.send_header("Set-Cookie", cookie)
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def read_urlencoded(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    data = handler.rfile.read(length).decode("utf-8") if length else ""
    return {key: values[0] for key, values in parse_qs(data).items()}


def client_ip(handler):
    forwarded = handler.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
    return forwarded or handler.client_address[0]


def session_user(handler):
    cookie = SimpleCookie()
    try:
        cookie.load(handler.headers.get("Cookie", ""))
    except Exception:
        return None
    morsel = cookie.get(auth.SESSION_COOKIE_NAME)
    return auth.parse_session_token(morsel.value) if morsel else None


def is_public_client_api(method, path):
    if method == "GET":
        return (
            path == "/api/client/projects"
            or path == "/api/client/station-config"
            or path == "/api/station-completions/check"
            or path == "/api/client-update/latest"
            or path.startswith("/api/client-update/download/")
        )
    if method == "POST":
        if (
            path.startswith("/api/client/")
            or path.startswith("/api/production/")
            or path in CLIENT_SESSION_ENDPOINTS
            or path in STATION_SESSION_LIFECYCLE_ENDPOINTS
        ):
            return True
        return path in {
            "/api/client-update/report",
        }
    return False


def requires_station_session(method, path):
    if method == "GET":
        return path == "/api/station-completions/check"
    if method != "POST":
        return False
    return (
        path in CLIENT_SESSION_ENDPOINTS
        or path.startswith("/api/production/")
        or (
            path.startswith("/api/client/")
            and path != "/api/client-update/report"
        )
    )


def require_api_auth(handler, method, path):
    if not path.startswith("/api/") or is_public_client_api(method, path):
        handler.current_user = session_user(handler)
        return True
    handler.current_user = session_user(handler)
    if handler.current_user:
        return True
    json_response(handler, {"code": 401, "msg": "未登录或登录已过期"}, 401)
    return False


def read_json(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    if length == 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def read_form(handler):
    content_type = handler.headers.get("Content-Type", "")
    environ = {
        "REQUEST_METHOD": "POST",
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": handler.headers.get("Content-Length", "0"),
    }
    form = cgi.FieldStorage(fp=handler.rfile, headers=handler.headers, environ=environ, keep_blank_values=True)
    payload = {}
    files = {}
    if not form.list:
        return payload, files
    for item in form.list:
        if item.filename:
            upload = tempfile.SpooledTemporaryFile(
                max_size=8 * 1024 * 1024,
                mode="w+b",
            )
            shutil.copyfileobj(item.file, upload)
            upload.seek(0)
            files[item.name] = upload
            payload[f"{item.name}_filename"] = item.filename
        else:
            payload[item.name] = item.value
    return payload, files


class AdminHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        json_response(self, {})

    def do_HEAD(self):
        path = urlparse(self.path).path
        if path == "/login":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            return
        if path != "/":
            self.send_response(404)
            self.end_headers()
            return
        if not session_user(self):
            redirect_response(self, "/login")
            return
        data = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/login":
            if session_user(self):
                redirect_response(self, "/")
            else:
                login_html_response(self)
            return
        if path == "/logout":
            user = session_user(self)
            if user:
                auth.log_auth_event(
                    user["username"],
                    user["role"],
                    client_ip(self),
                    self.headers.get("User-Agent", ""),
                    True,
                    "退出登录",
                )
            redirect_response(self, "/login", auth.expired_session_cookie())
            return
        if path == "/" and not session_user(self):
            redirect_response(self, "/login")
            return
        if not require_api_auth(self, "GET", path):
            return
        try:
            if requires_station_session("GET", path):
                query = parse_qs(urlparse(self.path).query)
                validate_station_session(
                    {key: values[0] for key, values in query.items()}
                )
            self.route_get()
        except Exception as exc:
            logging.exception("GET %s 处理失败", self.path)
            json_response(self, {"error": str(exc)}, 500)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/login":
            payload = read_urlencoded(self)
            user, error = auth.authenticate(
                payload.get("username", ""),
                payload.get("password", ""),
                client_ip(self),
                self.headers.get("User-Agent", ""),
            )
            if not user:
                login_html_response(self, error, 401)
                return
            redirect_response(self, "/", auth.session_cookie(auth.create_session_token(user)))
            return
        if not require_api_auth(self, "POST", path):
            return
        if path == "/api/client-releases":
            if (self.current_user or {}).get("role") not in {
                "admin",
                "super_admin",
            }:
                json_response(
                    self,
                    {"error": "当前账号无权上传客户端更新包"},
                    403,
                )
                return
            try:
                content_length = int(
                    self.headers.get("Content-Length", "0") or 0
                )
            except ValueError:
                content_length = 0
            if content_length > MAX_CLIENT_UPDATE_REQUEST_BYTES:
                json_response(
                    self,
                    {"error": "文件过大，请检查上传限制"},
                    413,
                )
                return
        self._request_uploads = []
        try:
            self.route_post()
        except ClientValidationError as exc:
            json_response(
                self,
                {"error": str(exc), **exc.details},
                400,
            )
        except ValueError as exc:
            json_response(self, {"error": str(exc)}, 400)
        except Exception as exc:
            logging.exception("POST %s 处理失败", self.path)
            json_response(self, {"error": str(exc)}, 500)
        finally:
            for upload in self._request_uploads:
                try:
                    upload.close()
                except Exception:
                    pass
            self._request_uploads = []

    def do_PUT(self):
        path = urlparse(self.path).path
        if not require_api_auth(self, "PUT", path):
            return
        try:
            self.route_put()
        except ValueError as exc:
            json_response(self, {"error": str(exc)}, 400)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, 500)

    def do_DELETE(self):
        path = urlparse(self.path).path
        if not require_api_auth(self, "DELETE", path):
            return
        try:
            self.route_delete()
        except ValueError as exc:
            json_response(self, {"error": str(exc)}, 400)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, 500)

    def route_get(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/":
            html_response(self)
        elif path == "/api/auth/me":
            json_response(self, {"user": self.current_user})
        elif path == "/api/admin/users":
            json_response(self, {"users": auth.list_users()})
        elif path == "/api/admin/login-logs":
            json_response(self, {"records": auth.list_login_logs(query.get("limit", ["100"])[0])})
        elif path == "/api/projects":
            json_response(self, {"projects": list_projects()})
        elif path == "/api/client/projects":
            json_response(self, {"projects": list_projects()})
        elif path == "/api/projects/full":
            json_response(self, {"projects": list_projects_full()})
        elif path.startswith("/api/projects/") and path.endswith("/route-config"):
            project_id = int(path.strip("/").split("/")[2])
            json_response(self, get_route_config(project_id))
        elif path.startswith("/api/projects/") and path.endswith("/config"):
            json_response(self, get_station_config(path))
        elif path == "/api/station-config":
            project_name = query.get("project", [""])[0]
            station_name = query.get("station", [""])[0]
            if not project_name or not station_name:
                raise ValueError("项目和工位不能为空")
            json_response(self, get_station_config(project_name, station_name))
        elif path == "/api/client/station-config":
            project_id = query.get("project_id", [""])[0]
            station_id = query.get("station_id", [""])[0]
            if not project_id or not station_id:
                json_response(
                    self,
                    {"code": -1, "msg": "缺少 project_id 或 station_id", "data": None},
                    400,
                )
                return
            try:
                data = get_station_config_by_ids(int(project_id), int(station_id))
            except (TypeError, ValueError):
                json_response(
                    self,
                    {"code": -1, "msg": "project_id 或 station_id 格式不正确", "data": None},
                    400,
                )
                return
            except Exception:
                logging.exception("按 ID 下载工位配置失败")
                json_response(
                    self,
                    {"code": -1, "msg": "下载工位配置失败，请查看服务端日志", "data": None},
                    500,
                )
                return
            if data is None:
                json_response(
                    self,
                    {"code": -1, "msg": "未找到指定工位配置", "data": None},
                    404,
                )
                return
            json_response(self, {"code": 1, "msg": "ok", "data": data})
        elif path.startswith("/api/stations/") and path.endswith("/steps"):
            station_id = int(path.split("/")[3])
            json_response(self, {"steps": list_steps(station_id)})
        elif path.startswith("/api/stations/") and path.endswith("/dependencies"):
            station_id = int(path.split("/")[3])
            json_response(
                self,
                {"dependency": product_flow.get_station_dependency(station_id)},
            )
        elif path == "/api/product-flow/trace":
            json_response(
                self,
                product_flow.trace_by_barcode(query.get("barcode", [""])[0]),
            )
        elif path == "/api/station-completions/check":
            json_response(self, check_station_completion(query))
        elif path == "/api/station-sessions":
            json_response(self, list_station_sessions(query))
        elif path == "/api/scan-records":
            json_response(self, {"records": list_scan_records(query)})
        elif path == "/api/production-records":
            json_response(self, list_production_records(query))
        elif path == "/api/step-records":
            json_response(self, list_step_records(query))
        elif path == "/api/screw-records":
            json_response(self, list_screw_records(query))
        elif path == "/api/trace":
            json_response(self, get_trace(query))
        elif path == "/api/admin/db/status":
            json_response(self, db_status())
        elif path == "/api/admin/db/maintenance-logs":
            json_response(self, maintenance_logs(query))
        elif path == "/api/client-releases":
            json_response(self, {"releases": list_client_releases()})
        elif path == "/api/client-update/logs":
            json_response(self, list_client_update_logs(query))
        elif path == "/api/client-update/latest":
            json_response(self, latest_client_release(query))
        elif path.startswith("/api/client-update/download/"):
            parts = path.strip("/").split("/")
            if len(parts) != 5:
                json_response(self, {"error": "not found"}, 404)
                return
            version, kind = parts[3], parts[4]
            file_path, default_name = download_client_release(version, kind)
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{default_name}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            json_response(self, {"error": "not found"}, 404)

    def route_post(self):
        path = urlparse(self.path).path
        content_type = self.headers.get("Content-Type", "")
        is_multipart = content_type.startswith("multipart/form-data")
        if is_multipart:
            payload, files = read_form(self)
            self._request_uploads.extend((files or {}).values())
        else:
            payload, files = read_json(self), None
        if path == "/api/client-releases":
            payload["_uploaded_by"] = (
                (self.current_user or {}).get("username") or ""
            )
        if requires_station_session("POST", path):
            validate_station_session(payload)
        if path == "/api/auth/change-password":
            try:
                auth.change_own_password(
                    self.current_user["id"],
                    payload.get("old_password", ""),
                    payload.get("new_password", ""),
                )
            except ValueError as exc:
                auth.log_auth_event(
                    self.current_user["username"],
                    self.current_user["role"],
                    client_ip(self),
                    self.headers.get("User-Agent", ""),
                    False,
                    f"修改密码失败：{exc}",
                )
                raise
            auth.log_auth_event(
                self.current_user["username"],
                self.current_user["role"],
                client_ip(self),
                self.headers.get("User-Agent", ""),
                True,
                "修改密码成功",
            )
            json_response(
                self,
                {"ok": True, "message": "密码修改成功，请重新登录"},
                extra_headers={"Set-Cookie": auth.expired_session_cookie()},
            )
        elif path == "/api/admin/users":
            json_response(self, auth.create_admin_user(payload))
        elif path == "/api/projects":
            json_response(self, add_project(payload))
        elif path == "/api/stations":
            json_response(self, add_station(payload))
        elif path == "/api/steps":
            json_response(self, add_step(payload))
        elif path.startswith("/api/projects/") and path.endswith("/route-template"):
            project_id = int(path.strip("/").split("/")[2])
            json_response(
                self,
                create_route_template(project_id, payload.get("template")),
            )
        elif path == "/api/station-completions":
            json_response(self, add_station_completion(payload))
        elif path == "/api/scan-records":
            json_response(self, add_scan_record(payload))
        elif path == "/api/production-records":
            json_response(self, add_production_record(payload))
        elif path == "/api/step-records":
            json_response(self, add_step_record(payload))
        elif path == "/api/screw-records":
            json_response(self, add_screw_record(payload))
        elif path == "/api/product-flow/resolve-barcode":
            json_response(self, product_flow.resolve_barcode(payload))
        elif path == "/api/product-flow/verify-entry":
            json_response(self, product_flow.verify_station_entry(payload))
        elif path == "/api/product-flow/switch-barcode":
            json_response(self, product_flow.switch_main_barcode(payload))
        elif path == "/api/product-flow/bind-material":
            json_response(self, product_flow.bind_child_material(payload))
        elif path == "/api/client/barcode/validate":
            json_response(self, validate_barcode_use(payload))
        elif path == "/api/client/barcode/cancel":
            json_response(self, cancel_barcode_record(payload))
        elif path == "/api/client/tool/degrade-mode/report":
            json_response(self, report_degrade_mode(payload))
        elif path == "/api/station-session/acquire":
            json_response(self, acquire_station_session(payload))
        elif path == "/api/station-session/force-acquire":
            json_response(self, acquire_station_session(payload, force=True))
        elif path == "/api/station-session/heartbeat":
            json_response(self, heartbeat_station_session(payload))
        elif path == "/api/station-session/release":
            json_response(self, release_station_session(payload))
        elif path == "/api/station-session/admin-release":
            json_response(self, admin_release_station_session(payload))
        elif path == "/api/admin/db/backup":
            json_response(self, backup_database())
        elif path == "/api/admin/db/archive":
            json_response(self, archive_old_records(payload))
        elif path == "/api/admin/db/delete-old-records":
            json_response(self, delete_old_records(payload))
        elif path == "/api/admin/db/vacuum-or-analyze":
            json_response(self, vacuum_or_analyze())
        elif path == "/api/client-update/report":
            json_response(self, report_client_update(payload))
        elif path == "/api/client-releases":
            json_response(self, upsert_client_release(payload, files=files))
        else:
            json_response(self, {"error": "not found"}, 404)

    def route_put(self):
        path = urlparse(self.path).path
        payload = read_json(self)
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[:3] == ["api", "admin", "users"]:
            user_id = int(parts[3])
            try:
                json_response(self, auth.update_admin_user(user_id, payload))
            except ValueError as exc:
                if str(exc) == auth.PROTECTED_MESSAGE:
                    auth.log_auth_event(
                        self.current_user["username"],
                        self.current_user["role"],
                        client_ip(self),
                        self.headers.get("User-Agent", ""),
                        False,
                        "尝试修改超级管理员被拒绝",
                    )
                raise
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "projects":
            json_response(self, update_project(int(parts[2]), payload))
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "stations":
            json_response(self, update_station(int(parts[2]), payload))
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "steps":
            json_response(self, update_step(int(parts[2]), payload))
        elif (
            len(parts) == 4
            and parts[0] == "api"
            and parts[1] == "stations"
            and parts[3] == "dependencies"
        ):
            json_response(
                self,
                {
                    "dependency": product_flow.save_station_dependency(
                        int(parts[2]), payload
                    )
                },
            )
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "scan-records":
            json_response(self, update_scan_record(int(parts[2]), payload))
        else:
            json_response(self, {"error": "not found"}, 404)

    def route_delete(self):
        path = urlparse(self.path).path
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[:3] == ["api", "admin", "users"]:
            user_id = int(parts[3])
            try:
                auth.delete_admin_user(user_id, self.current_user["id"])
            except ValueError as exc:
                if str(exc) == auth.PROTECTED_MESSAGE:
                    auth.log_auth_event(
                        self.current_user["username"],
                        self.current_user["role"],
                        client_ip(self),
                        self.headers.get("User-Agent", ""),
                        False,
                        "尝试删除超级管理员被拒绝",
                    )
                raise
            json_response(self, {"ok": True})
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "projects":
            delete_project(int(parts[2]))
            json_response(self, {"ok": True})
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "stations":
            delete_station(int(parts[2]))
            json_response(self, {"ok": True})
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "steps":
            delete_step(int(parts[2]))
            json_response(self, {"ok": True})
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "scan-records":
            delete_scan_record(int(parts[2]))
            json_response(self, {"ok": True})
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "material-bindings":
            json_response(
                self,
                product_flow.unbind_material(int(parts[2]), read_json(self)),
            )
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "client-releases":
            delete_client_release(parts[2])
            json_response(self, {"ok": True})
        else:
            json_response(self, {"error": "not found"}, 404)

    def log_message(self, format, *args):
        return



def load_server_config(config_path=CONFIG_PATH):
    config = configparser.ConfigParser()
    if config_path.exists():
        config.read(config_path, encoding="utf-8")
    host = config.get("SERVER", "host", fallback="0.0.0.0").strip() or "0.0.0.0"
    port = config.getint("SERVER", "port", fallback=8000)
    if not 1 <= port <= 65535:
        raise ValueError("SERVER.port 必须在 1-65535 之间")
    return {"host": host, "port": port}


def run(host=None, port=None):
    server_config = load_server_config()
    host = server_config["host"] if host is None else host
    port = server_config["port"] if port is None else port
    init_db()
    ensure_client_updates_dir()
    auth.ensure_session_secret()
    auth.validate_builtin_accounts()
    server = ThreadingHTTPServer((host, port), AdminHandler)
    print(f"管理后台监听地址：http://{host}:{port}")
    db_config = load_database_config()
    if get_database_type() == "sqlite":
        print(f"数据库：SQLite {db_config['path']}")
    else:
        print(f"数据库：PostgreSQL {db_config['host']}:{db_config['port']}/{db_config['database']}")
    server.serve_forever()


if __name__ == "__main__":
    run()
