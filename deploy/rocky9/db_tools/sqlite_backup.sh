#!/usr/bin/env bash
set -euo pipefail
DB_FILE="${DB_FILE:-quality_control.db}"
BACKUP_DIR="${BACKUP_DIR:-backup}"
mkdir -p "${BACKUP_DIR}"
OUT="${BACKUP_DIR}/quality_control_$(date +%Y%m%d_%H%M%S).db"
cp -p "${DB_FILE}" "${OUT}"
echo "SQLite 备份完成：${OUT}"
