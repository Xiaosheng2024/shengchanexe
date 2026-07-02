import csv
import json
import logging
import shutil
import socket
import subprocess
import hashlib
import os
import zipfile
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
CLIENT_UPDATES_DIR = RELEASES_DIR / "client_updates"
UPLOADS_DIR = Path("/opt/mes/uploads") if Path("/opt/mes").exists() else ROOT_DIR / "uploads"
MAX_CLIENT_UPDATE_FILE_BYTES = 220 * 1024 * 1024
MAINTENANCE_TABLES = [
    "scan_records",
    "station_work_records",
    "step_work_records",
    "screw_action_records",
    "plc_magnet_logs",
    "station_session_logs",
]


def table_time_column(table):
    return "completed_at" if table == "station_completions" else "created_at"
SCAN_TYPE = "扫码"
SCREW_TYPE = "螺丝"
PLC_TYPE = "PLC接收"
PLC_MAGNET_TYPE = "plc_magnet_check"
PLC_MAGNET_LEGACY_TYPE = "PLC磁通检测获取"
BARCODE_SWITCH_TYPE = "主条码切换"
MATERIAL_BIND_TYPE = "子物料绑定"
STATION_ROLES = {
    "普通工位",
    "起点工位",
    "PLC起点",
    "主条码切换工位",
    "合并工位",
    "合并绑定工位",
    "后续工位",
    "B起点工位",
    "B完成工位",
}
ROUTE_NAMES = {"A主线", "B子线", "返修线", "其他"}
STEP_TYPES = (
    SCAN_TYPE,
    SCREW_TYPE,
    PLC_TYPE,
    PLC_MAGNET_TYPE,
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
PLC_MAGNET_DEFAULTS = {
    "plc_enabled": True,
    "plc_ip": "192.168.111.50",
    "plc_rack": 0,
    "plc_slot": 1,
    "plc_db": 221,
    "plc_poll_interval_ms": 300,
    "plc_timeout_seconds": 30,
    "barcode_ok_offset": 0,
    "cylinder_clamped_offset": 2,
    "screw_complete_offset": 4,
    "magnet_complete_offset": 6,
    "mes_read_done_offset": 8,
    "left_flux_offset": 10,
    "left_polarity_offset": 14,
    "left_result_offset": 16,
    "right_flux_offset": 18,
    "right_polarity_offset": 22,
    "right_result_offset": 24,
    "ok_value": 1,
    "read_block_start": 0,
    "read_block_size": 26,
    "write_verify_retry_count": 3,
    "write_verify_interval_ms": 100,
}
STATION_SESSION_TIMEOUT_SECONDS = 120


class ClientValidationError(ValueError):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}


def normalize_step_type(value):
    if value == PLC_MAGNET_LEGACY_TYPE:
        return PLC_MAGNET_TYPE
    return value


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


