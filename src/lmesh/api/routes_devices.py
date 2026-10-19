"""删除设备与单个配置版本（REQ-038）：所有登录账号都可删除，删除记入日志。

- GET /devices/{id}/delete-preview：将删除的内容计数、作基线的检查项目与脚本、每个版本的信息（不删除）
- DELETE /devices/{id}?force=false：删除设备；被检查项目作基线时 409（data 为删除预览），force=true 时清空这些项目的基线
- DELETE /devices/{id}/versions/{version_id}?force=false：删除一个配置版本；最后一个版本 409；被项目固定为基线时 409，
  force=true 时这些项目改为跟随最新版本
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, Depends, Query, Request

from lmesh.api.common import E_NOT_FOUND, E_STATE, ApiError, Principal, db_of, ok, require_token, settings_of
from lmesh.core import device_delete

router = APIRouter(dependencies=[Depends(require_token)])


def _raise(e: device_delete.DeleteError) -> NoReturn:
    if e.kind == "not_found":
        raise ApiError(E_NOT_FOUND, 404, e.key, data=e.data, **e.fmt) from e
    raise ApiError(E_STATE, 409, e.key, data=e.data, **e.fmt) from e


def _actor(p: Principal) -> str:
    return p.username if p.via == "session" else "api-token"


@router.get(
    "/devices/{device_id}/delete-preview", summary="删除设备的预览：连带删除的内容计数与受影响的检查项目（不删除）"
)
def delete_preview(request: Request, device_id: int) -> dict[str, Any]:
    try:
        return ok(request, device_delete.preview(db_of(request), device_id))
    except device_delete.DeleteError as e:
        _raise(e)


@router.delete("/devices/{device_id}", summary="删除设备与它的全部配置版本、快照、图、未识别行、导入记录、检查忽略项")
def delete_device(
    request: Request,
    device_id: int,
    force: bool = Query(False, description="被配置检查项目作基线时仍删除，并清空这些项目的基线"),
    p: Principal = Depends(require_token),
) -> dict[str, Any]:
    try:
        return ok(request, device_delete.delete_device(db_of(request), device_id, force, _actor(p)))
    except device_delete.DeleteError as e:
        _raise(e)


@router.delete(
    "/devices/{device_id}/versions/{version_id}", summary="删除设备的一个配置版本（最后一个版本不能单独删除）"
)
def delete_version(
    request: Request,
    device_id: int,
    version_id: int,
    force: bool = Query(False, description="版本被配置检查项目固定为基线时仍删除，这些项目改为跟随最新版本"),
    p: Principal = Depends(require_token),
) -> dict[str, Any]:
    from lmesh.core import analysis, kbservice

    db = db_of(request)
    try:
        kb = analysis.load_kb(kbservice.runtime_root(settings_of(request)))
    except Exception:  # 知识库加载失败不影响删除，变化计数留到查看时间线时再算
        kb = None
    try:
        return ok(request, device_delete.delete_version(db, device_id, version_id, force, _actor(p), kb))
    except device_delete.DeleteError as e:
        _raise(e)
