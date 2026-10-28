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

平台族 views.yaml 的 block: exit（Nokia Classic）用另一种分块方式（_parse_exit_blocks）：缩进按 indent 个空格折算层级；
每个块由与开头同列的 exit 关闭（原文块也一样）；exit all 清空视图栈；configure 等结构行进入根视图；
# 注释、echo 版式行与分隔行不改变视图栈；没有进入视图的命令下面若有更深缩进的子行，子行按原文保留。
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from lmesh.core.kb import KnowledgeBase
from lmesh.core.kb import syntax as syn
from lmesh.core.kb.model import Card, Family

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
    # M7-4（Nokia MD-CLI，block: braces）：prefix 是扁平格式里命令前面的路径（/configure router "Base" interface "x" ），
    # tail 是行尾的花括号（" {" 进入块，" { }" 空块）；virtual 是扁平格式按路径补出的容器 / 列表行（原文里没有单独的一行，
    # 编号接在最后一行之后，往返时不输出）。text 是去掉 prefix 与 tail 的命令本身
    prefix: str = ""
    tail: str = ""
    virtual: bool = False

    @property
    def text(self) -> str:
        if self.prefix or self.tail:
            body = self.raw[len(self.indent) + len(self.prefix) :]
            return (body[: len(body) - len(self.tail)] if self.tail else body).strip()
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
        if self.virtual:
            d["virtual"] = True
        return d


@dataclass
class Parsed:
    family: str
    lines: list[Line] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for ln in self.lines:
            if not ln.virtual:  # 扁平格式补出的路径行不是原文的行
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
        self.root_view = kb.families[family].root_view
        self.quotes = kb.families[family].quotes
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
                # 整条语法只有一个关键字的卡（华为接口下的 mpls、shutdown）只说明这一个词：
                # 不把“以它开头的其他命令”（mpls te、mpls rsvp-te，属于范围外的功能）算作知识库缺口
                if len(lead) > 1 or len(c.parsed.nodes) > 1:
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
        self.enters = {c.id: str(c.enters_view) for c in kb.cards_of(family) if c.enters_view}
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
    begin: bool = False  # 结构行打开的块（MD-CLI 的 configure {）


def match_undo(index: CardIndex, view: str, text: str) -> tuple[Card, syn.Match, syn.Syntax] | None:
    """取消形式：先按命令卡的 undo 语法匹配；匹配不上时，“取消前缀 + 某张卡开头的全部关键字”也算（no ip address）。"""
    best: tuple[Card, syn.Match, syn.Syntax] | None = None
    for card, usyn in index.undo.get(view, []):
        m = syn.match(usyn, text, card.params, index.quotes)
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
                m = syn.match(bare, text, {}, index.quotes)
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
            m = syn.match(card.parsed, text, card.params, index.quotes)
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


def _abnormal_depth(stack: list[_Frame], indent: int, index: CardIndex, stripped: str) -> int | None:
    """异常缩进的行：在当前视图匹配得到时返回 None（照常处理）；否则从内往外找第一个能匹配的外层视图，
    返回应保留的栈深度（栈中这一层以内的帧保留）。都匹配不到时返回 None。"""
    frames = [f for f in stack if f.indent < indent] or []
    if not frames or frames[-1].raw:
        return None

    def matches(view: str) -> bool:
        if stripped.split()[0].lower() == index.negative and match_undo(index, view, stripped):
            return True
        return match_line(index, view, stripped) is not None

    if matches(frames[-1].view):
        return None
    if not index.prefixes.get(frames[-1].view):
        return None  # 当前视图没有任何命令卡（范围外的块，内容按原文保留）：不往外层找，免得把块内的行算到外层
    for depth in range(len(frames) - 1, 0, -1):
        if frames[depth - 1].raw:
            return None
        if matches(frames[depth - 1].view):
            return depth
    return 0 if matches(index.root_view) else None


