"""增量变更与影响分析接口：POST /change、POST /change/report、POST /impact。都需要令牌。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from lmesh.api.common import E_NOT_FOUND, E_PARAM, ApiError, ok, require_token, settings_of
from lmesh.api.routes_compare import SideBody
from lmesh.api.routes_compare import _side as compare_side
from lmesh.core import analysis, change, compare, i18n, impact, kbservice, report, report_change, terms

router = APIRouter(dependencies=[Depends(require_token)])


class ChangeBody(BaseModel):
    """当前与目标：各给出 text（配置文本）、version_id（配置版本）或 device_id（设备的最新版本）之一，同一平台族。"""

    current: SideBody
    target: SideBody
    rollback: bool = Field(True, description="同时生成回滚脚本（目标 → 当前）")
    verify: bool = Field(True, description="在当前配置上模拟执行脚本，与目标按有效值对比")
    impact: bool = Field(True, description="附上变更的影响范围（受影响的业务对象）")
    style: Literal["huawei", "cisco", "nokia"] | None = Field(
        None, description="说明文字中对象的显示风格（label 字段）；不填时用配置 ui.term_style"
    )
    lang: Literal["zh-CN", "en", "pt-BR"] | None = Field(None, description="脚本说明行的语言；不填时按请求的语言")


class ChangeReportBody(ChangeBody):
    report_lang: Literal["zh-CN", "en"] = Field("zh-CN", description="报告语言（界面是 pt-BR 时用 en）")
    format: Literal["html", "md"] = Field("html", description="html：自包含单文件、可打印；md：贴进工单")
    include_ai_summary: bool = Field(
        True,
        description="包含本项目已采纳的 AI 摘要（M8-5；两边都是已导入的设备 / 版本时才有，与数据不一致时只给说明）",
    )


class ImpactBody(BaseModel):
    """配置：给出 text、version_id 或 device_id 之一；nodes 是起点节点编号（也可以写对象编号中唯一的一段）。"""

    text: str | None = None
    device_id: int | None = None
    version_id: int | None = None
    profile: str | None = None
    nodes: list[str] = Field(..., min_length=1)
    direction: Literal["up", "down", "both"] = Field("up", description="up：谁受影响；down：依赖谁；both：两个方向")


def _error(e: Exception) -> ApiError:
    kind = getattr(e, "kind", "param")
    key, fmt = getattr(e, "key", str(e)), getattr(e, "fmt", {})
    if kind == "not_found":
        return ApiError(E_NOT_FOUND, 404, key, **fmt)
    return ApiError(E_PARAM, 422, key, **fmt)


def run(request: Request, body: ChangeBody) -> dict[str, Any]:
    settings = settings_of(request)
    root = kbservice.runtime_root(settings)
    kb = analysis.load_kb(root)
    namer = terms.namer(root, kb, body.style or str(settings.get("ui.term_style")))
    lang = body.lang or i18n.from_accept_language(request.headers.get("accept-language"))
    try:
        a = compare_side(request, kb, body.current, "current")
        b = compare_side(request, kb, body.target, "target")
        result = change.change(
            a,
            b,
            kb,
            rollback=body.rollback,
            verify_scripts=body.verify,
            namer=namer,
            lang=lang,
            with_impact=body.impact,
        )
    except (compare.CompareError, change.ChangeError) as e:
        raise _error(e) from e
    # REQ-044：当前配置来自使用近似 Profile 的设备时，下发前提示核对
    from lmesh.core import model_support

    result["approx_profile"] = model_support.approx_note(settings.database_url, a.device_id)
    return result


@router.post(
    "/change",
    summary="增量变更脚本：当前 → 目标，按依赖拓扑排序、补发副作用，返回逐条说明、风险、下发脚本、回滚脚本与模拟验证",
)
def run_change(request: Request, body: ChangeBody) -> dict[str, Any]:
    return ok(request, run(request, body))


@router.post(
    "/change/report",
    summary="导出变更报告（中文 / English，HTML / Markdown），直接返回文件",
    response_class=Response,
)
def change_report(request: Request, body: ChangeReportBody) -> Response:
    result = run(request, body)
    settings = settings_of(request)
    root = kbservice.runtime_root(settings)
    namer = terms.namer(root, analysis.load_kb(root), body.style or str(settings.get("ui.term_style")))
    try:
        ai = None
        if body.include_ai_summary:
            from lmesh.core import ai_report_summary

            ai = ai_report_summary.lookup(settings.database_url, "change", body.model_dump(), body.report_lang, result)
        rep = report_change.change_report(result, body.report_lang, body.format, namer=namer, ai=ai)
    except report.ReportError as e:
        raise ApiError(E_PARAM, 422, e.key, **e.fmt) from e
    return Response(
        content=rep.content.encode("utf-8"),
        media_type=rep.media_type,
        headers={"Content-Disposition": rep.disposition()},
    )


@router.post("/impact", summary="变更影响分析：从一组节点沿依赖边求影响范围，列出受影响的对象、业务对象与路径")
def run_impact(request: Request, body: ImpactBody) -> dict[str, Any]:
    settings = settings_of(request)
    kb = analysis.load_kb(kbservice.runtime_root(settings))
    try:
        side = compare_side(
            request,
            kb,
            SideBody(text=body.text, device_id=body.device_id, version_id=body.version_id, profile=body.profile),
            "config",
        )
        result = impact.analyze(side.graph, kb, body.nodes, body.direction)
    except (compare.CompareError, impact.ImpactError) as e:
        raise _error(e) from e
    return ok(request, result)
