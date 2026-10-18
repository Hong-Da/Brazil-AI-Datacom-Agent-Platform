"""规范模式渲染（M3-3）：配置图 → 指定 Profile（平台族）的规范配置文本。

与往返渲染（renderer.render_roundtrip，按原文重放）不同，规范渲染只看图中的语义节点，按目标平台族的写法重新生成命令。
翻译（translate.py）、含默认值的完整配置、模板批量生成都用它。

生成方向的知识不单独手写，而是由“命令卡 + 映射规则”反推（生成—校验）：
    1. 对每个要写出的节点（事实），找目标平台族在当前视图中映射到该 Schema 节点的命令卡；
    2. 把卡上每个映射表达式反过来求解（$参数 → 参数取值，fmt: → 按模板拆开，kw: → 需要出现的关键字，
       flag → 正 / 取消形式，if: / tail: …），得到参数取值与关键字约束，再按命令卡语法生成候选命令行；
    3. 每个候选行交给解析器在同一视图中匹配、按映射规则求值，结果与图中的节点（键、有效值、所在对象）完全一致才采用。
    因此生成的每一行都能被解析回同样的节点；新功能域只要有命令卡和映射，不用另写生成规则。
    反推不了（没有命令卡、映射写法无法求解、校验不通过）的节点留在 uncovered，由调用方报告为不支持。

结构：
    - 对象有“入口命令”（进入视图的命令卡，例如 interface X、bgp 100）时写成块，块内是它的属性与子对象；
      没有入口命令的对象（Cisco 的 BGP 邻居、华为接口下的 OSPF 参数）由各属性行顺带给出键；
      需要先声明的对象（Cisco neighbor X peer-group、华为 group X internal）先写声明行（只给键、不带参数取值的卡）。
    - 同一层的对象按依赖排序：被引用的先出现（VRF 在接口前，前缀列表在路由策略前，路由策略在 BGP 前），其余按原始行号。
    - 属性行进入子视图时（华为 pwsignal ldp），同一对象只能在子视图里写的属性接着写在它下面；本层写不出的子对象
      试着写进兄弟对象的块里（Cisco 的 backup peer 写在 xconnect 块中）。
    - 华为用 # 分隔顶层块、return 结尾；Cisco 用 ! 与 end；块内第一层的子块之间加 “ #” / “ !”。
    - 同平台族渲染时，未映射的命令（ext）与功能域外的原文行（raw / unknown）按原文写回原来的位置，反推不出命令的节点
      （带密文的命令）按原文写回；跨平台族时都不写（由翻译列出）。
    - include_defaults：默认值节点（origin=default）也写成命令（类似 display current-configuration all），
      这些行集中放在所在块的显式行之后，前面加一行注释 “! default”（注释行重新解析时是 comment，不影响图）。

平台族的书写习惯（可选）在 knowledge/render/<平台族>.yaml：exits（离开视图时写的命令）、nested_separator、
prefer（某个 Schema 节点优先使用的命令卡）、avoid（不用于生成的命令卡）、no_declare（不写声明行的对象类型）、
infer（写声明行必须给出、源配置又没有的取值的推导规则）、interface_types（翻译时检查接口类型）。
"""

from __future__ import annotations

import copy
import ipaddress
import itertools
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from lmesh.core import parser as parsemod
from lmesh.core.compare import _Schema, norm_scalar, norm_value
from lmesh.core.graph import DEVICE, Builder, _short
from lmesh.core.kb import KnowledgeBase, mapping, read_yaml
from lmesh.core.kb import syntax as syn
from lmesh.core.kb.model import Card, Note, SchemaNode

DEFAULT_MARK = "! default"
_AUTO = object()  # auto 表达式：按出现顺序编号，生成时不约束
_GEN_LIMIT = 12  # 每张卡最多尝试的候选行
_IPV4 = re.compile(r"^\d+\.\d+\.\d+\.\d+$")


class CanonError(ValueError):
    """规范渲染的参数错误（文案键 + 参数）。"""

    def __init__(self, key: str, **fmt: Any):
        super().__init__(key)
        self.key, self.fmt = key, fmt


# ---------------------------------------------------------------- 平台族的书写习惯


_STYLE_CACHE: dict[tuple[str, int], dict[str, Any]] = {}


def load_style(kb: KnowledgeBase, family: str) -> dict[str, Any]:
    """平台族的书写习惯：运行时知识库没有 render/ 时（M3-3 之前创建的）用程序自带的。
    按文件与修改时间缓存（增量变更、重排每个视图块都要取退出命令）；返回副本，调用方可以修改。"""
    f = Path(kb.root) / "render" / f"{family}.yaml"
    if not f.exists():
        from lmesh import paths

        f = paths.builtin_knowledge_dir() / "render" / f"{family}.yaml"
    key = (str(f), f.stat().st_mtime_ns if f.exists() else -1)
    hit = _STYLE_CACHE.get(key)
    if hit is None:
        hit = _STYLE_CACHE[key] = _read_style(f)
    return copy.deepcopy(hit)


def _read_style(f: Path) -> dict[str, Any]:
    data = (read_yaml(f) or {}) if f.exists() else {}
    return {
        "exits": {str(k): str(v) for k, v in (data.get("exits") or {}).items()},
        "nested_separator": bool(data.get("nested_separator", True)),
        "prefer": {str(k): [str(x) for x in (v or [])] for k, v in (data.get("prefer") or {}).items()},
        "avoid": {str(x) for x in (data.get("avoid") or [])},
        "no_declare": {str(x) for x in (data.get("no_declare") or [])},
        "infer": [dict(x) for x in (data.get("infer") or []) if isinstance(x, dict) and x.get("node")],
        "interface_types": [str(x) for x in (data.get("interface_types") or [])],
        "access_form": str(data.get("access_form") or ""),
    }


# ---------------------------------------------------------------- 命令卡索引（按视图 + Schema 节点）


@dataclass
class _CardT:
    card: Card
    targets: list[tuple[str, list[mapping.Target], Any]]
    enters: bool
    declare: set[str] = field(default_factory=set)  # 这张卡可以作为哪些对象的声明行


class _Index:
    def __init__(self, kb: KnowledgeBase, family: str, style: dict[str, Any]):
        self.parser = parsemod.CardIndex(kb, family)
        self.by_vs: dict[tuple[str, str], list[_CardT]] = defaultdict(list)
        self.targets: dict[str, list[tuple[str, list[mapping.Target], Any]]] = {}
        self.undo: dict[str, syn.Syntax | None] = {}
        for c in kb.cards_of(family):
            if not c.maps:
                continue
            try:
                c.parsed  # noqa: B018 — 语法写错的卡跳过
            except syn.SyntaxErrorKB:
                continue
            targets = [(t, mapping.parse_target(t), e) for t, e in c.maps.items()]
            self.targets[c.id] = targets
            if c.id in style["avoid"]:
                continue
            ct = _CardT(c, targets, bool(c.enters_view))
            objs = [
                (alts[0].node, e)
                for _, alts, e in targets
                if len(alts) == 1 and kb.nodes.get(alts[0].node) and kb.nodes[alts[0].node].type == "object"
            ]
            has_alt = any(len(alts) > 1 for _, alts, _ in targets)
            others_plain = all(
                not mapping.params_in_expr(e)
                for _, alts, e in targets
                if not (kb.nodes.get(alts[0].node) and kb.nodes[alts[0].node].type == "object")
            )
            if len(objs) == 1 and not has_alt and others_plain and mapping.params_in_expr(objs[0][1]):
                ct.declare.add(objs[0][0])
            for s in {a.node for _, alts, _ in targets for a in alts}:
                self.by_vs[(c.view, s)].append(ct)


_INDEX: dict[tuple[int, str], tuple[KnowledgeBase, _Index, dict[str, Any]]] = {}


