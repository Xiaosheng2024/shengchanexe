#!/usr/bin/env bash
set -euo pipefail
BEFORE_DATE="${1:-}"
if [ -z "${BEFORE_DATE}" ]; then
  echo "用法：$0 YYYY-MM-DD"
  echo "说明：导出指定日期前的历史记录到 /opt/mes/archive，不删除主库数据。"
  exit 1
fi
ARCHIVE_DIR="${ARCHIVE_DIR:-/opt/mes/archive}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-mes_db}"
DB_USER="${DB_USER:-mes_user}"
mkdir -p "${ARCHIVE_DIR}"
OUT="${ARCHIVE_DIR}/mes_archive_before_${BEFORE_DATE}_$(date +%Y%m%d_%H%M%S).csv"
echo "正在归档 ${BEFORE_DATE} 前的数据到 ${OUT} ..."
psql -U "${DB_USER}" -h "${DB_HOST}" -p "${DB_PORT}" -d "${DB_NAME}" -c "\\copy (SELECT 'scan_records' AS table_name, * FROM scan_records WHERE created_at < '${BEFORE_DATE}') TO '${OUT}' CSV HEADER"
echo "归档完成。此脚本不删除主库数据。"
