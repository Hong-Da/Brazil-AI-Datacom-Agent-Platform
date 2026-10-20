"""登录与账号接口（REQ-030）：/auth/* 与 /users（管理员）。

网页登录后发放会话 Cookie（HttpOnly、SameSite=Strict），数据库只存其哈希；脚本继续用 Bearer API 令牌（视为管理员）。
"""

from __future__ import annotations

import logging
from typing import Any, Literal, NoReturn

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from lmesh.api.common import (
    E_AUTH,
    E_FORBIDDEN,
    E_NOT_FOUND,
    E_PARAM,
    E_STATE,
    SESSION_COOKIE,
    ApiError,
    Principal,
    db_of,
    lang_of,
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


@router.get(
    "/auth/status",
    summary="登录页需要的状态：是否已配置、是否已有账号；还没有账号时另给配置文件路径与是否设置了令牌（不需要认证）",
)
def auth_status(request: Request) -> dict[str, Any]:
    configured = config.is_configured()
    has_users = users.count(db_of(request)) > 0 if configured else False
    s = settings_of(request)
    data: dict[str, Any] = {
        "configured": configured,
        "has_users": has_users,
        "session_hours": s.get("security.session_hours"),
        # 自助注册（REQ-039）：登录页据此显示注册入口；还没有账号时不开放（先创建管理员）
        "registration": {
            "open": bool(configured and has_users and s.get("auth.registration")),
            "approval": bool(s.get("auth.registration_approval")),
        },
    }
    if configured and not has_users:
        # 只在创建第一个管理员之前返回：实际读取的配置文件路径与是否设置了令牌（不返回令牌内容）
        data["config_file"] = str(config.config_path().resolve())
        data["token_set"] = bool(str(s.get("security.api_token") or "").strip())
    return ok(request, data)


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
        if e.reason == "pending":
            raise ApiError(E_AUTH, 403, "auth.pending", data={"reason": "pending"}) from None
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


class RegisterBody(BaseModel):
    username: str = Field(..., max_length=64)
    password: str = Field(..., max_length=256)


def _audit(request: Request, actor: str, user_id: int | None, action: str, detail: dict[str, Any]) -> None:
    from lmesh.core import projects

    projects.audit(db_of(request), projects.Identity(user_id, actor, "user"), None, "", action, detail)


@router.post(
    "/auth/register",
    summary="自助注册（REQ-039，不需要登录）：关闭时 403；同一来源地址超过频率 429；需要审核时账号待审核，否则直接登录",
)
def auth_register(request: Request, response: Response, body: RegisterBody) -> dict[str, Any]:
    if not config.is_configured():
        raise ApiError(E_STATE, 409, "config.not_configured")
    s = settings_of(request)
    db = db_of(request)
    if not s.get("auth.registration") or users.count(db) == 0:
        raise ApiError(E_FORBIDDEN, 403, "auth.registration_closed")
    limit = int(s.get("auth.registration_rate_per_hour"))
    client = _client(request)
    if not users.REGISTER_LIMITER.allow(client or "-", limit):
        _log.warning("注册过于频繁 [%s]", client)
        raise ApiError(E_AUTH, 429, "auth.registration_rate", data={"per_hour": limit}, n=limit)
    approval = bool(s.get("auth.registration_approval"))
    try:
        user = users.register(db, body.username, body.password, approval)
    except users.UserError as e:
        _user_error(e)
    _audit(
        request,
        user["username"],
        None,
        "user.register",
        {"username": user["username"], "status": user["status"], "client": client},
    )
    data: dict[str, Any] = {"username": user["username"], "status": user["status"]}
    if user["status"] == "active":  # 不需要审核：直接登录
        data.update(_start_session(request, response, user))
    return ok(request, data)


@router.post("/auth/logout", summary="登出：删除会话并清除 Cookie（没有登录时也返回成功）")
def auth_logout(request: Request, response: Response) -> dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE, "")
    name = users.end_session(db_of(request), token) if token and config.is_configured() else None
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    return ok(request, {"logged_out": bool(name)})


