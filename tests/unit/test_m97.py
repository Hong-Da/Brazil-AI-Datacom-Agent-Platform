"""M9-7：个人偏好（REQ-047）、向导测试 AI 连接（REQ-048）、系统设置的核心逻辑（REQ-049）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from lmesh.core import ai, config, setup, store, users

# ---------------------------------------------------------------- 迁移 0013 与偏好


def test_migration_0013_adds_prefs(db_url: str) -> None:
    from tests.unit.test_project_refs import _upgrade_to

    _upgrade_to(db_url, "0012")
    with store.get_engine(db_url).begin() as c:
        c.execute(
            text(
                "INSERT INTO users (id, username, role, disabled, password_hash, failed_count, password_changed_at, "
                "created_at) VALUES (1, 'boss', 'admin', false, 'x', 0, :n, :n)"
            ),
            {"n": "2026-10-20 00:00:00"},
        )
    store._UPGRADED.discard(db_url)
    store.upgrade(db_url)
    assert users.get_prefs(db_url, 1) is None  # 已有账号：还没保存过
    assert users.save_prefs(db_url, 1, {"lang": "en"}) == {"lang": "en"}
    assert users.save_prefs(db_url, 1, {"theme": "dark"}) == {"lang": "en", "theme": "dark"}
    assert users.get_prefs(db_url, 1) == {"lang": "en", "theme": "dark"}


def test_prefs_validation(db: str) -> None:
    u = users.create_user(db, "liwei", "Pass-word-123")
    with pytest.raises(users.UserError) as e:
        users.save_prefs(db, u["id"], {"theme": "purple"})
    assert e.value.key == "prefs.invalid" and e.value.fmt["name"] == "theme"
    with pytest.raises(users.UserError) as e:
        users.save_prefs(db, u["id"], {"font": "big"})
    assert e.value.key == "prefs.unknown"
    with pytest.raises(users.UserError):
        users.get_prefs(db, 9999)
    # 数据库里有以前的、已不认识的项或值：读取时忽略
    with store.session(db) as s:
        from lmesh.core.store.models import User

        s.get(User, u["id"]).prefs = {"lang": "fr", "theme": "dark", "old": 1}  # type: ignore[union-attr]
    assert users.get_prefs(db, u["id"]) == {"theme": "dark"}


@pytest.fixture
def db(tmp_root: Path) -> str:
    url = f"sqlite:///{(tmp_root / 'data' / 'm97.db').as_posix()}"
    (tmp_root / "data").mkdir(parents=True, exist_ok=True)
    store.upgrade(url)
    return url


# ---------------------------------------------------------------- 向导测试 AI 连接


def test_validate_ai_test() -> None:
    assert setup.validate_ai_test("", "", "m") == {"ai.provider": "config.invalid.choice"}
    assert setup.validate_ai_test("openai", " ", "m") == {"ai.base_url": "config.invalid.required"}
    assert setup.validate_ai_test("anthropic", "", "") == {"ai.model": "config.invalid.required"}
    assert setup.validate_ai_test("anthropic", "", "claude") == {}


def test_test_unsaved_uses_plain_key(monkeypatch: pytest.MonkeyPatch) -> None:
    got: dict[str, Any] = {}

    def hook(conn: Any, model: str, system: str, prompt: str) -> ai.Reply:
        got.update(key=conn.api_key(), model=model, prompt=prompt)
        return ai.Reply(" OK ", model, 3, 1)

    monkeypatch.setattr(ai, "provider_hook", hook)
    r = ai.test_unsaved(
        config.Settings(values={f.key: f.default for f in config.FIELDS}), "openai", "http://x/v1", "enc:abc", "m1"
    )
    assert got == {
        "key": "enc:abc",
        "model": "m1",
        "prompt": "Reply with exactly: OK",
    }  # 明文 Key 原样使用，不当作加密值
    assert r["reply"] == "OK" and r["tokens_in"] == 3

    def boom(conn: Any, model: str, system: str, prompt: str) -> ai.Reply:
        raise TimeoutError("slow")

    monkeypatch.setattr(ai, "provider_hook", boom)
    with pytest.raises(ai.AIError) as e:
        ai.test_unsaved(
            config.Settings(values={f.key: f.default for f in config.FIELDS}), "openai", "http://x/v1", "k", "m1"
        )
    assert str(e.value) == "ai.call_failed" and e.value.error_type == "TimeoutError" and e.value.status is None


# ---------------------------------------------------------------- 系统设置


def _settings(**over: Any) -> config.Settings:
    s = config.Settings(
        values={f.key: f.default for f in config.FIELDS}, sources={f.key: "default" for f in config.FIELDS}
    )
    for k, v in over.items():
        s.values[k.replace("__", ".")] = v
    return s


def test_readonly_reasons() -> None:
    s = _settings()
    s.sources["log.level"] = "env"
    assert setup.readonly_reason("log.level", s) == "env"
    assert setup.readonly_reason("ai.model_ask", s) == "ai"
    assert setup.readonly_reason("database.url", s) == "secret"
    assert setup.readonly_reason("ai.timeout", s) is None
    assert {"server.host", "server.port"} <= setup.RESTART_KEYS


def test_check_settings_collects_all_errors() -> None:
    s = _settings()
    with pytest.raises(setup.SetupError) as e:
        setup.check_settings(
            {"nope": 1, "security.api_token": "x", "history.keep": "abc", "ui.term_style": "juniper"},
            s,
            s,
            check_port=False,
        )
    assert e.value.errors == {
        "nope": "config.invalid.unknown",
        "security.api_token": "config.invalid.readonly_secret",
        "history.keep": "config.invalid.int",
        "ui.term_style": "config.invalid.choice",
    }
    setup.check_settings({"history.keep": 10, "server.port": 9100}, s, s, check_port=False)


def test_restart_pending_and_view() -> None:
    running = _settings()
    saved = _settings(server__port=9100, log__level="DEBUG", history__keep=10)
    pend = setup.restart_pending(running, saved)
    assert [p["key"] for p in pend] == ["server.port", "log.level"]  # 按配置项顺序，history.keep 不需要重启
    assert pend[0] == {"key": "server.port", "running": 9090, "saved": 9100}
    view = setup.settings_view("en", saved, running)
    assert view["groups"][0]["title"] == "Interface"
    f = next(x for g in view["groups"] for x in g["fields"] if x["key"] == "auth.registration")
    assert f["value"] == "false" and f["choices"] == ["true", "false"]  # 开关按两个选项给出
    assert setup.wizard_schema("en")[0]["fields"][0]["key"] == "ui.language"
    assert all("value" not in x for g in setup.wizard_schema("en") for x in g["fields"])
