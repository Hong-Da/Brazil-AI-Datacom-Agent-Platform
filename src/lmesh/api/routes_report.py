"""报告导出：POST /reports 直接返回文件（对比报告、检查报告；中文 / English；HTML / Markdown）。需要令牌。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from lmesh.api import routes_check, routes_compare
from lmesh.api.common import E_PARAM, ApiError, require_token, settings_of
from lmesh.core import graphstore, report

router = APIRouter(dependencies=[Depends(require_token)])


class ReportBody(BaseModel):
    kind: Literal["compare", "check"]
    lang: Literal["zh-CN", "en"] = Field("zh-CN", description="报告语言（界面是 pt-BR 时用 en）")
    format: Literal["html", "md"] = Field("html", description="html：自包含单文件、可打印；md：贴进工单")
    compare: routes_compare.CompareBody | None = Field(None, description="kind=compare 时必填，与 POST /compare 相同")
    check: routes_check.CheckBody | None = Field(None, description="kind=check 时必填，与 POST /check 相同")


@router.post(
    "/reports",
    summary="导出报告：对比报告或检查报告，直接返回文件（Content-Disposition: attachment）",
    response_class=Response,
)
def export_report(request: Request, body: ReportBody) -> Response:
    db = settings_of(request).database_url
    if body.kind == "compare":
        if body.compare is None:
            raise ApiError(E_PARAM, 422, "report.need_body", kind="compare")
        result, a, b = routes_compare.run(request, body.compare)
        meta = {k: report.version_meta(db, s.version_id) for k, s in (("a", a), ("b", b))}
        rep = report.compare_report(result, body.lang, body.format, meta)
    else:
        if body.check is None:
            raise ApiError(E_PARAM, 422, "report.need_body", kind="check")
        res, g, kb = routes_check.run_check(request, body.check)
        meta = {}
        if body.check.device_id is not None:
            ver = graphstore.latest_version(db, body.check.device_id)
            meta = report.version_meta(db, ver.id if ver else None)
        rep = report.build_check_report(g, kb, res, body.lang, body.format, meta)
    return Response(
        content=rep.content.encode("utf-8"),
        media_type=rep.media_type,
        headers={"Content-Disposition": rep.disposition()},
    )