@router.get(
    "/auth/me", summary="当前调用者：账号、角色、认证方式（session / token / pat）、是否只读令牌、个人令牌前 8 个字符"
)
def auth_me(request: Request, p: Principal = Depends(require_token)) -> dict[str, Any]:
    return ok(
        request,
        {
            "username": p.username,
            "role": p.role,
            "via": p.via,
            "expires_at": p.session_expires_at,
            "read_only": p.read_only,
            "token_prefix": p.token_prefix,
        },
    )


class PrefsBody(BaseModel):
    lang: Literal["zh-CN", "en", "pt-BR"] | None = None
    theme: Literal["auto", "light", "dark"] | None = None
    term_style: Literal["huawei", "cisco", "nokia"] | None = Field(
        None, description="显示风格（华为 / Cisco / Nokia 的叫法）"
    )
    icon_set: Literal["cyl", "geo", "line"] | None = Field(
        None, description="设备图标风格：cyl 圆柱、geo 几何徽章、line 线框"
    )


@router.get(
    "/me/prefs",
    summary="我的个人偏好（REQ-047）：语言、主题、显示风格、图标风格；prefs 为 null 表示账号还没保存过（全局令牌没有账号）",
)
def get_prefs(request: Request, p: Principal = Depends(require_token)) -> dict[str, Any]:
    if p.user_id is None:
        return ok(request, {"has_account": False, "prefs": None})
    try:
        return ok(request, {"has_account": True, "prefs": users.get_prefs(db_of(request), p.user_id)})
    except users.UserError as e:
        _user_error(e)


@router.put(
    "/me/prefs",
    summary="保存我的个人偏好（只改给出的项；全局 API 令牌没有账号：409；只读个人令牌：403）",
)
def put_prefs(request: Request, body: PrefsBody, p: Principal = Depends(require_token)) -> dict[str, Any]:
    if p.user_id is None:
        raise ApiError(E_STATE, 409, "prefs.no_account")
    if p.read_only:
        raise ApiError(E_FORBIDDEN, 403, "api.error.read_only_token")
    try:
        saved = users.save_prefs(db_of(request), p.user_id, body.model_dump(exclude_none=True))
    except users.UserError as e:
        _user_error(e)
    return ok(request, {"has_account": True, "prefs": saved})


@router.delete(
    "/me/prefs",
    summary="清除我保存在账号里的个人偏好（下次登录时网页改用浏览器本地的值并写入账号）",
)
def delete_prefs(request: Request, p: Principal = Depends(require_token)) -> dict[str, Any]:
    if p.user_id is None:
        raise ApiError(E_STATE, 409, "prefs.no_account")
    if p.read_only:
        raise ApiError(E_FORBIDDEN, 403, "api.error.read_only_token")
    try:
        users.clear_prefs(db_of(request), p.user_id)
    except users.UserError as e:
        _user_error(e)
    return ok(request, {"has_account": True, "prefs": None})


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


@admin.get(
    "/users", summary="账号列表（管理员）：另附拥有的项目数与有效的个人令牌数；status=pending 只看待审核的自助注册账号"
)
def users_list(
    request: Request, status: str | None = Query(None, pattern="^(active|pending)$", description="active | pending")
) -> dict[str, Any]:
    from lmesh.core import projects, tokens

    db = db_of(request)
    rows = users.list_users(db, status)
    for r in rows:
        r["projects"] = len(projects.owned_projects(db, r["username"], non_empty_only=True))
        r["tokens"] = sum(1 for t in tokens.list_tokens(db, r["username"]) if t["state"] == "active")
    return ok(request, {"users": rows, "count": len(rows), "pending": users.count_pending(db)})


