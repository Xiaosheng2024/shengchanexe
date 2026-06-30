#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 sudo 执行此脚本" >&2
  exit 1
fi

SECRET_FILE="/root/server-secrets/web_admin_accounts.txt"
new_password="$(openssl rand -hex 20)"

MES_WEB_ADMIN_NEW_PASSWORD="${new_password}" \
  /opt/mes/.venv/bin/python /opt/mes/tools/manage_web_admin_users.py reset --username super_admin

MES_SECRET_FILE="${SECRET_FILE}" MES_SECRET_PASSWORD="${new_password}" python3 - <<'PY'
import os
from pathlib import Path

path = Path(os.environ["MES_SECRET_FILE"])
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else ["MES Web Admin:"]
key = "super_admin_password"
value = os.environ["MES_SECRET_PASSWORD"]
updated = []
found = False
for line in lines:
    if line.startswith(key + "="):
        updated.append(f"{key}={value}")
        found = True
    else:
        updated.append(line)
if not found:
    updated.append(f"{key}={value}")
path.write_text("\n".join(updated) + "\n", encoding="utf-8")
PY
chmod 600 "${SECRET_FILE}"
unset new_password

echo "超级管理员密码已重置，保存路径：${SECRET_FILE}"
