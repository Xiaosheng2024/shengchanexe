#!/usr/bin/env bash
set -euo pipefail

MES_DIR="${MES_DIR:-/opt/mes}"
MES_DB_NAME="${MES_DB_NAME:-mes_db}"
MES_DB_USER="${MES_DB_USER:-mes_user}"
MES_DB_PASSWORD="${MES_DB_PASSWORD:-$(openssl rand -base64 24 | tr -d '\n')}"

dnf install -y python3 python3-pip firewalld
dnf install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm
dnf -qy module disable postgresql || true
dnf install -y postgresql16-server postgresql16

if [ ! -f /var/lib/pgsql/16/data/PG_VERSION ]; then
  /usr/pgsql-16/bin/postgresql-16-setup initdb
fi

systemctl enable --now postgresql-16

sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \\$\\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${MES_DB_USER}') THEN
    CREATE USER ${MES_DB_USER} WITH PASSWORD '${MES_DB_PASSWORD}';
  END IF;
END
\\$\\$;
SELECT 'CREATE DATABASE ${MES_DB_NAME} OWNER ${MES_DB_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${MES_DB_NAME}')\\gexec
GRANT ALL PRIVILEGES ON DATABASE ${MES_DB_NAME} TO ${MES_DB_USER};
SQL

mkdir -p "${MES_DIR}" "${MES_DIR}/backup"

cat > "${MES_DIR}/config.ini" <<EOF
[DATABASE]
type = postgresql
host = 127.0.0.1
port = 5432
database = ${MES_DB_NAME}
user = ${MES_DB_USER}
password = ${MES_DB_PASSWORD}
EOF
chmod 600 "${MES_DIR}/config.ini"

systemctl enable --now firewalld
firewall-cmd --permanent --add-service=ssh
firewall-cmd --permanent --add-port=8000/tcp
firewall-cmd --reload

echo "PostgreSQL 16 已安装，MES 数据库 ${MES_DB_NAME} 已创建。"
echo "请将项目文件部署到 ${MES_DIR}，并使用 ${MES_DIR}/config.ini 启动 MES 服务。"
echo "数据库密码已随机生成并写入 ${MES_DIR}/config.ini，请妥善保存。"