def validate_station_session(payload):
    client_id = str(payload.get("client_id") or "").strip()
    if not client_id:
        raise ValueError("缺少 client_id，当前工位未占用成功，请重新下载配置")
    if payload.get("project_id") in (None, ""):
        raise ValueError("缺少 project_id，当前工位未占用成功，请重新下载配置")
    if payload.get("station_id") in (None, ""):
        raise ValueError("缺少 station_id，当前工位未占用成功，请重新下载配置")
    session_id = payload.get("station_session_id")
    if session_id in (None, ""):
        raise ValueError("当前工位未占用成功，请重新下载配置")
    try:
        project_id = int(payload["project_id"])
        station_id = int(payload["station_id"])
        session_id = int(session_id)
    except (TypeError, ValueError):
        raise ValueError("工位占用信息格式错误，请重新下载配置") from None

    with get_conn() as conn:
        release_stale_station_sessions(conn)
        row = conn.execute(
            "SELECT * FROM station_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not row or row["status"] != "online":
            raise ValueError("工位占用已失效，请重新下载配置")
        if (
            int(row["project_id"]) != project_id
            or int(row["station_id"]) != station_id
        ):
            raise ValueError("当前工位占用信息不匹配，请重新下载配置")
        if str(row["client_id"]) != client_id:
            raise ValueError("当前客户端与工位占用信息不匹配，请重新下载配置")
        last_heartbeat = parse_time(row["last_heartbeat_at"])
        threshold = datetime.now() - timedelta(
            seconds=STATION_SESSION_TIMEOUT_SECONDS
        )
        if not last_heartbeat or last_heartbeat < threshold:
            conn.execute(
                "UPDATE station_sessions SET status = 'offline', note = ? WHERE id = ?",
                ("心跳超时自动释放", session_id),
            )
            raise ValueError("工位占用已失效，请重新下载配置")
        return row_to_dict(row)


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
    session = validate_station_session(payload)
    with get_conn() as conn:
        conn.execute(
            "UPDATE station_sessions SET last_heartbeat_at = ?, note = ? WHERE id = ?",
            (now_text(), "心跳更新", session["id"]),
        )
    return {"ok": True, "session_id": session["id"]}


def release_station_session(payload):
    client_id = str(payload.get("client_id") or "").strip()
    if not client_id:
        raise ValueError("缺少 client_id，当前工位未占用成功，请重新下载配置")
    if payload.get("station_session_id") in (None, ""):
        raise ValueError("当前工位未占用成功，请重新下载配置")
    with get_conn() as conn:
        project_id, station_id = resolve_project_station_ids(conn, payload)
        try:
            session_id = int(payload["station_session_id"])
        except (TypeError, ValueError):
            raise ValueError("station_session_id格式错误") from None
        row = conn.execute(
            "SELECT * FROM station_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            raise ValueError("工位占用已失效，请重新下载配置")
        if (
            int(row["project_id"]) != project_id
            or int(row["station_id"]) != station_id
            or str(row["client_id"]) != client_id
        ):
            raise ValueError("当前工位占用信息不匹配，请重新下载配置")
        conn.execute(
            "UPDATE station_sessions SET status = 'offline', note = ? "
            "WHERE id = ? AND status = 'online'",
            ("客户端释放", session_id),
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
                """
                SELECT id, name, route_name, route_order, station_role, material_type
                FROM stations
                WHERE project_id = ?
                ORDER BY
                  CASE route_name
                    WHEN 'A主线' THEN 1 WHEN 'B子线' THEN 2
                    WHEN '返修线' THEN 3 ELSE 4
                  END,
                  route_order, id
                """,
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
                        row_to_dict(row)
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
                """
                SELECT * FROM stations
                WHERE project_id = ?
                ORDER BY
                  CASE route_name
                    WHEN 'A主线' THEN 1 WHEN 'B子线' THEN 2
                    WHEN '返修线' THEN 3 ELSE 4
                  END,
                  route_order, id
                """,
                (project["id"],),
            ).fetchall()
            project["stations"] = [row_to_dict(row) for row in stations]
            for station in project["stations"]:
                station["steps"] = [
                    station_config_step(step)
                    for step in list_steps(station["id"])
                ]
                station["dependency"] = product_flow.get_station_dependency(
                    station["id"]
                )
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
    route_name, route_order, station_role, material_type = station_route_values(
        payload
    )
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO stations
            (project_id, name, route_name, route_order, station_role,
             material_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                name,
                route_name,
                route_order,
                station_role,
                material_type,
                now_text(),
            ),
        )
        return {"id": cursor.lastrowid, "name": name}


def update_station(station_id, payload):
    project_id = int(payload.get("project_id", 0))
    name = payload.get("name", "").strip()
    if not project_id or not name:
        raise ValueError("项目和工位名称不能为空")
    with get_conn() as conn:
        current = conn.execute(
            "SELECT * FROM stations WHERE id = ?", (station_id,)
        ).fetchone()
        if not current:
            raise ValueError("工位不存在")
        merged = {
            "route_name": payload.get("route_name", current["route_name"]),
            "route_order": payload.get("route_order", current["route_order"]),
            "station_role": payload.get("station_role", current["station_role"]),
            "material_type": payload.get("material_type", current["material_type"]),
        }
        route_name, route_order, station_role, material_type = (
            station_route_values(merged)
        )
        conn.execute(
            """
            UPDATE stations
            SET project_id = ?, name = ?, route_name = ?, route_order = ?,
                station_role = ?, material_type = ?
            WHERE id = ?
            """,
            (
                project_id,
                name,
                route_name,
                route_order,
                station_role,
                material_type,
                station_id,
            ),
        )
    return {"ok": True}


def station_route_values(payload):
    route_name = str(payload.get("route_name") or "A主线").strip() or "A主线"
    if route_name not in ROUTE_NAMES:
        raise ValueError("所属路线不正确")
    route_order = max(int(payload.get("route_order") or 0), 0)
    station_role = str(payload.get("station_role") or "普通工位").strip()
    if station_role not in STATION_ROLES:
        raise ValueError("工位作用不正确")
    material_type = str(payload.get("material_type") or "").strip()
    return route_name, route_order, station_role, material_type


def get_route_config(project_id):
    project_id = int(project_id)
    project = next(
        (
            project
            for project in list_projects_full()
            if int(project["id"]) == project_id
        ),
        None,
    )
    if not project:
        raise ValueError("项目不存在")
    return {
        "project": project,
        "route_names": sorted(
            {station["route_name"] or "A主线" for station in project["stations"]}
        ),
        "templates": [
            "普通串行路线",
            "PLC首工位路线",
            "主条码切换路线",
            "B子线两工位路线",
            "A主线绑定B子线路线",
        ],
    }


def create_route_template(project_id, template_name):
    project_id = int(project_id)
    template_name = str(template_name or "").strip()
    with get_conn() as conn:
        project = conn.execute(
            "SELECT id, name FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not project:
            raise ValueError("项目不存在")
        specs = route_template_specs(project["name"], template_name)
        existing_names = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM stations WHERE project_id = ?", (project_id,)
            )
        }
        duplicate_names = [
            spec["name"] for spec in specs if spec["name"] in existing_names
        ]
        if duplicate_names:
            raise ValueError(
                "模板工位已存在：" + "、".join(duplicate_names)
            )

        station_ids = {}
        for spec in specs:
            cursor = conn.execute(
                """
                INSERT INTO stations
                (project_id, name, route_name, route_order, station_role,
                 material_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    spec["name"],
                    spec["route"],
                    spec["order"],
                    spec["role"],
                    spec["material"],
                    now_text(),
                ),
            )
            station_ids[spec["key"]] = cursor.lastrowid

        for spec in specs:
            station_id = station_ids[spec["key"]]
            for step in spec["steps"]:
                cursor = conn.execute(
                    """
                    INSERT INTO steps
                    (station_id, step_order, name, type, required_count,
                     barcode_start, barcode_end, expected_content,
                     is_main_barcode, created_at)
                    VALUES (?, ?, ?, ?, ?, 1, 7, '', ?, ?)
                    """,
                    (
                        station_id,
                        step["order"],
                        step["name"],
                        step["type"],
                        step.get("required_count", 0),
                        1 if step.get("is_main_barcode") else 0,
                        now_text(),
                    ),
                )
                if step["type"] == MATERIAL_BIND_TYPE:
                    conn.execute(
                        """
                        UPDATE steps
                        SET bind_child_project_id = ?,
                            bind_child_material_type = 'B物料',
                            bind_child_route = 'B子线',
                            bind_required_count = 1,
                            bind_required_station_ids = ?,
                            bind_require_parent_switch = ?,
                            bind_allow_duplicate = ?,
                            bind_allow_unbind = ?
                        WHERE id = ?
                        """,
                        (
                            project_id,
                            product_flow.json_ids(
                                [
                                    station_ids["b_pre1"],
                                    station_ids["b_pre2"],
                                ]
                            ),
                            True,
                            False,
                            False,
                            cursor.lastrowid,
                        ),
                    )

        for spec in specs:
            dependency = spec.get("dependency") or {}
            required_ids = [
                station_ids[key] for key in dependency.get("required", [])
            ]
            child_ids = [
                station_ids[key]
                for key in dependency.get("child_required", [])
            ]
            conn.execute(
                """
                INSERT INTO station_dependencies
                (station_id, require_previous_station, required_station_ids,
                 require_barcode_switch, require_current_barcode,
                 required_child_project_id, required_child_material_type,
                 required_child_count, required_child_station_ids,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    station_ids[spec["key"]],
                    False,
                    product_flow.json_ids(required_ids),
                    bool(dependency.get("switch")),
                    bool(dependency.get("current_barcode")),
                    project_id if dependency.get("child_count") else None,
                    "B物料" if dependency.get("child_count") else "",
                    int(dependency.get("child_count", 0)),
                    product_flow.json_ids(child_ids),
                    now_text(),
                    now_text(),
                ),
            )
    return get_route_config(project_id)


