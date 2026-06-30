#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 sudo 执行此脚本" >&2
  exit 1
fi

SECRET_DIR="/root/server-secrets"
SECRET_FILE="${SECRET_DIR}/web_admin_accounts.txt"
PYTHON="/opt/mes/.venv/bin/python"
MANAGER="/opt/mes/tools/manage_web_admin_users.py"

if [[ -f "${SECRET_FILE}" ]]; then
  "${PYTHON}" "${MANAGER}" validate
  echo "Web 管理账号已初始化，保存路径：${SECRET_FILE}"
  exit 0
fi

admin_password="$(openssl rand -hex 16)"
super_password="$(openssl rand -hex 20)"
created_at="$(date -Iseconds)"

MES_ADMIN_INITIAL_PASSWORD="${admin_password}" \
MES_SUPER_ADMIN_INITIAL_PASSWORD="${super_password}" \
  "${PYTHON}" "${MANAGER}" init

install -d -m 700 "${SECRET_DIR}"
umask 077
{
  echo "MES Web Admin:"
  echo "admin_username=admin"
  echo "admin_initial_password=${admin_password}"
  echo "super_admin_username=super_admin"
  echo "super_admin_password=${super_password}"
  echo "created_at=${created_at}"
} > "${SECRET_FILE}"
chmod 600 "${SECRET_FILE}"
unset admin_password super_password

echo "Web 管理账号已初始化，保存路径：${SECRET_FILE}"
