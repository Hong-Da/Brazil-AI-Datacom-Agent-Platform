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


FALLBACK_REASONS = ("no_undo", "undo_invalid", "render_failed", "match_failed")


def render_undo_reason(card: Any, line: Line, negative: str, quotes: bool = False) -> tuple[str, str | None]:
    """返回 (取消命令, 兜底原因)；不兜底时原因为 None。原因：no_undo 命令卡没有取消语法、undo_invalid 取消语法写错、
    render_failed 用原行的参数渲染不出（关键字不在原行中）、match_failed 渲染结果回匹配取消语法失败。"""
    original = {w.lower() for w in line.text.split()}
    reason = "no_undo"
    if card is not None and card.undo:
        try:
            usyn = syn.parse(card.undo)
        except syn.SyntaxErrorKB:
            usyn = None
            reason = "undo_invalid"
        if usyn is not None:
            reason = "render_failed"
            best: tuple[int, int, str] | None = None
            for words, kws, used in itertools.islice(_expand(usyn.nodes, line.values()), _MAX_EXPANSIONS):
                if not words or words[0].lower() != negative or not set(kws[1:]) <= original:
                    continue
                text = " ".join(words)
                if syn.match(usyn, text, card.params, quotes) is None:
                    reason = "match_failed"
                    continue
                score = (used, -len(words), text)
                if best is None or score[:2] > best[:2]:
                    best = score
            if best is not None:
                return best[2], None
    return f"{negative} {line.text}", reason


def render_undo(card: Any, line: Line, negative: str, quotes: bool = False) -> tuple[str, bool]:
    """返回 (取消命令, 是否兜底)。"""
    text, reason = render_undo_reason(card, line, negative, quotes)
    return text, reason is not None


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


def select(orph: checks.Orphans, objects: list[str] | None) -> tuple[list[str], list[dict[str, Any]]]:
    """按选中的对象决定删除范围：(要删的对象, 跳过的对象)。

    不给 objects 时删除全部孤儿与级联孤儿。选中孤儿时，只被选中对象（及其级联孤儿）引用的级联孤儿随之删除；
    选中的级联孤儿还被没选中的孤儿引用时不能删（parent_kept）；不是孤儿的对象不删（not_orphan，名称出现在未映射行中的为 maybe_referenced）。
    """
    if objects is None:
        return orph.removal(), []
    chosen = list(dict.fromkeys(objects))
    skipped: list[dict[str, Any]] = []
    picked: set[str] = set()
    for o in chosen:
        if o in orph.orphan or o in orph.cascade:
            picked.add(o)
        elif o in orph.unsure:
            skipped.append({"node": o, "reason": "maybe_referenced", "lines": orph.unsure[o]})
        else:
            skipped.append({"node": o, "reason": "not_orphan", "lines": []})
    keep: set[str] = set()
    changed = True
    while changed:  # 级联孤儿：引用它的对象都要删时才能删；选了父对象时自动带上
        changed = False
        for c, via in orph.cascade.items():
            ok = all(v in picked and v not in keep for v in via)
            if ok and c not in picked:
                picked.add(c)
                changed = True
            elif not ok and c in picked and c not in keep:
                keep.add(c)
                changed = True
    for c in sorted(keep):
        if c in chosen:
            kept = [v for v in orph.cascade[c] if v not in picked or v in keep]
            skipped.append({"node": c, "reason": "parent_kept", "lines": [], "via": kept})
    return [o for o in orph.removal() if o in picked and o not in keep], skipped