def route_template_specs(project_name, template_name):
    prefix = str(project_name).strip()
    scan = lambda name, order=1, main=True: {
        "name": name,
        "type": SCAN_TYPE,
        "order": order,
        "is_main_barcode": main,
    }
    plc = lambda name: {
        "name": name,
        "type": PLC_TYPE,
        "order": 1,
        "is_main_barcode": True,
    }
    switch = {
        "name": "A主条码切换",
        "type": BARCODE_SWITCH_TYPE,
        "order": 1,
    }
    bind = {
        "name": "A绑定B物料",
        "type": MATERIAL_BIND_TYPE,
        "order": 1,
    }
    if template_name == "A主线绑定B子线路线":
        return [
            {
                "key": "a1", "name": f"{prefix}-A主线1",
                "route": "A主线", "order": 1, "role": "PLC起点",
                "material": "A物料", "steps": [plc("PLC接收A主条码")],
                "dependency": {},
            },
            {
                "key": "a2", "name": f"{prefix}-A主线2",
                "route": "A主线", "order": 2, "role": "普通工位",
                "material": "A物料",
                "steps": [scan("扫码A主条码"), scan("A普通规则", 2, False)],
                "dependency": {"required": ["a1"]},
            },
            {
                "key": "a_switch", "name": f"{prefix}-A主条码切换",
                "route": "A主线", "order": 3,
                "role": "主条码切换工位", "material": "A物料",
                "steps": [switch],
                "dependency": {"required": ["a2"], "current_barcode": True},
            },
            {
                "key": "a_merge", "name": f"{prefix}-A合并B工位",
                "route": "A主线", "order": 4, "role": "合并绑定工位",
                "material": "A物料", "steps": [bind],
                "dependency": {
                    "required": ["a_switch"],
                    "switch": True,
                    "current_barcode": True,
                },
            },
            {
                "key": "a_after", "name": f"{prefix}-A后续工位",
                "route": "A主线", "order": 5, "role": "后续工位",
                "material": "A物料", "steps": [scan("扫码A当前主条码")],
                "dependency": {
                    "required": ["a_merge"],
                    "switch": True,
                    "current_barcode": True,
                    "child_count": 1,
                    "child_required": ["b_pre1", "b_pre2"],
                },
            },
            {
                "key": "b_pre1", "name": "B子线-预装1",
                "route": "B子线", "order": 1, "role": "B起点工位",
                "material": "B物料", "steps": [scan("扫码B主条码")],
                "dependency": {},
            },
            {
                "key": "b_pre2", "name": "B子线-预装2",
                "route": "B子线", "order": 2, "role": "B完成工位",
                "material": "B物料",
                "steps": [scan("扫码B主条码"), scan("B完成确认", 2, False)],
                "dependency": {"required": ["b_pre1"]},
            },
        ]
    if template_name == "B子线两工位路线":
        return [
            {
                "key": "b_pre1", "name": "B子线-预装1",
                "route": "B子线", "order": 1, "role": "B起点工位",
                "material": "B物料", "steps": [scan("扫码B主条码")],
                "dependency": {},
            },
            {
                "key": "b_pre2", "name": "B子线-预装2",
                "route": "B子线", "order": 2, "role": "B完成工位",
                "material": "B物料", "steps": [scan("扫码B主条码")],
                "dependency": {"required": ["b_pre1"]},
            },
        ]
    if template_name == "主条码切换路线":
        return [
            {
                "key": "start", "name": f"{prefix}-起点",
                "route": "A主线", "order": 1, "role": "起点工位",
                "material": "A物料", "steps": [scan("扫码旧主条码")],
                "dependency": {},
            },
            {
                "key": "switch", "name": f"{prefix}-主条码切换",
                "route": "A主线", "order": 2,
                "role": "主条码切换工位", "material": "A物料",
                "steps": [switch],
                "dependency": {"required": ["start"], "current_barcode": True},
            },
        ]
    if template_name in {"普通串行路线", "PLC首工位路线"}:
        first_step = plc("PLC接收主条码") if template_name == "PLC首工位路线" else scan("扫码主条码")
        return [
            {
                "key": "start", "name": f"{prefix}-工位1",
                "route": "A主线", "order": 1,
                "role": (
                    "PLC起点"
                    if template_name == "PLC首工位路线"
                    else "起点工位"
                ),
                "material": "A物料", "steps": [first_step],
                "dependency": {},
            },
            {
                "key": "next", "name": f"{prefix}-工位2",
                "route": "A主线", "order": 2, "role": "普通工位",
                "material": "A物料", "steps": [scan("扫码主条码")],
                "dependency": {"required": ["start"]},
            },
        ]
    raise ValueError("未知的工艺路线模板")


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
    conn.execute("DELETE FROM plc_magnet_logs WHERE station_id = ?", (station_id,))
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
    step_type = normalize_step_type(payload.get("type", "扫码"))
    is_main_barcode = normalize_main_barcode(payload, step_type)
    if not station_id or not name:
        raise ValueError("工位和工序名称不能为空")
    if step_type not in STEP_TYPES:
        raise ValueError("功能只能是扫码、螺丝、PLC接收、PLC磁通检测获取、主条码切换或子物料绑定")
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
        update_step_magnet_config(conn, cursor.lastrowid, payload, step_type)
        validate_station_main_barcode(conn, station_id)
        return {"id": cursor.lastrowid}


