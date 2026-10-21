"""AI 查询会话（REQ-052）、附件（REQ-053）与下载（REQ-054）接口。都在项目下（也挂网络路径），需要令牌。

- 会话只有本人可见；分享后同项目成员可以只读查看（GET 会话、下载报告与结果表）。
- 追问 POST …/turns：AI 能看到本会话前几轮的问题与图查询（脱敏后）；附件里的配置作为临时设备加入范围，
  文档文字作参考资料，图片需要 ai.ask_images 开启并在请求里 confirm_images=true。
- 改问重答 POST …/turns/{tid}/versions：追加版本并切到它；PUT …/turns/{tid} 切换显示的版本。
- 下载：GET …/report（会话报告 HTML / Markdown，中文 / English）、GET …/turns/{tid}/table（CSV / Excel）；
  POST …/ai-report：AI 写 Markdown 报告，代码核对数字与对象名（需要 AI）。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from lmesh.api.common import (
    E_FORBIDDEN,
    E_NOT_FOUND,
    E_PARAM,
    E_STATE,
    ApiError,
    lang_of,
    ok,
    require_token,
    settings_of,
)
from lmesh.api.routes_ask import _ask_error, _kb
from lmesh.api.routes_skills import skill_actor
from lmesh.core import ai, ask, ask_report, ask_sessions, report, store
from lmesh.core.report import Report

router = APIRouter(dependencies=[Depends(require_token)])

_KINDS = {
    "param": (E_PARAM, 422),
    "not_found": (E_NOT_FOUND, 404),
    "state": (E_STATE, 409),
    "forbidden": (E_FORBIDDEN, 403),
}


def _err(e: ask_sessions.SessionError) -> ApiError:
    code, status = _KINDS.get(e.kind, (E_PARAM, 422))
    return ApiError(code, status, e.key, **e.fmt)


def _db(request: Request) -> str:
    db = settings_of(request).database_url
    store.upgrade(db)
    return db


class SessionBody(BaseModel):
    title: str = Field("", max_length=200, description="标题；不填时用第一个问题")
    devices: list[str] | None = Field(None, description="范围（设备名）；不给时为当前网络全部可查询设备")


class SessionPatch(BaseModel):
    title: str | None = Field(None, max_length=200)
    archived: bool | None = Field(None, description="归档 / 恢复")
    shared: bool | None = Field(None, description="分享给项目成员只读查看 / 取消分享")
    devices: list[str] | None = Field(None, description="更改范围（之后的提问生效；网络取当前网络）")
    clear_devices: bool = Field(False, description="范围改回网络全部可查询设备")


class TurnBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    lang: Literal["zh-CN", "en", "pt-BR"] | None = Field(None, description="回答语言；不填时按请求的语言")
    confirm_images: bool = Field(False, description="会话里有图片附件时必须为 true（图片不经脱敏原样发给 AI）")


class CurrentBody(BaseModel):
    current: int = Field(..., ge=0, description="要显示的版本下标（从 0 开始）")


class AiReportBody(BaseModel):
    lang: Literal["zh-CN", "en", "pt-BR"] | None = Field(None, description="报告语言；pt-BR 时用英文")


@router.get(
    "/ask/sessions",
    summary="我的 AI 查询会话（which=active 进行中 / archived 已归档 / shared 别人分享给我的），最近更新的在前",
)
def list_sessions(
    request: Request,
    which: Literal["active", "archived", "shared"] = Query("active"),
    q: str = Query("", max_length=200, description="按标题搜索"),
) -> dict[str, Any]:
    db = _db(request)
    try:
        return ok(request, {"sessions": ask_sessions.list_sessions(db, which, q), "counts": ask_sessions.counts(db)})
    except ask_sessions.SessionError as e:
        raise _err(e) from e


@router.post("/ask/sessions", summary="新建会话：记下当前网络与范围")
def create_session(request: Request, body: SessionBody) -> dict[str, Any]:
    try:
        return ok(request, ask_sessions.create(_db(request), body.title, body.devices))
    except ask_sessions.SessionError as e:
        raise _err(e) from e


@router.get(
    "/ask/sessions/{sid}", summary="会话全文：各轮的版本（问题与结果）、附件（不含内容）；别人分享的会话 mine 为 false"
)
def get_session(request: Request, sid: int) -> dict[str, Any]:
    try:
        return ok(request, ask_sessions.get(_db(request), sid))
    except ask_sessions.SessionError as e:
        raise _err(e) from e


@router.patch("/ask/sessions/{sid}", summary="重命名、归档 / 恢复、分享 / 取消分享、更改范围（只有本人）")
def patch_session(request: Request, sid: int, body: SessionPatch) -> dict[str, Any]:
    changes: dict[str, Any] = body.model_dump(exclude_none=True, exclude={"clear_devices"})
    if body.clear_devices:
        changes["devices"] = None
    try:
        return ok(request, ask_sessions.update(_db(request), sid, changes))
    except ask_sessions.SessionError as e:
        raise _err(e) from e


@router.delete("/ask/sessions/{sid}", summary="删除会话（连同各轮与附件；只有本人）")
def delete_session(request: Request, sid: int) -> dict[str, Any]:
    try:
        ask_sessions.delete(_db(request), sid)
    except ask_sessions.SessionError as e:
        raise _err(e) from e
    return ok(request, {"deleted": sid})


def _run(
    request: Request, sid: int, question: str, lang: str | None, confirm: bool, before: int | None
) -> tuple[dict[str, Any], int, list[int]]:
    """执行一次提问（core/ask_sessions.run）：范围、前几轮上下文、附件、确认过的图片。"""
    settings = settings_of(request)
    if not ask.status(settings)["configured"]:
        raise ApiError(E_STATE, 409, "ai.not_configured", data=ai.not_configured_data(settings))
    kb, _ = _kb(request)
    try:
        return ask_sessions.run(
            _db(request), sid, question, kb, settings, lang or lang_of(request), skill_actor(request), confirm, before
        )
    except ask_sessions.SessionError as e:
        err = _err(e)
        err.data = getattr(e, "data", None)
        raise err from e
    except ask.AskError as e:
        raise _ask_error(e) from e


@router.post(
    "/ask/sessions/{sid}/turns",
    summary="在会话里提问 / 追问（带前几轮上下文与附件；需要 AI）：返回新的一轮（含结果）",
)
def post_turn(request: Request, sid: int, body: TurnBody) -> dict[str, Any]:
    result, ctx, atts = _run(request, sid, body.question, body.lang, body.confirm_images, None)
    try:
        return ok(request, ask_sessions.add_turn(_db(request), sid, body.question, result, ctx, atts))
    except ask_sessions.SessionError as e:
        raise _err(e) from e


@router.post(
    "/ask/sessions/{sid}/turns/{tid}/versions",
    summary="改问题重新回答：追加一个版本并切到它（上下文为这一轮之前的各轮；之后的轮次不受影响）",
)
def post_version(request: Request, sid: int, tid: int, body: TurnBody) -> dict[str, Any]:
    try:
        pos = ask_sessions.turn_position(_db(request), sid, tid)
    except ask_sessions.SessionError as e:
        raise _err(e) from e
    result, ctx, atts = _run(request, sid, body.question, body.lang, body.confirm_images, pos)
    try:
        return ok(request, ask_sessions.add_version(_db(request), sid, tid, body.question, result, ctx, atts))
    except ask_sessions.SessionError as e:
        raise _err(e) from e


@router.put("/ask/sessions/{sid}/turns/{tid}", summary="切换这一轮显示的版本（之后追问的上下文用它）")
def put_turn(request: Request, sid: int, tid: int, body: CurrentBody) -> dict[str, Any]:
    try:
        return ok(request, ask_sessions.set_current(_db(request), sid, tid, body.current))
    except ask_sessions.SessionError as e:
        raise _err(e) from e


@router.post(
    "/ask/sessions/{sid}/attachments",
    summary="添加附件（配置文件作为临时设备、文档提取文字并脱敏、图片需要 ai.ask_images）；每会话最多 10 个、单个 10 MB",
)
async def post_attachments(request: Request, sid: int, files: list[UploadFile] = File(...)) -> dict[str, Any]:
    settings = settings_of(request)
    data = [(f.filename or "file", await f.read()) for f in files]
    kb, _ = _kb(request)
    try:
        added = ask_sessions.add_attachments(_db(request), sid, data, bool(settings.get("ai.ask_images")), kb)
    except ask_sessions.SessionError as e:
        raise _err(e) from e
    return ok(request, {"attachments": added})


@router.delete("/ask/sessions/{sid}/attachments/{aid}", summary="删除附件（只有本人）")
def delete_attachment(request: Request, sid: int, aid: int) -> dict[str, Any]:
    try:
        ask_sessions.delete_attachment(_db(request), sid, aid)
    except ask_sessions.SessionError as e:
        raise _err(e) from e
    return ok(request, {"deleted": aid})


def _file(rep: Report) -> Response:
    return Response(rep.content, media_type=rep.media_type, headers={"Content-Disposition": rep.disposition()})


@router.get(
    "/ask/sessions/{sid}/report",
    summary="下载会话报告：HTML（自包含、可打印为 PDF）或 Markdown，中文 / English（pt-BR 用英文）",
)
def get_report(
    request: Request,
    sid: int,
    lang: Literal["zh-CN", "en", "pt-BR"] | None = Query(None),
    format: Literal["html", "md"] = Query("html"),
) -> Response:
    try:
        sess = ask_sessions.get(_db(request), sid)
    except ask_sessions.SessionError as e:
        raise _err(e) from e
    rep = ask_report.session_report(sess, report.report_lang(lang or lang_of(request)), format)
    return _file(rep)


@router.get(
    "/ask/sessions/{sid}/turns/{tid}/table", summary="下载这一轮（当前版本）的结果表：CSV（UTF-8 带 BOM）或 Excel"
)
def get_table(request: Request, sid: int, tid: int, format: Literal["csv", "xlsx"] = Query("csv")) -> Response:
    try:
        sess = ask_sessions.get(_db(request), sid)
    except ask_sessions.SessionError as e:
        raise _err(e) from e
    turn = next((t for t in sess["turn_list"] if t["id"] == tid), None)
    if turn is None:
        raise ApiError(E_NOT_FOUND, 404, "ask_session.turn_not_found", id=tid)
    res = ask_report.current_version(turn).get("result") or {}
    n = next(i for i, t in enumerate(sess["turn_list"], 1) if t["id"] == tid)
    name = f"ask-session-{sid}-turn-{n}"
    if format == "xlsx":
        body = ask_report.table_xlsx(res, f"turn {n}")
        rep = Report(f"{name}.xlsx", "", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        body = ask_report.table_csv(res)
        rep = Report(f"{name}.csv", "", "text/csv; charset=utf-8")
    return Response(body, media_type=rep.media_type, headers={"Content-Disposition": rep.disposition()})


@router.post(
    "/ask/sessions/{sid}/ai-report",
    summary="AI 写会话报告（Markdown；需要 AI）：数字与对象名由代码从会话结果填入并核对，blocks 标出未经核对的句子",
)
def post_ai_report(request: Request, sid: int, body: AiReportBody) -> dict[str, Any]:
    settings = settings_of(request)
    if not ask.status(settings)["configured"]:
        raise ApiError(E_STATE, 409, "ai.not_configured", data=ai.not_configured_data(settings))
    try:
        sess = ask_sessions.get(_db(request), sid)
    except ask_sessions.SessionError as e:
        raise _err(e) from e
    try:
        out = ask_report.ai_report(settings, sess, body.lang or lang_of(request), actor=skill_actor(request))
    except ask.AskError as e:
        raise _ask_error(e) from e
    out["filename"] = f"ask-session-{sid}-ai-report.{out['lang']}.md"
    return ok(request, out)
