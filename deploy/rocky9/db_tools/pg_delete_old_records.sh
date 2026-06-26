#!/usr/bin/env bash
set -euo pipefail
BEFORE_DATE="${1:-}"
if [ -z "${BEFORE_DATE}" ]; then
  echo "用法：$0 YYYY-MM-DD"
  echo "危险操作：删除指定日期前的历史数据，默认不删除 station_completions。"
  exit 1
fi
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-mes_db}"
DB_USER="${DB_USER:-mes_user}"
echo "删除前自动备份数据库..."
"$(dirname "$0")/pg_backup.sh"
read -r -p "确认删除 ${BEFORE_DATE} 前历史数据？请输入 DELETE 确认：" CONFIRM
if [ "${CONFIRM}" != "DELETE" ]; then
  echo "已取消。"
  exit 1
fi
psql -U "${DB_USER}" -h "${DB_HOST}" -p "${DB_PORT}" -d "${DB_NAME}" <<SQL
DELETE FROM scan_records WHERE created_at < '${BEFORE_DATE}';
DELETE FROM station_work_records WHERE created_at < '${BEFORE_DATE}';
DELETE FROM step_work_records WHERE created_at < '${BEFORE_DATE}';
DELETE FROM screw_action_records WHERE created_at < '${BEFORE_DATE}';
DELETE FROM station_session_logs WHERE created_at < '${BEFORE_DATE}';
SQL
echo "历史数据删除完成。station_completions 未删除。"
