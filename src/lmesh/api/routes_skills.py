"""内置 AI skill 接口（REQ-033）：/ai/skills。

管理类接口只对管理员开放（普通账号 403）：列表、详情、保存、启用、版本、对比、回滚、恢复内置、试运行、统计、调用记录、回归集、进化、批准。
反馈接口 POST /ai/skills/feedback 对所有登录账号开放（AI 查询、AI 生成、配置检查项目的 AI 结果上提交点赞 / 点踩 / 更正）。
未配置 AI 时查看、编辑、版本、统计照常；试运行只能回放（mode=replay），进化返回 409 not_configured。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from lmesh.api.common import (
    E_NOT_FOUND,
    E_PARAM,
    E_STATE,
    ApiError,
    Principal,
    db_of,
    lang_of,
    ok,
    require_admin,
    require_token,
    settings_of,
)
from lmesh.core import ai, analysis, kbservice, skill_runners, skills, tasks

router = APIRouter(dependencies=[Depends(require_token)])
admin = APIRouter(dependencies=[Depends(require_admin)])


def skill_actor(request: Request) -> skills.Actor:
    """当前调用者（skill 调用记录与反馈用）：网页账号带编号，令牌调用为 api-token。"""
    p: Principal | None = getattr(request.state, "principal", None)
    if p is None:
        return skills.Actor(None, "api")
    return skills.Actor(p.user_id, p.username)


def _err(e: skills.SkillError) -> ApiError:
    if e.kind == "not_found":
        return ApiError(E_NOT_FOUND, 404, e.key, data=e.data, **e.fmt)
    if e.kind == "state":
        return ApiError(E_STATE, 409, e.key, data=e.data, **e.fmt)
    return ApiError(E_PARAM, 422, e.key, data=e.data, **e.fmt)


def _ctx(request: Request) -> skill_runners.Ctx:
    settings = settings_of(request)
    db_of(request)
    return skill_runners.Ctx(settings, lambda: analysis.load_kb(kbservice.runtime_root(settings)), lang_of(request))


def _ai_state(request: Request) -> dict[str, Any]:
    s = settings_of(request)
    on = ai.is_configured(s)
    return {"configured": on, "provider": s.get("ai.provider") or None, "status": "ready" if on else "not_configured"}


class FeedbackBody(BaseModel):
    run_id: int = Field(..., description="结果中 skill_runs[].run_id / skill_run")
    rating: Literal["up", "down"] | None = Field(None, description="点赞 / 点踩；为空且没有更正时撤销评价")
    correction: str = Field("", max_length=20000, description="更正：写出正确的内容（进入回归集）")


@router.post(
    "/ai/skills/feedback",
    summary="对一次 AI 结果的反馈：点赞 / 点踩 / 更正（所有登录账号）；点踩与更正进入回归集，校验通过且点赞的成为候选示例",
)
def post_feedback(request: Request, body: FeedbackBody) -> dict[str, Any]:
    p: Principal = request.state.principal
    try:
        r = skills.feedback(db_of(request), body.run_id, body.rating, body.correction, skill_actor(request), p.is_admin)
    except skills.SkillError as e:
        raise _err(e) from e
    return ok(request, r)


@admin.get(
    "/ai/skills", summary="skill 列表：启用状态、当前版本、近 N 天的调用数、代码校验通过率、被拦截比例、评价、回归集"
)
def list_skills(request: Request, days: int = Query(30, ge=1, le=3650)) -> dict[str, Any]:
    settings = settings_of(request)
    st = skills.stats(db_of(request), days)
    items = [{**skills.info(skills.current(i), settings), "stats": st.get(i)} for i in skills.list_ids()]
    return ok(request, {"ai": _ai_state(request), "days": days, "skills": items})


@admin.get("/ai/skills/{sid}", summary="skill 详情：生效定义、内置定义、变量说明、试运行样例、可选工具、代码校验")
def get_skill(request: Request, sid: str) -> dict[str, Any]:
    try:
        d = skills.detail(sid, settings_of(request))
        d["stats"] = skills.stats(db_of(request), 30, sid)[sid]
    except skills.SkillError as e:
        raise _err(e) from e
    return ok(request, {**d, "ai": _ai_state(request)})


class SaveBody(BaseModel):
    system: str | None = None
    prompt: str | None = None
    templates: dict[str, str] | None = None
    examples: list[dict[str, Any]] | None = None
    tools: list[str] | None = None
    output: dict[str, str] | None = None
    note: str = Field("", max_length=2000, description="保存说明（写入版本历史）")


@admin.put(
    "/ai/skills/{sid}", summary="保存为新版本并生效（校验变量、模板、示例、工具、输出格式）；内容没变时不新建版本"
)
def put_skill(request: Request, sid: str, body: SaveBody) -> dict[str, Any]:
    data = body.model_dump(exclude_none=True)
    note = data.pop("note", "")
    try:
        r = skills.save(sid, data, skill_actor(request).name, note)
        return ok(request, {**r, "skill": skills.detail(sid, settings_of(request))})
    except skills.SkillError as e:
        raise _err(e) from e


class EnabledBody(BaseModel):
    enabled: bool


@admin.put(
    "/ai/skills/{sid}/enabled", summary="启用 / 停用（停用后对应的 AI 功能返回 skill_disabled，核心功能不受影响）"
)
def put_enabled(request: Request, sid: str, body: EnabledBody) -> dict[str, Any]:
    try:
        return ok(request, skills.set_enabled(sid, body.enabled, skill_actor(request).name))
    except skills.SkillError as e:
        raise _err(e) from e


@admin.get(
    "/ai/skills/{sid}/versions", summary="版本历史：内置版本与每次保存的版本（来源、作者、时间、说明、是否生效）"
)
def get_versions(request: Request, sid: str) -> dict[str, Any]:
    try:
        return ok(request, {"skill": sid, "active": skills.state(sid)["active"], "versions": skills.versions(sid)})
    except skills.SkillError as e:
        raise _err(e) from e


@admin.get("/ai/skills/{sid}/versions/{version}", summary="某个版本的定义（builtin 或版本号）")
def get_version(request: Request, sid: str, version: str) -> dict[str, Any]:
    try:
        s = skills.load_version(sid, version)
    except skills.SkillError as e:
        raise _err(e) from e
    return ok(request, {"skill": sid, "version": s.active, "definition": s.definition()})


@admin.get("/ai/skills/{sid}/diff", summary="两个版本逐字段对比（文本字段逐行差异）")
def get_diff(request: Request, sid: str, a: str = "builtin", b: str = "current") -> dict[str, Any]:
    try:
        return ok(request, skills.diff(sid, a, b))
    except skills.SkillError as e:
        raise _err(e) from e


class RollbackBody(BaseModel):
    version: str = Field(..., description="builtin 或版本号")


@admin.post("/ai/skills/{sid}/rollback", summary="回滚：把生效版本指向任一历史版本（版本文件不删除）")
def post_rollback(request: Request, sid: str, body: RollbackBody) -> dict[str, Any]:
    try:
        return ok(request, skills.rollback(sid, body.version, skill_actor(request).name))
    except skills.SkillError as e:
        raise _err(e) from e


@admin.post("/ai/skills/{sid}/restore", summary="恢复内置版本")
def post_restore(request: Request, sid: str) -> dict[str, Any]:
    try:
        return ok(request, skills.restore(sid, skill_actor(request).name))
    except skills.SkillError as e:
        raise _err(e) from e


class TestBody(BaseModel):
    sample: int | None = Field(None, description="内置样例的序号")
    case_id: int | None = Field(None, description="回归集或候选示例的编号")
    input: dict[str, Any] | None = Field(None, description="手填的输入（与样例的 input 结构相同）")
    definition: dict[str, Any] | None = Field(
        None, description="未保存的定义（编辑中的草稿），不给时用 version 或生效版本"
    )
    version: str | None = None
    mode: Literal["ai", "replay"] = Field(
        "ai", description="ai 真实调用；replay 回放样例 / 案例记下的回复或 reply（不需要 AI）"
    )
    reply: str | None = Field(None, max_length=200000, description="回放用的回复")


@admin.post(
    "/ai/skills/{sid}/test",
    summary="试运行：渲染提示词 → 调用 AI（或回放）→ 代码校验；返回实际发送的内容（脱敏后）、回复与校验结果",
)
def post_test(request: Request, sid: str, body: TestBody) -> dict[str, Any]:
    ctx = _ctx(request)
    if body.mode == "ai" and not ai.is_configured(ctx.settings):
        raise ApiError(E_STATE, 409, "ai.not_configured", data={"status": "not_configured", "configured": False})
    try:
        r = skill_runners.test(
            ctx,
            sid,
            body.sample,
            body.case_id,
            body.input,
            body.definition,
            body.version,
            body.mode,
            body.reply,
            skill_actor(request),
        )
    except skills.SkillError as e:
        raise _err(e) from e
    return ok(request, r)


@admin.get("/ai/skills/{sid}/stats", summary="统计：近 N 天合计、每日调用（按校验结论）、按版本、最近调用")
def get_stats(request: Request, sid: str, days: int = Query(30, ge=1, le=365)) -> dict[str, Any]:
    try:
        return ok(request, skills.stats_detail(db_of(request), sid, days))
    except skills.SkillError as e:
        raise _err(e) from e


@admin.get("/ai/skills/{sid}/runs", summary="调用记录（新的在前；可按状态、来源筛选）")
def get_runs(
    request: Request,
    sid: str,
    limit: int = Query(50, ge=1, le=500),
    status: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    try:
        skills.builtin(sid)
    except skills.SkillError as e:
        raise _err(e) from e
    return ok(request, {"skill": sid, "runs": skills.runs(db_of(request), sid, limit, status, source)})


@admin.get("/ai/skills/{sid}/runs/{run_id}", summary="一次调用的详情：输入、回复（均为脱敏后）与校验明细")
def get_run(request: Request, sid: str, run_id: int) -> dict[str, Any]:
    try:
        r = skills.get_run(db_of(request), run_id)
    except skills.SkillError as e:
        raise _err(e) from e
    if r["skill"] != sid:
        raise ApiError(E_NOT_FOUND, 404, "skills.run_not_found", id=run_id)
    return ok(request, r)


@admin.get("/ai/skills/{sid}/cases", summary="回归集（失败案例自动入集）与候选示例（校验通过且点赞）")
def get_cases(request: Request, sid: str) -> dict[str, Any]:
    try:
        return ok(request, {"skill": sid, **skills.cases(db_of(request), sid)})
    except skills.SkillError as e:
        raise _err(e) from e


class CaseBody(BaseModel):
    run_id: int
    kind: Literal["regression", "candidate"] = "regression"
    note: str = Field("", max_length=2000)


@admin.post("/ai/skills/{sid}/cases", summary="把一次调用手动加入回归集或候选示例（同样的输入只留一条）")
def post_case(request: Request, sid: str, body: CaseBody) -> dict[str, Any]:
    try:
        return ok(
            request, skills.add_case(db_of(request), sid, body.run_id, body.kind, skill_actor(request), body.note)
        )
    except skills.SkillError as e:
        raise _err(e) from e


@admin.delete("/ai/skills/{sid}/cases/{cid}", summary="删除案例")
def delete_case(request: Request, sid: str, cid: int) -> dict[str, Any]:
    try:
        skills.delete_case(db_of(request), sid, cid)
    except skills.SkillError as e:
        raise _err(e) from e
    return ok(request, {"deleted": cid})


@admin.post(
    "/ai/skills/{sid}/cases/{cid}/example",
    summary="把案例加入示例（few-shot），形成新版本并生效；输出取用户更正，没有时取原回复",
)
def post_case_example(request: Request, sid: str, cid: int) -> dict[str, Any]:
    ctx = _ctx(request)
    try:
        r = skills.case_to_example(
            ctx.db_url, sid, cid, skill_actor(request).name, lambda s, inp: skill_runners.prompt_for(s, inp, ctx)
        )
    except skills.SkillError as e:
        raise _err(e) from e
    return ok(request, r)


class EvolveBody(BaseModel):
    limit: int = Field(20, ge=1, le=100, description="最多用回归集里最近的多少条案例")
    wait: bool = Field(False, description="在请求中等待完成（默认后台任务，返回 task_id）")


@admin.post(
    "/ai/skills/{sid}/evolve",
    summary="发起进化（需要配置 AI、回归集至少 1 条）：AI 提出候选版本 → 回归集新旧对比打分 → 待管理员批准（不自动上线）",
)
def post_evolve(request: Request, sid: str, body: EvolveBody) -> dict[str, Any]:
    ctx = _ctx(request)
    if not ai.is_configured(ctx.settings):
        raise ApiError(E_STATE, 409, "ai.not_configured", data={"status": "not_configured", "configured": False})
    actor = skill_actor(request)
    try:
        skills.builtin(sid)
        if sid == "skill-evolve":
            raise skills.SkillError("skills.evolve_self", "state", id=sid)
        if not skills.cases(ctx.db_url, sid, "regression")["regression"]:
            raise skills.SkillError("skills.evolve_no_cases", "state", data={"status": "no_cases"}, id=sid)
        if body.wait:
            return ok(request, {"evolution": skill_runners.evolve(ctx, sid, actor, body.limit)})
    except skills.SkillError as e:
        raise _err(e) from e
    task_id = tasks.submit(
        ctx.db_url, "skill-evolve", lambda progress: skill_runners.evolve(ctx, sid, actor, body.limit, progress)
    )
    return ok(request, {"task_id": task_id})


@admin.get("/ai/skills/{sid}/evolutions", summary="进化记录（待批准 / 已批准 / 已放弃 / 失败）")
def get_evolutions(request: Request, sid: str) -> dict[str, Any]:
    try:
        skills.builtin(sid)
    except skills.SkillError as e:
        raise _err(e) from e
    return ok(request, {"skill": sid, "evolutions": skills.evolutions(db_of(request), sid)})


@admin.get(
    "/ai/skills/{sid}/evolutions/{eid}",
    summary="一次进化的详情：候选版本、与旧版本的差异、回归集逐条对比与得分、AI 的改动说明",
)
def get_evolution(request: Request, sid: str, eid: int) -> dict[str, Any]:
    try:
        return ok(request, skills.get_evolution(db_of(request), sid, eid))
    except skills.SkillError as e:
        raise _err(e) from e


class DecideBody(BaseModel):
    note: str = Field("", max_length=2000)


@admin.post("/ai/skills/{sid}/evolutions/{eid}/approve", summary="批准发布：候选版本保存为新版本并生效")
def post_approve(request: Request, sid: str, eid: int, body: DecideBody | None = None) -> dict[str, Any]:
    try:
        r = skills.decide(db_of(request), sid, eid, True, skill_actor(request).name, body.note if body else "")
    except skills.SkillError as e:
        raise _err(e) from e
    return ok(request, r)


@admin.post("/ai/skills/{sid}/evolutions/{eid}/reject", summary="放弃这次进化（候选版本不发布）")
def post_reject(request: Request, sid: str, eid: int, body: DecideBody | None = None) -> dict[str, Any]:
    try:
        r = skills.decide(db_of(request), sid, eid, False, skill_actor(request).name, body.note if body else "")
    except skills.SkillError as e:
        raise _err(e) from e
    return ok(request, r)
