"""割接迁移接口：POST /migrate、POST /migrate/suggest-map。需要令牌。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from lmesh.api.common import E_NOT_FOUND, E_PARAM, ApiError, ok, require_token, settings_of
from lmesh.core import analysis, compare, importer, kbservice, migration, store, translate

router = APIRouter(dependencies=[Depends(require_token)])


class SuggestBody(BaseModel):
    """旧设备配置：给出 text（配置文本）、version_id（配置版本）或 device_id（设备的最新版本）之一。"""

    text: str | None = Field(None, max_length=importer.MAX_BYTES)
    device_id: int | None = None
    version_id: int | None = None
    profile: str | None = Field(None, description="旧配置的 Profile（不给时自动识别）")
    to: str = Field(..., description="新设备的目标 Profile，例如 cisco-iosxe-asr920-17.15")
    interface_map: dict[str, str] | None = Field(
        None, description="接口映射表 {旧接口: 新接口}，可以只给部分，其余自动建议；新接口为 - 表示不迁移"
    )
    target_text: str | None = Field(
        None, max_length=importer.MAX_BYTES, description="新设备现有配置（出厂 / 已配置的管理口），按目标 Profile 解析"
    )
    model: str | None = Field(None, description="新设备型号（按知识库的端口清单分配接口）")


class MigrateBody(SuggestBody):
    on_conflict: str = Field("migrate", description="现有配置与迁移内容冲突时：migrate 以旧设备为准，keep 保留现有")
    verify: bool = Field(True, description="新配置再解析建图，与旧设备按有效值对比")


def _db(request: Request) -> str:
    url = settings_of(request).database_url
    store.upgrade(url)
    return url


def _inputs(request: Request, body: SuggestBody) -> tuple[Any, Any, Any]:
    kb = analysis.load_kb(kbservice.runtime_root(settings_of(request)))
    if body.to not in kb.profiles:
        raise migration.MigrateError("parse.profile_unknown", profile=body.to)
    if body.text:
        side = compare.side_from_text(body.text, kb, body.profile, "old")
    elif body.version_id is not None:
        side = compare.side_from_version(_db(request), kb, body.version_id, body.profile, body.device_id)
    elif body.device_id is not None:
        side = compare.side_from_device(_db(request), kb, body.device_id, body.profile)
    else:
        raise ApiError(E_PARAM, 422, "translate.need_source")
    tg = migration.target_graph_from_text(body.target_text, kb, body.to) if body.target_text else None
    return kb, side.graph, tg


def _errors(fn: Any) -> Any:
    try:
        return fn()
    except compare.CompareError as e:
        if e.kind == "not_found":
            raise ApiError(E_NOT_FOUND, 404, e.key, **e.fmt) from e
        raise ApiError(E_PARAM, 422, e.key, **e.fmt) from e
    except (migration.MigrateError, translate.TranslateError) as e:
        raise ApiError(E_PARAM, 422, e.key, **e.fmt) from e


@router.post(
    "/migrate",
    summary="割接迁移：翻译 + 接口映射（自动建议），返回新设备配置、增量配置、映射表、告警、校验结果与割接步骤",
)
def run_migrate(request: Request, body: MigrateBody) -> dict[str, Any]:
    def go() -> dict[str, Any]:
        kb, g, tg = _inputs(request, body)
        return migration.migrate(
            g,
            kb,
            str(g.graph.get("profile")),
            body.to,
            body.interface_map,
            tg,
            body.model,
            body.on_conflict,
            verify=body.verify,
        )

    return ok(request, _errors(go))


@router.post("/migrate/suggest-map", summary="割接迁移的接口映射建议：每条附依据与置信度，列出未映射的接口")
def run_suggest(request: Request, body: SuggestBody) -> dict[str, Any]:
    def go() -> dict[str, Any]:
        kb, g, tg = _inputs(request, body)
        return migration.suggest_map(g, kb, str(g.graph.get("profile")), body.to, body.interface_map, tg, body.model)

    return ok(request, _errors(go))
