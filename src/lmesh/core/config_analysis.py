"""设备配置分析（REQ-034）：分析摘要与结构化脚本的数据。CLI（lmesh analyze）与 API（/devices/{id}/analysis）共用。

全部由代码在已建好的图上计算，不重复解析：
    script   每行的类型、层级（父行、深度）、所属节点、功能域与层、关键字 / 参数 / 引用的字符区间（按命令卡匹配出的
             参数取值在原文中定位）、引用目标与被引用处、隐藏的默认值行（规范渲染 include_defaults 的结果，放在所属对象块的末尾）
    summary  各功能域对象数、配置检查发现、行的分类计数、依赖默认值的关键配置、安全基线得分、与上一版本的变化
依赖默认值的关键配置：取值来自 Profile 默认值、且其他平台族的 Profile 对同一 Schema 节点登记了不同默认值的属性
（换平台、翻译时行为会变，宜显式写出）。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import networkx as nx

from lmesh.core import checks, layers
from lmesh.core import rules as rulesmod
from lmesh.core.kb import KnowledgeBase
from lmesh.core.kb import syntax as syn

LINE_KINDS = ("command", "raw", "unknown", "comment", "separator", "blank", "end")
TOP = 20  # 摘要里每类列出的条数上限


def _statements(g: nx.MultiDiGraph) -> list[Any]:
    return list(g.graph.get("statements") or [])


def _domain_of(kb: KnowledgeBase, schema: str | None) -> str:
    if not schema or schema.startswith("ext:"):
        return ""
    n = kb.nodes.get(schema)
    return n.domain if n else ""


# ---------------------------------------------------------------- 结构化脚本


def _deepest(nodes: list[str]) -> str | None:
    return max(nodes, key=lambda n: (n.count("/"), len(n))) if nodes else None


def spans(raw: str, values: dict[str, Any], quotes: bool = False) -> list[dict[str, Any]]:
    """一行命令的字符区间：kw 关键字、param 参数取值（p 是参数名）。位置相对整行原文（含行首空白）。

    参数取值来自命令卡的匹配结果：含空格的取值（text 参数）按子串定位，其余按词逐个对应；第一个词总是关键字。
    quotes（Nokia）：引号字符串是一个词，按去掉引号的取值对应，区间含引号。"""
    toks = syn.tokenize_line(raw, quotes)
    out: list[dict[str, Any]] = []
    covered: list[tuple[int, int]] = []
    singles: list[tuple[str, str]] = []
    first_end = toks[0][1] + len(toks[0][0]) if toks else 0
    for p, v in values.items():
        for x in v if isinstance(v, list) else [v]:
            s = "" if x is None else str(x)
            if not s:
                continue
            if " " in s.strip():
                i = raw.find(s, first_end)
                if i >= 0:
                    out.append({"s": i, "e": i + len(s), "t": "param", "p": p})
                    covered.append((i, i + len(s)))
                    continue
            singles.append((p, s))
    for k, (word, pos) in enumerate(toks):
        if any(a <= pos < b for a, b in covered):
            continue
        bare = syn.unquote(word)[0] if quotes else word
        hit = next((i for i, (_, s) in enumerate(singles) if s in (word, bare)), None) if k > 0 else None
        if hit is not None:
            p, _ = singles.pop(hit)
            out.append({"s": pos, "e": pos + len(word), "t": "param", "p": p})
        else:
            out.append({"s": pos, "e": pos + len(word), "t": "kw"})
    out.sort(key=lambda x: x["s"])
    return out


def script(g: nx.MultiDiGraph, kb: KnowledgeBase, lay: layers.Layers, with_defaults: bool = True) -> dict[str, Any]:
    """结构化脚本：逐行数据 + 引用（目标 → 引用行）+ 定义行 + 隐藏的默认值行。"""
    layer_of, owner = layers.node_layers(g, kb, lay)
    refs_out: dict[str, list[str]] = defaultdict(list)
    for a, b, d in g.edges(data=True):
        if d.get("kind") == "reference":
            refs_out[a].append(b)
    lines: list[dict[str, Any]] = []
    depth: dict[int, int] = {}
    fam = kb.families.get(str(g.graph.get("family") or ""))
    quotes = bool(fam and fam.quotes)
    refs: dict[str, list[int]] = defaultdict(list)
    for st in _statements(g):
        ln = st.line
        dep = depth.get(ln.parent, -1) + 1 if ln.parent else 0
        depth[ln.no] = dep
        node = _deepest(list(st.nodes))
        row: dict[str, Any] = {"no": ln.no, "kind": ln.kind, "text": ln.raw, "depth": dep, "parent": ln.parent}
        if node:
            row["node"] = node
            row["layer"] = layer_of.get(node)
            o = owner.get(node)
            row["domain"] = ln.domain or _domain_of(kb, g.nodes[o].get("schema") if o else None)
        if ln.kind == "command" and ln.card:
            row["card"] = ln.card
            if ln.negated:
                row["negated"] = True
            sp = spans(ln.raw, ln.values(), quotes)
            _attach_refs(g, st, sp, refs_out, ln.raw)
            for s in sp:
                for tgt in s.get("ref", []):
                    if ln.no not in refs[tgt]:
                        refs[tgt].append(ln.no)
            row["spans"] = sp
        lines.append(row)
    defs = {}
    for tgt in refs:
        d = g.nodes[tgt]
        ls = sorted(d.get("lines") or [])
        defs[tgt] = ls[0] if ls and d.get("origin") != "derived" else None
    return {
        "device": g.graph.get("device"),
        "profile": g.graph.get("profile"),
        "family": g.graph.get("family"),
        "lines": lines,
        "refs": {k: sorted(v) for k, v in refs.items()},
        "defs": defs,
        "defaults": default_lines(g, kb, owner, depth) if with_defaults else [],
    }


def _attach_refs(
    g: nx.MultiDiGraph, st: Any, sp: list[dict[str, Any]], refs_out: dict[str, list[str]], raw: str
) -> None:
    """引用：这一行产生的属性有引用边时，把目标挂到取值对应的参数区间上（按参数来源或取值文字对应）。"""
    by_param: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in sp:
        if s["t"] == "param":
            by_param[s["p"]].append(s)
    src_param = {n: p for p, n in (st.sources or {}).items()}
    for n in st.nodes:
        targets = refs_out.get(n)
        if not targets:
            continue
        d = g.nodes[n]
        cand: list[dict[str, Any]] = list(by_param.get(src_param.get(n, ""), []))
        if not cand:
            vals = d.get("raw") if d.get("raw") is not None else d.get("value")
            texts = {str(x) for x in (vals if isinstance(vals, list) else [vals]) if x is not None}
            cand = [s for s in sp if s["t"] == "param" and raw[s["s"] : s["e"]] in texts]
        for s in cand:
            s["t"] = "ref"
            for t in targets:
                if t not in s.setdefault("ref", []):
                    s["ref"].append(t)


def default_lines(
    g: nx.MultiDiGraph, kb: KnowledgeBase, owner: dict[str, str | None], depth: dict[int, int]
) -> list[dict[str, Any]]:
    """隐藏的默认值：每个默认值节点一行，after 是所属对象块的最后一行（插在它后面），text 是该平台的命令写法
    （规范渲染 include_defaults 的结果；写不出命令时为 null，界面显示 Schema 与取值）。"""
    texts: dict[str, str] = {}
    try:
        from lmesh.core import canon

        # 只渲染默认值节点（对象的入口行随之写出）：渲染整份配置在 2 万行的设备上要几十秒
        facts = {n for n, d in g.nodes(data=True) if d.get("kind") == "attr" and d.get("origin") == "default"}
        r = canon.render_full(g, kb, str(g.graph.get("profile")), include_defaults=True, facts=facts, extras=False)
        for ln in r.lines:
            if ln.origin == "default" and ln.kind == "command":
                for n in ln.nodes:
                    texts.setdefault(n, ln.text)
    except Exception:  # noqa: BLE001 - 规范渲染失败时只是没有命令写法
        texts = {}
    parent = {b: a for a, b, d in g.edges(data=True) if d.get("kind") == "contains"}
    subtree_last: dict[str, int] = {}
    for n, d in g.nodes(data=True):
        ls = d.get("lines") or []
        if not ls or d.get("origin") == "default":
            continue
        last = max(ls)
        cur: str | None = n
        hops = 0
        while cur is not None and hops < 64:
            if subtree_last.get(cur, 0) < last:
                subtree_last[cur] = last
            cur = parent.get(cur)
            hops += 1
    out: list[dict[str, Any]] = []
    for n, d in g.nodes(data=True):
        if d.get("kind") != "attr" or d.get("origin") != "default":
            continue
        o = owner.get(n)
        od = g.nodes[o] if o else {}
        first = min(od.get("lines") or [0]) if o else 0
        out.append(
            {
                "node": n,
                "owner": o,
                "schema": d.get("schema"),
                "value": d.get("value"),
                "after": subtree_last.get(o) if o else None,
                "depth": depth.get(first, 0) + 1 if first else 1,
                "text": texts.get(n),
            }
        )
    out.sort(key=lambda x: (x["after"] or 10**9, x["node"]))
    return out


# ---------------------------------------------------------------- 分析摘要


def line_counts(g: nx.MultiDiGraph) -> dict[str, Any]:
    c = {k: 0 for k in LINE_KINDS}
    for st in _statements(g):
        c[st.line.kind] = c.get(st.line.kind, 0) + 1
    total = len(_statements(g))
    base = c["command"] + c["unknown"]
    return {"total": total, **c, "coverage": round(c["command"] / base, 4) if base else 1.0}


def domain_counts(g: nx.MultiDiGraph, kb: KnowledgeBase) -> list[dict[str, Any]]:
    """各功能域：对象数（显式与派生）、显式属性数、默认值数、涉及的原文行数。"""
    rows: dict[str, dict[str, Any]] = {}
    for _, d in g.nodes(data=True):
        dom = _domain_of(kb, d.get("schema"))
        if not dom:
            continue
        r = rows.setdefault(dom, {"domain": dom, "objects": 0, "attrs": 0, "defaults": 0, "lines": set()})
        if d.get("kind") == "object":
            r["objects"] += 1
        elif d.get("kind") == "attr":
            r["defaults" if d.get("origin") == "default" else "attrs"] += 1
        r["lines"].update(d.get("lines") or [])
    order = {dom: i for i, dom in enumerate(kb.domains)}
    out = [{**r, "lines": len(r["lines"])} for r in rows.values()]
    out.sort(key=lambda r: (-r["objects"], order.get(r["domain"], 999), r["domain"]))
    return out


def key_defaults(g: nx.MultiDiGraph, kb: KnowledgeBase, owner: dict[str, str | None]) -> dict[str, Any]:
    """依赖默认值的关键配置：默认值节点中，其他平台族的 Profile 登记了不同默认值的。"""
    me = str(g.graph.get("profile"))
    family = kb.profiles[me].family if me in kb.profiles else g.graph.get("family")
    others: dict[str, dict[str, Any]] = {}
    for pid, p in kb.profiles.items():
        if p.family == family:
            continue
        others[pid] = {n: e.default for n, e in kb.resolve_profile(pid).entries.items() if e.default is not None}
    total = 0
    items: list[dict[str, Any]] = []
    for n, d in g.nodes(data=True):
        if d.get("kind") != "attr" or d.get("origin") != "default":
            continue
        total += 1
        sch = str(d.get("schema"))
        diff = [
            {"profile": pid, "value": tbl[sch]}
            for pid, tbl in sorted(others.items())
            if sch in tbl and str(tbl[sch]).lower() != str(d.get("value")).lower()
        ]
        if diff:
            items.append(
                {
                    "node": n,
                    "owner": owner.get(n),
                    "schema": sch,
                    "domain": _domain_of(kb, sch),
                    "value": d.get("value"),
                    "others": diff,
                }
            )
    items.sort(key=lambda x: (x["domain"], x["schema"], x["node"]))
    return {"total": total, "key": len(items), "items": items[:TOP], "truncated": len(items) > TOP}


def summary(
    g: nx.MultiDiGraph,
    kb: KnowledgeBase,
    lay: layers.Layers,
    *,
    check: dict[str, Any] | None = None,
    baseline: dict[str, Any] | None = None,
    history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """分析摘要。check / baseline / history 由调用方算好传入（各自依赖规则目录、数据库）。"""
    cls = layers.classify(g, kb, lay)
    _, owner = layers.node_layers(g, kb, lay)
    out: dict[str, Any] = {
        "device": g.graph.get("device"),
        "profile": g.graph.get("profile"),
        "family": g.graph.get("family"),
        "kb_version": g.graph.get("kb_version"),
        "lines": line_counts(g),
        "domains": domain_counts(g, kb),
        "layers": [{"id": r["id"], "objects": r["objects"], "attrs": r["attrs"]} for r in cls["layers"]],
        "cross_layer": len(cls["cross"]),
        "dangling": len(g.graph.get("dangling") or []),
        "defaults": key_defaults(g, kb, owner),
        "unknown_lines": [st.line.no for st in _statements(g) if st.line.kind == "unknown"][:200],
        "check": _check_brief(check) if check is not None else None,
        "baseline": _baseline_brief(baseline) if baseline is not None else None,
        "history": history,
    }
    return out


def _check_brief(res: dict[str, Any]) -> dict[str, Any]:
    keep = ("rule", "severity", "node", "domain", "lines", "message", "suggestion", "ignored")
    top = [{k: f.get(k) for k in keep} for f in res["findings"] if not f.get("ignored")][:TOP]
    used = {f["message"]["key"] for f in top} | {f["suggestion"]["key"] for f in top}
    return {
        "summary": res["summary"],
        "rules_loaded": res.get("rules_loaded"),
        "top": top,
        "texts": {k: v for k, v in (res.get("texts") or {}).items() if k in used},
    }


def _baseline_brief(res: dict[str, Any]) -> dict[str, Any]:
    keep = ("rule", "severity", "node", "lines", "message", "suggestion")
    return {
        "baseline": res.get("baseline"),
        "score": res.get("score"),
        "summary": res.get("summary"),
        "failures": [{k: f.get(k) for k in keep} for f in res.get("failures", [])][:TOP],
        "failure_count": len(res.get("failures", [])),
        "texts": res.get("texts", {}),
    }


def run_check(
    g: nx.MultiDiGraph,
    kb: KnowledgeBase,
    rules: list[rulesmod.Rule],
    overrides: dict[str, dict[str, Any]] | None,
    ignores: dict[tuple[str, str], dict[str, Any]] | None,
) -> dict[str, Any]:
    return checks.check(g, kb, rules, "info", None, overrides, ignores)


def run_baseline(
    g: nx.MultiDiGraph, kb: KnowledgeBase, kb_root: Any, profile: str | None = None
) -> dict[str, Any] | None:
    """安全基线（默认 basic）。基线文件有错误时返回 None（摘要里显示为不可用，不影响其他项）。"""
    from lmesh.core import baseline as blmod

    try:
        bl = blmod.load(kb, blmod.baseline_dir(kb_root))
    except rulesmod.RuleError:
        return None
    name = profile or blmod.DEFAULT_PROFILE
    if name not in bl.profiles:
        return None
    rules, overrides = blmod.select(bl, name)
    res = blmod.audit_device(g, rules, overrides)
    used = {f["message"]["key"] for f in res["failures"][:TOP]} | {
        f["suggestion"]["key"] for f in res["failures"][:TOP]
    }
    texts: dict[str, dict[str, str]] = {}
    for r in rules:
        for part in ("message", "suggestion"):
            k = f"baseline.{r.id}.{part}"
            if k in used:
                texts[k] = getattr(r, part)
    return {**res, "baseline": name, "texts": texts}


def history_brief(db_url: str, device_id: int, version_id: int, kb: KnowledgeBase) -> dict[str, Any] | None:
    """与上一版本相比的变化：给定版本与它前一个快照；只有一个快照时 previous 为 null。"""
    from lmesh.core import history

    try:
        tl = history.timeline(db_url, device_id, kb)
    except history.HistoryError:
        return None
    snaps = tl["snapshots"]
    idx = next((i for i, s in enumerate(snaps) if s["id"] == version_id), None)
    if idx is None:
        return None
    cur = snaps[idx]
    brief = {k: cur.get(k) for k in ("id", "seq", "collected_at", "source_name", "kb_version", "tag")}
    if idx == 0:
        return {"current": brief, "previous": None, "snapshots": len(snaps), "summary": None, "items": []}
    prev = snaps[idx - 1]
    try:
        d = history.diff(db_url, device_id, kb, prev["id"], cur["id"], with_text=False)
    except history.HistoryError:
        return None
    return {
        "current": brief,
        "previous": {k: prev.get(k) for k in ("id", "seq", "collected_at", "source_name", "kb_version", "tag")},
        "snapshots": len(snaps),
        "equal": d["equal"],
        "summary": d["summary"],
        "items": [
            {"object": it.get("object"), "kind": it.get("kind"), "domain": it.get("domain")} for it in d["items"][:TOP]
        ],
    }
