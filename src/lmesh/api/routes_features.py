"""特性能力查询接口（M5-4）：查询特性在各 Profile 的支持情况、命令写法、默认值与来源；两个 Profile 对比。都需要令牌。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from lmesh.api.common import E_NOT_FOUND, E_PARAM, ApiError, ok, require_token, settings_of
from lmesh.core import analysis, features, kbservice, terms

router = APIRouter(dependencies=[Depends(require_token)])


def _error(e: features.FeatureError) -> ApiError:
    if e.kind == "not_found":
        return ApiError(E_NOT_FOUND, 404, e.key, **e.fmt)
    return ApiError(E_PARAM, 422, e.key, **e.fmt)


def _profiles(v: str | None) -> list[str] | None:
    return [x.strip() for x in v.split(",") if x.strip()] if v else None


@router.get(
    "/features",
    summary="特性能力查询：按关键词（节点编号、叫法、命令写法）查各 Profile 的支持情况、默认值、命令卡与来源",
)
def get_features(
    request: Request,
    q: str = Query("", description="关键词；空为浏览全部（各 Profile 完全相同的只计数）"),
    profile: str | None = Query(None, description="逗号分隔的 Profile；不给时为全部"),
    family: str | None = Query(None, description="只看一个平台族"),
    domain: str | None = Query(None, description="只看一个功能域"),
    state: str | None = Query(None, description="supported / unsupported / unfilled：任一 Profile 符合"),
    include_same: bool = Query(False, description="浏览全部时也列出各 Profile 完全相同的特性"),
    limit: int = Query(200, ge=1, le=2000),
) -> dict[str, Any]:
    root = kbservice.runtime_root(settings_of(request))
    kb = analysis.load_kb(root)
    try:
        r = features.search(
            kb, q, _profiles(profile), family, domain, state, include_same, terms=terms.load(root, kb), limit=limit
        )
    except features.FeatureError as e:
        raise _error(e) from e
    return ok(request, r)


@router.get(
    "/features/detail", summary="一个特性（Schema 节点）在各 Profile 中的完整信息：命令卡、取消写法、视图、来源、依赖"
)
def get_feature_detail(
    request: Request,
    node: str = Query(..., description="Schema 节点编号，例如 interface.mtu"),
    profile: str | None = Query(None, description="逗号分隔的 Profile；不给时为全部"),
) -> dict[str, Any]:
    kb = analysis.load_kb(kbservice.runtime_root(settings_of(request)))
    try:
        return ok(request, features.detail(kb, node, _profiles(profile)))
    except features.FeatureError as e:
        raise _error(e) from e


@router.get(
    "/features/diff", summary="两个 Profile 对比：默认值不同的排在前面，其次支持情况不同、未填写；相同的默认只计数"
)
def get_feature_diff(
    request: Request,
    a: str = Query(..., description="Profile A"),
    b: str = Query(..., description="Profile B"),
    domain: str | None = Query(None),
    include_same: bool = Query(False, description="同时列出两边相同的特性"),
) -> dict[str, Any]:
    kb = analysis.load_kb(kbservice.runtime_root(settings_of(request)))
    try:
        return ok(request, features.diff(kb, a, b, domain, include_same))
    except features.FeatureError as e:
        raise _error(e) from e
