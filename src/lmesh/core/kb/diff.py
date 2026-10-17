"""两个知识库版本的差异（节点级）与建议的版本号升级。

版本规则（任务文档）：删除节点或修改语义 → 主版本；新增节点 → 次版本；修正默认值或渲染模板 → 修订号。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lmesh.core.kb import KnowledgeBase


@dataclass
class KbDiff:
    nodes_added: list[str] = field(default_factory=list)
    nodes_removed: list[str] = field(default_factory=list)
    nodes_semantic: list[str] = field(default_factory=list)  # 语义或类型变化
    nodes_deprecated: list[str] = field(default_factory=list)
    cards_added: list[str] = field(default_factory=list)
    cards_removed: list[str] = field(default_factory=list)
    cards_changed: list[str] = field(default_factory=list)
    defaults_changed: list[dict[str, Any]] = field(default_factory=list)  # {profile, node, old, new}
    profiles_added: list[str] = field(default_factory=list)

    def empty(self) -> bool:
        return not any(getattr(self, f) for f in self.__dataclass_fields__)

    def bump(self) -> str:
        if self.nodes_removed or self.nodes_semantic:
            return "major"
        if self.nodes_added or self.profiles_added or self.cards_added:
            return "minor"
        return "patch"

    def as_dict(self) -> dict[str, Any]:
        d = {f: getattr(self, f) for f in self.__dataclass_fields__}
        d["suggested_bump"] = self.bump()
        return d


def compare(old: KnowledgeBase, new: KnowledgeBase) -> KbDiff:
    d = KbDiff()
    d.nodes_added = sorted(set(new.nodes) - set(old.nodes))
    d.nodes_removed = sorted(set(old.nodes) - set(new.nodes))
    for nid in sorted(set(old.nodes) & set(new.nodes)):
        a, b = old.nodes[nid], new.nodes[nid]
        if a.semantic != b.semantic or a.type != b.type or a.parent != b.parent or a.key != b.key:
            d.nodes_semantic.append(nid)
        if b.deprecated and not a.deprecated:
            d.nodes_deprecated.append(nid)
    d.cards_added = sorted(set(new.cards) - set(old.cards))
    d.cards_removed = sorted(set(old.cards) - set(new.cards))
    for cid in sorted(set(old.cards) & set(new.cards)):
        ca, cb = old.cards[cid], new.cards[cid]
        if (ca.syntax, ca.view, ca.params, ca.maps, ca.default, ca.status) != (
            cb.syntax,
            cb.view,
            cb.params,
            cb.maps,
            cb.default,
            cb.status,
        ):
            d.cards_changed.append(cid)
    d.profiles_added = sorted(set(new.profiles) - set(old.profiles))
    for pid in sorted(set(old.profiles) & set(new.profiles)):
        oe, ne = old.profiles[pid].entries, new.profiles[pid].entries
        for node in sorted(set(oe) | set(ne)):
            ov = oe[node].default if node in oe else None
            nv = ne[node].default if node in ne else None
            if ov != nv:
                d.defaults_changed.append({"profile": pid, "node": node, "old": ov, "new": nv})
    return d


def next_version(current: str, bump: str) -> str:
    parts = [int(x) for x in (current.split(".") + ["0", "0", "0"])[:3]]
    if bump == "major":
        return f"{parts[0] + 1}.0.0"
    if bump == "minor":
        return f"{parts[0]}.{parts[1] + 1}.0"
    return f"{parts[0]}.{parts[1]}.{parts[2] + 1}"
