"""AI 接入：可配置的接口（Anthropic / OpenAI 兼容 / 本地模型），按任务选模型，记录每次调用。

原则：确定性的结论由代码给出，AI 只负责理解、归纳、给建议；AI 的输出一律先经代码校验。
未配置 AI 时 is_configured() 为 False，调用方隐藏相关功能，核心功能不受影响。
发给 AI 的配置文本由调用方先脱敏。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from lmesh.core import ai_connections, config, store
from lmesh.core.store.models import AICall, iso

_log = logging.getLogger("lmesh.ai")
TASK_MODEL_KEYS = {
    "extract": "ai.model_extract",
    "merge": "ai.model_merge",
    "ask": "ai.model_ask",
    "generate": "ai.model_generate",
}


class AIError(RuntimeError):
    """AI 调用失败；args[0] 是文案键。error_type / status：底层异常类型与 HTTP 状态码（不含请求内容）。"""

    def __init__(self, key: str, error_type: str = "", status: int | None = None):
        super().__init__(key)
        self.error_type, self.status = error_type, status


@dataclass
class Reply:
    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0


def resolve(settings: config.Settings) -> ai_connections.Resolution:
    """当前请求用哪个接口（REQ-040）：按 settings.actor（发起人）的选择，见 ai_connections.resolve。"""
    return ai_connections.resolve(settings)


def is_configured(settings: config.Settings) -> bool:
    return resolve(settings).configured


def not_configured_data(settings: config.Settings) -> dict[str, Any]:
    """“未配置”时返回给界面的状态：带原因（管理员未开放公共接口 / 所选接口已关闭 / 你还没设置个人接口……）。"""
    return {"status": "not_configured", "configured": False, "reason": resolve(settings).reason}


def model_for(settings: config.Settings, task: str) -> str:
    conn = resolve(settings).conn
    if conn is None:
        return ""
    return conn.model_for(task)


def provider_of(settings: config.Settings) -> str | None:
    conn = resolve(settings).conn
    return conn.provider if conn else None


def _call_provider(conn: ai_connections.Conn, settings: config.Settings, model: str, system: str, prompt: str) -> Reply:
    provider = conn.provider
    timeout = float(settings.get("ai.timeout"))
    max_tokens = int(settings.get("ai.max_tokens"))
    if provider == "anthropic":
        try:
            import anthropic
        except ImportError as e:
            raise AIError("ai.sdk_missing") from e
        kwargs: dict[str, Any] = {"api_key": conn.api_key(), "timeout": timeout}
        if conn.base_url:
            kwargs["base_url"] = conn.base_url
        client = anthropic.Anthropic(**kwargs)
        imgs = _IMAGES.get()
        content: Any = prompt
        if imgs:
            content = [
                *({"type": "image", "source": {"type": "base64", "media_type": m, "data": b64}} for m, b64 in imgs),
                {"type": "text", "text": prompt},
            ]
        msg = client.messages.create(
            model=model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": content}]
        )
        text = "".join(getattr(b, "text", "") for b in msg.content)
        return Reply(text, model, msg.usage.input_tokens, msg.usage.output_tokens)
    try:
        import openai
    except ImportError as e:
        raise AIError("ai.sdk_missing") from e
    client_o = openai.OpenAI(api_key=conn.api_key() or "not-needed", base_url=conn.base_url, timeout=timeout)
    imgs = _IMAGES.get()
    user: Any = prompt
    if imgs:
        user = [
            *({"type": "image_url", "image_url": {"url": f"data:{m};base64,{b64}"}} for m, b64 in imgs),
            {"type": "text", "text": prompt},
        ]
    resp = client_o.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    usage = resp.usage
    return Reply(
        resp.choices[0].message.content or "",
        model,
        usage.prompt_tokens if usage else 0,
        usage.completion_tokens if usage else 0,
    )


# 测试时替换成假的实现：provider_hook(conn, model, system, prompt) -> Reply（conn 是 ai_connections.Conn）
def _default_hook(conn: ai_connections.Conn, model: str, system: str, prompt: str) -> Reply:
    return _call_provider(conn, _HOOK_SETTINGS.get(), model, system, prompt)


provider_hook: Callable[[Any, str, str, str], Reply] = _default_hook
_HOOK_SETTINGS: ContextVar[config.Settings] = ContextVar("lmesh_ai_settings")
_CALL_IDS: ContextVar[list[int] | None] = ContextVar("lmesh_ai_call_ids", default=None)
# 随下一次调用一起发送的图片 [(媒体类型, base64)]（REQ-053：AI 查询的图片附件，用户确认后才设置；不脱敏）
_IMAGES: ContextVar[tuple[tuple[str, str], ...]] = ContextVar("lmesh_ai_images", default=())


class with_images:
    """在这段代码里的 AI 调用都带上这些图片：with ai.with_images([(mime, b64), …]): …"""

    def __init__(self, images: list[tuple[str, str]]):
        self._images = tuple(images)

    def __enter__(self) -> None:
        self._token = _IMAGES.set(self._images)

    def __exit__(self, *exc: object) -> None:
        _IMAGES.reset(self._token)


def pending_images() -> tuple[tuple[str, str], ...]:
    """当前调用会带上的图片（测试替身用来确认图片有没有发出去）。"""
    return _IMAGES.get()


def _record_call_id(call_id: int) -> None:
    ids = _CALL_IDS.get()
    if ids is not None:
        ids.append(call_id)


class collect_call_ids:  # noqa: N801  用法像函数：with ai.collect_call_ids() as ids
    """收集这段代码里（同一线程）每次 complete 写入的调用记录编号（AI 建议记下“调用记录编号”用）。"""

    def __enter__(self) -> list[int]:
        self._ids: list[int] = []
        self._token = _CALL_IDS.set(self._ids)
        return self._ids

    def __exit__(self, *exc: object) -> None:
        _CALL_IDS.reset(self._token)


def complete(
    settings: config.Settings,
    task: str,
    prompt: str,
    system: str = "",
    review_item_id: int | None = None,
    feature: str = "",
    conn: ai_connections.Conn | None = None,
) -> Reply:
    """调用 AI 并记录：发起人、接口、任务、功能（skill）、模型、token 用量、成功与否。失败抛出 AIError。
    conn 给出时直接用它（测试连接），否则按发起人的选择解析。"""
    res = resolve(settings) if conn is None else None
    conn = conn if conn is not None else (res.conn if res else None)
    if conn is None:
        raise AIError("ai.not_configured")
    who = settings.actor if settings.actor is not None else ai_connections.cli_actor()
    model = conn.model_for(task)
    call = AICall(
        task=task,
        provider=conn.provider,
        model=model,
        review_item_id=review_item_id,
        user_id=getattr(who, "user_id", None),
        actor=str(getattr(who, "username", "") or ("cli" if who is None else "")),
        connection_id=None if conn.personal else conn.id,
        connection_name=conn.name,
        source="personal" if conn.personal else "connection",
        feature=feature[:60],
    )
    token = _HOOK_SETTINGS.set(settings)
    try:
        reply = provider_hook(conn, model, system, prompt)
        call.tokens_in, call.tokens_out, call.status = reply.tokens_in, reply.tokens_out, "ok"
        return reply
    except AIError:
        call.status = "error"
        raise
    except Exception as e:  # SDK 的各种网络、认证错误
        call.status, call.error = "error", f"{type(e).__name__}: {str(e)[:500]}"
        _log.warning("AI 调用失败（%s，%s）：%s", task, model, type(e).__name__)
        raise AIError("ai.call_failed") from e
    finally:
        _HOOK_SETTINGS.reset(token)
        try:
            with store.session(settings.database_url) as s:
                s.add(call)
                s.flush()
                _record_call_id(int(call.id))
        except Exception:  # 记录失败不影响调用结果
            _log.debug("AI 调用记录写入失败", exc_info=True)


def test(settings: config.Settings, conn: ai_connections.Conn | None = None) -> dict[str, Any]:
    reply = complete(settings, "test", "Reply with exactly: OK", system="You are a connectivity check.", conn=conn)
    return {
        "model": reply.model,
        "reply": reply.text.strip()[:100],
        "tokens_in": reply.tokens_in,
        "tokens_out": reply.tokens_out,
    }


class _PlainConn(ai_connections.Conn):
    """还没保存的接口（首次运行向导测试连接）：Key 是明文，只在内存里，用完即丢。"""

    def api_key(self) -> str:
        return self.api_key_enc


def test_unsaved(settings: config.Settings, provider: str, base_url: str, api_key: str, model: str) -> dict[str, Any]:
    """测试还没保存的接口（首次运行向导）：不写调用记录（这时还没有数据库），不保存、不记录 Key。

    失败抛 AIError；error_type / status 只含异常类型与 HTTP 状态码，不含请求内容。
    """
    conn = _PlainConn(None, "setup", provider, base_url, api_key, {"model": model})
    token = _HOOK_SETTINGS.set(settings)
    started = datetime.now(UTC)
    try:
        reply = provider_hook(conn, model, "You are a connectivity check.", "Reply with exactly: OK")
    except AIError:
        raise
    except Exception as e:  # SDK 的各种网络、认证错误
        _log.warning("向导测试 AI 连接失败（%s，%s）：%s", provider, model, type(e).__name__)
        status = getattr(e, "status_code", None)
        raise AIError("ai.call_failed", type(e).__name__, status if isinstance(status, int) else None) from e
    finally:
        _HOOK_SETTINGS.reset(token)
    return {
        "model": reply.model,
        "reply": reply.text.strip()[:100],
        "tokens_in": reply.tokens_in,
        "tokens_out": reply.tokens_out,
        "elapsed_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
    }


def _call_filters(user_id: int | None, connection_id: int | None, task: str | None, actor: str | None) -> list[Any]:
    conds: list[Any] = []
    if user_id is not None:
        conds.append(AICall.user_id == user_id)
    if actor:
        conds.append(AICall.actor == actor)
    if connection_id is not None:
        conds.append(AICall.connection_id == connection_id)
        conds.append(AICall.source == "connection")
    if task:
        conds.append(AICall.task == task)
    return conds


def recent_calls(
    db_url: str,
    limit: int = 100,
    user_id: int | None = None,
    connection_id: int | None = None,
    task: str | None = None,
    actor: str | None = None,
) -> list[dict[str, Any]]:
    """最近的调用记录（新的在前）。user_id：只看某个账号的（普通账号只能看自己的）；actor：按账号名过滤（管理员）。"""
    from sqlalchemy import select

    with store.session(db_url) as s:
        q = select(AICall).where(*_call_filters(user_id, connection_id, task, actor))
        rows = s.scalars(q.order_by(AICall.id.desc()).limit(limit))
        return [
            {
                "id": c.id,
                "task": c.task,
                "feature": c.feature or c.task,
                "provider": c.provider,
                "model": c.model,
                "tokens_in": c.tokens_in,
                "tokens_out": c.tokens_out,
                "status": c.status,
                "error": c.error,
                "review_item_id": c.review_item_id,
                "user": c.actor,
                "connection": c.connection_name,
                "connection_id": c.connection_id if c.source == "connection" else None,
                "source": c.source,
                "created_at": iso(c.created_at),
            }
            for c in rows
        ]


USAGE_GROUPS = ("day", "user", "connection", "feature", "model")


def _day(v: Any) -> date:
    if isinstance(v, datetime):
        return (v if v.tzinfo is None else v.astimezone(UTC)).date()
    return date.fromisoformat(str(v)[:10])


def usage(
    db_url: str,
    start: date | None = None,
    end: date | None = None,
    user_id: int | None = None,
    connection_id: int | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """用量统计：范围内（UTC 日期，含两端；默认最近 30 天）按天、账号、接口、功能、模型汇总调用次数、失败与 token。
    个人接口统一记为 personal（不暴露别人的个人接口编号）。"""
    from sqlalchemy import select

    end = end or datetime.now(UTC).date()
    start = start or (end - timedelta(days=29))
    if start > end:
        start, end = end, start
    lo = datetime(start.year, start.month, start.day, tzinfo=UTC)
    hi = datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
    cols = (
        AICall.created_at,
        AICall.actor,
        AICall.connection_id,
        AICall.connection_name,
        AICall.source,
        AICall.feature,
        AICall.task,
        AICall.model,
        AICall.status,
        AICall.tokens_in,
        AICall.tokens_out,
    )
    groups: dict[str, dict[str, dict[str, Any]]] = {g: {} for g in USAGE_GROUPS}
    total = {"calls": 0, "errors": 0, "tokens_in": 0, "tokens_out": 0}

    def add(group: str, key: str, row: dict[str, int], extra: dict[str, Any] | None = None) -> None:
        g = groups[group].setdefault(
            key, {"key": key, **(extra or {}), "calls": 0, "errors": 0, "tokens_in": 0, "tokens_out": 0}
        )
        for k, v in row.items():
            g[k] += v

    d = start
    while d <= end:
        add("day", d.isoformat(), {})
        d += timedelta(days=1)
    with store.session(db_url) as s:
        q = select(*cols).where(
            AICall.created_at >= lo, AICall.created_at < hi, *_call_filters(user_id, connection_id, None, actor)
        )
        for at, who, cid, cname, source, feature, task, model, status, tin, tout in s.execute(q):
            row = {"calls": 1, "errors": int(status != "ok"), "tokens_in": int(tin or 0), "tokens_out": int(tout or 0)}
            for k, v in row.items():
                total[k] += v
            add("day", _day(at).isoformat(), row)
            add("user", who or "cli", row)
            if source == "personal":
                add("connection", "personal", row, {"id": None})
            else:
                add("connection", cname or "—", row, {"id": cid})
            add("feature", feature or task, row)
            add("model", model or "—", row)

    def ordered(g: str) -> list[dict[str, Any]]:
        rows = list(groups[g].values())
        if g == "day":
            return sorted(rows, key=lambda r: r["key"])
        return sorted(rows, key=lambda r: (-(r["tokens_in"] + r["tokens_out"]), -r["calls"], r["key"]))

    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "totals": total,
        **{f"by_{g}": ordered(g) for g in USAGE_GROUPS},
    }


def usage_csv(data: dict[str, Any], group: str) -> str:
    """一组统计导出为 CSV（UTF-8 带 BOM，Excel 直接打开不乱码）。"""
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator=CRLF)
    w.writerow(["key", "calls", "errors", "tokens_in", "tokens_out"])
    for r in data[f"by_{group}"]:
        w.writerow([r["key"], r["calls"], r["errors"], r["tokens_in"], r["tokens_out"]])
    return BOM + buf.getvalue()


CRLF = chr(13) + chr(10)
BOM = chr(0xFEFF)
