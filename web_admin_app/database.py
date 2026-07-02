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

PLC_STEP_COLUMNS = {
    "plc_ip": "TEXT NOT NULL DEFAULT '10.162.86.65'",
    "plc_rack": "INTEGER NOT NULL DEFAULT 0",
    "plc_slot": "INTEGER NOT NULL DEFAULT 1",
    "plc_barcode_db": "INTEGER NOT NULL DEFAULT 201",
    "plc_barcode_offset": "INTEGER NOT NULL DEFAULT 800",
    "plc_barcode_length": "INTEGER NOT NULL DEFAULT 40",
    "plc_barcode1_db": "INTEGER NOT NULL DEFAULT 201",
    "plc_barcode1_offset": "INTEGER NOT NULL DEFAULT 800",
    "plc_barcode1_length": "INTEGER NOT NULL DEFAULT 40",
    "plc_barcode2_db": "INTEGER NOT NULL DEFAULT 201",
    "plc_barcode2_offset": "INTEGER NOT NULL DEFAULT 840",
    "plc_barcode2_length": "INTEGER NOT NULL DEFAULT 40",
    "plc_parts_ok_db": "INTEGER NOT NULL DEFAULT 221",
    "plc_parts_ok_offset": "INTEGER NOT NULL DEFAULT 358",
    "plc_parts_ok_type": "TEXT NOT NULL DEFAULT 'int'",
    "plc_trigger_mode": "TEXT NOT NULL DEFAULT 'barcode_changed_then_parts_ok_increment'",
    "plc_use_barcode_index": "INTEGER NOT NULL DEFAULT 1",
    "plc_barcode_encoding": "TEXT NOT NULL DEFAULT 'ascii'",
    "plc_barcode_strip_null": "INTEGER NOT NULL DEFAULT 1",
    "plc_barcode_strip_space": "INTEGER NOT NULL DEFAULT 1",
    "plc_timeout_seconds": "INTEGER NOT NULL DEFAULT 3",
    "plc_poll_interval_ms": "INTEGER NOT NULL DEFAULT 500",
    "plc_barcode_wait_ok_timeout_seconds": "INTEGER NOT NULL DEFAULT 30",
}
MAGNET_STEP_COLUMNS = {
    "plc_magnet_config": "TEXT NOT NULL DEFAULT '{}'",
}

FLOW_STEP_COLUMNS = {
    "switch_require_old": "INTEGER NOT NULL DEFAULT 1",
    "switch_require_new": "INTEGER NOT NULL DEFAULT 1",
    "switch_set_current": "INTEGER NOT NULL DEFAULT 1",
    "switch_disable_old": "INTEGER NOT NULL DEFAULT 1",
    "bind_child_project_id": "INTEGER",
    "bind_child_material_type": "TEXT NOT NULL DEFAULT ''",
    "bind_child_route": "TEXT NOT NULL DEFAULT ''",
    "bind_required_count": "INTEGER NOT NULL DEFAULT 1",
    "bind_required_station_ids": "TEXT NOT NULL DEFAULT '[]'",
    "bind_require_parent_switch": "INTEGER NOT NULL DEFAULT 1",
    "bind_allow_duplicate": "INTEGER NOT NULL DEFAULT 0",
    "bind_allow_unbind": "INTEGER NOT NULL DEFAULT 0",
}
STATION_ROUTE_COLUMNS = {
    "route_name": "TEXT NOT NULL DEFAULT 'A主线'",
    "route_order": "INTEGER NOT NULL DEFAULT 0",
    "station_role": "TEXT NOT NULL DEFAULT '普通工位'",
    "material_type": "TEXT NOT NULL DEFAULT ''",
}
FLOW_STEP_BOOLEAN_COLUMNS = {
    "switch_require_old",
    "switch_require_new",
    "switch_set_current",
    "switch_disable_old",
    "bind_require_parent_switch",
    "bind_allow_duplicate",
    "bind_allow_unbind",
}

