#!/usr/bin/env bash
# 开发辅助：把本机代码同步到 Linux 测试机的工作目录（本机为准；Linux 上的 config/ 与 data/ 不被覆盖）。
# 用法：scripts/linux_sync.sh [用户@地址] [工作目录]
# 默认读取环境变量 LMESH_LINUX_HOST（root@linux-test-host）、LMESH_LINUX_DIR（lmesh）、LMESH_LINUX_KEY（~/.ssh/lmesh_dev_ed25519）。
set -euo pipefail
cd "$(dirname "$0")/.."
HOST="${1:-${LMESH_LINUX_HOST:-root@linux-test-host}}"
DIR="${2:-${LMESH_LINUX_DIR:-lmesh}}"
KEY="${LMESH_LINUX_KEY:-$HOME/.ssh/lmesh_dev_ed25519}"
SSH=(ssh -i "$KEY" -o BatchMode=yes "$HOST")

tar czf - \
  --exclude=./.git --exclude=./.venv --exclude=./.toolchain --exclude=./frontend/node_modules \
  --exclude=./data --exclude=./logs --exclude=./cache --exclude=./tmp --exclude=./dist \
  --exclude=./tests/output --exclude=./config --exclude=./DevelopDocs --exclude=./src/lmesh/web/static \
  --exclude='__pycache__' --exclude=./.pytest_cache --exclude=./.mypy_cache --exclude=./.ruff_cache \
  . | "${SSH[@]}" "mkdir -p ~/$DIR/config && tar xzf - -C ~/$DIR"

# 示例配置要同步（config/ 其余内容以 Linux 上的为准）
"${SSH[@]}" "cat > ~/$DIR/config/config.example.toml" < config/config.example.toml
echo "已同步到 $HOST:~/$DIR"
