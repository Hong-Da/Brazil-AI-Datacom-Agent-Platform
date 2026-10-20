"""配置翻译接口：POST /translate。需要令牌。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import Field

from lmesh.api.common import E_NOT_FOUND, E_PARAM, ApiError, ok, require_token, settings_of
from lmesh.api.routes_translate_rules import RulesRef, resolve_rules
from lmesh.core import analysis, compare, importer, kbservice, store, translate

router = APIRouter(dependencies=[Depends(require_token)])


class TranslateBody(RulesRef):
    """源配置：给出 text（配置文本）、version_id（配置版本）或 device_id（设备的最新版本）之一；
    rule_set / rules：翻译自定义规则（REQ-032），结果另有 naming。"""

    text: str | None = Field(None, max_length=importer.MAX_BYTES)
    device_id: int | None = None
    version_id: int | None = None
    profile: str | None = Field(None, description="源配置的 Profile（不给时自动识别）")
    to: str = Field(..., description="目标 Profile，例如 cisco-iosxe-asr920-17.15")
    interface_map: dict[str, str] | None = Field(None, description="接口映射表 {源接口: 目标接口}，子接口按父接口映射")
    verify: bool = Field(True, description="译文再解析建图，与源图按有效值对比")


def _db(request: Request) -> str:
    url = settings_of(request).database_url
    store.upgrade(url)
    return url


@router.post(
    "/translate", summary="配置翻译：按有效值翻译到另一个 Profile，返回译文、告警、不支持的项、省略的默认值与校验结果"
)
def run_translate(request: Request, body: TranslateBody) -> dict[str, Any]:
    kb = analysis.load_kb(kbservice.runtime_root(settings_of(request)))
    rules = resolve_rules(request, body, kb)
    try:
        if body.text:
            side = compare.side_from_text(body.text, kb, body.profile, "source")
        elif body.version_id is not None:
            side = compare.side_from_version(_db(request), kb, body.version_id, body.profile, body.device_id)
        elif body.device_id is not None:
            side = compare.side_from_device(_db(request), kb, body.device_id, body.profile)
        else:
            raise ApiError(E_PARAM, 422, "translate.need_source")
        result = translate.translate(
            side.graph,
            kb,
            str(side.graph.graph.get("profile")),
            body.to,
            body.interface_map,
            verify=body.verify,
            rules=rules,
        )
    except compare.CompareError as e:
        if e.kind == "not_found":
            raise ApiError(E_NOT_FOUND, 404, e.key, **e.fmt) from e
        raise ApiError(E_PARAM, 422, e.key, **e.fmt) from e
    except translate.TranslateError as e:
        raise ApiError(E_PARAM, 422, e.key, **e.fmt) from e
    scope = getattr(request.state, "scope", None)
    if body.device_id is not None and not body.text and scope is not None:
        # M8-4：项目里采纳的“翻译未支持项”AI 写法写进译文（标为 AI 来源：ai_lines、ai_patches）
        from lmesh.core import ai_suggest_change

        patches = ai_suggest_change.translate_patches(_db(request), scope.project_id, body.device_id, body.to)
        result = ai_suggest_change.apply_translate_patches(result, patches, kb, body.to)
    return ok(request, result)
