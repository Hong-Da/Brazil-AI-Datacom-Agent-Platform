"""系统接口：健康检查、首次运行向导。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from lmesh.api.common import E_PARAM, E_STATE, ApiError, lang_of, ok, require_admin, settings_of
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
    s = settings_of(request)
    return ok(
        request,
        {
            "groups": setup.wizard_schema(lang),
            "addresses": setup.local_addresses(),
            "languages": list(i18n.LANGS),
            # 确认页（M6-9）：将写入的配置文件，以及当前运行的监听地址（与它不同的项需要重启才生效）
            "config_path": str(config.config_path()),
            "running": {"server.host": s.get("server.host"), "server.port": s.get("server.port")},
        },
    )


class AdminBody(BaseModel):
    username: str = ""
    password: str = ""


class SetupBody(BaseModel):
    language: str = "zh-CN"
    values: dict[str, Any] = {}
    admin: AdminBody | None = None  # 第一个管理员（REQ-030）；网页向导总会给出，省略时登录页再用 API 令牌创建
    dry_run: bool = False  # 只校验，不写入（输入即校验）


@router.post("/setup", summary="提交向导结果（仅未配置时可用）")
def setup_apply(request: Request, response: Response, body: SetupBody) -> dict[str, Any]:
    if config.is_configured():
        raise ApiError(E_STATE, 409, "setup.already")
    lang = i18n.normalize(body.language)
    values = dict(body.values)
    values.setdefault("ui.language", lang)
    current = int(settings_of(request).get("server.port"))
    admin = body.admin.model_dump() if body.admin else None
    errors = setup.validate_answers(values, current_port=current)
    errors.update(setup.validate_admin(admin))
    if errors:
        raise ApiError(E_PARAM, 422, data={"errors": {k: i18n.t(v, lang) for k, v in errors.items()}})
    if body.dry_run:
        return ok(request, {"valid": True})
    old_host = settings_of(request).get("server.host")
    result = setup.apply(values, lang, current_port=current, admin=admin)
    new = config.load()
    request.app.state.settings = new
    if result.get("admin"):  # 向导里创建了管理员：直接登录
        from lmesh.api.routes_auth import _start_session

        result["session_expires_at"] = _start_session(request, response, result["admin"])["expires_at"]
    # 改了监听地址或端口时，需要重启服务才能生效
    result["restart_required"] = (new.get("server.host"), new.get("server.port")) != (old_host, current)
    return ok(request, result)


@router.get(
    "/config", summary="当前生效的配置（敏感值只显示是否已设置；管理员）", dependencies=[Depends(require_admin)]
)
def effective_config(request: Request) -> dict[str, Any]:
    s = settings_of(request)
    return ok(request, {"values": s.public_dict(), "sources": s.sources})
