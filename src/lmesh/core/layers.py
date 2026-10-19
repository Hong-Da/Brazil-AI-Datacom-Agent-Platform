"""配置分层（REQ-034）：按知识库 layers.yaml 把配置图的节点归到 TCP/IP 模型的层，并找出跨层依赖。

层（自下而上）：physical 物理层、datalink 数据链路层、mpls 2.5 层（MPLS / SR / L2VPN / EVPN）、network 网络层、
transport 传输层、application 应用层；QoS、时钟同步是跨层特性（features），按作用层标出。

归类规则（只影响显示，不影响解析、建图、对比与检查）：
    对象节点   layers.yaml 的 objects[Schema]，再按 keys 里的正则细分（子接口、聚合口、三层逻辑口）；
               没有登记时用 domains[功能域] 兜底，并在知识库校验中提示（layers.unclassified）
    属性节点   attrs[Schema]；没有登记时跟随所属对象
    ext / raw / unknown   跟随所属对象；不在任何对象下的原文行不归层（None）
跨层依赖：引用与前置依赖边（reference / prerequisite）两端所属的对象、以及包含关系中父子对象，
层不同的记一条（按对象对与边类型合并计数）。
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from lmesh.core.kb import KnowledgeBase, read_yaml

FILE = "layers.yaml"
UNCLASSIFIED = "unclassified"
CROSS_KINDS = ("reference", "prerequisite")  # 副作用、互斥都在同一对象内，不算跨层依赖


@dataclass
class Layers:
    layers: list[dict[str, Any]] = field(default_factory=list)  # [{id, order, name, desc}]，按 order
    features: list[dict[str, Any]] = field(default_factory=list)  # [{id, name, desc, span, match}]
    domains: dict[str, str] = field(default_factory=dict)
    objects: dict[str, str] = field(default_factory=dict)
    attrs: dict[str, str] = field(default_factory=dict)
    keys: dict[str, list[tuple[re.Pattern[str], str]]] = field(default_factory=dict)
    file: str = ""

    @property
    def ids(self) -> list[str]:
        return [str(x["id"]) for x in self.layers]

    def info(self) -> dict[str, Any]:
        """界面用的层与特性说明（不含归类表）。"""
        return {
            "layers": [{k: x.get(k) for k in ("id", "order", "name", "desc")} for x in self.layers],
            "features": [{k: x.get(k) for k in ("id", "name", "desc", "span")} for x in self.features],
        }


_cache: dict[str, tuple[float, Layers]] = {}
_lock = threading.Lock()


def path_for(kb_root: Path) -> Path:
    """运行时知识库没有 layers.yaml 时（早于 REQ-034 复制出的知识库），用程序自带的。"""
    own = kb_root / FILE
    if own.exists():
        return own
    from lmesh import paths

    return paths.builtin_knowledge_dir() / FILE


def load(kb_root: Path) -> Layers:
    f = path_for(kb_root)
    if not f.exists():
        return Layers()
    mtime = f.stat().st_mtime
    key = str(f.resolve())
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
    raw = read_yaml(f) or {}
    lay = Layers(
        layers=sorted((dict(x) for x in raw.get("layers") or []), key=lambda x: int(x.get("order") or 0)),
        features=[
            {**dict(x), "span": [str(s) for s in x.get("span") or []], "match": [str(m) for m in x.get("match") or []]}
            for x in raw.get("features") or []
        ],
        domains={str(k): str(v) for k, v in (raw.get("domains") or {}).items()},
        objects={str(k): str(v) for k, v in (raw.get("objects") or {}).items()},
        attrs={str(k): str(v) for k, v in (raw.get("attrs") or {}).items()},
        keys={
            str(k): [(re.compile(str(r["pattern"]), re.IGNORECASE), str(r["layer"])) for r in v or []]
            for k, v in (raw.get("keys") or {}).items()
        },
        file=str(f),
    )
    with _lock:
        _cache[key] = (mtime, lay)
    return lay


# ---------------------------------------------------------------- 校验


def problems(kb: KnowledgeBase, lay: Layers, check_nodes: bool = True) -> list[tuple[str, str]]:
    """(问题代码, 说明)：对象没有登记层、登记了不存在的节点或层。kb validate 与测试共用。

    check_nodes=False：layers.yaml 不是这个知识库自己的（用的是程序自带的），不报“登记了不存在的节点”。"""
    out: list[tuple[str, str]] = []
    if not lay.layers:
        return [("layers.missing", f"没有找到 {FILE}")]
    ids = set(lay.ids)
    for nid, n in sorted(kb.nodes.items()):
        if n.type == "object" and nid not in lay.objects:
            fallback = lay.domains.get(n.domain)
            out.append(
                (
                    "layers.unclassified",
                    f"对象 {nid} 没有在 {FILE} 的 objects 中归层"
                    + (f"（暂按功能域 {n.domain} 归入 {fallback}）" if fallback else "（归入“未分类”）"),
                )
            )
    for section, table in (("objects", lay.objects), ("attrs", lay.attrs)):
        for nid, layer in table.items():
            if nid not in kb.nodes:
                if check_nodes:
                    out.append(("layers.node_missing", f"{FILE} 的 {section}.{nid} 在 Schema 中不存在"))
            elif section == "objects" and kb.nodes[nid].type != "object":
                out.append(("layers.not_object", f"{FILE} 的 objects.{nid} 不是对象（属性请写在 attrs）"))
            if layer not in ids:
                out.append(("layers.bad_layer", f"{FILE} 的 {section}.{nid} 的层 {layer} 没有定义"))
    for dom, layer in lay.domains.items():
        if layer not in ids:
            out.append(("layers.bad_layer", f"{FILE} 的 domains.{dom} 的层 {layer} 没有定义"))
    for nid, rules in lay.keys.items():
        if nid not in kb.nodes and check_nodes:
            out.append(("layers.node_missing", f"{FILE} 的 keys.{nid} 在 Schema 中不存在"))
        for _, layer in rules:
            if layer not in ids:
                out.append(("layers.bad_layer", f"{FILE} 的 keys.{nid} 的层 {layer} 没有定义"))
    for ft in lay.features:
        for s in ft["span"]:
            if s not in ids:
                out.append(("layers.bad_layer", f"{FILE} 的特性 {ft.get('id')} 的层 {s} 没有定义"))
    return out


# ---------------------------------------------------------------- 归类


def object_layer(kb: KnowledgeBase, lay: Layers, schema: str, key: Any = None) -> str:
    rules = lay.keys.get(schema)
    if rules and key not in (None, ""):
        text = " ".join(str(v) for v in key.values()) if isinstance(key, dict) else str(key)
        for pat, layer in rules:
            if pat.search(text):
                return layer
    if schema in lay.objects:
        return lay.objects[schema]
    node = kb.nodes.get(schema)
    return lay.domains.get(node.domain, UNCLASSIFIED) if node else UNCLASSIFIED


def schema_feature(lay: Layers, schema: str | None) -> str | None:
    if not schema:
        return None
    for ft in lay.features:
        for m in ft["match"]:
            if (schema.startswith(m) if m.endswith(".") else schema == m or schema.startswith(m + ".")) and m:
                return str(ft["id"])
    return None


def _parents(g: nx.MultiDiGraph) -> dict[str, str]:
    return {b: a for a, b, d in g.edges(data=True) if d.get("kind") == "contains"}


def owner_objects(g: nx.MultiDiGraph) -> dict[str, str | None]:
    """每个节点所属的对象：对象是自身，其余是最近的对象祖先（没有时 None）。"""
    parent = _parents(g)
    out: dict[str, str | None] = {}
    for n in g.nodes:
        path: list[str] = []
        cur: str | None = n
        res: str | None = None
        while cur is not None:
            if cur in out:
                res = out[cur]
                break
            if g.nodes[cur].get("kind") == "object":
                out[cur] = res = cur
                break
            path.append(cur)
            cur = parent.get(cur)
        for p in path:
            out[p] = res
    return out


def node_layers(
    g: nx.MultiDiGraph, kb: KnowledgeBase, lay: Layers
) -> tuple[dict[str, str | None], dict[str, str | None]]:
    """(节点 → 层, 节点 → 所属对象)。"""
    owner = owner_objects(g)
    obj_layer: dict[str, str] = {}
    for n, d in g.nodes(data=True):
        if d.get("kind") == "object" and d.get("schema"):
            obj_layer[n] = object_layer(kb, lay, str(d["schema"]), d.get("key"))
    out: dict[str, str | None] = {}
    for n, d in g.nodes(data=True):
        kind = d.get("kind")
        if kind == "device":
            out[n] = None
        elif kind == "object":
            out[n] = obj_layer.get(n, UNCLASSIFIED)
        elif kind == "attr" and str(d.get("schema")) in lay.attrs:
            out[n] = lay.attrs[str(d["schema"])]
        else:
            o = owner.get(n)
            out[n] = obj_layer.get(o) if o else None
    return out, owner


def node_features(g: nx.MultiDiGraph, lay: Layers, owner: dict[str, str | None]) -> dict[str, str]:
    out: dict[str, str] = {}
    for n, d in g.nodes(data=True):
        f = schema_feature(lay, d.get("schema") if d.get("kind") in ("object", "attr") else None)
        if f is None and d.get("kind") in ("ext", "raw", "unknown"):
            o = owner.get(n)
            f = schema_feature(lay, g.nodes[o].get("schema")) if o else None
        if f:
            out[n] = f
    return out


def cross_edges(
    g: nx.MultiDiGraph, layer_of: dict[str, str | None], owner: dict[str, str | None]
) -> list[dict[str, Any]]:
    """跨层依赖，按（所属对象对, 边类型）合并；via 是第一条原始边的起点（属性或对象）。"""
    agg: dict[tuple[str, str, str], dict[str, Any]] = {}
    for a, b, d in g.edges(data=True):
        kind = d.get("kind")
        if kind == "contains":
            if g.nodes[a].get("kind") != "object" or g.nodes[b].get("kind") != "object":
                continue
            oa, ob = a, b
        elif kind in CROSS_KINDS:
            oa, ob = owner.get(a), owner.get(b)
        else:
            continue
        if not oa or not ob or oa == ob:
            continue
        la, lb = layer_of.get(oa), layer_of.get(ob)
        if not la or not lb or la == lb:
            continue
        k = (oa, ob, str(kind))
        e = agg.get(k)
        if e is None:
            agg[k] = {"from": oa, "to": ob, "kind": kind, "from_layer": la, "to_layer": lb, "via": a, "count": 1}
        else:
            e["count"] += 1
    return sorted(agg.values(), key=lambda e: (e["from_layer"], e["to_layer"], e["kind"], e["from"], e["to"]))


def classify(g: nx.MultiDiGraph, kb: KnowledgeBase, lay: Layers) -> dict[str, Any]:
    """接口与 CLI 的分层结果：层与特性的计数、每个节点的层与特性、跨层依赖、图里用到但没有登记的对象类型。"""
    layer_of, owner = node_layers(g, kb, lay)
    feats = node_features(g, lay, owner)
    counts: dict[str, dict[str, int]] = {}
    fcounts: dict[str, int] = {}
    unclassified: set[str] = set()
    other = 0
    for n, d in g.nodes(data=True):
        kind = d.get("kind")
        if kind == "device":
            continue
        layer = layer_of.get(n)
        if layer is None:
            other += 1
            continue
        c = counts.setdefault(layer, {"objects": 0, "attrs": 0, "defaults": 0, "other": 0})
        if kind == "object":
            c["objects"] += 1
            if d.get("schema") not in lay.objects:
                unclassified.add(str(d.get("schema")))
            if n in feats:
                fcounts[feats[n]] = fcounts.get(feats[n], 0) + 1
        elif kind == "attr":
            c["defaults" if d.get("origin") == "default" else "attrs"] += 1
        else:
            c["other"] += 1
    known = lay.ids
    rows = [
        {**{k: x.get(k) for k in ("id", "order", "name", "desc")}, **counts.get(str(x["id"]), _zero())}
        for x in lay.layers
    ]
    if UNCLASSIFIED in counts:
        rows.append({"id": UNCLASSIFIED, "order": 99, "name": None, "desc": None, **counts[UNCLASSIFIED]})
    cross = cross_edges(g, layer_of, owner)
    order = {lid: i for i, lid in enumerate([*known, UNCLASSIFIED])}
    return {
        "layers": rows,
        "features": [
            {**{k: x.get(k) for k in ("id", "name", "desc", "span")}, "objects": fcounts.get(str(x["id"]), 0)}
            for x in lay.features
        ],
        "nodes": {n: v for n, v in layer_of.items() if v is not None},
        "features_of": feats,
        "cross": cross,
        "cross_by_layers": _cross_matrix(cross, order),
        "outside": other,
        "unclassified": sorted(unclassified),
    }


def _zero() -> dict[str, int]:
    return {"objects": 0, "attrs": 0, "defaults": 0, "other": 0}


def _cross_matrix(cross: list[dict[str, Any]], order: dict[str, int]) -> list[dict[str, Any]]:
    """层对之间的跨层依赖条数（不分方向，低层在前）。"""
    m: dict[tuple[str, str], int] = {}
    for e in cross:
        a, b = sorted((e["from_layer"], e["to_layer"]), key=lambda x: order.get(x, 99))
        m[(a, b)] = m.get((a, b), 0) + 1
    return [
        {"a": a, "b": b, "count": n}
        for (a, b), n in sorted(m.items(), key=lambda t: (order.get(t[0][0], 99), order.get(t[0][1], 99)))
    ]