def cleanup(
    g: nx.MultiDiGraph, kb: KnowledgeBase, verify: bool = True, objects: list[str] | None = None
) -> dict[str, Any]:
    """objects：只清理这些对象（见 select）；不给时清理全部孤儿与级联孤儿。"""
    ix = checks.Index.of(g, kb)
    family = str(g.graph.get("family") or kb.profiles[str(g.graph["profile"])].family)
    negative = kb.families[family].negative
    quotes = kb.families[family].quotes
    orph = checks.find_orphans(g, kb, ix)
    chosen = objects
    removal, picked_skipped = select(orph, chosen)
    order = _order(g, ix, removal)
    out_objects: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []
    seen: dict[tuple[tuple[str, ...], str], dict[str, Any]] = {}
    for o in order:
        d = g.nodes[o]
        out_objects.append(
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
            text, why = render_undo_reason(card, ln, negative, quotes)
            ctx = tuple(ix.lines[p].text for p in ix.context(no))
            views = [str(getattr(kb.cards.get(str(ix.lines[p].card)), "enters_view", "") or "") for p in ix.context(no)]
            hit = seen.get((ctx, text))
            if hit is not None:  # 同一条命令删除整个对象（例如 no ip community-list standard X）：只输出一次
                hit["lines"].append(no)
                continue
            cmd = {
                "seq": len(commands) + 1,
                "text": text,
                "context": list(ctx),
                "context_views": views,
                "object": o,
                "lines": [no],
                "card": ln.card,
                "fallback": why is not None,
                "fallback_reason": why,
            }
            seen[(ctx, text)] = cmd
            commands.append(cmd)
    result: dict[str, Any] = {
        "device": g.graph.get("device"),
        "profile": g.graph.get("profile"),
        "family": family,
        "objects": out_objects,
        "commands": commands,
        "selected": chosen is not None,
        "skipped": picked_skipped
        if chosen is not None
        else [{"node": o, "reason": "maybe_referenced", "lines": lines} for o, lines in orph.unsure.items()],
        "fallbacks": sum(1 for c in commands if c["fallback"]),
        "script": script_text(commands, g, _exit_word(kb, family), _comment(kb, family), _frame(kb, family)),
    }
    if verify:
        result["verify"] = verify_removal(g, kb, [o["node"] for o in out_objects], orph.removal())
    return result


def _comment(kb: KnowledgeBase, family: str) -> str:
    """说明行的前缀：华为 / Cisco 用 !（两家都按注释处理），Nokia 用 #（views.yaml 的 comment）。"""
    fam = kb.families[family]
    return fam.comment[0] if fam.comment else "!"


def _frame(kb: KnowledgeBase, family: str) -> dict[str, Any] | None:
    """Nokia（render 有 prologue 的平台族）：脚本的开头 / 结尾、缩进单位、进入视图后先写 / 退出前再写的命令；华为 / Cisco 为 None。"""
    from lmesh.core import canon

    style = canon.load_style(kb, family)
    if not style["prologue"]:
        return None
    return {
        "begin": style["prologue"],
        "finish": style["epilogue"],
        "indent": kb.families[family].indent,
        "wrap": style["wrap"],
    }


def script_text(
    commands: list[dict[str, Any]],
    g: nx.MultiDiGraph,
    exit_word: str,
    comment: str = "!",
    frame: dict[str, Any] | None = None,
) -> str:
    """脚本文本：注释行（华为 / Cisco 的 !、Nokia 的 #）注明删除的对象与原配置行号；兜底命令标 FALLBACK。
    frame（Nokia）：exit all / configure 开头、exit all 结尾，按平台族的缩进单位，policy-options 的修改包在 begin … commit 里。"""
    head = f"{comment} lmesh cleanup: {g.graph.get('device')} ({g.graph.get('profile')}), {len(commands)} command(s)"
    out = [head, *(frame["begin"] if frame else [])]
    unit = frame["indent"] if frame else 1
    wrap = frame["wrap"] if frame else {}
    for c in commands:
        depth = len(c["context"])
        views = c.get("context_views") or [""] * depth
        lines = ",".join(str(n) for n in c["lines"])
        out.append(f"{comment} [{c['seq']}] {c['object']} @{lines}" + (" FALLBACK" if c["fallback"] else ""))
        for i, t in enumerate(c["context"]):
            out.append(" " * (unit * i) + t)
            if len(wrap.get(views[i]) or []) >= 2:
                out.append(" " * (unit * (i + 1)) + wrap[views[i]][0])
        out.append(" " * (unit * depth) + c["text"])
        for i in range(depth):
            k = depth - 1 - i
            if len(wrap.get(views[k]) or []) >= 2:
                out.append(" " * (unit * (k + 1)) + wrap[views[k]][-1])
            out.append(" " * (unit * k) + exit_word)
    out += frame["finish"] if frame else []
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


def verify_removal(
    g: nx.MultiDiGraph, kb: KnowledgeBase, objs: list[str], known_orphans: list[str] | None = None
) -> dict[str, Any]:
    """known_orphans：删除前就是孤儿、这次没选中的对象，删除后仍是孤儿不算新问题。"""
    profile = str(g.graph["profile"])
    text = removal_text(g, kb, objs)
    parsed = parsermod.parse(text, kb, kb.profiles[profile].family)
    after = graphmod.build(parsed, kb, profile, str(g.graph.get("device") or "device"))
    before_keys, after_keys = _dangling_keys(g, kb), _dangling_keys(after, kb)
    new = sorted(after_keys - before_keys)
    remaining = [o for o in objs if o in after]
    before = set(known_orphans or [])
    left = [o for o in checks.find_orphans(after, kb).removal() if o not in before]
    return {
        "ok": not new and not remaining and not left,
        "dangling_before": len(before_keys),
        "dangling_after": len(after_keys),
        "new_dangling": [{"referrer": r, "target_type": t, "value": v} for r, t, v in new],
        "remaining_objects": remaining,
        "new_orphans": left,
    }
