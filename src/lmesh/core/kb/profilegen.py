"""Profile 汇总：由已映射的命令卡生成 Profile 条目（支持情况、渲染所用命令卡）。

- 只为没有继承关系的基础 Profile 汇总（子 Profile 只写差异，由人工维护）。
- 人工条目（manual: true）原样保留：条件化默认值、文档以外的实测默认值等；自动汇总只补上 cards 列表。
- 该平台族有命令卡映射到的节点记为 supported；没有映射到的节点不写（覆盖矩阵中显示为“未填写”）。
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap

from lmesh.core import kb as kbmod
from lmesh.core.kb import files as kbfiles
from lmesh.core.kb import mapping


def generate(kb_root: Path, families: list[str] | None = None) -> dict[str, Any]:
    """families：只汇总这些平台族的 Profile（不给时全部）。"""
    kb = kbmod.load(kb_root)
    by_family: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for c in kb.cards.values():
        if c.status == "rejected":
            continue
        for target in c.maps:
            if mapping.is_directive(target):
                continue
            for t in mapping.parse_target(target):
                by_family[c.family][t.node].append(c.id)
                for obj in t.fixed:
                    by_family[c.family][obj].append(c.id)
    stats: dict[str, Any] = {}
    for p in kb.profiles.values():
        if p.inherits or (families and p.family not in families):
            continue
        f = kb_root / p.file
        doc = kbfiles.load_rt(f)
        old = doc.get("entries") or {}
        entries = CommentedMap()
        nodes = by_family.get(p.family, {})
        for node in sorted(set(nodes) | {k for k, v in old.items() if (v or {}).get("manual")}):
            prev = dict(old.get(node) or {})
            e = CommentedMap()
            if prev.get("manual"):
                for k, v in prev.items():
                    e[k] = v
            else:
                e["supported"] = True
            cards = sorted(set(nodes.get(node, [])))
            if cards:
                e["cards"] = cards
            entries[node] = e
        doc["entries"] = entries
        kbfiles.dump_rt(f, doc)
        stats[p.id] = {"entries": len(entries), "manual": sum(1 for v in entries.values() if v.get("manual"))}
    return stats
