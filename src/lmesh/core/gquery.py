"""受限的图查询语言（M5-5）：AI 把自然语言问题写成这种查询，由代码校验语法与 Schema 路径后执行。

写法（关键字不分大小写；只读，只能查对象与属性，不能修改）：

    FIND <对象类型> [ON <设备>[, <设备>…] | ON *]
      [WHERE <条件> [AND <条件>]…]
      [RETURN <字段>[, <字段>…]]
      [WITH DEFAULTS]
      [LIMIT <行数>]

    条件：<字段> = | != | ~ | !~ | > | < | >= | <= <取值>；<字段> IN (<取值>, …)；<字段> EXISTS；<字段> NOT EXISTS

- 对象类型是 Schema 中的对象节点（interface、bgp.peer、vrf.instance、static.route…）。
- 字段是相对对象的 Schema 路径（description、ipv4.address、af.rd），或对象的键字段（name、address），或 device。
- WHERE 按有效值比较（显式值，否则 Profile 默认值）；~ 是正则（不分大小写）；多个取值（多个地址）任一满足即可，!= / !~ 要求都不满足。
- RETURN 的格子默认只给配置了的值；WITH DEFAULTS 时也给出 Profile 默认值（来源标为 default）。
- 同一请求也可以直接用 JSON 形式：{"find", "on", "where": [{"field", "op", "value"}], "return", "with_defaults", "limit"}。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from lmesh.core import compare
from lmesh.core.kb import KnowledgeBase, SchemaNode
from lmesh.core.objtable import Cell, Extractor, TableError, display, resolve_field, resolve_type

OPS = ("=", "!=", "~", "!~", ">", "<", ">=", "<=", "in", "exists", "not_exists")
MAX_LIMIT = 1000
DEFAULT_LIMIT = 200
_TOKEN = re.compile(
    r"""\s*(?:
      (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
    | (?P<op>!=|!~|>=|<=|=|~|>|<)
    | (?P<punct>[(),*])
    | (?P<word>[^\s(),=!~<>"']+)
    )""",
    re.X,
)
_KEYWORDS = {"find", "on", "where", "and", "return", "with", "defaults", "limit", "in", "exists", "not"}


class QueryError(ValueError):
    def __init__(self, key: str, **fmt: Any):
        super().__init__(key)
        self.key, self.fmt = key, fmt
        self.kind = "param"


@dataclass
class Cond:
    field: str
    op: str
    value: Any = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"field": self.field, "op": self.op}
        if self.op not in ("exists", "not_exists"):
            out["value"] = self.value
        return out


@dataclass
class Query:
    find: str
    on: list[str] = field(default_factory=list)  # 空表示全部设备
    where: list[Cond] = field(default_factory=list)
    ret: list[str] = field(default_factory=list)
    with_defaults: bool = False
    limit: int = DEFAULT_LIMIT

    def as_dict(self) -> dict[str, Any]:
        return {
            "find": self.find,
            "on": self.on,
            "where": [c.as_dict() for c in self.where],
            "return": self.ret,
            "with_defaults": self.with_defaults,
            "limit": self.limit,
        }

    def text(self) -> str:
        """规范写法（界面显示与回放用）。"""
        out = [f"FIND {self.find}", "ON " + (", ".join(_q(d) for d in self.on) if self.on else "*")]
        if self.where:
            parts = []
            for c in self.where:
                if c.op == "exists":
                    parts.append(f"{c.field} EXISTS")
                elif c.op == "not_exists":
                    parts.append(f"{c.field} NOT EXISTS")
                elif c.op == "in":
                    parts.append(f"{c.field} IN ({', '.join(_q(v) for v in c.value)})")
                else:
                    parts.append(f"{c.field} {c.op} {_q(c.value)}")
            out.append("WHERE " + " AND ".join(parts))
        if self.ret:
            out.append("RETURN " + ", ".join(self.ret))
        if self.with_defaults:
            out.append("WITH DEFAULTS")
        if self.limit != DEFAULT_LIMIT:
            out.append(f"LIMIT {self.limit}")
        return "\n".join(out)


def _q(v: Any) -> str:
    s = str(v)
    if re.fullmatch(r"[^\s(),=!~<>\"']+", s) and s.lower() not in _KEYWORDS:
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---------------------------------------------------------------- 解析


def _tokens(text: str) -> list[tuple[str, str, int]]:
    out: list[tuple[str, str, int]] = []
    pos = 0
    text = text.strip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise QueryError("query.syntax", pos=pos, near=text[pos : pos + 20])
        kind = m.lastgroup or ""
        val = m.group(kind)
        if kind == "str":
            val = re.sub(r"\\(.)", r"\1", val[1:-1])
        out.append((kind, val, m.start(kind)))
        pos = m.end()
    return out


class _Parser:
    def __init__(self, text: str):
        self.toks = _tokens(text)
        self.i = 0
        self.text = text

    def peek(self) -> tuple[str, str, int] | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def kw(self, word: str) -> bool:
        t = self.peek()
        if t and t[0] == "word" and t[1].lower() == word:
            self.i += 1
            return True
        return False

    def need_kw(self, word: str) -> None:
        if not self.kw(word):
            self.fail(f"expected {word.upper()}")

    def fail(self, what: str) -> None:
        t = self.peek()
        raise QueryError("query.syntax", pos=t[2] if t else len(self.text), near=(t[1] if t else what))

    def value(self) -> str:
        t = self.peek()
        if t is None or t[0] not in ("word", "str"):
            self.fail("value")
        assert t is not None
        self.i += 1
        return t[1]

    def punct(self, ch: str) -> bool:
        t = self.peek()
        if t and t[0] == "punct" and t[1] == ch:
            self.i += 1
            return True
        return False

    def parse(self) -> Query:
        self.need_kw("find")
        q = Query(find=self.value())
        if self.kw("on"):
            if self.punct("*"):
                q.on = []
            else:
                q.on = [self.value()]
                while self.punct(","):
                    q.on.append(self.value())
        if self.kw("where"):
            q.where.append(self.cond())
            while self.kw("and"):
                q.where.append(self.cond())
        if self.kw("return"):
            q.ret = [self.value()]
            while self.punct(","):
                q.ret.append(self.value())
        if self.kw("with"):
            self.need_kw("defaults")
            q.with_defaults = True
        if self.kw("limit"):
            v = self.value()
            if not v.isdigit():
                raise QueryError("query.bad_limit", value=v)
            q.limit = int(v)
        if self.peek() is not None:
            self.fail("end")
        return q

    def cond(self) -> Cond:
        f = self.value()
        if self.kw("exists"):
            return Cond(f, "exists")
        if self.kw("not"):
            self.need_kw("exists")
            return Cond(f, "not_exists")
        if self.kw("in"):
            if not self.punct("("):
                self.fail("(")
            vals = [self.value()]
            while self.punct(","):
                vals.append(self.value())
            if not self.punct(")"):
                self.fail(")")
            return Cond(f, "in", vals)
        t = self.peek()
        if t is None or t[0] != "op":
            self.fail("operator")
        assert t is not None
        self.i += 1
        return Cond(f, t[1], self.value())


def parse(text: str) -> Query:
    if not text or not text.strip():
        raise QueryError("query.empty")
    return _Parser(text).parse()


def from_dict(d: dict[str, Any]) -> Query:
    try:
        where = []
        for c in d.get("where") or []:
            op = str(c.get("op", "=")).lower()
            op = {"not exists": "not_exists", "==": "="}.get(op, op)
            where.append(Cond(str(c["field"]), op, c.get("value")))
        on = d.get("on") or []
        if isinstance(on, str):
            on = [] if on.strip() in ("", "*") else [x.strip() for x in on.split(",")]
        return Query(
            find=str(d["find"]),
            on=[str(x) for x in on],
            where=where,
            ret=[str(x) for x in d.get("return") or []],
            with_defaults=bool(d.get("with_defaults", False)),
            limit=int(d.get("limit", DEFAULT_LIMIT)),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise QueryError("query.bad_json") from e


def coerce(q: str | dict[str, Any] | Query) -> Query:
    if isinstance(q, Query):
        return q
    if isinstance(q, dict):
        return from_dict(q)
    return parse(q)


# ---------------------------------------------------------------- 校验


def validate(q: Query, kb: KnowledgeBase, devices: list[str] | None = None) -> SchemaNode:
    """对象类型、字段路径、运算符、行数、设备名都要合法；不合法时抛出 QueryError。"""
    try:
        obj = resolve_type(kb, q.find)
    except TableError as e:
        raise QueryError("query.bad_object", object=q.find) from e
    q.find = obj.id
    for f in [*(c.field for c in q.where), *q.ret]:
        if f in ("device", "@key"):
            continue
        try:
            resolve_field(kb, obj, f)
        except TableError as e:
            raise QueryError("query.bad_field", field=f, object=obj.id) from e
    for c in q.where:
        if c.op not in OPS:
            raise QueryError("query.bad_op", op=c.op)
        if c.op == "in" and not isinstance(c.value, list):
            c.value = [c.value]
        if c.op in ("~", "!~"):
            try:
                re.compile(str(c.value))
            except re.error as e:
                raise QueryError("query.bad_regex", value=str(c.value)) from e
    if not 1 <= q.limit <= MAX_LIMIT:
        raise QueryError("query.bad_limit", value=q.limit)
    if devices is not None:
        known = {d.lower() for d in devices}
        for d in q.on:
            if d.lower() not in known:
                raise QueryError("query.bad_device", device=d)
    return obj


# ---------------------------------------------------------------- 执行


def _num(v: Any) -> float | None:
    try:
        return float(str(v))
    except (TypeError, ValueError):
        return None


def value_type(kb: KnowledgeBase, obj: SchemaNode, f: str) -> str:
    """字段取值的类型（比较时按类型规范化：接口名缩写、掩码与前缀、RD 写法……）。"""
    if f in ("device", "@key"):
        return "string" if f == "device" else compare._Schema(kb).field_type(obj, obj.key[0] if obj.key else "name")[0]
    chain = resolve_field(kb, obj, f)
    last = chain[-1]
    if isinstance(last, SchemaNode):
        return "string" if last.type == "object" else last.type
    owner = chain[-2] if len(chain) > 1 and isinstance(chain[-2], SchemaNode) else obj
    return compare._Schema(kb).field_type(owner, last)[0]


def _norm(v: Any, t: str) -> str:
    s = display(v).strip()
    if t == "interface":
        return compare.interface_name(s).lower()
    if isinstance(v, bool) or s.lower() in ("true", "false"):
        return s.lower()
    try:
        return str(compare.norm_scalar(t or "string", s)).lower()
    except Exception:
        return s.lower()


def _match(op: str, cell: Cell, want: Any, t: str = "string") -> bool:
    present = cell.origin not in ("none", "unsupported")
    if op == "exists":
        return present and (not cell.secret or bool(cell.value))
    if op == "not_exists":
        return not present
    if not present:
        return op in ("!=", "!~")
    vals = cell.value if isinstance(cell.value, list) else [cell.value]
    if op in ("=", "!=", "in"):
        wants = want if isinstance(want, list) else [want]
        nw = {_norm(w, t) for w in wants}
        hit = any(_norm(v, t) in nw for v in vals)
        return not hit if op == "!=" else hit
    if op in ("~", "!~"):
        rx = re.compile(str(want), re.I)
        hit = any(rx.search(display(v)) for v in vals)
        return not hit if op == "!~" else hit
    w = _num(want)
    for v in vals:
        x = _num(v)
        if x is None or w is None:
            continue
        if (op == ">" and x > w) or (op == "<" and x < w) or (op == ">=" and x >= w) or (op == "<=" and x <= w):
            return True
    return False


def _key_text(key: Any) -> str:
    return display(key)


def execute(q: str | dict[str, Any] | Query, devices: list[Any], kb: KnowledgeBase) -> dict[str, Any]:
    """devices：topology.Device 列表（name、g、device_id、version_id）。返回列、行（每格带节点与行号）与统计。"""
    query = coerce(q)
    obj = validate(query, kb, [d.name for d in devices])
    wanted = {d.lower() for d in query.on}
    chosen = [d for d in devices if not wanted or d.name.lower() in wanted]
    ret = query.ret or list(obj.key)
    sns: dict[str, SchemaNode | None] = {}
    for f in {*ret, *(c.field for c in query.where)}:
        if f in ("device", "@key"):
            sns[f] = None
            continue
        last = resolve_field(kb, obj, f)[-1]
        sns[f] = last if isinstance(last, SchemaNode) else None
    types = {c.field: value_type(kb, obj, c.field) for c in query.where}
    rows: list[dict[str, Any]] = []
    total = 0
    for dev in chosen:
        ex = Extractor(dev.g, kb)
        for nid in ex.ix.objects(obj.id):
            nd = dev.g.nodes[nid]

            def get(
                f: str, defaults: bool, nid: str = nid, nd: dict[str, Any] = nd, ex: Extractor = ex, dev: Any = dev
            ) -> Cell:
                if f == "device":
                    return Cell(dev.name, "explicit", [], [])
                if f == "@key":
                    return Cell(nd.get("key"), str(nd.get("origin") or "explicit"), [nid], list(nd.get("lines") or []))
                return ex.cell(nid, obj, f, with_defaults=defaults)

            if not all(_match(c.op, get(c.field, True), c.value, types[c.field]) for c in query.where):
                continue
            total += 1
            if len(rows) >= query.limit:
                continue
            cells = {f: get(f, query.with_defaults).as_dict() for f in ret}
            rows.append(
                {
                    "n": len(rows) + 1,
                    "device": dev.name,
                    "device_id": getattr(dev, "device_id", None),
                    "version_id": getattr(dev, "version_id", None),
                    "node": nid,
                    "schema": obj.id,
                    "key": nd.get("key"),
                    "label": _key_text(nd.get("key")),
                    "lines": ex.ix.subtree_lines(nid),
                    "cells": cells,
                }
            )
    return {
        "query": query.as_dict(),
        "text": query.text(),
        "object": obj.id,
        "columns": [
            {
                "field": f,
                "schema": sns[f].id if sns.get(f) is not None else None,  # type: ignore[union-attr]
                "type": sns[f].type if sns.get(f) is not None else ("key" if f not in ("device",) else "device"),  # type: ignore[union-attr]
                "secret": bool(sns[f].secret) if sns.get(f) is not None else False,  # type: ignore[union-attr]
            }
            for f in ret
        ],
        "rows": rows,
        "count": total,
        "truncated": total > len(rows),
        "devices": [d.name for d in chosen],
    }


def grammar() -> dict[str, Any]:
    """查询语言说明（给 AI 的提示与 API 文档用）。"""
    return {
        "syntax": "FIND <object> [ON <device>[, ...] | ON *] [WHERE <field> <op> <value> [AND ...]] "
        "[RETURN <field>[, ...]] [WITH DEFAULTS] [LIMIT n]",
        "ops": ["=", "!=", "~ (regex)", "!~", ">", "<", ">=", "<=", "IN (a, b)", "EXISTS", "NOT EXISTS"],
        "notes": [
            "object is a Schema object id such as interface, bgp.peer, vrf.instance, static.route",
            "field is a Schema path relative to the object (description, ipv4.address, af.rd) or a key field (name)",
            "WHERE compares effective values (explicit, otherwise the Profile default)",
            "read only; no OR, no joins: issue a query per object type",
        ],
    }
