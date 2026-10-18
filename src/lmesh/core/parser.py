"""结构化解析：配置文本 → 带行号的结构化结果（每行的类型、所在视图、匹配的命令卡与参数）。

行的类型：
    separator  块分隔行（华为 #，Cisco !）
    end        配置结尾（return / end）
    comment    注释或配置头（华为以 ! 开头的行、Cisco 以 ! 开头且有内容的行）
    blank      空行
    command    匹配上命令卡
    unknown    当前视图里有同样开头的命令卡，但整行匹配不上：知识库的缺口，进入未识别队列
    raw        功能域之外的配置（原文节点），以及 raw 块下面的子行：原样保留，往返时原样输出

层级以缩进为准；例外是“比上一行缩进深很多、而上一行并没有进入子视图”的行（终端分页留下的异常缩进），
它仍属于上一行所在的视图，原始空白原样保留。
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from lmesh.core.kb import KnowledgeBase
from lmesh.core.kb import syntax as syn
from lmesh.core.kb.model import Card

STATUS_RANK = {"verified": 3, "reviewed": 2, "draft": 1, "rejected": 0}


@dataclass
class Line:
    no: int  # 1 开始
    raw: str  # 原文（不含换行）
    kind: str
    indent: str = ""  # 行首空白原文
    view: str = ""
    card: str | None = None
    match: syn.Match | None = None
    parent: int | None = None  # 父命令所在行号（进入视图的那一行）
    domain: str = ""
    negated: bool = False  # undo / no 形式
    fmt: str | None = None  # 渲染结果与原文只差空白时，记录原文（保证往返逐字一致）

    @property
    def text(self) -> str:
        return self.raw.strip()

    def values(self) -> dict[str, Any]:
        return self.match.all_values() if self.match else {}

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"no": self.no, "kind": self.kind, "text": self.text, "view": self.view}
        if self.card:
            d.update(card=self.card, domain=self.domain, values=self.values())
            if self.negated:
                d["negated"] = True
        if self.parent:
            d["parent"] = self.parent
        return d


@dataclass
class Parsed:
    family: str
    lines: list[Line] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for ln in self.lines:
            out[ln.kind] += 1
        return dict(out)

    def unknown(self) -> list[Line]:
        return [ln for ln in self.lines if ln.kind == "unknown"]

    def coverage(self) -> float:
        """功能域覆盖率：command / (command + unknown)。"""
        c = self.counts()
        total = c.get("command", 0) + c.get("unknown", 0)
        return 1.0 if total == 0 else c.get("command", 0) / total

    def as_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "counts": self.counts(),
            "coverage": round(self.coverage(), 4),
            "lines": [ln.as_dict() for ln in self.lines],
        }


class CardIndex:
    """按（视图, 第一个关键字）索引命令卡，并为每个视图记录已知的命令开头（区分 unknown 与 raw）。"""

    def __init__(self, kb: KnowledgeBase, family: str):
        self.negative = kb.families[family].negative
        self.undo: dict[str, list[tuple[Card, syn.Syntax]]] = defaultdict(list)  # 视图 → (卡, undo 语法)
        self.by_key: dict[tuple[str, str], list[Card]] = defaultdict(list)
        self.loose: dict[str, list[Card]] = defaultdict(list)  # 语法不以关键字开头的卡
        self.prefixes: dict[str, set[tuple[str, ...]]] = defaultdict(set)
        for c in kb.cards_of(family):
            try:
                lead = c.parsed.leading_keywords()
            except syn.SyntaxErrorKB:
                continue
            if lead:
                self.by_key[(c.view, lead[0])].append(c)
                self.prefixes[c.view].add(tuple(lead[:2]))
            else:
                self.loose[c.view].append(c)
            if c.undo:
                try:
                    usyn = syn.parse(c.undo)
                    self.undo[c.view].append((c, usyn))
                    # 取消形式记录前三个关键字（undo ip vpn-instance），避免 undo set … 之类的无关命令被当成缺口
                    if len(usyn.leading_keywords()) >= 2:
                        self.prefixes[c.view].add(tuple(usyn.leading_keywords()[:3]))
                except syn.SyntaxErrorKB:
                    pass
        for cards in self.by_key.values():
            cards.sort(key=lambda c: (-STATUS_RANK.get(c.status, 0), c.id))

    def candidates(self, view: str, first: str) -> list[Card]:
        return self.by_key.get((view, first.lower()), []) + self.loose.get(view, [])

    def known_prefix(self, view: str, tokens: list[str]) -> bool:
        """这一行的开头是否与当前视图中某张命令卡的开头关键字一致（一致却匹配不上 → unknown）。"""
        low = [t.lower() for t in tokens[:3]]
        return any(p and list(p) == low[: len(p)] for p in self.prefixes.get(view, ()))


@dataclass
class _Frame:
    indent: int
    view: str
    line: int
    raw: bool = False  # raw 块：下面的子行都是 raw


def match_undo(index: CardIndex, view: str, text: str) -> tuple[Card, syn.Match, syn.Syntax] | None:
    """取消形式：先按命令卡的 undo 语法匹配；匹配不上时，“取消前缀 + 某张卡开头的全部关键字”也算（no ip address）。"""
    best: tuple[Card, syn.Match, syn.Syntax] | None = None
    for card, usyn in index.undo.get(view, []):
        m = syn.match(usyn, text, card.params)
        if m is not None and (
            best is None
            or m.keywords > best[1].keywords
            or (m.keywords == best[1].keywords and STATUS_RANK.get(card.status, 0) > STATUS_RANK.get(best[0].status, 0))
        ):
            best = (card, m, usyn)
    if best is None:
        words = [w.lower() for w in text.split()[1:]]
        for card in index.candidates(view, words[0] if words else ""):
            lead = card.parsed.leading_keywords()
            if lead and lead == words:
                bare = syn.parse(" ".join([text.split()[0], *card.parsed.leading_keywords()]))
                m = syn.match(bare, text, {})
                if m is not None:
                    return (card, m, bare)
    return best


def match_line(index: CardIndex, view: str, text: str) -> tuple[Card, syn.Match] | None:
    toks = text.split()
    if not toks:
        return None
    best: tuple[Card, syn.Match] | None = None
    for card in index.candidates(view, toks[0]):
        try:
            m = syn.match(card.parsed, text, card.params)
        except syn.SyntaxErrorKB:
            continue
        if m is None:
            continue
        if (
            best is None
            or m.keywords > best[1].keywords
            or (m.keywords == best[1].keywords and STATUS_RANK.get(card.status, 0) > STATUS_RANK.get(best[0].status, 0))
        ):
            best = (card, m)
    return best


def parse(text: str, kb: KnowledgeBase, family: str) -> Parsed:
    fam = kb.families[family]
    index = CardIndex(kb, family)
    out = Parsed(family)
    stack: list[_Frame] = []
    prev_indent = 0
    prev_entered = False
    for no, raw in enumerate(text.split("\n"), start=1):
        stripped = raw.strip()
        lead = raw[: len(raw) - len(raw.lstrip())]
        indent = len(lead.expandtabs(1))
        if not stripped:
            out.lines.append(Line(no, raw, "blank", lead))
            continue
        if stripped == fam.separator and indent <= 1:
            out.lines.append(Line(no, raw, "separator", lead))
            # 华为：顶层 # 结束当前块；视图内的 " #"（缩进 1）只是视图内的分隔，不改变层级
            if indent == 0:
                stack.clear()
            prev_indent, prev_entered = indent, False
            continue
        if fam.end and stripped == fam.end and indent == 0:
            out.lines.append(Line(no, raw, "end", lead))
            stack.clear()
            continue
        if stripped.startswith("!") and (fam.separator != "!" or len(stripped) > 1):
            out.lines.append(Line(no, raw, "comment", lead))
            continue

        # 显式退出视图的命令（Cisco 的 exit-address-family 等）：在按缩进退栈之前处理，退出栈中最近的那个视图
        exit_at = next(
            (
                k
                for k in range(len(stack) - 1, -1, -1)
                if not stack[k].raw and stripped in getattr(fam.views.get(stack[k].view), "exit", [])
            ),
            None,
        )
        if exit_at is not None:
            ef = stack[exit_at]
            out.lines.append(Line(no, raw, "command", lead, ef.view, card=f"@exit:{stripped}", parent=ef.line))
            del stack[exit_at:]
            prev_indent, prev_entered = indent, False
            continue

        # 异常缩进：比上一行深很多，而上一行没有进入子视图 → 视作与上一行同级
        if indent > prev_indent + 1 and not prev_entered:
            indent = prev_indent
        while stack and stack[-1].indent >= indent:
            stack.pop()
        frame = stack[-1] if stack else None
        view = frame.view if frame else fam.root_view
        parent = frame.line if frame else None

        if frame is not None and frame.raw:
            out.lines.append(Line(no, raw, "raw", lead, view, parent=parent))
            stack.append(_Frame(indent, view, no, raw=True))
            prev_indent, prev_entered = indent, True
            continue

        if stripped.split()[0].lower() == index.negative:
            neg = match_undo(index, view, stripped)
            if neg:
                card, m, usyn = neg
                line = Line(no, raw, "command", lead, view, card.id, m, parent, card.domain, negated=True)
                if syn.render(usyn, m) != stripped:
                    line.fmt = stripped
                out.lines.append(line)
                prev_indent, prev_entered = indent, False
                continue

        hit = match_line(index, view, stripped)
        if hit:
            card, m = hit
            line = Line(no, raw, "command", lead, view, card.id, m, parent, card.domain)
            rendered = syn.render(card.parsed, m)
            if rendered != stripped:
                line.fmt = stripped  # 只差空白（例如多个空格）；保留原文
            out.lines.append(line)
            entered = bool(card.enters_view)
            if entered:
                stack.append(_Frame(indent, str(card.enters_view), no))
            prev_indent, prev_entered = indent, entered
            continue

        kind = "unknown" if index.known_prefix(view, stripped.split()) else "raw"
        out.lines.append(Line(no, raw, kind, lead, view, parent=parent))
        # 不认识的行下面若有更深缩进的子行，整块作为 raw（例如 ospf 1 下面的配置）
        stack.append(_Frame(indent, view, no, raw=True))
        prev_indent, prev_entered = indent, True
    return out


def normalize_pattern(text: str) -> str:
    """未识别行的归一化形态：数字、IP、名称替换成占位符，便于按频率汇总。"""
    t = re.sub(r"\b\d+\.\d+\.\d+\.\d+(/\d+)?\b", "<ip>", text)
    t = re.sub(r"\b\d+\b", "<n>", t)
    return t
