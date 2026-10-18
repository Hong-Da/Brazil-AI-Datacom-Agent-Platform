"""AI 接入：可配置的接口（Anthropic / OpenAI 兼容 / 本地模型），按任务选模型，记录每次调用。

原则：确定性的结论由代码给出，AI 只负责理解、归纳、给建议；AI 的输出一律先经代码校验。
未配置 AI 时 is_configured() 为 False，调用方隐藏相关功能，核心功能不受影响。
发给 AI 的配置文本由调用方先脱敏。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from lmesh.core import config, store
from lmesh.core.store.models import AICall, iso

_log = logging.getLogger("lmesh.ai")
TASK_MODEL_KEYS = {
    "extract": "ai.model_extract",
    "merge": "ai.model_merge",
    "ask": "ai.model_ask",
    "generate": "ai.model_generate",
}


class AIError(RuntimeError):
    pass


@dataclass
class Reply:
    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0


def is_configured(settings: config.Settings) -> bool:
    provider = settings.get("ai.provider")
    if not provider:
        return False
    if provider == "anthropic":
        return bool(settings.ai_api_key()) and bool(settings.get("ai.model"))
    return bool(settings.get("ai.base_url")) and bool(settings.get("ai.model"))


def model_for(settings: config.Settings, task: str) -> str:
    key = TASK_MODEL_KEYS.get(task)
    return str((settings.get(key) if key else "") or settings.get("ai.model"))


def _call_provider(settings: config.Settings, model: str, system: str, prompt: str) -> Reply:
    provider = settings.get("ai.provider")
    timeout = float(settings.get("ai.timeout"))
    max_tokens = int(settings.get("ai.max_tokens"))
    if provider == "anthropic":
        try:
            import anthropic
        except ImportError as e:
            raise AIError("ai.sdk_missing") from e
        kwargs: dict[str, Any] = {"api_key": settings.ai_api_key(), "timeout": timeout}
        if settings.get("ai.base_url"):
            kwargs["base_url"] = settings.get("ai.base_url")
        client = anthropic.Anthropic(**kwargs)
        msg = client.messages.create(
            model=model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": prompt}]
        )
        text = "".join(getattr(b, "text", "") for b in msg.content)
        return Reply(text, model, msg.usage.input_tokens, msg.usage.output_tokens)
    try:
        import openai
    except ImportError as e:
        raise AIError("ai.sdk_missing") from e
    client_o = openai.OpenAI(
        api_key=settings.ai_api_key() or "not-needed", base_url=settings.get("ai.base_url"), timeout=timeout
    )
    resp = client_o.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    )
    usage = resp.usage
    return Reply(
        resp.choices[0].message.content or "",
        model,
        usage.prompt_tokens if usage else 0,
        usage.completion_tokens if usage else 0,
    )


# 测试时替换成假的实现：provider_hook(settings, model, system, prompt) -> Reply
provider_hook = _call_provider


def complete(
    settings: config.Settings, task: str, prompt: str, system: str = "", review_item_id: int | None = None
) -> Reply:
    """调用 AI 并记录：任务、模型、token 用量、成功与否。失败抛出 AIError。"""
    if not is_configured(settings):
        raise AIError("ai.not_configured")
    model = model_for(settings, task)
    call = AICall(task=task, provider=str(settings.get("ai.provider")), model=model, review_item_id=review_item_id)
    try:
        reply = provider_hook(settings, model, system, prompt)
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
        try:
            with store.session(settings.database_url) as s:
                s.add(call)
        except Exception:  # 记录失败不影响调用结果
            _log.debug("AI 调用记录写入失败", exc_info=True)


def test(settings: config.Settings) -> dict[str, Any]:
    reply = complete(settings, "test", "Reply with exactly: OK", system="You are a connectivity check.")
    return {
        "model": reply.model,
        "reply": reply.text.strip()[:100],
        "tokens_in": reply.tokens_in,
        "tokens_out": reply.tokens_out,
    }


def recent_calls(db_url: str, limit: int = 100) -> list[dict[str, Any]]:
    from sqlalchemy import select

    with store.session(db_url) as s:
        rows = s.scalars(select(AICall).order_by(AICall.id.desc()).limit(limit))
        return [
            {
                "id": c.id,
                "task": c.task,
                "provider": c.provider,
                "model": c.model,
                "tokens_in": c.tokens_in,
                "tokens_out": c.tokens_out,
                "status": c.status,
                "error": c.error,
                "review_item_id": c.review_item_id,
                "created_at": iso(c.created_at),
            }
            for c in rows
        ]
