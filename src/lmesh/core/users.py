"""用户账号与网页会话（REQ-030）。CLI 与 API 共用。

- 密码只保存 scrypt 哈希（标准库 hashlib.scrypt，随机盐），最短 8 位；不写入日志或任何文件。
- 角色：admin（账号、系统设置、AI 接口、知识库发布）与 user（其余全部功能）。
- 至少保留一个启用的管理员：最后一个启用的管理员不能停用、删除或改成普通用户。
- 连续登录失败达到上限时锁定一段时间；登录、登出、失败、锁定写日志（不含密码）。
- 会话令牌随机生成，只返回一次；数据库只存其 SHA-256。停用账号、重置密码时删除该账号的全部会话。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select

from lmesh.core import store
from lmesh.core.store.models import User, UserSession, iso

ROLES = ("admin", "user")
MIN_PASSWORD = 8
MAX_PASSWORD = 256
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")
# scrypt 参数：N=2^14、r=8、p=1，约 16 MB 内存
_N, _R, _P, _DKLEN = 2**14, 8, 1, 32

_log = logging.getLogger("lmesh.auth")


class UserError(Exception):
    """账号操作失败。kind：param 参数不合格 / not_found 不存在 / state 当前状态不允许。key 是文案键。"""

    def __init__(self, kind: str, key: str, **fmt: Any):
        super().__init__(key)
        self.kind, self.key, self.fmt = kind, key, fmt


class AuthError(Exception):
    """登录失败。reason：invalid 用户名或密码不对 / locked 已锁定 / disabled 已停用。"""

    def __init__(self, reason: str, locked_until: datetime | None = None):
        super().__init__(reason)
        self.reason, self.locked_until = reason, locked_until


# ---------- 密码与令牌 ----------


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    b64 = base64.b64encode
    return f"scrypt${_N}${_R}${_P}${b64(salt).decode()}${b64(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        want = base64.b64decode(dk_b64)
        got = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(want),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, want)


_DUMMY_HASH: str | None = None


def _burn(password: str) -> None:
    """用户不存在时也算一次哈希，让响应时间不暴露用户名是否存在。"""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_urlsafe(12))
    verify_password(password, _DUMMY_HASH)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_username(name: str) -> str:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise UserError("param", "users.invalid_name")
    return name


def validate_password(password: str) -> str:
    if len(password or "") < MIN_PASSWORD:
        raise UserError("param", "users.password_short")
    if len(password) > MAX_PASSWORD:
        raise UserError("param", "users.password_long")
    return password


def validate_role(role: str) -> str:
    if role not in ROLES:
        raise UserError("param", "users.invalid_role")
    return role


# ---------- 时间 ----------


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite 读回来的时间不带时区，按 UTC 补上。"""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _locked(u: User, now: datetime) -> bool:
    until = _aware(u.locked_until)
    return until is not None and until > now


def to_dict(u: User) -> dict[str, Any]:
    now = _now()
    locked = _locked(u, now)
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "disabled": bool(u.disabled),
        "locked": locked,
        "locked_until": iso(u.locked_until) if locked else None,
        "last_login_at": iso(u.last_login_at),
        "password_changed_at": iso(u.password_changed_at),
        "created_at": iso(u.created_at),
    }


# ---------- 账号 ----------


def _get(s: Any, username: str) -> User:
    u = s.scalar(select(User).where(User.username == username))
    if u is None:
        raise UserError("not_found", "users.not_found", name=username)
    return u


def count(url: str) -> int:
    with store.session(url) as s:
        return int(s.scalar(select(func.count()).select_from(User)) or 0)


def list_users(url: str) -> list[dict[str, Any]]:
    with store.session(url) as s:
        return [to_dict(u) for u in s.scalars(select(User).order_by(User.username))]


def get_user(url: str, username: str) -> dict[str, Any]:
    with store.session(url) as s:
        return to_dict(_get(s, username))


def create_user(url: str, username: str, password: str, role: str = "user") -> dict[str, Any]:
    username = validate_username(username)
    validate_password(password)
    validate_role(role)
    with store.session(url) as s:
        if s.scalar(select(User).where(func.lower(User.username) == username.lower())) is not None:
            raise UserError("state", "users.exists", name=username)
        u = User(username=username, role=role, disabled=False, password_hash=hash_password(password), failed_count=0)
        s.add(u)
        s.flush()
        _log.info("账号已创建：%s（%s）", username, role)
        return to_dict(u)


def _other_enabled_admins(s: Any, u: User) -> int:
    q = select(func.count()).select_from(User).where(User.role == "admin", User.disabled.is_(False), User.id != u.id)
    return int(s.scalar(q) or 0)


def _guard_last_admin(s: Any, u: User) -> None:
    if u.role == "admin" and not u.disabled and _other_enabled_admins(s, u) == 0:
        raise UserError("state", "users.last_admin")


def _close_sessions(s: Any, user_id: int, keep_hash: str | None = None) -> int:
    q = delete(UserSession).where(UserSession.user_id == user_id)
    if keep_hash:
        q = q.where(UserSession.token_hash != keep_hash)
    return int(s.execute(q).rowcount or 0)  # type: ignore[attr-defined]


