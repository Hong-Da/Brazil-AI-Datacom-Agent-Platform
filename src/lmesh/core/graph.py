"""统一配置图：解析结果 + 知识库映射 → 图（networkx）。

节点：
    device                   设备根节点
    语义节点                 Schema 对象与属性，编号按层级：interface[GE0/2/1]/mtu、bgp.instance[65000]/bgp.af[afi=ipv4,vrf=]/…
    ext[命令卡@行号]         匹配上命令卡、但该卡还没有映射到 Schema 的命令（厂商私有或尚未归并），挂在最近的对象下
    raw[行号] / unknown[行号] 功能域外的原文行、未识别行
节点属性：kind（object / attr / ext / raw / unknown / device）、schema、value（有效值，已归一化）、raw（原文取值）、
          origin（explicit 显式 / default 默认（隐藏）/ derived 派生）、lines（原始行号）、cards（依据的命令卡）、negated。
边：contains（包含），以及 reference / prerequisite / side_effect / mutex / cross_device 五类依赖。
图的 graph 属性里保存按原始顺序排列的语句（statements），渲染时按它回放；dangling 记录悬空引用。
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from lmesh.core.kb import KnowledgeBase, mapping
from lmesh.core.kb.model import Card, Profile, SchemaNode
from lmesh.core.parser import Line, Parsed

DEVICE = "device"


@dataclass
class Statement:
    line: Line
    nodes: list[str] = field(default_factory=list)  # 这一行产生或修改的节点
    sources: dict[str, str] = field(default_factory=dict)  # 参数名 → 取值来源节点（渲染时从图中取值）


def _key_text(key: Any) -> str:
    if isinstance(key, dict):
        return ",".join(f"{k}={'' if v is None else v}" for k, v in key.items())
    return "" if key is None else str(key)


def _short(schema_id: str, parent_schema: str | None) -> str:
    """节点编号中的一段：去掉父对象的前缀（interface.ipv4 在 interface 下写成 ipv4）。"""
    if parent_schema and schema_id.startswith(parent_schema + "."):
        return schema_id[len(parent_schema) + 1 :]
    return schema_id


class Builder:
    def __init__(self, kb: KnowledgeBase, profile: Profile, device: str = "device"):
        self.kb, self.profile = kb, profile
        self.g = nx.MultiDiGraph(device=device, profile=profile.id, family=profile.family, kb_version=kb.version)
        self.g.add_node(DEVICE, kind="device", schema=None, value=device, origin="explicit", lines=[], cards=[])
        self.index: dict[tuple[str, str], str] = {}  # (Schema 对象类型, 键) → 节点编号（全局，用于依赖边）
        self.ctx: dict[int, dict[str, str]] = {}  # 行号 → 该行可见的对象实例（Schema 类型 → 节点编号）
        self.auto: dict[tuple[str, str], int] = defaultdict(int)  # 自动编号
        self.statements: list[Statement] = []

    # ----- 节点 -----

    def _node(self, nid: str, parent: str, schema: str, kind: str, **attrs: Any) -> str:
        if nid not in self.g:
            self.g.add_node(nid, kind=kind, schema=schema, origin="explicit", lines=[], cards=[], **attrs)
            self.g.add_edge(parent, nid, kind="contains")
        else:
            self.g.nodes[nid].update({k: v for k, v in attrs.items() if v is not None})
        return nid

    def _touch(self, nid: str, line: Line, card: Card | None) -> None:
        d = self.g.nodes[nid]
        if line.no not in d["lines"]:
            d["lines"].append(line.no)
        if card is not None and card.id not in d["cards"]:
            d["cards"].append(card.id)
        if d.get("origin") == "default":
            d["origin"] = "explicit"

    def _object(
        self,
        schema: SchemaNode,
        key: Any,
        scope: dict[str, str],
        fixed: dict[str, dict[str, str]],
        line: Line,
        card: Card,
        raw: Any = None,
    ) -> str:
        """取得或创建一个对象实例：父对象从本行已创建的、上下文中的、或路径中的固定键得到。"""
        parent_id = DEVICE
        if schema.parent:
            parent_schema = self.kb.nodes.get(schema.parent)
            # 父节点不一定是对象（属性下面挂对象的情况很少），向上找最近的对象
            while parent_schema is not None and parent_schema.type != "object":
                parent_schema = self.kb.nodes.get(parent_schema.parent) if parent_schema.parent else None
            if parent_schema is not None:
                if parent_schema.id in scope:
                    parent_id = scope[parent_schema.id]
                elif parent_schema.id in fixed:
                    parent_id = self._object(
                        parent_schema,
                        dict(fixed[parent_schema.id])
                        if len(parent_schema.key) > 1
                        else next(iter(fixed[parent_schema.id].values()), ""),
                        scope,
                        fixed,
                        line,
                        card,
                    )
                else:
                    parent_id = self._ensure_ancestor(parent_schema, scope, line, card)
        kt = _key_text(key)
        seg = f"{_short(schema.id, self.g.nodes[parent_id].get('schema'))}[{kt}]"
        nid = seg if parent_id == DEVICE else f"{parent_id}/{seg}"
        self._node(nid, parent_id, schema.id, "object", key=key if not isinstance(key, dict) else dict(key), raw=raw)
        self._touch(nid, line, card)
        self.index[(schema.id, kt)] = nid
        scope[schema.id] = nid
        return nid

    def _ensure_ancestor(self, schema: SchemaNode, scope: dict[str, str], line: Line, card: Card) -> str:
        """上下文中没有父对象（例如华为二层子接口的接入点没有单独一行声明）：键为空的占位对象。"""
        if schema.id in scope:
            return scope[schema.id]
        return self._object(schema, "_" if len(schema.key) <= 1 else {k: "" for k in schema.key}, scope, {}, line, card)

    # ----- 主流程 -----

    def build(self, parsed: Parsed) -> nx.MultiDiGraph:
        for ln in parsed.lines:
            st = Statement(ln)
            self.statements.append(st)
            scope = dict(self.ctx.get(ln.parent, {})) if ln.parent else {}
            if ln.kind in ("raw", "unknown"):
                owner = self._owner_for_raw(ln, scope)
                nid = f"{ln.kind}[{ln.no}]"
                self._node(nid, owner, None, ln.kind, text=ln.text)  # type: ignore[arg-type]
                self._touch(nid, ln, None)
                st.nodes.append(nid)
                self.ctx[ln.no] = scope
                continue
            if ln.kind != "command" or not ln.card or ln.card.startswith("@"):
                continue
            card = self.kb.cards[ln.card]
            created = self._apply(card, ln, scope, st)
            if not created:
                owner = self._nearest(scope)
                nid = f"{owner}/ext[{card.id}@{ln.no}]" if owner != DEVICE else f"ext[{card.id}@{ln.no}]"
                self._node(nid, owner, f"ext:{card.id}", "ext", value=ln.values() or True, negated=ln.negated)
                self._touch(nid, ln, card)
                st.nodes.append(nid)
            self.ctx[ln.no] = scope
        self._defaults()
        self._dependencies()
        self.g.graph["statements"] = self.statements
        return self.g

    def _owner_for_raw(self, ln: Line, scope: dict[str, str]) -> str:
        if ln.parent:
            parent_raw = f"raw[{ln.parent}]"
            if parent_raw in self.g:
                return parent_raw
            parent_unknown = f"unknown[{ln.parent}]"
            if parent_unknown in self.g:
                return parent_unknown
        return self._nearest(scope)

    def _nearest(self, scope: dict[str, str]) -> str:
        if not scope:
            return DEVICE
        # 层级最深的那个对象
        return max(scope.values(), key=lambda n: n.count("/"))

    def _apply(self, card: Card, ln: Line, scope: dict[str, str], st: Statement) -> bool:
        if not card.maps:
            return False
        values = ln.values()
        tokens = ln.text.split()
        created = False
        targets = [(text, mapping.parse_target(text), expr) for text, expr in card.maps.items()]
        # 二选一：按第一个“对象”目标的取值决定走哪一支
        branch = 0
        for _, alts, expr in targets:
            if len(alts) > 1:
                v = mapping.evaluate(expr, values, tokens, ln.negated)
                branch = mapping.choose_branch([v])
                break
        # 先对象，后属性
        ordered = sorted(
            targets,
            key=lambda t: (
                0
                if self.kb.nodes.get(t[1][min(branch, len(t[1]) - 1)].node, None)
                and self.kb.nodes[t[1][min(branch, len(t[1]) - 1)].node].type == "object"
                else 1
            ),
        )
        skipped: set[str] = set()
        for _, alts, expr in ordered:
            t = alts[min(branch, len(alts) - 1)]
            schema = self.kb.nodes.get(t.node)
            if schema is None:
                continue
            key = (schema.id, str(len(self.auto)))
            value: Any = None
            if isinstance(expr, str) and expr.endswith("||auto") and expr != "auto":
                # $序号||auto：行里有序号就用序号，没有时按出现顺序编号（Cisco 编号 ACL 的规则）
                value = mapping.evaluate(expr[: -len("||auto")], values, tokens, ln.negated)
            if value not in (None, ""):
                pass
            elif expr == "auto" or (isinstance(expr, str) and expr.endswith("||auto")):
                parent_scope = self._nearest(scope)
                self.auto[(schema.id, parent_scope)] += 1
                key = (schema.id, parent_scope)
                value = str(self.auto[key] * 10)
            else:
                value = mapping.evaluate(expr, values, tokens, ln.negated)
            if value is None or value == "" and schema.type != "object":
                if schema.type == "object":
                    skipped.add(schema.id)  # 这一行没有给出对象（例如 silent-interface all）
                continue
            if schema.type == "object":
                keys = value if isinstance(value, list) else [value]
                if isinstance(value, dict):
                    lists = {k: v for k, v in value.items() if isinstance(v, list)}
                    if lists:  # 复合键里有重复参数（vpn-target 1 2 3）：展开成多个对象
                        n = max(len(v) for v in lists.values())
                        keys = [
                            {k: (v[i] if isinstance(v, list) and i < len(v) else v) for k, v in value.items()}
                            for i in range(n)
                        ]
                    else:
                        keys = [value]
                for k in keys:
                    nid = self._object(
                        schema,
                        mapping.normalize("string", schema.id, k) if not isinstance(k, dict) else k,
                        scope,
                        t.fixed,
                        ln,
                        card,
                        raw=k,
                    )
                    if nid not in st.nodes:
                        st.nodes.append(nid)
                    if isinstance(expr, str) and expr.startswith("$") and "||" not in expr:
                        st.sources[expr[1:]] = nid
                created = True
                continue
            owner_schema = self._owner_schema(schema)
            if owner_schema is None:
                continue
            owner = scope.get(owner_schema.id)
            if owner is None and owner_schema.id in skipped:
                continue  # 同一行的对象没有取到值：属性也不写，避免生成编号为 "_" 的空对象
            if owner is None:
                if owner_schema.id in t.fixed:
                    owner = self._object(
                        owner_schema,
                        dict(t.fixed[owner_schema.id])
                        if len(owner_schema.key) > 1
                        else next(iter(t.fixed[owner_schema.id].values()), ""),
                        scope,
                        t.fixed,
                        ln,
                        card,
                    )
                else:
                    owner = self._ensure_ancestor(owner_schema, scope, ln, card)
            rel = _short(schema.id, owner_schema.id)
            # 重复对象（同一行展开了多个）时，属性写到这一行产生的每个对象上
            owners = [n for n in st.nodes if self.g.nodes[n].get("schema") == owner_schema.id] or [owner]
            for i, ow in enumerate(owners):
                v = value[i] if isinstance(value, list) and len(owners) > 1 and i < len(value) else value
                nid = f"{ow}/{rel}"
                norm = mapping.normalize(schema.type, schema.id, v)
                self._node(nid, ow, schema.id, "attr", value=norm, raw=v, negated=ln.negated)
                self.g.nodes[nid].update(value=norm, raw=v, origin="explicit", negated=ln.negated)
                self._touch(nid, ln, card)
                if nid not in st.nodes:
                    st.nodes.append(nid)
                if isinstance(expr, str) and expr.startswith("$") and "||" not in expr and len(owners) == 1:
                    st.sources[expr[1:]] = nid
            created = True
        return created

    def _owner_schema(self, schema: SchemaNode) -> SchemaNode | None:
        cur = self.kb.nodes.get(schema.parent) if schema.parent else None
        while cur is not None and cur.type != "object":
            cur = self.kb.nodes.get(cur.parent) if cur.parent else None
        return cur

    # ----- 隐藏的默认节点 -----

    def _defaults(self) -> None:
        resolved = self.kb.resolve_profile(self.profile.id)
        by_owner: dict[str, list[tuple[SchemaNode, Any, dict[str, Any]]]] = defaultdict(list)
        for node_id, e in resolved.entries.items():
            if e.default is None or not e.supported:
                continue
            sn = self.kb.nodes.get(node_id)
            if sn is None or sn.type == "object":
                continue
            owner = self._owner_schema(sn)
            if owner is not None:
                by_owner[owner.id].append((sn, e.default, e.when))
        for items in by_owner.values():
            items.sort(key=lambda t: bool(t[2].get("attr")))  # 不依赖兄弟属性的先补，条件里可以用到它们
        for nid, data in list(self.g.nodes(data=True)):
            if data.get("kind") != "object" or data.get("schema") not in by_owner:
                continue
            for sn, default, when in by_owner[data["schema"]]:
                child = f"{nid}/{_short(sn.id, data['schema'])}"
                if child in self.g or not self._when(nid, data, when):
                    continue
                self.g.add_node(
                    child,
                    kind="attr",
                    schema=sn.id,
                    value=mapping.normalize(sn.type, sn.id, default),
                    raw=None,
                    origin="default",
                    lines=[],
                    cards=[],
                    negated=False,
                )
                self.g.add_edge(nid, child, kind="contains")

    def _when(self, nid: str, data: dict[str, Any], when: dict[str, Any]) -> bool:
        """缺省值的适用条件：对象编号匹配正则、兄弟属性的有效值相等。"""
        if not when:
            return True
        key = str(data.get("key") or "")
        if when.get("key") and not re.search(str(when["key"]), key):
            return False
        if when.get("not_key") and re.search(str(when["not_key"]), key):
            return False
        for attr, want in (when.get("attr") or {}).items():
            sib = self.g.nodes.get(f"{nid}/{attr}")
            got = sib.get("value") if sib else None
            wants = want if isinstance(want, list) else [want]
            if got not in wants and str(got) not in [str(w) for w in wants]:
                return False
        return True

    # ----- 依赖边 -----

    def _dependencies(self) -> None:
        dangling: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        resolved = self.kb.resolve_profile(self.profile.id)
        rules = list(self.kb.deps) + list(resolved.side_effects)
        attrs_by_schema: dict[str, list[str]] = defaultdict(list)
        for nid, d in self.g.nodes(data=True):
            if d.get("schema"):
                attrs_by_schema[d["schema"]].append(nid)
        for r in rules:
            if (
                r.profiles
                and self.profile.id not in r.profiles
                and not set(r.profiles) & set(self.kb.lineage(self.profile.id))
            ):
                continue
            if r.kind in ("reference", "prerequisite"):
                for nid in attrs_by_schema.get(r.src, []):
                    d = self.g.nodes[nid]
                    if d.get("origin") == "default" or d.get("negated"):
                        continue
                    if d.get("kind") == "object" or "value" not in d:
                        # 对象之间的前置关系（例如 BFD 会话需要先全局使能 BFD）：连到同类型的全部对象；
                        # 一个都没有时记为缺少前置条件（配置检查用），不算悬空引用
                        if r.kind != "prerequisite":
                            continue
                        targets = attrs_by_schema.get(r.dst, [])
                        for tgt in targets:
                            self.g.add_edge(nid, tgt, kind=r.kind, note=r.note)
                        if not targets:
                            missing.append(
                                {
                                    "node": nid,
                                    "schema": r.src,
                                    "requires": r.dst,
                                    "note": r.note,
                                    "lines": d.get("lines", []),
                                }
                            )
                        continue
                    vals = d["value"] if isinstance(d["value"], list) else [d["value"]]
                    for v in vals:
                        if v in (None, "", True, False):
                            continue
                        target = self.index.get((r.dst, str(v)))
                        if target is None and r.dst in resolved.implicit and r.dst in self.kb.nodes:
                            # 被引用即隐式存在的对象：作为派生节点补上（例如 ASR 920 业务实例引用的桥域）
                            target = f"{_short(r.dst, None)}[{v}]"
                            if target not in self.g:
                                self.g.add_node(
                                    target,
                                    kind="object",
                                    schema=r.dst,
                                    key=str(v),
                                    raw=None,
                                    origin="derived",
                                    lines=list(d["lines"]),
                                    cards=[],
                                )
                                self.g.add_edge(DEVICE, target, kind="contains")
                            self.index[(r.dst, str(v))] = target
                        if target:
                            self.g.add_edge(nid, target, kind=r.kind, note=r.note)
                        elif r.kind == "reference":
                            dangling.append(
                                {"node": nid, "schema": r.src, "target_type": r.dst, "value": v, "lines": d["lines"]}
                            )
            elif r.kind in ("mutex", "side_effect"):
                for nid in attrs_by_schema.get(r.src, []):
                    d = self.g.nodes[nid]
                    if d.get("origin") == "default" or d.get("value") in (False, None):
                        continue
                    owner = next(iter(self.g.predecessors(nid)), None)
                    for other in attrs_by_schema.get(r.dst, []):
                        if other != nid and (owner is None or other.startswith(owner + "/")):
                            self.g.add_edge(nid, other, kind=r.kind, note=r.note)
        self.g.graph["dangling"] = dangling
        self.g.graph["missing_prerequisites"] = missing


def build(parsed: Parsed, kb: KnowledgeBase, profile_id: str, device: str = "device") -> nx.MultiDiGraph:
    return Builder(kb, kb.profiles[profile_id], device).build(parsed)


def summary(g: nx.MultiDiGraph) -> dict[str, Any]:
    kinds: dict[str, int] = defaultdict(int)
    origins: dict[str, int] = defaultdict(int)
    for _, d in g.nodes(data=True):
        kinds[d.get("kind", "?")] += 1
        if d.get("kind") == "attr":
            origins[d.get("origin", "?")] += 1
    edges: dict[str, int] = defaultdict(int)
    for _, _, d in g.edges(data=True):
        edges[d.get("kind", "?")] += 1
    return {
        "nodes": g.number_of_nodes(),
        "edges": g.number_of_edges(),
        "kinds": dict(kinds),
        "attr_origins": dict(origins),
        "edge_kinds": dict(edges),
        "dangling": len(g.graph.get("dangling", [])),
    }


def to_json(
    g: nx.MultiDiGraph, domain: str | None = None, include_raw: bool = True, roots: list[str] | None = None
) -> dict[str, Any]:
    """前端与 API 使用的图数据。

    domain：只保留该功能域——Schema 属于这些根节点（roots，由知识库按功能域给出；不给时用 domain 本身作前缀）
    的节点、它们的子节点（含其下的原文与未识别行）以及祖先（设备节点）。
    """
    prefixes = roots or ([domain] if domain else [])

    def in_domain(d: dict[str, Any]) -> bool:
        sch = str(d.get("schema") or "")
        return any(sch == p or sch.startswith(p + ".") for p in prefixes)

    allowed: set[str] | None = None
    if domain:
        contains = nx.DiGraph([(a, b) for a, b, d in g.edges(data=True) if d.get("kind") == "contains"])
        seeds = {n for n, d in g.nodes(data=True) if in_domain(d)}
        allowed = set(seeds)
        for n in seeds:
            if n in contains:
                allowed |= nx.descendants(contains, n) | nx.ancestors(contains, n)

    def keep(nid: str, d: dict[str, Any]) -> bool:
        if not include_raw and d.get("kind") in ("raw",):
            return False
        if allowed is not None:
            return nid in allowed or d.get("kind") == "device"
        return True

    nodes = [
        {
            "id": n,
            **{
                k: v
                for k, v in d.items()
                if k in ("kind", "schema", "value", "raw", "origin", "lines", "cards", "negated", "key", "text")
            },
        }
        for n, d in g.nodes(data=True)
        if keep(n, d)
    ]
    ids = {n["id"] for n in nodes}
    edges = [
        {"from": a, "to": b, "kind": d.get("kind"), "note": d.get("note", "")}
        for a, b, d in g.edges(data=True)
        if a in ids and b in ids
    ]
    return {
        "device": g.graph.get("device"),
        "profile": g.graph.get("profile"),
        "kb_version": g.graph.get("kb_version"),
        "nodes": nodes,
        "edges": edges,
        "dangling": g.graph.get("dangling", []),
        "summary": summary(g),
    }
