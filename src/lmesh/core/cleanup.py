"""冗余清理：为孤儿对象（含级联孤儿）生成删除命令脚本，并在图上验证删除后不产生新的悬空引用。

删除命令：
    - 只对对象的入口命令取反（route-policy X permit node 10 → undo route-policy X node 10；route-map X permit 10 → no route-map X …），
      对象由多个入口组成时（策略的多个节点、前缀列表的多条规则）逐个删除；入口下的子命令随入口一起删除；
    - 用命令卡的取消语法（undo / no）按原行的参数渲染：只使用原行中出现过的关键字，参数取原行的取值，取最具体的写法；
    - 命令卡没有取消语法、或取消语法用原行的参数渲染不出来时，用平台族的取消前缀 + 原命令兜底，并标注 fallback（需人工确认）。
顺序：先删引用方再删被引用方（级联孤儿排在引用它的孤儿之后）；同一层按原配置行号。
对象在某个视图里（例如 BGP 视图中的对等体组）时，先输出进入视图的原命令，命令缩进一级，最后退出视图。
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from typing import Any

import networkx as nx

from lmesh.core import checks
from lmesh.core import graph as graphmod
from lmesh.core import parser as parsermod
from lmesh.core.kb import KnowledgeBase
from lmesh.core.kb import syntax as syn
from lmesh.core.parser import Line

_MAX_EXPANSIONS = 4000


# ---------- 取消语法的渲染 ----------


def _expand(nodes: list[syn.Node], values: dict[str, Any]) -> Iterator[tuple[list[str], list[str], int]]:
    """按参数取值展开语法：产出 (词, 其中的关键字, 用到的参数个数)。参数没有取值的分支不产出。"""
    if not nodes:
        yield [], [], 0
        return
    for w1, k1, p1 in _one(nodes[0], values):
        for w2, k2, p2 in _expand(nodes[1:], values):
            yield w1 + w2, k1 + k2, p1 + p2


def _one(n: syn.Node, values: dict[str, Any]) -> Iterator[tuple[list[str], list[str], int]]:
    if isinstance(n, syn.Kw):
        yield [n.word], [n.word.lower()], 0
    elif isinstance(n, syn.Param):
        v = values.get(n.name)
        if isinstance(v, list):
            v = v[0] if len(v) == 1 else None
        if v not in (None, ""):
            yield [str(v)], [], 1
    elif isinstance(n, syn.Opt):
        yield from _expand(n.body, values)
        yield [], [], 0
    elif isinstance(n, syn.Choice):
        for alt in n.alts:
            yield from _expand(alt, values)
    elif isinstance(n, syn.Rep):
        inner = syn.Syntax("", [n.node]).params()
        lists = [values[p] for p in inner if isinstance(values.get(p), list)]
        rounds = max((len(x) for x in lists), default=1 if all(p in values for p in inner) and inner else 0)
        words: list[str] = []
        kws: list[str] = []
        used = 0
        for i in range(rounds):
            sub = {
                **values,
                **{p: (values[p][i] if i < len(values[p]) else None) for p in inner if isinstance(values.get(p), list)},
            }
            best = max(_one(n.node, sub), key=lambda x: x[2], default=None)
            if best is None:
                return
            words += best[0]
            kws += best[1]
            used += best[2]
        if rounds or isinstance(n.node, syn.Opt):
            yield words, kws, used


def render_undo(card: Any, line: Line, negative: str) -> tuple[str, bool]:
    """返回 (取消命令, 是否兜底)。"""
    original = {w.lower() for w in line.text.split()}
    if card is not None and card.undo:
        try:
            usyn = syn.parse(card.undo)
        except syn.SyntaxErrorKB:
            usyn = None
        if usyn is not None:
            best: tuple[int, int, str] | None = None
            for words, kws, used in itertools.islice(_expand(usyn.nodes, line.values()), _MAX_EXPANSIONS):
                if not words or words[0].lower() != negative or not set(kws[1:]) <= original:
                    continue
                text = " ".join(words)
                if syn.match(usyn, text, card.params) is None:
                    continue
                score = (used, -len(words), text)
                if best is None or score[:2] > best[:2]:
                    best = score
            if best is not None:
                return best[2], False
    return f"{negative} {line.text}", True


# ---------- 清理脚本 ----------


def _entry_lines(g: nx.MultiDiGraph, ix: checks.Index, obj: str) -> list[int]:
    """对象的入口命令：子树中每个对象第一次出现的行，且不在子树其他行的视图之内。"""
    sub = ix.subtree(obj)
    lines: set[int] = set()
    for n in sub:
        lines.update(g.nodes[n].get("lines") or [])
    out = set()
    for n in sub:
        d = g.nodes[n]
        if d.get("kind") == "object" and d.get("lines"):
            first = min(d["lines"])
            ln = ix.lines.get(first)
            if ln is None or ln.kind != "command" or not ln.card or ln.card.startswith("@"):
                continue
            if not any(p in lines for p in ix.context(first)):
                out.add(first)
    return sorted(out)


def _order(g: nx.MultiDiGraph, ix: checks.Index, objs: list[str]) -> list[str]:
    """引用方在前：对象之间的引用关系做拓扑排序，同层按行号。"""
    dg = nx.DiGraph()
    first = {o: min(g.nodes[o].get("lines") or [0]) for o in objs}
    dg.add_nodes_from(objs)
    subs = {o: ix.subtree(o) for o in objs}
    for x in objs:
        for t in subs[x]:
            for a in ix.ref_in.get(t, []):
                for y in objs:
                    if y != x and a in subs[y]:
                        dg.add_edge(y, x)
    try:
        return list(nx.lexicographical_topological_sort(dg, key=lambda o: (first[o], o)))
    except nx.NetworkXUnfeasible:  # 互相引用：按行号
        return sorted(objs, key=lambda o: (first[o], o))


def _exit_word(kb: KnowledgeBase, family: str) -> str:
    return "quit" if kb.families[family].negative == "undo" else "exit"


def cleanup(g: nx.MultiDiGraph, kb: KnowledgeBase, verify: bool = True) -> dict[str, Any]:
    ix = checks.Index.of(g, kb)
    family = str(g.graph.get("family") or kb.profiles[str(g.graph["profile"])].family)
    negative = kb.families[family].negative
    orph = checks.find_orphans(g, kb, ix)
    order = _order(g, ix, orph.removal())
    objects: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []
    seen: dict[tuple[tuple[str, ...], str], dict[str, Any]] = {}
    for o in order:
        d = g.nodes[o]
        objects.append(
            {
                "node": o,
                "schema": d.get("schema"),
                "key": checks.rulesmod.key_text(d.get("key")),
                "reason": "cascade" if o in orph.cascade else "orphan",
                "via": orph.cascade.get(o, []),
                "lines": sorted(ix.subtree_lines(ix.subtree(o))),
            }
        )
        for no in _entry_lines(g, ix, o):
            ln = ix.lines[no]
            card = kb.cards.get(str(ln.card))
            text, fallback = render_undo(card, ln, negative)
            ctx = tuple(ix.lines[p].text for p in ix.context(no))
            hit = seen.get((ctx, text))
            if hit is not None:  # 同一条命令删除整个对象（例如 no ip community-list standard X）：只输出一次
                hit["lines"].append(no)
                continue
            cmd = {
                "seq": len(commands) + 1,
                "text": text,
                "context": list(ctx),
                "object": o,
                "lines": [no],
                "card": ln.card,
                "fallback": fallback,
            }
            seen[(ctx, text)] = cmd
            commands.append(cmd)
    result: dict[str, Any] = {
        "device": g.graph.get("device"),
        "profile": g.graph.get("profile"),
        "family": family,
        "objects": objects,
        "commands": commands,
        "skipped": [{"node": o, "reason": "maybe_referenced", "lines": lines} for o, lines in orph.unsure.items()],
        "fallbacks": sum(1 for c in commands if c["fallback"]),
        "script": script_text(commands, g, _exit_word(kb, family)),
    }
    if verify:
        result["verify"] = verify_removal(g, kb, [o["node"] for o in objects])
    return result


def script_text(commands: list[dict[str, Any]], g: nx.MultiDiGraph, exit_word: str) -> str:
    """脚本文本：! 开头的行是注释（两家的配置里都按注释处理），注明删除的对象与原配置行号；兜底命令标 FALLBACK。"""
    out = [f"! lmesh cleanup: {g.graph.get('device')} ({g.graph.get('profile')}), {len(commands)} command(s)"]
    for c in commands:
        depth = len(c["context"])
        lines = ",".join(str(n) for n in c["lines"])
        out.append(f"! [{c['seq']}] {c['object']} @{lines}" + (" FALLBACK" if c["fallback"] else ""))
        out += [" " * i + t for i, t in enumerate(c["context"])]
        out.append(" " * depth + c["text"])
        out += [" " * (depth - 1 - i) + exit_word for i in range(depth)]
    return "\n".join(out) + "\n"


# ---------- 验证：在图上去掉这些对象后重新检查 ----------


def removal_text(g: nx.MultiDiGraph, kb: KnowledgeBase, objs: list[str]) -> str:
    """去掉对象子树的全部行（含入口下的子行）后的配置文本：等价于在设备上执行删除脚本后的配置。"""
    ix = checks.Index.of(g, kb)
    drop: set[int] = set()
    for o in objs:
        drop |= ix.subtree_lines(ix.subtree(o))
    return "\n".join(st.line.raw for st in g.graph.get("statements", []) if st.line.no not in drop)


def _dangling_keys(g: nx.MultiDiGraph, kb: KnowledgeBase) -> set[tuple[str, str, str]]:
    return {(d["referrer"], str(d["target_type"]), str(d["value"])) for d in checks.dangling(g, kb)}


def verify_removal(g: nx.MultiDiGraph, kb: KnowledgeBase, objs: list[str]) -> dict[str, Any]:
    profile = str(g.graph["profile"])
    text = removal_text(g, kb, objs)
    parsed = parsermod.parse(text, kb, kb.profiles[profile].family)
    after = graphmod.build(parsed, kb, profile, str(g.graph.get("device") or "device"))
    before_keys, after_keys = _dangling_keys(g, kb), _dangling_keys(after, kb)
    new = sorted(after_keys - before_keys)
    remaining = [o for o in objs if o in after]
    left = checks.find_orphans(after, kb).removal()
    return {
        "ok": not new and not remaining and not left,
        "dangling_before": len(before_keys),
        "dangling_after": len(after_keys),
        "new_dangling": [{"referrer": r, "target_type": t, "value": v} for r, t, v in new],
        "remaining_objects": remaining,
        "new_orphans": left,
    }
