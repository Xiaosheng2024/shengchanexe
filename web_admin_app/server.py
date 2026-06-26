import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


from web_admin_app.admin_page import HTML
from web_admin_app.database import get_database_type, init_db, load_database_config
from web_admin_app.services import (
    add_project,
    add_production_record,
    add_scan_record,
    add_screw_record,
    add_station,
    add_station_completion,
    add_step_record,
    add_step,
    acquire_station_session,
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
    get_trace,
    list_projects,
    list_projects_full,
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
    vacuum_or_analyze,
)



def json_response(handler, payload, status=200):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
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


def read_json(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    if length == 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


class AdminHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        json_response(self, {})

    def do_GET(self):
        try:
            self.route_get()
        except Exception as exc:
            json_response(self, {"error": str(exc)}, 500)

    def do_POST(self):
        try:
            self.route_post()
        except ValueError as exc:
            json_response(self, {"error": str(exc)}, 400)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, 500)

    def do_PUT(self):
        try:
            self.route_put()
        except ValueError as exc:
            json_response(self, {"error": str(exc)}, 400)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, 500)

    def do_DELETE(self):
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
        elif path == "/api/projects":
            json_response(self, {"projects": list_projects()})
        elif path == "/api/projects/full":
            json_response(self, {"projects": list_projects_full()})
        elif path.startswith("/api/projects/") and path.endswith("/config"):
            json_response(self, get_station_config(path))
        elif path.startswith("/api/stations/") and path.endswith("/steps"):
            station_id = int(path.split("/")[3])
            json_response(self, {"steps": list_steps(station_id)})
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
        else:
            json_response(self, {"error": "not found"}, 404)

    def route_post(self):
        path = urlparse(self.path).path
        payload = read_json(self)
        if path == "/api/projects":
            json_response(self, add_project(payload))
        elif path == "/api/stations":
            json_response(self, add_station(payload))
        elif path == "/api/steps":
            json_response(self, add_step(payload))
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
        else:
            json_response(self, {"error": "not found"}, 404)

    def route_put(self):
        path = urlparse(self.path).path
        payload = read_json(self)
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "projects":
            json_response(self, update_project(int(parts[2]), payload))
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "stations":
            json_response(self, update_station(int(parts[2]), payload))
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "steps":
            json_response(self, update_step(int(parts[2]), payload))
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "scan-records":
            json_response(self, update_scan_record(int(parts[2]), payload))
        else:
            json_response(self, {"error": "not found"}, 404)

    def route_delete(self):
        path = urlparse(self.path).path
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "projects":
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
        else:
            json_response(self, {"error": "not found"}, 404)

    def log_message(self, format, *args):
        return



def run(host="0.0.0.0", port=8000):
    init_db()
    server = ThreadingHTTPServer((host, port), AdminHandler)
    print(f"管理后台已启动：http://127.0.0.1:{port}")
    db_config = load_database_config()
    if get_database_type() == "sqlite":
        print(f"数据库：SQLite {db_config['path']}")
    else:
        print(f"数据库：PostgreSQL {db_config['host']}:{db_config['port']}/{db_config['database']}")
    server.serve_forever()


if __name__ == "__main__":
    run()