def parse(text: str, kb: KnowledgeBase, family: str) -> Parsed:
    fam = kb.families[family]
    index = CardIndex(kb, family)
    if fam.block == "exit":
        return _parse_exit_blocks(text, fam, index, Parsed(family))
    if fam.block == "braces":
        return _parse_brace_blocks(text, fam, index, Parsed(family))
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

        # 异常缩进：比上一行深很多，而上一行没有进入子视图 → 视作与上一行同级；
        # 如果在上一行的视图里匹配不到，再逐级往外层视图找（分页痕迹可能出现在一个子视图块的第一行，
        # 例如 OSPF 的 frr 块之后的 “                 area 0.0.0.8”），匹配到哪一层就按那一层的缩进算
        # 上一行刚进入子视图时，异常缩进的行先当作子视图的第一行；子视图里匹配不到、外层视图匹配得到时按外层算
        # （例如 VPN 实例的 ipv4-family 之后分页痕迹缩进的 “                 ipv6-family”）
        if indent > prev_indent + 1:
            indent = prev_indent + 1 if prev_entered else prev_indent
            depth = _abnormal_depth(stack, indent, index, stripped)
            if depth is not None:
                del stack[depth:]
                indent = stack[-1].indent + 1 if stack else 0
        while stack and stack[-1].indent >= indent:
            stack.pop()
        frame = stack[-1] if stack else None
        view = frame.view if frame else fam.root_view
        parent = frame.line if frame else None

        if frame is not None and frame.raw:
            out.lines.append(Line(no, raw, "raw", lead, view, parent=parent))
            stack.append(_Frame(indent, view, no, raw=True))
            # 原文块里同样识别分页痕迹：比上一行深一级以上的行视作同级（正常的子行只深一级）
            prev_indent, prev_entered = indent, False
            continue

        if stripped.split()[0].lower() == index.negative:
            neg = match_undo(index, view, stripped)
            if neg:
                card, m, usyn = neg
                line = Line(no, raw, "command", lead, view, card.id, m, parent, card.domain, negated=True)
                body = raw[len(lead) :]
                if syn.render(usyn, m) != body:
                    line.fmt = body  # 只差空白（多个空格、行尾空格）；保留原文
                out.lines.append(line)
                prev_indent, prev_entered = indent, False
                continue

        hit = match_line(index, view, stripped)
        if hit:
            card, m = hit
            line = Line(no, raw, "command", lead, view, card.id, m, parent, card.domain)
            rendered = syn.render(card.parsed, m)
            body = raw[len(lead) :]
            if rendered != body:
                line.fmt = body  # 只差空白（例如多个空格、行尾空格）；保留原文
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
        prev_indent, prev_entered = indent, False
    return out


def _command_line(index: CardIndex, view: str, no: int, raw: str, lead: str, parent: int | None) -> Line | None:
    """在视图里匹配一行（先取消形式，再普通形式）；匹配不上返回 None。"""
    stripped = raw.strip()
    body = raw[len(lead) :]
    if stripped.split()[0].lower() == index.negative:
        neg = match_undo(index, view, stripped)
        if neg:
            card, m, usyn = neg
            line = Line(no, raw, "command", lead, view, card.id, m, parent, card.domain, negated=True)
            if syn.render(usyn, m) != body:
                line.fmt = body
            return line
    hit = match_line(index, view, stripped)
    if hit is None:
        return None
    card, m = hit
    line = Line(no, raw, "command", lead, view, card.id, m, parent, card.domain)
    if syn.render(card.parsed, m) != body:
        line.fmt = body
    return line


