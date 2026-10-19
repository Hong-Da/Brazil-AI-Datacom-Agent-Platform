"""AI skill 的试运行、回归运行与进化（REQ-033）。

每个 skill 有一个运行器：build（由输入算出系统提示与正文，与线上调用用同一套函数）+ check（代码校验回复，给出状态与得分）。
输入就是 skill 调用记录 / 回归案例里保存的 input（已脱敏），或内置定义里的样例（samples）。
    试运行  mode=ai：真实调用 AI（需要配置 AI）；mode=replay：用样例或给出的回复走一遍渲染与代码校验（未配置 AI 也能用，标明不是真实 AI）
    进化    AI（skill-evolve）根据回归集里的失败案例与用户更正提出候选版本 → 代码检查候选保留全部变量 →
            用回归集分别运行旧版本与候选版本、按代码校验结果打分（通过 1、无法校验 0.5、其余 0）→ 存为待批准的进化，
            管理员批准后才发布（skills.decide），不自动上线（D-0148）。
回归运行不重新建图：脚本审查用调用时记下的行类型与图相关的拦截结论；配置生成按设备名取数据库中该设备的最新配置作为护栏的基准。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lmesh.core import ai, ask, config, gquery, i18n, skills
from lmesh.core.kb import KnowledgeBase

Progress = Callable[[int, str], None]


@dataclass
class Ctx:
    settings: config.Settings
    kb_loader: Callable[[], KnowledgeBase]
    lang: str = "zh-CN"
    _kb: KnowledgeBase | None = field(default=None, repr=False)

    @property
    def kb(self) -> KnowledgeBase:
        if self._kb is None:
            self._kb = self.kb_loader()
        return self._kb

    @property
    def db_url(self) -> str:
        return self.settings.database_url


def _item(ok: bool, reason: str, text: str = "", **extra: Any) -> dict[str, Any]:
    return {"ok": ok, "reason": reason, "text": text, **extra}


def _result(status: str, items: list[dict[str, Any]] | None = None, **detail: Any) -> dict[str, Any]:
    return {"status": status, "score": skills.SCORES.get(status, 0.0), "items": items or [], "detail": detail}


# ---------------------------------------------------------------- card-extract


def _card_build(s: skills.Skill, inp: dict[str, Any], ctx: Ctx) -> tuple[str, str]:
    return s.system_text(), s.prompt_text(title=inp.get("title", ""), format=inp.get("format", ""))


def _card_check(s: skills.Skill, inp: dict[str, Any], reply: str, ctx: Ctx) -> dict[str, Any]:
    from lmesh.core.kb import syntax as syn

    fixed = reply.strip().strip("`").splitlines()[0].strip() if reply.strip() else ""
    try:
        syn.parse(fixed)
    except syn.SyntaxErrorKB as e:
        return _result("rejected", [_item(False, "syntax", str(e)[:300])], syntax=fixed)
    return _result("passed", [_item(True, "syntax", fixed)], syntax=fixed)


# ---------------------------------------------------------------- ask-query


def _devices(inp: dict[str, Any], ctx: Ctx) -> list[dict[str, Any]]:
    devs = inp.get("devices")
    if isinstance(devs, list):
        return devs
    from lmesh.core import importer, store

    store.upgrade(ctx.db_url)
    out = []
    for d in importer.list_devices(ctx.db_url):
        prof = ctx.kb.profiles.get(d["profile"]) if d.get("profile") else None
        out.append({"name": d["name"], "profile": d.get("profile") or None, "family": prof.family if prof else None})
    return out


def _query_build(s: skills.Skill, inp: dict[str, Any], ctx: Ctx) -> tuple[str, str]:
    return ask.query_messages(s, inp.get("question", ""), _devices(inp, ctx), ctx.kb, inp.get("error"))


def _query_check(s: skills.Skill, inp: dict[str, Any], reply: str, ctx: Ctx) -> dict[str, Any]:
    try:
        data = ask._json_reply(reply)
        q = data.get("query")
        q_text = json.dumps(q, ensure_ascii=False) if isinstance(q, dict) else str(q or "")
        query = gquery.from_dict(q) if isinstance(q, dict) else gquery.parse(q_text)
        names = [d["name"] for d in _devices(inp, ctx)]
        gquery.validate(query, ctx.kb, names or None)
    except gquery.QueryError as e:
        msg = i18n.t(e.key, ctx.lang, **e.fmt)
        return _result("rejected", [_item(False, e.key, msg)], error={"key": e.key, "params": e.fmt})
    except (ValueError, TypeError, json.JSONDecodeError):
        return _result("rejected", [_item(False, "ask.bad_reply", i18n.t("ask.bad_reply", ctx.lang))])
    return _result("passed", [_item(True, "gquery.validate", query.text())], query=query.text())


# ---------------------------------------------------------------- ask-answer


def _answer_build(s: skills.Skill, inp: dict[str, Any], ctx: Ctx) -> tuple[str, str]:
    return ask.answer_messages(s, inp.get("question", ""), inp["result"], inp.get("lang") or ctx.lang)


def _answer_check(s: skills.Skill, inp: dict[str, Any], reply: str, ctx: Ctx) -> dict[str, Any]:
    try:
        answer = ask._json_reply(reply)
    except (ValueError, json.JSONDecodeError):
        answer = {"statements": [{"text": reply.strip()[:4000], "cites": [], "facts": []}]}
    checked = ask.verify(answer, inp["result"], inp.get("lang") or ctx.lang)
    items = [
        _item(st["status"] != "corrected", st["status"], st["corrected_text"] or st["text"])
        for st in checked["statements"]
    ]
    return _result(ask.answer_status(checked["summary"]), items, summary=checked["summary"])


# ---------------------------------------------------------------- config-generate


def _generate_build(s: skills.Skill, inp: dict[str, Any], ctx: Ctx) -> tuple[str, str]:
    prof = ctx.kb.profiles.get(inp.get("profile") or "")
    fam = inp.get("family") or (prof.family if prof else "")
    return ask.generate_messages(
        s,
        fam,
        inp.get("profile") or "",
        inp.get("device") or "device",
        inp.get("inventory") or "",
        inp.get("request") or "",
        inp.get("feedback") or "",
    )


def _generate_check(s: skills.Skill, inp: dict[str, Any], reply: str, ctx: Ctx) -> dict[str, Any]:
    from lmesh.core import guard, history, store

    pid = inp.get("profile") or ""
    if pid not in ctx.kb.profiles:
        return _result("error", [_item(False, "ask.need_profile", i18n.t("ask.need_profile", ctx.lang))])
    base = None
    device = inp.get("device") or "device"
    try:
        store.upgrade(ctx.db_url)
        hit = history.latest_text(ctx.db_url, device)
        base = hit[3] if hit else None
    except Exception:  # 没有数据库或设备时按空配置校验
        base = None
    text = ask.code_block(reply)
    try:
        checked = guard.guard(text, ctx.kb, pid, base, device, None, None, ctx.lang, False)
    except guard.GuardError as e:
        return _result("rejected", [_item(False, e.key, i18n.t(e.key, ctx.lang, **e.fmt))])
    bad = [i for i in checked.get("issues", []) if i.get("status") == "bad"]
    items = [_item(False, i["rule"], i["text"], line=i.get("line")) for i in bad]
    st = "passed" if checked.get("verdict") == "passed" else "rejected"
    return _result(st, items or [_item(True, "guard", checked.get("verdict", ""))], verdict=checked.get("verdict"))


# ---------------------------------------------------------------- script-review


def _review_build(s: skills.Skill, inp: dict[str, Any], ctx: Ctx) -> tuple[str, str]:
    from lmesh.core import script_check_ai

    return script_check_ai.messages(s, inp.get("script", ""), inp.get("rules") or [])


def _review_check(s: skills.Skill, inp: dict[str, Any], reply: str, ctx: Ctx) -> dict[str, Any]:
    """不重新建图：按记下的行类型、勾选的规则、与图有关的拦截结论（blocked）与证据核对每条发现。"""
    from lmesh.core import script_check_ai

    try:
        data = ask._json_reply(reply)
        found = data.get("findings") or []
        if not isinstance(found, list):
            raise ValueError("findings")
    except (ValueError, TypeError, json.JSONDecodeError):
        return _result("rejected", [_item(False, "bad_reply")])
    lines = str(inp.get("script", "")).split("\n")
    kinds = inp.get("line_kinds") or [
        "command" if ln.strip() and not ln.strip().startswith("#") else "blank" for ln in lines
    ]
    rules = {r["id"] for r in inp.get("rules") or []}
    blocked = {(b.get("rule"), b.get("line")): b.get("reason") for b in inp.get("blocked") or []}
    items: list[dict[str, Any]] = []
    for raw in found[:200]:
        if not isinstance(raw, dict):
            items.append(_item(False, "bad_reply"))
            continue
        rid = str(raw.get("rule") or "")
        ln = raw.get("line")
        line = int(ln) if isinstance(ln, int | str) and str(ln).isdigit() else None
        evidence = str(raw.get("evidence") or "").strip()
        if rid not in rules:
            items.append(_item(False, "rule_not_selected", rid, line=line))
        elif line is None or not (1 <= line <= len(kinds)) or kinds[line - 1] != "command":
            items.append(_item(False, "line_invalid", rid, line=line))
        elif blocked.get((rid, line)) not in (None, "confirmed"):
            items.append(_item(False, str(blocked[(rid, line)]), rid, line=line))
        elif evidence and " ".join(evidence.split()).lower() not in " ".join(lines[line - 1].split()).lower():
            items.append(_item(False, "evidence_mismatch", evidence, line=line))
        else:
            items.append(_item(True, "passed" if evidence else "unverifiable", rid, line=line))
    passed = sum(1 for i in items if i["ok"] and i["reason"] == "passed")
    unver = sum(1 for i in items if i["ok"] and i["reason"] == "unverifiable")
    rejected = sum(1 for i in items if not i["ok"])
    st = script_check_ai.review_status(passed, unver, rejected)
    return _result(st, items, summary={"passed": passed, "unverifiable": unver, "rejected": rejected})


# ---------------------------------------------------------------- skill-evolve


def _evolve_vars(target: skills.Skill, case_list: list[dict[str, Any]]) -> dict[str, str]:
    cs = []
    for c in case_list:
        cs.append(
            {
                "case": c.get("id"),
                "reason": c.get("reason"),
                "input": json.dumps(c.get("input"), ensure_ascii=False)[:2000],
                "reply": str(c.get("reply") or "")[:2000],
                "check": (c.get("detail") or {}).get("summary") or (c.get("detail") or {}).get("error"),
                "issues": ((c.get("detail") or {}).get("issues") or (c.get("detail") or {}).get("rejected") or [])[:10],
                "user_correction": c.get("expect") or None,
            }
        )
    return {
        "skill": target.id,
        "title": target.title.get("en") or target.id,
        "checks": ", ".join(skills.CHECKS.get(k, {}).get("en", k) for k in target.checks),
        "system": target.system,
        "prompt": target.prompt,
        "templates": json.dumps(target.templates, ensure_ascii=False, indent=2),
        "examples": json.dumps(target.examples, ensure_ascii=False, indent=2),
        "cases": json.dumps(cs, ensure_ascii=False, indent=2),
    }


def _evolve_target(inp: dict[str, Any]) -> skills.Skill:
    return skills.current(str(inp.get("skill") or ""))


def _evolve_build(s: skills.Skill, inp: dict[str, Any], ctx: Ctx) -> tuple[str, str]:
    target = _evolve_target(inp)
    case_list = inp.get("cases")
    if case_list is None:
        case_list = skills.cases(ctx.db_url, target.id, "regression")["regression"][:20]
    return s.system_text(), s.prompt_text(**_evolve_vars(target, case_list))


def candidate_of(target: skills.Skill, reply: str) -> tuple[dict[str, Any] | None, str, list[dict[str, Any]]]:
    """从 skill-evolve 的回复取候选定义：(定义, 改动说明, 问题)；代码检查候选保留了全部变量并通过定义校验。"""
    try:
        data = ask._json_reply(reply)
    except (ValueError, json.JSONDecodeError):
        return None, "", [{"key": "skills.evolve.bad_reply"}]
    cand = target.definition()
    for k in ("system", "prompt"):
        if isinstance(data.get(k), str) and data[k].strip():
            cand[k] = data[k]
    if isinstance(data.get("templates"), dict):
        cand["templates"] = {
            **cand["templates"],
            **{k: str(v) for k, v in data["templates"].items() if k in cand["templates"]},
        }
    if isinstance(data.get("examples"), list):
        cand["examples"] = [x for x in data["examples"] if isinstance(x, dict)][: skills.MAX_EXAMPLES]
    issues = []
    olds = {
        "system": target.system,
        "prompt": target.prompt,
        **{f"templates.{k}": v for k, v in target.templates.items()},
    }
    news = {
        "system": cand["system"],
        "prompt": cand["prompt"],
        **{f"templates.{k}": v for k, v in cand["templates"].items()},
    }
    for where, old in olds.items():
        for name in sorted(skills.placeholders(old) - skills.placeholders(news.get(where, ""))):
            issues.append({"key": "skills.evolve.var_dropped", "params": {"field": where, "name": name}})
    try:
        cand, _ = skills.validate(skills.builtin(target.id), cand)
    except skills.SkillError as e:
        issues += [
            {"key": i["key"], "params": {**(i.get("params") or {}), "field": i["field"]}} for i in e.data["issues"]
        ]
    return (None if issues else cand), str(data.get("rationale") or "")[:4000], issues


def _evolve_check(s: skills.Skill, inp: dict[str, Any], reply: str, ctx: Ctx) -> dict[str, Any]:
    cand, rationale, issues = candidate_of(_evolve_target(inp), reply)
    if cand is None:
        return _result("rejected", [_item(False, i["key"], json.dumps(i.get("params") or {})) for i in issues])
    return _result("passed", [_item(True, "evolve.placeholders", rationale)], rationale=rationale)


RUNNERS: dict[str, tuple[Callable[..., tuple[str, str]], Callable[..., dict[str, Any]]]] = {
    "card-extract": (_card_build, _card_check),
    "ask-query": (_query_build, _query_check),
    "ask-answer": (_answer_build, _answer_check),
    "config-generate": (_generate_build, _generate_check),
    "script-review": (_review_build, _review_check),
    "skill-evolve": (_evolve_build, _evolve_check),
}


def build(skill: skills.Skill, inp: dict[str, Any], ctx: Ctx) -> tuple[str, str]:
    if skill.id not in RUNNERS:
        raise skills.SkillError("skills.no_runner", id=skill.id)
    try:
        return RUNNERS[skill.id][0](skill, inp, ctx)
    except (KeyError, TypeError) as e:
        raise skills.SkillError("skills.bad_input", id=skill.id, field=str(e)) from e


def prompt_for(skill: skills.Skill, inp: dict[str, Any], ctx: Ctx) -> str:
    """发给 AI 的正文（脱敏后）：案例加入示例时作为 input。"""
    return ask.sanitize_text(build(skill, inp, ctx)[1])


def run(
    ctx: Ctx,
    skill: skills.Skill,
    inp: dict[str, Any],
    mode: str = "ai",
    reply: str | None = None,
    source: str = "test",
    actor: skills.Actor | None = None,
) -> dict[str, Any]:
    """运行一次（试运行或回归）：渲染 → 调用 AI（或回放给出的回复）→ 代码校验。mode=ai 时记入调用记录（来源 test / regression / evolve）。"""
    system, prompt = build(skill, inp, ctx)
    t0 = time.monotonic()
    info: dict[str, Any] = {"model": "", "tokens_in": 0, "tokens_out": 0, "ms": 0, "calls": 0}
    if mode == "ai":
        if not ai.is_configured(ctx.settings):
            raise skills.SkillError(
                "ai.not_configured", "state", data={"status": "not_configured", "configured": False}
            )
        sess = ask._Session(ctx.settings, skill.task)
        try:
            reply = sess.call("test", system, prompt)
        except ask.AskError as e:
            skills.log_run(ctx.settings, skill, source, "error", inp, "", {}, sess.info(), actor)
            return {
                "mode": mode,
                "skill": skill.id,
                "version": skill.active,
                "sent": sess.sent,
                "reply": "",
                "check": _result("error", [_item(False, e.key, i18n.t(e.key, ctx.lang))]),
                "ai": sess.info(),
                "run_id": None,
            }
        sent = sess.sent
        info = sess.info()
    else:
        reply = reply or ""
        sent = [
            {"step": "replay", "system": ask.sanitize_text(system), "prompt": ask.sanitize_text(prompt), "reply": reply}
        ]
        info["ms"] = int((time.monotonic() - t0) * 1000)
    checked = RUNNERS[skill.id][1](skill, inp, reply, ctx)
    run_id = None
    if mode == "ai":
        det = {"summary": {"status": checked["status"], "score": checked["score"]}, "items": checked["items"][:50]}
        run_id = skills.log_run(ctx.settings, skill, source, checked["status"], inp, reply or "", det, info, actor)
    return {
        "mode": mode,
        "skill": skill.id,
        "version": skill.active,
        "sent": sent,
        "reply": reply,
        "check": checked,
        "ai": info,
        "run_id": run_id,
    }


def test(
    ctx: Ctx,
    sid: str,
    sample: int | None = None,
    case_id: int | None = None,
    inp: dict[str, Any] | None = None,
    definition: dict[str, Any] | None = None,
    version: str | None = None,
    mode: str = "ai",
    reply: str | None = None,
    actor: skills.Actor | None = None,
) -> dict[str, Any]:
    """试运行：样例 / 回归案例 / 手填的输入；可以给未保存的定义（编辑中的草稿）或指定版本。
    回放模式不调用 AI：回复取 reply，没有时取样例或案例记下的回复。"""
    s = skills.load_version(sid, version) if version else skills.current(sid)
    if definition:
        clean, _ = skills.validate(skills.builtin(sid), {**s.definition(), **definition})
        s = s.with_definition(clean, active="draft")
    canned = ""
    if case_id is not None:
        c = skills.get_case(ctx.db_url, sid, case_id)
        inp, canned = c["input"] or {}, c["reply"]
    elif sample is not None:
        b = skills.builtin(sid)
        if not 0 <= sample < len(b.samples):
            raise skills.SkillError("skills.sample_not_found", "not_found", id=sid, index=sample)
        inp, canned = b.samples[sample].get("input") or {}, b.samples[sample].get("reply") or ""
    if inp is None:
        raise skills.SkillError("skills.need_input", id=sid)
    if mode == "replay":
        return run(ctx, s, inp, "replay", reply if reply is not None else canned, "test", actor)
    return run(ctx, s, inp, "ai", None, "test", actor)


# ---------------------------------------------------------------- 进化


def _score(results: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(results)
    counts = {k: sum(1 for r in results if r["status"] == k) for k in skills.STATUSES}
    return {"score": round(sum(r["score"] for r in results) / n, 4) if n else None, "total": n, **counts}


def evolve(
    ctx: Ctx,
    sid: str,
    actor: skills.Actor | None = None,
    limit: int = 20,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """发起一次进化：AI 提出候选版本 → 回归集上新旧版本对比打分 → 存为待批准的进化（不自动发布）。"""
    prog = progress or (lambda pct, msg: None)
    if not ai.is_configured(ctx.settings):
        raise skills.SkillError("ai.not_configured", "state", data={"status": "not_configured", "configured": False})
    if sid == "skill-evolve":
        raise skills.SkillError("skills.evolve_self", "state", id=sid)
    target = skills.current(sid)
    meta = skills.require_enabled("skill-evolve")
    case_list = skills.cases(ctx.db_url, sid, "regression")["regression"][: max(1, min(limit, 100))]
    if not case_list:
        raise skills.SkillError("skills.evolve_no_cases", "state", data={"status": "no_cases"}, id=sid)
    who = actor.name if actor else ""
    prog(5, "propose")
    proposal = run(ctx, meta, {"skill": sid, "cases": case_list}, "ai", None, "evolve", actor)
    cand, rationale, issues = candidate_of(target, proposal["reply"] or "")
    if cand is None:
        return skills.add_evolution(
            ctx.db_url,
            sid,
            status="failed",
            base_version=target.active,
            rationale=rationale,
            error={"issues": issues, "reply": (proposal["reply"] or "")[:4000], "check": proposal["check"]["status"]},
            created_by=who,
        )
    new = target.with_definition(cand, active="candidate")
    rows = []
    for i, c in enumerate(case_list):
        prog(10 + int(85 * i / len(case_list)), f"case {c['id']}")
        old_r = run(ctx, target, c["input"] or {}, "ai", None, "regression", actor)
        new_r = run(ctx, new, c["input"] or {}, "ai", None, "regression", actor)
        o, n = old_r["check"], new_r["check"]
        rows.append(
            {
                "case_id": c["id"],
                "reason": c["reason"],
                "old": {
                    "status": o["status"],
                    "score": o["score"],
                    "items": o["items"][:10],
                    "reply": (old_r["reply"] or "")[:2000],
                },
                "new": {
                    "status": n["status"],
                    "score": n["score"],
                    "items": n["items"][:10],
                    "reply": (new_r["reply"] or "")[:2000],
                },
                "delta": "better" if n["score"] > o["score"] else "worse" if n["score"] < o["score"] else "same",
            }
        )
    old_s = _score([r["old"] for r in rows])
    new_s = _score([r["new"] for r in rows])
    summary = {
        "old": old_s["score"],
        "new": new_s["score"],
        "cases": len(rows),
        "better": sum(1 for r in rows if r["delta"] == "better"),
        "worse": sum(1 for r in rows if r["delta"] == "worse"),
        "same": sum(1 for r in rows if r["delta"] == "same"),
    }
    prog(98, "save")
    return skills.add_evolution(
        ctx.db_url,
        sid,
        status="pending",
        base_version=target.active,
        candidate=cand,
        rationale=rationale,
        scores={"summary": summary, "old": old_s, "new": new_s, "cases": rows},
        created_by=who,
    )
