#!/usr/bin/env bash
set -euo pipefail
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-mes_db}"
DB_USER="${DB_USER:-mes_user}"
echo "正在检查 PostgreSQL 数据库状态..."
psql -U "${DB_USER}" -h "${DB_HOST}" -p "${DB_PORT}" -d "${DB_NAME}" -c "SELECT now() AS 当前时间, current_database() AS 数据库;"
psql -U "${DB_USER}" -h "${DB_HOST}" -p "${DB_PORT}" -d "${DB_NAME}" -c "SELECT relname AS 表名, n_live_tup AS 估算记录数 FROM pg_stat_user_tables ORDER BY relname;"
echo "检查完成。"
