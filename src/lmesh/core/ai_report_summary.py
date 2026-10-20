"""报告摘要（M8-5，REQ-041）：检查、基线、对比、变更（割接）报告开头的中英文摘要。

- skill report-summary（类别 text_only）：代码先算出报告的结果（与导出报告同一套 core 函数），把数字放进 numbers、
  设备 / 问题 / 差异条目编号放进 objects；AI 只写句子，数字一律写 <<键>>、对象写 [[编号]]。报告摘要比一般文字更严：
  正文里直接写的数字（不是 <<键>>）一律拒绝（SkillSpec.check，原因 number_not_from_code）。一次给出两条：kind zh-CN 与 en。
- 范围（scope_key）：report:check:<设备>、report:baseline:<基线>:<设备,…>、report:compare:<A>:<B>、report:change:<当前>:<目标>，
  A / B 写成 d<设备编号> 或 v<版本编号>。界面按同样的规则算出范围来列出与采纳建议。
- 导出（for_export）：取本项目、这个范围、这种报告语言最近一条已采纳的摘要，用导出时的报告结果重新算事实并填入数字与对象名；
  采纳时的数字与现在不同（数据变了）或引用的编号 / 键已不存在时不放进报告，改为一行说明。报告里 AI 写的部分有标记
  （HTML：紫色虚线框“AI 撰写”，代码填入的数字与对象实线加粗；Markdown：引用块加 [AI] 前缀），末尾注明 AI 撰写、
  所用 skill 与版本、接口与模型。导出参数 include_ai_summary（API）/ --ai-summary（CLI），默认包含，可以取消。
"""

from __future__ import annotations

import html
from typing import Any

from sqlalchemy import select

from lmesh.core import ai_suggest, analysis, kbservice, store
from lmesh.core.ai_suggest import Context, Env, SkillSpec, SuggestError, reason, register_skill
from lmesh.core.ai_suggest_skills import LANG_NAMES, MAX_NAMES, _short
from lmesh.core.store.models import AISuggestion, AISuggestionBatch

SKILL = "report-summary"
KINDS = ("check", "baseline", "compare", "change")
REPORT_LANGS = ("zh-CN", "en")
MAX_OBJ = 40


# ---------------------------------------------------------------- 范围


def _side_key(v: Any) -> str:
    if isinstance(v, dict):
        if v.get("version_id") is not None:
            return f"v{int(v['version_id'])}"
        if v.get("device_id") is not None:
            return f"d{int(v['device_id'])}"
    return ""


def scope_key(kind: str, params: dict[str, Any]) -> str | None:
    """报告的范围；配置文本（没有导入的设备）不支持摘要，返回 None。"""
    if kind == "check":
        return f"report:check:{int(params['device_id'])}" if params.get("device_id") is not None else None
    if kind == "baseline":
        ids = sorted({int(x) for x in params.get("device_ids") or []})
        if not ids or params.get("configs"):
            return None
        return f"report:baseline:{params.get('baseline') or 'basic'}:{','.join(map(str, ids))}"
    if kind in ("compare", "change"):
        a, b = ("a", "b") if kind == "compare" else ("current", "target")
        ka, kb_ = _side_key(params.get(a)), _side_key(params.get(b))
        return f"report:{kind}:{ka}:{kb_}" if ka and kb_ else None
    return None


# ---------------------------------------------------------------- 报告结果（与导出同一套 core 函数）


def _kb(env: Env) -> tuple[Any, Any]:
    root = kbservice.runtime_root(env.settings)
    return analysis.load_kb(root), root