def _index(kb: KnowledgeBase, family: str) -> tuple[_Index, dict[str, Any]]:
    hit = _INDEX.get((id(kb), family))
    if hit is not None and hit[0] is kb:
        return hit[1], hit[2]
    style = load_style(kb, family)
    idx = _Index(kb, family, style)
    if len(_INDEX) > 8:
        _INDEX.clear()
    _INDEX[(id(kb), family)] = (kb, idx, style)
    return idx, style


# ---------------------------------------------------------------- 表达式反解


@dataclass(frozen=True)
class _Sol:
    values: tuple[tuple[str, Any], ...] = ()
    kws: frozenset[str] = frozenset()
    forbid: frozenset[str] = frozenset()
    neg: bool | None = None
    tail: tuple[str, str] | None = None


def _merge(a: _Sol, b: _Sol) -> _Sol | None:
    va = dict(a.values)
    for k, v in b.values:
        if k in va and va[k] != v:
            return None
        va[k] = v
    kws, forbid = a.kws | b.kws, a.forbid | b.forbid
    if kws & forbid:
        return None
    if a.neg is not None and b.neg is not None and a.neg != b.neg:
        return None
    if a.tail and b.tail and a.tail != b.tail:
        return None
    return _Sol(
        tuple(sorted(va.items(), key=lambda x: x[0])),
        kws,
        forbid,
        a.neg if a.neg is not None else b.neg,
        a.tail or b.tail,
    )


def _len_to_mask(n: int) -> str:
    return str(ipaddress.IPv4Address((0xFFFFFFFF << (32 - n)) & 0xFFFFFFFF if n else 0))


def _mask_to_len(s: str) -> str | None:
    if not _IPV4.match(s):
        return None
    try:
        n = int(ipaddress.IPv4Address(s))
    except ValueError:
        return None
    inv = (~n) & 0xFFFFFFFF
    return str(bin(n).count("1")) if (inv & (inv + 1)) == 0 else None


def _coerce(spec: dict[str, Any] | None, value: Any) -> str | None:
    """取值按参数类型换成命令里的写法（掩码长度 ↔ 点分掩码），类型不符时返回 None。"""
    spec = spec or {}
    t = spec.get("type", "word")
    s = "true" if value is True else "false" if value is False else str(value)
    if t == "mask" and s.isdigit() and 0 <= int(s) <= 32:
        s = _len_to_mask(int(s))
    elif t == "wildcard" and s.isdigit() and 0 <= int(s) <= 32:
        s = str(ipaddress.IPv4Address(~int(ipaddress.IPv4Address(_len_to_mask(int(s)))) & 0xFFFFFFFF))
    elif t in ("mask-length", "integer") and _IPV4.match(s):
        s = _mask_to_len(s) or s
    if t != "text" and (not s or " " in s):
        return None
    return s if syn.type_ok(s, spec) else None


def _text(v: Any) -> str:
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, list):
        return " ".join(_text(x) for x in v)
    return "" if v is None else str(v)


def _same(a: Any, b: Any, node_type: str = "string") -> bool:
    if a is None or b is None:
        return (a in (None, "")) and (b in (None, ""))
    if isinstance(a, bool) or isinstance(b, bool):
        return norm_scalar("boolean", a) == norm_scalar("boolean", b)
    return bool(norm_value(node_type, a) == norm_value(node_type, b) or _text(a).lower() == _text(b).lower())


class _Inverter:
    def __init__(self, card: Card, ctx: dict[str, Any] | None = None):
        self.card = card
        self.ctx = ctx  # ctx: 表达式的上下文（所在接口的键）

    def param(self, name: str, value: Any) -> _Sol | None:
        spec = self.card.params.get(name)
        if isinstance(value, str) and " " in value.strip() and (spec or {}).get("type") != "text":
            value = value.split()  # 重复组里的多个取值（apply community 1:1 2:2）
        if isinstance(value, list):
            vals = [_coerce(spec, x) for x in value]
            if any(v is None for v in vals):
                return None
            return _Sol(values=((name, tuple(vals)),))
        v = _coerce(spec, value)
        return None if v is None else _Sol(values=((name, v),))

    def run(self, expr: Any, want: Any, node_type: str) -> list[_Sol]:
        if isinstance(expr, dict):
            if want is None:
                return [_Sol()]
            if not isinstance(want, dict):
                return []
            sols = [_Sol()]
            for k, sub in expr.items():
                w = want.get(k)
                part = self.run(sub, None if w in (None, "") else w, "string")
                if w in (None, "") and isinstance(sub, str) and not sub.endswith("||") and "$" in sub:
                    # 键字段为空：表达式必须取不到值（参数不出现）
                    part = [_Sol()]
                sols = [m for a in sols for b in part if (m := _merge(a, b)) is not None][:64]
            return sols
        e = str(expr)
        if want is None:
            if e.startswith("if:"):
                return [_Sol(forbid=frozenset({e.split(":", 2)[1].lower()}))]
            if e.startswith("tail:"):
                return [_Sol(forbid=frozenset({e[5:].lower()}))]
            return [_Sol()]
        if "||" in e:
            out: list[_Sol] = []
            alts = [x.strip() for x in e.split("||")]
            for alt in alts:
                if alt == "":
                    continue
                out += self.run(alt, want, node_type)
            return out
        if e == "flag":
            return [_Sol(neg=not norm_scalar("boolean", want))]
        if e == "auto":
            return [_Sol()]
        if e.startswith("ctx:"):  # 由所在上下文决定，不能靠写法表达：取值必须与上下文一致
            return [_Sol()] if _same(mapping.context_value(e, self.ctx), want, node_type) else []
        if e.startswith("if:"):
            _, kw, rest = e.split(":", 2)
            if kw.startswith("$"):  # if:$参数:表达式——参数有值即可（通常由同一行的对象键给出）
                return self.run(rest, want, node_type)
            return [m for s in self.run(rest, want, node_type) if (m := _merge(_Sol(kws=frozenset({kw.lower()})), s))]
        if e.startswith("unless:"):  # 行里没有该关键字时才取值：写出取值时不能出现该关键字
            _, kw, rest = e.split(":", 2)
            return [
                m for s in self.run(rest, want, node_type) if (m := _merge(_Sol(forbid=frozenset({kw.lower()})), s))
            ]
        if e.startswith("tail:"):
            kw = e[5:].lower()
            return [_Sol(kws=frozenset({kw}), tail=(kw, _text(want)))]
        if e.startswith("kw:"):
            spec, _, default = e[3:].partition(":")
            items = [(i.partition("=")[0].lower(), i.partition("=")[2] or i.partition("=")[0]) for i in spec.split("|")]
            out = [_Sol(kws=frozenset({kw})) for kw, val in items if _same(val, want, node_type)]
            if default and _same(default, want, node_type):
                out.append(_Sol(forbid=frozenset(kw for kw, _ in items)))
            return out
        if e.startswith("fmt:"):
            return self.fmt(e[4:], want)
        if e.startswith("$"):
            s = self.param(e[1:], want)
            return [s] if s else []
        return [_Sol()] if _same(e, want, node_type) else []

    def fmt(self, tpl: str, want: Any) -> list[_Sol]:
        text = _text(want)
        holes = list(re.finditer(r"\{([\w\-|]+)\}", tpl))
        out: list[_Sol] = []
        # 取值可能只给了前几个占位（例如认证方法列表）：依次去掉末尾的占位再试
        for k in range(len(holes), 0, -1):
            part = tpl[: holes[k - 1].end()]
            pattern, names = "", []
            pos = 0
            for m in holes[:k]:
                pattern += re.escape(part[pos : m.start()]) + r"(.+?)"
                names.append(m.group(1).split("|"))
                pos = m.end()
            m2 = re.fullmatch(pattern + re.escape(part[pos:]), text)
            if not m2:
                continue
            choices: list[list[_Sol]] = []
            for opts, val in zip(names, m2.groups(), strict=True):
                cand = [s for o in opts if (s := self.param(o, val)) is not None]
                if not cand:
                    break
                choices.append(cand)
            else:
                for combo in itertools.islice(itertools.product(*choices), 16):
                    acc: _Sol | None = _Sol()
                    for s in combo:
                        acc = _merge(acc, s) if acc else None
                    if acc:
                        out.append(acc)
            if out:
                break
        return out


