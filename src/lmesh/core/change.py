"""增量变更脚本（M4-3，REQ-015）：当前配置图 + 目标配置图（同一平台族）→ 下发脚本与回滚脚本。

流程：
    1. 差异：两张图按 compare 的规范化（有效值、键的规范写法）逐节点比较，不做改名识别（改名在设备上就是新建 + 改引用 + 删除）。
       只差在默认值的不下发：一边显式写了默认值、另一边没写，有效值相同，不算差异。
    2. 命令：新增 / 修改的节点交给规范渲染器（core/canon.py，facts 只含这些节点）生成命令，块结构（进入视图的命令）一并得到；
       删除的对象与属性用清理模块（core/cleanup.py）的取消语法渲染，按原配置行的参数生成 undo / no 命令。
       修改默认是新值覆盖；命令卡不允许直接覆盖的（knowledge/change/<平台族>.yaml 的 undo_first）先删除对象再重建；
       属性写在对象入口行上（静态路由的 tag）而要恢复默认时，重写这一行而不是取消整行。
    3. 副作用与互斥：Profile 的 side_effects（以及变更知识中补充的）——src 变化时设备会删除同一对象下的 dst（华为接口绑定 VPN 会删除接口 IP），
       自动补发 dst 并标为高风险；Schema 的 mutex——先撤旧再配新；replace_first——同一父对象下一删一增时先删旧。
    4. 顺序：命令之间按依赖拓扑排序（被引用 / 前置对象先建，删除时先删引用方，对象的子命令在进入它的视图之后），
       没有约束的命令保持规范渲染的顺序（新增与修改在前，删除在后）。每条命令记录排在哪些命令之后、为什么。
    5. 脚本：按视图分块（进入视图的命令、缩进的子命令、退出）；华为 system-view … commit，Cisco configure terminal … end。
    6. 验证：在当前配置上模拟执行脚本（取消命令按命令卡的取消语法匹配要删的行，同一属性的新命令覆盖旧命令，副作用删除 dst，
       删除对象时一并删除它的全部配置行），得到的配置重新解析建图，与目标按有效值对比必须一致、没有新的悬空引用、
       执行过程中不出现“引用了还不存在的对象 / 删除了还被引用的对象”。回滚脚本（目标 → 当前）同样生成并验证。
"""

from __future__ import annotations

import itertools
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from lmesh.core import canon, checks, cleanup, compare, impact
from lmesh.core import graph as graphmod
from lmesh.core import parser as parsemod
from lmesh.core.compare import _Canon, _Canonicalizer, _Schema
from lmesh.core.graph import DEVICE
from lmesh.core.kb import KnowledgeBase, read_yaml
from lmesh.core.kb import syntax as syn

ACTIONS = ("add", "modify", "delete", "side_effect", "mutex")
RISKS = ("low", "medium", "high")
_WS = re.compile(r"\s+")


