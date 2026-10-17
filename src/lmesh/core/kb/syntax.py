"""命令卡语法：解析、匹配配置行、按匹配结果渲染。

语法写法（厂商无关）：
    peer <ipv4-address> timer keepalive <keepalive-time> hold <hold-time>
    ip route-static [ vpn-instance <vpn-instance-name> ] <ip-address> { <mask> | <mask-length> } <next-hop>
- 关键字直接写；参数用 <名称>；可选部分用 [ ]；多选一用 { a | b }。
- 参数的类型来自命令卡的 params（integer / ipv4 / mask / prefix / word / text …）；text 吃掉行尾剩余的全部内容（含空格）。

匹配结果 Match 记录参数取值，以及每个可选组是否出现、每个多选组选了哪一支（按组在语法中的先序编号），
渲染时按同样的选择重放，保证“配置 → 图 → 配置”逐字一致。
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

_TOKEN = re.compile(r"\[|\]|\{|\}|\||<[^<>\s]+>|[^\s\[\]{}|<>]+")


class SyntaxErrorKB(ValueError):
    """命令卡语法写错了。"""


@dataclass
class Kw:
    word: str


@dataclass
class Param:
    name: str


@dataclass
class Opt:
    gid: int
    body: list[Node]


@dataclass
class Choice:
    gid: int
    alts: list[list[Node]]


Node = Kw | Param | Opt | Choice


@dataclass
class Syntax:
    text: str
    nodes: list[Node]

    def params(self) -> list[str]:
        out: list[str] = []

        def walk(ns: list[Node]) -> None:
            for n in ns:
                if isinstance(n, Param):
                    out.append(n.name)
                elif isinstance(n, Opt):
                    walk(n.body)
                elif isinstance(n, Choice):
                    for a in n.alts:
                        walk(a)

        walk(self.nodes)
        return out

    def first_keyword(self) -> str | None:
        n = self.nodes[0] if self.nodes else None
        return n.word if isinstance(n, Kw) else None


def parse(text: str) -> Syntax:
    toks = _TOKEN.findall(text)
    pos = 0
    gid = 0

    def seq(stop: set[str]) -> list[Node]:
        nonlocal pos, gid
        out: list[Node] = []
        while pos < len(toks) and toks[pos] not in stop:
            t = toks[pos]
            if t == "[":
                pos += 1
                gid += 1
                my = gid
                body = seq({"]"})
                if pos >= len(toks) or toks[pos] != "]":
                    raise SyntaxErrorKB(f"缺少 ]：{text}")
                pos += 1
                out.append(Opt(my, body))
            elif t == "{":
                pos += 1
                gid += 1
                my = gid
                alts = [seq({"|", "}"})]
                while pos < len(toks) and toks[pos] == "|":
                    pos += 1
                    alts.append(seq({"|", "}"}))
                if pos >= len(toks) or toks[pos] != "}":
                    raise SyntaxErrorKB(f"缺少 }}：{text}")
                pos += 1
                out.append(Choice(my, alts))
            elif t in ("]", "}", "|"):
                raise SyntaxErrorKB(f"多余的 {t}：{text}")
            elif t.startswith("<"):
                out.append(Param(t[1:-1]))
                pos += 1
            else:
                out.append(Kw(t))
                pos += 1
        return out

    nodes = seq(set())
    if pos != len(toks):
        raise SyntaxErrorKB(f"无法解析：{text}")
    if not nodes:
        raise SyntaxErrorKB("语法为空")
    return Syntax(text, nodes)


# ---------- 参数类型 ----------

_IPV4 = re.compile(r"^(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}$")


def _int_ok(v: str, spec: dict[str, Any]) -> bool:
    if not re.fullmatch(r"\d+", v):
        return False
    rng = spec.get("range")
    if rng and len(rng) == 2:
        return int(rng[0]) <= int(v) <= int(rng[1])
    return True


def _mask_ok(v: str) -> bool:
    if not _IPV4.match(v):
        return False
    n = int(ipaddress.IPv4Address(v))
    inv = (~n) & 0xFFFFFFFF
    return (inv & (inv + 1)) == 0


TYPE_CHECKS: dict[str, Any] = {
    "integer": _int_ok,
    "ipv4": lambda v, s: bool(_IPV4.match(v)),
    "mask": lambda v, s: _mask_ok(v),
    "wildcard": lambda v, s: bool(_IPV4.match(v)),
    "prefix": lambda v, s: bool(re.fullmatch(r"[\d.]+/\d{1,2}", v)) and bool(_IPV4.match(v.split("/")[0])),
    "mask-length": lambda v, s: v.isdigit() and 0 <= int(v) <= 32,
    "asn": lambda v, s: bool(re.fullmatch(r"\d+(?:\.\d+)?", v)),
    "rd": lambda v, s: bool(re.fullmatch(r"[\d.]+:\d+", v)),
    "community": lambda v, s: bool(re.fullmatch(r"\d+:\d+|[A-Za-z][\w-]*", v)),
    "interface": lambda v, s: bool(re.fullmatch(r"[A-Za-z][A-Za-z\-]*[\d/.:]*\d[\d/.:]*|[A-Za-z]+\d*", v)),
    "word": lambda v, s: True,
    "string": lambda v, s: True,
    "text": lambda v, s: True,
}


def type_ok(value: str, spec: dict[str, Any] | None) -> bool:
    spec = spec or {}
    t = spec.get("type", "word")
    choices = spec.get("choices")
    if choices and value not in choices:
        return False
    check = TYPE_CHECKS.get(t, TYPE_CHECKS["word"])
    return bool(check(value, spec))


# ---------- 匹配 ----------


@dataclass
class Match:
    values: dict[str, str] = field(default_factory=dict)
    opts: dict[int, bool] = field(default_factory=dict)  # 可选组是否出现
    choices: dict[int, int] = field(default_factory=dict)  # 多选组选了第几支
    keywords: int = 0  # 匹配上的关键字数（越多越具体）

    def copy(self) -> Match:
        return Match(dict(self.values), dict(self.opts), dict(self.choices), self.keywords)


def tokenize_line(line: str) -> list[tuple[str, int]]:
    """配置行 → [(词, 起始位置)]，位置用于 text 参数取原文。"""
    return [(m.group(0), m.start()) for m in re.finditer(r"\S+", line)]


def match(syn: Syntax, line: str, params: dict[str, dict[str, Any]] | None = None) -> Match | None:
    """整行匹配；有多种匹配时取关键字最多的一种。匹配不上返回 None。"""
    params = params or {}
    toks = tokenize_line(line)
    best: Match | None = None
    for i, m in _match_seq(syn.nodes, toks, 0, Match(), params, line):
        if i == len(toks) and (best is None or m.keywords > best.keywords):
            best = m
    return best


def _match_seq(
    nodes: list[Node], toks: list[tuple[str, int]], i: int, m: Match, params: dict[str, dict[str, Any]], line: str
) -> Iterator[tuple[int, Match]]:
    if not nodes:
        yield i, m
        return
    head, rest = nodes[0], nodes[1:]
    if isinstance(head, Kw):
        if i < len(toks) and toks[i][0].lower() == head.word.lower():
            m2 = m.copy()
            m2.keywords += 1
            yield from _match_seq(rest, toks, i + 1, m2, params, line)
    elif isinstance(head, Param):
        spec = params.get(head.name, {})
        if spec.get("type") == "text":
            if i < len(toks):
                m2 = m.copy()
                m2.values[head.name] = line[toks[i][1] :].rstrip()
                yield from _match_seq(rest, toks, len(toks), m2, params, line)
        elif i < len(toks) and type_ok(toks[i][0], spec):
            m2 = m.copy()
            m2.values[head.name] = toks[i][0]
            yield from _match_seq(rest, toks, i + 1, m2, params, line)
    elif isinstance(head, Opt):
        # 先试“出现”，再试“不出现”
        m_in = m.copy()
        m_in.opts[head.gid] = True
        for j, m3 in _match_seq(head.body, toks, i, m_in, params, line):
            if j > i:
                yield from _match_seq(rest, toks, j, m3, params, line)
        m_out = m.copy()
        m_out.opts[head.gid] = False
        yield from _match_seq(rest, toks, i, m_out, params, line)
    elif isinstance(head, Choice):
        for k, alt in enumerate(head.alts):
            m_c = m.copy()
            m_c.choices[head.gid] = k
            for j, m3 in _match_seq(alt, toks, i, m_c, params, line):
                yield from _match_seq(rest, toks, j, m3, params, line)


# ---------- 渲染 ----------


def render(syn: Syntax, m: Match) -> str:
    """按匹配记录重放：同样的参数与选择得到同样的文本（词之间一个空格）。"""
    out: list[str] = []

    def walk(ns: list[Node]) -> None:
        for n in ns:
            if isinstance(n, Kw):
                out.append(n.word)
            elif isinstance(n, Param):
                if n.name not in m.values:
                    raise KeyError(n.name)
                out.append(m.values[n.name])
            elif isinstance(n, Opt):
                present = m.opts.get(n.gid)
                if present is None:  # 没有记录时：组内参数都有值才输出
                    present = all(p in m.values for p in _params_in(n.body)) and bool(_params_in(n.body))
                if present:
                    walk(n.body)
            elif isinstance(n, Choice):
                k = m.choices.get(n.gid)
                if k is None:
                    k = next((idx for idx, a in enumerate(n.alts) if all(p in m.values for p in _params_in(a))), 0)
                walk(n.alts[k])

    walk(syn.nodes)
    return " ".join(out)


def _params_in(ns: list[Node]) -> list[str]:
    return Syntax("", ns).params()
