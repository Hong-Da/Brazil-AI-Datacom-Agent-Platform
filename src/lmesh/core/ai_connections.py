"""AI 接口：公共与个人（REQ-040）。

- 管理员接口（owner_id 为空）：可以有多个，各有“允许公共使用”（public）与启用（enabled）开关。
- 个人接口：每个账号最多一个，只有本人能看到与修改（管理员也看不到），只用于本人发起的请求（含本人发起的后台任务）。
- 账号的选择：auto（默认）/ connection（某个管理员接口）/ personal / none。
- resolve() 是“当前请求用哪个接口”的唯一入口（规则见函数说明）；ai.complete / is_configured / model_for 都经过它。
- API Key 用 config.encrypt_secret 加密保存；任何返回值、日志、导出只给 api_key_set。
- 升级兼容：配置文件里的 [ai]（provider、base_url、api_key、model*）是第一个管理员接口的初始值——第一次用到时
  若还没有导入过（app_meta 的 ai.seeded），且填写完整，就导入为名为 default 的管理员接口（public = true，
  保持升级前所有账号都能用 AI）；之后以数据库为准。ai.timeout / ai.max_tokens 仍是全局配置。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, select

from lmesh.core import config, store
from lmesh.core.store.models import AICall, AIChoice, AIConnection, AppMeta, User, iso

PROVIDERS = ("anthropic", "openai", "local")
MODEL_FIELDS = ("model", "model_extract", "model_merge", "model_ask", "model_generate")
CHOICES = ("auto", "connection", "personal", "none")
SEED_KEY = "ai.seeded"
SEED_NAME = "default"
PERSONAL_NAME = "personal"
# 未配置的原因（界面据此提示）
REASONS = ("no_connection", "no_public", "public_closed", "personal_missing", "disabled_by_user")


class ConnError(ValueError):
    """kind：param（422 / 退出码 2）、not_found（404 / 4）、state（409 / 1）。"""

    def __init__(self, key: str, kind: str = "param", data: Any = None, **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.data, self.fmt = key, kind, data, fmt


@dataclass(frozen=True)
class Conn:
    """解析出的可用接口（不含明文 Key；调用时才解密）。"""

    id: int | None
    name: str
    provider: str
    base_url: str
    api_key_enc: str
    models: dict[str, str]
    public: bool = False
    personal: bool = False

    def api_key(self) -> str:
        return config.decrypt_secret(self.api_key_enc)

    def model_for(self, task: str) -> str:
        return self.models.get(f"model_{task}") or self.models.get("model", "")


@dataclass(frozen=True)
class Resolution:
    conn: Conn | None
    source: str | None  # connection / personal
    choice: str  # auto / connection / personal / none；没有账号时为 system
    reason: str | None
    user_id: int | None
    username: str

    @property
    def configured(self) -> bool:
        return self.conn is not None

    def public_dict(self) -> dict[str, Any]:
        c = self.conn
        return {
            "configured": c is not None,
            "source": self.source,
            "choice": self.choice,
            "connection": {"id": c.id, "name": c.name, "public": c.public} if c and not c.personal else None,
            "provider": c.provider if c else None,
            "model": c.models.get("model") if c else None,
            "reason": self.reason,
        }


# ---------------------------------------------------------------- 校验与转换


def complete(provider: str, base_url: str, api_key: str, model: str) -> bool:
    """填写完整：anthropic 需要 Key 与模型；OpenAI 兼容与本地模型需要地址与模型。"""
    if provider not in PROVIDERS or not model:
        return False
    return bool(api_key) if provider == "anthropic" else bool(base_url)


def _complete_row(c: AIConnection) -> bool:
    return complete(c.provider, c.base_url, c.api_key, c.model)


def _conn(c: AIConnection) -> Conn:
    return Conn(
        c.id,
        PERSONAL_NAME if c.owner_id is not None else c.name,
        c.provider,
        c.base_url,
        c.api_key,
        {k: getattr(c, k) or "" for k in MODEL_FIELDS},
        bool(c.public),
        c.owner_id is not None,
    )


def _clean_fields(data: dict[str, Any], current: AIConnection | None) -> dict[str, Any]:
    """校验并整理要写入的字段（provider、base_url、api_key、模型）。"""
    out: dict[str, Any] = {}
    if "provider" in data and data["provider"] is not None:
        p = str(data["provider"]).strip()
        if p not in PROVIDERS:
            raise ConnError("ai.conn.bad_provider", data={"error": f"provider: {' / '.join(PROVIDERS)}"}, v=p)
        out["provider"] = p
    if "base_url" in data and data["base_url"] is not None:
        url = str(data["base_url"]).strip()
        if url and not url.lower().startswith(("http://", "https://")):
            raise ConnError("ai.conn.bad_url", data={"error": "base_url: http(s)://…"})
        out["base_url"] = url[:500]
    for k in MODEL_FIELDS:
        if k in data and data[k] is not None:
            out[k] = str(data[k]).strip()[:120]
    if data.get("clear_api_key"):
        out["api_key"] = ""
    if data.get("api_key"):
        out["api_key"] = config.encrypt_secret(str(data["api_key"]).strip())
    merged = {
        k: out.get(k, getattr(current, k) if current is not None else "")
        for k in ("provider", "base_url", "api_key", "model")
    }
    if not complete(merged["provider"] or "", merged["base_url"] or "", merged["api_key"] or "", merged["model"] or ""):
        need = "api_key" if merged["provider"] == "anthropic" else "base_url"
        raise ConnError("ai.conn.incomplete", data={"error": f"provider, model, {need}"})
    return out


def _clean_name(name: Any) -> str:
    n = str(name or "").strip()
    if not 1 <= len(n) <= 64 or n.lower() == PERSONAL_NAME:
        raise ConnError("ai.conn.bad_name", data={"error": "name: 1–64, not 'personal'"})
    return n


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------- 升级导入


_SEEDED: set[str] = set()
_SEED_LOCK = threading.Lock()


def ensure_seeded(settings: config.Settings) -> None:
    """把配置文件里的 [ai] 导入为第一个管理员接口（只做一次；没填写完整时不导入、下次再看）。"""
    db = settings.database_url
    if db in _SEEDED:
        return
    store.upgrade(db)
    with _SEED_LOCK, store.session(db) as s:
        if s.get(AppMeta, SEED_KEY) is not None:
            _SEEDED.add(db)
            return
        has_admin = s.scalar(select(func.count()).select_from(AIConnection).where(AIConnection.owner_id.is_(None)))
        if has_admin:  # 管理员已经建过接口：不再导入
            s.add(AppMeta(key=SEED_KEY, value="skip"))
            _SEEDED.add(db)
            return
        v = settings.values
        provider = str(v.get("ai.provider") or "")
        key = str(v.get("ai.api_key") or "")
        if not complete(provider, str(v.get("ai.base_url") or ""), key, str(v.get("ai.model") or "")):
            return
        s.add(
            AIConnection(
                name=SEED_NAME,
                provider=provider,
                base_url=str(v.get("ai.base_url") or ""),
                api_key=config.encrypt_secret(key),
                public=True,
                enabled=True,
                **{k: str(v.get(f"ai.{k}") or "") for k in MODEL_FIELDS},
            )
        )
        s.add(AppMeta(key=SEED_KEY, value="config"))
    _SEEDED.add(db)


def _mark_seeded(s: Any) -> None:
    if s.get(AppMeta, SEED_KEY) is None:
        s.add(AppMeta(key=SEED_KEY, value="manual"))


# ---------------------------------------------------------------- 解析


def _usable_admin(s: Any, public_only: bool) -> AIConnection | None:
    q = select(AIConnection).where(AIConnection.owner_id.is_(None), AIConnection.enabled.is_(True))
    if public_only:
        q = q.where(AIConnection.public.is_(True))
    for c in s.scalars(q.order_by(AIConnection.id)):
        if _complete_row(c):
            return c  # type: ignore[no-any-return]
    return None


def resolve(settings: config.Settings, actor: Any = None) -> Resolution:
    """当前请求用哪个 AI 接口。actor（projects.Identity）默认取 settings.actor，再取命令行的 --as 账号。

    - 没有账号（全局 API 令牌、没有账号的命令行）：第一个可用的管理员接口。
    - auto：管理员账号用第一个可用的管理员接口；其他账号用第一个可用且允许公共使用的管理员接口。
      找不到时 reason = no_connection（管理员）/ no_public（其他账号）。
    - connection：该接口存在、启用、填写完整，且允许公共使用（管理员不受此限）；否则 public_closed（提示改选，不自动换）。
    - personal：个人接口填写完整；否则 personal_missing。none：disabled_by_user。
    可用 = 启用且填写完整。
    """
    who = actor if actor is not None else (settings.actor if settings.actor is not None else cli_actor())
    ensure_seeded(settings)
    uid = getattr(who, "user_id", None)
    name = str(getattr(who, "username", "") or "")
    is_admin = who is None or getattr(who, "role", "admin") == "admin"
    with store.session(settings.database_url) as s:
        if uid is None:
            c = _usable_admin(s, False)
            return Resolution(
                _conn(c) if c else None,
                "connection" if c else None,
                "system",
                None if c else "no_connection",
                None,
                name,
            )
        ch = s.get(AIChoice, uid)
        choice = ch.choice if ch is not None else "auto"
        if choice == "none":
            return Resolution(None, None, choice, "disabled_by_user", uid, name)
        if choice == "personal":
            p = s.scalar(select(AIConnection).where(AIConnection.owner_id == uid))
            ok = p is not None and p.enabled and _complete_row(p)
            return Resolution(
                _conn(p) if ok and p else None,
                "personal" if ok else None,
                choice,
                None if ok else "personal_missing",
                uid,
                name,
            )
        if choice == "connection":
            c = s.get(AIConnection, ch.connection_id) if ch is not None and ch.connection_id else None
            ok = c is not None and c.owner_id is None and c.enabled and _complete_row(c) and (c.public or is_admin)
            return Resolution(
                _conn(c) if ok and c else None,
                "connection" if ok else None,
                choice,
                None if ok else "public_closed",
                uid,
                name,
            )
        c = _usable_admin(s, not is_admin)
        reason = None if c else ("no_connection" if is_admin else "no_public")
        return Resolution(_conn(c) if c else None, "connection" if c else None, "auto", reason, uid, name)


# 命令行：--as 账号（不给时第一个管理员；还没有账号时为空），由 cli 在启动时设置为延迟函数
_cli_actor_fn: Any = None


def set_cli_actor(fn: Any) -> None:
    global _cli_actor_fn
    _cli_actor_fn = fn


def cli_actor() -> Any:
    fn = _cli_actor_fn
    if fn is None:
        return None
    try:
        return fn()
    except Exception:  # noqa: BLE001 数据库不可用时按系统自身
        return None


# ---------------------------------------------------------------- 管理员接口


def _usage_by_conn(s: Any, since: datetime) -> dict[int, dict[str, int]]:
    q = (
        select(
            AICall.connection_id,
            func.count(),
            func.sum(func.coalesce(AICall.tokens_in, 0)),
            func.sum(func.coalesce(AICall.tokens_out, 0)),
            func.sum(case((AICall.status != "ok", 1), else_=0)),
        )
        .where(AICall.created_at >= since, AICall.connection_id.is_not(None), AICall.source == "connection")
        .group_by(AICall.connection_id)
    )
    return {
        r[0]: {
            "calls": int(r[1] or 0),
            "tokens_in": int(r[2] or 0),
            "tokens_out": int(r[3] or 0),
            "errors": int(r[4] or 0),
        }
        for r in s.execute(q)
    }


def month_start() -> datetime:
    n = _now()
    return datetime(n.year, n.month, 1, tzinfo=UTC)


def _admin_dict(
    c: AIConnection, default_id: int | None, chosen: dict[int, int], usage: dict[int, dict[str, int]]
) -> dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "provider": c.provider,
        "base_url": c.base_url,
        "api_key_set": bool(c.api_key),
        **{k: getattr(c, k) or "" for k in MODEL_FIELDS},
        "public": bool(c.public),
        "enabled": bool(c.enabled),
        "complete": _complete_row(c),
        "is_default": c.id == default_id,
        "chosen_by": chosen.get(c.id, 0),
        "usage": usage.get(c.id, {"calls": 0, "errors": 0, "tokens_in": 0, "tokens_out": 0}),
        "created_at": iso(c.created_at),
        "updated_at": iso(c.updated_at),
    }


def _admin_rows(s: Any, only: int | None = None) -> list[dict[str, Any]]:
    d = _usable_admin(s, False)
    chosen = dict(
        s.execute(
            select(AIChoice.connection_id, func.count())
            .where(AIChoice.choice == "connection", AIChoice.connection_id.is_not(None))
            .group_by(AIChoice.connection_id)
        ).all()
    )
    usage = _usage_by_conn(s, month_start())
    q = select(AIConnection).where(AIConnection.owner_id.is_(None))
    if only is not None:
        q = q.where(AIConnection.id == only)
    return [_admin_dict(c, d.id if d else None, chosen, usage) for c in s.scalars(q.order_by(AIConnection.id))]


def list_connections(settings: config.Settings) -> dict[str, Any]:
    ensure_seeded(settings)
    with store.session(settings.database_url) as s:
        rows = _admin_rows(s)
    return {
        "connections": rows,
        "limits": {"timeout": settings.get("ai.timeout"), "max_tokens": settings.get("ai.max_tokens")},
    }


def _admin_row(s: Any, cid: int) -> AIConnection:
    c = s.get(AIConnection, cid)
    if c is None or c.owner_id is not None:  # 个人接口对管理员也不可见
        raise ConnError("ai.conn.not_found", "not_found", id=cid)
    return c  # type: ignore[no-any-return]


def get_connection(settings: config.Settings, cid: int) -> dict[str, Any]:
    ensure_seeded(settings)
    with store.session(settings.database_url) as s:
        _admin_row(s, cid)
        return _admin_rows(s, cid)[0]


def _name_taken(s: Any, name: str, except_id: int | None = None) -> bool:
    q = select(AIConnection.id).where(AIConnection.owner_id.is_(None), func.lower(AIConnection.name) == name.lower())
    return any(i != except_id for i in s.scalars(q))


def create_connection(settings: config.Settings, data: dict[str, Any]) -> dict[str, Any]:
    ensure_seeded(settings)
    name = _clean_name(data.get("name"))
    fields = _clean_fields(data, None)
    with store.session(settings.database_url) as s:
        if _name_taken(s, name):
            raise ConnError("ai.conn.name_taken", "state", name=name)
        c = AIConnection(
            name=name,
            public=bool(data.get("public", False)),
            enabled=bool(data.get("enabled", True)),
            **{**{k: "" for k in ("base_url", "api_key", *MODEL_FIELDS)}, **fields},
        )
        s.add(c)
        _mark_seeded(s)
        s.flush()
        cid = c.id
    return get_connection(settings, cid)


def update_connection(settings: config.Settings, cid: int, data: dict[str, Any]) -> dict[str, Any]:
    with store.session(settings.database_url) as s:
        c = _admin_row(s, cid)
        fields = _clean_fields(data, c)
        if data.get("name") is not None:
            name = _clean_name(data["name"])
            if _name_taken(s, name, cid):
                raise ConnError("ai.conn.name_taken", "state", name=name)
            c.name = name
        for k, v in fields.items():
            setattr(c, k, v)
        for k in ("public", "enabled"):
            if data.get(k) is not None:
                setattr(c, k, bool(data[k]))
        c.updated_at = _now()
    return get_connection(settings, cid)


def delete_connection(settings: config.Settings, cid: int) -> dict[str, Any]:
    with store.session(settings.database_url) as s:
        c = _admin_row(s, cid)
        affected = list(
            s.scalars(select(AIChoice).where(AIChoice.choice == "connection", AIChoice.connection_id == cid))
        )
        for ch in affected:  # 不依赖数据库外键：选了它的账号保留“connection”，解析时提示改选
            ch.connection_id = None
        s.flush()
        s.delete(c)
        _mark_seeded(s)
    return {"deleted": cid, "affected_users": len(affected)}


def find_admin(settings: config.Settings, ref: str) -> int:
    """命令行用：按编号或名称找管理员接口。"""
    ensure_seeded(settings)
    with store.session(settings.database_url) as s:
        if ref.isdigit():
            c = s.get(AIConnection, int(ref))
            if c is not None and c.owner_id is None:
                return c.id  # type: ignore[no-any-return]
        cid = s.scalar(
            select(AIConnection.id).where(AIConnection.owner_id.is_(None), func.lower(AIConnection.name) == ref.lower())
        )
        if cid is None:
            raise ConnError("ai.conn.not_found", "not_found", id=ref)
        return cid  # type: ignore[no-any-return]


def admin_conn(settings: config.Settings, cid: int) -> Conn:
    with store.session(settings.database_url) as s:
        return _conn(_admin_row(s, cid))


def first_admin_id(settings: config.Settings) -> int | None:
    """旧接口 /ai/settings 对应的第一个管理员接口（不论是否启用）。"""
    ensure_seeded(settings)
    with store.session(settings.database_url) as s:
        return s.scalar(
            select(AIConnection.id).where(AIConnection.owner_id.is_(None)).order_by(AIConnection.id).limit(1)
        )


# ---------------------------------------------------------------- 本人的选择与个人接口


def _personal_dict(p: AIConnection | None) -> dict[str, Any] | None:
    if p is None:
        return None
    return {
        "provider": p.provider,
        "base_url": p.base_url,
        "api_key_set": bool(p.api_key),
        **{k: getattr(p, k) or "" for k in MODEL_FIELDS},
        "complete": _complete_row(p),
        "updated_at": iso(p.updated_at),
    }


def _chosen_name(s: Any, ch: AIChoice | None) -> str | None:
    if ch is None or ch.choice != "connection" or not ch.connection_id:
        return None
    c = s.get(AIConnection, ch.connection_id)
    return c.name if c is not None and c.owner_id is None else None


def mine(settings: config.Settings, actor: Any) -> dict[str, Any]:
    """本人的 AI：选择、个人接口（不含 Key）、可选的管理员接口、生效来源。没有账号时只有生效来源。"""
    ensure_seeded(settings)
    uid = getattr(actor, "user_id", None)
    is_admin = actor is None or getattr(actor, "role", "admin") == "admin"
    with store.session(settings.database_url) as s:
        q = select(AIConnection).where(AIConnection.owner_id.is_(None), AIConnection.enabled.is_(True))
        if not is_admin:
            q = q.where(AIConnection.public.is_(True))
        options = [
            {"id": c.id, "name": c.name, "provider": c.provider, "model": c.model, "public": bool(c.public)}
            for c in s.scalars(q.order_by(AIConnection.id))
            if _complete_row(c)
        ]
        ch = s.get(AIChoice, uid) if uid is not None else None
        p = s.scalar(select(AIConnection).where(AIConnection.owner_id == uid)) if uid is not None else None
        out = {
            "choice": (ch.choice if ch else "auto") if uid is not None else "system",
            "connection_id": ch.connection_id if ch else None,
            # 所选管理员接口的名称（接口被关闭公共使用或停用后仍能告诉用户是哪一个；删除后为空）
            "chosen_name": _chosen_name(s, ch),
            "personal": _personal_dict(p),
            "options": options,
            "is_admin": is_admin,
            "has_account": uid is not None,
            "no_token_warn": bool(ch.no_token_warn) if ch else False,
        }
    out["effective"] = resolve(settings, actor if actor is not None else _NO_ACTOR).public_dict()
    return out


class _NoActor:
    """mine(settings, None)：按“没有账号”解析（不要回退到命令行的 --as）。"""

    user_id = None
    username = ""
    role = "admin"


_NO_ACTOR = _NoActor()


def save_mine(settings: config.Settings, actor: Any, data: dict[str, Any]) -> dict[str, Any]:
    uid = getattr(actor, "user_id", None)
    if uid is None:
        raise ConnError("ai.need_account", "state")
    ensure_seeded(settings)
    is_admin = getattr(actor, "role", "user") == "admin"
    with store.session(settings.database_url) as s:
        if s.get(User, uid) is None:
            raise ConnError("ai.need_account", "state")
        p = s.scalar(select(AIConnection).where(AIConnection.owner_id == uid))
        if data.get("remove_personal") and p is not None:
            s.delete(p)
            s.flush()
            p = None
        if data.get("personal"):
            fields = _clean_fields(data["personal"], p)
            if p is None:
                p = AIConnection(
                    name=PERSONAL_NAME,
                    owner_id=uid,
                    public=False,
                    enabled=True,
                    **{k: "" for k in ("provider", "base_url", "api_key", *MODEL_FIELDS)},
                )
                s.add(p)
            for k, v in fields.items():
                setattr(p, k, v)
            p.updated_at = _now()
        choice = data.get("choice")
        if choice is not None:
            if choice not in CHOICES:
                raise ConnError("ai.bad_choice", data={"error": f"choice: {' / '.join(CHOICES)}"})
            cid = None
            if choice == "connection":
                cid = data.get("connection_id")
                c = s.get(AIConnection, int(cid)) if cid is not None else None
                if (
                    c is None
                    or c.owner_id is not None
                    or not c.enabled
                    or not _complete_row(c)
                    or not (c.public or is_admin)
                ):
                    raise ConnError("ai.conn.not_available", data={"error": "connection_id"})
            if choice == "personal" and (p is None or not _complete_row(p)):
                raise ConnError("ai.personal_missing", data={"error": "personal"})
            ch = s.get(AIChoice, uid)
            if ch is None:
                ch = AIChoice(user_id=uid)
                s.add(ch)
            ch.choice, ch.connection_id, ch.updated_at = choice, cid, _now()
        elif data.get("remove_personal"):  # 删掉个人接口时，选了个人接口的改回自动
            ch = s.get(AIChoice, uid)
            if ch is not None and ch.choice == "personal":
                ch.choice, ch.connection_id = "auto", None
        if data.get("no_token_warn") is not None:  # 个人偏好：不提示大请求
            ch = s.get(AIChoice, uid)
            if ch is None:
                ch = AIChoice(user_id=uid, choice="auto")
                s.add(ch)
            ch.no_token_warn, ch.updated_at = bool(data["no_token_warn"]), _now()
    return mine(settings, actor)


def token_warn_limit(settings: config.Settings, actor: Any) -> int:
    """大请求提示线（M8-2）：本人关闭了提示时为 0，否则取全局 ai.warn_tokens（0 = 不提示）。"""
    uid = getattr(actor, "user_id", None)
    if uid is not None:
        with store.session(settings.database_url) as s:
            ch = s.get(AIChoice, uid)
            if ch is not None and ch.no_token_warn:
                return 0
    return max(0, int(settings.get("ai.warn_tokens") or 0))


def personal_conn(settings: config.Settings, actor: Any) -> Conn | None:
    uid = getattr(actor, "user_id", None)
    if uid is None:
        return None
    with store.session(settings.database_url) as s:
        p = s.scalar(select(AIConnection).where(AIConnection.owner_id == uid))
        return _conn(p) if p is not None and _complete_row(p) else None
