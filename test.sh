#!/usr/bin/env bash
# 透网 LucidMesh 一键测试（Linux）：./test.sh [--unit|--cli|--api|--docs|--roundtrip|--frontend|--e2e] [--changed [REF]] [-n N|--serial] [--max-workers N] [--live --base-url URL --token TOKEN]
cd "$(dirname "$0")" || exit 1
. scripts/env.sh
uv sync --frozen -q || { echo "依赖安装失败：先运行 ./start.sh --check"; exit 1; }
exec uv run python scripts/run_tests.py "$@"
