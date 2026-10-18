"""登录与账号接口（REQ-030）：/auth/* 与 /users（管理员）。

网页登录后发放会话 Cookie（HttpOnly、SameSite=Strict），数据库只存其哈希；脚本继续用 Bearer API 令牌（视为管理员）。
"""

from __future__ import annotations

import logging
from typing import Any, NoReturn

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from lmesh.api.common import (
    E_AUTH,
    E_NOT_FOUND,
    E_PARAM,
    E_STATE,
    SESSION_COOKIE,
    ApiError,
    Principal,
    db_of,
    ok,
    require_admin,
    require_token,
    settings_of,
    token_ok,
)
from lmesh.core import config, users
from lmesh.core.store.models import iso

router = APIRouter()
_log = logging.getLogger("lmesh.auth")


def _user_error(e: users.UserError) -> NoReturn:
    if e.kind == "not_found":
        raise ApiError(E_NOT_FOUND, 404, e.key, **e.fmt)
    if e.kind == "param":
        raise ApiError(E_PARAM, 422, e.key, **e.fmt)
    raise ApiError(E_STATE, 409, e.key, **e.fmt)


def _client(request: Request) -> str:
    return request.client.host if request.client else ""


def _start_session(request: Request, response: Response, user: dict[str, Any]) -> dict[str, Any]:
    hours = int(settings_of(request).get("security.session_hours"))
    token, expires = users.create_session(db_of(request), user["id"], hours)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=hours * 3600,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/",
    )
    return {"user": user, "expires_at": iso(expires)}


# ---------- 登录、登出、当前用户 ----------


@router.get("/auth/status", summary="登录页需要的状态：是否已配置、是否已有账号（不需要认证）")
def auth_status(request: Request) -> dict[str, Any]:
    configured = config.is_configured()
    has_users = users.count(db_of(request)) > 0 if configured else False
    return ok(
        request,
        {
            "configured": configured,
            "has_users": has_users,
            "session_hours": settings_of(request).get("security.session_hours"),
        },
    )


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/auth/login", summary="用户名 + 密码登录，成功后设置会话 Cookie")
def auth_login(request: Request, response: Response, body: LoginBody) -> dict[str, Any]:
    if not config.is_configured():
        raise ApiError(E_STATE, 409, "config.not_configured")
    s = settings_of(request)
    try:
        user = users.authenticate(
            db_of(request),
            body.username,
            body.password,
            int(s.get("security.login_max_failures")),
            int(s.get("security.login_lock_minutes")),
            client=_client(request),
        )
    except users.AuthError as e:
        if e.reason == "locked":
            until = iso(e.locked_until)
            raise ApiError(E_AUTH, 429, "auth.locked", data={"locked_until": until}, until=until) from None
        if e.reason == "disabled":
            raise ApiError(E_AUTH, 403, "auth.disabled") from None
        raise ApiError(E_AUTH, 401, "auth.invalid") from None
    return ok(request, _start_session(request, response, user))


class BootstrapBody(BaseModel):
    token: str
    username: str
    password: str


@router.post("/auth/bootstrap", summary="还没有任何账号时：用 API 令牌创建第一个管理员并登录")
def auth_bootstrap(request: Request, response: Response, body: BootstrapBody) -> dict[str, Any]:
    if not config.is_configured():
        raise ApiError(E_STATE, 409, "config.not_configured")
    db = db_of(request)
    if users.count(db) > 0:
        raise ApiError(E_STATE, 409, "auth.has_users")
    if not token_ok(settings_of(request), body.token.strip()):
        _log.warning("创建第一个管理员失败：API 令牌不正确 [%s]", _client(request))
        raise ApiError(E_AUTH, 401, "auth.bad_token")
    try:
        user = users.create_user(db, body.username, body.password, "admin")
    except users.UserError as e:
        _user_error(e)
    _log.info("用 API 令牌创建了第一个管理员：%s [%s]", user["username"], _client(request))
    return ok(request, _start_session(request, response, user))


@router.post("/auth/logout", summary="登出：删除会话并清除 Cookie（没有登录时也返回成功）")
def auth_logout(request: Request, response: Response) -> dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE, "")
    name = users.end_session(db_of(request), token) if token and config.is_configured() else None
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    return ok(request, {"logged_out": bool(name)})


@router.get("/auth/me", summary="当前调用者：账号、角色、认证方式（session / token）")
def auth_me(request: Request, p: Principal = Depends(require_token)) -> dict[str, Any]:
    return ok(
        request,
        {"username": p.username, "role": p.role, "via": p.via, "expires_at": p.session_expires_at},
    )


class PasswordBody(BaseModel):
    old_password: str
    new_password: str


@router.post("/auth/password", summary="修改自己的密码（其他会话失效，当前会话保留）")
def auth_password(request: Request, body: PasswordBody, p: Principal = Depends(require_token)) -> dict[str, Any]:
    if p.via != "session" or p.user_id is None:
        raise ApiError(E_STATE, 409, "auth.token_no_password")
    try:
        r = users.change_password(
            db_of(request), p.user_id, body.old_password, body.new_password, request.cookies.get(SESSION_COOKIE)
        )
    except users.UserError as e:
        _user_error(e)
    return ok(request, r)


# ---------- 账号管理（管理员） ----------

admin = APIRouter(dependencies=[Depends(require_admin)])


@admin.get("/users", summary="账号列表（管理员）")
def users_list(request: Request) -> dict[str, Any]:
    rows = users.list_users(db_of(request))
    return ok(request, {"users": rows, "count": len(rows)})


class NewUserBody(BaseModel):
    username: str
    password: str
    role: str = "user"


@admin.post("/users", summary="新建账号（管理员）")
def users_create(request: Request, body: NewUserBody) -> dict[str, Any]:
    try:
        return ok(request, {"user": users.create_user(db_of(request), body.username, body.password, body.role)})
    except users.UserError as e:
        _user_error(e)


class UpdateUserBody(BaseModel):
    role: str | None = None
    disabled: bool | None = None
    unlock: bool = False


def _not_self(request: Request, username: str) -> None:
    p: Principal = request.state.principal
    if p.via == "session" and p.username == username:
        raise ApiError(E_STATE, 409, "users.self")


@admin.put("/users/{username}", summary="改角色、停用 / 启用、解除锁定（管理员）")
def users_update(request: Request, username: str, body: UpdateUserBody) -> dict[str, Any]:
    if body.disabled or body.role == "user":
        _not_self(request, username)
    try:
        u = users.update_user(db_of(request), username, role=body.role, disabled=body.disabled, unlock=body.unlock)
    except users.UserError as e:
        _user_error(e)
    return ok(request, {"user": u})


class ResetBody(BaseModel):
    password: str


@admin.post("/users/{username}/password", summary="重置密码（管理员）：解除锁定，该账号的会话全部失效")
def users_reset(request: Request, username: str, body: ResetBody) -> dict[str, Any]:
    try:
        r = users.reset_password(db_of(request), username, body.password)
    except users.UserError as e:
        _user_error(e)
    closed = r.pop("sessions_closed")
    return ok(request, {"user": r, "sessions_closed": closed})


@admin.delete("/users/{username}", summary="删除账号（管理员；不能删除自己和最后一个启用的管理员）")
def users_delete(request: Request, username: str) -> dict[str, Any]:
    _not_self(request, username)
    try:
        return ok(request, users.delete_user(db_of(request), username))
    except users.UserError as e:
        _user_error(e)