def update_step(step_id, payload):
    name = payload.get("name", "").strip()
    step_type = normalize_step_type(payload.get("type", "扫码"))
    station_id = int(payload.get("station_id", 0))
    is_main_barcode = normalize_main_barcode(payload, step_type)
    if not station_id or not name:
        raise ValueError("工位和工序名称不能为空")
    if step_type not in STEP_TYPES:
        raise ValueError("功能只能是扫码、螺丝、PLC接收、PLC磁通检测获取、主条码切换或子物料绑定")
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
        update_step_magnet_config(conn, step_id, payload, step_type)
        if old_row and old_row["station_id"] != station_id:
            validate_station_main_barcode(conn, old_row["station_id"])
        validate_station_main_barcode(conn, station_id)
    return {"ok": True}


def list_steps(station_id):
    with get_conn() as conn:
        steps = [
            row_to_dict(row)
            for row in conn.execute(
                "SELECT * FROM steps WHERE station_id = ? ORDER BY step_order, id",
                (station_id,),
            )
        ]
    for step in steps:
        step["type"] = normalize_step_type(step.get("type", SCAN_TYPE))
        step["is_main_barcode"] = bool(step.get("is_main_barcode"))
        step["bind_required_station_ids"] = product_flow.int_list(
            step.get("bind_required_station_ids")
        )
        step["plc_magnet_config"] = magnet_step_config(step)
    return steps


def station_config_step(step):
    return {
        "id": step.get("id"),
        "step_order": step.get("step_order") or 1,
        "name": step.get("name", "未命名工序"),
        "type": normalize_step_type(step.get("type", SCAN_TYPE)),
        "required_count": step.get("required_count") or 0,
        "barcode_start": step.get("barcode_start") or 1,
        "barcode_end": step.get("barcode_end") or 7,
        "expected_content": step.get("expected_content") or "",
        "is_main_barcode": bool(step.get("is_main_barcode", False)),
        **flow_step_config(step),
        **plc_step_config(step),
        "plc_magnet_config": magnet_step_config(step),
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
                   projects.name AS project_name, stations.name AS station_name,
                   stations.route_name, stations.route_order,
                   stations.station_role, stations.material_type
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
        "route_name": row["route_name"],
        "route_order": row["route_order"],
        "station_role": row["station_role"],
        "material_type": row["material_type"],
        "product_name": f"{project_name} - {station_name}",
        "steps": [station_config_step(step) for step in steps],
    }


def get_station_config_by_ids(project_id, station_id):
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT projects.id AS project_id, stations.id AS station_id,
                   projects.name AS project_name, stations.name AS station_name,
                   stations.route_name, stations.route_order,
                   stations.station_role, stations.material_type
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
        "route_name": row["route_name"],
        "route_order": row["route_order"],
        "station_role": row["station_role"],
        "material_type": row["material_type"],
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
            bind_child_route = ?,
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
            payload.get("bind_child_route", ""),
            max(int(payload.get("bind_required_count") or 1), 1),
            product_flow.json_ids(payload.get("bind_required_station_ids")),
            bool(payload.get("bind_require_parent_switch", True)),
            bool(payload.get("bind_allow_duplicate", False)),
            bool(payload.get("bind_allow_unbind", False)),
            step_id,
        ),
    )


def normalized_magnet_config(payload):
    source = payload.get("plc_magnet_config") or {}
    if isinstance(source, str):
        try:
            source = json.loads(source)
        except (TypeError, ValueError):
            source = {}
    values = dict(PLC_MAGNET_DEFAULTS)
    for key in values:
        if key in source and source[key] not in ("", None):
            values[key] = source[key]
        elif key in payload and payload[key] not in ("", None):
            values[key] = payload[key]
    bool_keys = {"plc_enabled"}
    int_keys = set(values) - {"plc_ip"} - bool_keys
    for key in bool_keys:
        values[key] = bool(values[key])
    for key in int_keys:
        values[key] = int(values[key])
    if values["read_block_size"] < 26:
        raise ValueError("PLC磁通检测原始块读取长度不能小于26字节")
    if values["write_verify_retry_count"] < 1:
        raise ValueError("PLC磁通检测写入读回次数至少为1")
    return values


def update_step_magnet_config(conn, step_id, payload, step_type):
    config = (
        normalized_magnet_config(payload)
        if step_type == PLC_MAGNET_TYPE
        else {}
    )
    conn.execute(
        "UPDATE steps SET plc_magnet_config = ? WHERE id = ?",
        (json.dumps(config, ensure_ascii=False), step_id),
    )


def magnet_step_config(step):
    keys = step.keys() if hasattr(step, "keys") else []
    raw = step["plc_magnet_config"] if "plc_magnet_config" in keys else {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = {}
    return normalized_magnet_config({"plc_magnet_config": raw})


def validate_flow_step_payload(conn, payload, step_type):
    if step_type == BARCODE_SWITCH_TYPE:
        if not bool(payload.get("switch_require_new", True)):
            raise ValueError("主条码切换工序必须获取新主条码")
        return
    if step_type != MATERIAL_BIND_TYPE:
        return
    child_project_id = int(payload.get("bind_child_project_id") or 0)
    child_type = str(payload.get("bind_child_material_type", "")).strip()
    child_route = str(payload.get("bind_child_route", "")).strip()
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
            "SELECT project_id, route_name FROM stations WHERE id = ?",
            (station_id,),
        ).fetchone()
        if not station:
            raise ValueError(f"子物料要求工位不存在：{station_id}")
        if int(station["project_id"]) != child_project_id:
            raise ValueError("子物料要求工位不属于所选子物料项目")
        if child_route and station["route_name"] != child_route:
            raise ValueError("子物料要求工位不属于所选子件路线")


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
        "bind_child_route": value("bind_child_route", ""),
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


