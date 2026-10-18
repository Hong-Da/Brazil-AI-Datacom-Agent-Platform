"""解析、配置图、渲染、往返、未识别行接口。都需要令牌。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from lmesh.api.common import E_NOT_FOUND, E_PARAM, ApiError, ok, require_token, settings_of
from lmesh.core import analysis, graphstore, importer, kbservice, roundtrip, store, tasks
from lmesh.core import graph as graphmod
from lmesh.core.renderer import render_roundtrip

router = APIRouter(dependencies=[Depends(require_token)])


def _kb(request: Request):  # type: ignore[no-untyped-def]
    return analysis.load_kb(kbservice.runtime_root(settings_of(request)))


def _db(request: Request) -> str:
    url = settings_of(request).database_url
    store.upgrade(url)
    return url


class TextBody(BaseModel):
    text: str = Field(..., max_length=importer.MAX_BYTES)
    profile: str | None = None


def _parse(request: Request, body: TextBody):  # type: ignore[no-untyped-def]
    kb = _kb(request)
    try:
        return analysis.parse_text(body.text, kb, body.profile), kb
    except analysis.AnalysisError as e:
        raise ApiError(E_PARAM, 422, str(e), profile=body.profile or "") from e


@router.post("/parse", summary="解析为带行号的结构化 JSON")
def parse(request: Request, body: TextBody) -> dict[str, Any]:
    res, _ = _parse(request, body)
    return ok(request, res.as_dict())


@router.post("/render", summary="解析建图后渲染回配置文本（往返模式）")
def render(request: Request, body: TextBody) -> dict[str, Any]:
    res, kb = _parse(request, body)
    g = graphmod.build(res.parsed, kb, res.profile)
    return ok(request, {"profile": res.profile, "text": render_roundtrip(g, kb)})


class RoundtripBody(BaseModel):
    text: str | None = Field(None, max_length=importer.MAX_BYTES)
    profile: str | None = None
    samples: bool = False


@router.post("/roundtrip", summary="往返测试：给出 text 时同步返回；samples=true 时作为后台任务跑全部样本")
def run_roundtrip(request: Request, body: RoundtripBody) -> dict[str, Any]:
    kb = _kb(request)
    if body.samples:
        root = kbservice.runtime_root(settings_of(request))
        from lmesh.core import workbench

        task_id = tasks.submit(_db(request), "roundtrip", lambda progress: workbench.run_regression(root))
        return ok(request, {"task_id": task_id})
    if not body.text:
        raise ApiError(E_PARAM, 422)
    try:
        return ok(request, roundtrip.run(body.text, kb, body.profile))
    except analysis.AnalysisError as e:
        raise ApiError(E_PARAM, 422, str(e), profile=body.profile or "") from e


@router.get("/devices/{device_id}/graph", summary="设备配置图（最新配置版本，按当前知识库建图）")
def device_graph(
    request: Request,
    device_id: int,
    domain: str | None = None,
    raw: bool = Query(False, description="包含功能域外的原文节点"),
    version_id: int | None = Query(None, description="指定配置版本（默认最新版本）"),
) -> dict[str, Any]:
    db = _db(request)
    if version_id is None:
        ver = graphstore.latest_version(db, device_id)
        if ver is None:
            raise ApiError(E_NOT_FOUND, 404)
        version_id = ver.id
    try:
        g, v, dev = graphstore.build_for_version(db, version_id, _kb(request))
    except KeyError as e:
        raise ApiError(E_NOT_FOUND, 404, "compare.version_not_found", version=version_id) from e
    if v.device_id != device_id:
        raise ApiError(E_NOT_FOUND, 404, "compare.version_not_found", version=version_id)
    kb = _kb(request)
    roots = [n.id for n in kb.nodes.values() if domain and n.domain == domain and not n.parent]
    data = graphmod.to_json(g, domain, include_raw=raw, roots=roots or None)
    data["version_id"] = v.id
    data["text"] = v.raw_text if raw else None
    return ok(request, data)


@router.get("/unknown-lines", summary="已导入配置中的未识别行（按出现次数汇总）")
def unknown_lines(request: Request, limit: int = Query(100, le=1000)) -> dict[str, Any]:
    return ok(request, {"patterns": analysis.unknown_summary(_db(request), limit)})
