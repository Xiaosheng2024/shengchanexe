import csv
import json
import shutil
import socket
import subprocess
import hashlib
import os
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote

from web_admin_app import database
from web_admin_app.database import get_conn, now_text, row_to_dict
from web_admin_app import product_flow


MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 100
ROOT_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = Path("/opt/mes/backup") if Path("/opt/mes").exists() else ROOT_DIR / "backup"
ARCHIVE_DIR = Path("/opt/mes/archive") if Path("/opt/mes").exists() else ROOT_DIR / "archive"
RELEASES_DIR = Path("/opt/mes/releases") if Path("/opt/mes").exists() else ROOT_DIR / "releases"
UPLOADS_DIR = Path("/opt/mes/uploads") if Path("/opt/mes").exists() else ROOT_DIR / "uploads"
MAINTENANCE_TABLES = ["scan_records", "station_work_records", "step_work_records", "screw_action_records", "station_session_logs"]


def table_time_column(table):
    return "completed_at" if table == "station_completions" else "created_at"
SCAN_TYPE = "扫码"
SCREW_TYPE = "螺丝"
PLC_TYPE = "PLC接收"
BARCODE_SWITCH_TYPE = "主条码切换"
MATERIAL_BIND_TYPE = "子物料绑定"
STEP_TYPES = (
    SCAN_TYPE,
    SCREW_TYPE,
    PLC_TYPE,
    BARCODE_SWITCH_TYPE,
    MATERIAL_BIND_TYPE,
)
ADMIN_PASSWORD = "0000"


PLC_DEFAULTS = {
    "plc_ip": "10.162.86.65",
    "plc_rack": 0,
    "plc_slot": 1,
    "plc_barcode_db": 201,
    "plc_barcode_offset": 800,
    "plc_barcode_length": 40,
    "plc_barcode1_db": 201,
    "plc_barcode1_offset": 800,
    "plc_barcode1_length": 40,
    "plc_barcode2_db": 201,
    "plc_barcode2_offset": 840,
    "plc_barcode2_length": 40,
    "plc_parts_ok_db": 221,
    "plc_parts_ok_offset": 358,
    "plc_parts_ok_type": "int",
    "plc_trigger_mode": "barcode_changed_then_parts_ok_increment",
    "plc_use_barcode_index": 1,
    "plc_barcode_encoding": "ascii",
    "plc_barcode_strip_null": 1,
    "plc_barcode_strip_space": 1,
    "plc_timeout_seconds": 3,
    "plc_poll_interval_ms": 500,
    "plc_barcode_wait_ok_timeout_seconds": 30,
}
STATION_SESSION_TIMEOUT_SECONDS = 120


def pagination(query):
    page = max(int(query.get("page", ["1"])[0] or 1), 1)
    page_size = min(max(int(query.get("page_size", [str(DEFAULT_PAGE_SIZE)])[0] or DEFAULT_PAGE_SIZE), 1), MAX_PAGE_SIZE)
    return page, page_size, (page - 1) * page_size


def client_label(payload):
    return payload.get("client_id") or payload.get("device_id") or f"{payload.get('computer_name') or payload.get('device_name') or socket.gethostname()}-{payload.get('ip_address', '')}"


def normalize_session_payload(payload):
    payload = dict(payload)
    if not payload.get("client_id") and payload.get("device_id"):
        payload["client_id"] = payload.get("device_id")
    if not payload.get("computer_name") and payload.get("device_name"):
        payload["computer_name"] = payload.get("device_name")
    payload["client_id"] = client_label(payload)
    return payload


def resolve_project_station_ids(conn, payload):
    try:
        project_id = int(payload.get("project_id", 0))
        station_id = int(payload.get("station_id", 0))
        if project_id and station_id:
            return project_id, station_id
    except (TypeError, ValueError):
        pass
    project_name = payload.get("project", "") or payload.get("project_id", "")
    station_name = payload.get("station", "") or payload.get("station_id", "")
    row = find_project_station(conn, project_name, station_name)
    if not row:
        raise ValueError("项目或工位不存在")
    return row["project_id"], row["station_id"]


def record_project_station_ids(conn, payload):
    if payload.get("project") or payload.get("station"):
        return resolve_project_station_ids(conn, payload)
    return int(payload.get("project_id", 0)), int(payload.get("station_id", 0))


