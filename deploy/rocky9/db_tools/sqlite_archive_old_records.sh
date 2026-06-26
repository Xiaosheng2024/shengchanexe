#!/usr/bin/env bash
set -euo pipefail
BEFORE_DATE="${1:-}"
if [ -z "${BEFORE_DATE}" ]; then
  echo "用法：$0 YYYY-MM-DD"
  echo "说明：导出指定日期前 SQLite 历史记录到 archive，不删除主库数据。"
  exit 1
fi
DB_FILE="${DB_FILE:-quality_control.db}"
ARCHIVE_DIR="${ARCHIVE_DIR:-archive}"
mkdir -p "${ARCHIVE_DIR}"
OUT="${ARCHIVE_DIR}/sqlite_archive_before_${BEFORE_DATE}_$(date +%Y%m%d_%H%M%S).csv"
sqlite3 -header -csv "${DB_FILE}" "SELECT * FROM scan_records WHERE created_at < '${BEFORE_DATE}';" > "${OUT}"
echo "SQLite 归档完成：${OUT}"