# ---------------------------------------------------------------- 按语法生成候选命令行


_STRUCT: dict[int, tuple[Any, frozenset[str], tuple[str, ...]]] = {}


def _struct(obj: Any) -> tuple[frozenset[str], tuple[str, ...]]:
    """一段语法（节点列表或单个节点）里出现的全部关键字与参数名；按对象缓存（语法对象随知识库常驻）。"""
    hit = _STRUCT.get(id(obj))
    if hit is not None and hit[0] is obj:
        return hit[1], hit[2]
    nodes = obj if isinstance(obj, list) else [obj]
    words: set[str] = set()

    def walk(ns: list[Any]) -> None:
        for n in ns:
            if isinstance(n, syn.Kw):
                words.add(n.word.lower())
            elif isinstance(n, syn.Opt):
                walk(n.body)
            elif isinstance(n, syn.Choice):
                for a in n.alts:
                    walk(a)
            elif isinstance(n, syn.Rep):
                walk([n.node])

    walk(nodes)
    params = tuple(syn.Syntax("", nodes).params()) if nodes else ()
    if len(_STRUCT) > 200000:
        _STRUCT.clear()
    _STRUCT[id(obj)] = (obj, frozenset(words), params)
    return frozenset(words), params


@dataclass
class _Seq:
    """生成时把一段语法当作必须出现的一个整体。"""

    body: list[syn.Node]


class _Gen:
    def __init__(self, sol: _Sol, params: dict[str, dict[str, Any]] | None = None):
        self.params = params or {}
        self.vals = dict(sol.values)
        self.kws = sol.kws
        self.forbid = sol.forbid
        self.tail = sol.tail

    def seq(self, nodes: list[Any], vals: dict[str, Any]) -> list[tuple[list[str], bool]]:
        results: list[tuple[list[str], bool]] = [([], False)]
        for n in nodes:
            nxt: list[tuple[list[str], bool]] = []
            for toks, stopped in results:
                if stopped:
                    nxt.append((toks, True))
                    continue
                for more, st in self.one(n, vals):
                    nxt.append((toks + more, st))
                    if len(nxt) >= _GEN_LIMIT * 4:
                        break
            if not nxt:
                return []
            results = nxt
        return results

    def _choice_kw(self, name: str) -> str | None:
        """取值是固定选项的参数（enum）：要求出现的关键字正好是它的一个选项时，用这个选项。"""
        for c in (self.params.get(name) or {}).get("choices") or []:
            if str(c).lower() in self.kws or (self.tail and str(c).lower() == self.tail[0]):
                return str(c)
        return None

    def _words(self, nodes: Any) -> set[str]:
        words, params = _struct(nodes)
        extra = {c.lower() for p in params if (c := self._choice_kw(p))}
        return set(words) | extra if extra else set(words)

    @staticmethod
    def _must(nodes: list[syn.Node]) -> set[str]:
        """一定会出现的关键字（不含可选部分与多选一里的）。"""
        return {n.word.lower() for n in nodes if isinstance(n, syn.Kw)}

    def _wanted(self, nodes: Any, vals: dict[str, Any]) -> bool:
        words = self._words(nodes)
        params = _struct(nodes)[1]
        return (
            bool(words & self.kws)
            or (self.tail is not None and self.tail[0] in words)
            or any(p in vals for p in params)
        )

    def one(self, n: Any, vals: dict[str, Any]) -> list[tuple[list[str], bool]]:
        if isinstance(n, syn.Kw):
            if self.tail and n.word.lower() == self.tail[0]:
                return [([n.word, *self.tail[1].split()], True)]
            return [([n.word], False)]
        if isinstance(n, syn.Param):
            v = vals.get(n.name)
            if v is None:
                c = self._choice_kw(n.name)
                return [([c], False)] if c else []
            if isinstance(v, tuple):
                return [([str(v[0])], False)] if len(v) == 1 else []
            return [([str(v)], False)]
        if isinstance(n, syn.Opt):
            if self._must(n.body) & self.forbid or not self._wanted(n.body, vals):
                return [([], False)]
            return [*self.seq(n.body, vals), ([], False)]
        if isinstance(n, syn.Choice):
            scored = []
            for i, alt in enumerate(n.alts):
                if self._must(alt) & self.forbid:
                    continue
                params = _struct(alt)[1]
                words = self._words(alt)
                if words & self.kws or (self.tail and self.tail[0] in words):
                    rank = 0
                elif params and any(p in vals for p in params):
                    rank = 1
                elif not params:
                    rank = 2
                else:
                    rank = 3
                scored.append((rank, i, alt))
            out: list[tuple[list[str], bool]] = []
            for _, _, alt in sorted(scored, key=lambda x: (x[0], x[1])):
                out += self.seq(alt, vals)
            return out
        if isinstance(n, syn.Rep):
            params = _struct(n.node)[1]
            lists = {p: vals[p] for p in params if isinstance(vals.get(p), tuple)}
            count = max((len(v) for v in lists.values()), default=1)
            if count > 1:
                acc: list[tuple[list[str], bool]] = [([], False)]
                for i in range(count):
                    sub = {**vals, **{p: v[i] for p, v in lists.items() if i < len(v)}}
                    acc = [(a + b, s) for a, _ in acc for b, s in self.one(n.node, sub)][:_GEN_LIMIT]
                return acc
            inner = n.node.body if isinstance(n.node, syn.Opt) and len(n.node.body) == 1 else [n.node]
            if isinstance(inner[0], syn.Choice):
                # 重复的多选一（[ a | b | c ] &<1-N>）：每个需要的选项各写一次
                alts = [a for a in inner[0].alts if not (self._must(a) & self.forbid) and self._wanted(a, vals)]
                if not alts:
                    return [([], False)] if isinstance(n.node, syn.Opt) else self.one(n.node, vals)
                return self.seq([_Seq(a) for a in alts], vals)
            return self.one(n.node, vals)
        if isinstance(n, _Seq):
            return self.seq(n.body, vals)
        return []

    def lines(self, syntax: syn.Syntax) -> list[str]:
        out = []
        seen = set()
        for toks, _ in self.seq(syntax.nodes, self.vals):
            low = {t.lower() for t in toks}
            if not self.kws <= low or low & self.forbid:
                continue
            text = " ".join(toks)
            if text not in seen:
                seen.add(text)
                out.append(text)
            if len(out) >= _GEN_LIMIT:
                break
        return out


# ---------------------------------------------------------------- 渲染结果


@dataclass
class RLine:
    depth: int
    text: str
    kind: str = "command"  # command / original（反推不出、按原文写回的命令）/ extra（原文写回的 ext、raw）/ separator / comment / exit / end
    origin: str = "explicit"  # explicit / default
    nodes: list[str] = field(default_factory=list)
    card: str | None = None
    opens: bool = False  # 这一行进入了一个视图
    objects: list[str] = field(default_factory=list)  # 这一行所在 / 创建的对象（增量变更按它定位视图）
    matched: list[str] = field(default_factory=list)  # 这一行写出的全部节点（含不需要写、顺带写出的）

    def as_dict(self, no: int, indent: int) -> dict[str, Any]:
        return {
            "no": no,
            "text": " " * (indent * self.depth) + self.text,
            "kind": self.kind,
            "origin": self.origin,
            "nodes": self.nodes,
            "card": self.card,
        }