def compute_result(env: Env, kind: str, params: dict[str, Any]) -> dict[str, Any]:
    from lmesh.core import baseline as blmod
    from lmesh.core import change, checks, compare, graphstore, ignores
    from lmesh.core import rules as rulesmod

    kb, root = _kb(env)
    try:
        if kind == "check":
            did = int(params["device_id"])
            ver = graphstore.latest_version(env.db, did)
            if ver is None:
                raise SuggestError("ai_suggest.device_not_found", "not_found", id=did)
            g, _, _ = graphstore.build_for_version(env.db, ver.id, kb)
            rules = rulesmod.load_cached(kb, checks.rules_dir(root))
            over = checks.load_overrides(checks.rules_dir(root))
            sev = str(params.get("severity") or "info")
            return checks.check(g, kb, rules, sev, params.get("domain"), over, ignores.index(env.db, did))
        if kind == "baseline":
            bl = blmod.load(kb, blmod.baseline_dir(root))
            prof = str(params.get("baseline") or blmod.DEFAULT_PROFILE)
            if prof not in bl.profiles:
                raise SuggestError("baseline.unknown_profile", "param", profile=prof, allowed=", ".join(bl.profiles))
            graphs = []
            for did in sorted({int(x) for x in params.get("device_ids") or []}):
                ver = graphstore.latest_version(env.db, did)
                if ver is None:
                    raise SuggestError("ai_suggest.device_not_found", "not_found", id=did)
                graphs.append(graphstore.build_for_version(env.db, ver.id, kb)[0])
            return blmod.audit(graphs, bl, prof)
        a, b = ("a", "b") if kind == "compare" else ("current", "target")

        def side(v: dict[str, Any], label: str) -> Any:
            if v.get("version_id") is not None:
                return compare.side_from_version(env.db, kb, int(v["version_id"]), None, v.get("device_id"))
            return compare.side_from_device(env.db, kb, int(v["device_id"]))

        sa, sb = side(dict(params[a]), a), side(dict(params[b]), b)
        if kind == "compare":
            return compare.compare(sa, sb, kb)
        return change.change(sa, sb, kb, rollback=True, verify_scripts=True, lang="en", with_impact=True)
    except (compare.CompareError, change.ChangeError) as e:
        raise SuggestError(getattr(e, "key", str(e)), "param", **getattr(e, "fmt", {})) from e
    except rulesmod.RuleError as e:
        raise SuggestError("rules.invalid", "state", n=len(e.issues)) from e


def report_facts(kind: str, result: dict[str, Any]) -> dict[str, Any]:
    """报告结果 → 事实（数字、对象编号、可直接出现的名称）。导出时用同一个函数重新计算并核对。"""
    from lmesh.core import rules as rulesmod

    objects: dict[str, dict[str, Any]] = {}
    numbers: dict[str, Any] = {}
    names: set[str] = set()
    rows: list[str] = []
    if kind == "check":
        s = result["summary"]
        objects["d1"] = {"type": "device", "label": str(result.get("device") or "-")}
        numbers.update({"devices": 1, "findings.total": s["total"], "findings.ignored": s.get("ignored", 0)})
        for k in rulesmod.SEVERITIES:
            numbers[f"findings.{k}"] = s["by_severity"].get(k, 0)
        active = [f for f in result["findings"] if not f.get("ignored")]
        active.sort(key=lambda f: (-rulesmod.SEVERITY_RANK.get(f["severity"], 0), f["rule"], f["node"]))
        for i, f in enumerate(active[:MAX_OBJ], 1):
            fid = f"f{i}"
            label = f"{f['rule']} @ {f['node']}"
            objects[fid] = {"type": "finding", "label": label, "rule": f["rule"], "node": f["node"]}
            names.update({f["rule"], f["node"]})
            rows.append(f"{fid} | {f['severity']} | {f['rule']} | {f['node']} | lines {f.get('lines', [])[:4]}")
    elif kind == "baseline":
        s = result["summary"]
        for k in ("devices", "rules", "score", "pass", "fail", "na", "failures"):
            if s.get(k) is not None:
                numbers[k] = s[k]
        for i, dev in enumerate(result["matrix"]["devices"], 1):
            objects[f"d{i}"] = {"type": "device", "label": str(dev)}
            names.add(str(dev))
        failing = [(rid, v["fail"]) for rid, v in s.get("by_rule", {}).items() if v.get("fail")]
        failing.sort(key=lambda x: (-x[1], x[0]))
        sev = {r["id"]: r.get("severity") for r in result.get("rules") or []}
        for i, (rid, n) in enumerate(failing[:MAX_OBJ], 1):
            objects[f"r{i}"] = {"type": "rule", "label": rid}
            numbers[f"fail.r{i}"] = n
            names.add(rid)
            rows.append(f"r{i} | {rid} | severity={sev.get(rid) or '-'} | failed on {n} device(s) (fail.r{i})")
    elif kind == "compare":
        s = result["summary"]
        objects["d1"] = {"type": "device", "label": str(result["a"].get("device") or result["a"].get("label"))}
        objects["d2"] = {"type": "device", "label": str(result["b"].get("device") or result["b"].get("label"))}
        numbers["diffs.total"] = s["total"]
        for k, v in s["by_kind"].items():
            numbers[f"diffs.{k}"] = v
        for dm, v in s.get("by_domain", {}).items():
            numbers[f"domain.{dm}"] = v["total"]
        for i, d in enumerate(result.get("diffs", [])[:MAX_OBJ], 1):
            objects[f"c{i}"] = {"type": "diff", "label": d["node"], "kind": d["kind"]}
            names.add(d["node"])
            rows.append(f"c{i} | {d['kind']} | {d['domain']} | {d['node']}")
    else:  # change
        s = result["summary"]
        objects["d1"] = {"type": "device", "label": str(result["current"].get("label"))}
        objects["d2"] = {"type": "device", "label": str(result["target"].get("label"))}
        numbers["ops"] = s["ops"]
        for k, v in s.get("by_action", {}).items():
            numbers[f"action.{k}"] = v
        for k in ("side_effects", "unsupported", "fallbacks"):
            if s.get(k) is not None:
                numbers[k] = s[k]
        names.add(str((result.get("risk") or {}).get("level") or ""))
        for i, it in enumerate(result.get("items", [])[:MAX_OBJ], 1):
            objects[f"c{i}"] = {"type": "change", "label": it.get("node"), "action": it.get("action")}
            names.add(str(it.get("node")))
            rows.append(f"c{i} | {it.get('action')} | {it.get('node')}")
    for o in objects.values():
        names.add(str(o["label"]))
    return {"objects": objects, "numbers": numbers, "lines": {}, "names": sorted(names)[:MAX_NAMES], "rows": rows}


