#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/apple/Documents/生产工艺过程质量控制系统"
DIST_DIR="${PROJECT_DIR}/dist_deploy"
SERVER_HOST="10.162.70.53"
SERVER_USER="dell"
SERVER="${SERVER_USER}@${SERVER_HOST}"

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
  "${DIST_DIR}/SHA256SUMS"; do
  if [ ! -f "${required_file}" ]; then
    echo "错误：缺少 ${required_file}" >&2
    echo "请先在外网执行 prepare_update_package.sh。" >&2
    exit 1
  fi
done

DEPLOY_COMMIT="$(tr -d '[:space:]' < "${DIST_DIR}/deploy_commit.txt")"

echo "== 本地文件 =="
echo "commit=${DEPLOY_COMMIT}"
echo "mes_update=$(sha256_value "${DIST_DIR}/mes_update.tar.gz")"
echo "offline_wheels=$(sha256_value "${DIST_DIR}/offline_wheels.tar.gz")"

echo "== 检查 SSH =="
ssh -o ConnectTimeout=8 "${SERVER}" "echo SSH_OK"

echo "== 仅上传文件，不执行任何服务器部署命令 =="
scp "${DIST_DIR}/mes_update.tar.gz" "${SERVER}:/home/dell/"
scp "${DIST_DIR}/offline_wheels.tar.gz" "${SERVER}:/home/dell/"
scp "${DIST_DIR}/deploy_commit.txt" "${SERVER}:/home/dell/"
scp "${DIST_DIR}/SHA256SUMS" "${SERVER}:/home/dell/"

echo
echo "上传完成，脚本到此结束。"
echo "服务器文件："
echo "  /home/dell/mes_update.tar.gz"
echo "  /home/dell/offline_wheels.tar.gz"
echo "  /home/dell/deploy_commit.txt"
echo "  /home/dell/SHA256SUMS"
echo "后续请手工 SSH 登录服务器执行备份、更新、迁移和重启。"
