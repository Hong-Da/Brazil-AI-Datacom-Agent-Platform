"""个人 API 令牌（REQ-035）。CLI 与 API 共用。

- 每个账号可以生成自己的令牌，调用时权限与本人账号相同（只能访问自己有权限的项目）；可选“只读”（只能读取与计算，
  不能修改）与有效期（默认 90 天，可选不过期，D-0177）。
- 令牌形如 lmp_ + 32 位字母数字，只在创建时返回一次；数据库只存 SHA-256；列表与日志只显示前 8 个字符（D-0179）。
- 记录最后使用时间与地址；撤销后立即失效；账号停用时令牌随之不可用，删除账号时一并删除。
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import string
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from lmesh.core import store
from lmesh.core.store.models import ApiToken, User, iso

PREFIX = "lmp_"
BODY_LEN = 32
SHOW = 8  # 列表与日志显示的前几个字符（含 lmp_）
DEFAULT_DAYS = 90
MAX_DAYS = 3650
MAX_ACTIVE = 50
_ALPHABET = string.ascii_letters + string.digits
_TOUCH_EVERY = timedelta(seconds=60)  # 最后使用时间至多每分钟写一次

_log = logging.getLogger("lmesh.auth")


class TokenError(ValueError):
    def __init__(self, key: str, kind: str = "param", **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.fmt = key, kind, fmt


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def looks_personal(token: str) -> bool:
    return token.startswith(PREFIX)


def _state(t: ApiToken, now: datetime) -> str:
    if t.revoked_at is not None:
        return "revoked"
    exp = _aware(t.expires_at)
    if exp is not None and exp <= now:
        return "expired"
    return "active"


def to_dict(t: ApiToken) -> dict[str, Any]:
    return {
        "id": t.id,
        "name": t.name,
        "prefix": t.prefix,
        "read_only": bool(t.read_only),
        "created_at": iso(t.created_at),
        "expires_at": iso(t.expires_at),
        "last_used_at": iso(t.last_used_at),
        "last_used_ip": t.last_used_ip or None,
        "revoked_at": iso(t.revoked_at),
        "state": _state(t, _now()),
    }


def _user(s: Any, username: str) -> User:
    u = s.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if u is None:
        raise TokenError("tokens.user_not_found", "not_found", name=username)
    return u


def create(
    db_url: str, username: str, name: str, read_only: bool = False, days: int | None = DEFAULT_DAYS
) -> dict[str, Any]:
    """生成令牌；返回的 token 只出现这一次。days 为 None 或 0 表示不过期。"""
    name = (name or "").strip()
    if not name or len(name) > 200:
        raise TokenError("tokens.bad_name")
    if days is not None and (days < 0 or days > MAX_DAYS):
        raise TokenError("tokens.bad_days", max=MAX_DAYS)
    token = PREFIX + "".join(secrets.choice(_ALPHABET) for _ in range(BODY_LEN))
    with store.session(db_url) as s:
        u = _user(s, username)
        active = [
            t for t in s.scalars(select(ApiToken).where(ApiToken.user_id == u.id)) if _state(t, _now()) == "active"
        ]
        if len(active) >= MAX_ACTIVE:
            raise TokenError("tokens.too_many", "state", max=MAX_ACTIVE)
        t = ApiToken(
            user_id=u.id,
            name=name,
            prefix=token[:SHOW],
            token_hash=hash_token(token),
            read_only=read_only,
            expires_at=_now() + timedelta(days=days) if days else None,
            last_used_ip="",
        )
        s.add(t)
        s.flush()
        _log.info("个人令牌已创建：%s %s（%s）", u.username, t.prefix, "只读" if read_only else "读写")
        return {**to_dict(t), "token": token, "owner": u.username}


def list_tokens(db_url: str, username: str) -> list[dict[str, Any]]:
    with store.session(db_url) as s:
        u = _user(s, username)
        rows = s.scalars(select(ApiToken).where(ApiToken.user_id == u.id).order_by(ApiToken.created_at.desc()))
        return [to_dict(t) for t in rows]


def _own(s: Any, username: str, token_id: int) -> ApiToken:
    u = _user(s, username)
    t = s.get(ApiToken, token_id)
    if t is None or t.user_id != u.id:
        raise TokenError("tokens.not_found", "not_found", id=token_id)
    return t


def revoke(db_url: str, username: str, token_id: int) -> dict[str, Any]:
    with store.session(db_url) as s:
        t = _own(s, username, token_id)
        if t.revoked_at is None:
            t.revoked_at = _now()
            _log.info("个人令牌已撤销：%s %s", username, t.prefix)
        return to_dict(t)


def remove(db_url: str, username: str, token_id: int) -> dict[str, Any]:
    """从列表移除：只能移除已撤销或已过期的令牌（有效的先撤销）。"""
    with store.session(db_url) as s:
        t = _own(s, username, token_id)
        if _state(t, _now()) == "active":
            raise TokenError("tokens.still_active", "state", id=token_id)
        s.delete(t)
        return {"id": token_id, "removed": True}


def authenticate(db_url: str, token: str, client: str = "") -> dict[str, Any] | None:
    """校验个人令牌：有效且账号启用时返回 {user_id, username, role, read_only, token_id, prefix}，否则 None。"""
    if not looks_personal(token) or len(token) != len(PREFIX) + BODY_LEN:
        return None
    now = _now()
    with store.session(db_url) as s:
        t = s.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(token)))
        if t is None or _state(t, now) != "active":
            if t is not None:
                _log.info("个人令牌被拒：%s（%s）", t.prefix, _state(t, now))
            return None
        u = s.get(User, t.user_id)
        if u is None or u.disabled:
            return None
        last = _aware(t.last_used_at)
        if last is None or now - last >= _TOUCH_EVERY or (t.last_used_ip or "") != client[:64]:
            t.last_used_at, t.last_used_ip = now, client[:64]
        return {
            "user_id": u.id,
            "username": u.username,
            "role": u.role,
            "read_only": bool(t.read_only),
            "token_id": t.id,
            "prefix": t.prefix,
        }
