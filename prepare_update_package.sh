#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/apple/Documents/生产工艺过程质量控制系统"
DIST_DIR="${PROJECT_DIR}/dist_deploy"
WHEEL_DIR="${DIST_DIR}/offline_wheels"

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1"
  else
    shasum -a 256 "$1"
  fi
}

cd "${PROJECT_DIR}"

echo "== Git 状态 =="
git status
DIRTY_SOURCE_FILES="$(
  git status --porcelain --untracked-files=no \
    | awk '$2 != "s7_plc_test_tool/config.ini" {print}'
)"
if [ -n "${DIRTY_SOURCE_FILES}" ]; then
  echo "错误：工作区存在未提交修改，请先提交或清理后再准备更新包。" >&2
  printf '%s\n' "${DIRTY_SOURCE_FILES}" >&2
  exit 1
fi
if ! git diff --quiet -- s7_plc_test_tool/config.ini; then
  echo "提示：保留本机 S7 测试工具配置变化；该 config.ini 不会进入服务器更新包。"
fi
if [ -n "$(git ls-files --others --exclude-standard)" ]; then
  echo "提示：未跟踪文件不会进入更新包，服务器包只取已提交 commit。"
fi

echo "== 更新 main 分支 =="
git pull --ff-only origin main
DEPLOY_COMMIT="$(git rev-parse HEAD)"
echo "部署 commit：${DEPLOY_COMMIT}"

rm -rf "${DIST_DIR}"
mkdir -p "${WHEEL_DIR}"

echo "== 打包 MES 源码 =="
# 直接从已提交 commit 生成归档，天然排除工作区中的配置、日志、
# 虚拟环境、数据库、备份和历史 EXE/ZIP 等未跟踪文件。
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mes-update.XXXXXX")"
trap 'rm -rf "${STAGING_DIR}"' EXIT
git archive --format=tar "${DEPLOY_COMMIT}" \
  | tar -xf - -C "${STAGING_DIR}"
find "${STAGING_DIR}" -type d \
  \( -name '.venv' -o -name '__pycache__' -o -name 'logs' -o -name 'backups' \) \
  -prune -exec rm -rf {} +
find "${STAGING_DIR}" -type f \
  \( -name '*.pyc' -o -name 'quality_control.db' -o -name 'config.ini' \) \
  -delete
tar -czf "${DIST_DIR}/mes_update.tar.gz" \
  -C "${STAGING_DIR}" \
  .

if tar -tzf "${DIST_DIR}/mes_update.tar.gz" \
  | grep -Eq '(^|/)(\.git|\.venv|__pycache__|quality_control\.db|config\.ini|logs|backups)(/|$)|\.pyc$'; then
  echo "错误：源码更新包包含禁止部署的文件。" >&2
  exit 1
fi
for required_path in \
  "./shared/plc_magnet_flow.py" \
  "./desktop_app/plc_magnet_worker.py" \
  "./web_admin_app/database.py" \
  "./web_admin_app/admin_page.py"; do
  if ! tar -tzf "${DIST_DIR}/mes_update.tar.gz" \
    | grep -Fxq "${required_path}"; then
    echo "错误：源码更新包缺少 ${required_path}。" >&2
    exit 1
  fi
done

echo "== 准备服务端离线依赖 =="
# 保留调用者要求的当前 Mac/Python 下载结果。
python3 -m pip download \
  -r requirements-server.txt \
  -d "${WHEEL_DIR}"

# Rocky Linux 9 默认是 x86_64 + CPython 3.9；额外准备对应 Linux wheel。
python3 -m pip download \
  --only-binary=:all: \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 39 \
  --abi cp39 \
  -r requirements-server.txt \
  -d "${WHEEL_DIR}"

tar -czf "${DIST_DIR}/offline_wheels.tar.gz" \
  -C "${WHEEL_DIR}" \
  .

printf '%s\n' "${DEPLOY_COMMIT}" > "${DIST_DIR}/deploy_commit.txt"
cat > "${DIST_DIR}/DEPLOY_NOTES.txt" <<EOF
commit=${DEPLOY_COMMIT}
version=v0.9.3-rc8
database_migration=steps.plc_magnet_config, plc_magnet_logs, route_based_material_binding
server_restart=mes-web
windows_artifacts=QualityControlSystem.exe, QualityControlSystem_Debug.exe
EOF

{
  sha256_file "${DIST_DIR}/mes_update.tar.gz"
  sha256_file "${DIST_DIR}/offline_wheels.tar.gz"
} | tee "${DIST_DIR}/SHA256SUMS"

echo
echo "更新包准备完成："
echo "  ${DIST_DIR}/mes_update.tar.gz"
echo "  ${DIST_DIR}/offline_wheels.tar.gz"
echo "  ${DIST_DIR}/SHA256SUMS"
echo "  ${DIST_DIR}/DEPLOY_NOTES.txt"
echo "  commit=${DEPLOY_COMMIT}"