def log_station_session(conn, project_id, station_id, payload, action, message):
    conn.execute(
        """
        INSERT INTO station_session_logs
        (project_id, station_id, client_id, computer_name, ip_address, action, message, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            station_id,
            payload.get("client_id", ""),
            payload.get("computer_name", ""),
            payload.get("ip_address", ""),
            action,
            message,
            now_text(),
        ),
    )


def parse_time(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def release_stale_station_sessions(conn):
    threshold = datetime.now() - timedelta(seconds=STATION_SESSION_TIMEOUT_SECONDS)
    rows = conn.execute("SELECT * FROM station_sessions WHERE status = 'online'").fetchall()
    for row in rows:
        last_heartbeat = parse_time(row["last_heartbeat_at"])
        if last_heartbeat and last_heartbeat < threshold:
            conn.execute("UPDATE station_sessions SET status = 'offline', note = ? WHERE id = ?", ("心跳超时自动释放", row["id"]))
            log_station_session(conn, row["project_id"], row["station_id"], row_to_dict(row), "timeout-release", "心跳超过120秒，自动释放工位")


def acquire_station_session(payload, force=False):
    payload = normalize_session_payload(payload)
    with get_conn() as conn:
        project_id, station_id = resolve_project_station_ids(conn, payload)
        release_stale_station_sessions(conn)
        existing = conn.execute(
            """
            SELECT * FROM station_sessions
            WHERE project_id = ? AND station_id = ? AND status = 'online'
            ORDER BY last_heartbeat_at DESC LIMIT 1
            """,
            (project_id, station_id),
        ).fetchone()
        if existing and existing["client_id"] != payload["client_id"] and not force:
            return {"ok": False, "conflict": row_to_dict(existing), "message": "该工位已被其他电脑占用"}
        if force and payload.get("admin_password") != ADMIN_PASSWORD:
            raise ValueError("管理员密码错误")
        if existing and existing["client_id"] != payload["client_id"]:
            conn.execute("UPDATE station_sessions SET status = 'offline', note = ? WHERE id = ?", ("管理员强制接管", existing["id"]))
            log_station_session(conn, project_id, station_id, payload, "force-acquire", "管理员强制接管工位")
        conn.execute(
            """
            INSERT INTO station_sessions
            (project_id, station_id, client_id, computer_name, ip_address, status, acquired_at, last_heartbeat_at, note)
            VALUES (?, ?, ?, ?, ?, 'online', ?, ?, ?)
            ON CONFLICT DO NOTHING
            """,
            (
                project_id,
                station_id,
                payload["client_id"],
                payload.get("computer_name", ""),
                payload.get("ip_address", ""),
                now_text(),
                now_text(),
                "占用成功",
            ),
        )
        conn.execute(
            """
            UPDATE station_sessions
            SET client_id = ?, computer_name = ?, ip_address = ?, status = 'online', last_heartbeat_at = ?, note = ?
            WHERE project_id = ? AND station_id = ? AND status = 'online'
            """,
            (
                payload["client_id"],
                payload.get("computer_name", ""),
                payload.get("ip_address", ""),
                now_text(),
                "心跳更新",
                project_id,
                station_id,
            ),
        )
        session = conn.execute(
            """
            SELECT id FROM station_sessions
            WHERE project_id = ? AND station_id = ? AND client_id = ? AND status = 'online'
            ORDER BY last_heartbeat_at DESC LIMIT 1
            """,
            (project_id, station_id, payload["client_id"]),
        ).fetchone()
        log_station_session(conn, project_id, station_id, payload, "acquire", "工位占用成功")
    return {"ok": True, "client_id": payload["client_id"], "session_id": session["id"] if session else None}


def heartbeat_station_session(payload):
    payload = normalize_session_payload(payload)
    client_id = payload["client_id"]
    with get_conn() as conn:
        project_id, station_id = resolve_project_station_ids(conn, payload)
        release_stale_station_sessions(conn)
        row = conn.execute(
            "SELECT * FROM station_sessions WHERE project_id = ? AND station_id = ? AND status = 'online'",
            (project_id, station_id),
        ).fetchone()
        if not row or row["client_id"] != client_id:
            return {"ok": False, "message": "工位占用已失效或被接管", "session": row_to_dict(row)}
        conn.execute("UPDATE station_sessions SET last_heartbeat_at = ? WHERE id = ?", (now_text(), row["id"]))
    return {"ok": True}


def release_station_session(payload):
    payload = normalize_session_payload(payload)
    client_id = payload["client_id"]
    with get_conn() as conn:
        project_id, station_id = resolve_project_station_ids(conn, payload)
        conn.execute(
            "UPDATE station_sessions SET status = 'offline', note = ? WHERE project_id = ? AND station_id = ? AND client_id = ? AND status = 'online'",
            ("客户端释放", project_id, station_id, client_id),
        )
        log_station_session(conn, project_id, station_id, dict(payload, client_id=client_id), "release", "客户端释放工位")
    return {"ok": True}


def admin_release_station_session(payload):
    if payload.get("admin_password") != ADMIN_PASSWORD:
        raise ValueError("管理员密码错误")
    session_id = int(payload.get("session_id", 0))
    if not session_id:
        raise ValueError("session_id不能为空")
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM station_sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            raise ValueError("工位占用记录不存在")
        conn.execute("UPDATE station_sessions SET status = 'offline', note = ? WHERE id = ?", ("管理员后台释放", session_id))
        log_station_session(conn, row["project_id"], row["station_id"], row_to_dict(row), "admin-release", "管理员后台释放工位")
    return {"ok": True}


def list_station_sessions(query=None):
    query = query or {}
    status = query.get("status", ["online"])[0] if hasattr(query, "get") else "online"
    with get_conn() as conn:
        where = ""
        params = []
        if status:
            where = "WHERE station_sessions.status = ?"
            params.append(status)
        rows = conn.execute(
            f"""
            SELECT station_sessions.id, projects.name AS project_name, stations.name AS station_name,
                   station_sessions.client_id, station_sessions.computer_name, station_sessions.ip_address,
                   station_sessions.status, station_sessions.acquired_at, station_sessions.last_heartbeat_at,
                   station_sessions.note
            FROM station_sessions
            JOIN projects ON projects.id = station_sessions.project_id
            JOIN stations ON stations.id = station_sessions.station_id
            {where}
            ORDER BY station_sessions.last_heartbeat_at DESC
            """,
            params,
        ).fetchall()
    sessions = []
    threshold = datetime.now() - timedelta(seconds=STATION_SESSION_TIMEOUT_SECONDS)
    for row in rows:
        if status == "online":
            last_heartbeat = parse_time(row["last_heartbeat_at"])
            if last_heartbeat and last_heartbeat < threshold:
                continue
        sessions.append(row_to_dict(row))
    return {"sessions": sessions}


def list_projects():
    projects = []
    with get_conn() as conn:
        for project in conn.execute("SELECT * FROM projects ORDER BY id"):
            stations = conn.execute(
                "SELECT id, name FROM stations WHERE project_id = ? ORDER BY id",
                (project["id"],),
            ).fetchall()
            projects.append(
                {
                    "id": project["id"],
                    "name": project["name"],
                    "material_code": project["material_code"] or "",
                    "product_type": project["product_type"] or project["name"],
                    "stations": [row["name"] for row in stations],
                    "station_items": [
                        {"id": row["id"], "name": row["name"]}
                        for row in stations
                    ],
                }
            )
    return projects


def list_projects_full():
    with get_conn() as conn:
        projects = [row_to_dict(row) for row in conn.execute("SELECT * FROM projects ORDER BY id")]
        for project in projects:
            stations = conn.execute(
                "SELECT * FROM stations WHERE project_id = ? ORDER BY id",
                (project["id"],),
            ).fetchall()
            project["stations"] = [row_to_dict(row) for row in stations]
            for station in project["stations"]:
                station["steps"] = list_steps(station["id"])
    return projects


def add_project(payload):
    name = payload.get("name", "").strip()
    if not name:
        raise ValueError("项目名称不能为空")
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO projects
            (name, material_code, product_type, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                name,
                payload.get("material_code", "").strip(),
                payload.get("product_type", "").strip() or name,
                now_text(),
            ),
        )
        return {"id": cursor.lastrowid, "name": name}


def update_project(project_id, payload):
    name = payload.get("name", "").strip()
    if not name:
        raise ValueError("项目名称不能为空")
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE projects
            SET name = ?, material_code = ?, product_type = ?
            WHERE id = ?
            """,
            (
                name,
                payload.get("material_code", "").strip(),
                payload.get("product_type", "").strip() or name,
                project_id,
            ),
        )
    return {"ok": True}


def add_station(payload):
    project_id = int(payload.get("project_id", 0))
    name = payload.get("name", "").strip()
    if not project_id or not name:
        raise ValueError("项目和工位名称不能为空")
    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO stations (project_id, name, created_at) VALUES (?, ?, ?)",
            (project_id, name, now_text()),
        )
        return {"id": cursor.lastrowid, "name": name}


def update_station(station_id, payload):
    project_id = int(payload.get("project_id", 0))
    name = payload.get("name", "").strip()
    if not project_id or not name:
        raise ValueError("项目和工位名称不能为空")
    with get_conn() as conn:
        conn.execute(
            "UPDATE stations SET project_id = ?, name = ? WHERE id = ?",
            (project_id, name, station_id),
        )
    return {"ok": True}


