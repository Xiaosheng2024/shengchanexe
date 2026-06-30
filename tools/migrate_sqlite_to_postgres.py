#!/usr/bin/env python3
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from web_admin_app import database


DEFAULT_TABLES = ["projects", "stations", "steps", "scan_records", "station_completions"]
MIGRATABLE_TABLES = [
    "projects",
    "stations",
    "steps",
    "scan_records",
    "station_completions",
    "station_work_records",
    "step_work_records",
    "screw_action_records",
    "station_sessions",
    "station_session_logs",
    "maintenance_logs",
    "client_releases",
    "client_update_logs",
]


def sqlite_rows(sqlite_path: Path, table: str):
    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()]


def target_has_data(conn, tables):
    return any(conn.execute(f"SELECT COUNT(*) AS total FROM {table}").fetchone()["total"] for table in tables)


def clear_target(conn, tables):
    for table in reversed(tables):
        conn.execute(f"DELETE FROM {table}")


def insert_rows(conn, table: str, rows):
    if not rows:
        return 0
    columns = list(rows[0].keys())
    placeholders = ", ".join(["?"] * len(columns))
    column_sql = ", ".join(columns)
    sql = f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
    for row in rows:
        conn.execute(sql, [row[column] for column in columns])
    return len(rows)


def reset_sequences(conn, tables):
    for table in tables:
        conn.execute(
            "SELECT setval(pg_get_serial_sequence(?, 'id'), COALESCE((SELECT MAX(id) FROM " + table + "), 1), true)",
            (table,),
        )


def main():
    parser = argparse.ArgumentParser(description="Migrate MES SQLite data to PostgreSQL.")
    parser.add_argument("--sqlite", default=str(database.DB_PATH), help="SQLite database path, default quality_control.db")
    parser.add_argument("--force", action="store_true", help="Allow migration when PostgreSQL already has data")
    parser.add_argument(
        "--tables",
        default=",".join(DEFAULT_TABLES),
        help="Comma-separated tables to migrate",
    )
    args = parser.parse_args()
    tables = [item.strip() for item in args.tables.split(",") if item.strip()]
    invalid_tables = sorted(set(tables) - set(MIGRATABLE_TABLES))
    if not tables:
        raise SystemExit("至少指定一张迁移表")
    if invalid_tables:
        raise SystemExit(f"不支持迁移的表：{', '.join(invalid_tables)}")

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite 文件不存在：{sqlite_path}")

    db_config = database.load_database_config()
    if db_config["type"] != "postgresql":
        raise SystemExit("config.ini 的 [DATABASE] type 必须是 postgresql")

    with database.get_conn() as conn:
        database.create_postgresql_schema(conn)
        if target_has_data(conn, tables):
            if not args.force:
                raise SystemExit("目标 PostgreSQL 已有数据。如确认继续，请增加 --force")
            clear_target(conn, tables)

        counts = {}
        for table in tables:
            rows = sqlite_rows(sqlite_path, table)
            counts[table] = insert_rows(conn, table, rows)
        reset_sequences(conn, tables)

    print("SQLite 到 PostgreSQL 迁移完成")
    for table in tables:
        print(f"{table}: {counts[table]}")


if __name__ == "__main__":
    main()
