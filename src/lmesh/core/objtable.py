"""按对象类型从配置图取表格（M5）：审计表格导出与图查询共用。

一行是图中一个对象实例（Schema 类型为 object 的节点）；一列是相对该对象的 Schema 路径（`description`、`ipv4.address`、
`af.rd`），或对象的键字段（`name`、复合键的 `prefix`）。每个格子记录取值、来源（explicit 显式 / default 默认 /
derived 派生 / none 未配置 / unsupported Profile 不支持）、对应的图节点与配置行号，所以每格都能追溯。
敏感字段（Schema 标了 secret）只给出“已配置 / 未配置”，不输出取值。确定性的结论全部由这里在图上计算。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from lmesh.core.kb import KnowledgeBase, SchemaNode

ORIGINS = ("explicit", "default", "derived", "none", "unsupported")


class TableError(ValueError):
    def __init__(self, key: str, kind: str = "param", **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.fmt = key, kind, fmt


@dataclass
class Cell:
    value: Any = None
    origin: str = "none"
    nodes: list[str] = field(default_factory=list)
    lines: list[int] = field(default_factory=list)
    secret: bool = False

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"value": self.value, "origin": self.origin, "nodes": self.nodes, "lines": self.lines}
        if self.secret:
            out["secret"] = True
        return out


def object_types(kb: KnowledgeBase) -> list[str]:
    return sorted(n.id for n in kb.nodes.values() if n.type == "object")


def resolve_type(kb: KnowledgeBase, name: str) -> SchemaNode:
    """对象类型：Schema 编号（interface、bgp.peer），大小写不敏感。"""
    sn = kb.nodes.get(name) or next((n for n in kb.nodes.values() if n.id.lower() == name.lower()), None)
    if sn is None or sn.type != "object":
        raise TableError("table.bad_object", object=name)
    return sn


def resolve_field(kb: KnowledgeBase, obj: SchemaNode, path: str) -> list[SchemaNode | str]:
    """相对路径 → 沿途的 Schema 节点；最后一段可以是键字段（返回字段名字符串）。路径不存在时抛出 TableError。"""
    parts = [p for p in path.strip().split(".") if p]
    if not parts:
        raise TableError("table.bad_field", field=path, object=obj.id)
    chain: list[SchemaNode | str] = []
    cur = obj
    for i, p in enumerate(parts):
        sn = kb.nodes.get(f"{cur.id}.{p}")
        if sn is None:
            if i == len(parts) - 1 and p in cur.key:
                chain.append(p)
                return chain
            raise TableError("table.bad_field", field=path, object=obj.id)
        chain.append(sn)
        if i < len(parts) - 1:
            if sn.type != "object":
                raise TableError("table.bad_field", field=path, object=obj.id)
            cur = sn
    return chain


def field_schema(kb: KnowledgeBase, obj: SchemaNode, path: str) -> SchemaNode | None:
    """路径最后一段的 Schema 节点；键字段没有单独节点时为 None。"""
    last = resolve_field(kb, obj, path)[-1]
    return last if isinstance(last, SchemaNode) else None


def fields_of(kb: KnowledgeBase, obj: SchemaNode, depth: int = 2) -> list[dict[str, Any]]:
    """对象可用的列：键字段、属性，以及子对象（最多 depth 层）下的属性。"""
    out: list[dict[str, Any]] = [{"path": k, "type": "key", "secret": False, "semantic": {}} for k in obj.key]

    def walk(sn: SchemaNode, prefix: str, level: int) -> None:
        for ch in sorted(kb.children(sn.id), key=lambda n: n.id):
            short = ch.id[len(sn.id) + 1 :]
            path = f"{prefix}{short}"
            if ch.type == "object":
                if level < depth:
                    for k in ch.key:
                        if f"{ch.id}.{k}" not in kb.nodes:
                            out.append({"path": f"{path}.{k}", "type": "key", "secret": False, "semantic": {}})
                    walk(ch, path + ".", level + 1)
                continue
            if path in obj.key:
                continue
            out.append({"path": path, "type": ch.type, "secret": ch.secret, "semantic": dict(ch.semantic)})

    walk(obj, "", 1)
    return out


class GraphIndex:
    """一张配置图的 contains 树索引。"""

    def __init__(self, g: nx.MultiDiGraph):
        self.g = g
        self.children: dict[str, list[str]] = defaultdict(list)
        self.parent: dict[str, str] = {}
        self.by_schema: dict[str, list[str]] = defaultdict(list)
        for a, b, d in g.edges(data=True):
            if d.get("kind") == "contains":
                self.children[a].append(b)
                self.parent[b] = a
        for n, d in g.nodes(data=True):
            if d.get("kind") == "object" and d.get("schema"):
                self.by_schema[str(d["schema"])].append(n)
        self.profile = str(g.graph.get("profile") or "")

    def objects(self, schema: str) -> list[str]:
        """该类型的对象实例，按配置中的行号排序（没有行号的派生对象排在后面）。"""
        nodes = list(self.by_schema.get(schema, []))
        return sorted(nodes, key=lambda n: (min(self.g.nodes[n].get("lines") or [10**9]), n))

    def child(self, nid: str, schema: str) -> list[str]:
        return [c for c in self.children.get(nid, []) if self.g.nodes[c].get("schema") == schema]

    def subtree_lines(self, nid: str) -> list[int]:
        acc: set[int] = set(self.g.nodes[nid].get("lines") or [])
        stack = list(self.children.get(nid, []))
        while stack:
            n = stack.pop()
            acc.update(self.g.nodes[n].get("lines") or [])
            stack.extend(self.children.get(n, []))
        return sorted(acc)


def key_value(key: Any, fieldname: str, obj: SchemaNode) -> Any:
    if isinstance(key, dict):
        return key.get(fieldname)
    return key if (not obj.key or obj.key[0] == fieldname) else None


def supported(kb: KnowledgeBase, profile: str, schema: str, cache: dict[tuple[str, str], bool] | None = None) -> bool:
    """Profile 是否明确标了不支持（没有条目视为可能支持）。"""
    ck = (profile, schema)
    if cache is not None and ck in cache:
        return cache[ck]
    ok = True
    if profile in kb.profiles:
        e = kb.resolve_profile(profile).entries.get(schema)
        ok = not (e is not None and not e.supported)
    if cache is not None:
        cache[ck] = ok
    return ok


class Extractor:
    """在一张图上按路径取格子。"""

    def __init__(self, g: nx.MultiDiGraph, kb: KnowledgeBase):
        self.g, self.kb = g, kb
        self.ix = GraphIndex(g)
        self._sup: dict[tuple[str, str], bool] = {}
        self._entries = kb.resolve_profile(self.ix.profile).entries if self.ix.profile in kb.profiles else {}

    def cell(self, obj_node: str, obj: SchemaNode, path: str, with_defaults: bool = True) -> Cell:
        chain = resolve_field(self.kb, obj, path)
        owners = [(obj_node, obj)]
        for step in chain[:-1]:
            assert isinstance(step, SchemaNode)
            owners = [(c, step) for o, _ in owners for c in self.ix.child(o, step.id)]
        last = chain[-1]
        vals: list[Any] = []
        nodes: list[str] = []
        lines: set[int] = set()
        origins: set[str] = set()
        secret = isinstance(last, SchemaNode) and last.secret
        for o, osn in owners:
            od = self.g.nodes[o]
            if isinstance(last, str):  # 键字段
                v = key_value(od.get("key"), last, osn)
                if v not in (None, ""):
                    vals.append(v)
                    nodes.append(o)
                    lines.update(od.get("lines") or [])
                    origins.add(str(od.get("origin") or "explicit"))
                continue
            if last.type == "object":  # 子对象本身：取它的键
                for c in self.ix.child(o, last.id):
                    cd = self.g.nodes[c]
                    vals.append(cd.get("key"))
                    nodes.append(c)
                    lines.update(cd.get("lines") or [])
                    origins.add(str(cd.get("origin") or "explicit"))
                continue
            found = self.ix.child(o, last.id)
            if not found:
                # 没有属性节点：如果它同时是所属对象的键字段，取键
                short = last.id[len(osn.id) + 1 :]
                if short in osn.key:
                    v = key_value(od.get("key"), short, osn)
                    if v not in (None, ""):
                        vals.append(v)
                        nodes.append(o)
                        lines.update(od.get("lines") or [])
                        origins.add(str(od.get("origin") or "explicit"))
                continue
            for c in found:
                cd = self.g.nodes[c]
                origin = str(cd.get("origin") or "explicit")
                if origin == "default" and not with_defaults:
                    continue
                value = cd.get("value")
                if cd.get("negated") and not isinstance(value, bool):
                    e = self._entries.get(last.id)
                    if e is None or e.default is None:
                        continue
                    value, origin = e.default, "default"
                vals.append(value)
                nodes.append(c)
                lines.update(cd.get("lines") or [])
                origins.add(origin)
        if not vals:
            if isinstance(last, SchemaNode) and not supported(self.kb, self.ix.profile, last.id, self._sup):
                return Cell(None, "unsupported", secret=secret)
            return Cell(False if secret else None, "none", secret=secret)
        origin = "explicit" if "explicit" in origins else ("derived" if "derived" in origins else "default")
        out: Any = vals[0] if len(vals) == 1 else vals
        if secret:
            out = True  # 只说明已配置，不输出取值
        return Cell(out, origin, nodes, sorted(lines), secret)


def display(v: Any) -> str:
    """格子取值的文本写法（表格、CSV、回答校验共用）。"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, dict):
        return ",".join(f"{k}={'' if x is None else x}" for k, x in v.items())
    if isinstance(v, list):
        return ", ".join(display(x) for x in v)
    return str(v)
