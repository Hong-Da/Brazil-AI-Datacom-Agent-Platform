#!/usr/bin/env bash
# 透网 LucidMesh 一键运行（Linux）
# 用法：./start.sh [--check] [--setup [--defaults]] [--reinstall] [--port 端口]
#   --check      只做环境检查与依赖准备，不启动
#   --setup      重新进入配置向导（Web 向导；加 --defaults 时直接采用默认值与环境变量）
#   --reinstall  删除依赖目录后重新安装
#   --port       临时覆盖监听端口（不改配置文件）
set -uo pipefail
cd "$(dirname "$0")" || exit 1
. scripts/env.sh
mkdir -p logs
LOG="logs/start.log"
exec > >(tee -a "$LOG") 2>&1
echo "==== $(date '+%Y-%m-%d %H:%M:%S') start.sh $* ===="

CHECK=0; SETUP=0; DEFAULTS=0; REINSTALL=0; PORT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --check) CHECK=1 ;;
    --setup) SETUP=1 ;;
    --defaults) DEFAULTS=1 ;;
    --reinstall) REINSTALL=1 ;;
    --port) shift; PORT="${1:-}" ;;
    *) echo "未知参数：$1"; exit 2 ;;
  esac
  shift
done

die() { echo "失败：$1"; echo "处理建议：$2"; echo "详细记录见 $LOG"; exit 1; }

echo "[1/6] 检查 uv ……"
if ! command -v uv >/dev/null 2>&1; then
  if [ -t 0 ]; then
    read -r -p "没有找到 uv（Python 包管理器），现在安装吗？[Y/n] " ans
    case "${ans:-Y}" in
      [Yy]*) mkdir -p "$UV_INSTALL_DIR"
             curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh || die "uv 安装失败" "检查网络，或参考 https://docs.astral.sh/uv/ 手动安装"
             export PATH="$UV_INSTALL_DIR:$PATH" ;;
      *) die "需要 uv" "安装 uv 后重新运行 ./start.sh" ;;
    esac
  else
    die "没有找到 uv" "在终端中运行 ./start.sh 按提示安装（装到项目内的 .toolchain/bin/），或自行安装 uv 后重试"
  fi
fi
echo "      $(uv --version)"

echo "[2/6] 准备 Python 环境与依赖 ……"
[ "$REINSTALL" = 1 ] && rm -rf .venv frontend/node_modules
OFFLINE=""
[ -f .toolchain/offline ] && OFFLINE="--offline"
uv sync --frozen $OFFLINE || die "依赖安装失败" "检查网络或镜像源（UV_INDEX_URL），然后用 --reinstall 重试"

echo "[3/6] 准备 Web 界面 ……"
if ! uv run --no-project python scripts/build_frontend.py --check >/dev/null 2>&1; then
  uv run --no-project python scripts/ensure_node.py || die "Node 准备失败" "检查网络，或设置 LMESH_NODE_MIRROR 指定镜像"
  uv run --no-project python scripts/build_frontend.py || die "前端构建失败" "用 --reinstall 重试；仍失败时查看上面的 pnpm 输出"
else
  echo "      已是最新"
fi

echo "[4/6] 检查配置 ……"
if [ "$SETUP" = 1 ] && [ -f config/config.toml ]; then
  bak="config/config.toml.bak-$(date +%Y%m%d%H%M%S)"
  mv config/config.toml "$bak" && echo "      原配置已备份为 $bak"
fi
if [ "$SETUP" = 1 ] && [ "$DEFAULTS" = 1 ]; then
  uv run lmesh setup --defaults || die "配置失败" "检查环境变量中的配置值"
fi
if [ -f config/config.toml ]; then echo "      已配置"; else echo "      尚未配置：启动后在浏览器中完成向导"; fi

echo "[5/6] 检查数据库 ……"
if [ -f config/config.toml ]; then
  uv run lmesh db upgrade || die "数据库升级失败" "检查 config/config.toml 中的 [database] url"
else
  echo "      配置完成后自动初始化"
fi

if [ "$CHECK" = 1 ]; then
  echo "[6/6] 检查完成（--check，不启动）"
  uv run lmesh status
  exit 0
fi

echo "[6/6] 启动 ……"
if [ -n "$PORT" ]; then exec uv run lmesh serve --port "$PORT"; else exec uv run lmesh serve; fi