FLOW_RECORD_COLUMNS = {
    "station_completions": {
        "product_instance_id": "BIGINT",
        "barcode_used": "TEXT",
    },
    "scan_records": {
        "product_instance_id": "BIGINT",
        "barcode_used": "TEXT",
        "step_id": "BIGINT",
        "is_main_barcode": "INTEGER NOT NULL DEFAULT 0",
        "is_cancelled": "INTEGER NOT NULL DEFAULT 0",
        "cancelled_at": "TEXT",
    },
    "station_work_records": {
        "product_instance_id": "BIGINT",
        "barcode_used": "TEXT",
    },
    "step_work_records": {
        "product_instance_id": "BIGINT",
        "barcode_used": "TEXT",
    },
    "screw_action_records": {
        "product_instance_id": "BIGINT",
        "barcode_used": "TEXT",
    },
}
PROJECT_FLOW_COLUMNS = {
    "material_code": "TEXT NOT NULL DEFAULT ''",
    "product_type": "TEXT NOT NULL DEFAULT ''",
}

CLIENT_RELEASE_COLUMNS = {
    "version": "TEXT NOT NULL UNIQUE",
    "title": "TEXT NOT NULL DEFAULT ''",
    "release_notes": "TEXT NOT NULL DEFAULT '[]'",
    "release_date": "TEXT NOT NULL",
    "stable": "INTEGER NOT NULL DEFAULT 1",
    "force_update": "INTEGER NOT NULL DEFAULT 0",
    "min_required_version": "TEXT NOT NULL DEFAULT ''",
    "release_file_path": "TEXT NOT NULL DEFAULT ''",
    "debug_file_path": "TEXT NOT NULL DEFAULT ''",
    "s7_tool_file_path": "TEXT NOT NULL DEFAULT ''",
    "release_sha256": "TEXT NOT NULL DEFAULT ''",
    "debug_sha256": "TEXT NOT NULL DEFAULT ''",
    "s7_tool_sha256": "TEXT NOT NULL DEFAULT ''",
    "created_at": "TEXT NOT NULL",
    "updated_at": "TEXT NOT NULL",
}


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
        "password": section.get("password", "change_me_random_password"),
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
            "insert into web_admin_users ",
            "insert into product_instances ",
            "insert into barcode_aliases ",
            "insert into barcode_switch_records ",
            "insert into material_bindings ",
            "insert into station_dependencies ",
            "insert into barcode_cancel_logs ",
            "insert into degrade_mode_logs ",
            "insert into client_update_files ",
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
            migrate_postgresql_db(conn)
        else:
            create_sqlite_schema(conn)
            migrate_sqlite_db(conn)
        row = conn.execute("SELECT COUNT(*) AS total FROM projects").fetchone()
        if row["total"] == 0:
            seed_default_data(conn)
        ensure_default_main_barcodes(conn)
        ensure_default_client_release_tables(conn)


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
            route_name TEXT NOT NULL DEFAULT 'A主线',
            route_order INTEGER NOT NULL DEFAULT 0,
            station_role TEXT NOT NULL DEFAULT '普通工位',
            material_type TEXT NOT NULL DEFAULT '',
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
            plc_ip TEXT NOT NULL DEFAULT '10.162.86.65',
            plc_rack INTEGER NOT NULL DEFAULT 0,
            plc_slot INTEGER NOT NULL DEFAULT 1,
            plc_barcode_db INTEGER NOT NULL DEFAULT 201,
            plc_barcode_offset INTEGER NOT NULL DEFAULT 800,
            plc_barcode_length INTEGER NOT NULL DEFAULT 40,
            plc_barcode1_db INTEGER NOT NULL DEFAULT 201,
            plc_barcode1_offset INTEGER NOT NULL DEFAULT 800,
            plc_barcode1_length INTEGER NOT NULL DEFAULT 40,
            plc_barcode2_db INTEGER NOT NULL DEFAULT 201,
            plc_barcode2_offset INTEGER NOT NULL DEFAULT 840,
            plc_barcode2_length INTEGER NOT NULL DEFAULT 40,
            plc_parts_ok_db INTEGER NOT NULL DEFAULT 221,
            plc_parts_ok_offset INTEGER NOT NULL DEFAULT 358,
            plc_parts_ok_type TEXT NOT NULL DEFAULT 'int',
            plc_trigger_mode TEXT NOT NULL DEFAULT 'barcode_changed_then_parts_ok_increment',
            plc_use_barcode_index INTEGER NOT NULL DEFAULT 1,
            plc_barcode_encoding TEXT NOT NULL DEFAULT 'ascii',
            plc_barcode_strip_null INTEGER NOT NULL DEFAULT 1,
            plc_barcode_strip_space INTEGER NOT NULL DEFAULT 1,
            plc_timeout_seconds INTEGER NOT NULL DEFAULT 3,
            plc_poll_interval_ms INTEGER NOT NULL DEFAULT 500,
            plc_barcode_wait_ok_timeout_seconds INTEGER NOT NULL DEFAULT 30,
            plc_magnet_config TEXT NOT NULL DEFAULT '{}',
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
    create_product_flow_schema(conn)


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
            route_name TEXT NOT NULL DEFAULT 'A主线',
            route_order INTEGER NOT NULL DEFAULT 0,
            station_role TEXT NOT NULL DEFAULT '普通工位',
            material_type TEXT NOT NULL DEFAULT '',
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
            plc_ip TEXT NOT NULL DEFAULT '10.162.86.65',
            plc_rack INTEGER NOT NULL DEFAULT 0,
            plc_slot INTEGER NOT NULL DEFAULT 1,
            plc_barcode_db INTEGER NOT NULL DEFAULT 201,
            plc_barcode_offset INTEGER NOT NULL DEFAULT 800,
            plc_barcode_length INTEGER NOT NULL DEFAULT 40,
            plc_barcode1_db INTEGER NOT NULL DEFAULT 201,
            plc_barcode1_offset INTEGER NOT NULL DEFAULT 800,
            plc_barcode1_length INTEGER NOT NULL DEFAULT 40,
            plc_barcode2_db INTEGER NOT NULL DEFAULT 201,
            plc_barcode2_offset INTEGER NOT NULL DEFAULT 840,
            plc_barcode2_length INTEGER NOT NULL DEFAULT 40,
            plc_parts_ok_db INTEGER NOT NULL DEFAULT 221,
            plc_parts_ok_offset INTEGER NOT NULL DEFAULT 358,
            plc_parts_ok_type TEXT NOT NULL DEFAULT 'int',
            plc_trigger_mode TEXT NOT NULL DEFAULT 'barcode_changed_then_parts_ok_increment',
            plc_use_barcode_index INTEGER NOT NULL DEFAULT 1,
            plc_barcode_encoding TEXT NOT NULL DEFAULT 'ascii',
            plc_barcode_strip_null INTEGER NOT NULL DEFAULT 1,
            plc_barcode_strip_space INTEGER NOT NULL DEFAULT 1,
            plc_timeout_seconds INTEGER NOT NULL DEFAULT 3,
            plc_poll_interval_ms INTEGER NOT NULL DEFAULT 500,
            plc_barcode_wait_ok_timeout_seconds INTEGER NOT NULL DEFAULT 30,
            plc_magnet_config TEXT NOT NULL DEFAULT '{}',
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
    create_product_flow_schema(conn)


