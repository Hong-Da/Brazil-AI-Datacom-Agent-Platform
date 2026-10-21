"""用户账号与网页会话（REQ-030）。CLI 与 API 共用。

- 密码只保存 scrypt 哈希（标准库 hashlib.scrypt，随机盐），最短 8 位；不写入日志或任何文件。
- 角色：admin（账号、系统设置、AI 接口、全部项目）、maintainer（知识库维护员：知识库与共享规则 / 模板）与 user。
- 至少保留一个启用的管理员：最后一个启用的管理员不能停用、删除或改成普通用户。
- 连续登录失败达到上限时锁定一段时间；登录、登出、失败、锁定写日志（不含密码）。
- 会话令牌随机生成，只返回一次；数据库只存其 SHA-256。停用账号、重置密码时删除该账号的全部会话。
- 自助注册（REQ-039）：注册的账号为普通用户（origin = register）；需要审核时状态为 pending（待审核，不能登录），
  管理员批准后为 active，拒绝即删除该账号（用户名可以再注册）。同一来源地址的注册频率由 RateLimiter 限制。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import threading
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select

from lmesh.core import store
from lmesh.core.store.models import User, UserSession, iso

ROLES = ("admin", "maintainer", "user")  # maintainer：知识库维护员（M6，REQ-036）
STATUSES = ("active", "pending")  # pending：自助注册后等待管理员审核（REQ-039）
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
    """登录失败。reason：invalid 用户名或密码不对 / locked 已锁定 / disabled 已停用 / pending 待审核（REQ-039）。"""

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
        "status": u.status or "active",
        "origin": u.origin or "admin",
        "locked": locked,
        "locked_until": iso(u.locked_until) if locked else None,
        "last_login_at": iso(u.last_login_at),
        "password_changed_at": iso(u.password_changed_at),
        "created_at": iso(u.created_at),
        "can_create_projects": bool(u.can_create_projects),  # 单独授权创建项目（M9-8，REQ-050）
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


def list_users(url: str, status: str | None = None) -> list[dict[str, Any]]:
    """账号列表；status 给出时只列该状态（pending：待审核）。"""
    with store.session(url) as s:
        q = select(User).order_by(User.username)
        if status:
            q = q.where(User.status == status)
        return [to_dict(u) for u in s.scalars(q)]


def count_pending(url: str) -> int:
    with store.session(url) as s:
        return int(s.scalar(select(func.count()).select_from(User).where(User.status == "pending")) or 0)


def get_user(url: str, username: str) -> dict[str, Any]:
    with store.session(url) as s:
        return to_dict(_get(s, username))


def create_user(
    url: str, username: str, password: str, role: str = "user", *, status: str = "active", origin: str = "admin"
) -> dict[str, Any]:
    username = validate_username(username)
    validate_password(password)
    validate_role(role)
    with store.session(url) as s:
        if s.scalar(select(User).where(func.lower(User.username) == username.lower())) is not None:
            raise UserError("state", "users.exists", name=username)
        u = User(
            username=username,
            role=role,
            disabled=False,
            status=status,
            origin=origin,
            password_hash=hash_password(password),
            failed_count=0,
        )
        s.add(u)
        s.flush()
        _log.info("账号已创建：%s（%s，%s）", username, role, status)
        out = to_dict(u)
    from lmesh.core import projects

    projects.on_user_created(url, out["id"])
    return out


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
        if (role is not None and role != "admin" and u.role == "admin") or (disabled is True and not u.disabled):
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


def delete_user(
    url: str, username: str, transfer_to: str | None = None, delete_projects: bool = False, actor: Any = None
) -> dict[str, Any]:
    """删除账号。拥有项目时必须选择：transfer_to 全部转交给另一个账号（私有模板与规则集一并转交），
    或 delete_projects 一并删除（私有模板与规则集也删除）；都没给时拒绝（data.projects 列出项目）。"""
    from lmesh.core import assets, projects

    with store.session(url) as s:
        u = _get(s, username)
        _guard_last_admin(s, u)
        target = _get(s, transfer_to) if transfer_to else None
        if target is not None and (target.id == u.id or target.disabled):
            raise UserError("state", "users.bad_transfer_target", name=transfer_to)
        uid, target_id = u.id, (target.id if target else None)
    owned = projects.owned_projects(url, username, non_empty_only=True)
    if owned and target_id is None and not delete_projects:
        raise UserError("state", "users.has_projects", n=len(owned), projects=", ".join(p["slug"] for p in owned))
    ident = actor or projects.SYSTEM
    handled = projects.dispose_user_projects(url, username, transfer_to if target_id else None, ident)
    moved = assets.dispose_user(url, uid, target_id)
    with store.session(url) as s:
        u = _get(s, username)
        _close_sessions(s, u.id)
        s.delete(u)
        _log.info("账号已删除：%s", username)
    return {"deleted": username, "projects": handled, "assets": moved}


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
        if (u.status or "active") == "pending":  # 密码正确才提示待审核，不暴露账号是否存在
            _log.info("登录被拒：账号待审核 %s%s", u.username, where)
            raise AuthError("pending")
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
        if u is None or u.disabled or (u.status or "active") != "active":
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


# ---------- 自助注册（REQ-039） ----------


class RateLimiter:
    """按来源地址的滑动窗口计数（进程内；重启后清零）。limit 次 / window 秒。"""

    def __init__(self, window: float = 3600.0):
        self.window = window
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int) -> bool:
        """记一次尝试；超过 limit 时返回 False（被拒的尝试不计入）。"""
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


REGISTER_LIMITER = RateLimiter()


def register(url: str, username: str, password: str, approval: bool) -> dict[str, Any]:
    """自助注册：普通用户；approval 为真时待审核（不能登录），否则直接可用（能创建项目时建好默认项目）。"""
    u = create_user(url, username, password, "user", status="pending" if approval else "active", origin="register")
    if not approval:
        _provision(url, u)
    _log.info("自助注册：%s（%s）", u["username"], u["status"])
    return u


def _provision(url: str, u: dict[str, Any]) -> None:
    """新账号可以使用时：建工作空间与默认项目（REQ-035）；不能创建项目的账号不建（M9-8，REQ-050）。"""
    from lmesh.core import projects

    projects.default_project_or_none(url, projects.Identity(u["id"], u["username"], u["role"]))


def approve(url: str, username: str) -> dict[str, Any]:
    """批准待审核账号：可以登录，并建好默认项目。"""
    with store.session(url) as s:
        u = _get(s, username)
        if (u.status or "active") != "pending":
            raise UserError("state", "users.not_pending", name=username)
        u.status = "active"
        s.flush()
        out = to_dict(u)
    _provision(url, out)
    _log.info("已批准注册：%s", username)
    return out


def reject(url: str, username: str) -> dict[str, Any]:
    """拒绝待审核账号：删除它（用户名可以再注册）；只能拒绝待审核的账号。"""
    with store.session(url) as s:
        u = _get(s, username)
        if (u.status or "active") != "pending":
            raise UserError("state", "users.not_pending", name=username)
        _close_sessions(s, u.id)
        s.delete(u)
    _log.info("已拒绝注册并删除账号：%s", username)
    return {"rejected": username, "deleted": True}


# ---------- 个人偏好（REQ-047） ----------

# 每项偏好的可选值；网页登录后以账号保存的值为准，没有保存过时由网页把浏览器本地的值写入
PREF_CHOICES: dict[str, tuple[str, ...]] = {
    "lang": ("zh-CN", "en", "pt-BR"),
    "theme": ("auto", "light", "dark"),
    "term_style": ("huawei", "cisco", "nokia"),
    "icon_set": ("cyl", "geo", "line"),
    "ask_intro": ("open", "folded"),  # AI 查询页顶部的接口信息与说明（REQ-051）
}


def get_prefs(url: str, user_id: int) -> dict[str, str] | None:
    """账号保存的偏好；None 表示还没保存过。"""
    with store.session(url) as s:
        u = s.get(User, user_id)
        if u is None:
            raise UserError("not_found", "users.not_found", name=str(user_id))
        return _clean_prefs(u.prefs) if u.prefs else None


def save_prefs(url: str, user_id: int, data: dict[str, Any]) -> dict[str, str]:
    """合并保存偏好（只改给出的项）；值不合格时抛 UserError（prefs.invalid）。返回保存后的全部偏好。"""
    for k, v in data.items():
        if k not in PREF_CHOICES:
            raise UserError("param", "prefs.unknown", name=k)
        if v not in PREF_CHOICES[k]:
            raise UserError("param", "prefs.invalid", name=k, allowed=" / ".join(PREF_CHOICES[k]))
    with store.session(url) as s:
        u = s.get(User, user_id)
        if u is None:
            raise UserError("not_found", "users.not_found", name=str(user_id))
        merged = {**_clean_prefs(u.prefs), **{k: str(v) for k, v in data.items()}}
        u.prefs = merged
        return merged


def clear_prefs(url: str, user_id: int) -> None:
    """清除账号保存的偏好（恢复为“没保存过”：下次登录时网页把浏览器本地的值写入账号）。"""
    with store.session(url) as s:
        u = s.get(User, user_id)
        if u is None:
            raise UserError("not_found", "users.not_found", name=str(user_id))
        u.prefs = None


def _clean_prefs(raw: Any) -> dict[str, str]:
    """数据库里的偏好只保留认识且合格的项（以后删掉的选项不影响读取）。"""
    if not isinstance(raw, dict):
        return {}
    return {k: str(v) for k, v in raw.items() if k in PREF_CHOICES and v in PREF_CHOICES[k]}