def _validate_barcode_use(conn, payload):
    barcode = str(payload.get("barcode") or "").strip()
    station_id = int(payload.get("station_id") or 0)
    product_instance_id = int(payload.get("product_instance_id") or 0) or None
    step_id = int(payload.get("step_id") or 0) or None
    is_main = bool(payload.get("is_main_barcode"))
    if not barcode or not station_id:
        raise ValueError("缺少条码或工位")
    if is_main:
        completion = conn.execute(
            """
            SELECT station_completions.id, projects.name AS project_name,
                   stations.name AS station_name,
                   station_completions.completed_at AS used_at
            FROM station_completions
            JOIN projects ON projects.id = station_completions.project_id
            JOIN stations ON stations.id = station_completions.station_id
            WHERE station_completions.station_id = ?
              AND (station_completions.barcode = ?
                   OR station_completions.barcode_used = ?
                   OR (? IS NOT NULL AND station_completions.product_instance_id = ?))
            LIMIT 1
            """,
            (station_id, barcode, barcode, product_instance_id, product_instance_id),
        ).fetchone()
        record = completion or conn.execute(
            """
            SELECT scan_records.id, projects.name AS project_name,
                   stations.name AS station_name, scan_records.step AS step_name,
                   scan_records.created_at AS used_at
            FROM scan_records
            LEFT JOIN projects ON projects.id = scan_records.project_id
            LEFT JOIN stations ON stations.id = scan_records.station_id
            WHERE scan_records.station_id = ?
              AND scan_records.is_main_barcode = 1
              AND scan_records.is_cancelled = 0
              AND scan_records.result IN ('完成', 'OK')
              AND (scan_records.barcode = ?
                   OR scan_records.barcode_used = ?
                   OR (? IS NOT NULL AND scan_records.product_instance_id = ?))
            LIMIT 1
            """,
            (station_id, barcode, barcode, product_instance_id, product_instance_id),
        ).fetchone()
        if record:
            return {
                "allowed": False,
                "message": "当前主条码已在本工位扫码/完成，禁止重复扫码。",
                "existing": row_to_dict(record),
            }
        return {"allowed": True}
    bound = conn.execute(
        """
        SELECT material_bindings.id, projects.name AS project_name,
               stations.name AS station_name, '子物料绑定' AS step_name,
               material_bindings.created_at AS used_at
        FROM material_bindings
        LEFT JOIN projects ON projects.id = material_bindings.project_id
        LEFT JOIN stations ON stations.id = material_bindings.station_id
        WHERE material_bindings.child_barcode = ?
          AND material_bindings.is_active
        LIMIT 1
        """,
        (barcode,),
    ).fetchone()
    alias = conn.execute(
        """
        SELECT barcode_aliases.id, projects.name AS project_name,
               '' AS station_name, '产品主条码' AS step_name,
               barcode_aliases.created_at AS used_at
        FROM barcode_aliases
        JOIN product_instances
          ON product_instances.id = barcode_aliases.product_instance_id
        LEFT JOIN projects ON projects.id = product_instances.project_id
        WHERE barcode_aliases.barcode = ?
        LIMIT 1
        """,
        (barcode,),
    ).fetchone()
    record = bound or alias or conn.execute(
        """
        SELECT scan_records.id, scan_records.station_id, scan_records.step_id,
               scan_records.product_instance_id, projects.name AS project_name,
               stations.name AS station_name, scan_records.step AS step_name,
               scan_records.created_at AS used_at
        FROM scan_records
        LEFT JOIN projects ON projects.id = scan_records.project_id
        LEFT JOIN stations ON stations.id = scan_records.station_id
        WHERE scan_records.barcode = ?
          AND scan_records.is_main_barcode = 0
          AND scan_records.is_cancelled = 0
          AND scan_records.result IN ('完成', 'OK')
        ORDER BY scan_records.id
        LIMIT 1
        """,
        (barcode,),
    ).fetchone()
    if record:
        detail = row_to_dict(record)
        return {
            "allowed": False,
            "message": (
                "该条码已在其他位置使用："
                f"{detail.get('project_name') or ''}/"
                f"{detail.get('station_name') or ''}/"
                f"{detail.get('step_name') or ''}/"
                f"{detail.get('used_at') or ''}"
            ),
            "existing": detail,
        }
    return {"allowed": True, "step_id": step_id}


def validate_barcode_use(payload):
    with get_conn() as conn:
        return _validate_barcode_use(conn, payload)


