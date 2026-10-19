"""配置检查项目接口（REQ-031）：/check-projects 下的项目、脚本、实时检查、按依赖重排、修订记录与文本差异对比。

项目属于创建它的账号：普通账号只能看到自己的项目，管理员与 API 令牌能看到全部。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from lmesh.api.common import (
    E_NOT_FOUND,
    E_PARAM,
    ApiError,
    Principal,
    db_of,
    ok,
    require_token,
    settings_of,
)
from lmesh.api.routes_skills import skill_actor
from lmesh.core import ai, analysis, checkproj, i18n, kbservice, script_check, terms, textdiff

router = APIRouter(dependencies=[Depends(require_token)])
StyleT = Literal["huawei", "cisco", "nokia"] | None
LangT = Literal["zh-CN", "en", "pt-BR"] | None


class ProjectBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    device_id: int | None = Field(None, description="基线设备；变更脚本必须有基线")
    version_id: int | None = Field(None, description="基线版本；不填时跟随设备最新版本")
    profile: str | None = Field(None, description="没有基线设备时，完整配置用的 Profile（不填自动识别）")
    default_kind: Literal["change", "full"] = "change"
    order_check: bool = True
    ai_check: bool = False
    ai_rules: list[str] = Field(default_factory=list, description="交给 AI 参与的规则编号（规则文件中 ai: true）")


class ProjectPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    device_id: int | None = None
    version_id: int | None = None
    profile: str | None = None
    default_kind: Literal["change", "full"] | None = None
    order_check: bool | None = None
    ai_check: bool | None = None
    ai_rules: list[str] | None = None


class ScriptBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    kind: Literal["change", "full"] | None = Field(None, description="不填时用项目的默认类型")
    content: str = ""


class ScriptPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    kind: Literal["change", "full"] | None = None
    content: str | None = Field(None, description="保存内容；与最新修订不同时形成一条 manual 修订")
    position: int | None = None
    summary: dict[str, Any] | None = Field(None, description="保存时的检查摘要（界面传入，记在修订上）")


class CheckBody(BaseModel):
    content: str | None = Field(None, description="编辑器中的内容（不保存）；不填时检查保存的内容")
    kind: Literal["change", "full"] | None = None
    order: bool | None = Field(None, description="顺序核查；不填时用项目设置")
    ai: bool = Field(False, description="AI 一起校验（未配置 AI 时结果中 ai.status 为 not_configured）")
    ai_rules: list[str] | None = Field(None, description="交给 AI 的规则；不填时用项目设置")
    style: StyleT = None
    lang: LangT = None


class ReorderBody(BaseModel):
    content: str | None = None
    apply: bool = Field(False, description="true：保存为修订（重排前的内容未保存时先存一条）")
    style: StyleT = None
    lang: LangT = None


class DiffSide(BaseModel):
    """对比的一侧：revision（revision_id）/ script（script_id，可带 text 表示编辑器里未保存的内容）/
    baseline（project_id 的基线设备配置）/ text（text，kind 为 change 或 full，project_id 给出基线）。"""

    type: Literal["revision", "script", "baseline", "text"]
    revision_id: int | None = None
    script_id: int | None = None
    project_id: int | None = None
    text: str | None = None
    kind: Literal["change", "full"] | None = None
    label: str | None = None


class DiffBody(BaseModel):
    a: DiffSide
    b: DiffSide
    ignore_order: bool = Field(False, description="忽略顺序：按视图路径 + 行内容的多重集合比较")
    semantic: bool = Field(True, description="同时给出语义差异（按有效值比较）")
    style: StyleT = None


class DiffReportBody(DiffBody):
    format: Literal["html", "unified"] = "html"
    report_lang: Literal["zh-CN", "en"] = "zh-CN"


def _actor(request: Request) -> checkproj.Actor:
    p: Principal | None = getattr(request.state, "principal", None)
    if p is None or p.user_id is None:
        return checkproj.Actor(None, True, p.username if p else "api")
    return checkproj.Actor(p.user_id, p.is_admin, p.username)


def _err(e: Exception) -> ApiError:
    kind = getattr(e, "kind", "param")
    key, fmt = getattr(e, "key", str(e)), getattr(e, "fmt", {})
    if kind == "not_found":
        return ApiError(E_NOT_FOUND, 404, key, **fmt)
    return ApiError(E_PARAM, 422, key, **fmt)


def _kb(request: Request) -> Any:
    return analysis.load_kb(kbservice.runtime_root(settings_of(request)))


def _namer(request: Request, kb: Any, style: str | None) -> Any:
    settings = settings_of(request)
    return terms.namer(kbservice.runtime_root(settings), kb, style or str(settings.get("ui.term_style")))


def _lang(request: Request, lang: str | None) -> str:
    return lang or i18n.from_accept_language(request.headers.get("accept-language"))


# ---------------------------------------------------------------- 项目


@router.get("/check-projects", summary="配置检查项目列表（普通账号只看到自己的）")
def list_projects(request: Request) -> dict[str, Any]:
    return ok(request, {"projects": checkproj.list_projects(db_of(request), _actor(request))})


@router.get("/check-projects/ai-rules", summary="可交给 AI 参与校验的规则（规则文件中 ai: true）与 AI 是否已配置")
def ai_rules(request: Request) -> dict[str, Any]:
    kb = _kb(request)
    return ok(
        request,
        {"configured": ai.is_configured(settings_of(request)), "rules": script_check.ai_rules(kb)},
    )


@router.post("/check-projects", summary="新建配置检查项目")
def create_project(request: Request, body: ProjectBody) -> dict[str, Any]:
    try:
        return ok(request, checkproj.create_project(db_of(request), _actor(request), body.model_dump()))
    except checkproj.ProjectError as e:
        raise _err(e) from e


@router.post(
    "/check-projects/diff",
    summary="文本差异对比：修订 / 脚本 / 基线配置 / 文本，移动识别、行内字符标记、忽略顺序与语义差异",
)
def diff(request: Request, body: DiffBody) -> dict[str, Any]:
    kb = _kb(request)
    try:
        r = checkproj.diff(
            db_of(request),
            kb,
            _actor(request),
            body.a.model_dump(),
            body.b.model_dump(),
            body.ignore_order,
            body.semantic,
            _namer(request, kb, body.style),
        )
    except checkproj.ProjectError as e:
        raise _err(e) from e
    return ok(request, r)


@router.post(
    "/check-projects/diff/report",
    summary="下载差异：统一 diff（.diff）或中文 / 英文 HTML 报告",
    response_class=Response,
)
def diff_report(request: Request, body: DiffReportBody) -> Response:
    kb = _kb(request)
    try:
        r = checkproj.diff(
            db_of(request),
            kb,
            _actor(request),
            body.a.model_dump(),
            body.b.model_dump(),
            body.ignore_order,
            body.semantic and body.format == "html",
            _namer(request, kb, body.style),
        )
    except checkproj.ProjectError as e:
        raise _err(e) from e
    rep = textdiff.report(r, r["a"]["label"], r["b"]["label"], body.report_lang, body.format, r.get("semantic"))
    return Response(
        content=rep.content.encode("utf-8"),
        media_type=rep.media_type,
        headers={"Content-Disposition": rep.disposition()},
    )


@router.get("/check-projects/{pid}", summary="项目详情（含脚本列表）")
def get_project(request: Request, pid: int) -> dict[str, Any]:
    try:
        return ok(request, checkproj.get_project(db_of(request), _actor(request), pid))
    except checkproj.ProjectError as e:
        raise _err(e) from e


@router.put("/check-projects/{pid}", summary="修改项目（名称、基线、顺序核查、AI 一起校验与规则）")
def update_project(request: Request, pid: int, body: ProjectPatch) -> dict[str, Any]:
    try:
        data = body.model_dump(exclude_unset=True)
        return ok(request, checkproj.update_project(db_of(request), _actor(request), pid, data))
    except checkproj.ProjectError as e:
        raise _err(e) from e


@router.delete("/check-projects/{pid}", summary="删除项目（连同脚本与修订记录）")
def delete_project(request: Request, pid: int) -> dict[str, Any]:
    try:
        return ok(request, checkproj.delete_project(db_of(request), _actor(request), pid))
    except checkproj.ProjectError as e:
        raise _err(e) from e


# ---------------------------------------------------------------- 脚本


@router.post("/check-projects/{pid}/scripts", summary="新建脚本（形成第一条修订）")
def create_script(request: Request, pid: int, body: ScriptBody) -> dict[str, Any]:
    try:
        return ok(request, checkproj.create_script(db_of(request), _actor(request), pid, body.model_dump()))
    except checkproj.ProjectError as e:
        raise _err(e) from e


@router.get("/check-projects/{pid}/scripts/{sid}", summary="脚本内容")
def get_script(request: Request, pid: int, sid: int) -> dict[str, Any]:
    try:
        return ok(request, checkproj.get_script(db_of(request), _actor(request), pid, sid))
    except checkproj.ProjectError as e:
        raise _err(e) from e


@router.put("/check-projects/{pid}/scripts/{sid}", summary="改名 / 改类型 / 保存内容（内容变化时形成修订）")
def update_script(request: Request, pid: int, sid: int, body: ScriptPatch) -> dict[str, Any]:
    try:
        data = body.model_dump(exclude_unset=True)
        return ok(request, checkproj.update_script(db_of(request), _actor(request), pid, sid, data))
    except checkproj.ProjectError as e:
        raise _err(e) from e


@router.delete("/check-projects/{pid}/scripts/{sid}", summary="删除脚本")
def delete_script(request: Request, pid: int, sid: int) -> dict[str, Any]:
    try:
        return ok(request, checkproj.delete_script(db_of(request), _actor(request), pid, sid))
    except checkproj.ProjectError as e:
        raise _err(e) from e


@router.post(
    "/check-projects/{pid}/scripts/{sid}/check",
    summary="实时检查：按行给出问题（解析、视图、取消、覆盖、副作用、顺序、冲突、规则、AI）与模拟执行后的结果",
)
def check(request: Request, pid: int, sid: int, body: CheckBody) -> dict[str, Any]:
    kb = _kb(request)
    actor = _actor(request)
    db = db_of(request)
    ai_cfg = None
    try:
        if body.ai:
            rules = body.ai_rules if body.ai_rules is not None else checkproj.settings_of(db, actor, pid)["ai_rules"]
            ai_cfg = {"settings": settings_of(request), "rules": rules, "actor": skill_actor(request)}
        r = checkproj.check(
            db,
            kb,
            actor,
            pid,
            sid,
            body.content,
            body.kind,
            body.order,
            ai_cfg,
            _namer(request, kb, body.style),
            _lang(request, body.lang),
        )
    except checkproj.ProjectError as e:
        raise _err(e) from e
    return ok(request, r)


@router.post(
    "/check-projects/{pid}/scripts/{sid}/reorder",
    summary="按依赖重排：新脚本、每条命令的移动与原因、重排前后的顺序错误；apply=true 时保存为修订",
)
def reorder(request: Request, pid: int, sid: int, body: ReorderBody) -> dict[str, Any]:
    kb = _kb(request)
    try:
        r = checkproj.reorder(
            db_of(request),
            kb,
            _actor(request),
            pid,
            sid,
            body.content,
            body.apply,
            _namer(request, kb, body.style),
            _lang(request, body.lang),
        )
    except checkproj.ProjectError as e:
        raise _err(e) from e
    return ok(request, r)


@router.get("/check-projects/{pid}/scripts/{sid}/revisions", summary="修订记录（新的在前，不含内容）")
def revisions(request: Request, pid: int, sid: int) -> dict[str, Any]:
    try:
        return ok(request, {"revisions": checkproj.revisions(db_of(request), _actor(request), pid, sid)})
    except checkproj.ProjectError as e:
        raise _err(e) from e


@router.get("/check-projects/{pid}/scripts/{sid}/revisions/{rid}", summary="一条修订（含内容）")
def get_revision(request: Request, pid: int, sid: int, rid: int) -> dict[str, Any]:
    try:
        return ok(request, checkproj.get_revision(db_of(request), _actor(request), pid, sid, rid))
    except checkproj.ProjectError as e:
        raise _err(e) from e


@router.post(
    "/check-projects/{pid}/scripts/{sid}/revisions/{rid}/restore", summary="恢复到某个修订（形成一条 restore 修订）"
)
def restore(request: Request, pid: int, sid: int, rid: int) -> dict[str, Any]:
    try:
        return ok(request, checkproj.restore(db_of(request), _actor(request), pid, sid, rid))
    except checkproj.ProjectError as e:
        raise _err(e) from e
