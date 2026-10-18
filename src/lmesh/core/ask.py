"""AI 自然语言查询与生成配置（M5-5）。

查询：问题 →（AI）受限的图查询（core/gquery）→（代码）校验语法与 Schema 路径并执行 →（AI）只根据结果组织回答 →
（代码）逐句核对：每句话引用结果中的行（引用编号 = 行号），写明依据的字段与取值（facts）或行数（count），
代码与查询结果比较，标出 passed 通过 / corrected 被更正（AI 原句不作为结论展示，由代码按图上的取值改写）/
unverifiable 无法校验（不是配置事实，只作参考）。
生成：需求 →（AI）配置文本 →（代码）护栏（core/guard）解析、入图、依赖、模板、冲突检查；被拦截时把问题交回 AI 再改，最多 rounds 轮。

发给 AI 的内容一律先脱敏（配置导入时已脱敏；问题、需求与上下文再过一遍脱敏器），实际发送的内容在结果的 sent 中返回供查看。
未配置 AI 时抛出 AskError("ai.not_configured")，调用方返回明确的“未配置”状态；核心功能不受影响。
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from typing import Any

from lmesh.core import ai, compare, config, gquery, i18n
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
    on = ai.is_configured(settings)
    return {
        "configured": on,
        "status": "ready" if on else "not_configured",
        "provider": settings.get("ai.provider") or None,
        "models": {
            "ask": ai.model_for(settings, "ask") if on else None,
            "generate": ai.model_for(settings, "generate") if on else None,
        },
        "sanitize": "always",
        "guard_without_ai": True,
    }


def _require(settings: config.Settings) -> None:
    if not ai.is_configured(settings):
        raise AskError("ai.not_configured", "state", data={"status": "not_configured", "configured": False})


def sanitize_text(text: str) -> str:
    """发给 AI 之前的脱敏：与导入时同一密钥，同一原值替换成同一个值（与库里已脱敏的配置一致）。"""
    return Sanitizer("basic", local_key()).sanitize(text).text


class _Session:
    """一次查询 / 生成中对 AI 的调用：记录发送的内容（脱敏后）、模型、token 与耗时。"""

    def __init__(self, settings: config.Settings, task: str):
        self.settings, self.task = settings, task
        self.sent: list[dict[str, Any]] = []
        self.model = ""
        self.tokens_in = self.tokens_out = 0
        self.ms = 0

    def call(self, step: str, system: str, prompt: str) -> str:
        system, prompt = sanitize_text(system), sanitize_text(prompt)
        self.sent.append({"step": step, "system": system, "prompt": prompt})
        t0 = time.monotonic()
        try:
            reply = ai.complete(self.settings, self.task, prompt, system=system)
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


_Q_SYSTEM = """You turn a network engineer's question about router configurations into ONE read-only query in the
LucidMesh graph query language. The query is validated and executed by code; never answer the question yourself.
Grammar: {syntax}
Operators: {ops}
Notes: {notes}
Reply with JSON only: {{"query": "<query text>"}}"""


def _q_prompt(question: str, devices: list[Any], kb: KnowledgeBase, error: str | None) -> str:
    devs = "\n".join(
        f"- {d.name} (profile {d.g.graph.get('profile')}, family {d.g.graph.get('family')})" for d in devices
    )
    out = f"Devices:\n{devs}\n\nSchema (object -> fields):\n{catalog(kb)}\n\nQuestion: {question}"
    if error:
        out += f"\n\nYour previous query was rejected by the validator: {error}\nWrite a corrected query."
    return out


_A_SYSTEM = """You answer a network engineer's question using ONLY the query result below. Every statement must cite the
result rows it relies on (row numbers), and list the facts it states as {{"row": n, "field": "<column>", "value": "<value>"}};
a statement about how many rows match uses "count". Statements that are not configuration facts (advice, opinions)
have no facts. Answer in {lang}. Reply with JSON only:
{{"statements": [{{"text": "...", "cites": [1], "facts": [{{"row": 1, "field": "description", "value": "..."}}], "count": null}}]}}"""


def _a_prompt(question: str, result: dict[str, Any]) -> str:
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
    body = json.dumps(
        {"columns": ["device", "object", *cols], "rows": rows, "count": result["count"]}, ensure_ascii=False
    )
    return f"Question: {question}\n\nQuery:\n{result['text']}\n\nResult:\n{body}"


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
) -> dict[str, Any]:
    """自然语言查询。devices：topology.Device 列表（查询范围）。"""
    _require(settings)
    if not question.strip():
        raise AskError("ask.empty")
    if not devices:
        raise AskError("ask.no_devices", "not_found")
    sess = _Session(settings, "ask")
    g = gquery.grammar()
    system = _Q_SYSTEM.format(syntax=g["syntax"], ops=", ".join(g["ops"]), notes="; ".join(g["notes"]))
    tried: list[dict[str, Any]] = []
    query: gquery.Query | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    for _ in range(max(1, attempts)):
        reply = sess.call("query", system, _q_prompt(question, devices, kb, error))
        q_text = reply
        try:
            data = _json_reply(reply)
            q = data.get("query")
            q_text = json.dumps(q, ensure_ascii=False) if isinstance(q, dict) else str(q or "")
            query = gquery.from_dict(q) if isinstance(q, dict) else gquery.parse(q_text)
            result = gquery.execute(query, devices, kb)
            tried.append({"query": query.text(), "error": None})
            break
        except gquery.QueryError as e:
            error = i18n.t(e.key, "en", **e.fmt)
            tried.append({"query": q_text[:2000], "error": {"key": e.key, "params": e.fmt}})
        except (ValueError, json.JSONDecodeError):
            error = "the reply was not JSON with a query field"
            tried.append({"query": reply[:2000], "error": {"key": "ask.bad_reply", "params": {}}})
        query = None
    base = {
        "question": question,
        "question_sent": sanitize_text(question),
        "attempts": tried,
        "sent": sess.sent,
    }
    if query is None or result is None:
        return {**base, "status": "query_invalid", "query": None, "result": None, "answer": None, "ai": sess.info()}
    lang_name = {"zh-CN": "Simplified Chinese", "en": "English", "pt-BR": "Brazilian Portuguese"}.get(lang, "English")
    reply = sess.call("answer", _A_SYSTEM.format(lang=lang_name), _a_prompt(question, result))
    try:
        answer = _json_reply(reply)
    except (ValueError, json.JSONDecodeError):
        answer = {"statements": [{"text": reply.strip()[:4000], "cites": [], "facts": []}]}
    checked = verify(answer, result, lang)
    return {
        **base,
        "status": "answered",
        "query": query.as_dict(),
        "query_text": query.text(),
        "result": result,
        "answer": checked,
        "ai": sess.info(),
    }


# ---------------------------------------------------------------- 生成配置


_G_SYSTEM = """You write router configuration for the platform family {family} (profile {profile}). Output only the
configuration lines to add, in the device's own syntax, inside one ``` code block, without session commands
(no system-view / configure terminal / commit / end). The configuration will be parsed and checked by code before
anyone sees it."""


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
    sess = _Session(settings, "generate")
    system = _G_SYSTEM.format(family=fam, profile=pid)
    out_rounds = []
    feedback = ""
    for n in range(1, max(1, rounds) + 1):
        prompt = f"Device: {device}\nExisting objects:\n{ctx or '(empty configuration)'}\n\nRequest: {request}"
        if feedback:
            prompt += f"\n\nThe previous attempt was blocked by the checks:\n{feedback}\nReturn the full corrected configuration."
        reply = sess.call(f"generate.{n}", system, prompt)
        m = _CODE.search(reply)
        text = (m.group(1) if m else reply).strip("\n")
        try:
            checked = guard.guard(text, kb, pid, base_text, device, others, template, lang)
        except guard.GuardError as e:
            checked = {"verdict": "blocked", "error": {"key": e.key, "params": e.fmt}, "issues": [], "lines": []}
        out_rounds.append({"round": n, "text": text, "guard": checked})
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
    }
