#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/mes/backups/postgres}"
DB_NAME="${DB_NAME:-mes_db}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="${BACKUP_DIR}/${DB_NAME}_${STAMP}.sql"

mkdir -p "${BACKUP_DIR}"
cd /tmp
pg_dump --dbname="${DB_NAME}" --file="${OUT}"
find "${BACKUP_DIR}" -type f -name "${DB_NAME}_*.sql" -mtime "+${RETENTION_DAYS}" -delete
echo "PostgreSQL 备份完成：${OUT}"
