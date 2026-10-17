#!/usr/bin/env bash
# 工具链与缓存位置：所有脚本先加载它（. scripts/env.sh），只设置环境变量和 PATH。
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export LMESH_ROOT="$ROOT"
export PYTHONUTF8=1

# Python（uv）：下载缓存、解释器、工具都放在项目内
export UV_CACHE_DIR="$ROOT/.toolchain/cache/uv"
export UV_PYTHON_INSTALL_DIR="$ROOT/.toolchain/runtime/python"
export UV_PYTHON_PREFERENCE=only-managed
export UV_TOOL_DIR="$ROOT/.toolchain/uv-tools"
# start 脚本安装 uv 时装到项目内
export UV_INSTALL_DIR="$ROOT/.toolchain/bin"
[ -d "$ROOT/.toolchain/bin" ] && export PATH="$ROOT/.toolchain/bin:$PATH"

# Node（只用于构建前端）：运行时与缓存放在项目内；pnpm store 写在 frontend/.npmrc
export npm_config_cache="$ROOT/.toolchain/cache/npm"
export COREPACK_HOME="$ROOT/.toolchain/cache/corepack"
if [ -d "$ROOT/.toolchain/runtime/node/bin" ]; then
  export PATH="$ROOT/.toolchain/runtime/node/bin:$PATH"
fi
