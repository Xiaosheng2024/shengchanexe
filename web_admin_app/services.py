from urllib.parse import unquote

from web_admin_app.database import get_conn, now_text, row_to_dict


def list_projects():
    projects = []
    with get_conn() as conn:
        for project in conn.execute("SELECT * FROM projects ORDER BY id"):
            stations = conn.execute(
                "SELECT name FROM stations WHERE project_id = ? ORDER BY id",
                (project["id"],),
            ).fetchall()
            projects.append({"name": project["name"], "stations": [row["name"] for row in stations]})
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
        cursor = conn.execute("INSERT INTO projects (name, created_at) VALUES (?, ?)", (name, now_text()))
        return {"id": cursor.lastrowid, "name": name}


def update_project(project_id, payload):
    name = payload.get("name", "").strip()
    if not name:
        raise ValueError("项目名称不能为空")
    with get_conn() as conn:
        conn.execute("UPDATE projects SET name = ? WHERE id = ?", (name, project_id))
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
        station_rows = conn.execute("SELECT id FROM stations WHERE project_id = ?", (project_id,)).fetchall()
        station_ids = [row["id"] for row in station_rows]
        for station_id in station_ids:
            delete_station_with_conn(conn, station_id)
        conn.execute("DELETE FROM scan_records WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM station_completions WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))


def delete_station(station_id):
    with get_conn() as conn:
        delete_station_with_conn(conn, station_id)


def delete_station_with_conn(conn, station_id):
    conn.execute("DELETE FROM steps WHERE station_id = ?", (station_id,))
    conn.execute("DELETE FROM scan_records WHERE station_id = ?", (station_id,))
    conn.execute("DELETE FROM station_completions WHERE station_id = ?", (station_id,))
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
    if step_type not in ("扫码", "螺丝"):
        raise ValueError("功能只能是扫码或螺丝")
    with get_conn() as conn:
        if is_main_barcode:
            clear_station_main_barcode(conn, station_id)
        cursor = conn.execute(
            """
            INSERT INTO steps
            (station_id, step_order, name, type, required_count, barcode_start, barcode_end, expected_content, is_main_barcode, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                now_text(),
            ),
        )
        validate_station_main_barcode(conn, station_id)
        return {"id": cursor.lastrowid}


def update_step(step_id, payload):
    name = payload.get("name", "").strip()
    step_type = payload.get("type", "扫码")
    station_id = int(payload.get("station_id", 0))
    is_main_barcode = normalize_main_barcode(payload, step_type)
    if not station_id or not name:
        raise ValueError("工位和工序名称不能为空")
    if step_type not in ("扫码", "螺丝"):
        raise ValueError("功能只能是扫码或螺丝")
    with get_conn() as conn:
        old_row = conn.execute("SELECT station_id FROM steps WHERE id = ?", (step_id,)).fetchone()
        if is_main_barcode:
            clear_station_main_barcode(conn, station_id)
        conn.execute(
            """
            UPDATE steps
            SET station_id = ?, step_order = ?, name = ?, type = ?, required_count = ?,
                barcode_start = ?, barcode_end = ?, expected_content = ?, is_main_barcode = ?
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
                step_id,
            ),
        )
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


def get_station_config(path):
    parts = path.split("/")
    project_name = unquote(parts[3])
    station_name = unquote(parts[5])
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT stations.id AS station_id, projects.name AS project_name, stations.name AS station_name
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
        "product_name": f"{project_name} - {station_name}",
        "steps": [
            {
                "name": step["name"],
                "type": step["type"],
                "required_count": step["required_count"],
                "barcode_start": step["barcode_start"],
                "barcode_end": step["barcode_end"],
                "expected_content": step["expected_content"],
                "is_main_barcode": bool(step["is_main_barcode"]),
            }
            for step in steps
        ],
    }


def normalize_main_barcode(payload, step_type: str) -> bool:
    is_main_barcode = bool(payload.get("is_main_barcode", False))
    if is_main_barcode and step_type != "扫码":
        raise ValueError("只有扫码工序可以设置为主条码")
    return is_main_barcode


