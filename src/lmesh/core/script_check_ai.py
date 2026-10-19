"""配置检查项目的“AI 一起校验”（REQ-031）。

只把规则文件中 ai: true、且用户勾选了的规则交给 AI；发送的脚本先脱敏（与导入同一密钥，core/ask.sanitize_text），带行号。
AI 返回 {"findings": [{"rule", "line", "evidence", "message", "suggestion"}]}，每条发现由代码校验后才展示：
    rule        必须是这次勾选的规则                                  → 否则拦截 rule_not_selected
    line        必须是脚本中真实存在的命令行                          → 否则拦截 line_invalid
    入图        该行在执行后的配置图上有节点（先入图）                → 否则拦截 not_in_graph
    适用对象    该行属于规则的 target 对象（设备级规则不限）          → 否则拦截 target_mismatch
    代码断言    规则也有代码断言时：代码判断该对象符合规则            → 拦截 code_disagrees；代码也判断不符合 → 已由代码报出（confirmed）
    证据        evidence 必须是该行（脱敏后）原文的一部分             → 不符拦截 evidence_mismatch；没有给出证据 → unverifiable（无法校验）
通过的发现 status=passed，来源 source=ai；被拦截的只计数并列出原因，不作为结论展示。
同一份脱敏后的请求在进程内缓存回复（边写边查时重复提交不重复调用）。
提示词来自 AI skill script-review（REQ-033，core/skills）；每次实际调用按校验结论记入 skill 调用记录（info.skill_run），供用户反馈。
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from typing import Any

from lmesh.core import ai, ask, i18n, skills
from lmesh.core import rules as rulesmod
from lmesh.core.kb import KnowledgeBase
from lmesh.core.objtable import GraphIndex

TASK = "script_check"
REJECT_REASONS = (
    "rule_not_selected",
    "line_invalid",
    "not_in_graph",
    "target_mismatch",
    "code_disagrees",
    "evidence_mismatch",
    "bad_reply",
)
_cache: OrderedDict[str, tuple[str, int | None]] = OrderedDict()
_lock = threading.Lock()

SKILL = "script-review"


def rule_info(r: rulesmod.Rule) -> dict[str, str]:
    """给 AI 的规则说明（也存入 skill 调用记录，回归运行时重建提示）。"""
    return {
        "id": r.id,
        "target": r.target,
        "severity": r.severity,
        "title": r.title.get("en") or r.title.get("zh-CN") or r.id,
        "message": r.message.get("en") or "",
        "suggestion": r.suggestion.get("en") or "",
    }


def messages(skill: skills.Skill, text: str, rules: list[dict[str, str]]) -> tuple[str, str]:
    """script-review 的系统提示与正文：规则清单 + 带行号的脚本（只列非空行）。"""
    rl = [
        f"- {r['id']} (applies to: {r['target']}; severity {r['severity']}): {r['title']}. {r['message']} {r['suggestion']}".strip()
        for r in rules
    ]
    sl = [f"{i} | {ln}" for i, ln in enumerate(text.split("\n"), start=1) if ln.strip()]
    return skill.system_text(), skill.prompt_text(rules="\n".join(rl), script="\n".join(sl)).rstrip("\n")


def review_status(passed: int, unverifiable: int, rejected: int) -> str:
    """一次审查的结论：有被拦截的发现 → rejected；只有无法校验的 → unverifiable；其余（含没有发现）→ passed。"""
    if rejected:
        return "rejected"
    if unverifiable and not passed:
        return "unverifiable"
    return "passed"


def _norm(s: str) -> str:
    return " ".join(str(s).split()).lower()


def _owner_chain(ix: GraphIndex, n: str) -> list[str]:
    out = [n]
    while n in ix.parent:
        n = ix.parent[n]
        out.append(n)
    return out


def run(
    out: dict[str, Any],
    text: str,
    kb: KnowledgeBase,
    rules: list[rulesmod.Rule],
    cfg: dict[str, Any],
    lang: str,
) -> dict[str, Any]:
    settings = cfg.get("settings")
    ids = [str(x) for x in (cfg.get("rules") or [])]
    info: dict[str, Any] = {"enabled": True, "configured": False, "rules": ids, "accepted": 0, "rejected": []}
    if settings is None or not ai.is_configured(settings):
        info["status"] = "not_configured"
        return info
    info["configured"] = True
    selected = [r for r in rules if r.ai and r.enabled and r.id in ids]
    if not selected:
        info["status"] = "no_rules"
        return info
    skill = skills.current(SKILL)
    if not skill.enabled:
        info["status"] = "skill_disabled"
        return info
    sanitized = ask.sanitize_text(text)
    s_lines = sanitized.split("\n")
    o_lines = text.replace("\r\n", "\n").split("\n")
    check_lines = s_lines if len(s_lines) == len(o_lines) else o_lines
    rinfo = [rule_info(r) for r in selected]
    system, prompt = messages(skill, sanitized, rinfo)
    key = hashlib.sha256((system + "\n" + prompt).encode("utf-8")).hexdigest()
    sess = ask._Session(settings, TASK)
    with _lock:
        hit = _cache.get(key)
    info["cached"] = hit is not None
    reply, run_id = hit if hit is not None else ("", None)
    actor = cfg.get("actor")
    inp: dict[str, Any] = {"script": sanitized, "rules": rinfo, "line_kinds": list(out["line_kinds"])}
    if hit is None:
        try:
            reply = sess.call("check", system, prompt)
        except ask.AskError as e:
            info.update(status="error", error=str(e), sent=sess.sent)
            skills.log_run(settings, skill, "script_check", "error", inp, "", {"step": "check"}, sess.info(), actor)
            return info
    info.update(sess.info())
    info["sent"] = sess.sent or [{"step": "check", "system": system, "prompt": prompt, "reply": reply}]

    def finish(status: str, blocked: list[dict[str, Any]], counts: dict[str, int]) -> None:
        """实际调用了 AI 时记一条 skill 调用记录；缓存命中时沿用上次的记录编号。"""
        nonlocal run_id
        if hit is None:
            inp["blocked"] = blocked
            det = {"summary": counts, "rejected": info["rejected"][:100], "confirmed": info.get("confirmed", [])}
            run_id = skills.log_run(settings, skill, "script_check", status, inp, reply, det, sess.info(), actor)
            with _lock:
                _cache[key] = (reply, run_id)
                while len(_cache) > 64:
                    _cache.popitem(last=False)
        info["skill_run"] = run_id
        info["skill"] = {"id": skill.id, "version": skill.active}

    try:
        data = ask._json_reply(reply)
        items = data.get("findings") or []
        if not isinstance(items, list):
            raise ValueError("findings")
    except (ValueError, TypeError):
        info["status"] = "bad_reply"
        info["rejected"].append({"rule": None, "line": None, "reason": "bad_reply"})
        finish("rejected", [], {"passed": 0, "unverifiable": 0, "rejected": 1})
        return info
    info["status"] = "ok"

    g = out.get("_final_graph")
    to_script = out.get("_script_line")
    kinds = out["line_kinds"]
    by_rule = {r.id: r for r in selected}
    nodes_of: dict[int, list[str]] = {}
    if g is not None and to_script is not None:
        for st in g.graph.get("statements") or []:
            sl = to_script(st.line.no)
            if sl:
                nodes_of.setdefault(sl, []).extend(st.nodes)
    merged: dict[int, list[str]] = out.get("_merged_nodes") or {}  # 只进入已有对象的行：按合并图的节点对应
    ix = GraphIndex(g) if g is not None else None
    ev = rulesmod.Evaluator(g) if g is not None else None
    code_hits = {(f.get("rule"), f["line"]) for f in out["issues"] if f["category"] == "rule"}
    n = 0
    for raw in items[:200]:
        if not isinstance(raw, dict):
            info["rejected"].append({"rule": None, "line": None, "reason": "bad_reply"})
            continue
        rid = str(raw.get("rule") or "")
        line = raw.get("line")
        line = int(line) if isinstance(line, int | str) and str(line).isdigit() else None

        def reject(reason: str, rid: str = rid, line: int | None = line) -> None:
            info["rejected"].append({"rule": rid or None, "line": line, "reason": reason})

        rule = by_rule.get(rid)
        if rule is None:
            reject("rule_not_selected")
            continue
        if line is None or not (1 <= line <= len(kinds)) or kinds[line - 1] != "command":
            reject("line_invalid")
            continue
        nodes = nodes_of.get(line) or [n for n in merged.get(line, []) if g is not None and n in g]
        if not nodes or ix is None or g is None or ev is None:
            reject("not_in_graph")
            continue
        inst = None
        if rule.target == rulesmod.DEVICE_TARGET:
            inst = rulesmod.DEVICE_NODE if rulesmod.DEVICE_NODE in g else None
        else:
            for nd in nodes:
                inst = next((x for x in _owner_chain(ix, nd) if g.nodes[x].get("schema") == rule.target), None)
                if inst:
                    break
        if inst is None:
            reject("target_mismatch")
            continue
        if rule.assert_ is not None:
            applies = rule.when is None or ev.test(rule, inst, rule.when)
            if applies and ev.test(rule, inst, rule.assert_):
                reject("code_disagrees")
                continue
            if (rule.id, line) in code_hits:
                info.setdefault("confirmed", []).append({"rule": rid, "line": line})
                continue
        evidence = str(raw.get("evidence") or "").strip()
        if evidence and _norm(evidence) not in _norm(check_lines[line - 1]):
            reject("evidence_mismatch")
            continue
        status = "passed" if evidence else "unverifiable"
        n += 1
        message = str(raw.get("message") or "").strip()[:500] or i18n.t("script_check.ai.no_message", lang)
        out["issues"].append(
            {
                "id": f"a{n}",
                "line": line,
                "lines": [line],
                "severity": rule.severity,
                "category": "ai",
                "code": "ai",
                "source": "ai",
                "status": status,
                "rule": rule.id,
                "rule_title": rule.title,
                "node": inst,
                "evidence": evidence,
                "message": {"key": "script_check.issue.ai", "params": {"rule": rule.id}},
                "text": message,
                "suggestion": str(raw.get("suggestion") or "").strip()[:500],
            }
        )
    info["accepted"] = n
    ai_issues = [i for i in out["issues"] if i.get("source") == "ai"]
    counts = {
        "passed": sum(1 for i in ai_issues if i["status"] == "passed"),
        "unverifiable": sum(1 for i in ai_issues if i["status"] == "unverifiable"),
        "rejected": len(info["rejected"]),
    }
    # 回归运行时不重新建图：与图有关的拦截原因按这次的结论记下来
    graph_reasons = ("not_in_graph", "target_mismatch", "code_disagrees")
    blocked = [x for x in info["rejected"] if x["reason"] in graph_reasons]
    blocked += [{**x, "reason": "confirmed"} for x in info.get("confirmed", [])]
    finish(review_status(counts["passed"], counts["unverifiable"], counts["rejected"]), blocked, counts)
    return info
