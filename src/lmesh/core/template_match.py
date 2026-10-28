"""模板校验与变量提取（约束匹配）：在图上按有效值比较，不做文本比较。

编译（compile_template）：
    1. 每个变量取一个按类型生成、互不相同的探针值，渲染整份正文（重复块渲染一个实例、可选块都带上），解析建图后
       用对比模块的规范化（_Canonicalizer）得到规范编号与有效值；
    2. 每个块再渲染一次“去掉这个块”的正文，两次结果的差就是这个块产生的节点；
    3. 每个显式节点变成一个模式（PItem）：对象的键、属性的有效值里出现的探针值（只看该节点所在行用到的表达式）
       换成变量，其余是固定值。Profile 补出的默认节点不进模式——模板没写的属性由“模板外的配置”处理。
匹配（check）：
    沿 contains 层级，父模式对上实际对象后在它下面找子模式；对象的键能对上多个实际对象时（例如 {{uplink}}）
    先试探每个候选能对上多少子模式，取最多的。基础部分先匹配，再按块：重复块的“锚点”对象（键里含块变量）
    在实际配置中的每个匹配是一个实例；可选块有匹配就算出现。
    捕获的表达式值反推出变量（派生关系与过滤器逐个验算），再检查类型与约束。
结果：符合、逐项原因（缺少、取值不符、前后不一致、违反约束、实例个数、模板外的配置），附实际配置与模板正文的行号。
"""

from __future__ import annotations

import ipaddress
import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from lmesh.core import analysis
from lmesh.core import graph as graphmod
from lmesh.core.compare import (
    Item,
    Multi,
    _Canon,
    _Canonicalizer,
    _mask_len,
    _Schema,
    _sort_key,
    norm_scalar,
    norm_value,
)
from lmesh.core.kb import KnowledgeBase
from lmesh.core.template import (
    INT_TYPES,
    Expr,
    OutLine,
    Template,
    TemplateError,
    Var,
    check_value,
    evaluate,
    render_lines,
    resolve_expr,
)

SEVERITY = {
    "missing": "error",
    "value": "error",
    "inconsistent": "error",
    "constraint": "error",
    "count": "error",
    "ambiguous": "info",
    "unknown_line": "warning",
}

_IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_PREFIX = re.compile(r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$")


# ---------------------------------------------------------------- 取值的各种写法


def forms(s: str) -> set[str]:
    """一个渲染出的字符串在规范化之后可能的样子（掩码 → 长度、接口名全称、大小写……）。"""
    out = {s, s.lower(), s.strip()}
    for t in ("integer", "ipv4", "prefix", "interface", "rd", "asn"):
        try:
            out.add(str(norm_scalar(t, s)))
        except (ValueError, TypeError):
            continue
    out.add(_mask_len(s))
    return {x for x in out if x}


def equivalent(a: str, b: str) -> bool:
    return a == b or a in forms(b) or b in forms(a)


# ---------------------------------------------------------------- 模式


@dataclass
class Pat:
    kind: str  # fixed / var / regex / list
    value: Any = None
    expr: str | None = None
    regex: re.Pattern[str] | None = None
    groups: list[str] = field(default_factory=list)
    items: list[Pat] = field(default_factory=list)
    display: str = ""

    @property
    def exprs(self) -> set[str]:
        if self.kind == "var" and self.expr:
            return {self.expr}
        if self.kind == "regex":
            return set(self.groups)
        if self.kind == "list":
            return set().union(*(p.exprs for p in self.items)) if self.items else set()
        return set()


def _edge_ok(s: str, start: int, end: int) -> bool:
    """子串替换的边界：数字不能紧挨数字、字母不能紧挨字母（ABIS{{vlan}} 可以，1{{vlan}} 不行）。"""

    def cls(ch: str) -> str:
        return "d" if ch.isdigit() else "a" if ch.isalpha() else "o"

    if start > 0 and cls(s[start - 1]) == cls(s[start]) != "o":
        return False
    return not (end < len(s) and cls(s[end]) == cls(s[end - 1]) != "o")


def _group_re(form: str, var_type: str) -> str:
    if form.isdigit():
        return r"\d+"
    if _IPV4.match(form):
        return r"\d{1,3}(?:\.\d{1,3}){3}"
    if _PREFIX.match(form):
        return r"\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}"
    if var_type == "text":
        return r".+?"
    return r"\S+?"


def build_pat(value: Any, exprs: dict[str, str], types: dict[str, str]) -> Pat:
    """把模板图中的一个取值变成模式：等于某个表达式的探针值 → 变量；包含探针值 → 正则；否则固定值。"""
    if value is None or isinstance(value, bool):
        return Pat("fixed", value, display=str(value))
    if isinstance(value, list):
        items = [build_pat(v, exprs, types) for v in value]
        if all(p.kind == "fixed" for p in items):
            return Pat("fixed", value, display=_sort_key(value))
        return Pat("list", items=items, display="[" + ", ".join(p.display for p in items) + "]")
    s = str(value)
    exact = [e for e, r in exprs.items() if s in forms(r)]
    if exact:
        exact.sort(key=lambda e: (exprs[e] != s, e))
        return Pat("var", expr=exact[0], display="{" + exact[0] + "}")
    reps: list[tuple[str, str]] = []
    for e, r in exprs.items():
        for f in forms(r):
            if len(f) >= 2 and f in s:
                reps.append((f, e))
    if not reps:
        return Pat("fixed", value, display=s)
    reps.sort(key=lambda x: -len(x[0]))
    i, parts, groups, disp = 0, [], [], []
    while i < len(s):
        hit = next(((f, e) for f, e in reps if s.startswith(f, i) and _edge_ok(s, i, i + len(f))), None)
        if hit is None:
            parts.append(re.escape(s[i]))
            disp.append(s[i])
            i += 1
            continue
        f, e = hit
        parts.append(f"({_group_re(f, types.get(e, 'word'))})")
        groups.append(e)
        disp.append("{" + e + "}")
        i += len(f)
    if not groups:
        return Pat("fixed", value, display=s)
    return Pat("regex", regex=re.compile("".join(parts)), groups=groups, display="".join(disp))


def match_pat(p: Pat | None, value: Any) -> list[tuple[str, str]] | None:
    """模式对实际取值：对上时返回捕获的（表达式, 取值）列表，对不上返回 None。"""
    if p is None:
        return []
    if p.kind == "fixed":
        if p.value == value:
            return []
        if isinstance(p.value, bool) or isinstance(value, bool):
            return None
        return [] if p.value is not None and value is not None and str(p.value) == str(value) else None
    if value is None or isinstance(value, bool | dict):
        return None
    if p.kind == "var":
        if isinstance(value, list):
            return None
        return [(str(p.expr), str(value))]
    if p.kind == "regex":
        if isinstance(value, list):
            return None
        assert p.regex is not None
        m = p.regex.fullmatch(str(value))
        return list(zip(p.groups, m.groups(), strict=True)) if m else None
    # list：元素一一对上（无序）
    vals = value if isinstance(value, list) else [value]
    if len(vals) != len(p.items):
        return None
    return _match_list(p.items, list(vals))


def _match_list(pats: list[Pat], vals: list[Any]) -> list[tuple[str, str]] | None:
    if not pats:
        return []
    head, rest = pats[0], pats[1:]
    for i, v in enumerate(vals):
        caps = match_pat(head, v)
        if caps is None:
            continue
        more = _match_list(rest, vals[:i] + vals[i + 1 :])
        if more is not None:
            return caps + more
    return None


def match_key(key_pat: dict[str, Pat] | Pat | None, key: Any) -> list[tuple[str, str]] | None:
    if isinstance(key_pat, dict):
        if not isinstance(key, dict) or set(key_pat) != set(key):
            return None
        caps: list[tuple[str, str]] = []
        for f, p in key_pat.items():
            c = match_pat(p, key[f])
            if c is None:
                return None
            caps += c
        return caps
    if isinstance(key, dict):
        return None
    return match_pat(key_pat, key)


def merge(b: dict[str, str], caps: list[tuple[str, str]]) -> dict[str, str] | None:
    """捕获并入已有的绑定；同一表达式前后取值不同时返回 None。"""
    if not caps:
        return b
    out = dict(b)
    for e, v in caps:
        if e in out:
            if not equivalent(out[e], v):
                return None
        else:
            out[e] = v
    return out


# ---------------------------------------------------------------- 编译


@dataclass
class PItem:
    idx: int
    kind: str  # object / attr / ext / raw
    schema: str  # ext：命令卡；raw：""
    parent: int | None
    block: str | None
    node: str  # 显示用的编号（探针值换成 {表达式}）
    key: dict[str, Pat] | Pat | None = None
    value: Pat | None = None
    group: str = ""
    tlines: list[int] = field(default_factory=list)
    children: list[int] = field(default_factory=list)
    domain: str = ""

    @property
    def exprs(self) -> set[str]:
        out: set[str] = set()
        if isinstance(self.key, dict):
            for p in self.key.values():
                out |= p.exprs
        elif self.key is not None:
            out |= self.key.exprs
        if self.value is not None:
            out |= self.value.exprs
        return out


@dataclass
class Compiled:
    template: Template
    family: str
    items: list[PItem]
    exprs: dict[str, Expr]  # 表达式文本 → 表达式
    probe: dict[str, Any]  # 探针参数（一行）
    probe_text: str
    domains: set[str]
    warnings: list[dict[str, Any]]


class _Probe:
    """按类型生成互不相同的探针值；seed 不同时整体错开，用于避开与正文中固定内容的冲突。"""

    def __init__(self, seed: int):
        self.seed, self.i = seed, 0
        self.used: set[str] = set()

    def value(self, v: Var) -> Any:
        self.i += 1
        i, k = self.i, self.seed
        for attempt in range(200):
            j = i * 17 + attempt * 31 + k * 101
            cand = self._gen(v, j, attempt == 0 and k == 0)
            key = str(cand)
            if key not in self.used and not (v.type in INT_TYPES and len(key) < 2 and attempt < 100):
                self.used.add(key)
                return cand
        raise TemplateError("template.probe_failed", var=v.name)

    @staticmethod
    def _gen(v: Var, j: int, first: bool) -> Any:
        t = v.type
        if t in ("integer", "vlan", "asn"):
            lo = v.min if v.min is not None else {"vlan": 2, "asn": 64600}.get(t, 1)
            hi = v.max if v.max is not None else {"vlan": 4094, "asn": 65500}.get(t, 65535)
            span = hi - lo + 1
            base = 3001 if t == "vlan" else 4100 if t == "integer" else 0
            return lo + (base + j * 7) % span if span > 0 else lo
        if t == "ipv4":
            return f"198.18.{20 + j % 200}.{21 + (j * 7) % 200}"
        if t == "prefix":
            lo, hi = v.length or (24, 24)
            length = max(lo, min(hi, 30)) if lo <= 30 else lo
            net = ipaddress.IPv4Network(f"198.19.{j % 250}.{(j * 64) % 256}/{length}", strict=False)
            off = 0 if v.network or net.num_addresses < 8 else 5
            if net.num_addresses <= 2:
                off = 0
            return f"{net.network_address + off}/{length}"
        if t == "rd":
            return f"{64900 + j % 90}:{7100 + j}"
        if t == "enum":
            return v.choices[j % len(v.choices)] if v.choices else "x"
        if t == "interface":
            if first and v.example:
                return str(v.example)
            return f"GigabitEthernet0/{7 + j % 3}/{11 + j % 40}"
        if t == "text":
            return f"LMTXT-{j}"
        return f"LMW{j}Q"


def _probe_row(t: Template, seed: int) -> dict[str, Any]:
    pr = _Probe(seed)
    row: dict[str, Any] = {v.name: pr.value(v) for v in t.input_vars(None)}
    for b in t.blocks.values():
        inst = {v.short: pr.value(v) for v in t.input_vars(b.name)}
        row[b.name] = [inst] if b.kind == "repeat" else (inst or True)
    return row


def _collides(t: Template, lines: list[OutLine]) -> bool:
    """同一行中两个表达式渲染相同，或探针值恰好出现在这一行的固定文字里：换一组探针。"""
    src = {}
    for seg in t.segments:
        for ln in seg.lines if seg.block else [seg]:
            src[ln.line_no] = ln.text
    from lmesh.core.template import PLACEHOLDER

    for ol in lines:
        vals = list(ol.exprs.values())
        if len(set(vals)) != len(vals):
            return True
        fixed = PLACEHOLDER.sub(" ", src.get(ol.src, ""))
        for v in vals:
            for f in forms(v):
                if len(f) >= 2 and re.search(rf"(?<![\w.]){re.escape(f)}(?![\w])", fixed):
                    return True
    return False


def _canon(text: str, kb: KnowledgeBase, profile: str, label: str) -> tuple[_Canon, nx.MultiDiGraph, Any]:
    res = analysis.parse_text(text, kb, profile)
    g = graphmod.build(res.parsed, kb, res.profile, label)
    return _Canonicalizer(g, kb, _Schema(kb)).run(), g, res


def _multi_key(m: Multi) -> tuple[str, str, str]:
    return (m.owner, m.group, m.sig)


_cache: dict[tuple[str, str, int], Compiled] = {}
_cache_lock = threading.Lock()


def compile_template(t: Template, kb: KnowledgeBase) -> Compiled:
    key = (t.digest, kb.version, id(kb))
    with _cache_lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit
    comp = _compile(t, kb)
    with _cache_lock:
        if len(_cache) > 64:
            _cache.clear()
        _cache[key] = comp
    return comp


def _compile(t: Template, kb: KnowledgeBase) -> Compiled:
    if t.profile not in kb.profiles:
        raise TemplateError("template.profile_unknown", "invalid", profile=t.profile)
    row: dict[str, Any] = {}
    lines: list[OutLine] = []
    for seed in range(8):
        row = _probe_row(t, seed)
        lines = render_lines(t, row)
        if not _collides(t, lines):
            break
    text = "\n".join(ln.text for ln in lines) + "\n"
    full, _, res = _canon(text, kb, t.profile, "template")
    warnings: list[dict[str, Any]] = []
    for ln in res.parsed.unknown():
        src = lines[ln.no - 1].src if 0 < ln.no <= len(lines) else 0
        warnings.append(
            {"kind": "unknown_line", "template_lines": [src], "text": ln.text.strip(), "key": "template.warn.unknown"}
        )
    # 每个块产生的节点：完整正文减去“去掉这个块”的正文
    block_items: dict[str, set[str]] = {}
    block_multis: dict[str, set[tuple[str, str, str]]] = {}
    for b in t.blocks.values():
        without = dict(row)
        without[b.name] = [] if b.kind == "repeat" else False
        c2, _, _ = _canon(render_text_lines(render_lines(t, without)), kb, t.profile, "template")
        # 去掉块后不存在、或只剩 Profile 默认值、或取值不同的节点都属于这个块（例如可选块里的 shutdown）
        block_items[b.name] = {
            cid
            for cid, it in full.items.items()
            if cid not in c2.items or c2.items[cid].origin != it.origin or c2.items[cid].value != it.value
        }
        have = {_multi_key(m) for m in [*c2.ext, *c2.raw]}
        block_multis[b.name] = {_multi_key(m) for m in [*full.ext, *full.raw]} - have

    exprs: dict[str, Expr] = {}
    types: dict[str, str] = {}
    for ol in lines:
        for etext in ol.exprs:
            if etext not in exprs:
                e = _expr_from_text(t, etext)
                exprs[etext] = e
                types[etext] = t.vars[e.var].type

    def line_exprs(nums: list[int]) -> dict[str, str]:
        out: dict[str, str] = {}
        for n in nums:
            if 0 < n <= len(lines):
                out.update(lines[n - 1].exprs)
        return out

    def src_lines(nums: list[int]) -> list[int]:
        return sorted({lines[n - 1].src for n in nums if 0 < n <= len(lines)})

    def display(cid: str, ex: dict[str, str]) -> str:
        reps = sorted(((f, e) for e, r in ex.items() for f in forms(r) if len(f) >= 2), key=lambda x: -len(x[0]))
        out, i = [], 0
        while i < len(cid):
            hit = next(((f, e) for f, e in reps if cid.startswith(f, i) and _edge_ok(cid, i, i + len(f))), None)
            if hit:
                out.append("{" + hit[1] + "}")
                i += len(hit[0])
            else:
                out.append(cid[i])
                i += 1
        return "".join(out)

    items: list[PItem] = []
    by_cid: dict[str, int] = {}
    anc_exprs: dict[str, dict[str, str]] = {"": {}}
    for cid, it in full.items.items():
        if it.origin != "explicit":
            continue
        if it.parent and it.parent not in by_cid:
            continue
        ex = line_exprs(it.lines)
        parent_ex = anc_exprs.get(it.parent, {})
        blk = next((b for b, s in block_items.items() if cid in s), None)
        sn = kb.nodes.get(it.schema)
        p = PItem(
            len(items),
            it.kind,
            it.schema,
            by_cid.get(it.parent) if it.parent else None,
            blk,
            display(cid, {**parent_ex, **ex}),
            tlines=src_lines(it.lines),
            domain=sn.domain if sn else "",
        )
        if it.kind == "object":
            if isinstance(it.key, dict):
                p.key = {f: build_pat(v, ex, types) for f, v in it.key.items()}
            else:
                p.key = build_pat(it.key, ex, types)
            anc_exprs[cid] = {**parent_ex, **ex}
            by_cid[cid] = p.idx
        else:
            p.value = build_pat(it.value, ex, types)
        items.append(p)
        if p.parent is not None:
            items[p.parent].children.append(p.idx)
    for m in [*full.ext, *full.raw]:
        if m.owner and m.owner not in by_cid:
            continue
        ex = line_exprs(m.lines)
        blk = next((b for b, s in block_multis.items() if _multi_key(m) in s), None)
        kind = "raw" if m.group == "raw" else "ext"
        p = PItem(
            len(items),
            kind,
            m.group if kind == "ext" else "",
            by_cid.get(m.owner) if m.owner else None,
            blk,
            display(
                f"{m.owner + '/' if m.owner else ''}{kind}[{m.sig if kind == 'raw' else m.group}]",
                {**anc_exprs.get(m.owner, {}), **ex},
            ),
            value=build_pat(m.sig, ex, types),
            group=m.group,
            tlines=src_lines(m.lines),
            domain=m.domain,
        )
        items.append(p)
        if p.parent is not None:
            items[p.parent].children.append(p.idx)
    domains = {p.domain for p in items if p.kind in ("object", "attr") and p.domain}
    for b in t.blocks.values():
        if not any(p.block == b.name for p in items):
            warnings.append({"kind": "empty_block", "block": b.name, "key": "template.warn.empty_block"})
    return Compiled(t, kb.profiles[t.profile].family, items, exprs, row, text, domains, warnings)


def render_text_lines(lines: list[OutLine]) -> str:
    return "\n".join(ln.text for ln in lines) + "\n"


def _expr_from_text(t: Template, text: str) -> Expr:
    """渲染记录的表达式文本（变量全名 + 过滤器）→ 表达式。"""
    from lmesh.core.template import parse_expr

    name, filters = parse_expr(text)
    if name not in t.vars:
        raise TemplateError("template.unknown_var", var=name)
    return Expr(name, tuple(filters))


# ---------------------------------------------------------------- 匹配


@dataclass
class _Rec:
    matched: dict[int, str] = field(default_factory=dict)  # 模式 → 实际编号
    used: set[str] = field(default_factory=set)
    findings: list[dict[str, Any]] = field(default_factory=list)
    count: int = 0
    prov: dict[str, tuple[int, str, list[int]]] = field(
        default_factory=dict
    )  # 表达式 → 首次捕获的（模式, 实际编号, 行号）

    def child(self) -> _Rec:
        return _Rec(dict(self.matched), set(self.used))

    def note(self, old: dict[str, str], new: dict[str, str], p: PItem, cid: str, lines: list[int]) -> None:
        for e in new.keys() - old.keys():
            self.prov.setdefault(e, (p.idx, cid, list(lines)))


class _Matcher:
    def __init__(self, comp: Compiled, canon: _Canon, kb: KnowledgeBase, same_family: bool):
        self.comp, self.c, self.kb, self.same_family = comp, canon, kb, same_family
        self.items = comp.items
        self.by_parent: dict[str, list[Item]] = defaultdict(list)
        for it in canon.items.values():
            self.by_parent[it.parent].append(it)
        self.multis: dict[tuple[str, str], list[Multi]] = defaultdict(list)
        for m in [*canon.ext, *canon.raw]:
            self.multis[(m.owner, m.group)].append(m)
        self.subtree: dict[int, int] = {}

    def size(self, idx: int) -> int:
        if idx not in self.subtree:
            self.subtree[idx] = 1 + sum(self.size(k) for k in self.items[idx].children)
        return self.subtree[idx]

    # ----- 单个模式

    def options(self, p: PItem, parent: str, b: dict[str, str], used: set[str]) -> list[tuple[Item, dict[str, str]]]:
        out = []
        for a in self.by_parent.get(parent, []):
            if a.kind != "object" or a.schema != p.schema or a.cid in used:
                continue
            caps = match_key(p.key, a.key)
            if caps is None:
                continue
            b2 = merge(b, caps)
            if b2 is not None:
                out.append((a, b2))
        out.sort(key=lambda x: (min(x[0].lines or [10**9]), x[0].cid))
        return out

    def finding(self, rec: _Rec, kind: str, p: PItem, scope: tuple[str | None, int | None], **kw: Any) -> None:
        if rec is None:
            return
        f = {
            "kind": kind,
            "severity": SEVERITY.get(kind, "error"),
            "block": scope[0],
            "instance": scope[1],
            "node": p.node,
            "node_kind": p.kind,
            "schema": p.schema or None,
            "domain": p.domain,
            "actual_node": kw.get("actual_node"),
            "expected": kw.get("expected"),
            "actual": kw.get("actual"),
            "actual_origin": kw.get("actual_origin"),
            "var": kw.get("var"),
            "count": kw.get("count"),
            "parent": kw.get("parent"),
            "lines": kw.get("lines", []),
            "template_lines": p.tlines,
        }
        rec.findings.append(f)

    def run(
        self,
        kids: list[int],
        parent: str,
        b: dict[str, str],
        rec: _Rec,
        scope: tuple[str | None, int | None],
        dry: bool = False,
    ) -> dict[str, str]:
        """在实际对象 parent 下匹配一组子模式（只处理属于当前块的）。"""
        block = scope[0]
        mine = [self.items[k] for k in kids if self.items[k].block == block]
        attrs = [p for p in mine if p.kind == "attr"]
        objs = [p for p in mine if p.kind == "object"]
        multis = [p for p in mine if p.kind in ("ext", "raw")]
        # 属性：同一对象下同一 Schema 只有一个实际节点（含 Profile 补出的默认节点，按有效值比较）
        for p in attrs:
            cands = [a for a in self.by_parent.get(parent, []) if a.kind == "attr" and a.schema == p.schema]
            if not cands:
                self.finding(rec, "missing", p, scope, parent=parent, expected=p.value.display if p.value else None)
                continue
            a = cands[0]
            rec.used.add(a.cid)
            caps = match_pat(p.value, a.value)
            if caps is None:
                self.finding(
                    rec,
                    "value",
                    p,
                    scope,
                    actual_node=a.cid,
                    expected=p.value.display if p.value else None,
                    actual=a.value,
                    actual_origin=a.origin,
                    lines=a.lines,
                )
                continue
            b2 = merge(b, caps)
            if b2 is None:
                e = next(e for e, v in caps if e in b and not equivalent(b[e], v))
                self.finding(
                    rec,
                    "inconsistent",
                    p,
                    scope,
                    actual_node=a.cid,
                    var=e,
                    expected=b[e],
                    actual=a.value,
                    actual_origin=a.origin,
                    lines=a.lines,
                )
                continue
            rec.note(b, b2, p, a.cid, a.lines)
            b = b2
            rec.matched[p.idx] = a.cid
            rec.count += 1
        pending = list(objs)
        while pending:
            # 先匹配键里未绑定变量最少的对象：前面对上的对象绑定了变量，后面的对象就能唯一确定
            p = min(pending, key=lambda q: (len(q.exprs - set(b)), pending.index(q)))
            pending.remove(p)
            opts = self.options(p, parent, b, rec.used)
            if not opts:
                self.finding(rec, "missing", p, scope, parent=parent, count=self.size(p.idx))
                continue
            pick = opts[0]
            if len(opts) > 1 and not dry:
                scored = [(self.score(p, a, b2, rec, scope), i, a, b2) for i, (a, b2) in enumerate(opts)]
                best = max(s for s, *_ in scored)
                tops = [x for x in scored if x[0] == best]
                pick = (tops[0][2], tops[0][3])
                if len(tops) > 1 and p.exprs - set(b):
                    self.finding(
                        rec,
                        "ambiguous",
                        p,
                        scope,
                        actual_node=pick[0].cid,
                        actual=[x[2].cid for x in tops[:5]],
                        lines=pick[0].lines,
                    )
            rec.note(b, pick[1], p, pick[0].cid, pick[0].lines)
            a, b = pick
            rec.matched[p.idx] = a.cid
            rec.used.add(a.cid)
            rec.count += 1
            b = self.run(p.children, a.cid, b, rec, scope, dry)
        for p in multis:
            if not self.same_family:
                continue
            pool = [m for m in self.multis.get((parent, p.group), []) if m.node not in rec.used]
            hit = None
            for m in pool:
                caps = match_pat(p.value, m.sig)
                b2 = merge(b, caps) if caps is not None else None
                if b2 is not None:
                    rec.note(b, b2, p, m.node, m.lines)
                    hit, b = m, b2
                    break
            if hit is None:
                self.finding(rec, "missing", p, scope, parent=parent, expected=p.value.display if p.value else None)
                continue
            rec.used.add(hit.node)
            rec.matched[p.idx] = hit.node
            rec.count += 1
        return b

    def score(self, p: PItem, a: Item, b: dict[str, str], rec: _Rec, scope: tuple[str | None, int | None]) -> int:
        """试探：对象 p 对上实际对象 a 时，它下面能对上多少个模式。"""
        r = rec.child()
        r.used.add(a.cid)
        self.run(p.children, a.cid, b, r, scope, dry=True)
        return r.count


# ---------------------------------------------------------------- 变量反推


def _solve_var(
    v: Var, caps: dict[Expr, list[str]], comp: Compiled
) -> tuple[Any, list[tuple[str, str, str]], str | None]:
    """由捕获反推变量取值。返回 (取值, 验算不符的 [(表达式, 期望, 实际)], 约束问题)。"""
    mine = {e: vs for e, vs in caps.items() if e.var == v.name}
    if not mine:
        return None, [], None
    value: Any = None
    direct = mine.get(Expr(v.name, ()))
    if direct:
        value = direct[0]
    elif v.type == "prefix":
        value = _solve_prefix(v, mine)
    else:
        for e, vs in mine.items():
            if len(e.filters) == 1 and e.filters[0][0] == "add":
                n = e.filters[0][1] or 0
                s = vs[0]
                value = str(int(s) - n) if s.isdigit() else str(ipaddress.IPv4Address(s) - n)
                break
            if len(e.filters) == 1 and e.filters[0][0] in ("upper", "lower"):
                value = vs[0]
                break
    if value is None:
        return None, [], None
    norm, problem = check_value(v, value)
    bad = []
    for e, vs in mine.items():
        try:
            want = evaluate(e, {v.name: norm})
        except (TemplateError, ValueError):
            want = None
        for got in vs:
            if want is None or not equivalent(want, got):
                bad.append((e.text, want or "", got))
    return norm, bad, problem


def _solve_prefix(v: Var, mine: dict[Expr, list[str]]) -> str | None:
    length: int | None = None
    addr: tuple[str, str, int] | None = None  # (过滤器, 地址, n)
    for e, vs in mine.items():
        if len(e.filters) != 1:
            continue
        name, arg = e.filters[0]
        s = vs[0]
        if name in ("len", "mask"):
            t = _mask_len(s)
            length = int(t) if t.isdigit() else length
        elif name == "wildcard":
            try:
                length = 32 - bin(int(ipaddress.IPv4Address(s))).count("1")
            except ValueError:
                continue
        elif name in ("ip", "network", "host", "broadcast") and (addr is None or name == "ip"):
            addr = (name, s, arg or 0)
    if length is None and v.length and v.length[0] == v.length[1]:
        length = v.length[0]
    if addr is None or length is None:
        return None
    name, s, n = addr
    try:
        if name == "ip":
            return f"{ipaddress.IPv4Address(s)}/{length}"
        net = ipaddress.IPv4Network(f"{s}/{length}", strict=False)
    except ValueError:
        return None
    return f"{net.network_address}/{length}"


def _solve_scope(
    t: Template, comp: Compiled, b: dict[str, str], block: str | None, outer: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """一个作用域（基础部分或一个块实例）的变量：返回 ({变量全名: 取值}, 发现)。"""
    caps: dict[Expr, list[str]] = defaultdict(list)
    for etext, val in b.items():
        e = comp.exprs.get(etext)
        if e is not None and t.vars[e.var].block == block:
            caps[e].append(val)
    values: dict[str, Any] = {}
    findings: list[dict[str, Any]] = []
    for v in t.vars.values():
        if v.block != block or v.derived:
            continue
        val, bad, problem = _solve_var(v, caps, comp)
        values[v.name] = val
        for etext, want, got in bad:
            findings.append({"kind": "inconsistent", "var": etext, "expected": want, "actual": got})
        if problem and val is not None:
            findings.append({"kind": "constraint", "var": v.name, "actual": val, "problem": problem})
    scope_vals = {**outer, **values}
    for v in t.vars.values():
        if v.block == block and v.derived and v.expr:
            try:
                values[v.name] = evaluate(resolve_expr(t, v.expr, v.block), scope_vals)
            except (TemplateError, ValueError):
                values[v.name] = None
    return values, findings


# ---------------------------------------------------------------- 入口


def _var_finding(
    f: dict[str, Any],
    block: str | None,
    inst: int | None,
    recs: tuple[_Rec, ...] = (),
    comp: Compiled | None = None,
) -> dict[str, Any]:
    """变量层面的发现（验算不符、违反约束、实例个数）：从捕获记录找出取值来自哪个节点、哪一行。"""
    node = actual_node = None
    lines: list[int] = []
    tlines: list[int] = []
    var = f.get("var")
    if var and comp is not None:
        for r in recs:
            hit = r.prov.get(var) or next(
                (v for e, v in r.prov.items() if e in comp.exprs and comp.exprs[e].var == var), None
            )
            if hit:
                p = comp.items[hit[0]]
                node, actual_node, lines, tlines = p.node, hit[1], hit[2], p.tlines
                break
    return {
        "kind": f["kind"],
        "severity": SEVERITY[f["kind"]],
        "block": block,
        "instance": inst,
        "node": node,
        "node_kind": "var",
        "schema": None,
        "domain": None,
        "actual_node": actual_node,
        "expected": f.get("expected"),
        "actual": f.get("actual"),
        "actual_origin": None,
        "var": var,
        "problem": f.get("problem"),
        "count": None,
        "parent": None,
        "lines": lines,
        "template_lines": tlines,
    }


def _short_values(t: Template, values: dict[str, Any], block: str) -> dict[str, Any]:
    return {t.vars[k].short: v for k, v in values.items()}


def check(
    t: Template,
    graph: nx.MultiDiGraph,
    kb: KnowledgeBase,
    label: str | None = None,
    extra: str | None = None,
    extra_scope: str | None = None,
) -> dict[str, Any]:
    """按模板校验一张配置图并提取变量。extra / extra_scope 覆盖模板中的设置。"""
    comp = compile_template(t, kb)
    extra = extra or t.extra
    extra_scope = extra_scope or t.extra_scope
    if extra not in ("allow", "deny"):
        raise TemplateError("template.bad_extra", value=extra)
    if extra_scope not in ("none", "matched", "domains"):
        raise TemplateError("template.bad_scope", value=extra_scope)
    canon = _Canonicalizer(graph, kb, _Schema(kb)).run()
    family = str(graph.graph.get("family") or "")
    profile = str(graph.graph.get("profile") or "")
    same_family = family == comp.family
    notes: list[dict[str, Any]] = []
    if not same_family:
        notes.append({"key": "template.note.family", "args": {"family": family, "template": comp.family}})
    applicable = t.profiles or [p for p, pr in kb.profiles.items() if pr.family == comp.family]
    if profile not in applicable:
        notes.append({"key": "template.note.profile", "args": {"profile": profile}})
    m = _Matcher(comp, canon, kb, same_family)
    items = comp.items
    findings: list[dict[str, Any]] = []
    covered: set[str] = set()

    # 基础部分
    base = _Rec()
    roots = [p.idx for p in items if p.parent is None]
    bind = m.run(roots, "", {}, base, (None, None))
    findings += base.findings
    covered |= set(base.matched.values()) | base.used
    matched_total = base.count
    base_values, _ = _solve_scope(t, comp, bind, None, {})

    # 块
    blocks_out: dict[str, Any] = {}
    instances_count: dict[str, int] = {}
    for blk in t.blocks.values():
        broots = [p for p in items if p.block == blk.name and (p.parent is None or items[p.parent].block != blk.name)]
        anchor = _anchor(blk, broots, comp)
        insts: list[tuple[dict[str, str], _Rec]] = []
        if anchor is None:
            blocks_out[blk.name] = [] if blk.kind == "repeat" else False
            instances_count[blk.name] = 0
            continue
        parent_of = {p.idx: ("" if p.parent is None else base.matched.get(p.parent)) for p in broots}
        aparent = parent_of[anchor.idx]
        cands: list[tuple[Item, dict[str, str]]] = []
        if aparent is not None:
            if anchor.kind == "object":
                cands = m.options(anchor, aparent, bind, base.used)
            else:
                probe = _Rec(used=set(base.used))
                m.run([anchor.idx], aparent, bind, probe, (blk.name, 0), dry=True)
                if anchor.idx in probe.matched:
                    cands = [(canon.items[probe.matched[anchor.idx]], bind)]
        if blk.kind == "optional" and len(cands) > 1:
            scored = [
                (m.score(anchor, a, b2, base, (blk.name, 0)) if anchor.kind == "object" else 0, a, b2)
                for a, b2 in cands
            ]
            best = max(s for s, _, _ in scored)
            cands = [next((a, b2) for s, a, b2 in scored if s == best)]
        if blk.kind == "repeat" and cands and anchor.kind == "object":
            # 锚点的键里有还没绑定的基础变量（例如只在块里出现的 {{port}}）：按它的取值分组，取能对上最多的一组
            # （只有一个实例时也要绑定，REQ-055-04）
            free = sorted(e for e in anchor.exprs if e not in bind and t.vars[comp.exprs[e].var].block is None)
            if free:
                groups: dict[tuple[str, ...], list[tuple[Item, dict[str, str]]]] = defaultdict(list)
                for a, b2 in cands:
                    groups[tuple(b2.get(e, "") for e in free)].append((a, b2))

                scope0: tuple[str | None, int | None] = (blk.name, 0)
                ranked = [
                    (sum(m.score(anchor, a, b2, base, scope0) for a, b2 in g), len(g), -i, g)
                    for i, g in enumerate(groups.values())
                ]
                chosen = max(ranked, key=lambda x: x[:3])[3]
                cands = chosen
                bind = merge(bind, [(e, chosen[0][1][e]) for e in free]) or bind
                base_values, _ = _solve_scope(t, comp, bind, None, {})
        anchors_used: set[str] = set()
        for a, b2 in cands:
            if a.cid in anchors_used:
                continue
            idx = len(insts)
            rec = _Rec(used=set(base.used) | anchors_used)
            if anchor.kind == "object":
                rec.matched[anchor.idx] = a.cid
                rec.used.add(a.cid)
                rec.count += 1
                bi = m.run(anchor.children, a.cid, b2, rec, (blk.name, idx))
            else:
                bi = b2
            rest = [p for p in broots if not (p.idx == anchor.idx and anchor.kind == "object")]
            while rest:
                p = min(rest, key=lambda q: (len(q.exprs - set(bi)), rest.index(q)))
                rest.remove(p)
                par = parent_of[p.idx]
                if par is None:
                    m.finding(rec, "missing", p, (blk.name, idx), count=m.size(p.idx))
                    continue
                bi = m.run([p.idx], par, bi, rec, (blk.name, idx))
            anchors_used.add(a.cid)
            insts.append((bi, rec))
        values_list = []
        for idx, (bi, rec) in enumerate(insts):
            findings += rec.findings
            covered |= set(rec.matched.values()) | rec.used
            matched_total += rec.count
            vals, vf = _solve_scope(t, comp, bi, blk.name, base_values)
            findings += [_var_finding(f, blk.name, idx, (rec, base), comp) for f in vf]
            anchor_node = rec.matched.get(anchor.idx)
            values_list.append(
                {
                    **_short_values(t, vals, blk.name),
                    "_node": anchor_node,
                    "_lines": canon.subtree_lines.get(anchor_node or "", []),
                }
            )
        # 块变量 unique
        for v in t.input_vars(blk.name):
            if not v.unique:
                continue
            seen: dict[str, int] = {}
            for idx, vals in enumerate(values_list):
                val = vals.get(v.short)
                if val is None:
                    continue
                k = str(val).lower()
                if k in seen:
                    findings.append(
                        _var_finding(
                            {
                                "kind": "constraint",
                                "var": v.name,
                                "actual": val,
                                "problem": "template.value.not_unique",
                            },
                            blk.name,
                            idx,
                            (insts[idx][1],),
                            comp,
                        )
                    )
                seen[k] = idx
        n = len(values_list)
        instances_count[blk.name] = n
        if blk.kind == "repeat":
            if n < blk.min or (blk.max is not None and n > blk.max):
                findings.append(
                    {
                        **_var_finding({"kind": "count"}, blk.name, None),
                        "node": anchor.node,
                        "node_kind": "block",
                        "count": n,
                        "expected": f"{blk.min}..{'' if blk.max is None else blk.max}",
                        "template_lines": anchor.tlines,
                    }
                )
            blocks_out[blk.name] = values_list
        else:
            if values_list:
                vals = {k: v for k, v in values_list[0].items() if not k.startswith("_")}
                blocks_out[blk.name] = vals or True
            else:
                blocks_out[blk.name] = False

    # 并列候选最后都被别的模式对上了（rr1 / rr2 这类对称的写法）：不是真正的歧义
    findings = [f for f in findings if f["kind"] != "ambiguous" or not set(f["actual"] or []) <= covered]

    base_values, vf = _solve_scope(t, comp, bind, None, {})
    findings += [_var_finding(f, None, None, (base,), comp) for f in vf]

    # 模板外的配置
    extras = _extras(comp, canon, kb, profile, covered, extra_scope, same_family) if extra_scope != "none" else []
    sev = "error" if extra == "deny" else "info"
    for e in extras:
        e["severity"] = sev
    findings += extras

    base_out = {t.vars[k].name: v for k, v in base_values.items()}
    unresolved = [k for k, v in base_out.items() if v is None and not t.vars[k].derived]
    by_kind: dict[str, int] = defaultdict(int)
    by_sev = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        by_kind[f["kind"]] += 1
        by_sev[f["severity"]] += 1
    row: dict[str, Any] = {"device": label or str(graph.graph.get("device") or "")}
    row.update({k: v for k, v in base_out.items() if not t.vars[k].derived})
    for blk in t.blocks.values():
        val = blocks_out.get(blk.name)
        if blk.kind == "repeat":
            row[blk.name] = [
                {k: v for k, v in inst.items() if not k.startswith("_") and not t.vars[f"{blk.name}.{k}"].derived}
                for inst in val or []
            ]
        else:
            row[blk.name] = (
                {k: v for k, v in val.items() if not t.vars[f"{blk.name}.{k}"].derived}
                if isinstance(val, dict)
                else bool(val)
            )
    return {
        "template": {k: v for k, v in t.info(kb).items() if k in ("id", "version", "title", "profile", "digest")},
        "device": label or graph.graph.get("device"),
        "profile": profile,
        "family": family,
        "compliant": by_sev["error"] == 0,
        "options": {"extra": extra, "extra_scope": extra_scope},
        "variables": base_out,
        "blocks": blocks_out,
        "row": row,
        "unresolved": unresolved,
        "findings": findings,
        "notes": notes,
        "warnings": comp.warnings,
        "summary": {
            "patterns": len(items),
            "matched": matched_total,
            "by_kind": dict(by_kind),
            "by_severity": by_sev,
            "instances": instances_count,
            "extra": len(extras),
        },
    }


def _anchor(blk: Any, roots: list[PItem], comp: Compiled) -> PItem | None:
    """重复块的锚点：键里含本块变量的对象，优先 anchor 指定的 Schema、键里固定内容与基础变量多的。"""
    if not roots:
        return None
    if blk.anchor:
        hit = next((p for p in roots if p.schema == blk.anchor and p.kind == "object"), None)
        if hit:
            return hit

    def own(p: PItem) -> int:
        if p.kind != "object":
            return 0
        es = p.exprs
        return sum(1 for e in es if comp.exprs[e].var.startswith(blk.name + "."))

    keyed = [p for p in roots if own(p) > 0]
    if not keyed:
        objs = [p for p in roots if p.kind == "object"]
        return objs[0] if objs else roots[0]

    def spec(p: PItem) -> tuple[int, int, int]:
        es = p.exprs
        uniq = sum(1 for e in es if comp.template.vars[comp.exprs[e].var].unique)
        base_n = sum(1 for e in es if comp.template.vars[comp.exprs[e].var].block is None)
        literal = len(re.sub(r"\{[^}]*\}", "", p.node))
        return (uniq, base_n, literal)

    return max(keyed, key=lambda p: (spec(p), -p.idx))


def _extras(
    comp: Compiled,
    canon: _Canon,
    kb: KnowledgeBase,
    profile: str,
    covered: set[str],
    scope: str,
    same_family: bool,
) -> list[dict[str, Any]]:
    """模板外的配置：没有被任何模式对上的显式节点。matched 只看模板对上的对象下面；domains 另外包括模板涉及的
    功能域中的顶层对象。只在最上层报一次（对象附子节点数）；显式写出、等于 Profile 默认值的属性不算。"""
    defaults: dict[str, Any] = {}
    if profile in kb.profiles:
        for nid, e in kb.resolve_profile(profile).entries.items():
            if e.supported and e.default is not None:
                defaults[nid] = e.default
    out: list[dict[str, Any]] = []
    reported: set[str] = set()
    items = canon.items

    def entry(kind: str, schema: str, domain: str, node: str, actual: Any, lines: list[int], count: Any) -> None:
        out.append(
            {
                "kind": "extra",
                "severity": "info",
                "block": None,
                "instance": None,
                "node": None,
                "node_kind": kind,
                "schema": schema,
                "domain": domain,
                "actual_node": node,
                "expected": None,
                "actual": actual,
                "actual_origin": "explicit",
                "var": None,
                "count": count,
                "parent": None,
                "lines": lines,
                "template_lines": [],
            }
        )

    for cid, it in items.items():
        if it.origin != "explicit" or cid in covered or (it.parent and it.parent in reported):
            continue
        if it.parent:
            if it.parent not in covered:
                continue
        elif not (scope == "domains" and it.domain in comp.domains):
            continue
        if it.kind == "attr":
            sn = kb.nodes.get(it.schema)
            if (
                sn is not None
                and it.schema in defaults
                and norm_value(sn.type, defaults[it.schema], sn.ordered) == it.value
            ):
                continue
            entry("attr", it.schema, it.domain, cid, it.value, it.lines, None)
            continue
        reported.add(cid)
        n = sum(1 for k in items if k.startswith(cid + "/"))
        entry("object", it.schema, it.domain, cid, it.key, canon.subtree_lines.get(cid, it.lines), n)
    if same_family:
        for mm in canon.ext:
            if mm.node in covered or not mm.owner or mm.owner not in covered:
                continue
            entry("ext", mm.group, mm.domain, f"{mm.owner}/ext[{mm.group}]", mm.value, mm.lines, None)
    return out


def check_text(
    t: Template,
    text: str,
    kb: KnowledgeBase,
    profile: str | None = None,
    label: str = "config",
    extra: str | None = None,
    extra_scope: str | None = None,
) -> dict[str, Any]:
    try:
        res = analysis.parse_text(text, kb, profile)
    except analysis.AnalysisError as e:
        raise TemplateError(str(e), profile=profile or "") from e
    g = graphmod.build(res.parsed, kb, res.profile, label)
    return check(t, g, kb, label, extra, extra_scope)


def extract_view(result: dict[str, Any]) -> dict[str, Any]:
    """提取变量的结果：变量表、块实例、可直接作为生成参数的一行，以及校验的概要。"""
    return {
        "template": result["template"],
        "device": result["device"],
        "profile": result["profile"],
        "compliant": result["compliant"],
        "variables": result["variables"],
        "blocks": result["blocks"],
        "row": result["row"],
        "unresolved": result["unresolved"],
        "summary": result["summary"],
        "findings": [f for f in result["findings"] if f["severity"] == "error"],
    }