@admin.get(
    "/users/{username}/projects", summary="账号拥有的项目（删除账号前选择转交或一并删除；空的默认项目会自动删除）"
)
def user_projects(request: Request, username: str) -> dict[str, Any]:
    from lmesh.core import projects

    try:
        return ok(request, {"projects": projects.owned_projects(db_of(request), username, non_empty_only=True)})
    except projects.ProjectError as e:
        raise ApiError(E_NOT_FOUND, 404, e.key, **e.fmt) from e


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
    if body.disabled or body.role not in (None, "admin"):
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


@admin.delete(
    "/users/{username}",
    summary="删除账号（管理员；不能删除自己和最后一个启用的管理员）；拥有项目时用 transfer_to 转交或 delete_projects 一并删除",
)
def users_delete(
    request: Request, username: str, transfer_to: str | None = None, delete_projects: bool = False
) -> dict[str, Any]:
    from lmesh.core import projects

    _not_self(request, username)
    db = db_of(request)
    p: Principal = request.state.principal
    try:
        return ok(request, users.delete_user(db, username, transfer_to, delete_projects, p.identity()))
    except users.UserError as e:
        if e.key == "users.has_projects":
            raise ApiError(
                E_STATE, 409, e.key, data={"projects": projects.owned_projects(db, username, True)}, **e.fmt
            ) from e
        _user_error(e)


@admin.post("/users/{username}/approve", summary="批准自助注册的待审核账号（管理员）：可以登录，并建好默认项目")
def users_approve(request: Request, username: str) -> dict[str, Any]:
    p: Principal = request.state.principal
    try:
        u = users.approve(db_of(request), username)
    except users.UserError as e:
        _user_error(e)
    _audit(request, p.username, p.user_id, "user.approve", {"username": u["username"]})
    return ok(request, {"user": u})


@admin.post("/users/{username}/reject", summary="拒绝自助注册的待审核账号（管理员）：删除该账号，用户名可以再注册")
def users_reject(request: Request, username: str) -> dict[str, Any]:
    p: Principal = request.state.principal
    try:
        r = users.reject(db_of(request), username)
    except users.UserError as e:
        _user_error(e)
    _audit(request, p.username, p.user_id, "user.reject", {"username": username})
    return ok(request, r)


REG_KEYS = ("auth.registration", "auth.registration_approval", "auth.registration_rate_per_hour")


def _reg_settings(s: config.Settings) -> dict[str, Any]:
    return {
        "registration": bool(s.get("auth.registration")),
        "approval": bool(s.get("auth.registration_approval")),
        "rate_per_hour": int(s.get("auth.registration_rate_per_hour")),
        "sources": {k.split(".", 1)[1]: s.sources.get(k) for k in REG_KEYS},
    }


@admin.get("/auth/settings", summary="自助注册设置（管理员）：是否开放、是否需要审核、每个地址每小时次数")
def auth_settings(request: Request) -> dict[str, Any]:
    return ok(request, _reg_settings(settings_of(request)))


class RegSettingsBody(BaseModel):
    registration: bool | None = None
    approval: bool | None = None
    rate_per_hour: int | None = Field(None, ge=1, le=1000)


@admin.put("/auth/settings", summary="保存自助注册设置（管理员；写入配置文件 [auth]，立即生效）")
def auth_settings_put(request: Request, body: RegSettingsBody) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if body.registration is not None:
        updates["auth.registration"] = body.registration
    if body.approval is not None:
        updates["auth.registration_approval"] = body.approval
    if body.rate_per_hour is not None:
        updates["auth.registration_rate_per_hour"] = body.rate_per_hour
    try:
        new = config.update_file(updates, lang_of(request))
    except config.ConfigError as e:
        raise ApiError(E_PARAM, 422, data={"error": str(e)}) from e
    request.app.state.settings = new
    p: Principal = request.state.principal
    _audit(request, p.username, p.user_id, "settings.registration", {k.split(".", 1)[1]: v for k, v in updates.items()})
    return ok(request, _reg_settings(new))
