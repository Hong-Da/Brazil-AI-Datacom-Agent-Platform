#!/usr/bin/env bash
# 透网 LucidMesh Linux 卸载（安装目录里的 uninstall.sh）
#
# 用法：sudo ./uninstall.sh [选项]
#   --prefix DIR   安装目录（默认本脚本所在目录）
#   --keep         保留配置与数据（config/ data/ logs/ backup/），只删除程序文件（不提问时的默认）
#   --purge        连同配置与数据一起删除
#   --yes          不提问
#   --dry-run      只列出将要执行的操作
# 注册了 systemd 服务时先停止并移除；创建的系统用户不删除（需要时自行 userdel）。
set -euo pipefail

PREFIX="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"; KEEP=""; YES=0; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) shift; PREFIX="$(cd "${1:?--prefix 需要目录}" && pwd)" ;;
    --keep) KEEP=1 ;;
    --purge) KEEP=0 ;;
    --yes|-y) YES=1 ;;
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "未知参数：$1（--help 查看用法）"; exit 2 ;;
  esac
  shift
done
[ -f "$PREFIX/VERSION" ] && [ -d "$PREFIX/runtime" ] || { echo "失败：$PREFIX 不是 LucidMesh 安装目录" >&2; exit 1; }
do_() { if [ "$DRY" = 1 ]; then echo "  [dry-run] $*"; else "$@"; fi; }
say() { echo "==> $*"; }

if [ -z "$KEEP" ]; then
  KEEP=1
  if [ "$YES" != 1 ] && [ -t 0 ]; then
    read -r -p "保留配置与数据（config、data、logs、backup）吗？[Y/n] " a
    case "${a:-Y}" in [Nn]*) KEEP=0 ;; esac
  fi
fi

UNIT=/etc/systemd/system/lmesh.service
if [ -f "$UNIT" ] && grep -q "ExecStart=$PREFIX/" "$UNIT"; then
  [ "$(id -u)" = 0 ] || { echo "失败：移除 systemd 服务需要 root，请用 sudo 运行" >&2; exit 1; }
  say "停止并移除服务 lmesh"
  do_ systemctl disable --now lmesh || true
  do_ rm -f "$UNIT"
  do_ systemctl daemon-reload
fi
if [ -L /usr/local/bin/lmesh ] && [ "$(readlink /usr/local/bin/lmesh)" = "$PREFIX/bin/lmesh" ]; then
  say "删除命令链接 /usr/local/bin/lmesh"; do_ rm -f /usr/local/bin/lmesh
fi

say "删除程序文件"
for d in runtime src knowledge assets docs bin cache tmp; do do_ rm -rf "${PREFIX:?}/$d"; done
for f in VERSION pyproject.toml start.sh README.txt config/config.example.toml; do do_ rm -f "$PREFIX/$f"; done
if [ "$KEEP" = 1 ]; then
  say "已保留配置与数据：$PREFIX/{config,data,logs,backup}；重新运行 install.sh --prefix $PREFIX 即可继续使用"
  do_ rm -f "$PREFIX/uninstall.sh"
else
  say "删除配置与数据"
  for d in config data logs backup; do do_ rm -rf "${PREFIX:?}/$d"; done
  do_ rm -f "$PREFIX/uninstall.sh"
  do_ rmdir "$PREFIX" 2>/dev/null || true
fi
say "卸载完成"