@dataclass
class Rendered:
    profile: str
    family: str
    lines: list[RLine]
    indent: int
    uncovered: list[str]  # 要写出、但没能生成命令的节点
    covered: set[str]
    skipped_extras: list[str]
    inferred: list[dict[str, Any]] = field(
        default_factory=list
    )  # 按推导规则补出、并写进了命令的取值 {node, schema, value}

    @property
    def text(self) -> str:
        return "\n".join(" " * (self.indent * ln.depth) + ln.text for ln in self.lines)

    def line_dicts(self) -> list[dict[str, Any]]:
        return [ln.as_dict(i, self.indent) for i, ln in enumerate(self.lines, start=1)]


@dataclass
class _Ctx:
    view: str
    scope: dict[str, str]
    depth: int


@dataclass
class _Stmt:
    text: str
    card: Card
    negated: bool
    covers: set[str]
    objects: dict[str, str]
    matched: set[str] = field(default_factory=set)
    full: bool = True  # 卡上能顺带写出的取值都写了（同样能写出 anchor 时优先用，命令更完整）


# ---------------------------------------------------------------- 渲染器


def valued(d: dict[str, Any]) -> bool:
    """属性节点是否有有效的取值（undo 掉的非布尔属性不算）。"""
    return d.get("kind") == "attr" and not (d.get("negated") and not isinstance(d.get("value"), bool))