def delete_project(project_id):
    with get_conn() as conn:
        instance_rows = conn.execute(
            "SELECT id FROM product_instances WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        instance_ids = [row["id"] for row in instance_rows]
        for instance_id in instance_ids:
            conn.execute(
                """
                DELETE FROM material_bindings
                WHERE parent_product_instance_id = ? OR child_product_instance_id = ?
                """,
                (instance_id, instance_id),
            )
            conn.execute(
                "DELETE FROM barcode_switch_records WHERE product_instance_id = ?",
                (instance_id,),
            )
            conn.execute(
                "DELETE FROM barcode_aliases WHERE product_instance_id = ?",
                (instance_id,),
            )
        conn.execute("DELETE FROM product_instances WHERE project_id = ?", (project_id,))
        station_rows = conn.execute("SELECT id FROM stations WHERE project_id = ?", (project_id,)).fetchall()
        station_ids = [row["id"] for row in station_rows]
        for station_id in station_ids:
            delete_station_with_conn(conn, station_id)
        conn.execute("DELETE FROM scan_records WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM station_completions WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM screw_action_records WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM step_work_records WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM station_work_records WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM station_session_logs WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM station_sessions WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))


def delete_station(station_id):
    with get_conn() as conn:
        delete_station_with_conn(conn, station_id)


def delete_station_with_conn(conn, station_id):
    conn.execute("DELETE FROM station_dependencies WHERE station_id = ?", (station_id,))
    conn.execute("DELETE FROM barcode_switch_records WHERE station_id = ?", (station_id,))
    conn.execute("DELETE FROM material_bindings WHERE station_id = ?", (station_id,))
    conn.execute("DELETE FROM steps WHERE station_id = ?", (station_id,))
    conn.execute("DELETE FROM scan_records WHERE station_id = ?", (station_id,))
    conn.execute("DELETE FROM station_completions WHERE station_id = ?", (station_id,))
    conn.execute("DELETE FROM screw_action_records WHERE station_id = ?", (station_id,))
    conn.execute("DELETE FROM step_work_records WHERE station_id = ?", (station_id,))
    conn.execute("DELETE FROM station_work_records WHERE station_id = ?", (station_id,))
    conn.execute("DELETE FROM station_session_logs WHERE station_id = ?", (station_id,))
    conn.execute("DELETE FROM station_sessions WHERE station_id = ?", (station_id,))
    conn.execute("DELETE FROM stations WHERE id = ?", (station_id,))


def delete_step(step_id):
    with get_conn() as conn:
        row = conn.execute("SELECT station_id FROM steps WHERE id = ?", (step_id,)).fetchone()
        conn.execute("DELETE FROM steps WHERE id = ?", (step_id,))
        if row:
            validate_station_main_barcode(conn, row["station_id"])


def add_step(payload):
    station_id = int(payload.get("station_id", 0))
    name = payload.get("name", "").strip()
    step_type = payload.get("type", "扫码")
    is_main_barcode = normalize_main_barcode(payload, step_type)
    if not station_id or not name:
        raise ValueError("工位和工序名称不能为空")
    if step_type not in STEP_TYPES:
        raise ValueError("功能只能是扫码、螺丝、PLC接收、主条码切换或子物料绑定")
    with get_conn() as conn:
        validate_flow_step_payload(conn, payload, step_type)
        if is_main_barcode:
            clear_station_main_barcode(conn, station_id)
        plc_values = plc_payload_values(payload)
        cursor = conn.execute(
            """
            INSERT INTO steps
            (station_id, step_order, name, type, required_count, barcode_start, barcode_end, expected_content, is_main_barcode,
             plc_ip, plc_rack, plc_slot, plc_barcode_db, plc_barcode_offset, plc_barcode_length,
             plc_barcode1_db, plc_barcode1_offset, plc_barcode1_length,
             plc_barcode2_db, plc_barcode2_offset, plc_barcode2_length, plc_parts_ok_db, plc_parts_ok_offset,
             plc_parts_ok_type, plc_trigger_mode, plc_use_barcode_index, plc_barcode_encoding,
             plc_barcode_strip_null, plc_barcode_strip_space, plc_timeout_seconds, plc_poll_interval_ms,
             plc_barcode_wait_ok_timeout_seconds, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                station_id,
                int(payload.get("step_order", 1)),
                name,
                step_type,
                int(payload.get("required_count", 0)),
                int(payload.get("barcode_start", 1)),
                int(payload.get("barcode_end", 7)),
                payload.get("expected_content", ""),
                1 if is_main_barcode else 0,
                *plc_values,
                now_text(),
            ),
        )
        update_step_flow_config(conn, cursor.lastrowid, payload)
        validate_station_main_barcode(conn, station_id)
        return {"id": cursor.lastrowid}


def update_step(step_id, payload):
    name = payload.get("name", "").strip()
    step_type = payload.get("type", "扫码")
    station_id = int(payload.get("station_id", 0))
    is_main_barcode = normalize_main_barcode(payload, step_type)
    if not station_id or not name:
        raise ValueError("工位和工序名称不能为空")
    if step_type not in STEP_TYPES:
        raise ValueError("功能只能是扫码、螺丝、PLC接收、主条码切换或子物料绑定")
    with get_conn() as conn:
        validate_flow_step_payload(conn, payload, step_type)
        old_row = conn.execute("SELECT station_id FROM steps WHERE id = ?", (step_id,)).fetchone()
        if is_main_barcode:
            clear_station_main_barcode(conn, station_id)
        plc_values = plc_payload_values(payload)
        conn.execute(
            """
            UPDATE steps
            SET station_id = ?, step_order = ?, name = ?, type = ?, required_count = ?,
                barcode_start = ?, barcode_end = ?, expected_content = ?, is_main_barcode = ?,
                plc_ip = ?, plc_rack = ?, plc_slot = ?, plc_barcode_db = ?, plc_barcode_offset = ?,
                plc_barcode_length = ?, plc_barcode1_db = ?, plc_barcode1_offset = ?,
                plc_barcode1_length = ?, plc_barcode2_db = ?, plc_barcode2_offset = ?, plc_barcode2_length = ?,
                plc_parts_ok_db = ?, plc_parts_ok_offset = ?, plc_parts_ok_type = ?, plc_trigger_mode = ?,
                plc_use_barcode_index = ?, plc_barcode_encoding = ?, plc_barcode_strip_null = ?,
                plc_barcode_strip_space = ?, plc_timeout_seconds = ?, plc_poll_interval_ms = ?,
                plc_barcode_wait_ok_timeout_seconds = ?
            WHERE id = ?
            """,
            (
                station_id,
                int(payload.get("step_order", 1)),
                name,
                step_type,
                int(payload.get("required_count", 0)),
                int(payload.get("barcode_start", 1)),
                int(payload.get("barcode_end", 7)),
                payload.get("expected_content", ""),
                1 if is_main_barcode else 0,
                *plc_values,
                step_id,
            ),
        )
        update_step_flow_config(conn, step_id, payload)
        if old_row and old_row["station_id"] != station_id:
            validate_station_main_barcode(conn, old_row["station_id"])
        validate_station_main_barcode(conn, station_id)
    return {"ok": True}


def list_steps(station_id):
    with get_conn() as conn:
        return [
            row_to_dict(row)
            for row in conn.execute(
                "SELECT * FROM steps WHERE station_id = ? ORDER BY step_order, id",
                (station_id,),
            )
        ]


def station_config_step(step):
    return {
        "id": step.get("id"),
        "name": step.get("name", "未命名工序"),
        "type": step.get("type", SCAN_TYPE),
        "required_count": step.get("required_count") or 0,
        "barcode_start": step.get("barcode_start") or 1,
        "barcode_end": step.get("barcode_end") or 7,
        "expected_content": step.get("expected_content") or "",
        "is_main_barcode": bool(step.get("is_main_barcode", False)),
        **flow_step_config(step),
        **plc_step_config(step),
    }


def get_station_config(project_or_path, station_name=None):
    if station_name is None:
        parts = project_or_path.split("/")
        if len(parts) < 7 or parts[1:3] != ["api", "projects"] or parts[-1] != "config":
            raise ValueError("工位配置请求路径不正确")
        try:
            stations_marker = parts.index("stations", 3, len(parts) - 1)
        except ValueError as exc:
            raise ValueError("工位配置请求路径不正确") from exc
        project_name = unquote("/".join(parts[3:stations_marker]))
        station_name = unquote("/".join(parts[stations_marker + 1:-1]))
        if not project_name or not station_name:
            raise ValueError("项目和工位不能为空")
    else:
        project_name = project_or_path
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT projects.id AS project_id, stations.id AS station_id,
                   projects.name AS project_name, stations.name AS station_name
            FROM stations
            JOIN projects ON projects.id = stations.project_id
            WHERE projects.name = ? AND stations.name = ?
            """,
            (project_name, station_name),
        ).fetchone()
        if not row:
            raise ValueError("未找到项目工位配置")
        steps = list_steps(row["station_id"])
    return {
        "project_id": row["project_id"],
        "station_id": row["station_id"],
        "product_name": f"{project_name} - {station_name}",
        "steps": [station_config_step(step) for step in steps],
    }


def get_station_config_by_ids(project_id, station_id):
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT projects.id AS project_id, stations.id AS station_id,
                   projects.name AS project_name, stations.name AS station_name
            FROM stations
            JOIN projects ON projects.id = stations.project_id
            WHERE projects.id = ? AND stations.id = ?
            """,
            (project_id, station_id),
        ).fetchone()
        if not row:
            return None
        steps = list_steps(row["station_id"])
    return {
        "project_id": row["project_id"],
        "station_id": row["station_id"],
        "project_name": row["project_name"],
        "station_name": row["station_name"],
        "product_name": f"{row['project_name']} - {row['station_name']}",
        "steps": [station_config_step(step) for step in steps],
        "station_dependencies": product_flow.get_station_dependency(station_id),
    }


def normalize_main_barcode(payload, step_type: str) -> bool:
    is_main_barcode = bool(payload.get("is_main_barcode", False))
    if is_main_barcode and step_type not in (SCAN_TYPE, PLC_TYPE):
        raise ValueError("只有扫码工序或PLC接收工序可以设置为主条码")
    return is_main_barcode


def update_step_flow_config(conn, step_id, payload):
    conn.execute(
        """
        UPDATE steps
        SET switch_require_old = ?, switch_require_new = ?,
            switch_set_current = ?, switch_disable_old = ?,
            bind_child_project_id = ?, bind_child_material_type = ?,
            bind_required_count = ?, bind_required_station_ids = ?,
            bind_require_parent_switch = ?, bind_allow_duplicate = ?,
            bind_allow_unbind = ?
        WHERE id = ?
        """,
        (
            bool(payload.get("switch_require_old", True)),
            bool(payload.get("switch_require_new", True)),
            bool(payload.get("switch_set_current", True)),
            bool(payload.get("switch_disable_old", True)),
            int(payload.get("bind_child_project_id") or 0) or None,
            payload.get("bind_child_material_type", ""),
            max(int(payload.get("bind_required_count") or 1), 1),
            product_flow.json_ids(payload.get("bind_required_station_ids")),
            bool(payload.get("bind_require_parent_switch", True)),
            bool(payload.get("bind_allow_duplicate", False)),
            bool(payload.get("bind_allow_unbind", False)),
            step_id,
        ),
    )


def validate_flow_step_payload(conn, payload, step_type):
    if step_type == BARCODE_SWITCH_TYPE:
        if not bool(payload.get("switch_require_new", True)):
            raise ValueError("主条码切换工序必须获取新主条码")
        return
    if step_type != MATERIAL_BIND_TYPE:
        return
    child_project_id = int(payload.get("bind_child_project_id") or 0)
    child_type = str(payload.get("bind_child_material_type", "")).strip()
    if not child_project_id:
        raise ValueError("子物料绑定工序必须选择子物料项目")
    if not child_type:
        raise ValueError("子物料绑定工序必须填写子物料类型")
    if not conn.execute(
        "SELECT 1 FROM projects WHERE id = ?", (child_project_id,)
    ).fetchone():
        raise ValueError("子物料项目不存在")
    for station_id in product_flow.int_list(
        payload.get("bind_required_station_ids")
    ):
        station = conn.execute(
            "SELECT project_id FROM stations WHERE id = ?",
            (station_id,),
        ).fetchone()
        if not station:
            raise ValueError(f"子物料要求工位不存在：{station_id}")
        if int(station["project_id"]) != child_project_id:
            raise ValueError("子物料要求工位不属于所选子物料项目")


def flow_step_config(step):
    keys = step.keys() if hasattr(step, "keys") else []

    def value(name, default):
        return step[name] if name in keys and step[name] is not None else default

    return {
        "switch_require_old": bool(value("switch_require_old", True)),
        "switch_require_new": bool(value("switch_require_new", True)),
        "switch_set_current": bool(value("switch_set_current", True)),
        "switch_disable_old": bool(value("switch_disable_old", True)),
        "bind_child_project_id": value("bind_child_project_id", None),
        "bind_child_material_type": value("bind_child_material_type", ""),
        "bind_required_count": int(value("bind_required_count", 1)),
        "bind_required_station_ids": product_flow.int_list(
            value("bind_required_station_ids", "[]")
        ),
        "bind_require_parent_switch": bool(
            value("bind_require_parent_switch", True)
        ),
        "bind_allow_duplicate": bool(value("bind_allow_duplicate", False)),
        "bind_allow_unbind": bool(value("bind_allow_unbind", False)),
    }


def station_number_from_name(name: str) -> int:
    digits = "".join(ch for ch in str(name or "") if ch.isdigit())
    return int(digits) if digits else 1


def plc_payload_values(payload):
    values = dict(PLC_DEFAULTS)
    if payload.get("plc_barcode_db") in ("", None) and payload.get("plc_barcode1_db") not in ("", None):
        payload = dict(payload)
        payload["plc_barcode_db"] = payload.get("plc_barcode1_db")
        payload["plc_barcode_offset"] = payload.get("plc_barcode1_offset")
        payload["plc_barcode_length"] = payload.get("plc_barcode1_length")
    for key in PLC_DEFAULTS:
        if key in payload and payload.get(key) not in ("", None):
            values[key] = payload.get(key)
    values["plc_barcode1_db"] = values["plc_barcode_db"]
    values["plc_barcode1_offset"] = values["plc_barcode_offset"]
    values["plc_barcode1_length"] = values["plc_barcode_length"]
    int_keys = [
        "plc_rack",
        "plc_slot",
        "plc_barcode_db",
        "plc_barcode_offset",
        "plc_barcode_length",
        "plc_barcode1_db",
        "plc_barcode1_offset",
        "plc_barcode1_length",
        "plc_barcode2_db",
        "plc_barcode2_offset",
        "plc_barcode2_length",
        "plc_parts_ok_db",
        "plc_parts_ok_offset",
        "plc_use_barcode_index",
        "plc_barcode_strip_null",
        "plc_barcode_strip_space",
        "plc_timeout_seconds",
        "plc_poll_interval_ms",
        "plc_barcode_wait_ok_timeout_seconds",
    ]
    for key in int_keys:
        values[key] = int(bool(values[key])) if key in ("plc_barcode_strip_null", "plc_barcode_strip_space") else int(values[key])
    return [values[key] for key in PLC_DEFAULTS]


def plc_step_config(step):
    keys = step.keys() if hasattr(step, "keys") else []
    config = {key: step[key] for key in PLC_DEFAULTS if key in keys}
    if "plc_barcode_db" not in config and "plc_barcode1_db" in config:
        config["plc_barcode_db"] = config["plc_barcode1_db"]
        config["plc_barcode_offset"] = config.get("plc_barcode1_offset", 800)
        config["plc_barcode_length"] = config.get("plc_barcode1_length", 40)
    config["plc_barcode1_db"] = config.get("plc_barcode_db", config.get("plc_barcode1_db", 201))
    config["plc_barcode1_offset"] = config.get("plc_barcode_offset", config.get("plc_barcode1_offset", 800))
    config["plc_barcode1_length"] = config.get("plc_barcode_length", config.get("plc_barcode1_length", 40))
    return config


def clear_station_main_barcode(conn, station_id: int):
    conn.execute("UPDATE steps SET is_main_barcode = 0 WHERE station_id = ?", (station_id,))


def validate_station_main_barcode(conn, station_id: int):
    conn.execute(
        "UPDATE steps SET is_main_barcode = 0 WHERE station_id = ? AND type NOT IN (?, ?)",
        (station_id, SCAN_TYPE, PLC_TYPE),
    )
    scan_count = conn.execute(
        "SELECT COUNT(*) AS total FROM steps WHERE station_id = ? AND type IN (?, ?)",
        (station_id, SCAN_TYPE, PLC_TYPE),
    ).fetchone()["total"]
    if scan_count == 0:
        return
    main_count = conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM steps
        WHERE station_id = ? AND type IN (?, ?) AND is_main_barcode = 1
        """,
        (station_id, SCAN_TYPE, PLC_TYPE),
    ).fetchone()["total"]
    flow_identity = conn.execute(
        """
        SELECT 1 FROM steps
        WHERE station_id = ? AND type IN (?, ?)
        LIMIT 1
        """,
        (station_id, BARCODE_SWITCH_TYPE, MATERIAL_BIND_TYPE),
    ).fetchone()
    if main_count == 0:
        if flow_identity:
            return
        raise ValueError("每个工位必须配置一个主条码扫码工序")
    if main_count > 1:
        raise ValueError("每个工位只能配置一个主条码扫码工序")
    main_row = conn.execute(
        """
        SELECT steps.step_order, stations.name AS station_name
        FROM steps
        JOIN stations ON stations.id = steps.station_id
        WHERE station_id = ? AND type IN (?, ?) AND is_main_barcode = 1
        ORDER BY steps.step_order, steps.id LIMIT 1
        """,
        (station_id, SCAN_TYPE, PLC_TYPE),
    ).fetchone()
    if main_row and station_number_from_name(main_row["station_name"]) > 1 and int(main_row["step_order"]) != 1:
        raise ValueError("非第一工位的主条码工序必须是当前工位第1道工序")


def ensure_station_has_main_barcode(conn, station_id: int):
    conn.execute(
        "UPDATE steps SET is_main_barcode = 0 WHERE station_id = ? AND type NOT IN (?, ?)",
        (station_id, SCAN_TYPE, PLC_TYPE),
    )
    scan_count = conn.execute(
        "SELECT COUNT(*) AS total FROM steps WHERE station_id = ? AND type IN (?, ?)",
        (station_id, SCAN_TYPE, PLC_TYPE),
    ).fetchone()["total"]
    if scan_count == 0:
        return
    main_count = conn.execute(
        "SELECT COUNT(*) AS total FROM steps WHERE station_id = ? AND is_main_barcode = 1",
        (station_id,),
    ).fetchone()["total"]
    if main_count == 1:
        return
    if main_count > 1:
        first_main = conn.execute(
            "SELECT id FROM steps WHERE station_id = ? AND is_main_barcode = 1 ORDER BY step_order, id LIMIT 1",
            (station_id,),
        ).fetchone()
        conn.execute(
            "UPDATE steps SET is_main_barcode = CASE WHEN id = ? THEN 1 ELSE 0 END WHERE station_id = ?",
            (first_main["id"], station_id),
        )
        return
    flow_identity = conn.execute(
        """
        SELECT 1 FROM steps
        WHERE station_id = ? AND type IN (?, ?)
        LIMIT 1
        """,
        (station_id, BARCODE_SWITCH_TYPE, MATERIAL_BIND_TYPE),
    ).fetchone()
    if flow_identity:
        return
    first_scan = conn.execute(
        "SELECT id FROM steps WHERE station_id = ? AND type IN (?, ?) ORDER BY step_order, id LIMIT 1",
        (station_id, SCAN_TYPE, PLC_TYPE),
    ).fetchone()
    conn.execute("UPDATE steps SET is_main_barcode = 1 WHERE id = ?", (first_scan["id"],))


def find_project_station(conn, project_name, station_name):
    return conn.execute(
        """
        SELECT projects.id AS project_id, stations.id AS station_id
        FROM stations
        JOIN projects ON projects.id = stations.project_id
        WHERE projects.name = ? AND stations.name = ?
        """,
        (project_name, station_name),
    ).fetchone()


def check_station_completion(query):
    project_id = query.get("project_id", [""])[0]
    previous_station_id = query.get("previous_station_id", [""])[0]
    project = query.get("project", [""])[0]
    barcode = query.get("barcode", [""])[0]
    previous_station = query.get("previous_station", [""])[0]
    product_instance_id = query.get("product_instance_id", [""])[0]
    with get_conn() as conn:
        if project_id and previous_station_id:
            ids = {
                "project_id": int(project_id),
                "station_id": int(previous_station_id),
            }
            valid = conn.execute(
                "SELECT 1 FROM stations WHERE id = ? AND project_id = ?",
                (ids["station_id"], ids["project_id"]),
            ).fetchone()
            if not valid:
                return {"completed": False}
        else:
            ids = find_project_station(conn, project, previous_station)
        if not ids:
            return {"completed": False}
        if product_instance_id:
            row = conn.execute(
                """
                SELECT 1 FROM station_completions
                WHERE project_id = ? AND station_id = ?
                  AND (product_instance_id = ?
                       OR (product_instance_id IS NULL AND barcode = ?))
                """,
                (
                    ids["project_id"],
                    ids["station_id"],
                    int(product_instance_id),
                    barcode,
                ),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT 1 FROM station_completions
                WHERE project_id = ? AND station_id = ? AND barcode = ?
                """,
                (ids["project_id"], ids["station_id"], barcode),
            ).fetchone()
    return {"completed": row is not None}


def add_station_completion(payload):
    barcode = payload.get("barcode", "")
    completed_at = payload.get("completed_at") or now_text()
    if not barcode:
        raise ValueError("条码不能为空")
    with get_conn() as conn:
        project_id, station_id = resolve_project_station_ids(conn, payload)
        product_instance_id = product_flow.ensure_product_for_completion(
            conn, payload, project_id, barcode
        )
        if conn.db_type == "postgresql":
            conn.execute(
                """
                INSERT INTO station_completions
                (project_id, station_id, barcode, product_instance_id, barcode_used, completed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (project_id, station_id, barcode) DO NOTHING
                """,
                (
                    project_id,
                    station_id,
                    barcode,
                    product_instance_id,
                    payload.get("barcode_used") or barcode,
                    completed_at,
                ),
            )
        else:
            conn.execute(
                """
                INSERT OR REPLACE INTO station_completions
                (project_id, station_id, barcode, product_instance_id, barcode_used, completed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    station_id,
                    barcode,
                    product_instance_id,
                    payload.get("barcode_used") or barcode,
                    completed_at,
                ),
            )
        conn.execute(
            """
            INSERT INTO scan_records
            (project_id, station_id, barcode, product_instance_id, barcode_used,
             step, result, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                station_id,
                barcode,
                product_instance_id,
                payload.get("barcode_used") or barcode,
                "工位完成",
                "完成",
                "桌面端上报",
                completed_at,
            ),
        )
    return {"ok": True, "product_instance_id": product_instance_id}


def add_scan_record(payload):
    project = payload.get("project", "")
    station = payload.get("station", "")
    barcode = payload.get("barcode", "")
    if not barcode:
        raise ValueError("条码不能为空")
    with get_conn() as conn:
        ids = None
        if payload.get("project_id") and payload.get("station_id"):
            project_id, station_id = resolve_project_station_ids(conn, payload)
            ids = {"project_id": project_id, "station_id": station_id}
        elif project and station:
            ids = find_project_station(conn, project, station)
        conn.execute(
            """
            INSERT INTO scan_records
            (project_id, station_id, barcode, product_instance_id, barcode_used,
             step, result, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ids["project_id"] if ids else None,
                ids["station_id"] if ids else None,
                barcode,
                int(payload.get("product_instance_id") or 0) or None,
                payload.get("barcode_used") or barcode,
                payload.get("step", ""),
                payload.get("result", "记录"),
                payload.get("note", ""),
                payload.get("created_at") or now_text(),
            ),
        )
    return {"ok": True}


def update_scan_record(record_id, payload):
    barcode = payload.get("barcode", "").strip()
    result = payload.get("result", "").strip()
    note = payload.get("note", "")
    if not barcode:
        raise ValueError("条码不能为空")
    if not result:
        raise ValueError("结果不能为空")
    with get_conn() as conn:
        conn.execute(
            "UPDATE scan_records SET barcode = ?, result = ?, note = ? WHERE id = ?",
            (barcode, result, note, record_id),
        )
    return {"ok": True}


def delete_scan_record(record_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM scan_records WHERE id = ?", (record_id,))


def list_scan_records(query):
    record_id = query.get("id", [""])[0]
    barcode = query.get("barcode", [""])[0]
    start = query.get("start", [""])[0]
    end = query.get("end", [""])[0]
    sql = """
        SELECT scan_records.*, projects.name AS project, stations.name AS station
        FROM scan_records
        LEFT JOIN projects ON projects.id = scan_records.project_id
        LEFT JOIN stations ON stations.id = scan_records.station_id
        WHERE 1=1
    """
    params = []
    if record_id:
        sql += " AND scan_records.id = ?"
        params.append(record_id)
    if barcode:
        sql += " AND scan_records.barcode LIKE ?"
        params.append(f"%{barcode}%")
    if start:
        sql += " AND scan_records.created_at >= ?"
        params.append(start)
    if end:
        sql += " AND scan_records.created_at <= ?"
        params.append(end)
    page, page_size, offset = pagination(query)
    sql += " ORDER BY scan_records.created_at DESC LIMIT ? OFFSET ?"
    params.extend([page_size, offset])
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    records = [
        {
            "id": row["id"],
            "created_at": row_to_dict(row)["created_at"],
            "project": row["project"] or "",
            "station": row["station"] or "",
            "barcode": row["barcode"],
            "step": row["step"],
            "result": row["result"],
            "note": row["note"],
        }
        for row in rows
    ]
    return records


def list_production_records(query):
    return list_trace_table(
        query,
        "station_work_records",
        [
            "id",
            "project_id",
            "station_id",
            "product_instance_id",
            "barcode_used",
            "main_barcode",
            "product_name",
            "station_name",
            "start_time",
            "end_time",
            "work_duration_seconds",
            "total_steps",
            "completed_steps",
            "screw_required_count",
            "screw_ok_count",
            "screw_ng_count",
            "result",
            "operator",
            "note",
            "created_at",
            "updated_at",
        ],
    )


def add_production_record(payload):
    with get_conn() as conn:
        project_id, station_id = record_project_station_ids(conn, payload)
        cursor = conn.execute(
            """
            INSERT INTO station_work_records
            (project_id, station_id, product_instance_id, barcode_used,
             main_barcode, product_name, station_name, start_time, end_time,
             work_duration_seconds, total_steps, completed_steps, screw_required_count, screw_ok_count,
             screw_ng_count, result, operator, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                station_id,
                int(payload.get("product_instance_id") or 0) or None,
                payload.get("barcode_used") or payload.get("main_barcode", ""),
                payload.get("main_barcode", ""),
                payload.get("product_name", ""),
                payload.get("station_name", ""),
                payload.get("start_time") or now_text(),
                payload.get("end_time"),
                int(payload.get("work_duration_seconds", 0)),
                int(payload.get("total_steps", 0)),
                int(payload.get("completed_steps", 0)),
                int(payload.get("screw_required_count", 0)),
                int(payload.get("screw_ok_count", 0)),
                int(payload.get("screw_ng_count", 0)),
                payload.get("result", "进行中"),
                payload.get("operator", ""),
                payload.get("note", ""),
            ),
        )
    return {"id": cursor.lastrowid}


def list_step_records(query):
    return list_trace_table(
        query,
        "step_work_records",
        [
            "id",
            "station_work_id",
            "project_id",
            "station_id",
            "product_instance_id",
            "barcode_used",
            "main_barcode",
            "step_name",
            "step_type",
            "step_order",
            "start_time",
            "end_time",
            "duration_seconds",
            "barcode",
            "scan_result",
            "screw_required_count",
            "screw_ok_count",
            "screw_ng_count",
            "result",
            "note",
            "created_at",
        ],
    )


def add_step_record(payload):
    with get_conn() as conn:
        project_id, station_id = record_project_station_ids(conn, payload)
        cursor = conn.execute(
            """
            INSERT INTO step_work_records
            (station_work_id, project_id, station_id, product_instance_id, barcode_used,
             main_barcode, step_name, step_type, step_order,
             start_time, end_time, duration_seconds, barcode, scan_result, screw_required_count,
             screw_ok_count, screw_ng_count, result, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.get("station_work_id"),
                project_id,
                station_id,
                int(payload.get("product_instance_id") or 0) or None,
                payload.get("barcode_used") or payload.get("barcode") or payload.get("main_barcode", ""),
                payload.get("main_barcode", ""),
                payload.get("step_name", ""),
                payload.get("step_type", ""),
                int(payload.get("step_order", 0)),
                payload.get("start_time") or now_text(),
                payload.get("end_time"),
                int(payload.get("duration_seconds", 0)),
                payload.get("barcode", ""),
                payload.get("scan_result", ""),
                int(payload.get("screw_required_count", 0)),
                int(payload.get("screw_ok_count", 0)),
                int(payload.get("screw_ng_count", 0)),
                payload.get("result", "进行中"),
                payload.get("note", ""),
            ),
        )
    return {"id": cursor.lastrowid}


def list_screw_records(query):
    return list_trace_table(
        query,
        "screw_action_records",
        [
            "id",
            "station_work_id",
            "step_work_id",
            "project_id",
            "station_id",
            "product_instance_id",
            "barcode_used",
            "main_barcode",
            "step_name",
            "screw_index",
            "required_count",
            "status_value",
            "trigger_value",
            "direction_value",
            "result",
            "is_counted",
            "ng_reason",
            "created_at",
        ],
    )


def add_screw_record(payload):
    with get_conn() as conn:
        project_id, station_id = record_project_station_ids(conn, payload)
        cursor = conn.execute(
            """
            INSERT INTO screw_action_records
            (station_work_id, step_work_id, project_id, station_id,
             product_instance_id, barcode_used, main_barcode, step_name, screw_index,
             required_count, status_value, trigger_value, direction_value, result, is_counted, ng_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.get("station_work_id"),
                payload.get("step_work_id"),
                project_id,
                station_id,
                int(payload.get("product_instance_id") or 0) or None,
                payload.get("barcode_used") or payload.get("main_barcode", ""),
                payload.get("main_barcode", ""),
                payload.get("step_name", ""),
                payload.get("screw_index"),
                payload.get("required_count"),
                payload.get("status_value"),
                payload.get("trigger_value"),
                payload.get("direction_value"),
                payload.get("result", ""),
                bool(payload.get("is_counted", False)),
                payload.get("ng_reason", ""),
            ),
        )
    return {"id": cursor.lastrowid}


def list_trace_table(query, table_name, columns):
    page, page_size, offset = pagination(query)
    filters = []
    params = []
    main_barcode = query.get("main_barcode", query.get("barcode", [""]))[0]
    project_id = query.get("project_id", [""])[0]
    station_id = query.get("station_id", [""])[0]
    result = query.get("result", [""])[0]
    start_time = query.get("start_time", query.get("start", [""]))[0]
    end_time = query.get("end_time", query.get("end", [""]))[0]
    if main_barcode:
        filters.append("main_barcode = ?")
        params.append(main_barcode)
    if project_id:
        filters.append("project_id = ?")
        params.append(project_id)
    if station_id:
        filters.append("station_id = ?")
        params.append(station_id)
    if result:
        filters.append("result = ?")
        params.append(result)
    if start_time:
        filters.append("created_at >= ?")
        params.append(start_time)
    if end_time:
        filters.append("created_at <= ?")
        params.append(end_time)
    where = " WHERE " + " AND ".join(filters) if filters else ""
    sql = f"SELECT {', '.join(columns)} FROM {table_name}{where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([page_size, offset])
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {"page": page, "page_size": page_size, "records": [row_to_dict(row) for row in rows]}


def get_trace(query):
    barcode = query.get("barcode", query.get("main_barcode", [""]))[0]
    if not barcode:
        raise ValueError("条码不能为空")
    trace_query = dict(query)
    trace_query["main_barcode"] = [barcode]
    return {
        "barcode": barcode,
        "production_records": list_production_records(trace_query)["records"],
        "step_records": list_step_records(trace_query)["records"],
        "screw_records": list_screw_records(trace_query)["records"],
    }


def log_maintenance(action, message, detail=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO maintenance_logs (action, message, detail, created_at) VALUES (?, ?, ?, ?)",
            (action, message, json.dumps(detail or {}, ensure_ascii=False), now_text()),
        )


def db_status():
    db_config = database.load_database_config()
    tables = [
        "projects",
        "stations",
        "steps",
        "scan_records",
        "station_completions",
        "station_work_records",
        "step_work_records",
        "screw_action_records",
        "station_sessions",
        "product_instances",
        "barcode_aliases",
        "barcode_switch_records",
        "material_bindings",
        "station_dependencies",
        "maintenance_logs",
        "client_releases",
        "client_update_logs",
    ]
    counts = {}
    recent = {}
    with get_conn() as conn:
        for table in tables:
            counts[table] = conn.execute(f"SELECT COUNT(*) AS total FROM {table}").fetchone()["total"]
            if table in MAINTENANCE_TABLES or table in ("station_completions", "maintenance_logs"):
                row = conn.execute(f"SELECT MAX(created_at) AS last_time FROM {table}").fetchone()
                recent[table] = row["last_time"] if row else None
    size = ""
    if db_config["type"] == "sqlite":
        path = Path(db_config["path"])
        if not path.is_absolute():
            path = database.ROOT_DIR / path
        size = path.stat().st_size if path.exists() else 0
    return {
        "database_type": db_config["type"],
        "database_size": size,
        "table_counts": counts,
        "recent_times": recent,
        "backup_dir": str(BACKUP_DIR),
        "archive_dir": str(ARCHIVE_DIR),
        "version": (ROOT_DIR / "VERSION").read_text(encoding="utf-8").strip() if (ROOT_DIR / "VERSION").exists() else "",
    }


def backup_database():
    db_config = database.load_database_config()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if db_config["type"] == "sqlite":
        source = Path(db_config["path"])
        if not source.is_absolute():
            source = database.ROOT_DIR / source
        target = BACKUP_DIR / f"mes_sqlite_{stamp}.db"
        if source.exists():
            shutil.copy2(source, target)
        else:
            target.write_text("", encoding="utf-8")
    else:
        target = BACKUP_DIR / f"mes_db_{stamp}.dump"
        try:
            with target.open("wb") as file:
                subprocess.run(
                    [
                        "pg_dump",
                        "-U",
                        db_config["user"],
                        "-h",
                        db_config["host"],
                        "-p",
                        str(db_config["port"]),
                        "-Fc",
                        db_config["database"],
                    ],
                    check=True,
                    stdout=file,
                )
        except Exception:
            target.write_text("pg_dump执行失败，请在服务器检查PostgreSQL客户端工具和权限。", encoding="utf-8")
    log_maintenance("backup", "数据库备份完成", {"backup_file": str(target)})
    return {"backup_file": str(target)}


def archive_old_records(payload):
    before_date = payload.get("before_date")
    if not before_date:
        raise ValueError("归档日期不能为空")
    tables = payload.get("tables") or MAINTENANCE_TABLES
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_file = ARCHIVE_DIR / f"mes_archive_before_{before_date}_{stamp}.csv"
    counts = {}
    with get_conn() as conn, archive_file.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        for table in tables:
            if table not in MAINTENANCE_TABLES and table != "station_completions":
                continue
            time_column = table_time_column(table)
            rows = conn.execute(f"SELECT * FROM {table} WHERE {time_column} < ? ORDER BY {time_column}", (before_date,)).fetchall()
            counts[table] = len(rows)
            writer.writerow([f"TABLE:{table}"])
            if rows:
                columns = list(dict(rows[0]).keys())
                writer.writerow(columns)
                for row in rows:
                    writer.writerow([row[column] for column in columns])
    log_maintenance("archive", "历史数据归档完成", {"archive_file": str(archive_file), "counts": counts})
    return {"archive_file": str(archive_file), "counts": counts}


def delete_old_records(payload):
    if payload.get("admin_password") != ADMIN_PASSWORD:
        raise ValueError("管理员密码错误")
    before_date = payload.get("before_date")
    if not before_date:
        raise ValueError("删除日期不能为空")
    tables = payload.get("tables") or MAINTENANCE_TABLES
    if payload.get("include_station_completions"):
        tables = list(tables) + ["station_completions"]
    backup = backup_database()
    deleted_counts = {}
    with get_conn() as conn:
        for table in tables:
            if table == "station_completions" and not payload.get("include_station_completions"):
                continue
            if table not in MAINTENANCE_TABLES and table != "station_completions":
                continue
            time_column = table_time_column(table)
            count = conn.execute(f"SELECT COUNT(*) AS total FROM {table} WHERE {time_column} < ?", (before_date,)).fetchone()["total"]
            conn.execute(f"DELETE FROM {table} WHERE {time_column} < ?", (before_date,))
            deleted_counts[table] = count
    detail = {"backup_file": backup["backup_file"], "deleted_counts": deleted_counts}
    log_maintenance("delete-old-records", "历史数据删除完成", detail)
    return {"code": 1, "message": "历史数据删除完成", "data": detail}


def maintenance_logs(query):
    page, page_size, offset = pagination(query)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM maintenance_logs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
    return {"page": page, "page_size": page_size, "records": [row_to_dict(row) for row in rows]}


def vacuum_or_analyze():
    db_config = database.load_database_config()
    with get_conn() as conn:
        if db_config["type"] == "sqlite":
            conn.execute("VACUUM")
        else:
            conn.execute("ANALYZE")
    log_maintenance("vacuum-or-analyze", "数据库维护命令已执行")
    return {"ok": True}


def _version_key(version):
    raw = str(version or "").strip().lower().lstrip("v")
    parts = []
    for part in raw.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(part)
    return parts


def _safe_release_dir(version):
    version = str(version or "").strip()
    if not version or any(part in version for part in ("..", "/", "\\")):
        raise ValueError("版本号非法")
    return RELEASES_DIR / version


def _sha256_file(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_row_to_dict(row):
    data = row_to_dict(row)
    if not data:
        return data
    try:
        data["release_notes"] = json.loads(data.get("release_notes") or "[]")
    except json.JSONDecodeError:
        data["release_notes"] = []
    data["stable"] = bool(data.get("stable"))
    data["force_update"] = bool(data.get("force_update"))
    return data


def list_client_releases():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM client_releases ORDER BY release_date DESC, id DESC").fetchall()
    return [_release_row_to_dict(row) for row in rows]


def get_client_release(version):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM client_releases WHERE version = ?", (version,)).fetchone()
    return _release_row_to_dict(row)


def upsert_client_release(payload, files=None):
    version = str(payload.get("version", "")).strip()
    if not version:
        raise ValueError("版本号不能为空")
    title = str(payload.get("title", "")).strip()
    release_notes = payload.get("release_notes", [])
    if isinstance(release_notes, str):
        try:
            release_notes = json.loads(release_notes)
        except json.JSONDecodeError:
            release_notes = [line.strip() for line in release_notes.splitlines() if line.strip()]
    if not isinstance(release_notes, list):
        release_notes = [str(release_notes)]
    release_date = payload.get("release_date") or now_text()
    stable = bool(payload.get("stable", True))
    force_update = bool(payload.get("force_update", False))
    min_required_version = str(payload.get("min_required_version", "")).strip()
    release_dir = _safe_release_dir(version)
    release_dir.mkdir(parents=True, exist_ok=True)

    def store_file(key, target_name):
        file_obj = (files or {}).get(key)
        if not file_obj:
            return None, None
        target_path = release_dir / target_name
        with target_path.open("wb") as target:
            shutil.copyfileobj(file_obj, target)
        return str(target_path), _sha256_file(target_path)

    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM client_releases WHERE version = ?", (version,)).fetchone()
        release_file_path, release_sha256 = store_file("release_file", payload.get("release_filename") or "QualityControlSystem.exe")
        debug_file_path, debug_sha256 = store_file("debug_file", payload.get("debug_filename") or "QualityControlSystem_Debug.exe")
        s7_tool_file_path, s7_tool_sha256 = store_file("s7_tool_file", payload.get("s7_tool_filename") or "S7_PLC_Test_Tool.exe")
        release_file_path = release_file_path or (existing["release_file_path"] if existing else "")
        debug_file_path = debug_file_path or (existing["debug_file_path"] if existing else "")
        s7_tool_file_path = s7_tool_file_path or (existing["s7_tool_file_path"] if existing else "")
        release_sha256 = release_sha256 or (existing["release_sha256"] if existing else "")
        debug_sha256 = debug_sha256 or (existing["debug_sha256"] if existing else "")
        s7_tool_sha256 = s7_tool_sha256 or (existing["s7_tool_sha256"] if existing else "")
        if existing:
            conn.execute(
                """
                UPDATE client_releases
                SET title = ?, release_notes = ?, release_date = ?, stable = ?, force_update = ?,
                    min_required_version = ?, release_file_path = ?, debug_file_path = ?, s7_tool_file_path = ?,
                    release_sha256 = ?, debug_sha256 = ?, s7_tool_sha256 = ?, updated_at = ?
                WHERE version = ?
                """,
                (
                    title,
                    json.dumps(release_notes, ensure_ascii=False),
                    release_date,
                    stable,
                    force_update,
                    min_required_version,
                    release_file_path,
                    debug_file_path,
                    s7_tool_file_path,
                    release_sha256,
                    debug_sha256,
                    s7_tool_sha256,
                    now_text(),
                    version,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO client_releases
                (version, title, release_notes, release_date, stable, force_update, min_required_version,
                 release_file_path, debug_file_path, s7_tool_file_path, release_sha256, debug_sha256, s7_tool_sha256,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version,
                    title,
                    json.dumps(release_notes, ensure_ascii=False),
                    release_date,
                    stable,
                    force_update,
                    min_required_version,
                    release_file_path,
                    debug_file_path,
                    s7_tool_file_path,
                    release_sha256,
                    debug_sha256,
                    s7_tool_sha256,
                    now_text(),
                    now_text(),
                ),
            )
    return {"ok": True, "version": version}


def delete_client_release(version):
    release = get_client_release(version)
    if not release:
        raise ValueError("版本不存在")
    with get_conn() as conn:
        conn.execute("DELETE FROM client_releases WHERE version = ?", (version,))
    return {"ok": True}


def latest_client_release(query):
    client_version = str(query.get("client_version", [""])[0]).strip()
    channel = str(query.get("channel", ["stable"])[0]).strip().lower() or "stable"
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM client_releases ORDER BY release_date DESC, id DESC",
        ).fetchall()
    if channel == "stable":
        candidates = [row for row in rows if bool(row["stable"])]
    else:
        candidates = rows
    if not candidates:
        return {"code": 1, "data": {"has_update": False, "current_version": client_version, "latest_version": client_version}}
    latest = _release_row_to_dict(candidates[0])
    has_update = _version_key(latest["version"]) > _version_key(client_version)
    download_base = f"/api/client-update/download/{latest['version']}"
    return {
        "code": 1,
        "data": {
            "has_update": has_update,
            "current_version": client_version,
            "latest_version": latest["version"],
            "force_update": latest["force_update"],
            "title": latest["title"],
            "release_notes": latest["release_notes"],
            "download_url": f"{download_base}/release",
            "debug_download_url": f"{download_base}/debug",
            "s7_tool_download_url": f"{download_base}/s7_tool",
            "sha256": latest["release_sha256"],
            "size": Path(latest["release_file_path"]).stat().st_size if latest.get("release_file_path") and Path(latest["release_file_path"]).exists() else 0,
        },
    }


def download_client_release(version, kind):
    release = get_client_release(version)
    if not release:
        raise ValueError("版本不存在")
    field_map = {
        "release": ("release_file_path", "release.exe"),
        "debug": ("debug_file_path", "debug.exe"),
        "s7_tool": ("s7_tool_file_path", "s7_tool.exe"),
    }
    if kind not in field_map:
        raise ValueError("文件类型不正确")
    path_key, _default_name = field_map[kind]
    file_path = release.get(path_key)
    if not file_path or not Path(file_path).exists():
        raise ValueError("文件不存在")
    path = Path(file_path)
    return path, path.name or _default_name


def report_client_update(payload):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO client_update_logs
            (client_id, computer_name, ip_address, current_version, target_version, action, result, message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.get("client_id", ""),
                payload.get("computer_name", ""),
                payload.get("ip_address", ""),
                payload.get("current_version", ""),
                payload.get("target_version", ""),
                payload.get("action", ""),
                payload.get("result", ""),
                payload.get("message", ""),
                now_text(),
            ),
        )
    return {"ok": True}


def list_client_update_logs(query):
    page, page_size, offset = pagination(query)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM client_update_logs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
    return {"page": page, "page_size": page_size, "records": [row_to_dict(row) for row in rows]}
