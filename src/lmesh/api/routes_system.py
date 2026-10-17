"""系统接口：健康检查、首次运行向导。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from lmesh.api.common import E_PARAM, E_STATE, ApiError, lang_of, ok, require_token, settings_of
from lmesh.core import config, i18n, setup, status

router = APIRouter()


@router.get("/health", summary="健康检查（不需要认证）")
def health(request: Request) -> dict[str, Any]:
    return ok(request, status.collect(settings_of(request)))


@router.get("/setup", summary="向导需要的参数定义（仅未配置时可用）")
def setup_schema(request: Request) -> dict[str, Any]:
    if config.is_configured():
        raise ApiError(E_STATE, 409, "setup.already")
    lang = lang_of(request)
    return ok(
        request,
        {"groups": setup.wizard_schema(lang), "addresses": setup.local_addresses(), "languages": list(i18n.LANGS)},
    )


class SetupBody(BaseModel):
    language: str = "zh-CN"
    values: dict[str, Any] = {}
    dry_run: bool = False  # 只校验，不写入（输入即校验）


@router.post("/setup", summary="提交向导结果（仅未配置时可用）")
def setup_apply(request: Request, body: SetupBody) -> dict[str, Any]:
    if config.is_configured():
        raise ApiError(E_STATE, 409, "setup.already")
    lang = i18n.normalize(body.language)
    values = dict(body.values)
    values.setdefault("ui.language", lang)
    current = int(settings_of(request).get("server.port"))
    errors = setup.validate_answers(values, current_port=current)
    if errors:
        raise ApiError(E_PARAM, 422, data={"errors": {k: i18n.t(v, lang) for k, v in errors.items()}})
    if body.dry_run:
        return ok(request, {"valid": True})
    old_host = settings_of(request).get("server.host")
    result = setup.apply(values, lang, current_port=current)
    new = config.load()
    request.app.state.settings = new
    # 改了监听地址或端口时，需要重启服务才能生效
    result["restart_required"] = (new.get("server.host"), new.get("server.port")) != (old_host, current)
    return ok(request, result)


@router.get("/config", summary="当前生效的配置（敏感值只显示是否已设置）", dependencies=[Depends(require_token)])
def effective_config(request: Request) -> dict[str, Any]:
    s = settings_of(request)
    return ok(request, {"values": s.public_dict(), "sources": s.sources})