class _Renderer:
    def __init__(
        self,
        g: nx.MultiDiGraph,
        kb: KnowledgeBase,
        profile_id: str,
        facts: set[str],
        extras: bool,
    ):
        self.g, self.kb = g, kb
        self.profile = kb.profiles[profile_id]
        self.fam = kb.families[self.profile.family]
        self.idx, self.style = _index(kb, self.profile.family)
        self.sch = _Schema(kb)
        self.facts = set(facts)
        self.pending = set(facts)
        self.covered: set[str] = set()
        self.defaults: dict[str, Any] = {
            nid: e.default
            for nid, e in kb.resolve_profile(profile_id).entries.items()
            if e.supported and e.default is not None
        }
        self.children: dict[str, list[str]] = defaultdict(list)
        self.parent: dict[str, str] = {}
        for a, b, d in g.edges(data=True):
            if d.get("kind") == "contains":
                self.children[a].append(b)
                self.parent[b] = a
        self.order = {n: i for i, n in enumerate(g.nodes)}
        self.node_rank = {n: i for i, n in enumerate(kb.nodes)}
        self.extras_on = extras
        self.stmts = {st.line.no: st for st in g.graph.get("statements", [])}
        self.extra_place: dict[str, tuple[str, Any]] = {}
        self.attached: dict[str, list[str]] = defaultdict(list)  # 语义节点 → 挂在生成它的那一行下面的原文
        self.nested: dict[str, list[str]] = defaultdict(list)  # 原文节点 → 它下面的原文子行
        self.emitted_extras: set[str] = set()
        self.default_facts = {n for n in facts if g.nodes[n].get("origin") == "default"}
        self.inferred = {n for n, d in g.nodes(data=True) if d.get("origin") == "inferred"}
        self.inferred_used: set[str] = set()
        self.parse_cache: dict[tuple[str, str, bool], tuple[Card, syn.Match] | None] = {}
        self.last_block: _Ctx | None = None
        if extras:
            self._place_extras()

    # ----- 图的工具 -----

    def first_line(self, nid: str) -> float:
        lines = self.g.nodes[nid].get("lines") or []
        return min(lines) if lines else float("inf")

    def chain(self, nid: str) -> dict[str, str]:
        out: dict[str, str] = {}
        cur: str | None = nid
        while cur and cur != DEVICE:
            d = self.g.nodes[cur]
            if d.get("kind") == "object" and d.get("schema"):
                out.setdefault(d["schema"], cur)
            cur = self.parent.get(cur)
        return out

    def owner_schema(self, sn: SchemaNode) -> SchemaNode | None:
        cur = self.kb.nodes.get(sn.parent) if sn.parent else None
        while cur is not None and cur.type != "object":
            cur = self.kb.nodes.get(cur.parent) if cur.parent else None
        return cur

    def key_eq(self, sn: SchemaNode, have: Any, got: Any) -> bool:
        if got is _AUTO:
            return True
        if isinstance(have, dict) or isinstance(got, dict):
            if not (isinstance(have, dict) and isinstance(got, dict)):
                return False
            for f in set(have) | set(got):
                t, _ = self.sch.field_type(sn, f)
                a, b = have.get(f), got.get(f)
                if a in (None, "") and b in (None, ""):
                    continue
                if a in (None, "") or b in (None, ""):
                    return False
                if norm_scalar(t, a) != norm_scalar(t, b):
                    return False
            return True
        if isinstance(got, list):
            if len(got) != 1:
                return False
            got = got[0]
        f = sn.key[0] if sn.key else "name"
        t, _ = self.sch.field_type(sn, f)
        if have in (None, "") or got in (None, ""):
            return have in (None, "") and got in (None, "")
        return bool(norm_scalar(t, have) == norm_scalar(t, got))

    def placeholder(self, nid: str) -> bool:
        k = self.g.nodes[nid].get("key")
        if isinstance(k, dict):
            return all(v in (None, "") for v in k.values())
        return k in ("_", "", None)

    # ----- 原文节点的位置（同平台族） -----

    def _place_extras(self) -> None:
        for nid, d in self.g.nodes(data=True):
            if d.get("kind") == "object" and negated_object(self.g, nid):
                self.extra_place[nid] = ("ctx", self.parent.get(nid, DEVICE))
                continue
            if d.get("kind") not in ("ext", "raw", "unknown"):
                continue
            owner = self.parent.get(nid, DEVICE)
            lines = d.get("lines") or []
            st = self.stmts.get(min(lines)) if lines else None
            pl = st.line.parent if st else None
            if self.g.nodes.get(owner, {}).get("kind") in ("raw", "unknown", "ext"):
                self.nested[owner].append(nid)
                continue
            if pl is None or pl not in self.stmts:
                self.extra_place[nid] = ("ctx", owner)
                continue
            pst = self.stmts[pl]
            extra_parent = next(
                (n for n in pst.nodes if self.g.nodes.get(n, {}).get("kind") in ("ext", "raw", "unknown")), None
            )
            if extra_parent:
                self.nested[extra_parent].append(nid)
            elif owner in pst.nodes or pl in (self.g.nodes.get(owner, {}).get("lines") or [])[:1]:
                self.extra_place[nid] = ("ctx", owner)
            elif pst.nodes:
                self.extra_place[nid] = ("attach", list(pst.nodes))
                for n in pst.nodes:
                    self.attached[n].append(nid)
            else:
                self.extra_place[nid] = ("ctx", owner)

    def extra_text(self, nid: str) -> str:
        d = self.g.nodes[nid]
        lines = d.get("lines") or []
        st = self.stmts.get(min(lines)) if lines else None
        if st is not None:
            return st.line.text
        if d.get("text"):
            return str(d["text"]).strip()
        return ""

    def extra_lines(self, nid: str, depth: int) -> list[RLine]:
        if nid in self.emitted_extras:
            return []
        text = self.extra_text(nid)
        self.emitted_extras.add(nid)
        if not text:
            return []
        out = [RLine(depth, text, "extra", nodes=[nid])]
        for child in sorted(self.nested.get(nid, []), key=self.first_line):
            out += self.extra_lines(child, depth + 1)
        return out

    def attached_lines(self, st: _Stmt, depth: int) -> list[RLine]:
        out: list[RLine] = []
        for n in sorted(st.covers | set(st.objects.values())):
            for x in sorted(self.attached.get(n, []), key=self.first_line):
                out += self.extra_lines(x, depth + 1)
        return out

    # ----- 排序：被引用的先出现 -----

    def sorted_children(self, nid: str, kinds: tuple[str, ...]) -> list[str]:
        items = [c for c in self.children.get(nid, []) if self.g.nodes[c].get("kind") in kinds]
        if not items:
            return []
        member: dict[str, str] = {}
        for c in items:
            member[c] = c
            stack = list(self.children.get(c, []))
            while stack:
                x = stack.pop()
                member[x] = c
                stack.extend(self.children.get(x, []))
        before: dict[str, set[str]] = defaultdict(set)
        for a, b, d in self.g.edges(data=True):
            if d.get("kind") in ("reference", "prerequisite") and a in member and b in member:
                ma, mb = member[a], member[b]
                if ma != mb:
                    before[ma].add(mb)
        base = sorted(items, key=lambda c: (self.first_line(c), self.order.get(c, 0)))
        out: list[str] = []
        done: set[str] = set()
        visiting: set[str] = set()

        def visit(c: str) -> None:
            if c in done or c in visiting:
                return
            visiting.add(c)
            for dep in sorted(before.get(c, ()), key=lambda x: base.index(x)):
                visit(dep)
            visiting.discard(c)
            done.add(c)
            out.append(c)

        for c in base:
            visit(c)
        return out

    def subtree_pending(self, nid: str) -> bool:
        if nid in self.pending:
            return True
        stack = list(self.children.get(nid, []))
        while stack:
            x = stack.pop()
            if x in self.pending:
                return True
            if self.extras_on and self.extra_place.get(x, ("", None))[0] == "ctx" and x not in self.emitted_extras:
                return True
            stack.extend(self.children.get(x, []))
        return False

    # ----- 生成一行 -----

    def desired(self, sn: SchemaNode, inst: str, relaxed: bool) -> Any:
        owner = self.g.nodes[inst]
        if sn.type == "object":
            return owner.get("key")
        rel = _short(sn.id, owner.get("schema"))
        nid = f"{inst}/{rel}"
        d = self.g.nodes.get(nid)
        if d is None or not valued(d):
            return None
        if nid in self.facts or relaxed:
            return d.get("value")
        return None

    def candidates(self, ctx: _Ctx, anchor: str, entering: bool | None, declare: bool = False) -> list[_Stmt]:
        d = self.g.nodes[anchor]
        schema = d.get("schema")
        chain = self.chain(anchor)
        out: list[_Stmt] = []
        for ct in self.idx.by_vs.get((ctx.view, schema), []):
            if entering is not None and ct.enters != entering:
                continue
            if declare and schema not in ct.declare:
                continue
            for relaxed in (False, True):
                got = self.try_card(ctx, anchor, ct, chain, relaxed)
                out += got
                if got:
                    break
        return out

    def try_card(self, ctx: _Ctx, anchor: str, ct: _CardT, chain: dict[str, str], relaxed: bool) -> list[_Stmt]:
        """一张卡写出 anchor：对象键与 anchor 自己的取值必须表达；卡上其他属性能顺带写出就写（贪心），写不出就不写。"""
        anchor_schema = self.g.nodes[anchor].get("schema")
        nb = max((len(alts) for _, alts, _ in ct.targets), default=1)
        out: list[_Stmt] = []
        inv = _Inverter(ct.card, self.ctx_of(chain))
        for b in range(nb):
            chosen = [(alts[min(b, len(alts) - 1)], expr) for _, alts, expr in ct.targets]
            if anchor_schema not in {t.node for t, _ in chosen}:
                continue
            must: list[list[_Sol]] = []
            optional: list[tuple[list[_Sol], list[_Sol]]] = []
            ok = True
            for t, expr in chosen:
                sn = self.kb.nodes.get(t.node)
                if sn is None:
                    continue
                if sn.type == "object":
                    inst = chain.get(sn.id)
                else:
                    osn = self.owner_schema(sn)
                    inst = chain.get(osn.id) if osn else None
                if inst is None:
                    if sn.id == anchor_schema:
                        ok = False
                        break
                    # 不在 anchor 所在链上的对象（以及它的属性）：这一行不能写出它，表达式必须取不到值
                    if expr != "auto":
                        must.append(inv.run(expr, None, "string"))
                    continue
                for path, fixed in t.fixed.items():
                    finst, fsn = chain.get(path), self.kb.nodes.get(path)
                    if finst is None or fsn is None:
                        ok = False
                        break
                    if ctx.scope.get(path) == finst:
                        continue  # 上下文里已有这个对象：解析时用上下文里的，固定键不起作用
                    fk = dict(fixed) if len(fsn.key) > 1 else next(iter(fixed.values()), "")
                    if not self.key_eq(fsn, self.g.nodes[finst].get("key"), fk):
                        ok = False
                        break
                if not ok:
                    break
                if expr == "auto":
                    continue
                want = self.desired(sn, inst, relaxed)
                ntype = sn.type if sn.type != "object" else "string"
                if sn.type == "object" or sn.id == anchor_schema:
                    part = inv.run(expr, want, ntype)
                    if not part:
                        ok = False
                        break
                    must.append(part)
                else:
                    optional.append(
                        (inv.run(expr, want, ntype) if want is not None else [], inv.run(expr, None, ntype))
                    )
            if not ok:
                continue
            sols = [_Sol()]
            for part in must:
                sols = [m for a in sols for x in part if (m := _merge(a, x)) is not None][:24]
            tried: set[_Sol] = set()
            for base in sols:
                full: _Sol | None = base
                minimal: _Sol | None = base
                for wants, absent in optional:
                    nxt = next((m for x in wants if full and (m := _merge(full, x)) is not None), None)
                    if nxt is None:
                        nxt = next((m for x in absent if full and (m := _merge(full, x)) is not None), None)
                    full = nxt
                    minimal = next((m for x in absent if minimal and (m := _merge(minimal, x)) is not None), None)
                for sol, is_full in ((full, True), (minimal, False)):
                    if sol is None or sol in tried or (not is_full and out):
                        continue  # 完整写法能通过时不再试最简写法
                    tried.add(sol)
                    found = 0
                    for text, neg in self.lines_for(ct.card, sol):
                        st = self.verify(ctx, text, neg, chain, anchor)
                        if st is not None:
                            st.full = is_full
                            out.append(st)
                            found += 1
                            if found >= 2:
                                break
                if out:
                    break
            if out:
                break
        return out

    def lines_for(self, card: Card, sol: _Sol) -> list[tuple[str, bool]]:
        gen = _Gen(sol, card.params)
        if not sol.neg:
            return [(t, False) for t in gen.lines(card.parsed)]
        out: list[tuple[str, bool]] = []
        if card.undo:
            if card.id not in self.idx.undo:
                try:
                    self.idx.undo[card.id] = syn.parse(card.undo)
                except syn.SyntaxErrorKB:
                    self.idx.undo[card.id] = None
            usyn = self.idx.undo[card.id]
            if usyn is not None:
                out += [(t, True) for t in gen.lines(usyn)]
        bare = " ".join([self.fam.negative, *card.parsed.leading_keywords()])
        out.append((bare, True))
        return out

    def ctx_of(self, chain: dict[str, str]) -> dict[str, Any] | None:
        inst = chain.get("interface")
        return {"interface": self.g.nodes[inst].get("key")} if inst else None

    def evaluate(
        self, card: Card, values: dict[str, Any], tokens: list[str], neg: bool, ctx: dict[str, Any] | None = None
    ) -> list[tuple[mapping.Target, SchemaNode, Any]]:
        targets = self.idx.targets.get(card.id)
        if targets is None:
            return []
        branch = 0
        for _, alts, expr in targets:
            if len(alts) > 1:
                branch = mapping.choose_branch([mapping.evaluate(expr, values, tokens, neg, ctx=ctx)])
                break
        out = []
        for _, alts, expr in targets:
            t = alts[min(branch, len(alts) - 1)]
            sn = self.kb.nodes.get(t.node)
            if sn is None:
                continue
            v: Any = _AUTO if expr == "auto" else mapping.evaluate(expr, values, tokens, neg, ctx=ctx)
            if v is None or (v == "" and sn.type != "object"):
                if sn.type == "object":
                    out.append((t, sn, None))
                continue
            out.append((t, sn, v))
        return out

    def verify(self, ctx: _Ctx, text: str, neg: bool, chain: dict[str, str], anchor: str) -> _Stmt | None:
        key = (ctx.view, text, neg)
        if key not in self.parse_cache:
            if neg:
                hit = parsemod.match_undo(self.idx.parser, ctx.view, text)
                self.parse_cache[key] = (hit[0], hit[1]) if hit else None
            else:
                self.parse_cache[key] = parsemod.match_line(self.idx.parser, ctx.view, text)
        parsed = self.parse_cache[key]
        if parsed is None:
            return None
        card, m = parsed
        produced = self.evaluate(card, m.all_values(), text.split(), neg, self.ctx_of(chain))
        if not produced:
            return None
        objects: dict[str, str] = {}
        skipped: set[str] = set()
        matched: set[str] = set()
        for _t, sn, v in produced:
            if sn.type != "object":
                continue
            if v is None:
                skipped.add(sn.id)
                continue
            inst = chain.get(sn.id)
            if inst is None or isinstance(v, list) and len(v) != 1:
                return None
            if isinstance(v, dict) and any(isinstance(x, list) for x in v.values()):
                if any(isinstance(x, list) and len(x) != 1 for x in v.values()):
                    return None  # 一行展开成多个对象：生成时只写一个
                v = {k: (x[0] if isinstance(x, list) else x) for k, x in v.items()}
            if not self.key_eq(sn, self.g.nodes[inst].get("key"), v):
                return None
            objects[sn.id] = inst
            matched.add(inst)
        for t, _sn, _v in produced:
            for path, fixed in t.fixed.items():
                finst, fsn = chain.get(path), self.kb.nodes.get(path)
                if finst is None or fsn is None:
                    return None
                if ctx.scope.get(path) == finst:
                    continue
                fk = dict(fixed) if len(fsn.key) > 1 else next(iter(fixed.values()), "")
                if not self.key_eq(fsn, self.g.nodes[finst].get("key"), fk):
                    return None
                objects.setdefault(path, finst)
                matched.add(finst)  # 路径上的固定键对象也由这一行创建
        for inst in list(objects.values()):
            if not self.placed(inst, ctx, objects):
                return None
        for _t, sn, v in produced:
            if sn.type == "object":
                continue
            osn = self.owner_schema(sn)
            if osn is None:
                return None
            inst = objects.get(osn.id) or ctx.scope.get(osn.id)
            if inst is None:
                if osn.id in skipped:
                    continue
                inst = chain.get(osn.id)
                if inst is None or not (self.placeholder(inst) and self.placed(inst, ctx, objects)):
                    return None
            if inst != chain.get(osn.id):
                return None
            nid = f"{inst}/{_short(sn.id, osn.id)}"
            d = self.g.nodes.get(nid)
            if v is _AUTO:
                continue
            value = mapping.normalize(sn.type, sn.id, v)
            if d is not None and valued(d):
                if not _same(d.get("value"), value, sn.type):
                    return None
                matched.add(nid)
            elif not (value is False or (sn.id in self.defaults and _same(self.defaults[sn.id], value, sn.type))):
                return None
        if anchor not in matched:
            return None
        return _Stmt(text, card, neg, matched & self.pending, objects, matched)

    def placed(self, inst: str, ctx: _Ctx, objects: dict[str, str], depth: int = 0) -> bool:
        p = self.parent.get(inst, DEVICE)
        if p == DEVICE or depth > 8:
            return p == DEVICE
        ps = self.g.nodes[p].get("schema")
        if ctx.scope.get(ps) == p:
            return True
        if ps in ctx.scope:  # 上下文里有同类型的另一个对象：解析时会挂到那一个下面
            return False
        if p in objects.values() or self.placeholder(p):
            return self.placed(p, ctx, objects, depth + 1)
        return False

    def best(self, cands: list[_Stmt], anchor: str) -> _Stmt | None:
        if not cands:
            return None
        schema = self.g.nodes[anchor].get("schema") or ""
        prefer = self.style["prefer"].get(schema, [])
        orig = set(self.g.nodes[anchor].get("cards") or [])
        for s0 in cands:
            for n in s0.covers:
                orig.update(self.g.nodes[n].get("cards") or [])
        rank = parsemod.STATUS_RANK

        def score(s: _Stmt) -> tuple[Any, ...]:
            # 顺带把不需要写的取值（默认值）写成显式的，扣分
            extra = sum(1 for n in s.matched - s.covers if self.g.nodes[n].get("origin") == "default")
            return (
                s.card.id in prefer,
                len(s.covers),
                -extra,
                s.card.id in orig,
                s.full,
                rank.get(s.card.status, 0),
                -len(s.text),
                s.card.id,
            )

        return max(cands, key=score)

    def take(self, st: _Stmt, depth: int) -> list[RLine]:
        self.pending -= st.covers
        self.covered |= st.covers
        self.inferred_used |= st.matched & self.inferred
        origin = "default" if st.covers and st.covers <= self.default_facts else "explicit"
        line = RLine(depth, st.text, "command", origin, sorted(st.covers), st.card.id, bool(st.card.enters_view))
        line.objects, line.matched = sorted(set(st.objects.values())), sorted(st.matched | st.covers)
        return [line, *self.attached_lines(st, depth)]

    def original(self, ctx: _Ctx, nid: str, header: bool = False) -> tuple[list[RLine], _Stmt | None]:
        """同平台族时，反推不出命令的节点按原文写回（例如带密文的命令）：原文行所在视图与当前视图相同才用。"""
        if not self.extras_on:
            return [], None
        for no in self.g.nodes[nid].get("lines") or []:
            st0 = self.stmts.get(no)
            if st0 is None or st0.line.kind != "command" or st0.line.view != ctx.view or nid not in st0.nodes:
                continue
            card = self.kb.cards.get(str(st0.line.card))
            if card is None:
                continue
            if header and (
                not card.enters_view
                or any(n.startswith(nid + "/") and self.g.nodes[n].get("kind") == "object" for n in st0.nodes)
            ):
                continue  # 入口命令：这一行创建的最深的对象必须就是它
            objects = {
                str(self.g.nodes[n].get("schema")): n
                for n in st0.nodes
                if self.g.nodes.get(n, {}).get("kind") == "object"
            }
            st = _Stmt(st0.line.text, card, st0.line.negated, set(st0.nodes) & self.pending, objects)
            lines = self.take(st, ctx.depth)
            lines[0].kind = "original"
            return lines, st
        return [], None

    # ----- 块 -----

    def flat(self, ctx: _Ctx, nid: str, declare: bool = False) -> list[RLine]:
        if nid not in self.pending:
            return []
        entering = False if self.g.nodes[nid].get("kind") == "object" else None
        st = self.best(self.candidates(ctx, nid, entering, declare), nid)
        if st is not None:
            lines = self.take(st, ctx.depth)
            if st.card.enters_view and entering is None:
                lines += self.bridge(ctx, st, str(st.card.enters_view), self.parent.get(nid, DEVICE))
            return lines
        if declare:
            return []
        return self.original(ctx, nid)[0]

    def bridge(self, ctx: _Ctx, st: _Stmt | None, view: str, owner: str) -> list[RLine]:
        """属性行（或未映射的命令）进入了一个子视图（华为 pwsignal ldp → VSI-LDP 视图）：
        同一对象只能在这个子视图里写的属性与子对象接着写在它下面。"""
        if owner == DEVICE or view not in self.fam.views:
            return []
        scope = {**ctx.scope, **({str(self.g.nodes[n]["schema"]): n for n in st.objects.values()} if st else {})}
        inner = self.ctx_lines(_Ctx(view, scope, ctx.depth + 1), owner, extras=False)
        exit_cmd = self.style["exits"].get(view)
        return inner + ([RLine(ctx.depth, exit_cmd, "exit")] if inner and exit_cmd else [])

    def attrs_of(self, owner: str) -> list[str]:
        return sorted(
            (c for c in self.children.get(owner, []) if self.g.nodes[c].get("kind") == "attr"),
            key=lambda c: (self.first_line(c), self.node_rank.get(self.g.nodes[c].get("schema"), 0)),
        )

    def ctx_lines(self, ctx: _Ctx, owner: str, extras: bool = True) -> list[RLine]:
        explicit: list[RLine] = []
        defaults: list[RLine] = []
        for a in self.attrs_of(owner):
            got = self.flat(ctx, a)
            (defaults if got and got[0].origin == "default" and got[0].kind == "command" else explicit).extend(got)
        out = explicit
        blocks: list[tuple[int, _Ctx]] = []  # 这一层写出的子块：（块结束的位置，块内的上下文）
        for c in self.sorted_children(owner, ("object", "ext", "raw", "unknown")):
            if self.g.nodes[c].get("kind") == "object" and c not in self.extra_place:
                self.last_block = None
                out += self.object_lines(ctx, c)
                if self.last_block is not None:
                    end = len(out) - (1 if out and out[-1].kind == "exit" else 0)
                    blocks.append((end, self.last_block))
            elif extras and self.extras_on and self.extra_place.get(c, ("", None)) == ("ctx", owner):
                out += self.extra_lines(c, ctx.depth)
                card = self.kb.cards.get(str(self.g.nodes[c].get("schema") or "")[4:])
                if card is not None and card.enters_view:  # 未映射的命令进入了子视图：同一对象的属性接着写在它下面
                    out += self.bridge(ctx, None, str(card.enters_view), owner)
        self.into_sibling_blocks(owner, out, blocks)
        if defaults:
            out += [RLine(ctx.depth, DEFAULT_MARK, "comment", "default"), *defaults]
        return out

    def into_sibling_blocks(self, owner: str, out: list[RLine], blocks: list[tuple[int, _Ctx]]) -> None:
        """在本层写不出的子对象，试着写进兄弟对象的块里（解析时块内的上下文也包含本层对象，
        例如 Cisco 的 backup peer 写在 xconnect 块里，但属于业务实例）。"""
        if not blocks:
            return
        rest = [
            c for c in self.sorted_children(owner, ("object",)) if c not in self.extra_place and self.subtree_pending(c)
        ]
        for c in rest:
            schema = str(self.g.nodes[c].get("schema"))
            for i, (end, bctx) in enumerate(blocks):
                if not any(v == bctx.view for v, sch in self.idx.by_vs if sch == schema):
                    continue
                self.last_block = None
                got = self.object_lines(bctx, c)
                if got:
                    out[end:end] = got
                    blocks[i:] = [(e + len(got), b) for e, b in blocks[i:]]
                    break

    def subtree_facts(self, obj: str) -> list[str]:
        out, stack = [], [obj]
        while stack:
            x = stack.pop()
            if x in self.pending:
                out.append(x)
            stack.extend(self.children.get(x, []))
        return out

    def header(self, ctx: _Ctx, obj: str) -> _Stmt | None:
        """入口命令：进入视图的卡；有多张卡进入不同视图时，选块内能写出最多节点的那个视图。"""
        cands = self.candidates(ctx, obj, True)
        if not cands:
            return None
        views = {str(c.card.enters_view) for c in cands}
        if len(views) > 1:
            facts = self.subtree_facts(obj)

            def able(v: str) -> int:
                return sum(1 for f in facts if self.idx.by_vs.get((v, str(self.g.nodes[f].get("schema")))))

            top = max(able(v) for v in views)
            cands = [c for c in cands if able(str(c.card.enters_view)) == top]
        return self.best(cands, obj)

    def object_lines(self, ctx: _Ctx, obj: str) -> list[RLine]:
        if not self.subtree_pending(obj):
            return []
        st = self.header(ctx, obj)
        if st is not None:
            head = self.take(st, ctx.depth)
        else:
            head, st = self.original(ctx, obj, header=True)
            if st is None:
                return self.flat_subtree(ctx, obj)
        view = str(st.card.enters_view)
        scope = {**ctx.scope, **{str(self.g.nodes[n]["schema"]): n for n in st.objects.values()}}
        inner = self.ctx_lines(_Ctx(view, scope, ctx.depth + 1), obj)
        before = self.flat_subtree(ctx, obj)  # 块里写不出、但在外层视图能写的
        exit_cmd = self.style["exits"].get(view)
        block = head + inner + ([RLine(ctx.depth, exit_cmd, "exit")] if exit_cmd else [])
        self.last_block = _Ctx(view, scope, ctx.depth + 1)
        if ctx.depth == 1 and self.style["nested_separator"]:
            block = [RLine(1, self.fam.separator, "separator"), *block]
        return before + block

    def flat_subtree(self, ctx: _Ctx, obj: str) -> list[RLine]:
        """没有入口命令的对象：属性行顺带给出键；需要先声明的对象先写声明行。"""
        out: list[RLine] = []
        schema = self.g.nodes[obj].get("schema") or ""
        attrs = self.attrs_of(obj)
        kids_pending = any(self.subtree_pending(c) for c in self.sorted_children(obj, ("object",)))
        if obj in self.pending and schema not in self.style["no_declare"]:
            direct = {a for a in attrs if a in self.pending}
            best_any = self.best(self.candidates(ctx, obj, False), obj) if direct or not kids_pending else None
            if best_any is not None and direct <= best_any.covers:
                out += self.take(best_any, ctx.depth)  # 一行就能写全
            else:
                out += self.flat(ctx, obj, declare=True)
        defaults: list[RLine] = []
        for a in attrs:
            got = self.flat(ctx, a)
            (defaults if got and got[0].origin == "default" and got[0].kind == "command" else out).extend(got)
        for c in self.sorted_children(obj, ("object",)):
            out += self.object_lines(ctx, c)
        out += self.flat(ctx, obj)
        if defaults:
            out += [RLine(ctx.depth, DEFAULT_MARK, "comment", "default"), *defaults]
        return out

    # ----- 整体 -----

    def run(self) -> Rendered:
        root = _Ctx(self.fam.root_view, {}, 0)
        sep, end = self.fam.separator, self.fam.end
        lines: list[RLine] = [RLine(0, sep, "separator")]
        for c in self.sorted_children(DEVICE, ("object", "ext", "raw", "unknown")):
            kind = self.g.nodes[c].get("kind")
            if kind == "object" and c not in self.extra_place:
                part = self.object_lines(root, c)
            elif self.extras_on and self.extra_place.get(c, ("", None))[0] == "ctx":
                part = self.extra_lines(c, 0)
            else:
                part = []
            if not part:
                continue
            block = any(ln.depth > 0 or ln.opens for ln in part)
            if block and lines[-1].kind != "separator":
                lines.append(RLine(0, sep, "separator"))
            lines += part
            if block:
                lines.append(RLine(0, sep, "separator"))
        if lines[-1].kind != "separator":
            lines.append(RLine(0, sep, "separator"))
        if end:
            lines.append(RLine(0, end, "end"))
        skipped = sorted(
            n
            for n, d in self.g.nodes(data=True)
            if self.extras_on
            and (d.get("kind") in ("ext", "raw", "unknown") or n in self.extra_place)
            and n not in self.emitted_extras
        )
        uncovered = [n for n in self.g.nodes if n in self.pending]
        return Rendered(
            self.profile.id,
            self.fam.id,
            lines,
            self.fam.indent,
            uncovered,
            set(self.covered),
            skipped,
            [
                {"node": n, "schema": self.g.nodes[n].get("schema"), "value": self.g.nodes[n].get("value")}
                for n in sorted(self.inferred_used)
            ],
        )


