#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/apple/Documents/生产工艺过程质量控制系统"
DIST_DIR="${PROJECT_DIR}/dist_deploy"
SERVER_HOST="10.162.70.53"
SERVER_USER="dell"
SERVER="${SERVER_USER}@${SERVER_HOST}"
MES_DIR="/opt/mes"
MES_SERVICE="mes-web"
MES_DB_NAME="mes_db"

sha256_value() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

cd "${PROJECT_DIR}"

for required_file in \
  "${DIST_DIR}/mes_update.tar.gz" \
  "${DIST_DIR}/offline_wheels.tar.gz" \
  "${DIST_DIR}/deploy_commit.txt" \
  "${DIST_DIR}/DEPLOY_NOTES.txt" \
  "${DIST_DIR}/SHA256SUMS"; do
  if [ ! -f "${required_file}" ]; then
    echo "错误：缺少 ${required_file}，请先在外网执行 prepare_update_package.sh。" >&2
    exit 1
  fi
done

DEPLOY_COMMIT="$(tr -d '[:space:]' < "${DIST_DIR}/deploy_commit.txt")"
MES_PACKAGE_SHA256="$(sha256_value "${DIST_DIR}/mes_update.tar.gz")"
WHEELS_PACKAGE_SHA256="$(sha256_value "${DIST_DIR}/offline_wheels.tar.gz")"

echo "== 校验本地更新包 =="
(
  cd "${DIST_DIR}"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c SHA256SUMS
  else
    shasum -a 256 -c SHA256SUMS
  fi
)

echo "== 检查公司内网连接 =="
ping -c 2 "${SERVER_HOST}"
ssh -o ConnectTimeout=5 "${SERVER}" "echo SSH_OK"

echo "== 上传更新包 =="
scp "${DIST_DIR}/mes_update.tar.gz" "${SERVER}:/home/dell/"
scp "${DIST_DIR}/offline_wheels.tar.gz" "${SERVER}:/home/dell/"

echo "== 在服务器执行部署 =="
ssh -tt "${SERVER}" \
  "DEPLOY_COMMIT='${DEPLOY_COMMIT}' MES_PACKAGE_SHA256='${MES_PACKAGE_SHA256}' WHEELS_PACKAGE_SHA256='${WHEELS_PACKAGE_SHA256}' bash -s" <<'REMOTE_SCRIPT'
set -euo pipefail

MES_DIR="/opt/mes"
MES_SERVICE="mes-web"
MES_DB_NAME="mes_db"
MES_PACKAGE="/home/dell/mes_update.tar.gz"
WHEELS_PACKAGE="/home/dell/offline_wheels.tar.gz"
MANUAL_BACKUP_DIR="${MES_DIR}/backups/manual"
UPDATE_DIR="/tmp/mes_update"
OFFLINE_WHEEL_DIR="/tmp/offline_wheels"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DB_BACKUP="${MANUAL_BACKUP_DIR}/${MES_DB_NAME}_before_update_${TIMESTAMP}.dump"
CODE_BACKUP="${MANUAL_BACKUP_DIR}/mes_code_before_update_${TIMESTAMP}.tar.gz"

deployment_failed() {
  exit_code=$?
  echo
  echo "部署失败，退出码：${exit_code}" >&2
  echo "数据库备份：${DB_BACKUP}" >&2
  echo "代码备份：${CODE_BACKUP}" >&2
  echo "最近 mes-web 日志：" >&2
  sudo journalctl -u "${MES_SERVICE}" -n 120 --no-pager || true
  exit "${exit_code}"
}
trap deployment_failed ERR

remote_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

echo "部署 commit：${DEPLOY_COMMIT}"
test "$(remote_sha256 "${MES_PACKAGE}")" = "${MES_PACKAGE_SHA256}"
test "$(remote_sha256 "${WHEELS_PACKAGE}")" = "${WHEELS_PACKAGE_SHA256}"

sudo mkdir -p "${MANUAL_BACKUP_DIR}"

echo "== 备份 PostgreSQL =="
sudo bash -c "sudo -iu postgres pg_dump -Fc '${MES_DB_NAME}' > '${DB_BACKUP}'"
sudo test -s "${DB_BACKUP}"

echo "== 备份当前代码 =="
sudo tar \
  --exclude='mes/.venv' \
  --exclude='mes/backups' \
  -czf "${CODE_BACKUP}" \
  -C /opt \
  mes