def cancel_barcode_record(payload):
    barcode = str(
        payload.get("barcode_to_cancel") or payload.get("barcode") or ""
    ).strip()
    station_id = int(payload.get("station_id") or 0)
    project_id = int(payload.get("project_id") or 0)
    step_id = int(
        payload.get("current_step_id") or payload.get("step_id") or 0
    ) or None
    product_instance_id = int(
        payload.get("current_product_id")
        or payload.get("product_instance_id")
        or 0
    ) or None
    current_main_barcode = str(
        payload.get("current_main_barcode") or ""
    ).strip()
    requested_cancel_type = str(
        payload.get("cancel_type") or "auto"
    ).strip().lower()
    if requested_cancel_type not in {
        "auto",
        "main_barcode",
        "component_barcode",
        "non_main_barcode",
    }:
        raise ValueError("取消条码类型不正确")
    raw_is_main = payload.get("is_main_barcode")
    is_main = (
        raw_is_main
        if isinstance(raw_is_main, bool)
        else str(raw_is_main or "").strip().lower()
        in {"1", "true", "yes", "是"}
    )
    if requested_cancel_type == "main_barcode":
        is_main = True
    elif requested_cancel_type in {
        "component_barcode",
        "non_main_barcode",
    }:
        is_main = False
    operator = str(payload.get("operator") or "管理员").strip()
    reason_text = str(payload.get("reason") or "cancelcode").strip()
    if not barcode or not station_id or not project_id:
        raise ValueError("取消条码缺少项目、工位或条码")
    logging.info(
        "收到取消条码请求 client_id=%s project_id=%s station_id=%s "
        "session_id=%s current_step_id=%s current_product_id=%s "
        "current_main_barcode=%s barcode_to_cancel=%s cancel_type=%s "
        "reason=%s",
        payload.get("client_id"),
        project_id,
        station_id,
        payload.get("station_session_id"),
        step_id,
        product_instance_id,
        current_main_barcode,
        barcode,
        requested_cancel_type,
        reason_text,
    )
    with get_conn() as conn:
        def cancel_mismatch(message):
            other = conn.execute(
                """
                SELECT id, project_id, station_id, step_id
                FROM scan_records
                WHERE barcode = ? AND is_cancelled = 0
                  AND result IN ('完成', 'OK')
                ORDER BY CASE WHEN station_id = ? THEN 0 ELSE 1 END, id DESC
                LIMIT 1
                """,
                (barcode, station_id),
            ).fetchone()
            details = {
                "request_station_id": station_id,
                "record_station_id": other["station_id"] if other else None,
                "found_record_station_id": (
                    other["station_id"] if other else None
                ),
                "record_step_id": other["step_id"] if other else None,
                "record_project_id": other["project_id"] if other else None,
                "barcode": barcode,
                "barcode_to_cancel": barcode,
                "current_main_barcode": current_main_barcode,
                "matched_record_id": other["id"] if other else None,
                "reason": message,
            }
            logging.warning("取消条码拒绝：%s", details)
            raise ClientValidationError(message, details)

        if requested_cancel_type == "auto":
            if current_main_barcode and barcode == current_main_barcode:
                is_main = True
            else:
                auto_record = conn.execute(
                    """
                    SELECT id, is_main_barcode
                    FROM scan_records
                    WHERE project_id = ? AND station_id = ?
                      AND barcode = ? AND is_cancelled = 0
                      AND result IN ('完成', 'OK')
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (project_id, station_id, barcode),
                ).fetchone()
                if auto_record:
                    is_main = bool(auto_record["is_main_barcode"])
                    logging.info(
                        "取消条码auto匹配 record_id=%s is_main=%s",
                        auto_record["id"],
                        is_main,
                    )

        affected_record_ids = []
        if is_main:
            record = conn.execute(
                """
                SELECT id FROM station_completions
                WHERE project_id = ? AND station_id = ?
                  AND (barcode = ? OR barcode_used = ?
                       OR (? IS NOT NULL AND product_instance_id = ?))
                ORDER BY id DESC LIMIT 1
                """,
                (
                    project_id,
                    station_id,
                    barcode,
                    barcode,
                    product_instance_id,
                    product_instance_id,
                ),
            ).fetchone()
            scan_record = conn.execute(
                """
                SELECT id, step_id FROM scan_records
                WHERE project_id = ? AND station_id = ?
                  AND is_main_barcode = 1 AND is_cancelled = 0
                  AND result IN ('完成', 'OK')
                  AND (barcode = ? OR barcode_used = ?
                       OR (? IS NOT NULL AND product_instance_id = ?))
                ORDER BY id DESC LIMIT 1
                """,
                (
                    project_id,
                    station_id,
                    barcode,
                    barcode,
                    product_instance_id,
                    product_instance_id,
                ),
            ).fetchone()
            if not record and not scan_record:
                cancel_mismatch("该主条码在当前工位没有可取消记录")
            if record:
                conn.execute(
                    "DELETE FROM station_completions WHERE id = ?", (record["id"],)
                )
                affected_record_ids.append(
                    f"station_completion:{record['id']}"
                )
            scan_rows = conn.execute(
                """
                SELECT id FROM scan_records
                WHERE project_id = ? AND station_id = ?
                  AND is_main_barcode = 1 AND is_cancelled = 0
                  AND (barcode = ? OR barcode_used = ?
                       OR (? IS NOT NULL AND product_instance_id = ?))
                """,
                (
                    project_id,
                    station_id,
                    barcode,
                    barcode,
                    product_instance_id,
                    product_instance_id,
                ),
            ).fetchall()
            conn.execute(
                """
                UPDATE scan_records SET is_cancelled = 1, cancelled_at = ?
                WHERE project_id = ? AND station_id = ?
                  AND is_main_barcode = 1 AND is_cancelled = 0
                  AND (barcode = ? OR barcode_used = ?
                       OR (? IS NOT NULL AND product_instance_id = ?))
                """,
                (
                    now_text(),
                    project_id,
                    station_id,
                    barcode,
                    barcode,
                    product_instance_id,
                    product_instance_id,
                ),
            )
            affected_record_ids.extend(
                f"scan_record:{row['id']}" for row in scan_rows
            )
            old_record_id = record["id"] if record else scan_record["id"]
            matched_step_id = (
                scan_record["step_id"] if scan_record else step_id
            )
            cancel_type = "main_barcode"
        else:
            params = [project_id, station_id, barcode]
            product_clause = ""
            if product_instance_id is not None:
                product_clause = " AND product_instance_id = ?"
                params.append(product_instance_id)
            record = conn.execute(
                f"""
                SELECT id, project_id, station_id, step_id,
                       product_instance_id
                FROM scan_records
                WHERE project_id = ? AND station_id = ?
                  AND barcode = ? AND is_main_barcode = 0 AND is_cancelled = 0
                  AND result IN ('完成', 'OK')
                  {product_clause}
                ORDER BY id DESC LIMIT 1
                """,
                tuple(params),
            ).fetchone()
            if not record:
                reason = "待取消条码不属于本工位"
                if product_instance_id is not None or current_main_barcode:
                    reason = "待取消条码不属于当前工位或当前产品"
                cancel_mismatch(reason)
            conn.execute(
                """
                UPDATE scan_records
                SET is_cancelled = 1, cancelled_at = ?
                WHERE id = ?
                """,
                (now_text(), record["id"]),
            )
            old_record_id = record["id"]
            matched_step_id = record["step_id"]
            cancel_type = "non_main_barcode"
            affected_record_ids.append(f"scan_record:{record['id']}")
            logging.info(
                "取消条码匹配当前工位记录 id=%s station_id=%s step_id=%s "
                "product_instance_id=%s",
                record["id"],
                record["station_id"],
                record["step_id"],
                record["product_instance_id"],
            )
        cursor = conn.execute(
            """
            INSERT INTO barcode_cancel_logs
            (project_id, station_id, step_id, product_instance_id, barcode,
             cancel_type, old_record_id, operator, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                station_id,
                matched_step_id,
                product_instance_id,
                barcode,
                cancel_type,
                old_record_id,
                operator,
                now_text(),
            ),
        )
        logging.info(
            "取消条码完成 barcode=%s cancel_type=%s affected=%s "
            "cancel_log_id=%s",
            barcode,
            cancel_type,
            affected_record_ids,
            cursor.lastrowid,
        )
    return {
        "ok": True,
        "cancel_type": cancel_type,
        "matched_step_id": matched_step_id,
        "old_record_id": old_record_id,
        "log_id": cursor.lastrowid,
    }