class ChangeError(ValueError):
    """变更参数错误。key 是文案键；kind 为 param 或 not_found。"""

    def __init__(self, key: str, kind: str = "param", **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.fmt = key, kind, fmt


# ---------------------------------------------------------------- 平台族的下发习惯


def load_rules(kb: KnowledgeBase, family: str) -> dict[str, Any]:
    """knowledge/change/<平台族>.yaml；运行时知识库没有时用程序自带的。"""
    f = Path(kb.root) / "change" / f"{family}.yaml"
    if not f.exists():
        from lmesh import paths

        f = paths.builtin_knowledge_dir() / "change" / f"{family}.yaml"
    data = (read_yaml(f) or {}) if f.exists() else {}
    fam = kb.families[family]
    undo = fam.negative == "undo"
    return {
        "begin": [str(x) for x in (data.get("begin") or (["system-view"] if undo else ["configure terminal"]))],
        "finish": [str(x) for x in (data.get("finish") or (["return"] if undo else ["end"]))],
        "exit": str(data.get("exit") or ("quit" if undo else "exit")),
        "comment": str(data.get("comment") or ("#" if undo else "!")),
        "side_effects": [
            (str(x["from"]), str(x["to"]), str(x.get("note") or ""))
            for x in (data.get("side_effects") or [])
            if isinstance(x, dict) and x.get("from") and x.get("to")
        ],
        "undo_first": {str(x) for x in (data.get("undo_first") or [])},
        "replace_first": {str(x) for x in (data.get("replace_first") or [])},
        "risk_high": [str(x) for x in (data.get("risk_high") or [])],
        "undo_extra": {
            str(k): [str(x) for x in (v if isinstance(v, list) else [v])]
            for k, v in (data.get("undo_extra") or {}).items()
        },
    }


# ---------------------------------------------------------------- 命令


@dataclass(frozen=True)
class CtxLine:
    """进入视图的命令（脚本中的块头）。obj 是它打开的对象（规范编号），按 obj 判断两个块头是否同一视图。"""

    text: str
    view: str
    obj: str = ""

    @property
    def key(self) -> str:
        return self.obj or "text:" + _WS.sub(" ", self.text.strip()).lower()


@dataclass
class Op:
    id: int
    action: str  # add / modify / delete / side_effect / mutex
    text: str
    context: list[CtxLine]
    view: str  # 命令所在的视图
    rank: tuple[int, float]
    card: str | None = None
    opens: str | None = None  # 这条命令进入的视图（新建对象的入口命令）
    obj: str = ""  # 这条命令打开的对象（opens 时）
    target_nodes: list[str] = field(default_factory=list)
    current_nodes: list[str] = field(default_factory=list)
    cids: set[str] = field(default_factory=set)  # 写出的属性 / 对象（规范编号；覆盖判断用）
    creates: set[str] = field(default_factory=set)  # 新建的对象
    removes: set[str] = field(default_factory=set)  # 删除的节点（含子树）
    refs: set[str] = field(default_factory=set)  # 引用的对象
    subject: str = ""  # 说明里的对象（规范编号）
    fallback: bool = False
    fallback_reason: str | None = None
    notes: list[str] = field(default_factory=list)
    lines_current: list[int] = field(default_factory=list)
    lines_target: list[int] = field(default_factory=list)
    after: dict[int, dict[str, Any]] = field(default_factory=dict)  # 前置命令 → 原因
    risk: str = "low"
    risk_reasons: list[str] = field(default_factory=list)

    @property
    def negative(self) -> bool:
        return self.action in ("delete", "mutex") or (self.action == "modify" and bool(self.removes) and not self.cids)

    def as_ctx(self) -> CtxLine:
        return CtxLine(self.text, str(self.opens), self.obj)


def _key_tokens(g: nx.MultiDiGraph, objs: list[str]) -> set[str]:
    """对象键在原配置行中的写法（删除对象时，取消命令写出这些键即可）。"""
    out: set[str] = set()
    for n in objs:
        d = g.nodes[n]
        raw = d.get("raw") if d.get("raw") not in (None, "") else d.get("key")
        vals = raw.values() if isinstance(raw, dict) else [raw]
        out |= {str(v).lower() for v in vals if v not in (None, "", "_")}
    return out


def undo_text(
    card: Any, line: parsemod.Line, negative: str, keys: set[str], extra: list[str] | None = None
) -> tuple[str, str | None]:
    """删除对象的取消命令：在取消语法（命令卡的 undo，加上变更知识 undo_extra 补充的写法）能渲染出的写法中，
    优先选写出了对象全部键的最短写法（undo rule 10，而不是按规则内容删除）；没有时用清理模块的写法（参数最多）。"""
    text, why = cleanup.render_undo_reason(card, line, negative)
    if not keys or card is None:
        return text, why
    original = {w.lower() for w in line.text.split()}
    best: tuple[int, str] | None = None
    for src in [*(extra or []), *([card.undo] if card.undo else [])]:
        try:
            usyn = syn.parse(src)
        except syn.SyntaxErrorKB:
            continue
        for words, kws, _ in itertools.islice(cleanup._expand(usyn.nodes, line.values()), cleanup._MAX_EXPANSIONS):
            low = [w.lower() for w in words]
            if not words or low[0] != negative or not set(kws[1:]) <= original or not keys <= set(low):
                continue
            cand = " ".join(words)
            if syn.match(usyn, cand, card.params) is None:
                continue
            if best is None or len(words) < best[0]:
                best = (len(words), cand)
    return (best[1], None) if best is not None else (text, why)


def _deepest(cids: list[str]) -> str:
    return max(cids, key=lambda c: (c.count("/"), len(c)), default="")


# ---------------------------------------------------------------- 规划


class _Planner:
    def __init__(self, cur: nx.MultiDiGraph, tgt: nx.MultiDiGraph, kb: KnowledgeBase):
        self.cur, self.tgt, self.kb = cur, tgt, kb
        fa = str(cur.graph.get("family") or kb.profiles[str(cur.graph["profile"])].family)
        fb = str(tgt.graph.get("family") or kb.profiles[str(tgt.graph["profile"])].family)
        if fa != fb:
            raise ChangeError("change.family_mismatch", a=fa, b=fb)
        self.family = fa
        self.fam = kb.families[fa]
        self.profile = str(tgt.graph.get("profile"))
        self.rules = load_rules(kb, fa)
        self.sch = _Schema(kb)
        self.ca: _Canon = _Canonicalizer(cur, kb, self.sch).run()
        self.cb: _Canon = _Canonicalizer(tgt, kb, self.sch).run()
        self.cix = checks.Index.of(cur, kb)
        self.tix = checks.Index.of(tgt, kb)
        self.cid_schema = {c: it.schema for c, it in {**self.ca.items, **self.cb.items}.items()}
        self.cid_kind = {c: it.kind for c, it in {**self.ca.items, **self.cb.items}.items()}
        self.tfacts = canon.default_facts(tgt, kb, self.profile, False)
        self.clinks = impact.links(cur, kb)
        self.tlinks = impact.links(tgt, kb)
        self.tlinks_from: dict[str, list[impact.Link]] = defaultdict(list)
        for lk in self.tlinks:
            self.tlinks_from[lk.src].append(lk)
        self.side_rules = [(r.src, r.dst, r.note) for r in kb.resolve_profile(self.profile).side_effects]
        self.side_rules += [r for r in self.rules["side_effects"] if r[:2] not in {x[:2] for x in self.side_rules}]
        self.mutex = {(r.src, r.dst) for r in kb.deps if r.kind == "mutex"}
        self.mutex |= {(b, a) for a, b in self.mutex}
        self.write: set[str] = set()  # 目标图中要写出的节点
        self.side_nodes: set[str] = set()  # 因副作用补发的节点
        self.rewrite: dict[str, int] = {}  # 目标节点 → 需要排在其后的当前行（取消多取值行后补写）
        self.undo_attrs: set[str] = set()  # 当前图中要取消的属性
        self.dels: set[str] = set()  # 当前图中要删除的对象（最上层）
        self.replaced: set[str] = set()  # undo_first：先删后建的对象（规范编号）
        self.unsupported: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        self.ops: list[Op] = []

    # ----- 工具 -----

    def cids_c(self, n: str) -> list[str]:
        return list(self.ca.node_cids.get(n, []))

    def cids_t(self, n: str) -> list[str]:
        return list(self.cb.node_cids.get(n, []))

    def subtree(self, g: nx.MultiDiGraph, n: str) -> list[str]:
        out, stack = [], [n]
        while stack:
            x = stack.pop()
            out.append(x)
            stack.extend(b for _, b, d in g.out_edges(x, data=True) if d.get("kind") == "contains")
        return out

    def target_subtree_facts(self, n: str) -> set[str]:
        return {x for x in self.subtree(self.tgt, n) if x in self.tfacts}

    def owner_cid(self, cid: str) -> str:
        it = self.ca.items.get(cid) or self.cb.items.get(cid)
        if it is None:
            return ""
        return cid if it.kind == "object" else it.parent

    def in_view(self, cid: str, owner: str) -> bool:
        return cid.startswith(owner + "/")

    def extra_undo(self, card_id: str) -> list[str]:
        """变更知识补充的取消写法：按命令卡编号（同一命令的变体卡 X~2 也算）。"""
        out: list[str] = []
        for k, v in self.rules["undo_extra"].items():
            if card_id == k or _base(card_id) == _base(k) or (k.endswith("*") and card_id.startswith(k[:-1])):
                out += [x for x in v if x not in out]
        return out

    # ----- 1. 差异 -----

    def diff(self) -> None:
        a, b = self.ca.items, self.cb.items
        for cid in sorted(set(a) | set(b)):
            ia, ib = a.get(cid), b.get(cid)
            if ia is not None and ib is not None:
                if ia.kind != "attr" or ia.value == ib.value:
                    continue
                if ib.origin == "default":
                    if ia.origin == "explicit":
                        self.undo_attrs.add(ia.node)
                elif ib.node in self.tgt:
                    self.write.add(ib.node)
                continue
            it = ia or ib
            assert it is not None
            if it.origin in ("derived", "default"):
                continue
            if it.parent and not (it.parent in a and it.parent in b):
                continue  # 祖先对象整体新增 / 删除
            if ib is not None:
                if ib.kind == "object":
                    self.write |= self.target_subtree_facts(ib.node)
                elif ib.node in self.tfacts:
                    self.write.add(ib.node)
            elif ia is not None:
                if ia.kind == "object":
                    if not canon.negated_object(self.cur, ia.node):
                        self.dels.add(ia.node)
                else:
                    self.undo_attrs.add(ia.node)
        self._undo_first()
        self._entry_line_attrs()
        # 整个对象要删除时，它下面的属性与子对象随之删除，不再单独取消
        tops = sorted(self.dels)
        self.dels = {d for d in self.dels if not any(d != t and self._under(d, t) for t in tops)}
        self.undo_attrs = {n for n in self.undo_attrs if not any(self._under(n, t) for t in self.dels)}

    def _entry_line(self, g: nx.MultiDiGraph, ix: checks.Index, attr: str) -> tuple[str, int] | None:
        """属性写在所属对象的入口行上（同一行创建了对象）：返回 (对象, 行号)。"""
        owner = ix.owner_object(attr)
        lines = g.nodes[attr].get("lines") or []
        olines = g.nodes[owner].get("lines") or []
        if not lines or not olines or owner == attr:
            return None
        first = min(olines)
        if first in lines and owner in ix.line_nodes.get(first, []):
            return owner, first
        return None

    def _undo_first(self) -> None:
        """命令卡不允许直接覆盖：修改对象入口行上的取值时先删除对象，再按目标重建整个对象。"""
        for n in sorted(self.write):
            for cid in self.cids_t(n):
                ia = self.ca.items.get(cid)
                if ia is None or ia.kind != "attr":
                    continue
                hit = self._entry_line(self.cur, self.cix, ia.node)
                if hit is None:
                    continue
                owner = hit[0]
                if str(self.cur.nodes[owner].get("schema")) not in self.rules["undo_first"]:
                    continue
                ocid = next(iter(self.cids_c(owner)), "")
                ib = self.cb.items.get(ocid)
                if ib is None:
                    continue
                if not any(self._under(owner, d) for d in self.dels):
                    self.dels.add(owner)
                self.replaced.add(ocid)
                self.write |= self.target_subtree_facts(ib.node)

    def _under(self, n: str, anc: str) -> bool:
        return n == anc or n.startswith(anc + "/")

    def _entry_line_attrs(self) -> None:
        """要恢复默认的属性写在对象入口行上（ip route-static … tag 100）：重写这一行，而不是取消整行（会删掉对象）。"""
        for n in sorted(self.undo_attrs):
            hit = self._entry_line(self.cur, self.cix, n)
            if hit is None:
                continue
            owner = hit[0]
            ocid = next(iter(self.cids_c(owner)), "")
            ib = self.cb.items.get(ocid)
            if ib is None:
                continue
            self.undo_attrs.discard(n)
            if ocid in self.replaced:
                continue
            if str(self.cur.nodes[owner].get("schema")) in self.rules["undo_first"]:
                if not any(self._under(owner, d) for d in self.dels):
                    self.dels.add(owner)
                self.replaced.add(ocid)
                self.write |= self.target_subtree_facts(ib.node)
                continue
            # 重写入口行：对象本身与这一行上的其他取值
            self.write.add(ib.node)
            for x in self.tix.line_nodes.get(min(self.tgt.nodes[ib.node].get("lines") or [0]), []):
                if x in self.tfacts:
                    self.write.add(x)

    # ----- 2. 副作用 -----

    def side_effects(self) -> list[tuple[str, str, str, str]]:
        """(触发节点, 所在一边 current / target, 对象规范编号, 说明)。补发 dst 节点加入 write。"""
        triggers: list[tuple[str, str, str, str]] = []
        for src, dst, note in self.side_rules:
            cand = [(n, "target") for n in self.write if self.tgt.nodes[n].get("schema") == src]
            cand += [(n, "current") for n in self.undo_attrs if self.cur.nodes[n].get("schema") == src]
            for n, side in cand:
                cids = self.cids_t(n) if side == "target" else self.cids_c(n)
                owner = self.owner_cid(cids[0]) if cids else ""
                if not owner or owner not in self.ca.items or owner not in self.cb.items:
                    continue  # 新建的对象没有旧地址；删除的对象不用补发
                triggers.append((n, side, owner, note))
                for cid, it in self.cb.items.items():
                    if it.schema != dst or not self.in_view(cid, owner) or it.origin != "explicit":
                        continue
                    if it.parent != owner and self.cb.items.get(it.parent, it).schema == dst:
                        continue
                    nodes = self.target_subtree_facts(it.node) if it.kind == "object" else {it.node}
                    new = nodes - self.write
                    self.side_nodes |= new
                    self.write |= nodes
        return triggers

    # ----- 3. 命令 -----

    def _ctx_current(self, no: int) -> list[CtxLine]:
        out = []
        for p in self.cix.context(no):
            ln = self.cix.lines[p]
            card = self.kb.cards.get(str(ln.card))
            objs = [
                c
                for n in self.cix.line_nodes.get(p, [])
                if self.cur.nodes[n].get("kind") == "object"
                for c in self.cids_c(n)
            ]
            out.append(CtxLine(ln.text, str(card.enters_view) if card and card.enters_view else "", _deepest(objs)))
        return out

    def _ctx_target(self, no: int) -> list[CtxLine]:
        out = []
        for p in self.tix.context(no):
            ln = self.tix.lines[p]
            card = self.kb.cards.get(str(ln.card))
            objs = [
                c
                for n in self.tix.line_nodes.get(p, [])
                if self.tgt.nodes[n].get("kind") == "object"
                for c in self.cids_t(n)
            ]
            out.append(CtxLine(ln.text, str(card.enters_view) if card and card.enters_view else "", _deepest(objs)))
        return out

    def _view(self, ctx: list[CtxLine]) -> str:
        return ctx[-1].view if ctx and ctx[-1].view else (self.fam.root_view if not ctx else ctx[-1].view)

    def _new_op(self, action: str, text: str, ctx: list[CtxLine], rank: tuple[int, float], **kw: Any) -> Op:
        op = Op(len(self.ops) + 1, action, text, ctx, self._view(ctx), rank, **kw)
        self.ops.append(op)
        return op

    def _refs_of(self, nodes: list[str]) -> set[str]:
        out: set[str] = set()
        for n in nodes:
            for lk in self.tlinks_from.get(n, []):
                if self.tgt.nodes[lk.dst].get("origin") == "derived":
                    continue
                out.update(self.cids_t(lk.dst))
        return out

    def render_writes(self) -> None:
        if not self.write:
            return
        r = canon.render_full(self.tgt, self.kb, self.profile, facts=set(self.write), extras=False)
        stack: list[CtxLine] = []
        for i, ln in enumerate(r.lines):
            if ln.kind not in ("command", "original"):
                continue
            stack = stack[: ln.depth]
            ctx = list(stack)
            card = self.kb.cards.get(str(ln.card)) if ln.card else None
            opens = str(card.enters_view) if card is not None and card.enters_view else None
            objs = [c for o in ln.objects for c in self.cids_t(o)]
            deep = _deepest([c for c in objs if self.cid_kind.get(c) == "object"])
            covers = [n for n in ln.nodes if n in self.write]
            if covers:
                cids = {c for n in covers for c in self.cids_t(n)}
                matched = {c for n in ln.matched for c in self.cids_t(n)}
                text = ln.text
                orig = self._original_line(covers, ln.card)
                if orig is not None:  # 同平台族：目标配置里写出这些节点的原文行（保留未映射的参数与用户的写法）
                    text = self.tix.lines[orig].text
                    matched |= {c for n in self.tix.line_nodes.get(orig, []) for c in self.cids_t(n)}
                new_objs = {c for c in cids if self.cid_kind.get(c) == "object" and c not in self.ca.items}
                existed = any(c in self.ca.items for c in cids)
                action = "modify" if existed else "add"
                if covers and all(n in self.side_nodes for n in covers):
                    action = "side_effect"
                subject = _deepest(sorted(new_objs)) or _deepest(sorted(cids))
                self._new_op(
                    action,
                    text,
                    ctx,
                    (0, float(i)),
                    card=ln.card,
                    opens=opens,
                    obj=deep if opens else "",
                    target_nodes=sorted(covers),
                    cids=cids | matched,
                    creates=new_objs,
                    refs=self._refs_of(covers),
                    subject=subject,
                    lines_target=sorted({x for n in covers for x in self.tgt.nodes[n].get("lines") or []}),
                )
            if opens:
                text0 = ln.text
                if not covers and deep in self.ca.items:  # 已有对象的块头：用设备上原配置的写法
                    text0 = self._current_header(deep, opens) or ln.text
                stack.append(CtxLine(text0, opens, deep))
        self._fallback_writes([n for n in r.uncovered if n in self.write])

    def _current_header(self, cid: str, view: str) -> str | None:
        """当前配置中进入该对象视图的原文行。"""
        node = self.ca.items[cid].node
        for no in sorted(self.cur.nodes[node].get("lines") or []):
            ln = self.cix.lines.get(no)
            card = self.kb.cards.get(str(ln.card)) if ln is not None else None
            if card is not None and str(card.enters_view or "") == view and node in self.cix.line_nodes.get(no, []):
                return ln.text  # type: ignore[union-attr]
        return None

    def _original_line(self, covers: list[str], card: str | None) -> int | None:
        """目标配置中同一张命令卡、写出了全部 covers 的原文行。"""
        lines = {no for n in covers for no in self.tgt.nodes[n].get("lines") or []}
        for no in sorted(lines):
            ln = self.tix.lines.get(no)
            if ln is not None and ln.card == card and set(covers) <= set(self.tix.line_nodes.get(no, [])):
                return no
        return None

    def _fallback_writes(self, nodes: list[str]) -> None:
        """规范渲染写不出的节点：按目标配置的原文行下发（标注兜底，需人工确认）。"""
        by_line: dict[int, list[str]] = defaultdict(list)
        for n in nodes:
            lines = [no for no in self.tgt.nodes[n].get("lines") or [] if n in self.tix.line_nodes.get(no, [])]
            if not lines:
                self.unsupported.append({"node": n, "reason": "no_command"})
                continue
            by_line[min(lines)].append(n)
        for no, ns in sorted(by_line.items()):
            ln = self.tix.lines[no]
            card = self.kb.cards.get(str(ln.card))
            cids = {c for n in ns for c in self.cids_t(n)}
            allc = {c for n in self.tix.line_nodes.get(no, []) for c in self.cids_t(n)}
            new_objs = {c for c in cids if self.cid_kind.get(c) == "object" and c not in self.ca.items}
            opens = str(card.enters_view) if card is not None and card.enters_view else None
            self._new_op(
                "modify" if any(c in self.ca.items for c in cids) else "add",
                ln.text,
                self._ctx_target(no),
                (1, float(no)),
                card=ln.card,
                opens=opens,
                obj=_deepest(sorted(c for c in allc if self.cid_kind.get(c) == "object")) if opens else "",
                target_nodes=sorted(ns),
                cids=allc,
                creates=new_objs,
                refs=self._refs_of(ns),
                subject=_deepest(sorted(new_objs)) or _deepest(sorted(cids)),
                fallback=True,
                fallback_reason="render_failed",
                lines_target=[no],
            )

    def deletes(self) -> None:
        negative = self.fam.negative
        seen: dict[tuple[tuple[str, ...], str], Op] = {}
        for o in sorted(self.dels, key=lambda n: (min(self.cur.nodes[n].get("lines") or [0]), n)):
            for no in cleanup._entry_lines(self.cur, self.cix, o):
                ln = self.cix.lines[no]
                card = self.kb.cards.get(str(ln.card))
                ctx = self._ctx_current(no)
                objs = [n for n in self.cix.line_nodes.get(no, []) if self.cur.nodes[n].get("kind") == "object"]
                text, why = undo_text(card, ln, negative, _key_tokens(self.cur, objs), self.extra_undo(str(ln.card)))
                root = max(objs, key=lambda n: n.count("/"), default=o)
                if not self._under(root, o):
                    root = o
                removes = {c for n in self.subtree(self.cur, root) for c in self.cids_c(n)}
                anc = root
                while (
                    anc != o and "/" in anc
                ):  # 从被删对象到这一行创建的对象之间的各层（最后一个入口删掉后它们也不存在了）
                    anc = self.cix.parent.get(anc, o)
                    removes.update(self.cids_c(anc))
                removes.update(self.cids_c(o))
                key = (tuple(c.key for c in ctx), text)
                hit = seen.get(key)
                if hit is not None:  # 同一条命令删除整个对象：只输出一次
                    hit.removes |= removes
                    hit.lines_current.append(no)
                    continue
                seen[key] = self._new_op(
                    "delete",
                    text,
                    ctx,
                    (2, float(no)),
                    card=ln.card,
                    current_nodes=[o],
                    removes=removes,
                    subject=next(iter(self.cids_c(root)), root),
                    fallback=why is not None,
                    fallback_reason=why,
                    lines_current=[no],
                )
        for n in sorted(self.undo_attrs, key=lambda x: (min(self.cur.nodes[x].get("lines") or [0]), x)):
            lines = [no for no in self.cur.nodes[n].get("lines") or [] if n in self.cix.line_nodes.get(no, [])]
            if not lines:
                continue
            no = min(lines)
            ln = self.cix.lines[no]
            card = self.kb.cards.get(str(ln.card))
            text, why = cleanup.render_undo_reason(card, ln, negative)
            ctx = self._ctx_current(no)
            key = (tuple(c.key for c in ctx), text)
            hit = seen.get(key)
            removes = set(self.cids_c(n))
            if hit is not None:
                hit.removes |= removes
                hit.current_nodes.append(n)
                continue
            op = self._new_op(
                "delete",
                text,
                ctx,
                (2, float(no)),
                card=ln.card,
                current_nodes=[n],
                removes=removes,
                subject=self.owner_cid(next(iter(removes), "")),
                fallback=why is not None,
                fallback_reason=why,
                lines_current=[no],
            )
            seen[key] = op
            # 同一行上的其他取值目标里仍然要：取消后补写
            for x in self.cix.line_nodes.get(no, []):
                if x == n or self.cur.nodes[x].get("kind") != "attr":
                    continue
                for c in self.cids_c(x):
                    ib = self.cb.items.get(c)
                    if ib is not None and ib.origin == "explicit" and ib.node in self.tfacts:
                        self.write.add(ib.node)
                        self.rewrite[ib.node] = op.id

    def ext_ops(self) -> None:
        """未映射到 Schema 的命令（ext）：同一对象下按多重集合比较，新增的按原文下发、删除的按取消语法。"""
        ga: dict[tuple[str, str], list[compare.Multi]] = defaultdict(list)
        gb: dict[tuple[str, str], list[compare.Multi]] = defaultdict(list)
        for m in self.ca.ext:
            ga[(m.owner, m.group)].append(m)
        for m in self.cb.ext:
            gb[(m.owner, m.group)].append(m)
        negative = self.fam.negative
        for key in sorted(set(ga) | set(gb)):
            owner = key[0]
            if owner and not (owner in self.ca.items and owner in self.cb.items):
                continue  # 所属对象整体新增 / 删除：随对象处理
            ma, mb = list(ga.get(key, [])), list(gb.get(key, []))
            for m in list(ma):
                hit = next((x for x in mb if x.sig == m.sig), None)
                if hit is not None:
                    ma.remove(m)
                    mb.remove(hit)
            dels: list[Op] = []
            for m in ma:
                no = min(m.lines) if m.lines else 0
                if no not in self.cix.lines:
                    continue
                ln = self.cix.lines[no]
                text, why = cleanup.render_undo_reason(self.kb.cards.get(str(ln.card)), ln, negative)
                dels.append(
                    self._new_op(
                        "delete",
                        text,
                        self._ctx_current(no),
                        (2, float(no)),
                        card=ln.card,
                        current_nodes=[m.node],
                        removes=set(self.cids_c(m.node)) | {f"ext:{m.node}"},
                        subject=owner,
                        fallback=why is not None,
                        fallback_reason=why,
                        lines_current=[no],
                    )
                )
            for m in mb:
                no = min(m.lines) if m.lines else 0
                if no not in self.tix.lines:
                    continue
                ln = self.tix.lines[no]
                op = self._new_op(
                    "modify" if dels else "add",
                    ln.text,
                    self._ctx_target(no),
                    (1, float(no)),
                    card=ln.card,
                    target_nodes=[m.node],
                    subject=owner,
                    lines_target=[no],
                )
                op.notes.append("ext")
                for d in dels:
                    op.after[d.id] = {"kind": "replace", "node": owner, "note": ""}

    # ----- 4. 约束 -----

    def constraints(self, triggers: list[tuple[str, str, str, str]]) -> None:
        ops = self.ops
        by_target: dict[str, Op] = {}
        creates: dict[str, Op] = {}
        removes: dict[str, Op] = {}
        for op in ops:
            for n in op.target_nodes:
                by_target.setdefault(n, op)
            for c in op.creates:
                creates.setdefault(c, op)
            for c in op.removes:
                removes.setdefault(c, op)
        by_cid_write: dict[str, Op] = {}
        for op in ops:
            for n in op.target_nodes:
                for c in self.cids_t(n):
                    by_cid_write.setdefault(c, op)

        def need(before: Op | None, after: Op | None, kind: str, node: str, note: str = "") -> None:
            if before is None or after is None or before.id == after.id:
                return
            after.after.setdefault(before.id, {"kind": kind, "node": node, "note": note})

        for op in ops:
            # 对象的子命令在进入它的视图之后：上下文里的对象由别的命令新建时排在它之后
            for cl in op.context:
                if cl.obj:
                    need(creates.get(cl.obj), op, "contains", cl.obj)
            # 被引用 / 前置对象先建
            for n in op.target_nodes:
                for lk in self.tlinks_from.get(n, []):
                    for c in self.cids_t(lk.dst):
                        need(creates.get(c), op, lk.kind, c, lk.note)
        # 删除：先处理引用方（删除、取消或改为引用别的对象）
        for lk in self.clinks:
            for y in self.cids_c(lk.dst):
                d = removes.get(y)
                if d is None or self.cid_kind.get(y) != "object":
                    continue
                for a in self.cids_c(lk.src):
                    h = removes.get(a) or by_cid_write.get(a)
                    if h is None:
                        anc = a
                        while "/" in anc and h is None:
                            anc = anc.rsplit("/", 1)[0]
                            h = removes.get(anc)
                    need(h, d, "referenced_by", a, lk.note)
        # 副作用：触发命令之后补发；同一对象下要删除的 dst 在触发之前删（否则设备上已经被副作用删掉，再删会报错）
        for n, side, owner, note in triggers:
            t = by_target.get(n) if side == "target" else next((o for o in ops if n in o.current_nodes), None)
            if t is None:
                continue
            if "side_effect" not in t.notes:
                t.notes.append("side_effect")
            src_cid = next(iter(self.cids_t(n) if side == "target" else self.cids_c(n)), n)
            dst_schemas = {
                d
                for s, d, _ in self.side_rules
                if s == str((self.tgt if side == "target" else self.cur).nodes[n].get("schema"))
            }
            for op in ops:
                if op is t:
                    continue
                if (
                    op.target_nodes
                    and any(
                        self.tgt.nodes[x].get("schema") in dst_schemas or self._schema_under(x, dst_schemas)
                        for x in op.target_nodes
                    )
                    and any(self.in_view(c, owner) for x in op.target_nodes for c in self.cids_t(x))
                ):
                    need(t, op, "side_effect", src_cid, note)
                if op.negative and any(
                    self.cid_schema.get(c) in dst_schemas and self.in_view(c, owner) for c in op.removes
                ):
                    need(op, t, "side_effect_cleanup", src_cid, note)
        # 互斥：先撤旧再配新；replace_first：同一父对象下一删一增先删旧；undo_first：先删后建
        for op in ops:
            if not op.target_nodes:
                continue
            for n in op.target_nodes:
                s = str(self.tgt.nodes[n].get("schema"))
                for c in self.cids_t(n):
                    owner = self.cb.items[c].parent if c in self.cb.items else ""
                    for d in ops:
                        if not d.negative:
                            continue
                        for rc in d.removes:
                            rs = self.cid_schema.get(rc, "")
                            ritem = self.ca.items.get(rc)
                            if ritem is None or ritem.parent != owner or rc in self.cb.items:
                                continue
                            if (s, rs) in self.mutex:
                                need(d, op, "mutex", rc)
                                if d.action == "delete":
                                    d.action = "mutex"
                            elif s == rs and s in self.rules["replace_first"] and self.cid_kind.get(c) == "object":
                                need(d, op, "replace", rc)
        for ocid in self.replaced:
            d = removes.get(ocid)
            for op in ops:
                if op is not d and any(
                    c == ocid or self.in_view(c, ocid) for n in op.target_nodes for c in self.cids_t(n)
                ):
                    need(d, op, "undo_first", ocid)
                    if "undo_first" not in op.notes:
                        op.notes.append("undo_first")
        for n, oid in self.rewrite.items():
            u = next((o for o in ops if o.id == oid), None)
            need(u, by_target.get(n), "rewrite", next(iter(self.cids_t(n)), n))

    def _schema_under(self, n: str, schemas: set[str]) -> bool:
        s = str(self.tgt.nodes[n].get("schema") or "")
        return any(s.startswith(x + ".") for x in schemas)

    # ----- 5. 排序 -----

    def _group_ranks(self) -> None:
        """视图内的删除紧跟同一顶层块里的新增 / 修改（少进出一次视图）；顶层对象的删除仍放在最后。"""
        last: dict[str, float] = {}
        for op in self.ops:
            if op.rank[0] < 2 and op.context:
                k = op.context[0].key
                last[k] = max(last.get(k, -1.0), op.rank[1] + (1000.0 if op.rank[0] == 1 else 0.0))
        for op in self.ops:
            if op.rank[0] == 2 and op.context and op.context[0].key in last:
                op.rank = (0, last[op.context[0].key] + 0.5 + op.rank[1] / 1e7)

    def order(self) -> list[Op]:
        self._group_ranks()
        dg = nx.DiGraph()
        byid = {op.id: op for op in self.ops}
        dg.add_nodes_from(byid)
        for op in self.ops:
            for b in op.after:
                dg.add_edge(b, op.id)
        priority = ["referenced_by", "replace", "rewrite", "contains", "reference", "key", "alias"]
        while True:
            try:
                ids = list(nx.lexicographical_topological_sort(dg, key=lambda i: (byid[i].rank, i)))
                break
            except nx.NetworkXUnfeasible:
                cyc = nx.find_cycle(dg)
                a, b = min(
                    ((x, y) for x, y, *_ in cyc),
                    key=lambda e: (
                        priority.index(byid[e[1]].after[e[0]]["kind"])
                        if byid[e[1]].after[e[0]]["kind"] in priority
                        else len(priority)
                    ),
                )
                dg.remove_edge(a, b)
                byid[b].after.pop(a, None)
                self.warnings.append({"key": "change.warn.cycle", "params": {"a": a, "b": b}})
        return [byid[i] for i in ids]

    # ----- 6. 风险 -----

    def risk(self, ops: list[Op]) -> None:
        walk = impact._walk_index(self.cur, self.kb)
        high = self.rules["risk_high"]

        def risky(schema: str) -> bool:
            return any(schema == h or schema.startswith(h + ".") for h in high)

        for op in ops:
            reasons: list[str] = []
            level = 0
            if op.action == "side_effect" or "side_effect" in op.notes:
                level, reasons = 2, ["side_effect"]
            existing = op.action != "add"
            schemas = [str(self.cid_schema.get(c, "")) for c in (op.cids | op.removes)]
            if existing and any(risky(s) for s in schemas):
                level = 2
                reasons.append("business_node")
            if op.fallback:
                level = max(level, 1)
                reasons.append("fallback")
            if existing and level < 2:
                seeds = [n for n in op.current_nodes if n in self.cur]
                seeds += [self.ca.items[c].node for n in op.target_nodes for c in self.cids_t(n) if c in self.ca.items]
                seeds = [s for s in dict.fromkeys(seeds) if s in self.cur and s != DEVICE]
                if seeds:
                    r = impact.analyze(self.cur, self.kb, seeds, walk=walk)
                    if r["business"]:
                        level = max(level, 1)
                        reasons.append("affects_business")
            op.risk, op.risk_reasons = RISKS[level], reasons

    # ----- 整体 -----

    def run(self) -> list[Op]:
        self.diff()
        triggers = self.side_effects()
        self.deletes()  # 先生成删除（取消多取值行时会补充要写的节点）
        self.render_writes()
        self.ext_ops()
        self.constraints(triggers)
        ops = self.order()
        self.risk(ops)
        return ops


# ---------------------------------------------------------------- 脚本文本


def _exit_word(kb: KnowledgeBase, family: str, view: str, rules: dict[str, Any]) -> str:
    exits = canon.load_style(kb, family)["exits"]
    return exits.get(view) or rules["exit"]


def script_lines(
    ops: list[Op], kb: KnowledgeBase, family: str, rules: dict[str, Any], notes: dict[int, str] | None = None
) -> list[str]:
    """按视图分块：进入视图的命令、缩进的子命令、退出；notes 给出时每条命令前加一行说明（注释）。"""
    indent = kb.families[family].indent
    out: list[str] = list(rules["begin"])
    stack: list[CtxLine] = []

    def pad(n: int) -> str:
        return " " * (indent * n)

    for op in ops:
        ctx = op.context
        common = 0
        while common < len(stack) and common < len(ctx) and stack[common].key == ctx[common].key:
            common += 1
        for i in reversed(range(common, len(stack))):
            out.append(pad(i) + _exit_word(kb, family, stack[i].view, rules))
        stack = stack[:common]
        for i in range(common, len(ctx)):
            out.append(pad(i) + ctx[i].text)
            stack.append(ctx[i])
        if notes is not None and op.id in notes:
            out.append(pad(len(stack)) + f"{rules['comment']} {notes[op.id]}")
        out.append(pad(len(stack)) + op.text)
        if op.opens and not op.negative:
            stack.append(op.as_ctx())
    for i in reversed(range(len(stack))):
        out.append(pad(i) + _exit_word(kb, family, stack[i].view, rules))
    out += rules["finish"]
    return out


# ---------------------------------------------------------------- 验证：在当前配置上模拟执行


@dataclass
class _Entry:
    text: str
    card: str | None = None
    values: dict[str, Any] = field(default_factory=dict)
    cids: set[str] = field(default_factory=set)
    objs: set[str] = field(default_factory=set)
    refs: set[str] = field(default_factory=set)
    view: str = ""  # 这一行进入的视图
    children: list[_Entry] = field(default_factory=list)


def _base(card_id: str | None) -> str:
    """命令卡编号去掉变体后缀（rule~2 → rule）：同一条命令的不同写法。"""
    return re.sub(r"([~.]\d+)+$", "", str(card_id or ""))


def _norm_val(v: Any) -> str:
    if isinstance(v, list):
        return " ".join(str(x) for x in v).lower()
    return str(v).lower()


class _Sim:
    def __init__(self, p: _Planner):
        self.p, self.kb = p, p.kb
        self.idx = parsemod.CardIndex(p.kb, p.family)
        self.root = _Entry("")
        self.issues: list[dict[str, Any]] = []
        self.violations: list[dict[str, Any]] = []
        entries: dict[int, _Entry] = {}
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
            e = _Entry(
                ln.text,
                ln.card,
                ln.values(),
                cids,
                {c for c in cids if p.cid_kind.get(c) == "object"},
                {c for n in st.nodes for c in clinks.get(n, set())},
                str(card.enters_view) if card is not None and card.enters_view else "",
            )
            entries[ln.no] = e
            parent = entries.get(ln.parent) if ln.parent else None
            (parent or self.root).children.append(e)

    # ----- 树 -----

    def _all(self, e: _Entry | None = None) -> list[_Entry]:
        out: list[_Entry] = []
        stack = list((e or self.root).children)
        while stack:
            x = stack.pop()
            out.append(x)
            stack.extend(x.children)
        return out

    def objects(self) -> set[str]:
        return {c for e in self._all() for c in e.objs}

    def _prune(self, e: _Entry, drop: set[str]) -> None:
        """删除对象：去掉只属于被删节点的行（连同子行）。"""
        e.children = [c for c in e.children if not (c.cids and c.cids <= drop)]
        for c in e.children:
            self._prune(c, drop)

    def block(self, ctx: list[CtxLine]) -> tuple[_Entry, str]:
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
                hit = _Entry(
                    c.text, m[0].id if m else None, m[1].all_values() if m else {}, {c.obj} - {""}, {c.obj} - {""}
                )
                hit.view = c.view
                cur.children.append(hit)
            cur, view = hit, c.view or view
        return cur, view

    # ----- 执行一条命令 -----

    def apply(self, op: Op) -> None:
        before = self.objects()
        blk, view = self.block(op.context)
        if op.negative:
            self._undo(op, blk, view)
        else:
            self._set(op, blk, view)
        self._side_effect(op, blk)
        self._check(op, before)

    def _undo(self, op: Op, blk: _Entry, view: str) -> None:
        hit = parsemod.match_undo(self.idx, view, op.text)
        extra = False
        if hit is None:
            hit, extra = self._extra_undo(view, op.text), True
        cand: list[_Entry] = []
        if hit is not None:
            card, m, _ = hit
            want = {k: _norm_val(v) for k, v in m.all_values().items() if v not in (None, "", [])}
            cand = [
                e
                for e in blk.children
                if (extra or _base(e.card) == _base(card.id))
                and (want or not extra)
                and all(_norm_val(e.values.get(k)) == v for k, v in want.items())
            ]
        if not cand:
            cand = [e for e in blk.children if e.cids & op.removes]
            if hit is not None or not op.fallback:
                self.issues.append({"seq": op.id, "kind": "undo_no_match", "text": op.text})
        blk.children = [e for e in blk.children if all(e is not x for x in cand)]
        if op.removes:
            self._prune(self.root, op.removes)

    def _extra_undo(self, view: str, text: str) -> tuple[Any, Any, Any] | None:
        """变更知识补充的取消写法（undo_extra）。"""
        for card in self.kb.cards_of(self.p.family):
            if card.view != view:
                continue
            for src in self.p.extra_undo(card.id):
                try:
                    usyn = syn.parse(src)
                except syn.SyntaxErrorKB:
                    continue
                m = syn.match(usyn, text, card.params)
                if m is not None:
                    return card, m, usyn
        return None

    def _set(self, op: Op, blk: _Entry, view: str) -> None:
        m = parsemod.match_line(self.idx, view, op.text)
        if m is None and op.text.split()[:1] == [self.p.fam.negative]:
            # 取消形式的设置命令（undo shutdown → shutdown=false）：按取消语法解析
            u = parsemod.match_undo(self.idx, view, op.text) or self._extra_undo(view, op.text)
            m = (u[0], u[1]) if u is not None else None
        if m is None:
            self.issues.append({"seq": op.id, "kind": "unparsable", "text": op.text})
        attrs = {c for c in op.cids if self.p.cid_kind.get(c) == "attr"}
        new = _Entry(
            op.text,
            m[0].id if m else None,
            m[1].all_values() if m else {},
            set(op.cids),
            set(op.creates) | {c for c in op.cids if self.p.cid_kind.get(c) == "object"},
            set(op.refs),
            op.opens or "",
        )
        kept: list[_Entry] = []
        moved: list[_Entry] = []
        for e in blk.children:
            same_obj = bool(op.obj and op.obj in e.objs and e.view)
            if (attrs and e.cids & attrs and not (e.cids & attrs) - set(op.cids)) or same_obj:
                moved += e.children  # 覆盖旧命令；它下面的子命令留在新命令下面
            else:
                kept.append(e)
        new.children = moved
        blk.children = [*kept, new]

    def _side_effect(self, op: Op, blk: _Entry) -> None:
        nodes = [(self.p.tgt, n) for n in op.target_nodes] + [(self.p.cur, n) for n in op.current_nodes]
        for src, dst, _ in self.p.side_rules:
            if not any(g.nodes[n].get("schema") == src for g, n in nodes if n in g):
                continue
            blk.children = [e for e in blk.children if not any(self.p.cid_schema.get(c) == dst for c in e.cids)]

    def _check(self, op: Op, before: set[str]) -> None:
        objs = self.objects()
        if not op.negative:
            missing = sorted(r for r in op.refs if r not in objs)
            if missing:
                self.violations.append({"seq": op.id, "kind": "missing_reference", "nodes": missing})
        else:
            gone = before - objs
            if gone:
                still = sorted({r for e in self._all() for r in e.refs & gone})
                if still:
                    self.violations.append({"seq": op.id, "kind": "still_referenced", "nodes": still})

    def text(self) -> str:
        indent = self.p.fam.indent
        out: list[str] = []

        def walk(e: _Entry, depth: int) -> None:
            for c in e.children:
                out.append(" " * (indent * depth) + c.text)
                walk(c, depth + 1)

        walk(self.root, 0)
        return "\n".join(out) + "\n"


def verify(p: _Planner, ops: list[Op]) -> dict[str, Any]:
    sim = _Sim(p)
    for op in ops:
        sim.apply(op)
    seq = {op.id: i for i, op in enumerate(ops, start=1)}
    for item in sim.issues + sim.violations:
        item["seq"] = seq.get(item["seq"], item["seq"])
    text = sim.text()
    profile = str(p.cur.graph["profile"])
    parsed = parsemod.parse(text, p.kb, p.family)
    after = graphmod.build(parsed, p.kb, profile, str(p.cur.graph.get("device") or "device"))
    c = compare.compare(compare.Side(after, "after"), compare.Side(p.tgt, "target"), p.kb)
    keys = {(d["referrer"], str(d["target_type"]), str(d["value"])) for d in checks.dangling(after, p.kb)}
    tkeys = {(d["referrer"], str(d["target_type"]), str(d["value"])) for d in checks.dangling(p.tgt, p.kb)}
    new_dangling = sorted(keys - tkeys)
    unknown = parsed.counts().get("unknown", 0)
    ok = c["equal"] and not new_dangling and not sim.violations and not sim.issues
    return {
        "ok": ok,
        "equal": c["equal"],
        "diffs": [{"kind": d["kind"], "node": d["node"]} for d in c["diffs"][:30]],
        "diff_count": len(c["diffs"]),
        "new_dangling": [{"referrer": r, "target_type": t, "value": v} for r, t, v in new_dangling],
        "order_violations": sim.violations,
        "issues": sim.issues,
        "unknown": unknown,
    }


# ---------------------------------------------------------------- 结果


def _op_dict(op: Op, seq: dict[int, int], namer: Any, kb: KnowledgeBase, p: _Planner) -> dict[str, Any]:
    subj = op.subject or (op.context[-1].obj if op.context else "")
    sn = kb.nodes.get(str(p.cid_schema.get(subj, "")))
    return {
        "seq": seq[op.id],
        "action": op.action,
        "text": op.text,
        "context": [c.text for c in op.context],
        "view": op.view,
        "depth": len(op.context),
        "object": subj,
        "label": namer(subj) if namer and subj else subj,
        "domain": sn.domain if sn else "",
        "card": op.card,
        "target_nodes": op.target_nodes,
        "current_nodes": op.current_nodes,
        "fallback": op.fallback,
        "fallback_reason": op.fallback_reason,
        "notes": op.notes,
        "risk": op.risk,
        "risk_reasons": op.risk_reasons,
        "after": [
            {
                "seq": seq[b],
                "kind": r["kind"],
                "node": r["node"],
                "label": namer(r["node"]) if namer and r["node"] else r["node"],
                "note": r.get("note", ""),
            }
            for b, r in sorted(op.after.items(), key=lambda kv: seq[kv[0]])
        ],
        "lines": {"current": sorted(op.lines_current), "target": sorted(op.lines_target)},
    }


def note_text(d: dict[str, Any], lang: str) -> str:
    """脚本中每条命令前的说明（按语言）。"""
    from lmesh.core import i18n

    parts = [i18n.t(f"change.action.{d['action']}", lang)]
    if d.get("label"):
        parts.append(str(d["label"]))
    if d["after"]:
        parts.append(
            i18n.t(
                "change.note.after",
                lang,
                deps=", ".join(
                    f"[{a['seq']}] {i18n.t('change.dep.' + a['kind'], lang)} {a['label']}" for a in d["after"][:3]
                ),
            )
        )
    if d["fallback"]:
        parts.append(i18n.t("change.note.fallback", lang))
    parts.append(i18n.t("change.note.risk", lang, risk=i18n.t(f"change.risk.{d['risk']}", lang)))
    return f"[{d['seq']}] " + "; ".join(parts)


def _plan(
    cur: nx.MultiDiGraph, tgt: nx.MultiDiGraph, kb: KnowledgeBase, namer: Any, lang: str, do_verify: bool
) -> dict[str, Any]:
    p = _Planner(cur, tgt, kb)
    ops = p.run()
    seq = {op.id: i for i, op in enumerate(ops, start=1)}
    items = [_op_dict(op, seq, namer, kb, p) for op in ops]
    notes = {op.id: note_text(d, lang) for op, d in zip(ops, items, strict=True)}
    by_action = dict.fromkeys(ACTIONS, 0)
    by_domain: dict[str, int] = defaultdict(int)
    counts = dict.fromkeys(RISKS, 0)
    for d in items:
        by_action[d["action"]] += 1
        by_domain[d["domain"] or "other"] += 1
        counts[d["risk"]] += 1
    level = max((RISKS.index(d["risk"]) for d in items), default=0)
    out: dict[str, Any] = {
        "ops": items,
        "script": "\n".join(script_lines(ops, kb, p.family, p.rules, notes)) + "\n",
        "script_plain": "\n".join(script_lines(ops, kb, p.family, p.rules)) + "\n",
        "risk": {"level": RISKS[level], "counts": counts},
        "summary": {
            "ops": len(items),
            "by_action": by_action,
            "by_domain": dict(sorted(by_domain.items())),
            "fallbacks": sum(1 for d in items if d["fallback"]),
            "side_effects": sum(1 for d in items if d["action"] == "side_effect"),
            "unsupported": len(p.unsupported),
        },
        "unsupported": p.unsupported,
        "warnings": p.warnings,
        "family": p.family,
    }
    if do_verify:
        out["verify"] = verify(p, ops)
    return out


def side_info(g: nx.MultiDiGraph, label: str) -> dict[str, Any]:
    return {
        "label": label,
        "device": g.graph.get("device"),
        "profile": g.graph.get("profile"),
        "family": g.graph.get("family"),
    }


def change(
    current: compare.Side,
    target: compare.Side,
    kb: KnowledgeBase,
    rollback: bool = True,
    verify_scripts: bool = True,
    namer: Any = None,
    lang: str = "zh-CN",
    with_impact: bool = True,
) -> dict[str, Any]:
    """当前 → 目标的下发脚本（ops、script），以及目标 → 当前的回滚脚本（rollback）；verify 为模拟执行的验证结果。

    namer：规范编号 → 显示名（按显示风格，只影响说明文字）；lang：脚本说明的语言。"""
    cur, tgt = current.graph, target.graph
    fwd = _plan(cur, tgt, kb, namer, lang, verify_scripts)
    result: dict[str, Any] = {
        "current": {**current.info(), "label": current.label},
        "target": {**target.info(), "label": target.label},
        "family": fwd.pop("family"),
        "equal": not fwd["ops"],
        **fwd,
    }
    if rollback:
        rb = _plan(tgt, cur, kb, namer, lang, verify_scripts)
        rb.pop("family", None)
        result["rollback"] = rb
    if with_impact:
        result["impact"] = impact.of_change(cur, tgt, kb, result)
    return result


def change_text(
    current_text: str,
    target_text: str,
    kb: KnowledgeBase,
    profile: str | None = None,
    **kw: Any,
) -> dict[str, Any]:
    a = compare.side_from_text(current_text, kb, profile, "current")
    b = compare.side_from_text(target_text, kb, profile or str(a.graph.graph.get("profile")), "target")
    return change(a, b, kb, **kw)


def plan(
    current_graph: nx.MultiDiGraph,
    target_graph: nx.MultiDiGraph,
    kb: KnowledgeBase,
    profile: str | None = None,
    **kw: Any,
) -> dict[str, Any]:
    """供其他模块（割接迁移等）调用的简化入口：两张图 → {script, rollback, items, verify, …}。

    profile 只用于图里没有记录 Profile 时补上（两张图都必须由配置文本解析建图，带 statements）；
    其余参数同 change()。返回：script / script_plain（下发脚本）、rollback / rollback_plain（回滚脚本）、
    items（逐条命令，同 change() 的 ops）、verify / rollback_verify（模拟执行验证）、risk、summary、result（完整结果）。"""
    for g in (current_graph, target_graph):
        if profile and not g.graph.get("profile"):
            g.graph["profile"] = profile
            g.graph["family"] = kb.profiles[profile].family
    r = change(
        compare.Side(current_graph, str(current_graph.graph.get("device") or "current")),
        compare.Side(target_graph, str(target_graph.graph.get("device") or "target")),
        kb,
        **kw,
    )
    rb = r.get("rollback") or {}
    return {
        "script": r["script"],
        "script_plain": r["script_plain"],
        "rollback": rb.get("script", ""),
        "rollback_plain": rb.get("script_plain", ""),
        "items": r["ops"],
        "verify": r.get("verify"),
        "rollback_verify": rb.get("verify"),
        "risk": r["risk"],
        "summary": r["summary"],
        "result": r,
    }
