"""渲染：图 → 配置文本。

往返模式（render_roundtrip）：按原始语句顺序回放，原文行（分隔、注释、功能域外、未识别）原样输出；命令行用命令卡语法
（undo / no 形式用取消语法）重放匹配记录，其中能直接对应到参数的取值从图节点读取（节点的原文取值），
因此往返一致说明图中的取值足以重建配置。
"""

from __future__ import annotations

import networkx as nx

from lmesh.core.graph import Statement
from lmesh.core.kb import KnowledgeBase
from lmesh.core.kb import syntax as syn


def _render_command(st: Statement, g: nx.MultiDiGraph, kb: KnowledgeBase) -> str:
    ln = st.line
    if not ln.card or ln.card.startswith("@") or ln.match is None:
        return ln.raw
    card = kb.cards[ln.card]
    m = ln.match.copy()
    # 取值以图为准：直接映射到节点的参数，从节点的原文取值取回
    for param, nid in st.sources.items():
        if nid in g and param in m.values:
            raw = g.nodes[nid].get("raw")
            if raw is not None and not isinstance(raw, list | dict):
                m.values[param] = str(raw)
    if ln.fmt is not None:
        body = ln.fmt  # 原文只在空白上与标准写法不同
    elif ln.negated:
        try:
            usyn = syn.parse(card.undo) if card.undo else None
            quotes = kb.families[card.family].quotes if card.family in kb.families else False
            matched = usyn is not None and syn.match(usyn, ln.text, card.params, quotes) is not None
        except syn.SyntaxErrorKB:
            usyn, matched = None, False
        if usyn is not None and matched:
            body = syn.render(usyn, m)
        else:  # 只有关键字的取消形式（no ip address / undo shutdown）
            body = " ".join([ln.text.split()[0], *card.parsed.leading_keywords()])
    else:
        body = syn.render(card.parsed, m)
    return ln.indent + body


def render_roundtrip(g: nx.MultiDiGraph, kb: KnowledgeBase) -> str:
    out: list[str] = []
    for st in g.graph.get("statements", []):
        if st.line.kind == "command":
            out.append(_render_command(st, g, kb))
        else:
            out.append(st.line.raw)
    return "\n".join(out)