def report_degrade_mode(payload):
    action = str(payload.get("action") or "").strip()
    if action not in {"enabled", "disabled"}:
        raise ValueError("降级模式动作不正确")
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO degrade_mode_logs
            (project_id, station_id, client_id, operator, action, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(payload.get("project_id") or 0) or None,
                int(payload.get("station_id") or 0) or None,
                payload.get("client_id", ""),
                payload.get("operator", "管理员"),
                action,
                payload.get("reason", ""),
                now_text(),
            ),
        )
    return {"ok": True, "id": cursor.lastrowid}


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
        duplicate = conn.execute(
            """
            SELECT 1 FROM station_completions
            WHERE project_id = ? AND station_id = ?
              AND (barcode = ? OR product_instance_id = ?)
            """,
            (project_id, station_id, barcode, product_instance_id),
        ).fetchone()
        if duplicate:
            raise ValueError("当前主条码已在本工位扫码/完成，禁止重复扫码。")
        conn.execute(
            """
            INSERT INTO station_completions
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
             step_id, step, result, note, is_main_barcode, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                station_id,
                barcode,
                product_instance_id,
                payload.get("barcode_used") or barcode,
                None,
                "工位完成",
                "完成",
                "桌面端上报",
                1,
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
        is_main = bool(payload.get("is_main_barcode"))
        enforce_unique = bool(payload.get("is_main_barcode")) or str(
            payload.get("step_type") or ""
        ) == SCAN_TYPE
        if (
            ids
            and payload.get("result", "记录") in {"完成", "OK"}
            and enforce_unique
            and not bool(payload.get("skip_validation"))
        ):
            validation = _validate_barcode_use(
                conn,
                {
                    **payload,
                    "station_id": ids["station_id"],
                    "is_main_barcode": is_main,
                },
            )
            if not validation["allowed"]:
                raise ValueError(validation["message"])
        conn.execute(
            """
            INSERT INTO scan_records
            (project_id, station_id, barcode, product_instance_id, barcode_used,
             step_id, step, result, note, is_main_barcode, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ids["project_id"] if ids else None,
                ids["station_id"] if ids else None,
                barcode,
                int(payload.get("product_instance_id") or 0) or None,
                payload.get("barcode_used") or barcode,
                int(payload.get("step_id") or 0) or None,
                payload.get("step", ""),
                payload.get("result", "记录"),
                payload.get("note", ""),
                int(is_main),
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


def add_plc_magnet_log(payload):
    with get_conn() as conn:
        project_id, station_id = record_project_station_ids(conn, payload)
        cursor = conn.execute(
            """
            INSERT INTO plc_magnet_logs
            (project_id, station_id, step_id, product_barcode,
             plc_ip, plc_db, left_flux, left_polarity, left_result,
             right_flux, right_polarity, right_result, raw_hex,
             started_at, finished_at, result, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                station_id,
                int(payload.get("step_id") or 0) or None,
                payload.get("product_barcode")
                or payload.get("main_barcode", ""),
                payload.get("plc_ip", ""),
                int(payload.get("plc_db") or 221),
                payload.get("left_flux"),
                payload.get("left_polarity"),
                payload.get("left_result"),
                payload.get("right_flux"),
                payload.get("right_polarity"),
                payload.get("right_result"),
                payload.get("raw_hex", ""),
                payload.get("started_at") or now_text(),
                payload.get("finished_at") or now_text(),
                payload.get("result", "ERROR"),
                payload.get("error_message", ""),
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
        "client_update_files",
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


def ensure_client_updates_dir():
    try:
        CLIENT_UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        raise ValueError(
            f"更新包目录无写入权限：{CLIENT_UPDATES_DIR}"
        ) from exc
    except OSError as exc:
        raise ValueError(
            f"无法创建更新包目录 {CLIENT_UPDATES_DIR}：{exc}"
        ) from exc
    if not os.access(CLIENT_UPDATES_DIR, os.W_OK):
        raise ValueError(f"更新包目录无写入权限：{CLIENT_UPDATES_DIR}")
    return CLIENT_UPDATES_DIR


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
        file_rows = conn.execute(
            "SELECT * FROM client_update_files ORDER BY uploaded_at DESC, id DESC"
        ).fetchall()
    files_by_version = {}
    for row in file_rows:
        item = row_to_dict(row)
        files_by_version.setdefault(item["version"], []).append(item)
    releases = [_release_row_to_dict(row) for row in rows]
    for release in releases:
        release["update_files"] = files_by_version.get(
            release["version"],
            [],
        )
    return releases


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
    stable = str(payload.get("stable", "1")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    force_update = str(
        payload.get("force_update", "0")
    ).strip().lower() in {"1", "true", "yes", "on"}
    min_required_version = str(payload.get("min_required_version", "")).strip()
    release_dir = _safe_release_dir(version)
    try:
        release_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        raise ValueError(f"版本发布目录无写入权限：{release_dir}") from exc
    update_dir = ensure_client_updates_dir()
    uploaded_by = str(payload.get("_uploaded_by") or "").strip()
    remark = str(payload.get("remark") or title or "").strip()

    def store_zip(key, expected_executable):
        file_obj = (files or {}).get(key)
        if not file_obj:
            return None
        original_name = str(
            payload.get(f"{key}_filename") or ""
        ).strip()
        if not original_name.lower().endswith(".zip"):
            logging.warning(
                "客户端更新上传拒绝 user=%s original=%s zip_valid=false reason=扩展名不是zip",
                uploaded_by,
                original_name,
            )
            raise ValueError("只支持 ZIP 更新包")
        temp_path = update_dir / (
            f".uploading_{os.getpid()}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.zip"
        )
        package_path = None
        file_size = 0
        try:
            if hasattr(file_obj, "seek"):
                file_obj.seek(0)
            with temp_path.open("wb") as target:
                while True:
                    chunk = file_obj.read(1024 * 1024)
                    if not chunk:
                        break
                    file_size += len(chunk)
                    if file_size > MAX_CLIENT_UPDATE_FILE_BYTES:
                        raise ValueError("文件过大，请检查上传限制")
                    target.write(chunk)
            if file_size == 0:
                raise ValueError("上传文件为空")
            if not zipfile.is_zipfile(temp_path):
                raise ValueError("只支持 ZIP 更新包")
            package_sha256 = _sha256_file(temp_path)
            safe_version = "".join(
                char if char.isalnum() or char in ".-_" else "_"
                for char in version
            )
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
            stored_name = (
                f"client_update_{safe_version}_{key}_{package_sha256[:8]}_{timestamp}.zip"
            )
            package_path = update_dir / stored_name
            temp_path.replace(package_path)

            extracted = {}
            with zipfile.ZipFile(package_path) as archive:
                members = {
                    Path(info.filename).name: info
                    for info in archive.infolist()
                    if not info.is_dir()
                }
                if expected_executable not in members:
                    raise ValueError(
                        f"ZIP中缺少 {expected_executable}"
                    )
                executable_names = [expected_executable]
                if (
                    key == "release_file"
                    and "QualityControlSystem_Debug.exe" in members
                ):
                    executable_names.append(
                        "QualityControlSystem_Debug.exe"
                    )
                for executable_name in executable_names:
                    target_path = release_dir / executable_name
                    with archive.open(members[executable_name]) as source:
                        with target_path.open("wb") as target:
                            shutil.copyfileobj(source, target)
                    extracted[executable_name] = {
                        "path": str(target_path),
                        "sha256": _sha256_file(target_path),
                    }
            logging.info(
                "客户端更新ZIP保存成功 user=%s original=%s size=%s dir=%s path=%s sha256=%s zip_valid=true",
                uploaded_by,
                original_name,
                file_size,
                update_dir,
                package_path,
                package_sha256,
            )
            return {
                "version": version,
                "original_name": original_name,
                "stored_name": stored_name,
                "file_path": str(package_path),
                "file_size": file_size,
                "sha256": package_sha256,
                "uploaded_by": uploaded_by,
                "uploaded_at": now_text(),
                "remark": remark,
                "extracted": extracted,
            }
        except PermissionError as exc:
            logging.exception(
                "客户端更新ZIP保存失败，目录无权限：%s",
                update_dir,
            )
            raise ValueError(
                f"更新包目录无写入权限：{update_dir}"
            ) from exc
        except Exception:
            logging.exception(
                "客户端更新ZIP保存失败 user=%s original=%s size=%s dir=%s",
                uploaded_by,
                original_name,
                file_size,
                update_dir,
            )
            raise
        finally:
            if temp_path.exists():
                temp_path.unlink()
            if package_path is not None and package_path.exists():
                if "package_sha256" not in locals() or not extracted:
                    package_path.unlink()

    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM client_releases WHERE version = ?", (version,)).fetchone()
        uploaded_packages = []
        release_package = store_zip(
            "release_file",
            "QualityControlSystem.exe",
        )
        debug_package = store_zip(
            "debug_file",
            "QualityControlSystem_Debug.exe",
        )
        uploaded_packages.extend(
            package
            for package in (release_package, debug_package)
            if package
        )
        release_extracted = (
            release_package.get("extracted", {}) if release_package else {}
        )
        debug_extracted = (
            debug_package.get("extracted", {}) if debug_package else {}
        )
        release_data = release_extracted.get("QualityControlSystem.exe")
        debug_data = debug_extracted.get(
            "QualityControlSystem_Debug.exe"
        ) or release_extracted.get("QualityControlSystem_Debug.exe")
        release_file_path = (
            release_data["path"] if release_data else
            (existing["release_file_path"] if existing else "")
        )
        debug_file_path = (
            debug_data["path"] if debug_data else
            (existing["debug_file_path"] if existing else "")
        )
        release_sha256 = (
            release_data["sha256"] if release_data else
            (existing["release_sha256"] if existing else "")
        )
        debug_sha256 = (
            debug_data["sha256"] if debug_data else
            (existing["debug_sha256"] if existing else "")
        )
        s7_tool_file_path = existing["s7_tool_file_path"] if existing else ""
        s7_tool_sha256 = existing["s7_tool_sha256"] if existing else ""
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
        for package in uploaded_packages:
            conn.execute(
                """
                INSERT INTO client_update_files
                (version, original_name, stored_name, file_path, file_size,
                 sha256, uploaded_by, uploaded_at, remark)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    package["version"],
                    package["original_name"],
                    package["stored_name"],
                    package["file_path"],
                    package["file_size"],
                    package["sha256"],
                    package["uploaded_by"],
                    package["uploaded_at"],
                    package["remark"],
                ),
            )
    return {
        "ok": True,
        "version": version,
        "files": [
            {
                key: value
                for key, value in package.items()
                if key != "extracted"
            }
            for package in uploaded_packages
        ],
    }


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
