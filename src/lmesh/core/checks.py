"""配置检查：在配置图上计算悬空引用、孤儿对象（含级联孤儿）、互斥冲突与规则约束（knowledge/rules/）。

每条发现：rule（规则编号）、severity（error / warning / info）、domain（功能域）、node（主要节点的规范编号）、
nodes（涉及的全部节点）、lines（原配置行号）、message / suggestion（文案键 + 参数，不写死语言）。
内置检查的文案在 locales（check.<规则>.message 等）；规则文件的文案随结果放在 texts 里（三种语言）。

孤儿对象：Schema 中被引用的对象类型（type=ref 的 ref，或 reference 依赖的终点；按知识库推导）的实例没有任何引用。
    - 被别的对象以键使用（bgp.af[vrf=X]、按组名写的 bgp.af.peer[Client]、名称为“字母前缀 + 编号”的接口 Vbdif100 → 桥域 100）算作使用；
    - 名称出现在未映射的行（功能域外的原文、未识别行、未映射的命令）里时，可能被这些配置使用：只给出 info 级提示，不进入清理；
    - 被引用即隐式存在的对象（Profile 的 implicit，派生节点）不算。
级联孤儿：只被孤儿（或级联孤儿）引用的对象，删除引用方后也成为孤儿，与引用方一起清理。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from lmesh.core import i18n
from lmesh.core import rules as rulesmod
from lmesh.core.kb import KnowledgeBase, read_yaml

BUILTIN: dict[str, str] = {
    "ref.dangling": "error",
    "ref.dangling_unsure": "warning",
    "ref.orphan": "warning",
    "ref.orphan_cascade": "warning",
    "ref.orphan_unsure": "info",
    "dep.mutex": "error",
}


def rules_dir(kb_root: Path) -> Path:
    """知识库的规则目录；早于 M2 复制出的运行时知识库没有 rules/ 时，用程序自带的规则。"""
    own = kb_root / "rules"
    if own.exists():
        return own
    from lmesh import paths

    return paths.builtin_knowledge_dir() / "rules"


def load_overrides(directory: Path) -> dict[str, dict[str, Any]]:
    """内置检查的开关与级别覆盖（rules/builtin.yaml）：{builtin: {规则: {enabled, severity}}}。没有文件时为空。"""
    path = directory / rulesmod.BUILTIN_FILE
    if not path.is_file():
        return {}
    fname = rulesmod.BUILTIN_FILE
    try:
        doc = read_yaml(path) or {}
    except Exception as e:  # YAML 语法错误
        first = str(e).splitlines()[0] if str(e) else ""
        raise rulesmod.RuleError(
            [{"file": fname, "rule": "", "field": "", "code": "rules.err.yaml", "params": {"error": first}}]
        ) from e
    issues: list[dict[str, Any]] = []
    out: dict[str, dict[str, Any]] = {}
    table = doc.get("builtin") if isinstance(doc, dict) else None
    if not isinstance(table, dict):
        table = {}
    for rid, entry in table.items():
        rid = str(rid)

        def bad(field_: str, code: str, rid: str = rid, **params: Any) -> None:
            issues.append({"file": fname, "rule": rid, "field": field_, "code": code, "params": params})

        if rid not in BUILTIN:
            bad("", "rules.err.unknown_builtin", value=rid)
            continue
        entry = entry if isinstance(entry, dict) else {}
        enabled = entry.get("enabled", True)
        sev = entry.get("severity", BUILTIN[rid])
        if not isinstance(enabled, bool):
            bad("enabled", "rules.err.bad_bool")
        if sev not in rulesmod.SEVERITIES:
            bad("severity", "rules.err.bad_severity", value=str(sev), allowed=", ".join(rulesmod.SEVERITIES))
        out[rid] = {"enabled": bool(enabled), "severity": sev}
    if issues:
        raise rulesmod.RuleError(issues)
    return out


def builtin_rules(overrides: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """内置检查的说明（三种语言），供规则列表展示；overrides 是 rules/builtin.yaml 中的开关与级别。"""
    out = []
    for rid, sev in BUILTIN.items():
        ov = (overrides or {}).get(rid, {})
        out.append(
            {
                "id": rid,
                "builtin": True,
                "source": "builtin",
                "target": None,
                "domain": None,
                "severity": ov.get("severity", sev),
                "default_severity": sev,
                "enabled": ov.get("enabled", True),
                **{
                    f: {lang: i18n.catalog(lang).get(f"check.{rid}.{f}", "") for lang in i18n.LANGS}
                    for f in ("title", "message", "suggestion")
                },
            }
        )
    return out


def list_rules(kb: KnowledgeBase, directory: Path) -> dict[str, Any]:
    loaded = rulesmod.load_cached(kb, directory)
    builtin = builtin_rules(load_overrides(directory))
    return {"builtin": len(builtin), "custom": len(loaded), "rules": builtin + [r.as_dict() for r in loaded]}


# ---------- 图上的辅助结构 ----------


def ref_target_types(kb: KnowledgeBase) -> set[str]:
    out = {n.ref for n in kb.nodes.values() if n.type == "ref" and n.ref}
    out |= {d.dst for d in kb.deps if d.kind == "reference"}
    return {t for t in out if t in kb.nodes}


@dataclass
class Index:
    g: nx.MultiDiGraph
    kb: KnowledgeBase
    children: dict[str, list[str]] = field(default_factory=dict)
    parent: dict[str, str] = field(default_factory=dict)
    ref_in: dict[str, list[str]] = field(default_factory=dict)  # 被引用对象 → 引用它的属性节点
    lines: dict[int, Any] = field(default_factory=dict)  # 行号 → Line
    line_nodes: dict[int, list[str]] = field(default_factory=dict)

    @classmethod
    def of(cls, g: nx.MultiDiGraph, kb: KnowledgeBase) -> Index:
        ix = cls(g, kb)
        for a, b, d in g.edges(data=True):
            if d.get("kind") == "contains":
                ix.children.setdefault(a, []).append(b)
                ix.parent[b] = a
            elif d.get("kind") == "reference":
                ix.ref_in.setdefault(b, []).append(a)
        for st in g.graph.get("statements", []):
            ix.lines[st.line.no] = st.line
            ix.line_nodes[st.line.no] = list(st.nodes)
        return ix

    def subtree(self, n: str) -> set[str]:
        out, stack = {n}, [n]
        while stack:
            for c in self.children.get(stack.pop(), []):
                if c not in out:
                    out.add(c)
                    stack.append(c)
        return out

    def subtree_lines(self, nodes: set[str]) -> set[int]:
        out: set[int] = set()
        for n in nodes:
            out.update(self.g.nodes[n].get("lines") or [])
        # 行的层级：进入视图的行下面的子行也属于该对象（例如未映射的子命令）
        return self.with_child_lines(out)

    def with_child_lines(self, lines: set[int]) -> set[int]:
        out = set(lines)
        for no in sorted(self.lines):
            p = self.lines[no].parent
            if p is not None and p in out:
                out.add(no)
        return out

    def owner_object(self, n: str) -> str:
        """属性节点所属的对象（沿 contains 向上的第一个对象）。"""
        p = self.parent.get(n)
        while p is not None and self.g.nodes[p].get("kind") != "object":
            p = self.parent.get(p)
        return p or n

    def context(self, line_no: int) -> list[int]:
        """一行所在的视图链：从最外层到直接父行。"""
        chain: list[int] = []
        p = self.lines[line_no].parent if line_no in self.lines else None
        while p is not None:
            chain.append(p)
            p = self.lines[p].parent if p in self.lines else None
        return list(reversed(chain))


def _domain(kb: KnowledgeBase, schema: str | None) -> str:
    node = kb.nodes.get(schema or "")
    return node.domain if node else ""


def _finding(
    kb: KnowledgeBase,
    g: nx.MultiDiGraph,
    rule: str,
    severity: str,
    node: str,
    nodes: list[str],
    params: dict[str, Any],
    msg_key: str | None = None,
    sug_key: str | None = None,
    extra_lines: list[int] | None = None,
    line_nodes: list[str] | None = None,
) -> dict[str, Any]:
    """lines 取 line_nodes（默认 nodes）的行号加上 extra_lines。"""
    lines: set[int] = set(extra_lines or [])
    for n in nodes if line_nodes is None else line_nodes:
        lines.update(g.nodes[n].get("lines") or [])
    schema = g.nodes[node].get("schema")
    return {
        "rule": rule,
        "severity": severity,
        "domain": _domain(kb, schema),
        "node": node,
        "schema": schema,
        "nodes": nodes,
        "lines": sorted(lines),
        "message": {"key": msg_key or f"check.{rule}.message", "params": params},
        "suggestion": {"key": sug_key or f"check.{rule}.suggestion", "params": params},
    }


# ---------- 悬空引用 ----------


def dangling(g: nx.MultiDiGraph, kb: KnowledgeBase, ix: Index | None = None) -> list[dict[str, Any]]:
    """建图时记录的悬空引用（reference 依赖规则），以及 Schema 中标了 ref、却没有依赖规则的属性。"""
    ix = ix or Index.of(g, kb)
    out: list[dict[str, Any]] = []
    for d in g.graph.get("dangling", []):
        nid = d["node"]
        out.append(
            {
                "node": nid,
                "referrer": ix.owner_object(nid),
                "schema": d.get("schema"),
                "target_type": d.get("target_type"),
                "value": d.get("value"),
                "lines": list(d.get("lines") or []),
            }
        )
    with_rule = {r.src for r in kb.deps if r.kind == "reference"}
    keys = {
        (str(dd.get("schema")), rulesmod.key_text(dd.get("key")))
        for _, dd in g.nodes(data=True)
        if dd.get("kind") == "object"
    }
    for nid, dd in g.nodes(data=True):
        sn = kb.nodes.get(str(dd.get("schema") or ""))
        if dd.get("kind") != "attr" or sn is None or sn.type != "ref" or not sn.ref or sn.id in with_rule:
            continue
        if dd.get("origin") == "default" or dd.get("negated"):
            continue
        for v in dd["value"] if isinstance(dd.get("value"), list) else [dd.get("value")]:
            if v in (None, "", True, False) or (sn.ref, str(v)) in keys:
                continue
            out.append(
                {
                    "node": nid,
                    "referrer": ix.owner_object(nid),
                    "schema": sn.id,
                    "target_type": sn.ref,
                    "value": v,
                    "lines": list(dd.get("lines") or []),
                }
            )
    # 被引用的名称出现在未映射的行（原文、未识别行、未映射的命令）里：可能在那里声明，只是知识库还没映射
    unmapped = [
        (no, _tokens(ln.text))
        for no, ln in ix.lines.items()
        if ln.kind in ("raw", "unknown")
        or (ln.kind == "command" and ix.line_nodes.get(no) and all("ext[" in n for n in ix.line_nodes[no]))
    ]
    for d in out:
        d["mentions"] = [no for no, toks in unmapped if str(d["value"]) in toks and no not in d["lines"]]
    return out


# ---------- 孤儿对象 ----------


@dataclass
class Orphans:
    orphan: list[str] = field(default_factory=list)  # 直接孤儿（按行号）
    cascade: dict[str, list[str]] = field(default_factory=dict)  # 级联孤儿 → 引用它的孤儿
    unsure: dict[str, list[int]] = field(default_factory=dict)  # 名称出现在未映射行中的候选 → 行号

    def removal(self) -> list[str]:
        return self.orphan + list(self.cascade)


def _tokens(text: str) -> set[str]:
    return set(text.split())


def find_orphans(g: nx.MultiDiGraph, kb: KnowledgeBase, ix: Index | None = None) -> Orphans:
    ix = ix or Index.of(g, kb)
    targets = ref_target_types(kb)

    cands: list[str] = []
    for n, d in g.nodes(data=True):
        if (
            d.get("kind") == "object"
            and d.get("schema") in targets
            and d.get("origin") == "explicit"
            and not d.get("negated")
            and d.get("lines")
            and not isinstance(d.get("key"), dict)
            and rulesmod.key_text(d.get("key")) not in ("", "_")
        ):
            cands.append(n)
    cands.sort(key=lambda n: (min(g.nodes[n]["lines"]), n))

    # 每行“已解释”的词：该行映射出的对象的键与属性的取值。名称只以这些身份出现时，已由图中的边表达（或不是引用）；
    # 否则（功能域外的原文、未识别行、未映射的命令，或已映射命令中未映射的参数）算作可能的使用
    explained: dict[int, set[str]] = {}
    for no, nodes in ix.line_nodes.items():
        words: set[str] = set()
        for n in nodes:
            d = g.nodes[n]
            if d.get("kind") == "object":
                key = d.get("key")
                words |= {str(v) for v in key.values()} if isinstance(key, dict) else {rulesmod.key_text(key)}
            elif d.get("kind") == "attr":
                for v in d.get("raw"), d.get("value"):
                    for item in v if isinstance(v, list) else [v]:
                        if item is not None:
                            words |= _tokens(str(item))
        explained[no] = words

    # 以键使用：别的（非被引用类型的）对象的键等于名称，或接口名是“字母前缀 + 编号”
    key_users: dict[str, list[str]] = {}
    for n, d in g.nodes(data=True):
        if d.get("kind") != "object" or d.get("schema") in targets:
            continue
        key = d.get("key")
        vals = (
            [str(v) for v in key.values() if v not in (None, "")] if isinstance(key, dict) else [rulesmod.key_text(key)]
        )
        parent = next((a for a, _, ed in g.in_edges(n, data=True) if ed.get("kind") == "contains"), None)
        parent_key = rulesmod.key_text(g.nodes[parent].get("key")) if parent is not None else ""
        for v in vals:
            if parent_key.endswith("." + v):
                continue  # 键取自所在子接口的编号（接入点 GE0/2/9.1500 → 1500），不是对同名对象的使用
            key_users.setdefault(v, []).append(n)
            m = re.fullmatch(r"[A-Za-z][A-Za-z\-]*(\d+)", v)
            if m:
                key_users.setdefault("#" + m.group(1), []).append(n)

    info: dict[str, dict[str, Any]] = {}
    for o in cands:
        sub = ix.subtree(o)
        sub_lines = ix.subtree_lines(sub)
        name = rulesmod.key_text(g.nodes[o].get("key"))
        referrers = {a for t in sub for a in ix.ref_in.get(t, []) if a not in sub}
        users = [u for u in key_users.get(name, []) if u not in sub]
        if name.isdigit():
            users += [u for u in key_users.get("#" + name, []) if u not in sub]
        mentions: list[int] = []
        for no, ln in ix.lines.items():
            if no in sub_lines or ln.kind not in ("command", "raw", "unknown"):
                continue
            if name in _tokens(ln.text) and name not in explained.get(no, set()):
                mentions.append(no)
        info[o] = {"sub": sub, "sub_lines": sub_lines, "referrers": referrers, "users": users, "mentions": mentions}

    res = Orphans()
    removed: set[str] = set()  # 待删除对象的子树中的全部节点
    removed_lines: set[int] = set()
    for o in cands:
        i = info[o]
        if not i["referrers"] and not i["users"]:
            if i["mentions"]:
                res.unsure[o] = i["mentions"]
            else:
                res.orphan.append(o)
                removed |= i["sub"]
                removed_lines |= i["sub_lines"]
    changed = True
    while changed:
        changed = False
        for o in cands:
            if o in res.orphan or o in res.cascade or o in res.unsure:
                continue
            i = info[o]
            if not i["referrers"] or not i["referrers"] <= removed or not set(i["users"]) <= removed:
                continue
            if any(no not in removed_lines for no in i["mentions"]):
                continue
            via = [r for r in res.removal() if i["referrers"] & info[r]["sub"]]
            res.cascade[o] = via
            removed |= i["sub"]
            removed_lines |= i["sub_lines"]
            changed = True
    return res


# ---------- 互斥 ----------


def mutex(g: nx.MultiDiGraph) -> list[tuple[str, str, str]]:
    seen: set[tuple[str, str]] = set()
    out = []
    for a, b, d in g.edges(data=True):
        if d.get("kind") == "mutex" and (a, b) not in seen and (b, a) not in seen:
            seen.add((a, b))
            out.append((a, b, str(d.get("note", ""))))
    return out


# ---------- 汇总 ----------


def check(
    g: nx.MultiDiGraph,
    kb: KnowledgeBase,
    rules: list[rulesmod.Rule],
    severity: str | None = None,
    domain: str | None = None,
    overrides: dict[str, dict[str, Any]] | None = None,
    ignores: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """全部检查。severity 是最低级别（info 表示全部），domain 只保留该功能域的发现。

    overrides：内置检查的开关与级别（load_overrides）；ignores：{(规则, 节点): {id, reason}}，命中的发现带
    ignored / ignore_reason / ignore_id，不计入级别统计与 has_errors。
    """
    ix = Index.of(g, kb)
    findings: list[dict[str, Any]] = []
    sev_of = {rid: (overrides or {}).get(rid, {}).get("severity", sev) for rid, sev in BUILTIN.items()}
    for d in dangling(g, kb, ix):
        rid = "ref.dangling_unsure" if d["mentions"] else "ref.dangling"
        findings.append(
            _finding(
                kb,
                g,
                rid,
                sev_of[rid],
                d["node"],
                [d["referrer"], d["node"]] if d["referrer"] != d["node"] else [d["node"]],
                {
                    "node": d["node"],
                    "referrer": d["referrer"],
                    "target_type": d["target_type"],
                    "value": str(d["value"]),
                    "mentions": ", ".join(map(str, d["mentions"])),
                },
                extra_lines=d["lines"] + d["mentions"],
                line_nodes=[],
            )
        )
    orph = find_orphans(g, kb, ix)
    for o in orph.orphan:
        findings.append(_finding(kb, g, "ref.orphan", sev_of["ref.orphan"], o, [o], _obj_params(g, o)))
    for o, via in orph.cascade.items():
        findings.append(
            _finding(
                kb,
                g,
                "ref.orphan_cascade",
                sev_of["ref.orphan_cascade"],
                o,
                [o, *via],
                {**_obj_params(g, o), "via": ", ".join(via)},
                line_nodes=[o],
            )
        )
    for o, lines in orph.unsure.items():
        findings.append(
            _finding(
                kb,
                g,
                "ref.orphan_unsure",
                sev_of["ref.orphan_unsure"],
                o,
                [o],
                {**_obj_params(g, o), "mentions": ", ".join(map(str, lines))},
                extra_lines=lines,
            )
        )
    for a, b, note in mutex(g):
        findings.append(
            _finding(kb, g, "dep.mutex", sev_of["dep.mutex"], a, [a, b], {"node": a, "other": b, "note": note})
        )
    texts: dict[str, dict[str, str]] = {}
    for r, n in rulesmod.evaluate(g, rules):
        params = {"node": n, "key": rulesmod.key_text(g.nodes[n].get("key"))}
        mk, sk = f"rules.{r.id}.message", f"rules.{r.id}.suggestion"
        texts[mk], texts[sk] = r.message, r.suggestion
        findings.append(_finding(kb, g, r.id, r.severity, n, [n], params, mk, sk))

    disabled = {rid for rid, ov in (overrides or {}).items() if not ov.get("enabled", True)}
    findings = [f for f in findings if f["rule"] not in disabled]
    for f in findings:
        hit = (ignores or {}).get((f["rule"], f["node"]))
        f["ignored"] = hit is not None
        f["ignore_reason"] = hit["reason"] if hit else None
        f["ignore_id"] = hit["id"] if hit else None
    total = len(findings)
    floor = rulesmod.SEVERITY_RANK.get(severity or "info", 1)
    findings = [
        f for f in findings if rulesmod.SEVERITY_RANK[f["severity"]] >= floor and (not domain or f["domain"] == domain)
    ]
    findings.sort(key=lambda f: (-rulesmod.SEVERITY_RANK[f["severity"]], f["lines"][:1] or [0], f["rule"], f["node"]))
    used = {f["message"]["key"] for f in findings} | {f["suggestion"]["key"] for f in findings}
    return {
        "device": g.graph.get("device"),
        "profile": g.graph.get("profile"),
        "kb_version": g.graph.get("kb_version"),
        "filters": {"severity": severity or "info", "domain": domain},
        "rules_loaded": len([r for r in rules if r.enabled]),
        "summary": summarize(findings, total),
        "findings": findings,
        "texts": {k: v for k, v in sorted(texts.items()) if k in used},
    }


def _obj_params(g: nx.MultiDiGraph, o: str) -> dict[str, Any]:
    d = g.nodes[o]
    return {"node": o, "schema": d.get("schema"), "key": rulesmod.key_text(d.get("key"))}


def summarize(findings: list[dict[str, Any]], unfiltered: int | None = None) -> dict[str, Any]:
    """total 含被忽略的发现；by_severity / by_rule / by_domain / has_errors 只算没有被忽略的。"""
    by_sev = {s: 0 for s in rulesmod.SEVERITIES}
    by_rule: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    ignored = sum(1 for f in findings if f.get("ignored"))
    for f in findings:
        if f.get("ignored"):
            continue
        by_sev[f["severity"]] += 1
        by_rule[f["rule"]] = by_rule.get(f["rule"], 0) + 1
        by_domain[f["domain"] or "-"] = by_domain.get(f["domain"] or "-", 0) + 1
    return {
        "total": len(findings),
        "unfiltered": len(findings) if unfiltered is None else unfiltered,
        "ignored": ignored,
        "has_errors": by_sev["error"] > 0,
        "by_severity": by_sev,
        "by_rule": dict(sorted(by_rule.items())),
        "by_domain": dict(sorted(by_domain.items())),
    }


def render_text(ref: dict[str, Any], lang: str, texts: dict[str, dict[str, str]]) -> str:
    """把 {key, params} 按语言渲染成文字（CLI 与界面共用的规则）。"""
    key, params = ref["key"], ref.get("params", {})
    lang = i18n.normalize(lang)
    if key in texts:
        tpl = texts[key].get(lang) or texts[key].get(i18n.DEFAULT, key)
    else:  # 参数里有 key（实例的键），不能直接传给 i18n.t
        tpl = i18n.catalog(lang).get(key) or i18n.catalog(i18n.DEFAULT).get(key, key)
    try:
        return tpl.format(**params)
    except (KeyError, IndexError, ValueError):
        return tpl