def _parse_exit_blocks(text: str, fam: Family, index: CardIndex, out: Parsed) -> Parsed:
    """Nokia Classic 的分块：层级 = 缩进 / indent；块由同列的 exit 关闭（见模块说明）。"""
    unit = max(fam.indent, 1)
    layout = [re.compile(p) for p in fam.layout]
    stack: list[_Frame] = []  # _Frame.indent 存层级
    for no, raw in enumerate(text.split("\n"), start=1):
        stripped = raw.strip()
        lead = raw[: len(raw) - len(raw.lstrip())]
        if not stripped:
            out.lines.append(Line(no, raw, "blank", lead))
            continue
        if stripped == fam.separator:
            out.lines.append(Line(no, raw, "separator", lead))
            continue
        if any(stripped.startswith(c) for c in fam.comment) or any(p.search(stripped) for p in layout):
            out.lines.append(Line(no, raw, "comment", lead))
            continue
        if fam.end and stripped == fam.end:
            out.lines.append(Line(no, raw, "end", lead))
            stack.clear()
            continue
        if stripped in fam.begin and not lead:
            out.lines.append(Line(no, raw, "separator", lead))
            stack.clear()
            continue
        level = (len(lead.expandtabs(unit)) + unit - 1) // unit
        if stripped == "exit":
            while stack and stack[-1].indent > level:
                stack.pop()
            if stack and stack[-1].indent == level:
                fr = stack.pop()
                if fr.raw:
                    out.lines.append(Line(no, raw, "raw", lead, fr.view, parent=fr.line))
                else:
                    out.lines.append(Line(no, raw, "command", lead, fr.view, card="@exit:exit", parent=fr.line))
            else:  # 没有对应的块（多余的 exit）：原文保留
                frame = stack[-1] if stack else None
                out.lines.append(
                    Line(
                        no,
                        raw,
                        "raw",
                        lead,
                        frame.view if frame else fam.root_view,
                        parent=frame.line if frame else None,
                    )
                )
            continue
        while stack and stack[-1].indent >= level:
            stack.pop()
        frame = stack[-1] if stack else None
        view = frame.view if frame else fam.root_view
        parent = frame.line if frame else None
        if frame is not None and frame.raw:
            out.lines.append(Line(no, raw, "raw", lead, view, parent=parent))
            stack.append(_Frame(level, view, no, raw=True))
            continue
        line = _command_line(index, view, no, raw, lead, parent)
        if line is not None:
            out.lines.append(line)
            enters = index_card_enters(index, line)
            # 没有进入视图的命令：下面若有更深的子行（范围外的子上下文），按原文块保留
            stack.append(_Frame(level, enters or view, no, raw=not enters))
            continue
        kind = "unknown" if index.known_prefix(view, stripped.split()) else "raw"
        out.lines.append(Line(no, raw, kind, lead, view, parent=parent))
        stack.append(_Frame(level, view, no, raw=True))
    return out


_BRACE_TAIL = re.compile(r"\s*\{\s*\}?\s*$")


def _match_core(index: CardIndex, view: str, core: str) -> tuple[Card, syn.Match, bool, syn.Syntax] | None:
    """在视图里整行匹配命令本身（先取消形式，再普通形式）：(卡, 匹配, 是否取消形式, 用来渲染的语法)。"""
    if core.split()[0].lower() == index.negative:
        neg = match_undo(index, view, core)
        if neg:
            return neg[0], neg[1], True, neg[2]
    hit = match_line(index, view, core)
    return (hit[0], hit[1], False, hit[0].parsed) if hit else None