def create_traceability_schema(conn):
    if conn.db_type == "postgresql":
        id_type = "BIGSERIAL PRIMARY KEY"
        ts_type = "TIMESTAMP"
        bool_type = "BOOLEAN DEFAULT false"
        bool_true_type = "BOOLEAN DEFAULT true"
        current_ts = "CURRENT_TIMESTAMP"
    else:
        id_type = "INTEGER PRIMARY KEY AUTOINCREMENT"
        ts_type = "TEXT"
        bool_type = "INTEGER DEFAULT 0"
        bool_true_type = "INTEGER DEFAULT 1"
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
            plc_barcode1 TEXT,
            plc_barcode2 TEXT,
            parts_ok_before INTEGER,
            parts_ok_after INTEGER,
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
        CREATE TABLE IF NOT EXISTS plc_magnet_logs (
            id {id_type},
            project_id INTEGER NOT NULL,
            station_id INTEGER NOT NULL,
            step_id INTEGER,
            product_barcode TEXT,
            plc_ip TEXT NOT NULL,
            plc_db INTEGER NOT NULL,
            left_flux REAL,
            left_polarity INTEGER,
            left_result INTEGER,
            right_flux REAL,
            right_polarity INTEGER,
            right_result INTEGER,
            raw_hex TEXT,
            started_at {ts_type},
            finished_at {ts_type},
            result TEXT NOT NULL,
            error_message TEXT,
            created_at {ts_type} NOT NULL DEFAULT {current_ts}
        );
        CREATE TABLE IF NOT EXISTS station_sessions (
            id {id_type},
            project_id INTEGER NOT NULL,
            station_id INTEGER NOT NULL,
            client_id TEXT NOT NULL,
            computer_name TEXT,
            ip_address TEXT,
            status TEXT NOT NULL DEFAULT 'online',
            acquired_at {ts_type} NOT NULL DEFAULT {current_ts},
            last_heartbeat_at {ts_type} NOT NULL DEFAULT {current_ts},
            note TEXT
        );
        CREATE TABLE IF NOT EXISTS station_session_logs (
            id {id_type},
            project_id INTEGER,
            station_id INTEGER,
            client_id TEXT,
            computer_name TEXT,
            ip_address TEXT,
            action TEXT NOT NULL,
            message TEXT,
            created_at {ts_type} NOT NULL DEFAULT {current_ts}
        );
        CREATE TABLE IF NOT EXISTS maintenance_logs (
            id {id_type},
            action TEXT NOT NULL,
            message TEXT,
            detail TEXT,
            created_at {ts_type} NOT NULL DEFAULT {current_ts}
        );
        CREATE TABLE IF NOT EXISTS client_releases (
            id {id_type},
            version TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL DEFAULT '',
            release_notes TEXT NOT NULL DEFAULT '[]',
            release_date {ts_type} NOT NULL,
            stable {bool_type},
            force_update {bool_type},
            min_required_version TEXT NOT NULL DEFAULT '',
            release_file_path TEXT NOT NULL DEFAULT '',
            debug_file_path TEXT NOT NULL DEFAULT '',
            s7_tool_file_path TEXT NOT NULL DEFAULT '',
            release_sha256 TEXT NOT NULL DEFAULT '',
            debug_sha256 TEXT NOT NULL DEFAULT '',
            s7_tool_sha256 TEXT NOT NULL DEFAULT '',
            created_at {ts_type} NOT NULL DEFAULT {current_ts},
            updated_at {ts_type} NOT NULL DEFAULT {current_ts}
        );
        CREATE TABLE IF NOT EXISTS client_update_logs (
            id {id_type},
            client_id TEXT,
            computer_name TEXT,
            ip_address TEXT,
            current_version TEXT,
            target_version TEXT,
            action TEXT NOT NULL,
            result TEXT NOT NULL,
            message TEXT,
            created_at {ts_type} NOT NULL DEFAULT {current_ts}
        );
        CREATE TABLE IF NOT EXISTS client_update_files (
            id {id_type},
            version TEXT NOT NULL,
            original_name TEXT NOT NULL,
            stored_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size BIGINT NOT NULL,
            sha256 TEXT NOT NULL,
            uploaded_by TEXT,
            uploaded_at {ts_type} NOT NULL DEFAULT {current_ts},
            remark TEXT
        );
        CREATE TABLE IF NOT EXISTS web_admin_users (
            id {id_type},
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            is_builtin {bool_type} NOT NULL,
            is_active {bool_true_type} NOT NULL,
            last_login_at {ts_type},
            created_at {ts_type} NOT NULL DEFAULT {current_ts},
            updated_at {ts_type} NOT NULL DEFAULT {current_ts}
        );
        CREATE TABLE IF NOT EXISTS web_admin_login_logs (
            id {id_type},
            username TEXT,
            role TEXT,
            ip_address TEXT,
            user_agent TEXT,
            success {bool_type} NOT NULL,
            message TEXT,
            created_at {ts_type} NOT NULL DEFAULT {current_ts}
        );
        CREATE TABLE IF NOT EXISTS barcode_cancel_logs (
            id {id_type},
            project_id INTEGER NOT NULL,
            station_id INTEGER NOT NULL,
            step_id BIGINT,
            product_instance_id BIGINT,
            barcode TEXT NOT NULL,
            cancel_type TEXT NOT NULL,
            old_record_id BIGINT,
            operator TEXT,
            created_at {ts_type} NOT NULL DEFAULT {current_ts}
        );
        CREATE TABLE IF NOT EXISTS degrade_mode_logs (
            id {id_type},
            project_id INTEGER,
            station_id INTEGER,
            client_id TEXT,
            operator TEXT,
            action TEXT NOT NULL,
            reason TEXT,
            created_at {ts_type} NOT NULL DEFAULT {current_ts}
        );
        CREATE INDEX IF NOT EXISTS idx_client_update_logs_created_at ON client_update_logs(created_at);
        CREATE INDEX IF NOT EXISTS idx_client_update_logs_client_id ON client_update_logs(client_id);
        CREATE INDEX IF NOT EXISTS idx_client_update_files_version ON client_update_files(version);
        CREATE INDEX IF NOT EXISTS idx_client_update_files_uploaded_at ON client_update_files(uploaded_at);
        CREATE INDEX IF NOT EXISTS idx_web_admin_login_logs_created_at ON web_admin_login_logs(created_at);
        CREATE INDEX IF NOT EXISTS idx_web_admin_login_logs_username ON web_admin_login_logs(username);
        CREATE INDEX IF NOT EXISTS idx_web_admin_login_logs_ip ON web_admin_login_logs(ip_address);
        CREATE INDEX IF NOT EXISTS idx_barcode_cancel_logs_barcode ON barcode_cancel_logs(barcode);
        CREATE INDEX IF NOT EXISTS idx_degrade_mode_logs_created_at ON degrade_mode_logs(created_at);
        CREATE INDEX IF NOT EXISTS idx_station_work_barcode ON station_work_records(main_barcode);
        CREATE INDEX IF NOT EXISTS idx_station_work_project_station_time ON station_work_records(project_id, station_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_station_work_result ON station_work_records(result);
        CREATE INDEX IF NOT EXISTS idx_step_work_barcode ON step_work_records(main_barcode);
        CREATE INDEX IF NOT EXISTS idx_step_work_station_step_time ON step_work_records(project_id, station_id, step_name, created_at);
        CREATE INDEX IF NOT EXISTS idx_step_work_created_at ON step_work_records(created_at);
        CREATE INDEX IF NOT EXISTS idx_screw_action_barcode ON screw_action_records(main_barcode);
        CREATE INDEX IF NOT EXISTS idx_screw_action_project_station_time ON screw_action_records(project_id, station_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_screw_action_result ON screw_action_records(result);
        CREATE UNIQUE INDEX IF NOT EXISTS ux_station_sessions_online ON station_sessions(project_id, station_id) WHERE status = 'online';
        CREATE INDEX IF NOT EXISTS idx_station_sessions_client ON station_sessions(client_id);
        CREATE INDEX IF NOT EXISTS idx_station_session_logs_created_at ON station_session_logs(created_at);
        CREATE INDEX IF NOT EXISTS idx_maintenance_logs_created_at ON maintenance_logs(created_at);
        """
    )


def create_product_flow_schema(conn):
    if conn.db_type == "postgresql":
        id_type = "BIGSERIAL PRIMARY KEY"
        ts_type = "TIMESTAMP"
        bool_type = "BOOLEAN"
        bool_default_true = "BOOLEAN NOT NULL DEFAULT true"
        bool_default_false = "BOOLEAN NOT NULL DEFAULT false"
        current_ts = "CURRENT_TIMESTAMP"
    else:
        id_type = "INTEGER PRIMARY KEY AUTOINCREMENT"
        ts_type = "TEXT"
        bool_type = "INTEGER"
        bool_default_true = "INTEGER NOT NULL DEFAULT 1"
        bool_default_false = "INTEGER NOT NULL DEFAULT 0"
        current_ts = "CURRENT_TIMESTAMP"
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS product_instances (
            id {id_type},
            project_id INTEGER NOT NULL,
            material_code TEXT NOT NULL DEFAULT '',
            product_type TEXT NOT NULL DEFAULT '',
            current_barcode TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at {ts_type} NOT NULL DEFAULT {current_ts},
            updated_at {ts_type} NOT NULL DEFAULT {current_ts}
        );
        CREATE TABLE IF NOT EXISTS barcode_aliases (
            id {id_type},
            product_instance_id BIGINT NOT NULL,
            barcode TEXT NOT NULL UNIQUE,
            barcode_type TEXT NOT NULL DEFAULT 'main_current',
            is_current {bool_default_true},
            created_at {ts_type} NOT NULL DEFAULT {current_ts},
            disabled_at {ts_type}
        );
        CREATE TABLE IF NOT EXISTS barcode_switch_records (
            id {id_type},
            product_instance_id BIGINT NOT NULL,
            old_barcode TEXT NOT NULL,
            new_barcode TEXT NOT NULL,
            project_id INTEGER NOT NULL,
            station_id INTEGER NOT NULL,
            step_id INTEGER,
            operator TEXT,
            reason TEXT,
            created_at {ts_type} NOT NULL DEFAULT {current_ts}
        );
        CREATE TABLE IF NOT EXISTS material_bindings (
            id {id_type},
            parent_product_instance_id BIGINT NOT NULL,
            child_product_instance_id BIGINT NOT NULL,
            parent_barcode TEXT NOT NULL,
            child_barcode TEXT NOT NULL,
            binding_type TEXT NOT NULL DEFAULT '',
            project_id INTEGER NOT NULL,
            station_id INTEGER NOT NULL,
            step_id INTEGER,
            operator TEXT,
            is_active {bool_default_true},
            created_at {ts_type} NOT NULL DEFAULT {current_ts}
        );
        CREATE TABLE IF NOT EXISTS station_dependencies (
            id {id_type},
            station_id INTEGER NOT NULL UNIQUE,
            require_previous_station {bool_default_true},
            required_station_ids TEXT NOT NULL DEFAULT '[]',
            require_barcode_switch {bool_default_false},
            require_current_barcode {bool_default_false},
            required_child_project_id INTEGER,
            required_child_material_type TEXT NOT NULL DEFAULT '',
            required_child_count INTEGER NOT NULL DEFAULT 0,
            required_child_station_ids TEXT NOT NULL DEFAULT '[]',
            created_at {ts_type} NOT NULL DEFAULT {current_ts},
            updated_at {ts_type} NOT NULL DEFAULT {current_ts}
        );
        CREATE INDEX IF NOT EXISTS idx_product_instances_project ON product_instances(project_id);
        CREATE INDEX IF NOT EXISTS idx_product_instances_current_barcode ON product_instances(current_barcode);
        CREATE INDEX IF NOT EXISTS idx_barcode_alias_instance ON barcode_aliases(product_instance_id);
        CREATE INDEX IF NOT EXISTS idx_barcode_alias_current ON barcode_aliases(product_instance_id, is_current);
        CREATE INDEX IF NOT EXISTS idx_barcode_switch_instance ON barcode_switch_records(product_instance_id);
        CREATE INDEX IF NOT EXISTS idx_material_bind_parent ON material_bindings(parent_product_instance_id, is_active);
        CREATE INDEX IF NOT EXISTS idx_material_bind_child ON material_bindings(child_product_instance_id, is_active);
        CREATE UNIQUE INDEX IF NOT EXISTS ux_material_bind_child_active
            ON material_bindings(child_product_instance_id) WHERE is_active = {('true' if conn.db_type == 'postgresql' else '1')};
        """
    )


def migrate_sqlite_db(conn):
    project_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(projects)").fetchall()
    }
    for column, definition in PROJECT_FLOW_COLUMNS.items():
        if column not in project_columns:
            conn.execute(f"ALTER TABLE projects ADD COLUMN {column} {definition}")
    station_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(stations)").fetchall()
    }
    route_order_added = "route_order" not in station_columns
    for column, definition in STATION_ROUTE_COLUMNS.items():
        if column not in station_columns:
            conn.execute(f"ALTER TABLE stations ADD COLUMN {column} {definition}")
    if route_order_added:
        conn.execute(
            "UPDATE stations SET route_order = id WHERE route_order = 0"
        )
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(steps)").fetchall()]
    if "is_main_barcode" not in columns:
        conn.execute("ALTER TABLE steps ADD COLUMN is_main_barcode INTEGER NOT NULL DEFAULT 0")
        columns.append("is_main_barcode")
    for column, definition in PLC_STEP_COLUMNS.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE steps ADD COLUMN {column} {definition}")
            columns.append(column)
    for column, definition in MAGNET_STEP_COLUMNS.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE steps ADD COLUMN {column} {definition}")
            columns.append(column)
    for column, definition in FLOW_STEP_COLUMNS.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE steps ADD COLUMN {column} {definition}")
            columns.append(column)
    dependency_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(station_dependencies)").fetchall()
    }
    if "require_current_barcode" not in dependency_columns:
        conn.execute(
            "ALTER TABLE station_dependencies "
            "ADD COLUMN require_current_barcode INTEGER NOT NULL DEFAULT 0"
        )
    migrate_sqlite_flow_record_columns(conn)
    if "plc_barcode_db" in columns and "plc_barcode1_db" in columns:
        conn.execute(
            """
            UPDATE steps
            SET plc_barcode_db = plc_barcode1_db,
                plc_barcode_offset = plc_barcode1_offset,
                plc_barcode_length = plc_barcode1_length
            WHERE plc_barcode_db IS NULL
               OR plc_barcode_offset IS NULL
               OR plc_barcode_length IS NULL
            """
        )
    release_columns = [row["name"] for row in conn.execute("PRAGMA table_info(client_releases)").fetchall()]
    if release_columns:
        for column, definition in CLIENT_RELEASE_COLUMNS.items():
            if column not in release_columns:
                conn.execute(f"ALTER TABLE client_releases ADD COLUMN {column} {definition}")
    else:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS client_releases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL DEFAULT '',
                release_notes TEXT NOT NULL DEFAULT '[]',
                release_date TEXT NOT NULL,
                stable INTEGER NOT NULL DEFAULT 1,
                force_update INTEGER NOT NULL DEFAULT 0,
                min_required_version TEXT NOT NULL DEFAULT '',
                release_file_path TEXT NOT NULL DEFAULT '',
                debug_file_path TEXT NOT NULL DEFAULT '',
                s7_tool_file_path TEXT NOT NULL DEFAULT '',
                release_sha256 TEXT NOT NULL DEFAULT '',
                debug_sha256 TEXT NOT NULL DEFAULT '',
                s7_tool_sha256 TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS client_update_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT,
                computer_name TEXT,
                ip_address TEXT,
                current_version TEXT,
                target_version TEXT,
                action TEXT NOT NULL,
                result TEXT NOT NULL,
                message TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_client_update_logs_created_at ON client_update_logs(created_at);
            CREATE INDEX IF NOT EXISTS idx_client_update_logs_client_id ON client_update_logs(client_id);
            """
        )


def migrate_postgresql_db(conn):
    project_rows = conn.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'projects'
        """
    ).fetchall()
    project_columns = {row["column_name"] for row in project_rows}
    for column, definition in PROJECT_FLOW_COLUMNS.items():
        if column not in project_columns:
            conn.execute(f"ALTER TABLE projects ADD COLUMN {column} {definition}")
    station_rows = conn.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'stations'
        """
    ).fetchall()
    station_columns = {row["column_name"] for row in station_rows}
    route_order_added = "route_order" not in station_columns
    for column, definition in STATION_ROUTE_COLUMNS.items():
        if column not in station_columns:
            conn.execute(f"ALTER TABLE stations ADD COLUMN {column} {definition}")
    if route_order_added:
        conn.execute(
            "UPDATE stations SET route_order = id WHERE route_order = 0"
        )
    conn.execute(
        "ALTER TABLE stations ALTER COLUMN route_name SET DEFAULT 'A主线'"
    )
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'steps'
        """
    ).fetchall()
    columns = {row["column_name"] for row in rows}
    for column, definition in PLC_STEP_COLUMNS.items():
        if column in columns:
            continue
        pg_definition = definition.replace("INTEGER", "INTEGER").replace("TEXT", "TEXT")
        conn.execute(f"ALTER TABLE steps ADD COLUMN {column} {pg_definition}")
        columns.add(column)
    for column, definition in MAGNET_STEP_COLUMNS.items():
        if column in columns:
            continue
        conn.execute(f"ALTER TABLE steps ADD COLUMN {column} {definition}")
        columns.add(column)
    for column, definition in FLOW_STEP_COLUMNS.items():
        if column in columns:
            continue
        if column in FLOW_STEP_BOOLEAN_COLUMNS:
            default = "false" if "DEFAULT 0" in definition else "true"
            pg_definition = f"BOOLEAN NOT NULL DEFAULT {default}"
        else:
            pg_definition = definition
        conn.execute(f"ALTER TABLE steps ADD COLUMN {column} {pg_definition}")
        columns.add(column)
    dependency_rows = conn.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'station_dependencies'
        """
    ).fetchall()
    dependency_columns = {row["column_name"] for row in dependency_rows}
    if "require_current_barcode" not in dependency_columns:
        conn.execute(
            "ALTER TABLE station_dependencies "
            "ADD COLUMN require_current_barcode BOOLEAN NOT NULL DEFAULT false"
        )
    migrate_postgresql_flow_record_columns(conn)
    if {"plc_barcode_db", "plc_barcode1_db", "plc_barcode_offset", "plc_barcode1_offset", "plc_barcode_length", "plc_barcode1_length"}.issubset(columns):
        conn.execute(
            """
            UPDATE steps
            SET plc_barcode_db = plc_barcode1_db,
                plc_barcode_offset = plc_barcode1_offset,
                plc_barcode_length = plc_barcode1_length
            WHERE plc_barcode_db IS NULL
               OR plc_barcode_offset IS NULL
               OR plc_barcode_length IS NULL
            """
        )
    release_rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'client_releases'
        """
    ).fetchall()
    release_columns = {row["column_name"] for row in release_rows}
    if release_columns:
        for column, definition in CLIENT_RELEASE_COLUMNS.items():
            if column in release_columns:
                continue
            conn.execute(f"ALTER TABLE client_releases ADD COLUMN {column} {definition.replace('INTEGER', 'INTEGER').replace('TEXT', 'TEXT')}")
    else:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS client_releases (
                id BIGSERIAL PRIMARY KEY,
                version TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL DEFAULT '',
                release_notes TEXT NOT NULL DEFAULT '[]',
                release_date TIMESTAMP NOT NULL,
                stable BOOLEAN DEFAULT true,
                force_update BOOLEAN DEFAULT false,
                min_required_version TEXT NOT NULL DEFAULT '',
                release_file_path TEXT NOT NULL DEFAULT '',
                debug_file_path TEXT NOT NULL DEFAULT '',
                s7_tool_file_path TEXT NOT NULL DEFAULT '',
                release_sha256 TEXT NOT NULL DEFAULT '',
                debug_sha256 TEXT NOT NULL DEFAULT '',
                s7_tool_sha256 TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            );
            CREATE TABLE IF NOT EXISTS client_update_logs (
                id BIGSERIAL PRIMARY KEY,
                client_id TEXT,
                computer_name TEXT,
                ip_address TEXT,
                current_version TEXT,
                target_version TEXT,
                action TEXT NOT NULL,
                result TEXT NOT NULL,
                message TEXT,
                created_at TIMESTAMP NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_client_update_logs_created_at ON client_update_logs(created_at);
            CREATE INDEX IF NOT EXISTS idx_client_update_logs_client_id ON client_update_logs(client_id);
            """
        )


def migrate_sqlite_flow_record_columns(conn):
    for table, definitions in FLOW_RECORD_COLUMNS.items():
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for column, definition in definitions.items():
            if column not in columns:
                sqlite_definition = definition.replace("BIGINT", "INTEGER")
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sqlite_definition}")


def migrate_postgresql_flow_record_columns(conn):
    for table, definitions in FLOW_RECORD_COLUMNS.items():
        rows = conn.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = ?
            """,
            (table,),
        ).fetchall()
        columns = {row["column_name"] for row in rows}
        for column, definition in definitions.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


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
        if index == 1:
            default_steps = [
                (1, "PLC接收主条码", "PLC接收", 0, 1, 7, "", 1),
            ]
        else:
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
        flow_identity = conn.execute(
            """
            SELECT 1 FROM steps
            WHERE station_id = ? AND type IN (?, ?)
            LIMIT 1
            """,
            (station["id"], "主条码切换", "子物料绑定"),
        ).fetchone()
        if flow_identity:
            continue
        first_scan = conn.execute(
            "SELECT id FROM steps WHERE station_id = ? AND type IN (?, ?) ORDER BY step_order, id LIMIT 1",
            (station["id"], "扫码", "PLC接收"),
        ).fetchone()
        if first_scan:
            conn.execute("UPDATE steps SET is_main_barcode = 1 WHERE id = ?", (first_scan["id"],))


def ensure_default_client_release_tables(conn):
    row = conn.execute("SELECT COUNT(*) AS total FROM client_releases").fetchone()
    if row and row["total"]:
        return
