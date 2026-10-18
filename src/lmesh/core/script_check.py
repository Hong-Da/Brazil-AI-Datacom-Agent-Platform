"""配置检查项目的脚本检查（REQ-031）：变更脚本 / 完整配置，边写边查，问题按行给出。

变更脚本（kind=change）：
    1. 逐行跟踪视图（与设备一样：进入对象的命令打开视图，quit / exit 退出；有缩进时按缩进；当前视图匹配不到时
       逐级退回上层视图），命令按命令卡识别：未识别（error）、功能域外（info，无法校验）、视图错误（属于别的视图，error）。
    2. 脚本行（带所在视图）直接构造成解析结果，接在基线配置之后建图（合并图 M），得到每行的规范编号、新建的对象、引用的对象。
    3. 在基线配置的行树上模拟执行（复用 core/change.py 的 _Sim：取消命令按取消语法匹配、同一属性覆盖、Profile 副作用），
       记录每一行删除 / 覆盖了基线的哪一行、被副作用删除的行；顺序核查开启时按书写顺序执行，逐步检查
       “引用了后面才创建的对象”“删除时引用方在后面才处理”“先配的值被后面的命令的副作用删除”（这些都能靠重排解决，报为顺序错误）；
       关闭时按依赖重排后的顺序执行（只看内容）。
    4. 执行后的配置（行树直接构造成解析结果，不重新解析文本）建图，跑配置检查（core/checks.py），与基线的检查结果比较：
       新出现的发现落到脚本行上；另查新内容与现网的地址 / RD 冲突。
    5. 按依赖重排（reorder）：约束 = 子命令在进入视图之后、被引用的先建、删除时先处理引用方、副作用之后再配被删除的值、
       同一属性的多条命令保持原顺序；约束之外保持原顺序（lexicographical_topological_sort），并说明每条移动的命令为什么移动。
完整配置（kind=full）：解析、未识别行、配置检查规则；有基线时与基线按有效值对比（core/compare.py）给出差异摘要。
AI 一起校验：规则文件中 ai: true 的规则可勾选交给 AI；发给 AI 的配置先脱敏；AI 的发现必须落到脚本中真实存在的行、
该行在图上对应规则适用的对象、引用的原文与该行一致，代码校验通过才展示（status passed；没有给出证据的为 unverifiable），
否则拦截（rejected，只计数并列出原因）。
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import threading
import time
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from lmesh.core import change, checks, compare, i18n
from lmesh.core import graph as graphmod
from lmesh.core import parser as parsemod
from lmesh.core import rules as rulesmod
from lmesh.core.kb import KnowledgeBase

KINDS = ("change", "full")
SEVERITIES = ("error", "warning", "info")
CATEGORIES = ("parse", "view", "undo", "override", "side_effect", "order", "conflict", "rule", "ai")
AI_STATUSES = ("passed", "unverifiable")
_SEV_RANK = {"error": 3, "warning": 2, "info": 1}
_SESSION = re.compile(r"^(system-view|sys|configure(\s+terminal)?|conf(ig)?\s+t(erm(inal)?)?|commit|return|end)$", re.I)
_WS = re.compile(r"\s+")
REORDER_PRIORITY = ["same_target", "anchor", "side_effect", "referenced_by", "reference", "contains"]


class ScriptCheckError(ValueError):
    """参数错误。key 是文案键；kind 为 param / not_found / state。"""

    def __init__(self, key: str, kind: str = "param", **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.fmt = key, kind, fmt


# ---------------------------------------------------------------- 基线（缓存）


@dataclass
class Baseline:
    text: str
    profile: str
    family: str
    device: str
    parsed: parsemod.Parsed
    graph: nx.MultiDiGraph
    device_id: int | None = None
    version_id: int | None = None
    label: str = ""
    _check: dict[str, Any] | None = None

    def info(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "device_id": self.device_id,
            "version_id": self.version_id,
            "profile": self.profile,
            "family": self.family,
            "lines": len(self.parsed.lines),
            "label": self.label or self.device,
        }


_CACHE: OrderedDict[tuple[Any, ...], Baseline] = OrderedDict()
_CACHE_MAX = 8
_lock = threading.Lock()


def _cached(key: tuple[Any, ...], make: Any) -> Baseline:
    with _lock:
        hit = _CACHE.get(key)
        if hit is not None:
            _CACHE.move_to_end(key)
            return hit
    b: Baseline = make()
    with _lock:
        _CACHE[key] = b
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return b


def clear_cache() -> None:
    with _lock:
        _CACHE.clear()


def baseline_from_text(
    text: str, kb: KnowledgeBase, profile: str | None = None, device: str = "baseline", **meta: Any
) -> Baseline:
    """基线配置文本 → 解析结果与图（按 文本指纹 + Profile + 知识库对象 缓存）。"""
    from lmesh.core import analysis

    text = text.replace("\r\n", "\n")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

    def make() -> Baseline:
        try:
            res = analysis.parse_text(text, kb, profile)
        except analysis.AnalysisError as e:
            raise ScriptCheckError(str(e), profile=profile or "") from e
        g = graphmod.build(res.parsed, kb, res.profile, device)
        return Baseline(text, res.profile, res.family, device, res.parsed, g, **meta)

    return _cached(("text", digest, profile, device, id(kb), meta.get("version_id")), make)


def baseline_from_db(
    db_url: str, kb: KnowledgeBase, device_id: int, version_id: int | None = None, profile: str | None = None
) -> Baseline:
    """已导入设备的某个配置版本（不给版本时取最新）作为基线。"""
    from lmesh.core import store
    from lmesh.core.store.models import ConfigVersion, Device

    if version_id is None:
        vers = compare.versions(db_url, device_id)
        if not vers:
            raise ScriptCheckError("script_check.device_not_found", "not_found", device=device_id)
        version_id = int(vers[0]["id"])
    with store.session(db_url) as s:
        ver = s.get(ConfigVersion, version_id)
        if ver is None or ver.device_id != device_id:
            raise ScriptCheckError("script_check.version_not_found", "not_found", version=version_id)
        dev = s.get(Device, device_id)
        assert dev is not None
        text, name, dev_profile = ver.raw_text, dev.name, dev.profile
    use = profile or (dev_profile if dev_profile in kb.profiles else None)
    return baseline_from_text(
        text, kb, use, name, device_id=device_id, version_id=version_id, label=f"{name}@{version_id}"
    )


def _rules(kb: KnowledgeBase, rules_dir: Path | None) -> list[rulesmod.Rule]:
    d = rules_dir or checks.rules_dir(Path(kb.root))
    return rulesmod.load_cached(kb, d)


def _base_check(b: Baseline, kb: KnowledgeBase, rules: list[rulesmod.Rule]) -> dict[str, Any]:
    if b._check is None or b._check.get("_rules") != id(rules):
        r = checks.check(b.graph, kb, rules)
        r["_rules"] = id(rules)
        b._check = r
    return b._check


def ai_rules(kb: KnowledgeBase, rules_dir: Path | None = None) -> list[dict[str, Any]]:
    """可交给 AI 参与的规则（规则文件中 ai: true）：编号、标题（三语）、级别、适用对象、是否也有代码断言。"""
    return [
        {
            "id": r.id,
            "title": r.title,
            "severity": r.severity,
            "target": r.target,
            "domain": r.domain,
            "code": r.assert_ is not None,
            "file": r.file,
        }
        for r in _rules(kb, rules_dir)
        if r.ai and r.enabled
    ]


# ---------------------------------------------------------------- 1. 逐行跟踪视图


@dataclass
class SLine:
    no: int
    raw: str
    kind: str  # blank / comment / separator / session / exit / command / unknown / raw / wrong_view
    view: str = ""
    card: str | None = None
    negated: bool = False
    enters: str | None = None
    ctx: list[int] = field(default_factory=list)  # 所在视图的进入命令（脚本行号，外层在前）
    match: Any = None
    domain: str = ""
    belongs: str | None = None  # 视图错误：这条命令所属的视图
    implicit_from: str | None = None  # 当前视图匹配不到、退回上层视图执行时，原来的视图

    @property
    def text(self) -> str:
        return self.raw.strip()


@dataclass
class _Frame:
    indent: int
    view: str
    no: int


_INDEX: dict[tuple[int, str], parsemod.CardIndex] = {}


def card_index(kb: KnowledgeBase, family: str) -> parsemod.CardIndex:
    key = (id(kb), family)
    idx = _INDEX.get(key)
    if idx is None:
        idx = parsemod.CardIndex(kb, family)
        _INDEX.clear()  # 只留当前知识库的索引
        _INDEX[key] = idx
    return idx


def _match(idx: parsemod.CardIndex, view: str, text: str) -> tuple[Any, Any, bool] | None:
    if text.split()[0].lower() == idx.negative:
        u = parsemod.match_undo(idx, view, text)
        if u is not None:
            return u[0], u[1], True
    m = parsemod.match_line(idx, view, text)
    return (m[0], m[1], False) if m is not None else None


def _all_views(idx: parsemod.CardIndex) -> list[str]:
    views = {v for v, _ in idx.by_key} | set(idx.loose) | set(idx.undo)
    return sorted(views)


def track(text: str, kb: KnowledgeBase, family: str) -> list[SLine]:
    fam = kb.families[family]
    idx = card_index(kb, family)
    raw_lines = text.replace("\r\n", "\n").split("\n")
    indented = any(ln[:1] in (" ", "\t") and ln.strip() and ln.strip() != fam.separator for ln in raw_lines)
    exits = {v: set(getattr(fam.views.get(v), "exit", []) or []) for v in fam.views}
    out: list[SLine] = []
    stack: list[_Frame] = []
    for no, raw in enumerate(raw_lines, start=1):
        s = raw.strip()
        ind = len(raw.expandtabs(1)) - len(raw.expandtabs(1).lstrip())
        if not s:
            out.append(SLine(no, raw, "blank"))
            continue
        if s == fam.separator:
            if ind == 0:
                stack.clear()
            out.append(SLine(no, raw, "separator"))
            continue
        if s.startswith("!") or (fam.separator == "#" and s.startswith("#")):
            out.append(SLine(no, raw, "comment"))
            continue
        if _SESSION.match(s):
            stack.clear()
            out.append(SLine(no, raw, "session"))
            continue
        exit_at = next((k for k in range(len(stack) - 1, -1, -1) if s in exits.get(stack[k].view, set())), None)
        if exit_at is not None or s.lower() in ("quit", "exit"):
            if exit_at is not None:
                del stack[exit_at:]
            elif stack:
                stack.pop()
            out.append(SLine(no, raw, "exit"))
            continue
        if indented:
            while stack and stack[-1].indent >= ind:
                stack.pop()
        cur_view = stack[-1].view if stack else fam.root_view
        found = None
        for depth in range(len(stack), -1, -1):
            view = stack[depth - 1].view if depth else fam.root_view
            m = _match(idx, view, s)
            if m is not None:
                found = (depth, view, m)
                break
            if depth and not idx.prefixes.get(view) and not idx.loose.get(view):
                continue
        if found is not None:
            depth, view, (card, mt, neg) = found
            sl = SLine(no, raw, "command", view, card.id, neg, None, [f.no for f in stack[:depth]], mt, card.domain)
            if depth < len(stack):
                sl.implicit_from = cur_view
            del stack[depth:]
            if card.enters_view and not neg:
                sl.enters = str(card.enters_view)
                stack.append(_Frame(ind, sl.enters, no))
            out.append(sl)
            continue
        belongs = next((v for v in _all_views(idx) if v != cur_view and _match(idx, v, s) is not None), None)
        kind = "wrong_view" if belongs else ("unknown" if idx.known_prefix(cur_view, s.split()) else "raw")
        out.append(SLine(no, raw, kind, cur_view, ctx=[f.no for f in stack], belongs=belongs))
    return out


# ---------------------------------------------------------------- 2. 合并图：基线 + 脚本行


def _line_of(sl: SLine, no: int, parent: int | None, depth: int, indent: int) -> parsemod.Line:
    lead = " " * (indent * depth)
    return parsemod.Line(
        no,
        lead + sl.text,
        "command",
        lead,
        sl.view,
        sl.card,
        sl.match,
        parent,
        sl.domain,
        negated=sl.negated,
    )


@dataclass
class _Merged:
    graph: nx.MultiDiGraph
    nodes: dict[int, list[str]]  # 脚本行号 → 合并图中的节点
    lines: dict[int, parsemod.Line]  # 脚本行号 → 构造出的解析行（行号是脚本行号）


def _merge(b: Baseline, cmds: list[SLine], kb: KnowledgeBase) -> _Merged:
    fam = kb.families[b.family]
    off = len(b.parsed.lines) + 1
    shifted: list[parsemod.Line] = [parsemod.Line(off, fam.separator, "separator")]
    own: dict[int, parsemod.Line] = {}
    for sl in cmds:
        parent = sl.ctx[-1] if sl.ctx else None
        ln = _line_of(sl, sl.no, parent, len(sl.ctx), fam.indent)
        own[sl.no] = ln
        shifted.append(dataclasses.replace(ln, no=off + sl.no, parent=(off + parent) if parent else None))
    merged = parsemod.Parsed(b.family, [*b.parsed.lines, *shifted])
    g = graphmod.build(merged, kb, b.profile, b.device)
    nodes: dict[int, list[str]] = defaultdict(list)
    for st in g.graph.get("statements") or []:
        if st.line.no > off:
            nodes[st.line.no - off].extend(st.nodes)
    return _Merged(g, dict(nodes), own)


# ---------------------------------------------------------------- 3. 模拟执行（包装 change._Sim，记录每一行的来源）


class _Sim(change._Sim):
    """在 change._Sim 的基础上：每个行树节点记录来源（基线行号 / 脚本行号）与解析行，执行后直接构造解析结果；
    对象与引用按计数增量维护（不必每一步遍历整棵树）。"""

    def __init__(self, p: change._Planner, script_lines: dict[int, parsemod.Line]):
        # 与 change._Sim.__init__ 相同的建树逻辑，另记来源
        self.p, self.kb = p, p.kb
        self.idx = card_index(p.kb, p.family)
        self.root = change._Entry("")
        self.issues: list[dict[str, Any]] = []
        self.violations: list[dict[str, Any]] = []
        self.script_lines = script_lines
        entries: dict[int, change._Entry] = {}
        clinks: dict[str, set[str]] = defaultdict(set)
        for lk in p.clinks:
            clinks[lk.src].update(p.cids_c(lk.dst))
        for st in p.cur.graph.get("statements", []):
            ln = st.line
            if ln.kind not in ("command", "raw", "unknown") or (ln.card or "").startswith("@"):
                continue
            card = p.kb.cards.get(str(ln.card)) if ln.card else None
            cids = {c for n in st.nodes for c in p.cids_c(n)}
            if any(p.cur.nodes.get(n, {}).get("kind") == "ext" for n in st.nodes):
                cids |= {f"ext:{n}" for n in st.nodes}
            e = change._Entry(
                ln.text,
                ln.card,
                ln.values(),
                cids,
                {c for c in cids if p.cid_kind.get(c) == "object"},
                {c for n in st.nodes for c in clinks.get(n, set())},
                str(card.enters_view) if card is not None and card.enters_view else "",
            )
            e.src = ("base", ln.no)  # type: ignore[attr-defined]
            e.line = ln  # type: ignore[attr-defined]
            entries[ln.no] = e
            parent = entries.get(ln.parent) if ln.parent else None
            (parent or self.root).children.append(e)
        self.objs: Counter[str] = Counter()
        self.refs: Counter[str] = Counter()
        for e in self._all():
            self._count(e, 1)

    def _count(self, e: change._Entry, sign: int) -> None:
        for c in e.objs:
            self.objs[c] += sign
        for r in e.refs:
            self.refs[r] += sign

    def _count_tree(self, e: change._Entry, sign: int, skip: set[int] | None = None) -> None:
        stack = [e]
        while stack:
            x = stack.pop()
            if skip and id(x) in skip:
                continue
            self._count(x, sign)
            stack.extend(x.children)

    def block(self, ctx: list[change.CtxLine]) -> tuple[change._Entry, str]:
        cur, view = self.root, self.p.fam.root_view
        for c in ctx:
            hit = next(
                (
                    e
                    for e in cur.children
                    if (c.obj and c.obj in e.objs and e.view)
                    or (not c.obj and _WS.sub(" ", e.text).lower() == _WS.sub(" ", c.text).lower())
                ),
                None,
            )
            if hit is None:
                m = parsemod.match_line(self.idx, view, c.text)
                hit = change._Entry(
                    c.text, m[0].id if m else None, m[1].all_values() if m else {}, {c.obj} - {""}, {c.obj} - {""}
                )
                hit.view = c.view
                hit.src = ("ctx", None)  # type: ignore[attr-defined]
                hit.line = parsemod.Line(  # type: ignore[attr-defined]
                    0, c.text, "command", "", view, m[0].id if m else None, m[1] if m else None
                )
                cur.children.append(hit)
                self._count(hit, 1)
            cur, view = hit, c.view or view
        return cur, view

    def step(self, op: change.Op) -> dict[str, Any]:
        """执行一条命令，返回这一步的结果：removed（被取消 / 覆盖的行）、side（被副作用删除的行）、missing、still。"""
        blk, view = self.block(op.context)
        if op.opens and op.obj and not op.negative and any(op.obj in e.objs and e.view for e in blk.children):
            return {"enter": True, "removed": [], "side": [], "missing": [], "still": [], "block": blk}
        snap = list(blk.children)
        n_issues = len(self.issues)
        new: change._Entry | None = None
        if op.negative:
            self._undo(op, blk, view)
        else:
            self._set(op, blk, view)
            new = blk.children[-1]
            new.src = ("script", op.id)  # type: ignore[attr-defined]
            new.line = self.script_lines.get(op.id)  # type: ignore[attr-defined]
        main_ids = {id(x) for x in blk.children}
        removed = [e for e in snap if id(e) not in main_ids]
        after_main = list(blk.children)
        # 重复下发与现有配置完全相同的命令不会触发副作用（设备上没有变化）
        same = any(_WS.sub(" ", e.text).lower() == _WS.sub(" ", op.text).lower() for e in removed)
        if not same:
            self._side_effect(op, blk)
        final_ids = {id(x) for x in blk.children}
        side = [e for e in after_main if id(e) not in final_ids]
        gone_before = {c for e in removed for c in e.objs} | {c for e in side for c in e.objs}
        if new is not None:
            moved = {id(x) for x in new.children}
            for e in removed:
                self._count_tree(e, -1, moved)
            self._count(new, 1)
        else:
            for e in removed:
                self._count_tree(e, -1)
        for e in side:
            self._count_tree(e, -1)
        missing: list[str] = []
        still: list[str] = []
        if not op.negative:
            missing = sorted(r for r in op.refs if self.objs[r] <= 0)
        else:
            gone = {c for c in gone_before if self.objs[c] <= 0}
            still = sorted(r for r in gone if self.refs[r] > 0)
        issues = self.issues[n_issues:]
        return {
            "enter": False,
            "removed": removed,
            "side": side,
            "missing": missing,
            "still": still,
            "issues": issues,
            "block": blk,
        }

    def parsed(self) -> tuple[parsemod.Parsed, dict[int, tuple[str, int | None]]] | None:
        """执行后的配置：直接把行树写成解析结果（行号重排）。返回 (解析结果, 新行号 → 来源)；有行缺少解析信息时返回 None。"""
        indent = self.p.fam.indent
        lines: list[parsemod.Line] = []
        prov: dict[int, tuple[str, int | None]] = {}

        def walk(e: change._Entry, depth: int, parent: int | None) -> bool:
            for c in e.children:
                src = getattr(c, "line", None)
                if src is None:
                    return False
                no = len(lines) + 1
                lead = " " * (indent * depth)
                lines.append(dataclasses.replace(src, no=no, raw=lead + c.text, indent=lead, parent=parent, fmt=None))
                prov[no] = getattr(c, "src", ("ctx", None))
                if not walk(c, depth + 1, no):
                    return False
            return True

        if not walk(self.root, 0, None):
            return None
        return parsemod.Parsed(self.p.family, lines), prov


# ---------------------------------------------------------------- 命令 → Op


@dataclass
class _Ctx:
    kb: KnowledgeBase
    base: Baseline
    lines: list[SLine]
    cmds: list[SLine]
    merged: _Merged
    planner: change._Planner
    ops: dict[int, change.Op]  # 脚本行号 → Op（命令行）
    extra: dict[int, change.Op]  # 未识别 / 功能域外 / 视图错误的行（只参与重排）
    pure: set[int] = field(default_factory=set)  # 只是进入已有对象视图的行（重排时随子命令重新写出，不单独排序）


def _cids(p: change._Planner, nodes: list[str]) -> list[str]:
    out: list[str] = []
    for n in nodes:
        for c in p.cids_t(n):
            if c not in out:
                out.append(c)
    return out


def _build(text: str, base: Baseline, kb: KnowledgeBase) -> _Ctx:
    lines = track(text, kb, base.family)
    cmds = [sl for sl in lines if sl.kind == "command"]
    merged = _merge(base, cmds, kb)
    p = change._Planner(base.graph, merged.graph, kb)
    links_from: dict[str, list[Any]] = defaultdict(list)
    for lk in p.tlinks:
        links_from[lk.src].append(lk)
    m = merged.graph
    explicit_objs = {
        c
        for n, d in m.nodes(data=True)
        if d.get("kind") == "object" and d.get("lines") and d.get("origin") != "derived"
        for c in p.cids_t(n)
    }
    base_objs = {c for c, it in p.ca.items.items() if it.kind == "object"}
    by_no = {sl.no: sl for sl in lines}
    obj_of: dict[int, str] = {}
    ops: dict[int, change.Op] = {}
    for i, sl in enumerate(cmds):
        nodes = merged.nodes.get(sl.no, [])
        cids = _cids(p, nodes)
        objs = [c for c in cids if p.cid_kind.get(c) == "object"]
        if sl.enters:
            obj_of[sl.no] = change._deepest(objs)
        ctx = [change.CtxLine(by_no[f].text, str(by_no[f].enters or ""), obj_of.get(f, "")) for f in sl.ctx]
        refs: set[str] = set()
        notes: dict[str, Any] = {}
        for n in nodes:
            for lk in links_from.get(n, []):
                for c in p.cids_t(lk.dst):
                    if c in explicit_objs and c not in cids:
                        refs.add(c)
                        notes.setdefault(c, lk.note)
        negative = sl.negated and _is_removal(p, sl, cids)
        op = change.Op(
            id=sl.no,
            action="delete" if negative else "add",
            text=sl.text,
            context=ctx,
            view=sl.view,
            rank=(0, float(i)),
            card=sl.card,
            opens=sl.enters,
            obj=obj_of.get(sl.no, ""),
            target_nodes=list(nodes),
            cids=set() if negative else set(cids),
            creates=set() if negative else {c for c in objs if c not in base_objs},
            refs=set() if negative else refs,
            subject=change._deepest(cids) if cids else (ctx[-1].obj if ctx else ""),
        )
        op.lines_target = [sl.no]
        op.after = {}
        op.notes = [f"ref:{c}:{json.dumps(v, ensure_ascii=False)}" for c, v in notes.items() if v]  # 三语说明
        ops[sl.no] = op
    extra: dict[int, change.Op] = {}
    for i, sl in enumerate(lines):
        if sl.kind in ("unknown", "raw", "wrong_view", "comment"):
            ctx = [change.CtxLine(by_no[f].text, str(by_no[f].enters or ""), obj_of.get(f, "")) for f in sl.ctx]
            extra[sl.no] = change.Op(sl.no, "add", sl.text, ctx, sl.view, (0, float(i)))
    parents = {f for sl in lines for f in sl.ctx}
    pure = {no for no, op in ops.items() if op.opens and op.obj and not op.creates and no in parents}
    return _Ctx(kb, base, lines, cmds, merged, p, ops, extra, pure)


def _is_removal(p: change._Planner, sl: SLine, cids: list[str]) -> bool:
    """取消形式的命令：删除基线中的配置（undo ip address …）还是设置为取消状态（undo shutdown，设备配置里也写成这一行）。
    命令卡的整条语法只有关键字（没有参数）、且对应的是属性时，按设置处理。"""
    card = p.kb.cards.get(str(sl.card))
    if card is None:
        return True
    bare = not card.params
    attrs = [c for c in cids if p.cid_kind.get(c) == "attr"]
    return not (bare and attrs and not card.enters_view)


# ---------------------------------------------------------------- 5. 按依赖重排


def constraints(cx: _Ctx) -> dict[int, dict[int, dict[str, Any]]]:
    """after[b][a] = 原因：命令 b 必须排在命令 a 之后（行号）。"""
    p = cx.planner
    ops = cx.ops
    after: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)

    def need(a: int | None, b: int | None, kind: str, node: str = "", note: Any = "") -> None:
        if a is None or b is None or a == b:
            return
        after[b].setdefault(a, {"kind": kind, "node": node, "note": note})

    creates: dict[str, int] = {}
    for no, op in ops.items():
        for c in op.creates:
            creates.setdefault(c, no)
    line_of = {sl.no: sl for sl in cx.lines}
    for no, op in ops.items():
        sl = line_of[no]
        if sl.ctx:
            need(sl.ctx[-1], no, "contains", op.context[-1].obj if op.context else "")
        for cl in op.context:
            if cl.obj:
                need(creates.get(cl.obj), no, "contains", cl.obj)
        notes = {x.split(":", 2)[1]: json.loads(x.split(":", 2)[2]) for x in op.notes if x.startswith("ref:")}
        for r in op.refs:
            need(creates.get(r), no, "reference", r, notes.get(r, ""))
    # 删除对象：引用它的配置先删除或改为引用别的对象
    negs = {no: op for no, op in ops.items() if op.negative}
    if negs:
        gone_by: dict[str, int] = {}
        for no, op in negs.items():
            for c in _cids(p, op.target_nodes):
                if p.cid_kind.get(c) == "object":
                    gone_by.setdefault(c, no)
        handlers: dict[str, list[int]] = defaultdict(list)
        for no, op in ops.items():
            cs = _cids(p, op.target_nodes) if op.negative else list(op.cids)
            for c in cs:
                handlers[c].append(no)
        for lk in p.clinks:
            for y in p.cids_c(lk.dst):
                d = gone_by.get(y)
                if d is None:
                    continue
                for a in p.cids_c(lk.src):
                    anc = a
                    while True:
                        for h in handlers.get(anc, []):
                            if h != d:
                                need(h, d, "referenced_by", a, lk.note)
                        if "/" not in anc:
                            break
                        anc = anc.rsplit("/", 1)[0]
    # 副作用：触发命令之后再配置会被它删除的值
    for src, dst, note in p.side_rules:
        trig = [
            (no, op)
            for no, op in ops.items()
            if any(cx.merged.graph.nodes[n].get("schema") == src for n in op.target_nodes if n in cx.merged.graph)
        ]
        for tno, top in trig:
            owner = top.context[-1].obj if top.context else ""
            for no, op in ops.items():
                if no == tno or op.negative:
                    continue
                for n in op.target_nodes:
                    s = str(cx.merged.graph.nodes[n].get("schema") or "") if n in cx.merged.graph else ""
                    if (s == dst or s.startswith(dst + ".")) and any(
                        not owner or c.startswith(owner + "/") for c in p.cids_t(n)
                    ):
                        need(tno, no, "side_effect", next(iter(p.cids_t(n)), n), note)
                        break
    # 同一属性 / 同一行的多条命令保持原顺序（先取消再配置、先配置再取消的含义不同）
    groups: dict[str, list[int]] = defaultdict(list)
    for no, op in sorted(ops.items()):
        keys = {c for c in _cids(p, op.target_nodes) if p.cid_kind.get(c) == "attr"}
        keys.add("text:" + "/".join(c.key for c in op.context) + "|" + _WS.sub(" ", op.text.lower()))
        if op.opens and op.obj:
            keys.add(op.obj)
        for k in keys:
            groups[k].append(no)
    for k, nos in groups.items():
        for i_, j_ in zip(nos, nos[1:], strict=False):
            need(i_, j_, "same_target", k if not k.startswith("text:") else "")
    # 未识别等行：跟在原来前面那条命令之后
    prev: int | None = None
    order = sorted([*ops, *cx.extra])
    for no in order:
        if no in cx.extra and prev is not None:
            need(prev, no, "anchor")
        if no in ops:
            prev = no
    return after


def _lis_keep(seq: list[int]) -> set[int]:
    """新顺序中原序号的最长递增子序列：这些命令没有移动，其余的算作移动。"""
    import bisect

    tails: list[int] = []
    tails_idx: list[int] = []
    prev = [-1] * len(seq)
    for i, v in enumerate(seq):
        j = bisect.bisect_left(tails, v)
        if j == len(tails):
            tails.append(v)
            tails_idx.append(i)
        else:
            tails[j] = v
            tails_idx[j] = i
        prev[i] = tails_idx[j - 1] if j else -1
    keep: set[int] = set()
    k = tails_idx[-1] if tails_idx else -1
    while k >= 0:
        keep.add(seq[k])
        k = prev[k]
    return keep


def reorder_ops(cx: _Ctx) -> tuple[list[int], dict[int, dict[int, dict[str, Any]]], list[dict[str, Any]]]:
    """满足约束的顺序：约束之外保持原顺序；刚进入的视图里能排的命令优先接着排（少进出视图，块尽量不拆开）。"""
    after = constraints(cx)
    allops = {n: op for n, op in {**cx.ops, **cx.extra}.items() if n not in cx.pure}
    ctx_of = {sl.no: sl.ctx for sl in cx.lines}
    warnings: list[dict[str, Any]] = []
    preds: dict[int, set[int]] = {n: set(after.get(n, {})) & set(allops) for n in allops}
    done: set[int] = set()
    order: list[int] = []
    stack: list[int] = []

    def common(n: int) -> int:
        c = ctx_of.get(n, [])
        k = 0
        while k < len(c) and k < len(stack) and c[k] == stack[k]:
            k += 1
        return k if k == len(c) or k == len(stack) else 0

    while len(order) < len(allops):
        ready = [n for n in allops if n not in done and not (preds[n] - done)]
        if not ready:
            rest = {n for n in allops if n not in done}
            dg = nx.DiGraph([(a, b) for b in rest for a in preds[b] if a in rest])
            cyc = nx.find_cycle(dg)
            a, b = min(
                ((x, y) for x, y, *_ in cyc),
                key=lambda e: (
                    REORDER_PRIORITY.index(after[e[1]][e[0]]["kind"])
                    if after[e[1]][e[0]]["kind"] in REORDER_PRIORITY
                    else len(REORDER_PRIORITY)
                ),
            )
            preds[b].discard(a)
            after[b].pop(a, None)
            warnings.append({"key": "script_check.reorder.cycle", "params": {"a": a, "b": b}})
            continue
        n = min(ready, key=lambda x: (-common(x), x))
        order.append(n)
        done.add(n)
        op = allops[n]
        stack = [*ctx_of.get(n, []), *([n] if op.opens and not op.negative else [])]
    return order, after, warnings


def _script_rows(ops: list[change.Op], kb: KnowledgeBase, family: str) -> list[dict[str, Any]]:
    """同 change.script_rows（按视图分块：开头 / 进入视图 / 命令 / 退出 / 结尾），退出命令表只读一次。"""
    from lmesh.core import canon

    rules = change.load_rules(kb, family)
    exits = canon.load_style(kb, family)["exits"]

    def word(view: str) -> str:
        return exits.get(view) or rules["exit"]

    rows: list[dict[str, Any]] = [{"kind": "frame", "depth": 0, "text": t, "op": None} for t in rules["begin"]]
    stack: list[change.CtxLine] = []
    for op in ops:
        ctx = op.context
        common = 0
        while common < len(stack) and common < len(ctx) and stack[common].key == ctx[common].key:
            common += 1
        for i in reversed(range(common, len(stack))):
            rows.append({"kind": "quit", "depth": i, "text": word(stack[i].view), "op": None})
        stack = stack[:common]
        for i in range(common, len(ctx)):
            rows.append({"kind": "enter", "depth": i, "text": ctx[i].text, "op": None})
            stack.append(ctx[i])
        rows.append({"kind": "cmd", "depth": len(stack), "text": op.text, "op": op.id})
        if op.opens and not op.negative:
            stack.append(op.as_ctx())
    for i in reversed(range(len(stack))):
        rows.append({"kind": "quit", "depth": i, "text": word(stack[i].view), "op": None})
    rows += [{"kind": "frame", "depth": 0, "text": t, "op": None} for t in rules["finish"]]
    return rows


def reorder(cx: _Ctx, namer: Any = None, lang: str = "zh-CN") -> dict[str, Any]:
    """按依赖重排脚本：新脚本、每条命令的新旧行号、移动的命令与原因。"""
    order, after, warnings = reorder_ops(cx)
    allops = {n: op for n, op in {**cx.ops, **cx.extra}.items() if n not in cx.pure}
    seq = [allops[n] for n in order]
    rows = _script_rows(seq, cx.kb, cx.base.family)
    indent = cx.kb.families[cx.base.family].indent
    text_lines: list[str] = []
    new_line: dict[int, int] = {}
    for r in rows:
        pad = "" if r["kind"] == "frame" else " " * (indent * r["depth"])
        text_lines.append(pad + r["text"])
        if r["op"] is not None:
            new_line[r["op"]] = len(text_lines)
    keep = _lis_keep(order)
    pos = {n: i for i, n in enumerate(order)}
    moves: list[dict[str, Any]] = []

    def label(node: str) -> str:
        return namer(node) if namer and node else node

    for n in order:
        if n in keep:
            continue
        reasons: list[dict[str, Any]] = []
        for a, why in sorted(after.get(n, {}).items()):
            if a > n:  # 原来排在后面的命令现在必须在它之前
                reasons.append(
                    {"dir": "after", "line": a, "new_line": new_line.get(a), **why, "label": label(why["node"])}
                )
        for b, preds in after.items():
            if n in preds and b < n:  # 原来排在前面的命令依赖它
                why = preds[n]
                reasons.append(
                    {"dir": "before", "line": b, "new_line": new_line.get(b), **why, "label": label(why["node"])}
                )
        for rr in reasons:
            rr["note"] = _note(rr.get("note"), lang)
            rr["text"] = reason_text(rr, lang)
        moves.append(
            {
                "line": n,
                "new_line": new_line.get(n),
                "text": allops[n].text,
                "from_index": sorted(allops).index(n),
                "to_index": pos[n],
                "reasons": reasons,
            }
        )
    mapping = [{"line": n, "new_line": new_line.get(n), "moved": n not in keep} for n in order]
    return {
        "script": "\n".join(text_lines) + "\n",
        "moves": moves,
        "mapping": mapping,
        "changed": bool(moves),
        "warnings": warnings,
    }


def _note(v: Any, lang: str) -> str:
    """依赖 / 副作用的说明：知识库里可能是 {zh-CN, en, pt-BR}，按语言取（没有时取中文）。"""
    if isinstance(v, dict):
        return str(v.get(lang) or v.get(i18n.DEFAULT) or next(iter(v.values()), ""))
    return "" if v is None else str(v)


def reason_text(r: dict[str, Any], lang: str) -> str:
    key = f"script_check.reason.{r['kind']}.{r['dir']}"
    return i18n.t(key, lang, line=r["line"], label=r.get("label") or r.get("node") or "", note=r.get("note") or "")


# ---------------------------------------------------------------- 检查


class _Issues:
    def __init__(self, lang: str):
        self.lang = lang
        self.items: list[dict[str, Any]] = []

    def add(
        self,
        line: int | None,
        severity: str,
        category: str,
        code: str,
        lines: list[int] | None = None,
        source: str = "code",
        text: str | None = None,
        **params: Any,
    ) -> dict[str, Any]:
        key = f"script_check.issue.{code}"
        item = {
            "id": f"i{len(self.items) + 1}",
            "line": line,
            "lines": sorted(set(lines or ([] if line is None else [line]))),
            "severity": severity,
            "category": category,
            "code": code,
            "source": source,
            "message": {"key": key, "params": params},
            "text": text if text is not None else i18n.t(key, self.lang, **params),
        }
        for k in ("rule", "node"):
            if k in params:
                item[k] = params[k]
        self.items.append(item)
        return item


def _text_of(e: Any) -> str:
    return str(getattr(e, "text", ""))


def _src(e: Any) -> tuple[str, int | None]:
    return getattr(e, "src", ("ctx", None))  # type: ignore[no-any-return]


def check_text(
    text: str,
    kb: KnowledgeBase,
    base: Baseline | None,
    kind: str = "change",
    order: bool = True,
    profile: str | None = None,
    rules_dir: Path | None = None,
    namer: Any = None,
    lang: str = "zh-CN",
    with_reorder: bool = True,
    ai: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """检查一份脚本。base：基线（变更脚本必须有）；ai：{settings, rules: [规则编号]}，为 None 时不调用 AI。"""
    t0 = time.monotonic()
    if kind not in KINDS:
        raise ScriptCheckError("script_check.bad_kind", allowed=", ".join(KINDS))
    if not text.strip():
        raise ScriptCheckError("script_check.empty")
    rules = _rules(kb, rules_dir)
    lang = i18n.normalize(lang)
    if kind == "change":
        if base is None:
            raise ScriptCheckError("script_check.need_baseline")
        out = _check_change(text, kb, base, order, rules, namer, lang, with_reorder)
    else:
        out = _check_full(text, kb, base, profile, rules, namer, lang)
    if ai is not None:
        from lmesh.core import script_check_ai

        out["ai"] = script_check_ai.run(out, text, kb, rules, ai, lang)
    else:
        out["ai"] = {"enabled": False}
    out["issues"].sort(key=lambda x: (x["line"] or 10**9, -_SEV_RANK[x["severity"]], x["id"]))
    out["summary"] = _summary(out)
    out["ms"] = int((time.monotonic() - t0) * 1000)
    return out


def _summary(out: dict[str, Any]) -> dict[str, Any]:
    by_sev = dict.fromkeys(SEVERITIES, 0)
    by_cat: dict[str, int] = {}
    for it in out["issues"]:
        by_sev[it["severity"]] += 1
        by_cat[it["category"]] = by_cat.get(it["category"], 0) + 1
    kinds = Counter(x for x in out["line_kinds"])
    return {
        "errors": by_sev["error"],
        "warnings": by_sev["warning"],
        "infos": by_sev["info"],
        "by_category": dict(sorted(by_cat.items())),
        "lines": len(out["line_kinds"]),
        "commands": kinds.get("command", 0),
        "unknown": kinds.get("unknown", 0) + kinds.get("wrong_view", 0),
        "ok": by_sev["error"] == 0,
    }


def _parse_issues(lines: list[SLine], iss: _Issues, family: str) -> None:
    for sl in lines:
        if sl.kind == "unknown":
            iss.add(sl.no, "error", "parse", "unknown_command", cmd=sl.text, view=sl.view)
        elif sl.kind == "raw":
            iss.add(sl.no, "info", "parse", "out_of_scope", cmd=sl.text)
        elif sl.kind == "wrong_view":
            iss.add(sl.no, "error", "view", "wrong_view", view=sl.view, belongs=str(sl.belongs))
        elif sl.kind == "command" and sl.implicit_from and family.startswith("huawei"):
            iss.add(sl.no, "info", "view", "implicit_exit", view=sl.view, previous=sl.implicit_from)


def _findings(
    g: nx.MultiDiGraph,
    kb: KnowledgeBase,
    rules: list[rulesmod.Rule],
    lang: str,
    base_keys: set[tuple[str, str]] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    r = checks.check(g, kb, rules)
    new = [f for f in r["findings"] if base_keys is None or (f["rule"], f["node"]) not in base_keys]
    for f in new:
        f["text"] = checks.render_text(f["message"], lang, r["texts"])
        f["suggestion_text"] = checks.render_text(f["suggestion"], lang, r["texts"])
    return r, new


def _conflicts(g: nx.MultiDiGraph, script_line: Any, iss: _Issues) -> None:
    """新内容与现网冲突：同一 VRF 内接口地址重复、RD 被另一个 VPN 实例使用。"""
    import ipaddress

    from lmesh.core import guard
    from lmesh.core.objtable import GraphIndex

    ix = GraphIndex(g)
    seen: dict[tuple[str, str], tuple[str, list[int]]] = {}
    for _itf, name, scope, addr, lines in guard._addresses(g, ix):
        try:
            ip = str(ipaddress.ip_interface(addr.replace(" ", "/")).ip)
        except ValueError:
            ip = addr.split()[0] if addr else addr
        k = (scope, ip)
        if k in seen:
            other, olines = seen[k]
            mine = [script_line(n) for n in lines if script_line(n)]
            theirs = [script_line(n) for n in olines if script_line(n)]
            at = (mine or theirs or [None])[0]
            if at is not None:
                iss.add(at, "error", "conflict", "duplicate_ip", address=ip, interface=name, other=other)
        else:
            seen[k] = (name, lines)
    rds: dict[str, tuple[str, list[int]]] = {}
    for vrf, rd, lines in guard._rds(g, ix):
        if rd in rds and rds[rd][0] != vrf:
            other, olines = rds[rd]
            at = next((script_line(n) for n in [*lines, *olines] if script_line(n)), None)
            if at is not None:
                iss.add(at, "error", "conflict", "duplicate_rd", rd=rd, vrf=vrf, other=other)
        else:
            rds.setdefault(rd, (vrf, lines))


def _check_change(
    text: str,
    kb: KnowledgeBase,
    base: Baseline,
    order: bool,
    rules: list[rulesmod.Rule],
    namer: Any,
    lang: str,
    with_reorder: bool,
) -> dict[str, Any]:
    cx = _build(text, base, kb)
    p = cx.planner
    iss = _Issues(lang)
    _parse_issues(cx.lines, iss, base.family)

    def label(c: str) -> str:
        return namer(c) if namer and c else c

    # 执行顺序：开启顺序核查时按书写顺序，否则按依赖重排后的顺序
    seq = sorted(cx.ops) if order else [n for n in reorder_ops(cx)[0] if n in cx.ops]
    creators: dict[str, int] = {}
    for no, op in cx.ops.items():
        for c in op.creates:
            creators.setdefault(c, no)
    pos = {n: i for i, n in enumerate(seq)}
    sim = _Sim(p, cx.merged.lines)
    removed_rows: list[dict[str, Any]] = []
    pending_side: list[tuple[int, Any, Any, str, set[str], Any]] = []
    violations = 0
    dst_of: dict[str, list[tuple[str, Any]]] = defaultdict(list)
    for s_, d_, note_ in p.side_rules:
        dst_of[s_].append((d_, note_))
    for no in seq:
        op = cx.ops[no]
        st = sim.step(op)
        if st["enter"]:
            continue
        for it in st["issues"]:
            if it["kind"] == "undo_no_match":
                iss.add(no, "warning", "undo", "undo_no_match")
            elif it["kind"] == "unparsable":
                iss.add(no, "error", "parse", "unparsable", cmd=op.text)
        for e in st["removed"]:
            kind_, at = _src(e)
            row: dict[str, Any] = {"how": "undo" if op.negative else "override", "by": no, "text": _text_of(e)}
            if kind_ == "base":
                row["base_line"] = at
                removed_rows.append(row)
                if not op.negative:
                    same = _WS.sub(" ", _text_of(e)).lower() == _WS.sub(" ", op.text).lower()
                    code = "unchanged" if same else "override"
                    iss.add(no, "info", "override", code, base_line=at, old=_text_of(e))
            elif kind_ == "script" and not op.negative and at is not None:
                iss.add(at, "warning", "override", "overridden_in_script", lines=[at, no], by=no)
        if st["side"]:
            schemas = {str(cx.merged.graph.nodes[n].get("schema")) for n in op.target_nodes if n in cx.merged.graph}
            note = _note(next((nt for s_ in schemas for _, nt in dst_of.get(s_, [])), ""), lang)
            dsts = {d_ for s_ in schemas for d_, _ in dst_of.get(s_, [])}
            for e in st["side"]:
                kind_, at = _src(e)
                if kind_ == "script" and at is not None:
                    violations += 1 if order else 0
                    if order:
                        iss.add(at, "error", "order", "side_effect_lost", lines=[at, no], by=no, note=note)
                elif kind_ == "base":
                    removed_rows.append({"how": "side_effect", "by": no, "text": _text_of(e), "base_line": at})
                    pending_side.append((no, at, e, note, dsts, st["block"]))
        if order:
            for ref in st["missing"]:
                creator = creators.get(ref)
                if creator is not None and pos.get(creator, -1) > pos[no]:
                    violations += 1
                    iss.add(
                        no,
                        "error",
                        "order",
                        "order_missing_reference",
                        lines=[no, creator],
                        by=creator,
                        label=label(ref),
                    )
            for r in st["still"]:
                later = [
                    h for h, hop in cx.ops.items() if pos.get(h, -1) > pos[no] and (h in constraints_handlers(cx, r))
                ]
                if later:
                    violations += 1
                    iss.add(
                        no,
                        "error",
                        "order",
                        "order_still_referenced",
                        lines=[no, later[0]],
                        by=later[0],
                        label=label(r),
                    )
    # 副作用删除的基线行：后面有没有重新配置
    for no, at, e, note, dsts, blk in pending_side:
        redo = None
        if dsts:
            for x in blk.children:
                kind_, xat = _src(x)
                if kind_ == "script" and any(str(p.cid_schema.get(c, "")).startswith(tuple(dsts)) for c in x.cids):
                    redo = xat
                    break
        if redo is not None:
            iss.add(
                no,
                "info",
                "side_effect",
                "side_effect_ok",
                lines=[no, redo],
                base_line=at,
                old=_text_of(e),
                by=redo,
                note=note,
            )
        else:
            iss.add(no, "warning", "side_effect", "side_effect", base_line=at, old=_text_of(e), note=note)
    # 执行后的配置：建图、检查规则、冲突
    built = sim.parsed()
    prov: dict[int, tuple[str, int | None]]
    if built is None:
        from lmesh.core import analysis

        res = analysis.parse_text(sim.text(), kb, base.profile)
        final_parsed, prov = res.parsed, {}
    else:
        final_parsed, prov = built
    fg = graphmod.build(final_parsed, kb, base.profile, base.device)

    def script_line(n: int) -> int | None:
        s = prov.get(n)
        return s[1] if s and s[0] == "script" else None

    def base_line(n: int) -> int | None:
        s = prov.get(n)
        return s[1] if s and s[0] == "base" else None

    bchk = _base_check(base, kb, rules)
    base_keys = {(f["rule"], f["node"]) for f in bchk["findings"]}
    fchk, new = _findings(fg, kb, rules, lang, base_keys)
    findings_new: list[dict[str, Any]] = []
    for f in new:
        sl = sorted({x for n in f["lines"] if (x := script_line(n))})
        bl = sorted({x for n in f["lines"] if (x := base_line(n))})
        if not sl:  # 发现落在基线行上（例如脚本的副作用删掉了地址）：标到改动了同一对象的脚本行
            sl = sorted(
                no
                for no, nodes in cx.merged.nodes.items()
                if any(nd == f["node"] or nd.startswith(f["node"] + "/") for nd in nodes)
            )[:1]
        findings_new.append(_finding_row(f, sl, bl))
        if sl:
            iss.add(
                sl[0],
                f["severity"],
                "rule",
                "rule",
                lines=sl,
                text=f["text"],
                rule=f["rule"],
                node=f["node"],
            )["suggestion"] = f["suggestion_text"]
    fkeys = {(f["rule"], f["node"]) for f in fchk["findings"]}
    fixed = [
        _finding_row({**f, "text": checks.render_text(f["message"], lang, bchk["texts"])}, [], list(f["lines"]))
        for f in bchk["findings"]
        if (f["rule"], f["node"]) not in fkeys
    ]
    _conflicts(fg, script_line, iss)
    script_set = {v[1] for v in prov.values() if v[0] == "script"}
    out: dict[str, Any] = {
        "kind": "change",
        "baseline": base.info(),
        "line_kinds": [sl.kind for sl in cx.lines],
        "issues": iss.items,
        "order": {"enabled": order, "applicable": True, "violations": violations},
        "result": {
            "final_lines": len(final_parsed.lines),
            "lines_added": len(script_set),
            "lines_removed": sum(1 for r in removed_rows if r["how"] == "undo"),
            "lines_overridden": sum(1 for r in removed_rows if r["how"] == "override"),
            "side_effect_removed": sum(1 for r in removed_rows if r["how"] == "side_effect"),
            "removed": removed_rows[:300],
            "findings_new": findings_new[:300],
            "findings_fixed": fixed[:300],
            "unknown": sum(1 for sl in cx.lines if sl.kind in ("unknown", "wrong_view")),
        },
    }
    if with_reorder and order and violations:
        out["order"]["reorder"] = reorder(cx, namer, lang)
    out["_final_graph"] = fg
    out["_lines"] = cx.lines
    out["_script_line"] = script_line
    out["_merged_nodes"] = cx.merged.nodes
    return out


def constraints_handlers(cx: _Ctx, obj: str) -> set[int]:
    """删除对象 obj 时能消除引用的命令（取消或改写引用方）。"""
    p = cx.planner
    refs = {a for lk in p.clinks if obj in p.cids_c(lk.dst) for a in p.cids_c(lk.src)}
    out: set[int] = set()
    for no, op in cx.ops.items():
        cs = _cids(p, op.target_nodes) if op.negative else list(op.cids)
        if any(c == a or a.startswith(c + "/") for c in cs for a in refs):
            out.add(no)
    return out


def _finding_row(f: dict[str, Any], script_lines: list[int], base_lines: list[int]) -> dict[str, Any]:
    return {
        "rule": f["rule"],
        "severity": f["severity"],
        "node": f["node"],
        "domain": f.get("domain", ""),
        "text": f.get("text", ""),
        "script_lines": script_lines,
        "base_lines": base_lines,
    }


def _check_full(
    text: str,
    kb: KnowledgeBase,
    base: Baseline | None,
    profile: str | None,
    rules: list[rulesmod.Rule],
    namer: Any,
    lang: str,
) -> dict[str, Any]:
    from lmesh.core import analysis

    use = profile or (base.profile if base else None)
    try:
        res = analysis.parse_text(text, kb, use)
    except analysis.AnalysisError as e:
        raise ScriptCheckError(str(e), profile=use or "") from e
    if base is not None and kb.profiles[res.profile].family != base.family:
        raise ScriptCheckError("script_check.family_mismatch", a=base.family, b=kb.profiles[res.profile].family)
    g = graphmod.build(res.parsed, kb, res.profile, base.device if base else "config")
    iss = _Issues(lang)
    kinds: list[str] = []
    for ln in res.parsed.lines:
        k = ln.kind
        if k == "unknown":
            iss.add(ln.no, "error", "parse", "unknown_command", cmd=ln.text, view=ln.view)
        elif k == "raw":
            pass  # 完整配置里功能域外的行很多（sysname 等），只计数（result.raw），不逐行提示
        kinds.append(k)
    chk, new = _findings(g, kb, rules, lang, None)
    for f in new:
        if f["lines"]:
            iss.add(
                f["lines"][0],
                f["severity"],
                "rule",
                "rule",
                lines=f["lines"],
                text=f["text"],
                rule=f["rule"],
                node=f["node"],
            )["suggestion"] = f["suggestion_text"]
        else:
            iss.add(None, f["severity"], "rule", "rule", text=f["text"], rule=f["rule"], node=f["node"])
    result: dict[str, Any] = {
        "findings_total": len(new),
        "unknown": sum(1 for k in kinds if k == "unknown"),
        "raw": sum(1 for k in kinds if k == "raw"),
        "profile": res.profile,
    }
    if base is not None:
        c = compare.compare(compare.Side(base.graph, base.label or base.device), compare.Side(g, "script"), kb)
        result["compare"] = {
            "equal": c["equal"],
            "summary": c["summary"],
            "diffs": [
                {
                    "kind": d["kind"],
                    "node": d["node"],
                    "label": namer(d["node"]) if namer else d["node"],
                    "a": d.get("a"),
                    "b": d.get("b"),
                }
                for d in c["diffs"][:200]
            ],
        }
    script_line_map = {ln.no: ln.no for ln in res.parsed.lines}
    return {
        "kind": "full",
        "baseline": base.info() if base else None,
        "line_kinds": [_full_kind(k) for k in kinds],
        "issues": iss.items,
        "order": {"enabled": False, "applicable": False, "violations": 0},
        "result": result,
        "_final_graph": g,
        "_script_line": script_line_map.get,
    }


def _full_kind(k: str) -> str:
    return {"end": "session"}.get(k, k)


def public(out: dict[str, Any]) -> dict[str, Any]:
    """去掉内部字段（图、函数）后的结果，供 API / CLI 输出。"""
    return {k: v for k, v in out.items() if not k.startswith("_")}


# ---------------------------------------------------------------- 入口：重排（不检查内容时也可用）


def reorder_text(
    text: str,
    kb: KnowledgeBase,
    base: Baseline,
    namer: Any = None,
    lang: str = "zh-CN",
    recheck: bool = True,
    rules_dir: Path | None = None,
) -> dict[str, Any]:
    """按依赖重排变更脚本；recheck 时对重排前后各检查一次（顺序核查开启），给出顺序错误的变化。"""
    if not text.strip():
        raise ScriptCheckError("script_check.empty")
    cx = _build(text, base, kb)
    r = reorder(cx, namer, i18n.normalize(lang))
    if recheck:
        before = check_text(text, kb, base, "change", True, rules_dir=rules_dir, lang=lang, with_reorder=False)
        after = check_text(r["script"], kb, base, "change", True, rules_dir=rules_dir, lang=lang, with_reorder=False)
        r["before"] = {"summary": before["summary"], "order_violations": before["order"]["violations"]}
        r["after"] = {"summary": after["summary"], "order_violations": after["order"]["violations"]}
    return r
