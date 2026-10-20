#!/usr/bin/env bash
# 透网 LucidMesh Linux 离线安装 / 升级（在解压后的离线包目录里运行，不需要联网）
#
# 用法：sudo ./install.sh [选项]
#   --prefix DIR     安装目录（默认 /opt/lmesh；不用 root 时请指定自己有写权限的目录，例如 ~/.local/opt/lmesh）
#   --user NAME      以该系统用户运行服务、拥有 data/ config/ logs/（不给时用当前用户）
#   --create-user    --user 指定的用户不存在时创建（系统用户，不能登录）
#   --no-systemd     不注册 systemd 服务（默认：root 且有 systemd 时注册并启动 lmesh.service）
#   --no-link        不建立 /usr/local/bin/lmesh 命令链接（默认 root 时建立）
#   --setup          首次安装后在命令行里完成配置（lmesh setup）；不加时启动后在浏览器中完成向导
#   --yes            不提问（同版本重装、升级都直接继续）
#   --dry-run        只列出将要执行的操作，不做任何改动
#
# 已安装时自动按升级处理：停止服务 → 备份 SQLite 数据库与配置到 backup/ → 替换程序文件（保留 data/ config/ logs/）
# → 数据库迁移（lmesh db upgrade）→ 合并新版本自带的知识库（lmesh kb upgrade）→ 启动服务。
set -euo pipefail

SRC="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
VERSION="$(cat "$SRC/VERSION")"
PREFIX="/opt/lmesh"; RUN_USER=""; CREATE_USER=0; SYSTEMD=auto; LINK=auto; SETUP=0; YES=0; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) shift; PREFIX="${1:?--prefix 需要目录}" ;;
    --user) shift; RUN_USER="${1:?--user 需要用户名}" ;;
    --create-user) CREATE_USER=1 ;;
    --no-systemd) SYSTEMD=0 ;;
    --no-link) LINK=0 ;;
    --setup) SETUP=1 ;;
    --yes|-y) YES=1 ;;
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "未知参数：$1（--help 查看用法）"; exit 2 ;;
  esac
  shift
done
PREFIX="$(realpath -m "$PREFIX")"
IS_ROOT=0; [ "$(id -u)" = 0 ] && IS_ROOT=1
if [ "$SYSTEMD" = auto ]; then
  SYSTEMD=0; [ "$IS_ROOT" = 1 ] && command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ] && SYSTEMD=1
fi
[ "$LINK" = auto ] && LINK=$IS_ROOT
UNIT=/etc/systemd/system/lmesh.service

say() { echo "==> $*"; }
die() { echo "失败：$1" >&2; [ -n "${2:-}" ] && echo "处理建议：$2" >&2; exit 1; }
do_() { if [ "$DRY" = 1 ]; then echo "  [dry-run] $*"; else "$@"; fi; }
ask() {  # ask 问题 → 0 表示是
  [ "$YES" = 1 ] && return 0
  [ -t 0 ] || die "需要确认：$1" "加 --yes 不提问"
  local a; read -r -p "$1 [Y/n] " a; case "${a:-Y}" in [Yy]*) return 0 ;; *) return 1 ;; esac
}
as_user() {  # 以服务用户执行（root 且指定了 --user 时）
  if [ -n "$RUN_USER" ] && [ "$IS_ROOT" = 1 ]; then do_ runuser -u "$RUN_USER" -- "$@"; else do_ "$@"; fi
}

# ---------- 检查 ----------
[ "$(uname -m)" = x86_64 ] || die "本安装包只支持 x86_64（当前 $(uname -m)）"
[ -x "$SRC/runtime/python/bin/python3" ] || die "安装包不完整：缺少 runtime/python" "重新解压安装包"
if [ "$SRC" = "$PREFIX" ]; then die "不能安装到安装包自己的目录" "用 --prefix 指定其他目录"; fi
EXIST="$PREFIX"; while [ ! -e "$EXIST" ]; do EXIST="$(dirname "$EXIST")"; done  # 最近的已存在上级目录
if [ ! -w "$EXIST" ]; then
  die "没有写入 $PREFIX 的权限" "用 sudo 运行，或用 --prefix 指定自己有写权限的目录"
fi
if [ "$SYSTEMD" = 1 ] && [ "$IS_ROOT" != 1 ]; then die "注册 systemd 服务需要 root" "用 sudo 运行，或加 --no-systemd"; fi
if [ -n "$RUN_USER" ] && ! id "$RUN_USER" >/dev/null 2>&1; then
  [ "$CREATE_USER" = 1 ] || die "用户 $RUN_USER 不存在" "加 --create-user 创建，或先自行创建"
  [ "$IS_ROOT" = 1 ] || die "创建用户需要 root"
fi
need_kb=$(du -sk "$SRC" | cut -f1)
free_kb=$(df -Pk "$EXIST" | awk 'NR==2{print $4}')
[ "${free_kb:-0}" -gt "$((need_kb + 51200))" ] || die "磁盘空间不足：需要约 $((need_kb / 1024 + 50)) MB，可用 $((free_kb / 1024)) MB"

OLD=""; [ -f "$PREFIX/VERSION" ] && OLD="$(cat "$PREFIX/VERSION")"
if [ -z "$OLD" ]; then
  say "全新安装 LucidMesh $VERSION 到 $PREFIX"
  if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE '[:.]9090$'; then
    echo "  提示：端口 9090 已被占用。安装后在向导里改用其他端口，或设置环境变量 LMESH_SERVER__PORT。"
  fi
