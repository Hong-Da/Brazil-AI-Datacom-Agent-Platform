"""API 公共部分：统一返回结构、错误码、语言、认证。

返回结构：{"code": 0, "message": "ok", "data": {...}}；message 按 Accept-Language 返回对应语言，code 与 data 不随语言变化。
认证（REQ-030）：网页用会话 Cookie（lmesh_session，HttpOnly、SameSite=Strict）；脚本用 Authorization: Bearer <API 令牌>，视为管理员。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from lmesh.core import config, i18n, store, users

# 错误码表（同时写入 docs/api.md）
OK = 0
E_INTERNAL = 1000
E_PARAM = 1001
E_AUTH = 1002
E_STATE = 1003  # 未配置 / 已配置等状态不允许
E_NOT_FOUND = 1004
E_EXTERNAL = 1005
E_FORBIDDEN = 1006  # 已登录但没有权限（普通用户访问管理员接口）

ERROR_CODES = {
    OK: "api.ok",
    E_INTERNAL: "api.error.internal",
    E_PARAM: "api.error.param",
    E_AUTH: "api.error.auth",
    E_STATE: "api.error.state",
    E_NOT_FOUND: "api.error.not_found",
    E_EXTERNAL: "api.error.external",
    E_FORBIDDEN: "api.error.forbidden",
}


class ApiError(Exception):
    def __init__(self, code: int, http_status: int = 400, message_key: str | None = None, data: Any = None, **fmt: Any):
        super().__init__(code)
        self.code, self.http_status = code, http_status
        self.message_key = message_key or ERROR_CODES.get(code, "api.error.internal")
        self.data, self.fmt = data, fmt


def lang_of(request: Request) -> str:
    return i18n.from_accept_language(request.headers.get("accept-language"))


def ok(request: Request, data: Any = None) -> dict[str, Any]:
    return {"code": OK, "message": i18n.t("api.ok", lang_of(request)), "data": data}


def error_response(request: Request, err: ApiError) -> JSONResponse:
    lang = lang_of(request)
    body = {"code": err.code, "message": i18n.t(err.message_key, lang, **err.fmt), "data": err.data}
    return JSONResponse(body, status_code=err.http_status)


def settings_of(request: Request) -> config.Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


SESSION_COOKIE = "lmesh_session"
TOKEN_USER = "api-token"  # Bearer 令牌调用时的显示名


@dataclass(frozen=True)
class Principal:
    """当前调用者：会话登录的账号，或持 API 令牌的脚本（视为管理员）。"""

    username: str
    role: str
    via: str  # session / token
    user_id: int | None = None
    session_expires_at: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def bearer_of(request: Request) -> str:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else ""


def token_ok(settings: config.Settings, given: str) -> bool:
    expected = str(settings.get("security.api_token") or "")
    return bool(expected and given and secrets.compare_digest(given, expected))


def db_of(request: Request) -> str:
    url = settings_of(request).database_url
    store.upgrade(url)
    return url


def require_token(request: Request, settings: config.Settings = Depends(settings_of)) -> Principal:
    """需要登录的接口：会话 Cookie 或 Authorization: Bearer <令牌>（带了令牌就以令牌为准）。"""
    given = bearer_of(request)
    if given:
        if not token_ok(settings, given):
            raise ApiError(E_AUTH, 401)
        p = Principal(TOKEN_USER, "admin", "token")
    else:
        cookie = request.cookies.get(SESSION_COOKIE, "")
        if not cookie or not config.is_configured():
            raise ApiError(E_AUTH, 401)
        u = users.session_user(db_of(request), cookie)
        if u is None:
            raise ApiError(E_AUTH, 401)
        p = Principal(u["username"], u["role"], "session", u["id"], u.get("session_expires_at"))
    request.state.principal = p
    return p


def require_admin(p: Principal = Depends(require_token)) -> Principal:
    """管理员专属接口（账号、系统设置、AI 接口、知识库发布）：普通用户返回 403。"""
    if not p.is_admin:
        raise ApiError(E_FORBIDDEN, 403)
    return p
