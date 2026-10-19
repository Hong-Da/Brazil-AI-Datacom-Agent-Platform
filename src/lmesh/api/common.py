"""API 公共部分：统一返回结构、错误码、语言、认证。

返回结构：{"code": 0, "message": "ok", "data": {...}}；message 按 Accept-Language 返回对应语言，code 与 data 不随语言变化。
认证（REQ-030）：网页用会话 Cookie（lmesh_session，HttpOnly、SameSite=Strict）；脚本用 Authorization: Bearer <令牌>：
全局令牌（security.api_token）视为管理员；个人令牌（lmp_ 开头，M6）权限与本人账号相同，可以是只读的。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from lmesh.core import config, i18n, projects, store, tokens, users

# 错误码表（同时写入 docs/api.md）
OK = 0
E_INTERNAL = 1000
E_PARAM = 1001
E_AUTH = 1002
E_STATE = 1003  # 未配置 / 已配置等状态不允许
E_NOT_FOUND = 1004
E_EXTERNAL = 1005
E_FORBIDDEN = 1006  # 已登录但没有权限（普通用户访问管理员接口、只读成员或只读令牌修改数据）

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
    """当前调用者：会话登录的账号、持个人令牌的脚本（via=pat，权限同本人账号），或持全局令牌的脚本（视为管理员）。"""

    username: str
    role: str
    via: str  # session / token / pat
    user_id: int | None = None
    session_expires_at: str | None = None
    read_only: bool = False  # 只读的个人令牌
    token_prefix: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_kb_editor(self) -> bool:
        return self.role in ("admin", "maintainer")

    def identity(self) -> projects.Identity:
        return projects.Identity(self.user_id, self.username, self.role)


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
    if given and tokens.looks_personal(given):
        if not config.is_configured():
            raise ApiError(E_AUTH, 401)
        client = request.client.host if request.client else ""
        hit = tokens.authenticate(db_of(request), given, client)
        if hit is None:
            raise ApiError(E_AUTH, 401)
        p = Principal(
            hit["username"], hit["role"], "pat", hit["user_id"], read_only=hit["read_only"], token_prefix=hit["prefix"]
        )
    elif given:
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
    """管理员专属接口（账号、系统设置、AI 接口、公共设备库、所有项目）：其他角色返回 403。"""
    if not p.is_admin:
        raise ApiError(E_FORBIDDEN, 403)
    return p


def require_kb_editor(p: Principal = Depends(require_token)) -> Principal:
    """知识库与共享内容（REQ-036）：管理员与知识库维护员；普通用户返回 403（可以提交建议）。"""
    if not p.is_kb_editor:
        raise ApiError(E_FORBIDDEN, 403, "api.error.kb_editor_only")
    return p


def principal_of(request: Request) -> Principal:
    return request.state.principal  # type: ignore[no-any-return]


def project_error(e: projects.ProjectError) -> ApiError:
    """项目与权限错误 → 接口错误（not_found 404、forbidden 403、state 409、param 422）。"""
    if e.kind == "not_found":
        return ApiError(E_NOT_FOUND, 404, e.key, data=e.data, **e.fmt)
    if e.kind == "forbidden":
        return ApiError(E_FORBIDDEN, 403, e.key, data=e.data, **e.fmt)
    if e.kind == "state":
        return ApiError(E_STATE, 409, e.key, data=e.data, **e.fmt)
    return ApiError(E_PARAM, 422, e.key, data=e.data, **e.fmt)
