#!/usr/bin/env bash
# 生成发布包到 dist/<版本>/（Linux：离线安装包 tar.gz 与 Docker 镜像）
# 用法：scripts/build_release.sh [版本号] [--targets linux,docker] [--skip-frontend]
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/env.sh
exec uv run --no-project python scripts/build_release.py "$@"
