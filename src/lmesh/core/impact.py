"""变更影响分析（M4-4，REQ-016）：给一组节点（或一份变更），沿依赖边求影响范围。

依赖关系（links）由图与 Schema 得到，不写死功能域：
    - 图中的 reference / prerequisite 边（建图时按 Schema deps 建立）；
    - Schema 中 type=ref、却没有依赖规则的属性（按取值找被引用的对象）；
    - 键字段引用（bgp.af 的键 vrf 指向 VPN 实例：键字段的类型按 compare._Schema 推出）；
    - 键别名（KEY_ALIASES：地址族里的对等体按名字指向 BGP 视图中的对等体或对等体组）。
方向：
    up（默认）   谁受影响：被改的节点 → 所属对象（沿 contains 向上）→ 引用这些对象的节点 → ……
                 例如改前缀列表 → 引用它的路由策略节点 → 路由策略 → 引用策略的对等体 / VPN 实例 / 重分发；
    down         依赖谁：节点（含子树）引用的对象，以及这些对象再引用的对象；
    both         两个方向。
业务对象（BUSINESS）：VPN 实例、对等体、接口、二层业务等，结果中单独列出并给出从起点到它的路径。
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from lmesh.core.compare import _Schema, norm_scalar
from lmesh.core.graph import DEVICE
from lmesh.core.kb import KnowledgeBase
from lmesh.core.kb.model import Note

DIRECTIONS = ("up", "down", "both")
MAX_DEPTH = 32

# 业务对象：Schema 对象类型 → 类别（界面按类别分组显示）。知识库中不存在的类型自动忽略。
BUSINESS = {
    "vrf.instance": "vrf",
    "interface": "interface",
    "interface.access": "interface",
    "bgp.peer": "peer",
    "bgp.peer_group": "peer",
    "bgp.af.peer": "peer",
    "mpls.ldp.remote_peer": "peer",
    "bfd.session": "peer",
    "bridge_domain": "l2vpn",
    "interface.access.pw": "l2vpn",
    "l2vpn.vsi": "l2vpn",
}

# 键别名：这类对象的键（单键）是另一类对象的名字（同一个顶层对象之内）。
KEY_ALIASES = {"bgp.af.peer": ("bgp.peer", "bgp.peer_group")}


class ImpactError(ValueError):
    def __init__(self, key: str, kind: str = "param", **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.fmt = key, kind, fmt


@dataclass
class Link:
    src: str
    dst: str
    kind: str  # reference / prerequisite / key / alias
    note: Note = field(default_factory=Note)  # 依赖说明；键字段 / 别名引用时为字段名


def _key_text(key: Any) -> str:
    if isinstance(key, dict):
        return ",".join(f"{k}={'' if v is None else v}" for k, v in key.items())
    return "" if key is None else str(key)


def _top(nid: str) -> str:
    depth = 0
    for i, ch in enumerate(nid):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "/" and depth == 0:
            return nid[:i]
    return nid


def _depth(nid: str) -> int:
    """节点编号的层数（方括号里的 / 不算）。"""
    depth, n = 0, 0
    for ch in nid:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "/" and depth == 0:
            n += 1
    return n


def links(g: nx.MultiDiGraph, kb: KnowledgeBase) -> list[Link]:
    """图上的全部依赖关系（去重）：边 + 没有规则的 ref 属性 + 键字段引用 + 键别名。"""
    sch = _Schema(kb)
    out: dict[tuple[str, str, str], Link] = {}
    for a, b, d in g.edges(data=True):
        k = d.get("kind")
        if k in ("reference", "prerequisite"):
            out.setdefault((a, b, k), Link(a, b, k, Note.of(d.get("note"))))
    index: dict[tuple[str, str], list[str]] = defaultdict(list)
    for n, d in g.nodes(data=True):
        if d.get("kind") == "object" and d.get("schema"):
            sn = kb.nodes.get(d["schema"])
            index[(d["schema"], _key_text(d.get("key")))].append(n)
            if sn is not None and len(sn.key) <= 1 and not isinstance(d.get("key"), dict):
                t, _ = sch.field_type(sn, sn.key[0] if sn.key else "name")
                index[(d["schema"], str(norm_scalar(t, d.get("key"))))].append(n)
    linked = {(a, b) for a, b, _ in out}

    def find(schema: str, value: Any, near: str | None = None) -> list[str]:
        sn = kb.nodes.get(schema)
        if sn is None or value in (None, "", True, False):
            return []
        hits = list(index.get((schema, str(value)), []))
        if not hits and len(sn.key) <= 1:
            t, _ = sch.field_type(sn, sn.key[0] if sn.key else "name")
            hits = list(index.get((schema, str(norm_scalar(t, value))), []))
        if near is not None and len(hits) > 1:
            same = [h for h in hits if _top(h) == _top(near)]
            hits = same or hits
        return list(dict.fromkeys(hits))

    for n, d in g.nodes(data=True):
        sn = kb.nodes.get(str(d.get("schema") or ""))
        if sn is None or d.get("origin") == "default" or d.get("negated"):
            continue
        if d.get("kind") == "attr" and sn.type == "ref" and sn.ref:
            for v in d["value"] if isinstance(d.get("value"), list) else [d.get("value")]:
                for t in find(sn.ref, v):
                    if (n, t) not in linked:
                        out.setdefault((n, t, "reference"), Link(n, t, "reference"))
        elif d.get("kind") == "object":
            key = d.get("key")
            fields = key.items() if isinstance(key, dict) else [(sn.key[0] if sn.key else "name", key)]
            for f, v in fields:
                _, ref = sch.field_type(sn, f)
                if ref and ref != sn.id:
                    for t in find(ref, v):
                        out.setdefault((n, t, "key"), Link(n, t, "key", Note.of(f)))
            for alias in KEY_ALIASES.get(sn.id, ()):
                if not isinstance(key, dict):
                    for t in find(alias, key, near=n):
                        out.setdefault((n, t, "alias"), Link(n, t, "alias", Note.of(alias)))
    return list(out.values())


@dataclass
class _Walk:
    parent: dict[str, str] = field(default_factory=dict)  # contains：子 → 父
    children: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    ref_in: dict[str, list[Link]] = field(default_factory=lambda: defaultdict(list))
    ref_out: dict[str, list[Link]] = field(default_factory=lambda: defaultdict(list))


def _walk_index(g: nx.MultiDiGraph, kb: KnowledgeBase) -> _Walk:
    w = _Walk()
    for a, b, d in g.edges(data=True):
        if d.get("kind") == "contains":
            w.parent[b] = a
            w.children[a].append(b)
    for lk in links(g, kb):
        w.ref_in[lk.dst].append(lk)
        w.ref_out[lk.src].append(lk)
    return w


def resolve_nodes(g: nx.MultiDiGraph, names: list[str]) -> list[str]:
    """节点编号：完全相同优先；否则唯一一个包含该文字的对象节点。认不出时报错并给出候选。"""
    out: list[str] = []
    for name in names:
        name = name.strip()
        if not name:
            continue
        if name in g and name != DEVICE:
            out.append(name)
            continue
        hits = [n for n, d in g.nodes(data=True) if d.get("kind") == "object" and name in n]
        by_key = [n for n in hits if _key_text(g.nodes[n].get("key")) == name or n.endswith(name)]
        if len(by_key) > 1:  # 同名的键：取层级最浅的（GigabitEthernet0/2/1 → 接口本身）
            top = min(_depth(n) for n in by_key)
            by_key = [n for n in by_key if _depth(n) == top]
        pick = by_key if len(by_key) == 1 else hits
        if len(pick) != 1:
            raise ImpactError(
                "impact.node_not_found" if not pick else "impact.node_ambiguous",
                "not_found" if not pick else "param",
                node=name,
                candidates=", ".join(sorted(pick)[:8]),
            )
        out.append(pick[0])
    if not out:
        raise ImpactError("impact.need_nodes")
    return list(dict.fromkeys(out))


def _schema(g: nx.MultiDiGraph, n: str) -> str:
    return str(g.nodes[n].get("schema") or "")


def _domain(kb: KnowledgeBase, g: nx.MultiDiGraph, n: str) -> str:
    sn = kb.nodes.get(_schema(g, n))
    return sn.domain if sn else ""


def analyze(
    g: nx.MultiDiGraph,
    kb: KnowledgeBase,
    nodes: list[str],
    direction: str = "up",
    max_depth: int = MAX_DEPTH,
    walk: _Walk | None = None,
) -> dict[str, Any]:
    """从 nodes 出发求影响范围。返回受影响的节点（含到达它的上一跳与边的类型）、对象与业务对象的路径、按功能域汇总。"""
    if direction not in DIRECTIONS:
        raise ImpactError("impact.bad_direction", value=direction)
    seeds = resolve_nodes(g, nodes)
    w = walk or _walk_index(g, kb)
    found: dict[str, dict[str, Any]] = {}
    for dirn in ("up", "down") if direction == "both" else (direction,):
        prev: dict[str, tuple[str | None, str]] = {s: (None, "seed") for s in seeds}
        depth = dict.fromkeys(seeds, 0)
        queue = deque(seeds)
        while queue:
            n = queue.popleft()
            if depth[n] >= max_depth:
                continue
            nxt: list[tuple[str, str]] = []
            if dirn == "up":
                p = w.parent.get(n)
                if p and p != DEVICE and g.nodes[n].get("kind") in ("attr", "object", "ext"):
                    nxt.append((p, "contains"))
                # 经键别名到达的对象（地址族里的对等体组 → BGP 视图中的对等体组）不再沿别名回到其他地址族
                via_alias = prev[n][1] == "alias"
                nxt += [(lk.src, lk.kind) for lk in w.ref_in.get(n, []) if not (via_alias and lk.kind == "alias")]
                # 键别名指向的是同一个实体：影响也传给它（再传给组内的对等体）
                nxt += [(lk.dst, lk.kind) for lk in w.ref_out.get(n, []) if lk.kind == "alias"]
            else:
                stack, sub = [n], []
                while stack:  # 节点的子树引用的对象
                    x = stack.pop()
                    sub.append(x)
                    stack.extend(w.children.get(x, []))
                nxt += [(lk.dst, lk.kind) for x in sub for lk in w.ref_out.get(x, [])]
            for m, kind in nxt:
                if m in prev or m == DEVICE:
                    continue
                prev[m] = (n, kind)
                depth[m] = depth[n] + 1
                queue.append(m)
        for m, (via, kind) in prev.items():
            path = [m]
            cur = via
            while cur is not None:
                path.append(cur)
                cur = prev[cur][0]
            path.reverse()
            if m in found and len(found[m]["path"]) <= len(path):
                continue
            found[m] = {
                "node": m,
                "schema": _schema(g, m) or None,
                "kind": g.nodes[m].get("kind"),
                "domain": _domain(kb, g, m),
                "depth": depth[m],
                "via": via,
                "edge": kind,
                "direction": dirn if via is not None else "seed",
                "business": BUSINESS.get(_schema(g, m)),
                "path": path,
            }
    return _result(g, kb, seeds, direction, found)


def _result(
    g: nx.MultiDiGraph, kb: KnowledgeBase, seeds: list[str], direction: str, found: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    order = {dm: i for i, dm in enumerate(kb.domains)}
    items = sorted(
        found.values(),
        key=lambda x: (x["depth"], order.get(x["domain"], len(order)), x["node"]),
    )
    objects = [x for x in items if x["kind"] == "object" and x["direction"] != "seed"]
    business = [x for x in objects if x["business"]]
    by_domain: dict[str, dict[str, Any]] = {}
    for x in objects:
        dm = by_domain.setdefault(x["domain"], {"objects": 0, "business": 0, "nodes": []})
        dm["objects"] += 1
        dm["business"] += 1 if x["business"] else 0
        dm["nodes"].append(x["node"])
    by_business: dict[str, list[str]] = defaultdict(list)
    for x in business:
        by_business[str(x["business"])].append(x["node"])
    return {
        "device": g.graph.get("device"),
        "profile": g.graph.get("profile"),
        "direction": direction,
        "seeds": [{"node": s, "schema": _schema(g, s) or None, "domain": _domain(kb, g, s)} for s in seeds],
        "nodes": [{k: v for k, v in x.items() if k != "path"} for x in items],
        "objects": [{k: x[k] for k in ("node", "schema", "domain", "depth", "edge", "business")} for x in objects],
        "business": [
            {
                "node": x["node"],
                "schema": x["schema"],
                "domain": x["domain"],
                "type": x["business"],
                "direction": x["direction"],
                "path": x["path"],
            }
            for x in business
        ],
        "by_domain": dict(sorted(by_domain.items(), key=lambda kv: (order.get(kv[0], len(order)), kv[0]))),
        "by_business": {k: sorted(v) for k, v in sorted(by_business.items())},
        "summary": {
            "seeds": len(seeds),
            "nodes": sum(1 for x in items if x["direction"] != "seed"),
            "objects": len(objects),
            "business": len(business),
            "domains": len(by_domain),
        },
    }


def of_change(
    current: nx.MultiDiGraph, target: nx.MultiDiGraph, kb: KnowledgeBase, change: dict[str, Any]
) -> dict[str, Any]:
    """一份变更（core/change.py 的结果）的影响范围：删除 / 修改的节点在当前配置上求，新增 / 修改的节点在目标配置上求，按节点合并。"""
    cur_seeds = sorted({n for op in change.get("ops", []) for n in op.get("current_nodes", []) if n in current})
    tgt_seeds = sorted({n for op in change.get("ops", []) for n in op.get("target_nodes", []) if n in target})
    parts = []
    if cur_seeds:
        parts.append(("current", analyze(current, kb, cur_seeds)))
    if tgt_seeds:
        parts.append(("target", analyze(target, kb, tgt_seeds)))
    merged: dict[str, dict[str, Any]] = {}
    seeds: dict[str, dict[str, Any]] = {}
    for side, r in parts:
        for s in r["seeds"]:
            seeds.setdefault(s["node"], {**s, "side": side})
        for b in r["business"]:
            if b["node"] not in merged or len(b["path"]) < len(merged[b["node"]]["path"]):
                merged[b["node"]] = {**b, "side": side}
    objs: dict[str, dict[str, Any]] = {}
    for side, r in parts:
        for o in r["objects"]:
            objs.setdefault(o["node"], {**o, "side": side})
    order = {dm: i for i, dm in enumerate(kb.domains)}
    by_domain: dict[str, int] = defaultdict(int)
    for o in objs.values():
        by_domain[o["domain"]] += 1
    business = sorted(merged.values(), key=lambda x: (str(x["type"]), x["node"]))
    by_business: dict[str, list[str]] = defaultdict(list)
    for b in business:
        by_business[str(b["type"])].append(b["node"])
    return {
        "seeds": list(seeds.values()),
        "objects": sorted(objs.values(), key=lambda x: (order.get(x["domain"], len(order)), x["node"])),
        "business": business,
        "by_domain": dict(sorted(by_domain.items(), key=lambda kv: (order.get(kv[0], len(order)), kv[0]))),
        "by_business": dict(sorted(by_business.items())),
        "summary": {"seeds": len(seeds), "objects": len(objs), "business": len(business)},
    }