# ---------------------------------------------------------------- 入口


def negated_object(g: nx.MultiDiGraph, nid: str) -> bool:
    """只由取消形式的命令行产生的对象（例如 Cisco 的 no aaa new-model）：不算配置了这个对象。"""
    lines = g.nodes[nid].get("lines") or []
    if not lines:
        return False
    stmts = g.graph.get("_stmt_index")
    if stmts is None:
        stmts = {st.line.no: st for st in g.graph.get("statements", [])}
        g.graph["_stmt_index"] = stmts
    found = [stmts[no] for no in lines if no in stmts]
    if not found or len(found) != len(lines) or not all(st.line.negated for st in found):
        return False
    # 取消形式同时给出了属性（undo silent-interface X → enabled=false）时，对象是有意义的
    return not any(
        g.nodes[c].get("kind") == "attr" and g.nodes[c].get("origin") == "explicit" for c in g.successors(nid)
    )


def _operand(g: nx.MultiDiGraph, owner: str, parent: dict[str, str], name: str) -> Any:
    if name == "^":  # 上级对象的键
        p = parent.get(owner)
        return g.nodes[p].get("key") if p and p != DEVICE else None
    d = g.nodes.get(f"{owner}/{name}")
    return d.get("value") if d is not None and valued(d) else None


