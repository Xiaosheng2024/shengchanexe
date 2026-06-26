#!/usr/bin/env bash
set -euo pipefail
DB_FILE="${DB_FILE:-quality_control.db}"
echo "正在检查 SQLite 数据库：${DB_FILE}"
sqlite3 "${DB_FILE}" "PRAGMA integrity_check;"
sqlite3 "${DB_FILE}" "SELECT 'scan_records', COUNT(*) FROM scan_records UNION ALL SELECT 'station_work_records', COUNT(*) FROM station_work_records UNION ALL SELECT 'step_work_records', COUNT(*) FROM step_work_records UNION ALL SELECT 'screw_action_records', COUNT(*) FROM screw_action_records;"
echo "检查完成。"
