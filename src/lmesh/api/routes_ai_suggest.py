"""AI 建议（M8-2，REQ-041）：只挂在项目路径 /api/v1/projects/{project}/… 下。

权限沿用 M6 的项目角色（access.py）：查看（GET）所有成员；运行、采纳、忽略、撤销、取消需要可编辑（属主、可编辑成员、
管理员）；知识库类建议（kb_review）的采纳与撤销另外要求维护员或管理员。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from lmesh.api.common import (
    E_EXTERNAL,
    E_FORBIDDEN,
    E_NOT_FOUND,
    E_PARAM,
    E_STATE,
    ApiError,
    db_of,
    lang_of,
    ok,
    principal_of,
    require_token,
    settings_of,
)
from lmesh.core import ai_suggest, ai_suggest_analysis, analysis, kbservice, projects

router = APIRouter(dependencies=[Depends(require_token)])
_KIND = {
    "param": (E_PARAM, 422),
    "not_found": (E_NOT_FOUND, 404),
    "state": (E_STATE, 409),
    "forbidden": (E_FORBIDDEN, 403),
    "external": (E_EXTERNAL, 502),
}


def _err(e: ai_suggest.SuggestError) -> ApiError:
    code, status = _KIND.get(e.kind, (E_PARAM, 422))
    return ApiError(code, status, e.key, data=e.data, **e.fmt)


def _env(request: Request) -> ai_suggest.Env:
    settings = settings_of(request)
    db_of(request)
    p = principal_of(request)
    scope: projects.Scope = request.state.scope
    return ai_suggest.Env(
        settings,
        lambda: analysis.load_kb(kbservice.runtime_root(settings)),
        project_id=scope.project_id,
        user_id=p.user_id,
        actor=p.username,
        kb_editor=p.is_kb_editor,
        admin=p.is_admin,
        lang=lang_of(request),
    )


@router.get(
    "/ai/suggestions/skills",
    summary="可生成建议的 skill（名称、分组、类别、是否启用）与 AI 是否可用；不可用时 ai.reason 给出原因",
)
def suggest_skills(request: Request) -> dict[str, Any]:
    return ok(request, ai_suggest.skill_list(settings_of(request)))


class RunBody(BaseModel):
    skill: str = Field(..., max_length=60, description="skill 编号，例如 device-summary、topology-roles")
    device_id: int | None = Field(None, description="设备（作用于单台设备的 skill 必填）")
    params: dict[str, Any] = Field(default_factory=dict, description="skill 的其他参数，例如 device_ids")
    wait: bool = Field(False, description="true 时同步运行并直接返回批次（测试、脚本用）")


@router.post(
    "/ai/suggestions/run",
    summary="运行一个 skill 生成建议（后台任务，返回 task_id 与 batch_id；GET /tasks/{id} 看进度）；AI 不可用时 409",
)
def suggest_run(request: Request, body: RunBody) -> dict[str, Any]:
    env = _env(request)
    params = dict(body.params)
    if body.device_id is not None:
        params["device_id"] = body.device_id
    try:
        return ok(request, ai_suggest.run(env, body.skill, params, background=not body.wait))
    except ai_suggest.SuggestError as e:
        raise _err(e) from e


@router.post(
    "/ai/suggestions/estimate",
    summary="运行前估计发给 AI 的量（tokens；超过 50k 时 warn 为 true），不调用 AI",
)
def suggest_estimate(request: Request, body: RunBody) -> dict[str, Any]:
    params = dict(body.params)
    if body.device_id is not None:
        params["device_id"] = body.device_id
    try:
        return ok(request, ai_suggest.estimate(_env(request), body.skill, params))
    except ai_suggest.SuggestError as e:
        raise _err(e) from e


@router.get("/ai/suggestions/batches/{batch_id}", summary="一次运行：状态、计数、AI 接口与调用记录编号、失败原因")
def suggest_batch(request: Request, batch_id: int) -> dict[str, Any]:
    try:
        return ok(request, ai_suggest.get_batch(_env(request), batch_id))
    except ai_suggest.SuggestError as e:
        raise _err(e) from e


@router.post(
    "/ai/suggestions/batches/{batch_id}/cancel",
    summary="取消运行：AI 的回复到达后丢弃，不生成建议（已发出的调用照常计入用量）",
)
def suggest_cancel(request: Request, batch_id: int) -> dict[str, Any]:
    try:
        return ok(request, ai_suggest.cancel(_env(request), batch_id))
    except ai_suggest.SuggestError as e:
        raise _err(e) from e


@router.get("/ai/suggestions/adoptions", summary="采纳记录：已采纳与已撤销的建议（新的在前），含采纳做了什么与撤销信息")
def suggest_adoptions(request: Request, limit: int = Query(200, ge=1, le=1000)) -> dict[str, Any]:
    return ok(request, {"items": ai_suggest.adoptions(_env(request), limit)})


@router.get("/view-annotations", summary="项目级视图标注（设备角色、分组、标签、层次）：手工或采纳的 AI 建议")
def view_annotations(request: Request, target_type: str | None = None) -> dict[str, Any]:
    scope: projects.Scope = request.state.scope
    return ok(request, {"items": ai_suggest.list_annotations(db_of(request), scope.project_id, target_type)})


class AnnotationBody(BaseModel):
    target_type: Literal["device"] = Field("device", description="目标类型（目前只有设备）")
    target: str = Field(..., max_length=200, description="设备编号")
    key: Literal["role", "group", "label", "layer"] = Field(..., description="角色、分组、标签或层次")
    value: str | int | None = Field(
        None, description="取值：role 为 core / aggregation / access / pe / p / ce；layer 为 0～9；null 表示清除"
    )


@router.put(
    "/view-annotations",
    summary="手工设置或清除设备的视图标注（来源 user，优先于 AI 建议）；需要可编辑",
)
def put_view_annotation(request: Request, body: AnnotationBody) -> dict[str, Any]:
    try:
        item = ai_suggest_analysis.set_annotation(_env(request), body.target_type, body.target, body.key, body.value)
    except ai_suggest.SuggestError as e:
        raise _err(e) from e
    return ok(request, {"item": item})


@router.get(
    "/ai/suggestions/coverage",
    summary="覆盖核对（代码计算）：范围内最近一次运行的建议引用到的条目，与没有被任何建议解释到的条目（变化解读用 c 编号）",
)
def suggest_coverage(
    request: Request,
    skill: str = Query("diff-explain", max_length=60),
    scope: str = Query(..., max_length=200, description="范围，例如 compare:3:5、history:3:5"),
    prefix: str = Query("c", pattern="^[a-z]$"),
) -> dict[str, Any]:
    return ok(request, ai_suggest_analysis.coverage(_env(request), skill, scope, prefix))


@router.get(
    "/devices/{device_id}/handover",
    summary="设备交接文档（中文 / English，HTML / Markdown）：设备信息、视图标注、对象统计与最近采纳的 AI 设备摘要，直接返回文件",
    response_class=Response,
)
def device_handover(
    request: Request,
    device_id: int,
    lang: Literal["zh-CN", "en"] = Query("zh-CN", description="文档语言（界面是 pt-BR 时用 en）"),
    format: Literal["html", "md"] = Query("html"),
) -> Response:
    try:
        rep = ai_suggest_analysis.handover(_env(request), device_id, lang, format)
    except ai_suggest.SuggestError as e:
        raise _err(e) from e
    return Response(
        content=rep.content.encode("utf-8"),
        media_type=rep.media_type,
        headers={"Content-Disposition": rep.disposition()},
    )


@router.get("/ai/suggestions", summary="建议列表：按 skill、状态、校验结果、类别、设备、批次、范围过滤（新的在前）")
def suggest_list(
    request: Request,
    skill: str | None = None,
    status: Literal["pending", "adopted", "dismissed", "reverted"] | None = None,
    check: Literal["pass", "warn", "reject"] | None = None,
    category: str | None = None,
    device_id: int | None = None,
    batch_id: int | None = None,
    scope: str | None = Query(None, description="范围，例如 device:3、topology"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    data = ai_suggest.list_suggestions(
        _env(request), skill, status, check, category, device_id, batch_id, scope, limit, offset
    )
    return ok(request, data)


class AdoptBody(BaseModel):
    content: dict[str, Any] | None = Field(None, description="编辑后的内容（给出时先重新校验，被拒绝则 409）")
    title: str | None = Field(None, max_length=400)
    refs: list[dict[str, Any]] | None = Field(None, description="编辑后的引用（不给时沿用原来的）")
    note: str = Field("", max_length=2000)


class NoteBody(BaseModel):
    note: str = Field("", max_length=2000)


class BatchAdoptBody(BaseModel):
    category: str = Field(..., description="类别：refs_exist / script_valid / kb_review / view_hint / text_only")
    skill: str | None = None
    batch_id: int | None = None
    ids: list[int] | None = Field(None, description="只在这些建议里选")


@router.post(
    "/ai/suggestions/adopt-batch",
    summary="按类别批量采纳：只采纳校验通过（pass）且待处理的，warn / reject 的跳过",
)
def suggest_adopt_batch(request: Request, body: BatchAdoptBody) -> dict[str, Any]:
    try:
        return ok(request, ai_suggest.adopt_batch(_env(request), body.category, body.skill, body.batch_id, body.ids))
    except ai_suggest.SuggestError as e:
        raise _err(e) from e


@router.get("/ai/suggestions/{sid}", summary="一条建议：内容、依据与引用（可跳转）、代码校验结果、状态与采纳信息")
def suggest_get(request: Request, sid: int) -> dict[str, Any]:
    try:
        return ok(request, ai_suggest.get(_env(request), sid))
    except ai_suggest.SuggestError as e:
        raise _err(e) from e


@router.post(
    "/ai/suggestions/{sid}/adopt",
    summary="采纳（可带编辑后的内容，先重新校验）；被拒绝的不能采纳（409，data.check）；知识库类只限维护员与管理员",
)
def suggest_adopt(request: Request, sid: int, body: AdoptBody) -> dict[str, Any]:
    try:
        return ok(request, ai_suggest.adopt(_env(request), sid, body.content, body.title, body.note, body.refs))
    except ai_suggest.SuggestError as e:
        raise _err(e) from e


@router.post("/ai/suggestions/{sid}/dismiss", summary="忽略一条待处理的建议")
def suggest_dismiss(request: Request, sid: int, body: NoteBody) -> dict[str, Any]:
    try:
        return ok(request, ai_suggest.dismiss(_env(request), sid, body.note))
    except ai_suggest.SuggestError as e:
        raise _err(e) from e


@router.post("/ai/suggestions/{sid}/restore", summary="把忽略的建议恢复为待处理")
def suggest_restore(request: Request, sid: int) -> dict[str, Any]:
    try:
        return ok(request, ai_suggest.restore(_env(request), sid))
    except ai_suggest.SuggestError as e:
        raise _err(e) from e


@router.post(
    "/ai/suggestions/{sid}/revert",
    summary="撤销已采纳的建议：视图标注恢复原值、审核项撤回、未改动的脚本删除；之后被改动过时 409",
)
def suggest_revert(request: Request, sid: int, body: NoteBody) -> dict[str, Any]:
    try:
        return ok(request, ai_suggest.revert(_env(request), sid, body.note))
    except ai_suggest.SuggestError as e:
        raise _err(e) from e
