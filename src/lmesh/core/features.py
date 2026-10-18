"""特性能力查询（M5-4）：某个特性在哪些平台族 / Profile 支持、命令怎么写、默认值是多少、来源是什么。

结论全部由知识库计算：Schema 节点 + 各 Profile（继承展开后）的条目 + 条目对应的命令卡。不用 AI。
每个格子的状态：supported 支持、unsupported 明确不支持、unfilled 知识库还没填写。
跨厂商只是写法不同（各 Profile 状态与默认值都一样）的特性记为 same：不带关键词浏览全部特性、以及 Profile 对比时
默认只计数不列出（决策 D-0093）；带关键词查询时照常列出。
"""

from __future__ import annotations

import re
from typing import Any

from lmesh.core.kb import KnowledgeBase, SchemaNode
from lmesh.core.kb.edit import card_credibility

STATES = ("supported", "unsupported", "unfilled")
KINDS = ("default", "only_a", "only_b", "unfilled", "same")


class FeatureError(ValueError):
    def __init__(self, key: str, kind: str = "param", **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.fmt = key, kind, fmt


def _profiles(kb: KnowledgeBase, profiles: list[str] | None, family: str | None) -> list[str]:
    if profiles:
        for p in profiles:
            if p not in kb.profiles:
                raise FeatureError("feature.bad_profile", "not_found", profile=p)
        out = list(profiles)
    else:
        out = sorted(kb.profiles)
    if family:
        fams = {p.family for p in kb.profiles.values()}
        if family not in fams:
            raise FeatureError("feature.bad_family", "not_found", family=family, families=", ".join(sorted(fams)))
        out = [p for p in out if kb.profiles[p].family == family]
    return out


def _cell(kb: KnowledgeBase, resolved: Any, pid: str, nid: str) -> dict[str, Any]:
    e = resolved.entries.get(nid)
    if e is None:
        return {"state": "unfilled"}
    cards = [c for c in e.cards if c in kb.cards]
    return {
        "state": "supported" if e.supported else "unsupported",
        "default": e.default,
        "cards": e.cards,
        "syntax": [kb.cards[c].syntax for c in cards],
        "undo": [kb.cards[c].undo for c in cards if kb.cards[c].undo],
        "views": sorted({kb.cards[c].view for c in cards}),
        "credibility": card_credibility(kb, e.cards) if not e.manual else "reviewed",
        "source": e.source,
        "sources": [kb.cards[c].source for c in cards if kb.cards[c].source],
        "verified": e.verified,
        "manual": e.manual,
        "when": e.when,
        "origin": e.origin or pid,
        "inherited": bool(e.origin and e.origin != pid),
    }


def _texts(kb: KnowledgeBase, n: SchemaNode, terms: Any = None) -> list[str]:
    out = [n.id, n.id.rsplit(".", 1)[-1].replace("_", " "), *[str(v) for v in n.semantic.values()]]
    if terms is not None:
        for style in ("huawei", "cisco"):
            kw = terms.attr(n.id, style)
            if kw:
                out.append(kw)
            for lg in ("zh-CN", "en", "pt-BR"):
                out.append(terms.name(n.id, style, lg, kb))
    return [t.lower() for t in out if t]


def _score(q: str, n: SchemaNode, texts: list[str], syntaxes: list[str]) -> int:
    if not q:
        return 1
    if q == n.id.lower():
        return 100
    if n.id.lower().endswith("." + q) or n.id.lower().rsplit(".", 1)[-1] == q.replace(" ", "_"):
        return 80
    if q in n.id.lower():
        return 60
    if any(q in t for t in texts):
        return 40
    if any(q in s for s in syntaxes):
        return 30
    words = [w for w in re.split(r"[\s_.-]+", q) if w]
    if words and all(any(w in t for t in texts + syntaxes) for w in words):
        return 20
    return 0


def search(
    kb: KnowledgeBase,
    q: str = "",
    profiles: list[str] | None = None,
    family: str | None = None,
    domain: str | None = None,
    state: str | None = None,
    include_same: bool = False,
    include_objects: bool = False,
    terms: Any = None,
    limit: int = 200,
) -> dict[str, Any]:
    """按关键词（节点编号、语义、两种风格的叫法、命令写法）查询特性。

    state：只看某个 Profile 状态为该值的特性（supported / unsupported / unfilled，任一 Profile 符合即可）。"""
    if state and state not in STATES:
        raise FeatureError("feature.bad_state", state=state, allowed=", ".join(STATES))
    pids = _profiles(kb, profiles, family)
    domains = set(kb.domains) | {n.domain for n in kb.nodes.values()}
    if domain and domain not in domains:
        raise FeatureError("feature.bad_domain", domain=domain, domains=", ".join(sorted(domains)))
    resolved = {p: kb.resolve_profile(p) for p in pids}
    query = (q or "").strip().lower()
    hits: list[tuple[int, dict[str, Any]]] = []
    same = 0
    for nid in sorted(kb.nodes):
        n = kb.nodes[nid]
        if n.type == "object" and not include_objects:
            continue
        if domain and n.domain != domain:
            continue
        cells = {p: _cell(kb, resolved[p], p, nid) for p in pids}
        syntaxes = [s.lower() for c in cells.values() for s in c.get("syntax", [])]
        score = _score(query, n, _texts(kb, n, terms), syntaxes)
        if score <= 0:
            continue
        if state and not any(c["state"] == state for c in cells.values()):
            continue
        states = {c["state"] for c in cells.values()}
        defaults = {repr(c.get("default")) for c in cells.values() if c["state"] == "supported"}
        kind = "same" if len(states) == 1 and len(defaults) <= 1 else "differs"
        if "unfilled" in states:
            kind = "gap"
        if kind == "same" and len(pids) > 1 and not include_same and not query:
            same += 1
            continue
        hits.append(
            (
                score,
                {
                    "node": nid,
                    "domain": n.domain,
                    "type": n.type,
                    "parent": n.parent,
                    "semantic": n.semantic,
                    "range": n.range,
                    "choices": n.choices,
                    "secret": n.secret,
                    "deprecated": n.deprecated,
                    "kind": kind,
                    "score": score,
                    "profiles": cells,
                },
            )
        )
    order = {d: i for i, d in enumerate(kb.domains)}
    hits.sort(key=lambda h: (-h[0], order.get(h[1]["domain"], 99), h[1]["node"]))
    items = [h[1] for h in hits[:limit]]
    counts = {s: {p: 0 for p in pids} for s in STATES}
    for it in items:
        for p, c in it["profiles"].items():
            counts[c["state"]][p] += 1
    return {
        "q": q,
        "profiles": [_profile_info(kb, p) for p in pids],
        "items": items,
        "total": len(hits),
        "truncated": len(hits) > limit,
        "hidden_same": same,
        "counts": counts,
        "kb_version": kb.version,
    }


def _profile_info(kb: KnowledgeBase, pid: str) -> dict[str, Any]:
    p = kb.profiles[pid]
    return {
        "id": pid,
        "title": p.title,
        "vendor": p.vendor,
        "family": p.family,
        "platform": p.platform,
        "software": p.software,
        "inherits": p.inherits,
    }


def detail(kb: KnowledgeBase, node: str, profiles: list[str] | None = None) -> dict[str, Any]:
    """一个特性（Schema 节点）在各 Profile 中的完整信息。"""
    if node not in kb.nodes:
        raise FeatureError("feature.bad_node", "not_found", node=node)
    pids = _profiles(kb, profiles, None)
    n = kb.nodes[node]
    deps = [
        {"kind": d.kind, "src": d.src, "dst": d.dst, "note": d.note, "profiles": d.profiles}
        for d in kb.deps
        if node in (d.src, d.dst)
    ]
    return {
        "node": node,
        "domain": n.domain,
        "type": n.type,
        "parent": n.parent,
        "semantic": n.semantic,
        "range": n.range,
        "choices": n.choices,
        "key": n.key,
        "ref": n.ref,
        "secret": n.secret,
        "deprecated": n.deprecated,
        "replaced_by": n.replaced_by,
        "deps": deps,
        "profiles": {p: _cell(kb, kb.resolve_profile(p), p, node) for p in pids},
        "profile_info": [_profile_info(kb, p) for p in pids],
    }


def diff(kb: KnowledgeBase, a: str, b: str, domain: str | None = None, include_same: bool = False) -> dict[str, Any]:
    """两个 Profile 对比：默认值不同的排在最前，其次支持情况不同、未填写，写法不同但效果相同的默认只计数。"""
    for p in (a, b):
        if p not in kb.profiles:
            raise FeatureError("feature.bad_profile", "not_found", profile=p)
    ra, rb = kb.resolve_profile(a), kb.resolve_profile(b)
    rows: list[dict[str, Any]] = []
    counts = dict.fromkeys(KINDS, 0)
    for nid in sorted(kb.nodes):
        n = kb.nodes[nid]
        if n.type == "object" or (domain and n.domain != domain):
            continue
        ca, cb = _cell(kb, ra, a, nid), _cell(kb, rb, b, nid)
        sa, sb = ca["state"], cb["state"]
        if "unfilled" in (sa, sb) and sa != sb:
            kind = "unfilled"
        elif sa == "supported" and sb != "supported":
            kind = "only_a"
        elif sb == "supported" and sa != "supported":
            kind = "only_b"
        elif sa == sb == "supported" and ca.get("default") != cb.get("default"):
            kind = "default"
        elif sa == sb == "unfilled":
            continue  # 两边都没填写：不是两个 Profile 之间的差别
        else:
            kind = "same"
        counts[kind] += 1
        if kind == "same" and not include_same:
            continue
        rows.append(
            {
                "node": nid,
                "domain": n.domain,
                "type": n.type,
                "semantic": n.semantic,
                "kind": kind,
                "syntax_differs": ca.get("syntax") != cb.get("syntax"),
                "a": ca,
                "b": cb,
            }
        )
    order = {d: i for i, d in enumerate(kb.domains)}
    rows.sort(key=lambda r: (KINDS.index(r["kind"]), order.get(r["domain"], 99), r["node"]))
    return {
        "a": _profile_info(kb, a),
        "b": _profile_info(kb, b),
        "domain": domain,
        "counts": counts,
        "hidden_same": 0 if include_same else counts["same"],
        "rows": rows,
        "kb_version": kb.version,
    }