# ---------------------------------------------------------------- skill


def _params_kind(params: dict[str, Any]) -> str:
    kind = str(params.get("kind") or "")
    if kind not in KINDS:
        raise SuggestError("ai_kb.bad_report_kind", "param", report=kind, allowed=", ".join(KINDS))
    return kind


def _prepare(env: Env, params: dict[str, Any]) -> None:
    kind = _params_kind(params)
    if scope_key(kind, params) is None:
        raise SuggestError("ai_kb.report_needs_devices", "param", report=kind)


def _build(env: Env, params: dict[str, Any]) -> Context:
    kind = _params_kind(params)
    result = compute_result(env, kind, params)
    facts = report_facts(kind, result)
    rows = facts.pop("rows")
    objs = "\n".join(f"{k} | {o['type']} | {_short(o['label'], 100)}" for k, o in facts["objects"].items())
    if kind == "change":
        facts["risk"] = str((result.get("risk") or {}).get("level") or "")
    vars_ = {
        "kind": kind,
        "facts": "\n".join(f"{k} = {v}" for k, v in facts["numbers"].items()) or "-",
        "objects": objs or "-",
        "details": "\n".join(rows) or "-",
        "risk": str((result.get("risk") or {}).get("level") or "-") if kind == "change" else "-",
        "lang": LANG_NAMES.get(env.lang, "English"),
    }
    sk = scope_key(kind, params)
    assert sk is not None
    did = params.get("device_id") if kind == "check" else None
    return Context(vars_, facts, sk, int(did) if did is not None else None)


