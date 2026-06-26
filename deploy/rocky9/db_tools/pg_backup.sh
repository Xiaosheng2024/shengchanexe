#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/mes/backup}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-mes_db}"
DB_USER="${DB_USER:-mes_user}"

mkdir -p "${BACKUP_DIR}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="${BACKUP_DIR}/mes_db_${STAMP}.dump"

pg_dump -U "${DB_USER}" -h "${DB_HOST}" -p "${DB_PORT}" -Fc "${DB_NAME}" > "${OUT}"
echo "备份完成：${OUT}"
