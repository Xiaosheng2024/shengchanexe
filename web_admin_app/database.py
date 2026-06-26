import configparser
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

try:
    import psycopg2
    import psycopg2.extras
except ImportError:  # pragma: no cover - optional until PostgreSQL is used
    psycopg2 = None

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "quality_control.db"
CONFIG_PATH = ROOT_DIR / "config.ini"


def load_database_config():
    config = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        config.read(CONFIG_PATH, encoding="utf-8")
    if "DATABASE" not in config:
        return {"type": "sqlite", "path": str(DB_PATH)}
    section = config["DATABASE"]
    db_type = section.get("type", "postgresql").strip().lower()
    if db_type == "sqlite":
        return {"type": "sqlite", "path": section.get("path", str(DB_PATH))}
    return {
        "type": "postgresql",
        "host": section.get("host", "127.0.0.1"),
        "port": section.getint("port", fallback=5432),
        "database": section.get("database", "mes_db"),
        "user": section.get("user", "mes_user"),
        "password": section.get("password", "mes_password"),
    }


def now_text():
    return datetime.now().isoformat(timespec="seconds")


def row_to_dict(row):
    if not row:
        return None
    return {key: serialize_value(value) for key, value in dict(row).items()}


def serialize_value(value):
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return value


class CursorAdapter:
    def __init__(self, cursor, lastrowid=None):
        self.cursor = cursor
        self.lastrowid = lastrowid if lastrowid is not None else getattr(cursor, "lastrowid", None)

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def __iter__(self):
        return iter(self.fetchall())


class DatabaseConnection:
    def __init__(self, raw_conn, db_type):
        self.raw_conn = raw_conn
        self.db_type = db_type

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.raw_conn.commit()
        else:
            self.raw_conn.rollback()
        self.raw_conn.close()

    def execute(self, sql, params=None):
        params = tuple(params or ())
        if self.db_type == "sqlite":
            cursor = self.raw_conn.execute(sql, params)
            return CursorAdapter(cursor)
        return self._execute_postgres(sql, params)

    def executemany(self, sql, seq_of_params):
        if self.db_type == "sqlite":
            cursor = self.raw_conn.executemany(sql, seq_of_params)
            return CursorAdapter(cursor)
        converted = convert_placeholders(sql)
        with self.raw_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.executemany(converted, seq_of_params)
            return CursorAdapter(cursor)

    def executescript(self, sql_script):
        if self.db_type == "sqlite":
            self.raw_conn.executescript(sql_script)
            return
        with self.raw_conn.cursor() as cursor:
            cursor.execute(sql_script)

    def _execute_postgres(self, sql, params):
        converted = convert_placeholders(sql)
        returning_id = False
        if needs_returning_id(converted):
            converted = converted.rstrip().rstrip(";") + " RETURNING id"
            returning_id = True
        with self.raw_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(converted, params)
            rows = None
            lastrowid = None
            if returning_id:
                row = cursor.fetchone()
                lastrowid = row["id"] if row else None
                rows = []
            elif cursor.description:
                rows = cursor.fetchall()
            return CursorAdapter(BufferedCursor(rows), lastrowid=lastrowid)


class BufferedCursor:
    def __init__(self, rows):
        self.rows = rows if rows is not None else []
        self.index = 0
        self.lastrowid = None

    def fetchone(self):
        if self.index >= len(self.rows):
            return None
        row = self.rows[self.index]
        self.index += 1
        return row

    def fetchall(self):
        if self.index >= len(self.rows):
            return []
        rows = self.rows[self.index :]
        self.index = len(self.rows)
        return rows


def convert_placeholders(sql):
    return sql.replace("?", "%s")


def needs_returning_id(sql):
    normalized = re.sub(r"\s+", " ", sql.strip().lower())
    if " returning " in normalized:
        return False
    return normalized.startswith(
        (
            "insert into projects ",
            "insert into stations ",
            "insert into steps ",
            "insert into station_work_records ",
            "insert into step_work_records ",
            "insert into screw_action_records ",
        )
    )


def get_conn():
    config = load_database_config()
    if config["type"] == "sqlite":
        path = Path(config["path"])
        if not path.is_absolute():
            path = ROOT_DIR / path
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return DatabaseConnection(conn, "sqlite")
    if psycopg2 is None:
        raise RuntimeError("当前配置使用 PostgreSQL，请先安装 psycopg2-binary")
    conn = psycopg2.connect(
        host=config["host"],
        port=config["port"],
        dbname=config["database"],
        user=config["user"],
        password=config["password"],
    )
    return DatabaseConnection(conn, "postgresql")


def get_database_type():
    return load_database_config()["type"]


def execute(sql, params=None):
    with get_conn() as conn:
        return conn.execute(sql, params)


def fetch_one(sql, params=None):
    with get_conn() as conn:
        return conn.execute(sql, params).fetchone()


def fetch_all(sql, params=None):
    with get_conn() as conn:
        return conn.execute(sql, params).fetchall()


@contextmanager
def transaction():
    with get_conn() as conn:
        yield conn


def init_db():
    with get_conn() as conn:
        if conn.db_type == "postgresql":
            create_postgresql_schema(conn)
        else:
            create_sqlite_schema(conn)
            migrate_sqlite_db(conn)
        row = conn.execute("SELECT COUNT(*) AS total FROM projects").fetchone()
        if row["total"] == 0:
            seed_default_data(conn)
        ensure_default_main_barcodes(conn)