elif [ "$OLD" = "$VERSION" ]; then
  ask "已安装同一版本 $VERSION，重新安装（修复）吗？配置与数据保留。" || exit 1
else
  say "升级：$OLD → $VERSION（配置与数据保留）"
  newest="$(printf '%s\n%s\n' "$OLD" "$VERSION" | sort -V | tail -1)"
  if [ "$newest" = "$OLD" ]; then ask "要安装的版本 $VERSION 比已安装的 $OLD 旧，降级可能导致数据库不兼容。继续吗？" || exit 1; fi
fi
[ "$DRY" = 1 ] && say "dry-run：只列出操作，不做改动"

# ---------- 升级前：停止服务、备份 ----------
if [ -n "$OLD" ]; then
  if [ "$IS_ROOT" = 1 ] && command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet lmesh 2>/dev/null; then
    say "停止服务 lmesh"; do_ systemctl stop lmesh
  fi
  stamp="$(date +%Y%m%d%H%M%S)"
  do_ mkdir -p "$PREFIX/backup"
  if [ -f "$PREFIX/data/lmesh.db" ]; then
    say "备份 SQLite 数据库 → backup/lmesh-$OLD-$stamp.db"
    do_ cp -a "$PREFIX/data/lmesh.db" "$PREFIX/backup/lmesh-$OLD-$stamp.db"
  fi
  if [ -d "$PREFIX/config" ]; then
    say "备份配置 → backup/config-$OLD-$stamp.tar.gz"
    do_ tar -C "$PREFIX" -czf "$PREFIX/backup/config-$OLD-$stamp.tar.gz" config
  fi
  echo "  使用 PostgreSQL 时，请另行用 pg_dump 备份数据库。"
fi

# ---------- 复制程序文件 ----------
say "复制程序文件"
do_ mkdir -p "$PREFIX"
for d in runtime src knowledge assets docs bin; do
  do_ rm -rf "${PREFIX:?}/$d"
  do_ cp -a "$SRC/$d" "$PREFIX/$d"
done
for f in VERSION pyproject.toml start.sh uninstall.sh README.txt; do
  [ -f "$SRC/$f" ] && do_ cp -a "$SRC/$f" "$PREFIX/$f"
done
do_ mkdir -p "$PREFIX/config" "$PREFIX/data" "$PREFIX/logs" "$PREFIX/cache" "$PREFIX/tmp/os"
do_ cp -a "$SRC/config/config.example.toml" "$PREFIX/config/config.example.toml"

if [ -n "$RUN_USER" ]; then
  if ! id "$RUN_USER" >/dev/null 2>&1; then
    say "创建系统用户 $RUN_USER"
    do_ useradd --system --home-dir "$PREFIX" --no-create-home --shell /usr/sbin/nologin "$RUN_USER"
  fi
  do_ chown -R "$RUN_USER:" "$PREFIX/config" "$PREFIX/data" "$PREFIX/logs" "$PREFIX/cache" "$PREFIX/tmp"
  [ -d "$PREFIX/backup" ] && do_ chown -R "$RUN_USER:" "$PREFIX/backup"
fi
if [ "$LINK" = 1 ]; then
  say "命令链接 /usr/local/bin/lmesh"; do_ ln -sfn "$PREFIX/bin/lmesh" /usr/local/bin/lmesh
fi

# ---------- 配置、数据库迁移、知识库合并 ----------
if [ -f "$PREFIX/config/config.toml" ]; then
  say "数据库迁移"; as_user "$PREFIX/bin/lmesh" --yes db upgrade
  say "合并新版本自带的知识库（双方都改过的文件送审核队列）"; as_user "$PREFIX/bin/lmesh" --yes kb upgrade
elif [ "$SETUP" = 1 ]; then
  say "首次配置（命令行向导）"; as_user "$PREFIX/bin/lmesh" setup
fi

# ---------- systemd ----------
if [ "$SYSTEMD" = 1 ]; then
  say "注册 systemd 服务 lmesh.service"
  unit="[Unit]
Description=LucidMesh network configuration graph
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
${RUN_USER:+User=$RUN_USER
}WorkingDirectory=$PREFIX
ExecStart=$PREFIX/bin/lmesh serve
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target"
  if [ "$DRY" = 1 ]; then echo "  [dry-run] 写入 $UNIT："; echo "$unit" | sed 's/^/    /'; else echo "$unit" > "$UNIT"; fi
  do_ systemctl daemon-reload
  do_ systemctl enable lmesh
  do_ systemctl restart lmesh
fi

echo
if [ "$DRY" = 1 ]; then say "dry-run 结束：以上操作都没有执行"; exit 0; fi
say "完成：LucidMesh $VERSION 已安装到 $PREFIX"
if [ "$SYSTEMD" = 1 ]; then
  echo "  服务：systemctl status lmesh；日志：journalctl -u lmesh 与 $PREFIX/logs/"
else
  echo "  启动：$PREFIX/start.sh（前台运行）"
fi
[ -f "$PREFIX/config/config.toml" ] || echo "  首次配置：启动后用浏览器打开 http://<本机地址>:9090 完成向导，或运行 $PREFIX/bin/lmesh setup"
echo "  卸载：$PREFIX/uninstall.sh（默认保留配置与数据）"
