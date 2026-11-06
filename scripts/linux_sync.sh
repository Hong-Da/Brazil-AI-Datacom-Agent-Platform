#!/usr/bin/env bash
# 开发辅助：把本机代码同步到 Linux 测试机的工作目录（本机为准；Linux 上的 config/ 与 data/ 不被覆盖）。
# 用法：scripts/linux_sync.sh [用户@地址] [工作目录]
# 读取环境变量 LMESH_LINUX_HOST（用户@地址，必填）、LMESH_LINUX_DIR（默认 lmesh）、LMESH_LINUX_KEY（默认 ~/.ssh/lmesh_dev_ed25519）；
# 也可以写在 config/linux.env（不入库），例如 LMESH_LINUX_HOST=user@linux-test-host。
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
[ -f config/linux.env ] && . config/linux.env
HOST="${1:-${LMESH_LINUX_HOST:-}}"
[ -n "$HOST" ] || { echo "请设置 LMESH_LINUX_HOST（或写入 config/linux.env），或把 用户@地址 作为第一个参数" >&2; exit 2; }
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