def apply_infer(g: nx.MultiDiGraph, kb: KnowledgeBase, family: str) -> nx.MultiDiGraph:
    """推导规则（knowledge/render/<平台族>.yaml 的 infer）：目标平台族写声明行必须给出、源配置又没有的取值，
    按同一对象的其他取值推出（same：两个取值相等；differ：不相等；“^” 表示上级对象的键）。
    推出的节点 origin=inferred，不算要写出的节点，只让必须带上它的命令行通过校验；返回副本（没有推出时返回原图）。"""
    _, style = _index(kb, family)
    rules = style["infer"]
    if not rules:
        return g
    parent = {b: a for a, b, d in g.edges(data=True) if d.get("kind") == "contains"}
    added: list[tuple[str, str, str, Any]] = []
    for rule in rules:
        sn = kb.nodes.get(str(rule["node"]))
        if sn is None or sn.parent is None:
            continue
        owner_schema = sn.parent
        rel = _short(sn.id, owner_schema)
        for nid, d in g.nodes(data=True):
            if d.get("kind") != "object" or d.get("schema") != owner_schema or f"{nid}/{rel}" in g:
                continue
            ok = True
            for op, want_equal in (("same", True), ("differ", False)):
                if op in rule:
                    a, b = (_operand(g, nid, parent, str(x)) for x in rule[op])
                    if a is None or b is None or (str(a) == str(b)) != want_equal:
                        ok = False
            if ok and all(x[0] != f"{nid}/{rel}" for x in added):
                added.append((f"{nid}/{rel}", nid, sn.id, mapping.normalize(sn.type, sn.id, rule.get("value"))))
    if not added:
        return g
    h = g.copy()
    for child, owner, schema, value in added:
        h.add_node(
            child,
            kind="attr",
            schema=schema,
            value=value,
            raw=value,
            origin="inferred",
            lines=[],
            cards=[],
            negated=False,
        )
        h.add_edge(owner, child, kind="contains")
    return h