def update_user(
    url: str,
    username: str,
    *,
    role: str | None = None,
    disabled: bool | None = None,
    unlock: bool = False,
) -> dict[str, Any]:
    """改角色、停用 / 启用、解除锁定。停用时该账号的会话立即失效。"""
    if role is not None:
        validate_role(role)
    with store.session(url) as s:
        u = _get(s, username)
        if (role == "user" and u.role == "admin") or (disabled is True and not u.disabled):
            _guard_last_admin(s, u)
        if role is not None and role != u.role:
            _log.info("账号角色修改：%s %s → %s", u.username, u.role, role)
            u.role = role
        if disabled is not None and disabled != u.disabled:
            u.disabled = disabled
            if disabled:
                _close_sessions(s, u.id)
            _log.info("账号%s：%s", "已停用" if disabled else "已启用", u.username)
        if unlock:
            u.failed_count, u.locked_until = 0, None
            _log.info("账号已解除锁定：%s", u.username)
        s.flush()
        return to_dict(u)


def reset_password(url: str, username: str, password: str) -> dict[str, Any]:
    """管理员重置密码：同时解除锁定，并让该账号已登录的会话全部失效。"""
    validate_password(password)
    with store.session(url) as s:
        u = _get(s, username)
        u.password_hash = hash_password(password)
        u.password_changed_at = _now()
        u.failed_count, u.locked_until = 0, None
        closed = _close_sessions(s, u.id)
        _log.info("账号密码已重置：%s（结束会话 %d 个）", u.username, closed)
        return {**to_dict(u), "sessions_closed": closed}


def delete_user(url: str, username: str) -> dict[str, Any]:
    with store.session(url) as s:
        u = _get(s, username)
        _guard_last_admin(s, u)
        _close_sessions(s, u.id)
        s.delete(u)
        _log.info("账号已删除：%s", username)
        return {"deleted": username}


def change_password(url: str, user_id: int, old: str, new: str, keep_token: str | None = None) -> dict[str, Any]:
    """用户自己改密码：核对旧密码；除当前会话外，其他会话全部失效。"""
    validate_password(new)
    with store.session(url) as s:
        u = s.get(User, user_id)
        if u is None:
            raise UserError("not_found", "users.not_found", name=str(user_id))
        if not verify_password(old, u.password_hash):
            raise UserError("param", "auth.wrong_password")
        if old == new:
            raise UserError("param", "users.password_same")
        u.password_hash = hash_password(new)
        u.password_changed_at = _now()
        closed = _close_sessions(s, u.id, token_hash(keep_token) if keep_token else None)
        _log.info("用户修改了密码：%s（结束其他会话 %d 个）", u.username, closed)
        return {"changed": True, "sessions_closed": closed}


# ---------- 登录与会话 ----------


def authenticate(
    url: str, username: str, password: str, max_failures: int = 5, lock_minutes: int = 15, client: str = ""
) -> dict[str, Any]:
    """核对用户名与密码。失败计数达到上限时锁定 lock_minutes 分钟。成功返回账号信息。"""
    now = _now()
    where = f" [{client}]" if client else ""
    with store.session(url) as s:
        u = s.scalar(select(User).where(User.username == (username or "").strip()))
        if u is None:
            _burn(password or "")
            _log.warning("登录失败：用户名不存在%s", where)  # 不记录输入的用户名（可能误填了密码）
            raise AuthError("invalid")
        if _locked(u, now):
            _log.warning("登录被拒：账号锁定中 %s%s", u.username, where)
            raise AuthError("locked", _aware(u.locked_until))
        if not verify_password(password or "", u.password_hash):
            u.failed_count = (u.failed_count or 0) + 1
            if u.failed_count >= max_failures:
                u.locked_until = now + timedelta(minutes=lock_minutes)
                u.failed_count = 0
                _log.warning(
                    "账号已锁定 %d 分钟：%s 连续 %d 次密码错误%s", lock_minutes, u.username, max_failures, where
                )
                s.commit()
                raise AuthError("locked", u.locked_until)
            _log.warning("登录失败：密码错误 %s（第 %d 次）%s", u.username, u.failed_count, where)
            s.commit()
            raise AuthError("invalid")
        if u.disabled:
            _log.warning("登录被拒：账号已停用 %s%s", u.username, where)
            raise AuthError("disabled")
        u.failed_count, u.locked_until, u.last_login_at = 0, None, now
        _log.info("登录成功：%s%s", u.username, where)
        return to_dict(u)


def create_session(url: str, user_id: int, hours: int) -> tuple[str, datetime]:
    """新建会话，返回（令牌明文，过期时间）。令牌明文只在这里出现一次。顺便清理过期会话。"""
    token = secrets.token_urlsafe(32)
    now = _now()
    expires = now + timedelta(hours=hours)
    with store.session(url) as s:
        s.execute(delete(UserSession).where(UserSession.expires_at < now))
        s.add(UserSession(user_id=user_id, token_hash=token_hash(token), created_at=now, expires_at=expires))
    return token, expires


def session_user(url: str, token: str) -> dict[str, Any] | None:
    """按会话令牌找到账号；过期、账号停用或不存在时返回 None。"""
    if not token:
        return None
    with store.session(url) as s:
        row = s.scalar(select(UserSession).where(UserSession.token_hash == token_hash(token)))
        if row is None:
            return None
        if (_aware(row.expires_at) or _now()) <= _now():
            s.delete(row)
            return None
        u = s.get(User, row.user_id)
        if u is None or u.disabled:
            return None
        return {**to_dict(u), "session_expires_at": iso(row.expires_at)}


def end_session(url: str, token: str) -> str | None:
    """登出：删除会话，返回账号名（没有这个会话时返回 None）。"""
    if not token:
        return None
    with store.session(url) as s:
        row = s.scalar(select(UserSession).where(UserSession.token_hash == token_hash(token)))
        if row is None:
            return None
        u = s.get(User, row.user_id)
        s.delete(row)
        name = u.username if u else None
    if name:
        _log.info("已登出：%s", name)
    return name
