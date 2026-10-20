"""安全基线审计接口：POST /baseline、GET /baseline/rules、POST /baseline/report。都需要令牌。"""

from __future__ import annotations

from typing import Any, Literal

import networkx as nx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from lmesh.api.common import E_NOT_FOUND, E_PARAM, E_STATE, ApiError, ok, require_token, settings_of
from lmesh.api.routes_check import _device_graph
from lmesh.core import analysis, importer, kbservice, store, terms
from lmesh.core import baseline as blmod
from lmesh.core import graph as graphmod
from lmesh.core import rules as rulesmod
from lmesh.core.kb import KnowledgeBase

router = APIRouter(dependencies=[Depends(require_token)])


def _load(request: Request) -> tuple[KnowledgeBase, Any, blmod.Baseline]:
    root = kbservice.runtime_root(settings_of(request))
    kb = analysis.load_kb(root)
    try:
        return kb, root, blmod.load(kb, blmod.baseline_dir(root))
    except rulesmod.RuleError as e:
        raise ApiError(E_STATE, 409, "rules.invalid", data={"issues": e.issues}, n=len(e.issues)) from e


class ConfigItem(BaseModel):
    name: str = Field("device", max_length=200, description="设备名（结果与报告中显示）")
    text: str = Field(..., max_length=importer.MAX_BYTES, description="配置文本")
    profile: str | None = Field(None, description="知识库 Profile；不填时自动识别")


class BaselineBody(BaseModel):
    baseline: str = Field(blmod.DEFAULT_PROFILE, description="基线：basic | strict（见 GET /baseline/rules）")
    configs: list[ConfigItem] | None = Field(None, description="配置文本（可多份）")
    device_ids: list[int] | None = Field(None, description="已导入设备的编号：取最新配置版本")
    all: bool = Field(False, description="全部已导入设备的最新配置版本")


def run(request: Request, body: BaselineBody) -> tuple[dict[str, Any], KnowledgeBase, Any]:
    """POST /baseline 与基线报告共用。"""
    kb, root, bl = _load(request)
    if body.baseline not in bl.profiles:
        raise ApiError(
            E_PARAM, 422, "baseline.unknown_profile", profile=body.baseline, allowed=", ".join(bl.profiles) or "-"
        )
    if not body.configs and not body.device_ids and not body.all:
        raise ApiError(E_PARAM, 422, "baseline.need_target")
    graphs: list[nx.MultiDiGraph] = []
    ids = list(body.device_ids or [])
    if body.all:
        db = settings_of(request).database_url
        store.upgrade(db)
        ids += [d["id"] for d in importer.list_devices(db) if d["latest_version_id"] and d["id"] not in ids]
    for dev_id in ids:
        graphs.append(_device_graph(request, kb, dev_id))
    for item in body.configs or []:
        try:
            res = analysis.parse_text(item.text, kb, item.profile)
        except analysis.AnalysisError as e:
            raise ApiError(E_PARAM, 422, str(e), profile=item.profile or "") from e
        graphs.append(graphmod.build(res.parsed, kb, res.profile, item.name))
    if not graphs:
        raise ApiError(E_NOT_FOUND, 404, "baseline.no_devices")
    return blmod.audit(graphs, bl, body.baseline), kb, root


@router.post(
    "/baseline",
    summary="安全基线审计：设备 × 规则矩阵（pass / fail / na）、每台设备的不符合项（原文行号、修复建议、参考命令）与分数",
)
def baseline(request: Request, body: BaselineBody) -> dict[str, Any]:
    return ok(request, run(request, body)[0])


@router.get("/baseline/rules", summary="基线与规则：各基线（含包含关系）与规则的三语说明、修复参考命令")
def baseline_rules(request: Request, baseline: str | None = None) -> dict[str, Any]:
    _, _, bl = _load(request)
    try:
        return ok(request, blmod.list_rules(bl, baseline))
    except blmod.BaselineError as e:
        raise ApiError(E_PARAM, 422, e.key, **e.fmt) from e


class BaselineReportBody(BaselineBody):
    lang: Literal["zh-CN", "en"] = Field("zh-CN", description="报告语言（界面是 pt-BR 时用 en）")
    format: Literal["html", "md"] = Field("html", description="html：自包含单文件、可打印；md：贴进工单")
    style: Literal["huawei", "cisco", "nokia"] | None = Field(
        None, description="节点的显示风格；不填时用配置 ui.term_style"
    )
    include_ai_summary: bool = Field(
        True, description="包含本项目已采纳的 AI 摘要（M8-5；只对 device_ids 给出的设备，与数据不一致时只给说明）"
    )


@router.post(
    "/baseline/report",
    summary="导出基线报告：直接返回文件（Content-Disposition: attachment），中文 / English，HTML / Markdown",
    response_class=Response,
)
def baseline_report(request: Request, body: BaselineReportBody) -> Response:
    from lmesh.core.report_baseline import baseline_report as render

    res, kb, root = run(request, body)
    settings = settings_of(request)
    namer = terms.namer(root, kb, body.style or str(settings.get("ui.term_style")))
    ai = None
    if body.include_ai_summary:
        from lmesh.core import ai_report_summary

        ai = ai_report_summary.lookup(settings.database_url, "baseline", body.model_dump(), body.lang, res)
    rep = render(res, body.lang, body.format, namer=namer, kb_version=kb.version, ai=ai)
    return Response(
        content=rep.content.encode("utf-8"),
        media_type=rep.media_type,
        headers={"Content-Disposition": rep.disposition()},
    )