def clear_station_main_barcode(conn, station_id: int):
    conn.execute("UPDATE steps SET is_main_barcode = 0 WHERE station_id = ?", (station_id,))


def validate_station_main_barcode(conn, station_id: int):
    conn.execute(
        "UPDATE steps SET is_main_barcode = 0 WHERE station_id = ? AND type != ?",
        (station_id, "扫码"),
    )
    scan_count = conn.execute(
        "SELECT COUNT(*) AS total FROM steps WHERE station_id = ? AND type = ?",
        (station_id, "扫码"),
    ).fetchone()["total"]
    if scan_count == 0:
        return
    main_count = conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM steps
        WHERE station_id = ? AND type = ? AND is_main_barcode = 1
        """,
        (station_id, "扫码"),
    ).fetchone()["total"]
    if main_count == 0:
        raise ValueError("每个工位必须配置一个主条码扫码工序")
    if main_count > 1:
        raise ValueError("每个工位只能配置一个主条码扫码工序")


def ensure_station_has_main_barcode(conn, station_id: int):
    conn.execute(
        "UPDATE steps SET is_main_barcode = 0 WHERE station_id = ? AND type != ?",
        (station_id, "扫码"),
    )
    scan_count = conn.execute(
        "SELECT COUNT(*) AS total FROM steps WHERE station_id = ? AND type = ?",
        (station_id, "扫码"),
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
    first_scan = conn.execute(
        "SELECT id FROM steps WHERE station_id = ? AND type = ? ORDER BY step_order, id LIMIT 1",
        (station_id, "扫码"),
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
    project = query.get("project", [""])[0]
    barcode = query.get("barcode", [""])[0]
    previous_station = query.get("previous_station", [""])[0]
    with get_conn() as conn:
        ids = find_project_station(conn, project, previous_station)
        if not ids:
            return {"completed": False}
        row = conn.execute(
            """
            SELECT 1 FROM station_completions
            WHERE project_id = ? AND station_id = ? AND barcode = ?
            """,
            (ids["project_id"], ids["station_id"], barcode),
        ).fetchone()
    return {"completed": row is not None}


def add_station_completion(payload):
    project = payload.get("project", "")
    station = payload.get("station", "")
    barcode = payload.get("barcode", "")
    completed_at = payload.get("completed_at") or now_text()
    if not project or not station or not barcode:
        raise ValueError("项目、工位、条码不能为空")
    with get_conn() as conn:
        ids = find_project_station(conn, project, station)
        if not ids:
            raise ValueError("项目或工位不存在")
        conn.execute(
            """
            INSERT OR REPLACE INTO station_completions
            (project_id, station_id, barcode, completed_at)
            VALUES (?, ?, ?, ?)
            """,
            (ids["project_id"], ids["station_id"], barcode, completed_at),
        )
        conn.execute(
            """
            INSERT INTO scan_records
            (project_id, station_id, barcode, step, result, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (ids["project_id"], ids["station_id"], barcode, "工位完成", "完成", "桌面端上报", completed_at),
        )
    return {"ok": True}


def add_scan_record(payload):
    project = payload.get("project", "")
    station = payload.get("station", "")
    barcode = payload.get("barcode", "")
    if not barcode:
        raise ValueError("条码不能为空")
    with get_conn() as conn:
        ids = find_project_station(conn, project, station) if project and station else None
        conn.execute(
            """
            INSERT INTO scan_records
            (project_id, station_id, barcode, step, result, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ids["project_id"] if ids else None,
                ids["station_id"] if ids else None,
                barcode,
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
    sql += " ORDER BY scan_records.created_at DESC LIMIT 500"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "project": row["project"] or "",
            "station": row["station"] or "",
            "barcode": row["barcode"],
            "step": row["step"],
            "result": row["result"],
            "note": row["note"],
        }
        for row in rows
    ]