sudo test -s "${CODE_BACKUP}"

echo "== 停止 mes-web =="
sudo systemctl stop "${MES_SERVICE}"

echo "== 解压并同步代码 =="
sudo rm -rf "${UPDATE_DIR}"
sudo mkdir -p "${UPDATE_DIR}"
sudo tar -xzf "${MES_PACKAGE}" -C "${UPDATE_DIR}"
sudo rsync -a --delete \
  --exclude='config.ini' \
  --exclude='quality_control.db' \
  --exclude='.venv/' \
  --exclude='backups/' \
  --exclude='logs/' \
  --exclude='releases/' \
  "${UPDATE_DIR}/" \
  "${MES_DIR}/"

echo "== 准备客户端更新包目录 =="
sudo mkdir -p "${MES_DIR}/releases/client_updates"
sudo chown -R dell:dell "${MES_DIR}/releases"
sudo chmod -R 755 "${MES_DIR}/releases"

echo "== 校验服务器依赖清单 =="
if grep -Eiq 'PyQt5|PyQtWebEngine|PyQt5-Qt5|matplotlib|pyinstaller|python-snap7|pymodbus' \
  "${MES_DIR}/requirements-server.txt"; then
  echo "错误：requirements-server.txt 包含禁止安装的桌面端依赖。" >&2
  exit 1
fi

echo "== 安装离线服务端依赖 =="
sudo rm -rf "${OFFLINE_WHEEL_DIR}"
sudo mkdir -p "${OFFLINE_WHEEL_DIR}"
sudo tar -xzf "${WHEELS_PACKAGE}" -C "${OFFLINE_WHEEL_DIR}"
cd "${MES_DIR}"
source .venv/bin/activate
sudo "${VIRTUAL_ENV}/bin/python" -m pip install \
  --no-index \
  --find-links "${OFFLINE_WHEEL_DIR}" \
  -r requirements-server.txt

echo "== 执行数据库初始化/迁移 =="
sudo "${VIRTUAL_ENV}/bin/python" -c \
  "from web_admin_app.database import init_db; init_db()"

echo "== 验证 PLC磁通数据库迁移 =="
sudo "${VIRTUAL_ENV}/bin/python" - <<'PY'
from web_admin_app.database import get_conn, get_database_type

with get_conn() as conn:
    if get_database_type() == "postgresql":
        columns = {
            row["column_name"]
            for row in conn.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'steps'
                """
            ).fetchall()
        }
        tables = {
            row["table_name"]
            for row in conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            ).fetchall()
        }
    else:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(steps)").fetchall()
        }
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

assert "plc_magnet_config" in columns, "steps.plc_magnet_config 迁移失败"
assert "plc_magnet_logs" in tables, "plc_magnet_logs 建表失败"
print("PLC_MAGNET_MIGRATION_OK")
PY

echo "== 启动并验证服务 =="
sudo systemctl start "${MES_SERVICE}"
sleep 3
sudo systemctl is-active --quiet "${MES_SERVICE}"
sudo systemctl status "${MES_SERVICE}" --no-pager
sudo systemctl status postgresql-16 --no-pager
ss -lntp | grep -E ':8000|:5432'
PG_LISTEN_ADDRS="$(ss -lnt | awk '$4 ~ /:5432$/ {print $4}')"
echo "PostgreSQL listen addresses:"
echo "${PG_LISTEN_ADDRS}"
if echo "${PG_LISTEN_ADDRS}" | grep -Eq '^(0\.0\.0\.0|\*|\[::\]):5432$'; then
  echo "错误：PostgreSQL 5432 正在对外监听。" >&2
  exit 1
fi
curl -fsSI http://127.0.0.1:8000
curl -fsSI http://10.162.70.53:8000
sudo journalctl -u "${MES_SERVICE}" -n 120 --no-pager

trap - ERR
echo
echo "部署成功"
echo "部署 commit：${DEPLOY_COMMIT}"
echo "数据库备份路径：${DB_BACKUP}"
echo "代码备份路径：${CODE_BACKUP}"
echo "mes-web 状态：$(sudo systemctl is-active "${MES_SERVICE}")"
echo "Web 访问地址：http://10.162.70.53:8000"
echo "数据库迁移：PLC_MAGNET_MIGRATION_OK"
REMOTE_SCRIPT
