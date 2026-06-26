#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "用法：$0 /opt/mes/backup/mes_db_YYYYMMDD_HHMMSS.dump"
  exit 1
fi

BACKUP_FILE="$1"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-mes_db}"
DB_USER="${DB_USER:-mes_user}"
SERVICE_NAME="${SERVICE_NAME:-mes-web}"

if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
  systemctl stop "${SERVICE_NAME}" || true
fi

"$(dirname "$0")/pg_backup.sh" || true

pg_restore -U "${DB_USER}" -h "${DB_HOST}" -p "${DB_PORT}" -d "${DB_NAME}" --clean --if-exists "${BACKUP_FILE}"

if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
  systemctl start "${SERVICE_NAME}"
fi

echo "恢复完成：${BACKUP_FILE}"