def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def _check(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    kind = str(d.get("kind") or "")
    if kind not in REPORT_LANGS:
        return [reason("bad_report_lang", ref=kind)]
    text = str((d.get("content") or {}).get("text") or "") if isinstance(d.get("content"), dict) else ""
    for r in ai_suggest.check_text(text, facts):
        if r["code"] == "number_unverified":  # 报告摘要的数字必须由代码填入
            out.append(reason("number_not_from_code", ref=r.get("ref")))
    stripped = ai_suggest._PLACE.sub(" ", ai_suggest._MENTION.sub(" ", text))
    if kind == "zh-CN" and not _has_cjk(stripped):
        out.append(reason("wrong_lang", "warn", ref=kind))
    if kind == "en" and _has_cjk(stripped):
        out.append(reason("wrong_lang", "warn", ref=kind))
    return out


register_skill(
    SkillSpec(
        id=SKILL,
        build=_build,
        categories=("text_only",),
        default_category="text_only",
        scope="project",
        prepare=_prepare,
        check=_check,
    )
)


# ---------------------------------------------------------------- 导出


def _segments_html(text: str, facts: dict[str, Any]) -> str:
    out = []
    for seg in ai_suggest.text_segments(text, facts):
        v = html.escape(seg["v"])
        out.append(v if seg["t"] == "text" else f'<b class="cv">{v}</b>')
    return "".join(out).replace("\n", "<br>")


def _segments_md(text: str, facts: dict[str, Any]) -> str:
    out = []
    for seg in ai_suggest.text_segments(text, facts):
        v = seg["v"].replace("\n", " ")
        out.append(v if seg["t"] == "text" else f"**{v}**")
    return "".join(out)


def for_export(
    db_url: str, project_id: int | None, kind: str, params: dict[str, Any], lang: str, result: dict[str, Any]
) -> dict[str, Any] | None:
    """导出报告时取已采纳的摘要：返回 {html, md, skill, version, connection, model, stale}；没有已采纳的摘要时 None。
    数字与对象名用导出时的结果重新计算后填入；与采纳时不一致（stale）时不放正文，只给说明。"""
    sk = scope_key(kind, params)
    if sk is None:
        return None
    lang = lang if lang in REPORT_LANGS else "en"
    with store.session(db_url) as s:
        q = select(AISuggestion).where(
            AISuggestion.skill == SKILL,
            AISuggestion.scope_key == sk,
            AISuggestion.status == "adopted",
            AISuggestion.kind == lang,
        )
        if project_id is not None:
            q = q.where(AISuggestion.project_id == project_id)
            from lmesh.core import projects

            sc = projects.current()
            if sc is not None and sc.network_id is not None and sc.project_id == project_id:
                q = q.where(AISuggestion.network_id == sc.network_id)  # M9：按网络
        row = s.scalar(q.order_by(AISuggestion.decided_at.desc(), AISuggestion.id.desc()).limit(1))
        if row is None:
            return None
        b = s.get(AISuggestionBatch, row.batch_id)
        old = (b.context or {}) if b else {}
        text = str((row.content or {}).get("text") or "")
        info = {
            "skill": SKILL,
            "version": b.skill_version if b else "",
            "connection": row.connection_name or (b.connection_name if b else ""),
            "model": b.model if b else "",
            "suggestion_id": row.id,
            "mode": b.mode if b else "",
        }
    facts = report_facts(kind, result)
    facts.pop("rows", None)
    stale = any(facts["numbers"].get(k) != v for k, v in (old.get("numbers") or {}).items())
    used = ai_suggest.check_text(text, facts)
    if any(r["code"] in ("ref_not_found", "fact_not_found", "number_unverified") for r in used):
        stale = True
    if stale:
        return {**info, "stale": True, "html": "", "md": ""}
    return {**info, "stale": False, "html": _segments_html(text, facts), "md": _segments_md(text, facts)}


def export_params(kind: str, body: dict[str, Any]) -> dict[str, Any]:
    """报告接口的请求体 → 摘要范围的参数（check：device_id；baseline：device_ids、baseline；compare：a、b；change：current、target）。"""
    if kind == "check":
        return {"device_id": body.get("device_id")}
    if kind == "baseline":
        return {
            "device_ids": body.get("device_ids") or [],
            "baseline": body.get("baseline"),
            "configs": body.get("configs"),
        }
    if kind == "compare":
        return {"a": body.get("a") or {}, "b": body.get("b") or {}}
    return {"current": body.get("current") or {}, "target": body.get("target") or {}}


def lookup(db_url: str, kind: str, body: dict[str, Any], lang: str, result: dict[str, Any]) -> dict[str, Any] | None:
    """报告接口与命令行用：当前项目里这份报告已采纳的 AI 摘要（没有当前项目时不限项目）。"""
    from lmesh.core import projects

    sc = projects.current()
    return for_export(db_url, sc.project_id if sc else None, kind, export_params(kind, body), lang, result)
