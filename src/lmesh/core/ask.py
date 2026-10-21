"""AI 自然语言查询与生成配置（M5-5）。

查询：问题 →（AI）受限的图查询（core/gquery）→（代码）校验语法与 Schema 路径并执行 →（AI）只根据结果组织回答 →
（代码）逐句核对：每句话引用结果中的行（引用编号 = 行号），写明依据的字段与取值（facts）或行数（count），
代码与查询结果比较，标出 passed 通过 / corrected 被更正（AI 原句不作为结论展示，由代码按图上的取值改写）/
unverifiable 无法校验（不是配置事实，只作参考）。
生成：需求 →（AI）配置文本 →（代码）护栏（core/guard）解析、入图、依赖、模板、冲突检查；被拦截时把问题交回 AI 再改，最多 rounds 轮。

发给 AI 的内容一律先脱敏（配置导入时已脱敏；问题、需求与上下文再过一遍脱敏器），实际发送的内容在结果的 sent 中返回供查看。
提示词来自 AI skill（REQ-033，core/skills）：ask-query、ask-answer、config-generate；每次调用按代码校验的结论记入 skill 调用记录，
结果的 skill_runs 给出记录编号，供用户反馈（点赞 / 点踩 / 更正）。
未配置 AI 时抛出 AskError("ai.not_configured")，调用方返回明确的“未配置”状态；核心功能不受影响。
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from typing import Any

from lmesh.core import ai, compare, config, gquery, i18n, skills
from lmesh.core.kb import KnowledgeBase
from lmesh.core.objtable import display, fields_of
from lmesh.core.sanitize import Sanitizer, local_key

STATUSES = ("passed", "corrected", "unverifiable")
_JSON = re.compile(r"\{.*\}", re.S)
_CODE = re.compile(r"```[a-zA-Z0-9_-]*\n(.*?)```", re.S)


class AskError(ValueError):
    def __init__(self, key: str, kind: str = "param", data: Any = None, **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.data, self.fmt = key, kind, data, fmt


def status(settings: config.Settings) -> dict[str, Any]:
    """AI 查询入口是否可用（界面据此显示或隐藏）。"""
    res = ai.resolve(settings)
    on = res.configured
    return {
        "configured": on,
        "status": "ready" if on else "not_configured",
        "reason": res.reason,
        "provider": ai.provider_of(settings),
        "models": {
            "ask": ai.model_for(settings, "ask") if on else None,
            "generate": ai.model_for(settings, "generate") if on else None,
        },
        "sanitize": "always",
        "guard_without_ai": True,
        "images": bool(settings.get("ai.ask_images")),  # REQ-053：AI 查询可以附带图片（管理员开启）
    }


def _require(settings: config.Settings) -> None:
    if not ai.is_configured(settings):
        raise AskError("ai.not_configured", "state", data=ai.not_configured_data(settings))


def sanitize_text(text: str) -> str:
    """发给 AI 之前的脱敏：与导入时同一密钥，同一原值替换成同一个值（与库里已脱敏的配置一致）。
    当前项目有脱敏补充（M8-5 脱敏复核采纳的规则）时一并替换。"""
    from lmesh.core import projects

    sc = projects.current()
    return Sanitizer("basic", local_key(), redact=list(sc.redact) if sc else None).sanitize(text).text


class _Session:
    """一次查询 / 生成中对 AI 的调用：记录发送的内容（脱敏后）、模型、token 与耗时。"""

    def __init__(self, settings: config.Settings, task: str):
        self.settings, self.task = settings, task
        self.sent: list[dict[str, Any]] = []
        self.model = ""
        self.tokens_in = self.tokens_out = 0
        self.ms = 0

    def call(self, step: str, system: str, prompt: str, feature: str = "") -> str:
        system, prompt = sanitize_text(system), sanitize_text(prompt)
        self.sent.append({"step": step, "system": system, "prompt": prompt})
        t0 = time.monotonic()
        try:
            reply = ai.complete(self.settings, self.task, prompt, system=system, feature=feature)
        except ai.AIError as e:
            raise AskError(str(e), "external", data={"status": "ai_error", "sent": self.sent}) from e
        finally:
            self.ms += int((time.monotonic() - t0) * 1000)
        self.model = reply.model
        self.tokens_in += reply.tokens_in
        self.tokens_out += reply.tokens_out
        self.sent[-1]["reply"] = reply.text
        return reply.text

    def info(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "calls": len(self.sent),
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "ms": self.ms,
        }


def skill_or_error(sid: str) -> skills.Skill:
    """取生效的 skill；停用时按“未配置”同样的方式返回状态（kind=state）。"""
    try:
        return skills.require_enabled(sid)
    except skills.SkillError as e:
        raise AskError(e.key, "state" if e.kind == "state" else "param", data=e.data, **e.fmt) from e


def call_logged(
    sess: _Session,
    skill: skills.Skill,
    step: str,
    system: str,
    prompt: str,
    source: str,
    inp: dict[str, Any],
    actor: skills.Actor | None,
) -> str:
    """调用 AI；调用失败时记一条 error 的 skill 调用记录再抛出。"""
    try:
        return sess.call(step, system, prompt, skill.id)
    except AskError:
        skills.log_run(sess.settings, skill, source, "error", inp, "", {"step": step}, sess.info(), actor)
        raise


def last_info(sess: _Session) -> dict[str, Any]:
    """会话到目前为止的模型、token 与耗时（写入 skill 调用记录）。"""
    return {"model": sess.model, "tokens_in": sess.tokens_in, "tokens_out": sess.tokens_out, "ms": sess.ms}


def _run_ref(step: str, skill: skills.Skill, run_id: int | None, status: str) -> dict[str, Any]:
    return {"step": step, "skill": skill.id, "version": skill.active, "run_id": run_id, "status": status}


def _json_reply(text: str) -> dict[str, Any]:
    m = _CODE.search(text)
    body = m.group(1) if m else text
    m2 = _JSON.search(body)
    if not m2:
        raise ValueError("no json")
    data = json.loads(m2.group(0))
    if not isinstance(data, dict):
        raise ValueError("not an object")
    return data


# ---------------------------------------------------------------- 查询


def catalog(kb: KnowledgeBase, limit_types: int = 400) -> str:
    """给 AI 的 Schema 目录：对象类型 → 可用字段（路径:类型）。"""
    lines = []
    for n in sorted(kb.nodes.values(), key=lambda x: x.id):
        if n.type != "object":
            continue
        fs = [f"{f['path']}:{f['type']}" for f in fields_of(kb, n, depth=2) if not f.get("secret")]
        lines.append(f"{n.id} -> {', '.join(fs[:60])}")
        if len(lines) >= limit_types:
            break
    return "\n".join(lines)


def devices_list(devices: list[Any]) -> list[dict[str, Any]]:
    """查询范围的设备（给 AI 的上下文与 skill 调用记录）：名称、Profile、平台族。"""
    return [{"name": d.name, "profile": d.g.graph.get("profile"), "family": d.g.graph.get("family")} for d in devices]


# 管理员改过的 skill 版本里可能没有这两个模板（REQ-052、REQ-053 之前改的），这时用内置的写法
_CONTEXT_FALLBACK = (
    "Earlier questions in this conversation (oldest first) and the queries that answered them.\n"
    'The new question may refer to them (for example "only those on device X"); still write ONE complete query.\n'
    "{history}"
)
_REFERENCES_FALLBACK = (
    "Reference material attached by the user (documents, sanitised; images if any are attached to this message).\n"
    "Code cannot verify it: when a statement relies only on this material, give it no cites and no facts.\n"
    "{references}"
)
HISTORY_TURNS = 5
REFERENCE_CHARS = 30000


def history_text(history: list[dict[str, Any]]) -> str:
    """会话前几轮（REQ-052）：[{question, query}] → 给 AI 的文字（最多 HISTORY_TURNS 轮；发送前整体再脱敏）。"""
    lines = []
    for i, h in enumerate(history[-HISTORY_TURNS:], 1):
        lines.append(f"{i}. Q: {str(h.get('question') or '').strip()[:1000]}")
        if h.get("query"):
            lines.append(f"   query: {str(h['query'])[:1000]}")
    return "\n".join(lines)


def query_messages(
    skill: skills.Skill,
    question: str,
    devices: list[dict[str, Any]],
    kb: KnowledgeBase,
    error: str | None,
    history: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """ask-query 的系统提示与正文；history 是同一会话前几轮的问题与查询（REQ-052）。"""
    g = gquery.grammar()
    system = skill.system_text(syntax=g["syntax"], ops=", ".join(g["ops"]), notes="; ".join(g["notes"]))
    devs = "\n".join(f"- {d['name']} (profile {d.get('profile')}, family {d.get('family')})" for d in devices)
    prompt = skill.prompt_text(devices=devs, catalog=catalog(kb), question=question)
    if history:
        tpl = skill.templates.get("context") or _CONTEXT_FALLBACK
        prompt += "\n\n" + skills.render(tpl, {"history": history_text(history)})
    if error:
        prompt += "\n\n" + skill.prompt_text("retry", error=error)
    return system, prompt


LANG_NAMES = {"zh-CN": "Simplified Chinese", "en": "English", "pt-BR": "Brazilian Portuguese"}


def answer_messages(
    skill: skills.Skill, question: str, result: dict[str, Any], lang: str, references: str = ""
) -> tuple[str, str]:
    """ask-answer 的系统提示与正文；references 是附件文档的文字（REQ-053，参考资料，代码无法核对）。"""
    system = skill.system_text(lang=LANG_NAMES.get(lang, "English"))
    prompt = skill.prompt_text(question=question, query=result["text"], result=result_body(result))
    if references.strip():
        tpl = skill.templates.get("references") or _REFERENCES_FALLBACK
        prompt += "\n\n" + skills.render(tpl, {"references": references[:REFERENCE_CHARS]})
    return system, prompt


def slim_result(result: dict[str, Any], limit: int = 500) -> dict[str, Any]:
    """核对回答所需的查询结果（skill 调用记录与回归集用）。"""
    rows = [
        {
            "n": r["n"],
            "device": r["device"],
            "label": r["label"],
            "node": r["node"],
            "cells": {
                f: {k: c.get(k) for k in ("value", "origin", "secret") if k in c}
                for f, c in (r.get("cells") or {}).items()
            },
        }
        for r in result["rows"][:limit]
    ]
    cols = [{"field": c["field"]} for c in result["columns"]]
    return {"text": result["text"], "columns": cols, "rows": rows, "count": result["count"]}


def answer_status(summary: dict[str, int]) -> str:
    if summary.get("corrected"):
        return "corrected"
    if summary.get("passed"):
        return "passed"
    return "unverifiable"


def result_body(result: dict[str, Any]) -> str:
    cols = [c["field"] for c in result["columns"]]
    rows = []
    for r in result["rows"]:
        cells: dict[str, str | None] = {}
        for f in cols:
            c = r["cells"][f]
            if c.get("secret"):
                cells[f] = "configured" if c.get("value") else "not configured"
            elif c["origin"] in ("none", "unsupported"):
                cells[f] = None
            else:
                cells[f] = display(c["value"]) + (" (default)" if c["origin"] == "default" else "")
        rows.append({"row": r["n"], "device": r["device"], "object": r["label"], **cells})
    return json.dumps(
        {"columns": ["device", "object", *cols], "rows": rows, "count": result["count"]}, ensure_ascii=False
    )


def _norm(v: Any) -> str:
    s = display(v).strip().lower()
    s = re.sub(r"\s*\(default\)$", "", s)
    if re.match(r"^[a-z\-]+[0-9]", s):
        with contextlib.suppress(Exception):
            s = compare.interface_name(s).lower()
    return s


def _actual(row: dict[str, Any], f: str) -> tuple[bool, Any]:
    if f in ("device",):
        return True, row["device"]
    if f in ("object", "label", "@key", "key"):
        return True, row["label"]
    c = row["cells"].get(f)
    if c is None:
        return False, None
    if c.get("secret"):
        return True, "configured" if c.get("value") else "not configured"
    if c["origin"] in ("none", "unsupported"):
        return True, None
    return True, c["value"]


def _same(claimed: Any, actual: Any) -> bool:
    if actual is None:
        return _norm(claimed) in ("", "none", "null", "not configured", "未配置", "não configurado", "-", "—")
    vals = actual if isinstance(actual, list) else [actual]
    cn = _norm(claimed)
    if cn == _norm(actual):
        return True
    if any(cn == _norm(v) for v in vals):
        return True
    if isinstance(actual, bool) or str(actual).lower() in ("true", "false"):
        yes = {"true", "yes", "enabled", "on", "是", "sim", "启用", "开启", "已启用"}
        no = {"false", "no", "disabled", "off", "否", "não", "未启用", "关闭"}
        a = str(actual).lower() == "true"
        return (cn in yes and a) or (cn in no and not a)
    return False


def verify(answer: dict[str, Any], result: dict[str, Any], lang: str) -> dict[str, Any]:
    """逐句核对 AI 的回答（代码与查询结果比较）。"""
    rows = {r["n"]: r for r in result["rows"]}
    out = []
    for st in answer.get("statements") or []:
        if not isinstance(st, dict):
            continue
        text = str(st.get("text") or "")
        cites = [int(x) for x in st.get("cites") or [] if str(x).isdigit()]
        facts_in = [f for f in st.get("facts") or [] if isinstance(f, dict)]
        issues: list[dict[str, Any]] = []
        facts = []
        for c in cites:
            if c not in rows:
                issues.append({"key": "ask.fix.cite", "params": {"row": c}})
        for f in facts_in:
            try:
                rn = int(f.get("row"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                rn = -1
            field = str(f.get("field") or "")
            claimed = f.get("value")
            row = rows.get(rn)
            if row is None:
                facts.append({"row": rn, "field": field, "value": claimed, "actual": None, "ok": False})
                issues.append({"key": "ask.fix.cite", "params": {"row": rn}})
                continue
            known, actual = _actual(row, field)
            ok = known and _same(claimed, actual)
            facts.append({"row": rn, "field": field, "value": claimed, "actual": actual, "ok": ok, "node": row["node"]})
            if not known:
                issues.append({"key": "ask.fix.field", "params": {"row": rn, "field": field}})
            elif not ok:
                issues.append(
                    {
                        "key": "ask.fix.value",
                        "params": {
                            "row": rn,
                            "object": f"{row['device']} {row['label']}",
                            "field": field,
                            "actual": display(actual) if actual is not None else i18n.t("ask.not_set", lang),
                            "claimed": display(claimed),
                        },
                    }
                )
        count = st.get("count")
        count_ok = None
        if count is not None:
            try:
                count_ok = int(count) == int(result["count"])
            except (TypeError, ValueError):
                count_ok = False
            if not count_ok:
                issues.append({"key": "ask.fix.count", "params": {"n": result["count"], "claimed": count}})
        if issues:
            status = "corrected"
        elif facts or count_ok:
            status = "passed"
        else:
            status = "unverifiable"
        corrected = " ".join(i18n.t(i["key"], lang, **i["params"]) for i in issues) if issues else None
        out.append(
            {
                "text": text,
                "cites": cites,
                "facts": facts,
                "count": count,
                "status": status,
                "issues": issues,
                "corrected_text": corrected,
                "nodes": sorted({rows[c]["node"] for c in cites if c in rows}),
            }
        )
    summary = {s: sum(1 for x in out if x["status"] == s) for s in STATUSES}
    return {"statements": out, "summary": summary}


def ask(
    question: str,
    devices: list[Any],
    kb: KnowledgeBase,
    settings: config.Settings,
    lang: str = "zh-CN",
    attempts: int = 2,
    actor: skills.Actor | None = None,
    history: list[dict[str, Any]] | None = None,
    references: str = "",
    images: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """自然语言查询。devices：topology.Device 列表（查询范围）。
    会话（REQ-052、REQ-053）：history 为前几轮 [{question, query}]；references 为附件文档文字；images 为用户确认过的图片。"""
    if images:
        with ai.with_images(images):
            return ask(question, devices, kb, settings, lang, attempts, actor, history, references, None)
    _require(settings)
    if not question.strip():
        raise AskError("ask.empty")
    if not devices:
        raise AskError("ask.no_devices", "not_found")
    sk_q = skill_or_error("ask-query")
    sk_a = skill_or_error("ask-answer")
    sess = _Session(settings, "ask")
    devs = devices_list(devices)
    tried: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    query: gquery.Query | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    for _ in range(max(1, attempts)):
        system, prompt = query_messages(sk_q, question, devs, kb, error, history)
        inp: dict[str, Any] = {"question": question, "devices": devs, "error": error}
        if history:
            inp["history"] = len(history[-HISTORY_TURNS:])
        reply = call_logged(sess, sk_q, "query", system, prompt, "ask", inp, actor)
        q_text = reply
        failure: dict[str, Any] | None = None
        try:
            data = _json_reply(reply)
            q = data.get("query")
            q_text = json.dumps(q, ensure_ascii=False) if isinstance(q, dict) else str(q or "")
            query = gquery.from_dict(q) if isinstance(q, dict) else gquery.parse(q_text)
            result = gquery.execute(query, devices, kb)
            tried.append({"query": query.text(), "error": None})
        except gquery.QueryError as e:
            error = i18n.t(e.key, "en", **e.fmt)
            failure = {"key": e.key, "params": e.fmt}
            tried.append({"query": q_text[:2000], "error": failure})
        except (ValueError, json.JSONDecodeError):
            error = "the reply was not JSON with a query field"
            failure = {"key": "ask.bad_reply", "params": {}}
            tried.append({"query": reply[:2000], "error": failure})
        st = "rejected" if failure else "passed"
        det = {"query": tried[-1]["query"], "error": failure, "summary": {"status": st}}
        rid = skills.log_run(settings, sk_q, "ask", st, inp, reply, det, last_info(sess), actor)
        runs.append(_run_ref("query", sk_q, rid, st))
        if failure is None:
            break
        query = None
    base = {
        "question": question,
        "question_sent": sanitize_text(question),
        "attempts": tried,
        "sent": sess.sent,
    }
    if query is None or result is None:
        return {
            **base,
            "status": "query_invalid",
            "query": None,
            "result": None,
            "answer": None,
            "ai": sess.info(),
            "skill_runs": runs,
        }
    system, prompt = answer_messages(sk_a, question, result, lang, references)
    inp = {"question": question, "lang": lang, "result": slim_result(result)}
    if references.strip():
        inp["references"] = len(references)
    reply = call_logged(sess, sk_a, "answer", system, prompt, "ask", inp, actor)
    try:
        answer = _json_reply(reply)
    except (ValueError, json.JSONDecodeError):
        answer = {"statements": [{"text": reply.strip()[:4000], "cites": [], "facts": []}]}
    checked = verify(answer, result, lang)
    st = answer_status(checked["summary"])
    det = {"summary": checked["summary"], "issues": [i for x in checked["statements"] for i in x["issues"]][:50]}
    rid = skills.log_run(settings, sk_a, "ask", st, inp, reply, det, last_info(sess), actor)
    runs.append(_run_ref("answer", sk_a, rid, st))
    return {
        **base,
        "status": "answered",
        "query": query.as_dict(),
        "query_text": query.text(),
        "result": result,
        "answer": checked,
        "ai": sess.info(),
        "skill_runs": runs,
    }


# ---------------------------------------------------------------- 生成配置


def generate_messages(
    skill: skills.Skill, family: str, profile: str, device: str, inventory: str, request: str, feedback: str
) -> tuple[str, str]:
    """config-generate 的系统提示与正文。"""
    system = skill.system_text(family=family, profile=profile)
    prompt = skill.prompt_text(device=device, inventory=inventory or "(empty configuration)", request=request)
    if feedback:
        prompt += "\n\n" + skill.prompt_text("retry", feedback=feedback)
    return system, prompt


def code_block(reply: str) -> str:
    m = _CODE.search(reply)
    return (m.group(1) if m else reply).strip("\n")


def inventory(g: Any, kb: KnowledgeBase, limit: int = 60) -> str:
    """当前配置中各类对象的名字（给 AI 的上下文，不含取值与原文）。"""
    from lmesh.core.objtable import GraphIndex

    ix = GraphIndex(g)
    parts = []
    for sid in (
        "interface",
        "vrf.instance",
        "rp.policy",
        "rp.prefix_list",
        "acl.instance",
        "bgp.instance",
        "bridge_domain",
    ):
        if sid not in kb.nodes:
            continue
        names = [display(g.nodes[n].get("key")) for n in ix.objects(sid)][:limit]
        if names:
            parts.append(f"{sid}: {', '.join(names)}")
    return "\n".join(parts)


def guard_issues(checked: dict[str, Any]) -> list[dict[str, Any]]:
    """护栏拦截的问题（skill 调用记录用）。"""
    out = [
        {"line": i.get("line"), "rule": i.get("rule"), "message": i.get("message")}
        for i in checked.get("issues", [])
        if i.get("status") == "bad"
    ]
    if checked.get("error"):
        out.insert(0, {"line": None, "rule": "error", "message": checked["error"]})
    return out[:50]


def generate(
    request: str,
    kb: KnowledgeBase,
    settings: config.Settings,
    base_text: str | None,
    device: str,
    profile: str | None,
    others: list[Any] | None = None,
    template: Any = None,
    lang: str = "zh-CN",
    rounds: int = 2,
    actor: skills.Actor | None = None,
) -> dict[str, Any]:
    """AI 生成配置 → 护栏校验；被拦截时把问题交回 AI 修改，最多 rounds 轮。"""
    from lmesh.core import analysis, guard
    from lmesh.core import graph as graphmod

    _require(settings)
    if not request.strip():
        raise AskError("ask.empty")
    pid = profile
    ctx = ""
    if base_text:
        try:
            res = analysis.parse_text(base_text, kb, profile)
        except analysis.AnalysisError as e:
            raise AskError(str(e), profile=profile or "") from e
        pid = res.profile
        ctx = inventory(graphmod.build(res.parsed, kb, res.profile, device), kb)
    if not pid or pid not in kb.profiles:
        raise AskError("ask.need_profile")
    fam = kb.profiles[pid].family
    skill = skill_or_error("config-generate")
    sess = _Session(settings, "generate")
    out_rounds = []
    runs: list[dict[str, Any]] = []
    feedback = ""
    for n in range(1, max(1, rounds) + 1):
        system, prompt = generate_messages(skill, fam, pid, device, ctx, request, feedback)
        inp = {
            "device": device,
            "profile": pid,
            "family": fam,
            "request": request,
            "inventory": ctx,
            "feedback": feedback,
        }
        reply = call_logged(sess, skill, f"generate.{n}", system, prompt, "generate", inp, actor)
        text = code_block(reply)
        try:
            checked = guard.guard(text, kb, pid, base_text, device, others, template, lang)
        except guard.GuardError as e:
            checked = {"verdict": "blocked", "error": {"key": e.key, "params": e.fmt}, "issues": [], "lines": []}
        st = "passed" if checked.get("verdict") == "passed" else "rejected"
        det = {"verdict": checked.get("verdict"), "summary": checked.get("summary"), "issues": guard_issues(checked)}
        rid = skills.log_run(settings, skill, "generate", st, inp, reply, det, last_info(sess), actor)
        runs.append(_run_ref(f"generate.{n}", skill, rid, st))
        out_rounds.append({"round": n, "text": text, "guard": checked, "skill_run": rid})
        if checked.get("verdict") == "passed":
            break
        feedback = (
            "\n".join(
                f"- line {i.get('line')}: {i18n.t(i['message']['key'], 'en', **i['message']['params'])}"
                for i in checked.get("issues", [])
                if i.get("status") == "bad"
            )
            or "- the configuration could not be parsed"
        )
    final: dict[str, Any] = out_rounds[-1]
    return {
        "request": request,
        "request_sent": sanitize_text(request),
        "device": device,
        "profile": pid,
        "rounds": out_rounds,
        "final": final,
        "verdict": final["guard"].get("verdict"),
        "sent": sess.sent,
        "ai": sess.info(),
        "skill_runs": runs,
    }
