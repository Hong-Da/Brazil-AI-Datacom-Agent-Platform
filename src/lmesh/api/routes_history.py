"""版本历史接口（M5-2）：时间线、两个快照的差异、对象历史、标签、回到某个快照的变更脚本、差异报告。都需要令牌。

快照引用（a、b、to、from）：配置版本编号（数字或 v<编号>）、#<序号>、latest、prev、tag:<标签>。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from lmesh.api.common import E_NOT_FOUND, E_PARAM, ApiError, lang_of, ok, require_token, settings_of
from lmesh.core import analysis, history, kbservice, report, report_history, store, terms
from lmesh.core.kb import KnowledgeBase

router = APIRouter(dependencies=[Depends(require_token)])


def _ctx(request: Request) -> tuple[str, KnowledgeBase, Any]:
    settings = settings_of(request)
    db = settings.database_url
    store.upgrade(db)
    root = kbservice.runtime_root(settings)
    return db, analysis.load_kb(root), root


def _error(e: history.HistoryError) -> ApiError:
    if e.kind == "not_found":
        return ApiError(E_NOT_FOUND, 404, e.key, **e.fmt)
    return ApiError(E_PARAM, 422, e.key, **e.fmt)


def _keep(request: Request) -> int:
    return int(settings_of(request).get("history.keep"))


@router.get(
    "/devices/{device_id}/history",
    summary="快照时间线：导入记录（重复导入合并）、知识库版本、指纹、标签、相对上一快照的变化",
)
def get_history(request: Request, device_id: int) -> dict[str, Any]:
    db, kb, _ = _ctx(request)
    try:
        return ok(request, history.timeline(db, device_id, kb, _keep(request)))
    except history.HistoryError as e:
        raise _error(e) from e


@router.get(
    "/devices/{device_id}/history/diff",
    summary="两个快照之间的变化：按对象归并的图差异、只是写法不同的变化（默认只计数）、配置原文差异（每行带节点）",
)
def get_history_diff(
    request: Request,
    device_id: int,
    a: str | None = Query(None, description="较早的快照（默认上一个）"),
    b: str | None = Query(None, description="较晚的快照（默认最新）"),
    rebuild: bool = Query(False, description="两边都按当前知识库重新解析后比较"),
    show_noneff: bool = Query(False, description="同时列出只是写法不同、有效值相同的变化"),
    domain: str | None = Query(None, description="只看一个功能域"),
    text: bool = Query(True, description="附配置原文差异"),
    context: int = Query(3, ge=0, le=100000, description="原文差异每块前后保留的相同行数（取大值时返回整份原文）"),
) -> dict[str, Any]:
    db, kb, _ = _ctx(request)
    try:
        return ok(request, history.diff(db, device_id, kb, a, b, rebuild, show_noneff, domain, text, context))
    except history.HistoryError as e:
        raise _error(e) from e


@router.get("/devices/{device_id}/history/object", summary="一个对象（规范编号）在每个快照中的取值与变化")
def get_object_history(
    request: Request,
    device_id: int,
    node: str = Query(..., description="对象的规范编号，例如 interface[GigabitEthernet0/0/0]"),
    rebuild: bool = Query(False),
) -> dict[str, Any]:
    db, kb, _ = _ctx(request)
    try:
        return ok(request, history.object_history(db, device_id, node, kb, rebuild))
    except history.HistoryError as e:
        raise _error(e) from e


class TagBody(BaseModel):
    tag: str = Field(..., min_length=1, max_length=history.TAG_MAX, description="标签文字（贴了标签的快照永久保留）")


@router.put("/devices/{device_id}/history/{version_id}/tag", summary="给快照贴标签（永久保留）")
def put_tag(request: Request, device_id: int, version_id: int, body: TagBody) -> dict[str, Any]:
    db, _, _ = _ctx(request)
    try:
        return ok(request, history.set_tag(db, device_id, version_id, body.tag))
    except history.HistoryError as e:
        raise _error(e) from e


@router.delete("/devices/{device_id}/history/{version_id}/tag", summary="去掉快照的标签")
def delete_tag(request: Request, device_id: int, version_id: int) -> dict[str, Any]:
    db, _, _ = _ctx(request)
    try:
        return ok(request, history.set_tag(db, device_id, version_id, None))
    except history.HistoryError as e:
        raise _error(e) from e


class RestoreBody(BaseModel):
    to: str = Field(..., description="要回到的快照（例如上一个 prev、#3、版本编号）")
    from_: str | None = Field(None, alias="from", description="当前快照（默认最新）")
    style: Literal["huawei", "cisco"] | None = Field(None, description="说明文字中对象的显示风格")
    lang: Literal["zh-CN", "en", "pt-BR"] | None = Field(None, description="脚本说明行的语言；不填时按请求的语言")


@router.post(
    "/devices/{device_id}/history/restore",
    summary="回到某个快照：当前（默认最新）→ 目标快照的增量变更脚本（按依赖排序），附回滚脚本与模拟验证",
)
def post_restore(request: Request, device_id: int, body: RestoreBody) -> dict[str, Any]:
    db, kb, root = _ctx(request)
    namer = terms.namer(root, kb, body.style or str(settings_of(request).get("ui.term_style")))
    try:
        return ok(
            request, history.restore(db, device_id, kb, body.to, body.from_, namer, body.lang or lang_of(request))
        )
    except history.HistoryError as e:
        raise _error(e) from e


class HistoryReportBody(BaseModel):
    a: str | None = Field(None, description="较早的快照（默认上一个）")
    b: str | None = Field(None, description="较晚的快照（默认最新）")
    rebuild: bool = False
    domain: str | None = None
    lang: Literal["zh-CN", "en"] = Field("zh-CN", description="报告语言（界面是 pt-BR 时用 en）")
    format: Literal["html", "md"] = "html"
    style: Literal["huawei", "cisco"] | None = None


@router.post(
    "/devices/{device_id}/history/report",
    summary="导出版本差异报告（中文 / English，HTML / Markdown），直接返回文件",
    response_class=Response,
)
def post_history_report(request: Request, device_id: int, body: HistoryReportBody) -> Response:
    db, kb, root = _ctx(request)
    try:
        r = history.diff(db, device_id, kb, body.a, body.b, body.rebuild, False, body.domain, True)
        namer = terms.namer(root, kb, body.style or str(settings_of(request).get("ui.term_style")))
        rep = report_history.history_report(r, body.lang, body.format, namer=namer)
    except history.HistoryError as e:
        raise _error(e) from e
    except report.ReportError as e:
        raise ApiError(E_PARAM, 422, e.key, **e.fmt) from e
    return Response(
        content=rep.content.encode("utf-8"),
        media_type=rep.media_type,
        headers={"Content-Disposition": rep.disposition()},
    )