def create_sqlite_schema(conn):
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
    create_traceability_schema(conn)


def create_postgresql_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stations (
            id SERIAL PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            name TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL,
            UNIQUE(project_id, name)
        );
        CREATE TABLE IF NOT EXISTS steps (
            id SERIAL PRIMARY KEY,
            station_id INTEGER NOT NULL REFERENCES stations(id),
            step_order INTEGER NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            required_count INTEGER NOT NULL DEFAULT 0,
            barcode_start INTEGER NOT NULL DEFAULT 1,
            barcode_end INTEGER NOT NULL DEFAULT 7,
            expected_content TEXT NOT NULL DEFAULT '',
            is_main_barcode INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL
        );
        CREATE TABLE IF NOT EXISTS station_completions (
            id BIGSERIAL PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            station_id INTEGER NOT NULL REFERENCES stations(id),
            barcode TEXT NOT NULL,
            completed_at TIMESTAMP NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_station_completions_project_station_barcode
            ON station_completions(project_id, station_id, barcode);
        CREATE TABLE IF NOT EXISTS scan_records (
            id BIGSERIAL PRIMARY KEY,
            project_id INTEGER,
            station_id INTEGER,
            barcode TEXT NOT NULL,
            step TEXT,
            result TEXT NOT NULL,
            note TEXT,
            created_at TIMESTAMP NOT NULL
        );
        """
    )
    create_traceability_schema(conn)


def create_traceability_schema(conn):
    if conn.db_type == "postgresql":
        id_type = "BIGSERIAL PRIMARY KEY"
        ts_type = "TIMESTAMP"
        bool_type = "BOOLEAN DEFAULT false"
        current_ts = "CURRENT_TIMESTAMP"
    else:
        id_type = "INTEGER PRIMARY KEY AUTOINCREMENT"
        ts_type = "TEXT"
        bool_type = "INTEGER DEFAULT 0"
        current_ts = "CURRENT_TIMESTAMP"
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS station_work_records (
            id {id_type},
            project_id INTEGER NOT NULL,
            station_id INTEGER NOT NULL,
            main_barcode TEXT NOT NULL,
            product_name TEXT,
            station_name TEXT,
            start_time {ts_type} NOT NULL,
            end_time {ts_type},
            work_duration_seconds INTEGER DEFAULT 0,
            total_steps INTEGER DEFAULT 0,
            completed_steps INTEGER DEFAULT 0,
            screw_required_count INTEGER DEFAULT 0,
            screw_ok_count INTEGER DEFAULT 0,
            screw_ng_count INTEGER DEFAULT 0,
            result TEXT NOT NULL DEFAULT '进行中',
            operator TEXT,
            note TEXT,
            created_at {ts_type} NOT NULL DEFAULT {current_ts},
            updated_at {ts_type} NOT NULL DEFAULT {current_ts}
        );
        CREATE TABLE IF NOT EXISTS step_work_records (
            id {id_type},
            station_work_id BIGINT,
            project_id INTEGER NOT NULL,
            station_id INTEGER NOT NULL,
            main_barcode TEXT NOT NULL,
            step_name TEXT NOT NULL,
            step_type TEXT NOT NULL,
            step_order INTEGER NOT NULL,
            start_time {ts_type} NOT NULL,
            end_time {ts_type},
            duration_seconds INTEGER DEFAULT 0,
            barcode TEXT,
            scan_result TEXT,
            screw_required_count INTEGER DEFAULT 0,
            screw_ok_count INTEGER DEFAULT 0,
            screw_ng_count INTEGER DEFAULT 0,
            result TEXT NOT NULL DEFAULT '进行中',
            note TEXT,
            created_at {ts_type} NOT NULL DEFAULT {current_ts}
        );
        CREATE TABLE IF NOT EXISTS screw_action_records (
            id {id_type},
            station_work_id BIGINT,
            step_work_id BIGINT,
            project_id INTEGER NOT NULL,
            station_id INTEGER NOT NULL,
            main_barcode TEXT NOT NULL,
            step_name TEXT,
            screw_index INTEGER,
            required_count INTEGER,
            status_value INTEGER,
            trigger_value INTEGER,
            direction_value INTEGER,
            result TEXT NOT NULL,
            is_counted {bool_type},
            ng_reason TEXT,
            created_at {ts_type} NOT NULL DEFAULT {current_ts}
        );
        CREATE INDEX IF NOT EXISTS idx_station_work_barcode ON station_work_records(main_barcode);
        CREATE INDEX IF NOT EXISTS idx_station_work_project_station_time ON station_work_records(project_id, station_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_station_work_result ON station_work_records(result);
        CREATE INDEX IF NOT EXISTS idx_step_work_barcode ON step_work_records(main_barcode);
        CREATE INDEX IF NOT EXISTS idx_step_work_station_step_time ON step_work_records(project_id, station_id, step_name, created_at);
        CREATE INDEX IF NOT EXISTS idx_step_work_created_at ON step_work_records(created_at);
        CREATE INDEX IF NOT EXISTS idx_screw_action_barcode ON screw_action_records(main_barcode);
        CREATE INDEX IF NOT EXISTS idx_screw_action_project_station_time ON screw_action_records(project_id, station_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_screw_action_result ON screw_action_records(result);
        """
    )


def migrate_sqlite_db(conn):
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(steps)").fetchall()]
    if "is_main_barcode" not in columns:
        conn.execute("ALTER TABLE steps ADD COLUMN is_main_barcode INTEGER NOT NULL DEFAULT 0")


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
