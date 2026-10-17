#!/usr/bin/env bash
# 透网 LucidMesh 命令行包装（Linux）：在任意目录调用 ./cli.sh <参数>，等同于 lmesh <参数>
ROOT="$(cd "$(dirname "$0")" && pwd)"
. "$ROOT/scripts/env.sh"
exec uv run --project "$ROOT" --frozen -q lmesh "$@"
