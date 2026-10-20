#!/usr/bin/env bash
# 透网 LucidMesh 启动（Linux 离线包：自带 Python 运行时与依赖，不需要联网）
# 用法：./start.sh [--check] [--setup] [--port 端口]
#   --check  只检查（版本、配置、数据库、知识库），不启动
#   --setup  在命令行里完成首次配置（不加时启动后在浏览器中完成向导）
#   --port   临时覆盖监听端口（不改配置文件）
# 装成系统服务请用 install.sh。
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")" || exit 1
LM="./bin/lmesh"
mkdir -p logs
LOG="logs/start.log"
echo "==== $(date '+%Y-%m-%d %H:%M:%S') start.sh $* ====" >> "$LOG"

CHECK=0; SETUP=0; PORT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --check) CHECK=1 ;;
    --setup) SETUP=1 ;;
    --port) shift; PORT="${1:-}" ;;
    *) echo "未知参数：$1"; exit 2 ;;
  esac
  shift
done
die() { echo "失败：$1"; echo "处理建议：$2"; echo "失败：$1" >> "$LOG"; exit 1; }

echo "[1/3] 检查配置 ……"
if [ "$SETUP" = 1 ] && [ ! -f config/config.toml ]; then
  "$LM" setup || die "配置失败" "按提示重新填写；或不加 --setup 启动后在浏览器中完成向导"
fi
if [ -f config/config.toml ]; then echo "      已配置"; else echo "      尚未配置：启动后在浏览器中完成向导"; fi

echo "[2/3] 检查数据库与知识库 ……"
if [ -f config/config.toml ]; then
  "$LM" db upgrade >> "$LOG" 2>&1 || die "数据库升级失败" "检查 config/config.toml 中的 [database] url；详见 $LOG"
  echo "      数据库已是最新"
else
  echo "      配置完成后自动初始化"
fi

if [ "$CHECK" = 1 ]; then
  echo "[3/3] 检查完成（--check，不启动）"
  exec "$LM" status
fi
echo "[3/3] 启动 ……（按 Ctrl+C 停止）"
if [ -n "$PORT" ]; then exec "$LM" serve --port "$PORT"; else exec "$LM" serve; fi