def graph_from_json(data: dict[str, Any]) -> nx.MultiDiGraph:
    """to_json 格式（nodes / edges）的图 → networkx 图（模板等只有节点数据的调用方用）。"""
    g = nx.MultiDiGraph(device=data.get("device"), profile=data.get("profile"), kb_version=data.get("kb_version"))
    if DEVICE not in {n.get("id") for n in data.get("nodes", [])}:
        g.add_node(DEVICE, kind="device", schema=None, value=data.get("device"), origin="explicit", lines=[], cards=[])
    for n in data.get("nodes", []):
        attrs = {k: v for k, v in n.items() if k != "id"}
        attrs.setdefault("lines", [])
        attrs.setdefault("cards", [])
        attrs.setdefault("origin", "explicit")
        g.add_node(n["id"], **attrs)
    for e in data.get("edges", []):
        g.add_edge(e["from"], e["to"], kind=e.get("kind"), note=Note.of(e.get("note")))
    return g


def _as_graph(graph_or_nodes: Any) -> nx.MultiDiGraph:
    if isinstance(graph_or_nodes, nx.MultiDiGraph):
        return graph_or_nodes
    if isinstance(graph_or_nodes, dict) and "nodes" in graph_or_nodes:
        return graph_from_json(graph_or_nodes)
    raise CanonError("canon.bad_graph")


def retarget_defaults(g: nx.MultiDiGraph, kb: KnowledgeBase, profile_id: str) -> nx.MultiDiGraph:
    """换一个 Profile 看同一张图：去掉原 Profile 的默认节点，按目标 Profile 补上它的默认节点（副本）。"""
    h = g.copy()
    h.remove_nodes_from([n for n, d in g.nodes(data=True) if d.get("kind") == "attr" and d.get("origin") == "default"])
    b = Builder(kb, kb.profiles[profile_id], str(g.graph.get("device") or "device"))
    b.g = h
    b._defaults()
    h.graph["profile"] = profile_id
    h.graph["family"] = kb.profiles[profile_id].family
    return h


def default_facts(g: nx.MultiDiGraph, kb: KnowledgeBase, profile_id: str, include_defaults: bool) -> set[str]:
    """要写出的节点：显式的对象与属性；目标 Profile 不隐式创建的派生对象；include_defaults 时加上默认值节点。"""
    implicit = set(kb.resolve_profile(profile_id).implicit)
    out: set[str] = set()
    for n, d in g.nodes(data=True):
        kind, origin = d.get("kind"), d.get("origin")
        if kind == "object":
            if origin == "derived" and d.get("schema") in implicit:
                continue
            if origin == "default" or negated_object(g, n):
                continue
            out.add(n)
        elif kind == "attr" and valued(d):
            if origin == "default" and not include_defaults:
                continue
            if d.get("value") is None:
                continue
            out.add(n)
    return out


def render_full(
    graph_or_nodes: Any,
    kb: KnowledgeBase,
    profile_id: str,
    include_defaults: bool = False,
    facts: set[str] | None = None,
    extras: bool | None = None,
) -> Rendered:
    """规范渲染，返回逐行结果（每行的来源节点、是否默认值行）与没能写出的节点。"""
    if profile_id not in kb.profiles:
        raise CanonError("parse.profile_unknown", profile=profile_id)
    g = _as_graph(graph_or_nodes)
    if g.graph.get("profile") and g.graph.get("profile") != profile_id and include_defaults:
        g = retarget_defaults(g, kb, profile_id)
    src_profile = kb.profiles.get(str(g.graph.get("profile")))
    family = g.graph.get("family") or (src_profile.family if src_profile else None)
    same_family = family == kb.profiles[profile_id].family
    if facts is None:
        facts = default_facts(g, kb, profile_id, include_defaults)
    g = apply_infer(g, kb, kb.profiles[profile_id].family)
    return _Renderer(g, kb, profile_id, facts, same_family if extras is None else extras).run()


def result_dict(r: Rendered, with_defaults: bool = False) -> dict[str, Any]:
    """CLI / API 共用的规范渲染结果：文本、逐行来源、默认值行的行号、没能写出的节点。"""
    lines = r.line_dicts()
    return {
        "text": r.text,
        "profile": r.profile,
        "family": r.family,
        "mode": "canonical",
        "with_defaults": with_defaults,
        "lines": lines,
        "default_lines": [ln["no"] for ln in lines if ln["origin"] == "default" and ln["kind"] == "command"],
        "uncovered": r.uncovered,
        "skipped_extras": r.skipped_extras,
    }


def render(graph_or_nodes: Any, kb: KnowledgeBase, profile_id: str, include_defaults: bool = False) -> str:
    """规范渲染：图 → 目标 Profile 的配置文本（模板、翻译等共用的接口）。"""
    return render_full(graph_or_nodes, kb, profile_id, include_defaults).text