def _consume_path(
    index: CardIndex, view: str, core: str
) -> tuple[list[tuple[str, Card, syn.Match, str, str]], int, tuple[Card, syn.Match, bool, syn.Syntax] | None]:
    """扁平格式（info flat / full-context）：从 view 起逐段消耗路径。每段是一张进入视图的卡（容器、列表项），
    能整行匹配剩余部分时停止。返回 ([(段落原文, 卡, 匹配, 所在视图, 进入的视图)], 剩余部分在 core 中的起点, 剩余部分的匹配)。"""
    toks = syn.tokenize_line(core, index.quotes)
    segs: list[tuple[str, Card, syn.Match, str, str]] = []
    i = 0
    while i < len(toks):
        if i > 0:  # 第一段就整行匹配的情况调用方已经试过
            whole = _match_core(index, view, core[toks[i][1] :])
            if whole is not None:
                return segs, toks[i][1], whole
        found = None
        for k in range(min(len(toks) - 1, i + 7), i, -1):  # 最长的一段（多个键：route <前缀> route-type <类型>）
            piece = core[toks[i][1] : toks[k - 1][1] + len(toks[k - 1][0])]
            hit = match_line(index, view, piece)
            if hit and index.enters.get(hit[0].id):
                found = (piece, hit[0], hit[1], view, index.enters[hit[0].id], k)
                break
        if found is None:
            break
        segs.append(found[:5])
        view, i = found[4], found[5]
    return segs, (toks[i][1] if i < len(toks) else len(core)), None


