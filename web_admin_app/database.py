import sqlite3
from datetime import datetime
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent.parent / "quality_control.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS stations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(project_id, name),
                FOREIGN KEY(project_id) REFERENCES projects(id)
            );
            CREATE TABLE IF NOT EXISTS steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id INTEGER NOT NULL,
                step_order INTEGER NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                required_count INTEGER NOT NULL DEFAULT 0,
                barcode_start INTEGER NOT NULL DEFAULT 1,
                barcode_end INTEGER NOT NULL DEFAULT 7,
                expected_content TEXT NOT NULL DEFAULT '',
                is_main_barcode INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(station_id) REFERENCES stations(id)
            );
            CREATE TABLE IF NOT EXISTS station_completions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                station_id INTEGER NOT NULL,
                barcode TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                UNIQUE(project_id, station_id, barcode)
            );
            CREATE TABLE IF NOT EXISTS scan_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                station_id INTEGER,
                barcode TEXT NOT NULL,
                step TEXT,
                result TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        migrate_db(conn)
        row = conn.execute("SELECT COUNT(*) AS total FROM projects").fetchone()
        if row["total"] == 0:
            seed_default_data(conn)
        ensure_default_main_barcodes(conn)


def migrate_db(conn):
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(steps)").fetchall()]
    if "is_main_barcode" not in columns:
        conn.execute("ALTER TABLE steps ADD COLUMN is_main_barcode INTEGER NOT NULL DEFAULT 0")


def now_text():
    return datetime.now().isoformat(timespec="seconds")


def seed_default_data(conn):
    created_at = now_text()
    cursor = conn.execute("INSERT INTO projects (name, created_at) VALUES (?, ?)", ("默认项目", created_at))
    project_id = cursor.lastrowid
    for index in range(1, 10):
        cursor = conn.execute(
            "INSERT INTO stations (project_id, name, created_at) VALUES (?, ?, ?)",
            (project_id, f"工位{index}", created_at),
        )
        station_id = cursor.lastrowid
        default_steps = [
            (1, "扫码A零件", "扫码", 0, 1, 1, "A", 1),
            (2, "扫码B零件条码", "扫码", 0, 1, 1, "B", 0),
            (3, "打螺丝10颗", "螺丝", 10, 1, 7, "", 0),
            (4, "扫码C零件", "扫码", 0, 1, 1, "C", 0),
        ]
        conn.executemany(
            """
            INSERT INTO steps
            (station_id, step_order, name, type, required_count, barcode_start, barcode_end, expected_content, is_main_barcode, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(station_id, *step, created_at) for step in default_steps],
        )


def ensure_default_main_barcodes(conn):
    station_rows = conn.execute("SELECT id FROM stations").fetchall()
    for station in station_rows:
        main_count = conn.execute(
            "SELECT COUNT(*) AS total FROM steps WHERE station_id = ? AND is_main_barcode = 1",
            (station["id"],),
        ).fetchone()["total"]
        if main_count:
            continue
        first_scan = conn.execute(
            "SELECT id FROM steps WHERE station_id = ? AND type = ? ORDER BY step_order, id LIMIT 1",
            (station["id"], "扫码"),
        ).fetchone()
        if first_scan:
            conn.execute("UPDATE steps SET is_main_barcode = 1 WHERE id = ?", (first_scan["id"],))


def row_to_dict(row):
    return dict(row) if row else None
