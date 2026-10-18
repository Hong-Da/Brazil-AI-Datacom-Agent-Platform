"""检查规则的开关与级别（界面与 CLI 共用）：写回运行时知识库的 rules/ 并提交一次。

- 知识库规则：在所在的规则文件里改这条规则的 enabled / severity（ruamel 往返写回，保留注释与顺序）；
- 内置检查：写入覆盖文件 rules/builtin.yaml（{builtin: {规则: {enabled, severity}}}），内置检查的定义不变。
写入后重新加载全部规则校验，出错时恢复原文件，知识库不会处在半坏的状态。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap

from lmesh.core import checks
from lmesh.core import rules as rulesmod
from lmesh.core.kb import KnowledgeBase, files, repo

_HEADER = (
    "内置检查的开关与级别（界面或 lmesh rules set 写入）；内置检查本身的定义在程序里，这里只覆盖 enabled / severity。"
)


class RuleEditError(ValueError):
    """key 是文案键；kind 为 param（参数错误）或 not_found（规则不存在）。"""

    def __init__(self, key: str, kind: str = "param", **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.fmt = key, kind, fmt


def ensure_rules_dir(kb_root: Path) -> Path:
    """运行时知识库的 rules/；早于 M2 复制出的知识库没有时，先复制程序自带的规则再写，避免丢掉通用规则。"""
    own = kb_root / "rules"
    if not own.exists():
        from lmesh import paths

        builtin = paths.builtin_knowledge_dir() / "rules"
        if builtin.is_dir() and builtin.resolve() != own.resolve():
            shutil.copytree(builtin, own)
        else:
            own.mkdir(parents=True, exist_ok=True)
    return own


def rule_view(kb: KnowledgeBase, directory: Path, rule_id: str) -> dict[str, Any] | None:
    """规则列表中的一条（与 GET /kb/rules 的结构相同）。"""
    return next((r for r in checks.list_rules(kb, directory)["rules"] if r["id"] == rule_id), None)


def _find(directory: Path, rule_id: str) -> tuple[Path, Any, CommentedMap] | None:
    for f in sorted(directory.glob("*.yaml")):
        if f.name == rulesmod.BUILTIN_FILE:
            continue
        doc = files.load_rt(f)
        for item in (doc or {}).get("rules") or []:
            if isinstance(item, CommentedMap) and str(item.get("id")) == rule_id:
                return f, doc, item
    return None


@repo.locked
def set_rule(
    kb_root: Path, kb: KnowledgeBase, rule_id: str, enabled: bool | None = None, severity: str | None = None
) -> dict[str, Any]:
    if enabled is None and severity is None:
        raise RuleEditError("rules.edit_empty")
    if severity is not None and severity not in rulesmod.SEVERITIES:
        raise RuleEditError("check.bad_severity")
    directory = ensure_rules_dir(kb_root)
    if rule_id in checks.BUILTIN:
        path = directory / rulesmod.BUILTIN_FILE
        doc = files.load_rt(path) if path.exists() else None
        if not isinstance(doc, CommentedMap):
            doc = CommentedMap()
            doc.yaml_set_start_comment(_HEADER)
        table = doc.get("builtin")
        if not isinstance(table, CommentedMap):
            table = doc["builtin"] = CommentedMap()
        entry = table.get(rule_id)
        if not isinstance(entry, CommentedMap):
            entry = table[rule_id] = CommentedMap()
    else:
        hit = _find(directory, rule_id)
        if hit is None:
            raise RuleEditError("rules.not_found", "not_found", rule=rule_id)
        path, doc, entry = hit
    before = path.read_bytes() if path.exists() else None
    if enabled is not None:
        entry["enabled"] = enabled
    if severity is not None:
        entry["severity"] = severity
    files.dump_rt(path, doc)
    try:
        rulesmod.load_dir(kb, directory)
        checks.load_overrides(directory)
    except rulesmod.RuleError:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(before)
        raise
    changes = ", ".join(f"{k}={v}" for k, v in (("enabled", enabled), ("severity", severity)) if v is not None)
    if (kb_root / ".git").exists():
        repo.commit_all(kb_root, f"修改检查规则 {rule_id}：{changes}")
    view = rule_view(kb, directory, rule_id)
    assert view is not None
    return view