def _parse_brace_blocks(text: str, fam: Family, index: CardIndex, out: Parsed) -> Parsed:
    """Nokia MD-CLI 的分块（block: braces）：层级以花括号为准，缩进只是排版。
    - “name … {” 进入块（命令卡进入的视图；匹配不上或卡不进入视图时块内按原文保留），“}” 关闭最近的块，“name … { }” 是空块；
    - 结构行（configure {）进入根视图，它的 } 也是结构行；# 开头是注释；
    - 扁平格式（info flat 的相对路径、full-context 的 /configure …）：当前视图里整行匹配不上时按命令卡逐段消耗路径，
      路径上的每一段补一行 virtual 的命令行（相邻行的公共前缀共用同一行，相当于花括号格式的块头），剩余部分整行匹配；
      原文的行记下路径前缀（prefix），往返时原样输出。"""
    raws = text.split("\n")
    vno = len(raws)  # 补出的路径行编号接在最后一行之后
    stack: list[_Frame] = []
    flat: list[tuple[str, str, int, str]] = []  # 当前扁平块的路径：(段落原文, 所在视图, 行号, 进入的视图)
    flat_base: tuple[int, str] | None = None  # 扁平块的起点（所在块的行号、起始视图）
    for no, raw in enumerate(raws, start=1):
        stripped = raw.strip()
        lead = raw[: len(raw) - len(raw.lstrip())]
        if not stripped:
            out.lines.append(Line(no, raw, "blank", lead))
            continue
        if any(stripped.startswith(c) for c in fam.comment):
            out.lines.append(Line(no, raw, "comment", lead))
            continue
        if stripped == "}":
            flat, flat_base = [], None
            if not stack:  # 多余的 }：原文保留
                out.lines.append(Line(no, raw, "raw", lead, fam.root_view))
                continue
            fr = stack.pop()
            if fr.begin:
                out.lines.append(Line(no, raw, "separator", lead))
            elif fr.raw:
                out.lines.append(Line(no, raw, "raw", lead, fr.view, parent=fr.line))
            else:
                out.lines.append(Line(no, raw, "command", lead, fr.view, card="@exit:}", parent=fr.line))
            continue
        body = raw[len(lead) :]
        tm = _BRACE_TAIL.search(body)
        tail = tm.group(0) if tm and tm.start() > 0 else ""
        opens = bool(tail) and "}" not in tail
        core = body[: len(body) - len(tail)].strip() if tail else stripped
        frame = stack[-1] if stack else None
        view = frame.view if frame else fam.root_view
        parent = frame.line if frame and not frame.begin else None  # configure { 下的行与没有它时一样是顶层行
        if frame is not None and frame.raw:
            out.lines.append(Line(no, raw, "raw", lead, view, parent=parent, tail=tail))
            if opens:
                stack.append(_Frame(0, view, no, raw=True))
            continue
        if core in fam.begin and frame is None:
            flat, flat_base = [], None
            out.lines.append(Line(no, raw, "separator", lead, tail=tail))
            if opens:
                stack.append(_Frame(0, fam.root_view, no, begin=True))
            continue
        prefix0 = ""
        base_view, base_parent = view, parent
        first = core.split()[0]
        if first.startswith("/") and first[1:] in fam.begin:  # full-context：/configure … 从根视图起
            rest0 = body[len(first) :]
            prefix0 = first + rest0[: len(rest0) - len(rest0.lstrip())]
            core = body[len(prefix0) : len(body) - len(tail)].strip()
            base_view, base_parent = fam.root_view, None
        whole = _match_core(index, base_view, core) if not prefix0 else None
        if whole is not None:
            flat, flat_base = [], None
            card, m, neg, usyn = whole
            line = Line(
                no, raw, "command", lead, base_view, card.id, m, base_parent, card.domain, negated=neg, tail=tail
            )
            if syn.render(usyn, m) != core:
                line.fmt = core
            out.lines.append(line)
            if opens:
                enters = index_card_enters(index, line)
                stack.append(_Frame(0, enters or base_view, no, raw=not enters))
            continue
        if prefix0:
            whole = _match_core(index, base_view, core)
            segs, at, final = ([], 0, whole) if whole is not None else _consume_path(index, base_view, core)
        else:
            segs, at, final = _consume_path(index, base_view, core)
        if not segs and final is None:
            flat, flat_base = [], None
            kind = "unknown" if index.known_prefix(base_view, core.split()) else "raw"
            out.lines.append(Line(no, raw, kind, lead, base_view, parent=base_parent, prefix=prefix0, tail=tail))
            if opens:
                stack.append(_Frame(0, base_view, no, raw=True))
            continue
        # 路径上的段：与上一行相同的前缀共用已补出的行，其余新补
        key = (base_parent or 0, base_view)
        if flat_base != key:
            flat, flat_base = [], key
        keep = 0
        while (
            keep < len(flat) and keep < len(segs) and flat[keep][0] == segs[keep][0] and flat[keep][1] == segs[keep][3]
        ):
            keep += 1
        del flat[keep:]
        pno = flat[-1][2] if flat else base_parent
        for piece, card, m, v_from, v_to in segs[keep:]:
            vno += 1
            out.lines.append(Line(vno, piece, "command", "", v_from, card.id, m, pno, card.domain, virtual=True))
            flat.append((piece, v_from, vno, v_to))
            pno = vno
        view = flat[-1][3] if flat else base_view
        full_prefix = prefix0 + core[:at]
        if final is not None:
            card, m, neg, usyn = final
            line = Line(no, raw, "command", lead, view, card.id, m, pno, card.domain, negated=neg)
            line.prefix, line.tail = full_prefix, tail
            if syn.render(usyn, m) != line.text:
                line.fmt = line.text
            out.lines.append(line)
            if opens:
                enters = index_card_enters(index, line)
                stack.append(_Frame(0, enters or view, no, raw=not enters))
            continue
        rest = core[at:]
        kind = "unknown" if rest and index.known_prefix(view, rest.split()) else "raw"
        out.lines.append(Line(no, raw, kind, lead, view, parent=pno, prefix=full_prefix, tail=tail))
        if opens:
            stack.append(_Frame(0, view, no, raw=True))
    return out


def index_card_enters(index: CardIndex, line: Line) -> str | None:
    """命令行进入的视图（取消形式不进入）。"""
    if line.negated or not line.card:
        return None
    return index.enters.get(line.card)


def line_count(text: str) -> int:
    """配置的行数：末尾的换行不算多出一行（与编辑器、wc -l 和原文面板一致，REQ-055-08）。"""
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def normalize_pattern(text: str) -> str:
    """未识别行的归一化形态：数字、IP、名称替换成占位符，便于按频率汇总。"""
    t = re.sub(r"\b\d+\.\d+\.\d+\.\d+(/\d+)?\b", "<ip>", text)
    t = re.sub(r"\b\d+\b", "<n>", t)
    return t
