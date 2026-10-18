"""配置对比接口：POST /compare；设备的配置版本列表（界面选“变更前后”用）。都需要令牌。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from lmesh.api.common import E_NOT_FOUND, E_PARAM, ApiError, ok, require_token, settings_of
from lmesh.core import analysis, compare, importer, kbservice, store

router = APIRouter(dependencies=[Depends(require_token)])


class SideBody(BaseModel):
    """对比的一边：给出 text（配置文本）、version_id（配置版本）或 device_id（设备的最新版本）之一。"""

    text: str | None = Field(None, max_length=importer.MAX_BYTES)
    device_id: int | None = None
    version_id: int | None = None
    profile: str | None = None


class CompareBody(BaseModel):
    a: SideBody
    b: SideBody
    domain: str | None = None
    include_raw: bool = False
    interface_map: dict[str, str] | None = None
    rename_threshold: float = Field(1.0, gt=0, le=1)
    hide_identity: bool = Field(False, description="隐藏设备身份差异（Router ID、接口地址、对等体地址、主机名等）")


def _db(request: Request) -> str:
    url = settings_of(request).database_url
    store.upgrade(url)
    return url


def _error(e: compare.CompareError) -> ApiError:
    if e.kind == "not_found":
        return ApiError(E_NOT_FOUND, 404, e.key, **e.fmt)
    return ApiError(E_PARAM, 422, e.key, **e.fmt)


def _side(request: Request, kb: Any, s: SideBody, label: str) -> compare.Side:
    if s.text:
        return compare.side_from_text(s.text, kb, s.profile, label)
    if s.version_id is not None:
        return compare.side_from_version(_db(request), kb, s.version_id, s.profile, s.device_id)
    if s.device_id is not None:
        return compare.side_from_device(_db(request), kb, s.device_id, s.profile)
    raise compare.CompareError("compare.need_source", side=label)


def run(request: Request, body: CompareBody) -> tuple[dict[str, Any], compare.Side, compare.Side]:
    """POST /compare 与报告共用：返回 (结果, A, B)。"""
    kb = analysis.load_kb(kbservice.runtime_root(settings_of(request)))
    try:
        a = _side(request, kb, body.a, "A")
        b = _side(request, kb, body.b, "B")
        result = compare.compare(
            a,
            b,
            kb,
            domain=body.domain,
            include_raw=body.include_raw,
            interface_map=body.interface_map,
            rename_threshold=body.rename_threshold,
            hide_identity=body.hide_identity,
        )
    except compare.CompareError as e:
        raise _error(e) from e
    return result, a, b


@router.post("/compare", summary="配置对比：有效值、改名识别、语义等价；返回差异列表、改名、统计与未识别行")
def run_compare(request: Request, body: CompareBody) -> dict[str, Any]:
    return ok(request, run(request, body)[0])


@router.get("/devices/{device_id}/versions", summary="设备的配置版本列表（新的在前）")
def device_versions(request: Request, device_id: int) -> dict[str, Any]:
    vers = compare.versions(_db(request), device_id)
    if vers is None:
        raise ApiError(E_NOT_FOUND, 404, "compare.device_not_found", target=str(device_id))
    return ok(request, {"device_id": device_id, "versions": vers})


@router.get("/devices/{device_id}/versions/{version_id}/text", summary="配置版本的原文（脱敏后）")
def version_text(request: Request, device_id: int, version_id: int) -> dict[str, Any]:
    data = compare.version_text(_db(request), device_id, version_id)
    if data is None:
        raise ApiError(E_NOT_FOUND, 404, "compare.version_not_found", version=version_id)
    return ok(request, data)
