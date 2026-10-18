"""配置护栏（M5-5）：AI 生成（或手写、其他工具生成）的配置先入图校验，再决定能不能展示 / 交给增量变更。

阶段（全部由代码在图上计算，不用 AI）：
    parse     按目标设备的 Profile 逐行解析：功能域内匹配不到命令卡的行（未识别）被拦截，功能域外的行标为无法校验
    graph     合并到目标设备当前配置（最新快照的原文）后建图，每一行对应到图节点
    deps      依赖：引用了不存在的对象（悬空引用）、互斥、缺少前置条件、Profile 副作用（例如华为绑定 VPN 实例会删除接口地址）
    template  可选：按参数化模板校验，新内容不符合模板约束的地方提示
    conflict  冲突：接口地址与本机其他接口或其他设备重复、RD 与其他 VPN 实例重复、同一主接口下 dot1q 重复
有被拦截（bad）的问题时结论为 blocked，不能交给增量变更；全部通过时可附上增量变更脚本（当前 → 合并后）。
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from lmesh.core import analysis, checks, i18n
from lmesh.core import graph as graphmod
from lmesh.core.kb import KnowledgeBase
from lmesh.core.objtable import GraphIndex

STAGES = ("parse", "graph", "deps", "template", "conflict")
_SESSION = re.compile(r"^\s*(system-view|configure(\s+terminal)?|conf\s+t|commit|return|end)\s*$", re.I)


class GuardError(ValueError):
    def __init__(self, key: str, kind: str = "param", **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.fmt = key, kind, fmt


@dataclass
class _Issue:
    id: str
    status: str  # bad / warn / ok
    stage: str
    rule: str
    lines: list[int]  # 提交的文本中的行号
    params: dict[str, Any] = field(default_factory=dict)
    fix: str = ""

    def as_dict(self, lang: str) -> dict[str, Any]:
        key = f"guard.{self.rule}"
        return {
            "id": self.id,
            "status": self.status,
            "stage": self.stage,
            "rule": self.rule,
            "line": self.lines[0] if self.lines else None,
            "lines": self.lines,
            "message": {"key": key, "params": self.params},
            "text": i18n.t(key, lang, **self.params),
            "fix": self.fix,
        }


def strip_session(text: str) -> tuple[list[tuple[int, str]], list[int]]:
    """去掉会话命令（system-view、configure terminal、commit、return、end）与代码块围栏；返回 [(原行号, 文本)] 与跳过的行号。"""
    keep: list[tuple[int, str]] = []
    skipped: list[int] = []
    for i, ln in enumerate(text.replace("\r\n", "\n").split("\n"), start=1):
        if _SESSION.match(ln) or ln.strip().startswith("```"):
            skipped.append(i)
            continue
        keep.append((i, ln.rstrip()))
    while keep and not keep[-1][1].strip():
        keep.pop()
    return keep, skipped


def _base_body(base: str, family_end: str) -> list[str]:
    lines = base.replace("\r\n", "\n").rstrip("\n").split("\n")
    while lines and (not lines[-1].strip() or lines[-1].strip() == family_end):
        lines.pop()
    return lines


def _ip_scope(g: nx.MultiDiGraph, ix: GraphIndex, itf: str) -> str:
    for v in ix.child(itf, "interface.vrf"):
        return str(g.nodes[v].get("value") or "")
    return ""


def _addresses(g: nx.MultiDiGraph, ix: GraphIndex) -> list[tuple[str, str, str, str, list[int]]]:
    """(接口节点, 接口名, VRF, 地址, 行号)。"""
    out = []
    for itf in ix.objects("interface"):
        scope = _ip_scope(g, ix, itf)
        for ip in ix.child(itf, "interface.ipv4"):
            addr = str(g.nodes[ip].get("key") or "")
            if addr:
                out.append((itf, str(g.nodes[itf].get("key")), scope, addr, list(g.nodes[ip].get("lines") or [])))
    return out


def _rds(g: nx.MultiDiGraph, ix: GraphIndex) -> list[tuple[str, str, list[int]]]:
    out = []
    for vrf in ix.objects("vrf.instance"):
        for af in ix.child(vrf, "vrf.instance.af"):
            for rd in ix.child(af, "vrf.instance.af.rd"):
                out.append(
                    (str(g.nodes[vrf].get("key")), str(g.nodes[rd].get("value")), list(g.nodes[rd].get("lines") or []))
                )
    return out


def guard(
    text: str,
    kb: KnowledgeBase,
    profile: str | None = None,
    base_text: str | None = None,
    device: str = "device",
    others: list[Any] | None = None,
    template: Any = None,
    lang: str = "zh-CN",
    with_script: bool = True,
) -> dict[str, Any]:
    """校验一段配置。base_text：目标设备当前配置（合并后再校验，None 表示空配置）；others：其他设备（topology.Device，查冲突）；
    template：core/template 的 Template（可选）。"""
    keep, skipped = strip_session(text)
    if not any(t.strip() for _, t in keep):
        raise GuardError("guard.empty")
    # 先确定 Profile：给定的 > 当前配置识别出的 > 生成内容识别出的
    try:
        if profile is None and base_text:
            profile = analysis.resolve_profile(base_text, kb)[0]
        pid = analysis.resolve_profile("\n".join(t for _, t in keep), kb, profile)[0]
    except analysis.AnalysisError as e:
        raise GuardError(str(e), profile=profile or "") from e
    fam = kb.families[kb.profiles[pid].family]
    base_lines = _base_body(base_text or "", fam.end)
    offset = len(base_lines) + 1  # 合并文本：当前配置 + 分隔符 + 新内容 + 结尾
    merged_lines = [*base_lines, fam.separator, *(t for _, t in keep), fam.end]
    merged_no = {orig: offset + k + 1 for k, (orig, _) in enumerate(keep)}  # 提交文本行号 → 合并文本行号
    back = {v: k for k, v in merged_no.items()}
    gen_set = set(back)
    res = analysis.parse_text("\n".join(merged_lines), kb, pid)
    g = graphmod.build(res.parsed, kb, res.profile, device)
    ix = GraphIndex(g)
    by_line = {ln.no: ln for ln in res.parsed.lines}
    nodes_of: dict[int, list[str]] = {}
    for st in g.graph.get("statements") or []:
        nodes_of.setdefault(st.line.no, []).extend(st.nodes)

    issues: list[_Issue] = []

    def add(status: str, stage: str, rule: str, mlines: list[int], fix: str = "", **params: Any) -> None:
        orig = sorted({back[n] for n in mlines if n in back})
        issues.append(_Issue(f"i{len(issues) + 1}", status, stage, rule, orig, params, fix))

    def gen_lines(lines: list[int] | None) -> list[int]:
        return [n for n in lines or [] if n in gen_set]

    # parse：未识别 → 拦截；功能域外 → 无法校验
    for n in sorted(gen_set):
        ln = by_line.get(n)
        if ln is None:
            continue
        if ln.kind == "unknown":
            add("bad", "parse", "unknown_line", [n], text=ln.text)
        elif ln.kind == "raw":
            add("warn", "parse", "raw_line", [n], text=ln.text)

    # deps：悬空引用、互斥、缺少前置条件、副作用
    for d in checks.dangling(g, kb):
        if gen_lines(d["lines"]) and not d.get("mentions"):
            add("bad", "deps", "dangling_ref", d["lines"], value=str(d["value"]), target=str(d["target_type"]))
    for a, b, note in checks.mutex(g):
        la, lb = list(g.nodes[a].get("lines") or []), list(g.nodes[b].get("lines") or [])
        if gen_lines(la) or gen_lines(lb):
            add("bad", "deps", "mutex", la + lb, a=a, b=b, note=note)
    for m in g.graph.get("missing_prerequisites") or []:
        if gen_lines(m.get("lines")):
            add("warn", "deps", "prerequisite", m["lines"], node=m["node"], requires=m["requires"])
    prof = kb.resolve_profile(pid)
    for rule in prof.side_effects:
        for src in [n for n, d in g.nodes(data=True) if d.get("schema") == rule.src and d.get("kind") == "attr"]:
            sd = g.nodes[src]
            if not gen_lines(sd.get("lines")) or sd.get("value") in (False, None) or sd.get("negated"):
                continue
            owner = ix.parent.get(src, "")
            src_line = min(sd.get("lines") or [0])
            dsts = [
                n
                for n, d in g.nodes(data=True)
                if n.startswith(owner + "/") and str(d.get("schema") or "").startswith(rule.dst) and d.get("lines")
            ]
            if not dsts:
                continue
            before = [n for n in dsts if any(x < src_line for x in g.nodes[n]["lines"])]
            after_gen = [n for n in dsts if gen_lines([x for x in g.nodes[n]["lines"] if x > src_line])]
            if after_gen:
                add(
                    "ok",
                    "deps",
                    "side_effect_ok",
                    [src_line, *(min(g.nodes[n]["lines"]) for n in after_gen)],
                    src=rule.src,
                    dst=rule.dst,
                )
            elif before and any(min(g.nodes[n]["lines"]) in gen_set for n in before):
                add("bad", "deps", "side_effect_order", [src_line], src=rule.src, dst=rule.dst)
            elif before:
                add("warn", "deps", "side_effect", [src_line], src=rule.src, dst=rule.dst, note=rule.note)

    # template：只看与新内容相关的发现
    if template is not None:
        from lmesh.core import template_match

        try:
            tres = template_match.check(template, g, kb, device)
        except Exception as e:  # 模板本身有问题：作为提示，不影响其他阶段
            add("warn", "template", "template_error", [], error=str(e))
        else:
            for f in tres.get("findings") or []:
                if f.get("severity") not in ("error", "warning"):
                    continue
                if gen_lines(f.get("lines")):
                    add(
                        "warn",
                        "template",
                        "template",
                        f["lines"],
                        kind=str(f.get("kind")),
                        expected=_short(f.get("expected")),
                        actual=_short(f.get("actual")),
                        template=getattr(template, "id", ""),
                    )

    # conflict：地址、RD、dot1q
    mine = _addresses(g, ix)
    for itf, _name, scope, addr, lines in mine:
        if not gen_lines(lines):
            continue
        for itf2, name2, scope2, addr2, _l2 in mine:
            if itf2 != itf and addr2 == addr and scope2 == scope:
                add(
                    "bad",
                    "conflict",
                    "ip_duplicate",
                    lines,
                    address=addr,
                    device=device,
                    interface=name2,
                    vrf=scope or "-",
                )
        for other in others or []:
            oix = GraphIndex(other.g)
            for _i, oname, oscope, oaddr, _ol in _addresses(other.g, oix):
                if oaddr == addr and oscope == scope and not _is_anycast(addr):
                    add(
                        "bad",
                        "conflict",
                        "ip_duplicate",
                        lines,
                        address=addr,
                        device=other.name,
                        interface=oname,
                        vrf=scope or "-",
                    )
    rds = _rds(g, ix)
    for vrf, rd, lines in rds:
        if not gen_lines(lines):
            continue
        for vrf2, rd2, _l in rds:
            if vrf2 != vrf and rd2 == rd:
                add("bad", "conflict", "rd_duplicate", lines, rd=rd, device=device, vrf=vrf2)
        for other in others or []:
            for vrf2, rd2, _l in _rds(other.g, GraphIndex(other.g)):
                if vrf2 != vrf and rd2 == rd:
                    add("bad", "conflict", "rd_duplicate", lines, rd=rd, device=other.name, vrf=vrf2)
    vlans: dict[tuple[str, str], list[tuple[str, list[int]]]] = {}
    for itf in ix.objects("interface"):
        name = str(g.nodes[itf].get("key") or "")
        for v in ix.child(itf, "interface.dot1q_termination"):
            parent = name.split(".", 1)[0]
            vlans.setdefault((parent, str(g.nodes[v].get("value"))), []).append(
                (name, list(g.nodes[v].get("lines") or []))
            )
    for (parent, vid), users in vlans.items():
        if len(users) < 2:
            continue
        for name, lines in users:
            if gen_lines(lines):
                others_n = [u for u, _ in users if u != name]
                add("bad", "conflict", "vlan_duplicate", lines, vlan=vid, parent=parent, interface=", ".join(others_n))

    # 每一行的结论
    by_orig: dict[int, list[_Issue]] = {}
    for it in issues:
        for n in it.lines:
            by_orig.setdefault(n, []).append(it)
    rows = []
    texts = text.replace("\r\n", "\n").split("\n")
    for i, t in enumerate(texts, start=1):
        if i in skipped:
            rows.append({"no": i, "text": t, "status": "skip", "issues": [], "nodes": []})
            continue
        if i not in merged_no:
            continue
        mno = merged_no[i]
        its = by_orig.get(i, [])
        ln = by_line.get(mno)
        kind = ln.kind if ln else "blank"
        status = "ok"
        if any(x.status == "bad" for x in its):
            status = "bad"
        elif any(x.status == "warn" for x in its):
            status = "warn"
        elif kind in ("separator", "blank", "comment", "end"):
            status = "ctx"
        rows.append(
            {
                "no": i,
                "text": t,
                "status": status,
                "kind": kind,
                "card": ln.card if ln else None,
                "issues": [x.id for x in its],
                "nodes": [n for n in nodes_of.get(mno, []) if not n.startswith(("raw[", "unknown["))],
            }
        )
    stages = {}
    for st in STAGES:
        bad = sum(1 for x in issues if x.stage == st and x.status == "bad")
        warn = sum(1 for x in issues if x.stage == st and x.status == "warn")
        skipped_stage = st == "template" and template is None
        stages[st] = {
            "status": "skipped" if skipped_stage else ("bad" if bad else ("warn" if warn else "ok")),
            "bad": bad,
            "warn": warn,
        }
    stages["graph"]["lines"] = sum(1 for r in rows if r["status"] in ("ok", "warn") and r.get("nodes"))
    blocked = any(x.status == "bad" for x in issues)
    out: dict[str, Any] = {
        "device": device,
        "profile": pid,
        "family": fam.id,
        "verdict": "blocked" if blocked else "passed",
        "lines": rows,
        "issues": [
            x.as_dict(lang)
            for x in sorted(issues, key=lambda x: ({"bad": 0, "warn": 1, "ok": 2}[x.status], x.lines[:1] or [0]))
        ],
        "stages": stages,
        "summary": {
            "lines": len(keep),
            "bad": sum(1 for x in issues if x.status == "bad"),
            "warn": sum(1 for x in issues if x.status == "warn"),
            "ok": sum(1 for x in issues if x.status == "ok"),
            "skipped": len(skipped),
        },
        "merged_text": "\n".join(merged_lines) + "\n",
    }
    if with_script and not blocked:
        out["script"] = _script(base_text or "", out["merged_text"], kb, pid, device, lang)
    return out


def _is_anycast(addr: str) -> bool:
    try:
        return ipaddress.IPv4Address(addr).is_unspecified
    except ValueError:
        return False


def _short(v: Any) -> str:
    s = "" if v is None else str(v)
    return s if len(s) <= 120 else s[:117] + "..."


def _script(base: str, merged: str, kb: KnowledgeBase, pid: str, device: str, lang: str) -> dict[str, Any]:
    """通过校验后：当前配置 → 合并后的增量变更脚本（模块出错时给出原因，不影响校验结论）。"""
    from lmesh.core import change, compare

    try:
        fam = kb.families[kb.profiles[pid].family]
        cur = compare.side_from_text(base or fam.end, kb, pid, device)
        tgt = compare.side_from_text(merged, kb, pid, device)
        r = change.change(cur, tgt, kb, lang=lang, with_impact=False)
    except Exception as e:  # 变更模块不可用或出错
        return {"available": False, "reason": type(e).__name__}
    return {
        "available": True,
        "script": r["script"],
        "script_plain": r["script_plain"],
        "rollback": (r.get("rollback") or {}).get("script_plain", ""),
        "verify_ok": bool((r.get("verify") or {}).get("ok")),
        "ops": len(r["ops"]),
    }
