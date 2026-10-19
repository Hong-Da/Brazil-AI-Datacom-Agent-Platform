"""设备配置分析接口（REQ-034）：GET /devices/{id}/analysis、POST /analysis。都需要令牌。

parts 选择返回哪些部分（逗号分隔，默认全部）：
    summary  分析摘要（功能域对象数、检查发现、行的分类、依赖默认值的关键配置、安全基线得分、与上一版本的变化）
    layers   TCP/IP 分层（每个节点的层与跨层特性、跨层依赖）
    script   结构化脚本（逐行的区间、引用、定义行、隐藏的默认值行）
    graph    配置图（与 GET /devices/{id}/graph?raw=true 相同的结构），界面一次取齐
界面先取 graph,layers,script 显示脚本与视图，再单独取 summary（检查与历史比较慢一些）。
"""

from __future__ import annotations

from typing import Any

import networkx as nx
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from lmesh.api.common import E_NOT_FOUND, E_PARAM, ApiError, ok, require_token, settings_of
from lmesh.api.routes_check import _ignores, _overrides, _rules
from lmesh.core import analysis, config_analysis, graphstore, importer, kbservice, layers, store
from lmesh.core import graph as graphmod
from lmesh.core.kb import KnowledgeBase

router = APIRouter(dependencies=[Depends(require_token)])
PARTS = ("summary", "layers", "script", "graph")


def _parts(text: str | None) -> list[str]:
    if not text:
        return list(PARTS)
    got = [p.strip() for p in text.split(",") if p.strip()]
    bad = [p for p in got if p not in PARTS]
    if bad or not got:
        raise ApiError(E_PARAM, 422, "analysis.bad_part", part=", ".join(bad) or "-", allowed=", ".join(PARTS))
    return got


def build(
    request: Request,
    g: nx.MultiDiGraph,
    kb: KnowledgeBase,
    root: Any,
    parts: list[str],
    *,
    device_id: int | None = None,
    version_id: int | None = None,
    text: str | None = None,
    defaults: bool = True,
) -> dict[str, Any]:
    lay = layers.load(root)
    out: dict[str, Any] = {
        "device": g.graph.get("device"),
        "device_id": device_id,
        "version_id": version_id,
        "profile": g.graph.get("profile"),
        "family": g.graph.get("family"),
        "kb_version": g.graph.get("kb_version"),
        "parts": parts,
        "layer_info": lay.info(),
    }
    if "summary" in parts:
        chk = config_analysis.run_check(g, kb, _rules(kb, root), _overrides(root), _ignores(request, device_id))
        hist = None
        if device_id is not None and version_id is not None:
            hist = config_analysis.history_brief(settings_of(request).database_url, device_id, version_id, kb)
        out["summary"] = config_analysis.summary(
            g, kb, lay, check=chk, baseline=config_analysis.run_baseline(g, kb, root), history=hist
        )
    if "layers" in parts:
        out["layers"] = layers.classify(g, kb, lay)
    if "script" in parts:
        out["script"] = config_analysis.script(g, kb, lay, with_defaults=defaults)
    if "graph" in parts:
        data = graphmod.to_json(g, None, include_raw=True)
        data["text"] = text
        data["version_id"] = version_id
        out["graph"] = data
    return out


@router.get(
    "/devices/{device_id}/analysis",
    summary="设备配置分析：分析摘要、TCP/IP 分层、结构化脚本、配置图（parts 选择，默认全部）",
)
def device_analysis(
    request: Request,
    device_id: int,
    parts: str | None = Query(None, description="summary,layers,script,graph 中的若干个，逗号分隔；默认全部"),
    version_id: int | None = Query(None, description="指定配置版本（默认最新版本）"),
    defaults: bool = Query(True, description="结构化脚本带上隐藏的默认值行"),
) -> dict[str, Any]:
    want = _parts(parts)
    db = settings_of(request).database_url
    store.upgrade(db)
    if version_id is None:
        ver = graphstore.latest_version(db, device_id)
        if ver is None:
            raise ApiError(E_NOT_FOUND, 404)
        version_id = ver.id
    root = kbservice.runtime_root(settings_of(request))
    kb = analysis.load_kb(root)
    try:
        g, v, _ = graphstore.build_for_version(db, version_id, kb)
    except KeyError as e:
        raise ApiError(E_NOT_FOUND, 404, "compare.version_not_found", version=version_id) from e
    except analysis.AnalysisError as e:  # 知识库里没有能解析这份配置的 Profile
        raise ApiError(E_PARAM, 422, str(e), profile="") from e
    if v.device_id != device_id:
        raise ApiError(E_NOT_FOUND, 404, "compare.version_not_found", version=version_id)
    return ok(
        request,
        build(request, g, kb, root, want, device_id=device_id, version_id=v.id, text=v.raw_text, defaults=defaults),
    )


class AnalysisBody(BaseModel):
    text: str = Field(..., max_length=importer.MAX_BYTES, description="配置文本")
    profile: str | None = Field(None, description="知识库 Profile；不填时自动识别")
    name: str = Field("device", max_length=200, description="设备名（结果中显示）")
    parts: list[str] | None = Field(None, description="summary / layers / script / graph；默认全部")
    defaults: bool = Field(True, description="结构化脚本带上隐藏的默认值行")


@router.post("/analysis", summary="分析一份配置文本（不需要先导入；没有版本历史与忽略记录）")
def text_analysis(request: Request, body: AnalysisBody) -> dict[str, Any]:
    want = _parts(",".join(body.parts) if body.parts else None)
    root = kbservice.runtime_root(settings_of(request))
    kb = analysis.load_kb(root)
    try:
        res = analysis.parse_text(body.text, kb, body.profile)
    except analysis.AnalysisError as e:
        raise ApiError(E_PARAM, 422, str(e), profile=body.profile or "") from e
    g = graphmod.build(res.parsed, kb, res.profile, body.name)
    text = body.text.replace("\r\n", "\n")
    return ok(request, build(request, g, kb, root, want, text=text, defaults=body.defaults))
