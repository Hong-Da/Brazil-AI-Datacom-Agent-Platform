#!/usr/bin/env bash
# 版本检查：每次打开 Claude Code 会话时由 SessionStart 钩子运行，输出会作为上下文交给 Claude。
# 列出上次版本标签之后尚未打版本的提交、未提交的改动，以及进度中已完成却没有版本号的条目。
# 由 project-dev-spec 生成；Windows 上 Claude Code 通过 Git Bash 运行本脚本。
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/..}" || exit 0
command -v git >/dev/null 2>&1 || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

msgs=()
tag=$(git describe --tags --abbrev=0 2>/dev/null)
if [ -z "$tag" ]; then
  msgs+=("还没有打过版本标签。")
else
  n=$(git rev-list --count "$tag"..HEAD 2>/dev/null || echo 0)
  [ "$n" -gt 0 ] && msgs+=("上次版本 $tag 之后有 $n 个提交还没有打版本。")
fi
dirty=$(git status --porcelain 2>/dev/null | grep -c .)
[ "$dirty" -gt 0 ] && msgs+=("有 $dirty 个文件改动尚未提交。")

progress="DevelopDocs/progress/progress.json"
if [ -f "$progress" ]; then
  py=$(command -v python3 || command -v python || true)
  if [ -n "$py" ]; then
    items=$("$py" - "$progress" <<'PY' 2>/dev/null
import json, sys
p = json.load(open(sys.argv[1], encoding="utf-8"))
done = {"done", "accepted"}
out = [s["id"] for m in p.get("milestones") or [] for s in m.get("stages") or [] if s.get("status") in done and not s.get("version")]
out += [r["id"] for r in p.get("requirements") or [] if r.get("status") in done and not r.get("version")]
print("、".join(out))
PY
)
    [ -n "$items" ] && msgs+=("已完成但还没有版本号：$items。")
  fi
fi

if [ ${#msgs[@]} -gt 0 ]; then
  echo "【版本检查】${msgs[*]} 请按项目记忆中的版本规则，在第一条回复中提醒用户是否需要打版本（先问再打）。"
fi

# 决策记录：Claude 替用户做的决定中还有没查看的，提醒用户
decisions="DevelopDocs/decisions/decisions.json"
if [ -f "$decisions" ]; then
  py=$(command -v python3 || command -v python || true)
  if [ -n "$py" ]; then
    dc=$("$py" - "$decisions" <<'PY' 2>/dev/null
import json, sys
e = json.load(open(sys.argv[1], encoding="utf-8")).get("entries") or []
o = [x for x in e if x.get("status") in ("pending", "revert_requested")]
r = sum(1 for x in o if x.get("status") == "revert_requested")
m = sum(1 for x in o if x.get("mustConfirm"))
print(f"{len(o)} {r} {m}" if o else "")
PY
)
    if [ -n "$dc" ]; then
      set -- $dc
      extra=""
      [ "$3" -gt 0 ] && extra="其中 $3 条本应由用户确认，"
      [ "$2" -gt 0 ] && extra="${extra}用户要求改回 $2 条（先处理这些），"
      echo "【决策记录】有 $1 条 Claude 替用户做的决定待查看，${extra}见 DevelopDocs/decisions/decisions.html。请在第一条回复中告诉用户。"
    fi
  fi
fi
exit 0
