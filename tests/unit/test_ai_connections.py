"""AI 接口：公共与个人（REQ-040）。解析规则各分支、[ai] 配置导入、Key 加密不泄露、调用记录归属、用量统计、迁移。
AI 一律用假的客户端（替换 ai.provider_hook），不调用外部服务。"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text

from lmesh.core import ai, ai_connections, config, projects, store, users
from lmesh.core.store.models import AICall, AIConnection

pytestmark = pytest.mark.unit
PW = "Pass-word-123"
BASE = {"provider": "openai", "base_url": "http://127.0.0.1:9/v1", "model": "fake-model"}


@pytest.fixture
def s(configured_root: Path) -> config.Settings:
    st = config.load()
    store.upgrade(st.database_url)
    return st


@pytest.fixture
def who(s: config.Settings) -> dict[str, projects.Identity]:
    for name, role in (("boss", "admin"), ("liwei", "user"), ("zhang", "user")):
        users.create_user(s.database_url, name, PW, role)
    return {n: projects.cli_identity(s.database_url, n) for n in ("boss", "liwei", "zhang")}


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, str]]:
    seen: list[tuple[Any, str]] = []

    def hook(conn, model, system, prompt):  # type: ignore[no-untyped-def]
        seen.append((conn, model))
        return ai.Reply("OK", model, 7, 3)

    monkeypatch.setattr(ai, "provider_hook", hook)
    return seen


def _res(s: config.Settings, ident: projects.Identity | None) -> ai_connections.Resolution:
    return ai_connections.resolve(s.for_actor(ident) if ident else s)


def test_resolve_branches(s: config.Settings, who: dict[str, projects.Identity]) -> None:
    boss, liwei, zhang = who["boss"], who["liwei"], who["zhang"]
    # 没有任何接口
    assert _res(s, None).reason == "no_connection"
    assert _res(s, boss).reason == "no_connection"
    assert _res(s, liwei).reason == "no_public"
    internal = ai_connections.create_connection(s, {"name": "internal", **BASE, "model": "big"})
    shared = ai_connections.create_connection(s, {"name": "shared", "public": True, **BASE})
    # 系统自身与管理员默认：第一个可用的管理员接口（不论是否公共）；普通账号：第一个公共接口
    assert _res(s, None).conn.name == "internal"  # type: ignore[union-attr]
    assert _res(s, boss).conn.name == "internal"  # type: ignore[union-attr]
    r = _res(s, liwei)
    assert r.conn.name == "shared" and r.source == "connection" and r.choice == "auto"  # type: ignore[union-attr]
    assert ai.model_for(s.for_actor(liwei), "ask") == "fake-model"
    # 普通账号不能选不公开的接口
    with pytest.raises(ai_connections.ConnError):
        ai_connections.save_mine(s, liwei, {"choice": "connection", "connection_id": internal["id"]})
    ai_connections.save_mine(s, zhang, {"choice": "connection", "connection_id": shared["id"]})
    assert _res(s, zhang).conn.name == "shared"  # type: ignore[union-attr]
    # 管理员关闭公共使用：选了它的 zhang 提示改选（不自动换），auto 的 liwei 是“未开放公共接口”
    ai_connections.update_connection(s, shared["id"], {"public": False})
    assert _res(s, zhang).reason == "public_closed" and not _res(s, zhang).configured
    assert _res(s, liwei).reason == "no_public"
    # 管理员可以选不公开的接口
    ai_connections.save_mine(s, boss, {"choice": "connection", "connection_id": shared["id"]})
    assert _res(s, boss).conn.name == "shared"  # type: ignore[union-attr]
    # 停用：auto 跳过它
    ai_connections.update_connection(s, internal["id"], {"enabled": False})
    assert _res(s, None).conn.name == "shared"  # type: ignore[union-attr]
    # 个人接口
    with pytest.raises(ai_connections.ConnError):
        ai_connections.save_mine(s, liwei, {"choice": "personal"})
    ai_connections.save_mine(s, liwei, {"personal": {**BASE, "model": "mine"}, "choice": "personal"})
    r = _res(s, liwei)
    assert r.source == "personal" and r.conn.model_for("ask") == "mine"  # type: ignore[union-attr]
    # 不使用
    ai_connections.save_mine(s, liwei, {"choice": "none"})
    assert _res(s, liwei).reason == "disabled_by_user"
    # 删除被选用的接口：返回受影响的账号数，之后提示改选
    d = ai_connections.delete_connection(s, shared["id"])
    assert d["affected_users"] == 2 and _res(s, zhang).reason == "public_closed"
    # 删掉个人接口时，选了个人接口的改回自动
    ai_connections.save_mine(s, liwei, {"choice": "personal"})
    m = ai_connections.save_mine(s, liwei, {"remove_personal": True})
    assert m["choice"] == "auto" and m["personal"] is None


def test_validation(s: config.Settings) -> None:
    with pytest.raises(ai_connections.ConnError, match="incomplete"):
        ai_connections.create_connection(s, {"name": "x", "provider": "anthropic", "model": "m"})  # 缺 Key
    with pytest.raises(ai_connections.ConnError, match="bad_provider"):
        ai_connections.create_connection(s, {"name": "x", **BASE, "provider": "bogus"})
    with pytest.raises(ai_connections.ConnError, match="bad_url"):
        ai_connections.create_connection(s, {"name": "x", **BASE, "base_url": "ftp://x"})
    with pytest.raises(ai_connections.ConnError, match="bad_name"):
        ai_connections.create_connection(s, {"name": "personal", **BASE})
    ai_connections.create_connection(s, {"name": "Lab", **BASE})
    with pytest.raises(ai_connections.ConnError, match="name_taken"):
        ai_connections.create_connection(s, {"name": "lab", **BASE})
    with pytest.raises(ai_connections.ConnError) as e:
        ai_connections.update_connection(s, 999, {"public": True})
    assert e.value.kind == "not_found"


def test_seed_from_config_once(configured_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """升级兼容：[ai] 填写完整时导入为第一个管理员接口（公共），只导入一次；删掉后不再导入。"""
    monkeypatch.setenv("LMESH_AI__PROVIDER", "openai")
    monkeypatch.setenv("LMESH_AI__BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("LMESH_AI__MODEL", "seed-model")
    monkeypatch.setenv("LMESH_AI__MODEL_ASK", "seed-ask")
    monkeypatch.setenv("LMESH_AI__API_KEY", "seed-secret")
    s = config.load()
    rows = ai_connections.list_connections(s)["connections"]
    assert [(r["name"], r["public"], r["model_ask"], r["api_key_set"]) for r in rows] == [
        ("default", True, "seed-ask", True)
    ]
    ai_connections.delete_connection(s, rows[0]["id"])
    ai_connections._SEEDED.discard(s.database_url)
    assert ai_connections.list_connections(s)["connections"] == []


def test_seed_skipped_when_incomplete(s: config.Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LMESH_AI__PROVIDER", "anthropic")  # 没有 Key：不导入
    s2 = config.load()
    assert ai_connections.list_connections(s2)["connections"] == []
    assert not ai.is_configured(s2)


def test_keys_encrypted_and_never_returned(s: config.Settings, who: dict[str, projects.Identity]) -> None:
    ai_connections.create_connection(s, {"name": "shared", "public": True, **BASE, "api_key": "admin-secret"})
    ai_connections.save_mine(s, who["liwei"], {"personal": {**BASE, "api_key": "liwei-secret"}})
    with store.session(s.database_url) as ss:
        stored = [c.api_key for c in ss.scalars(select(AIConnection))]
    assert all(k.startswith(config.SECRET_PREFIX) for k in stored)
    assert not any("secret" in k for k in stored)
    out = json.dumps(
        [
            ai_connections.list_connections(s),
            ai_connections.mine(s, who["liwei"]),
            ai_connections.mine(s, who["boss"]),
        ]
    )
    assert "admin-secret" not in out and "liwei-secret" not in out
    # 管理员的列表里没有个人接口；别人的“我的 AI”里也没有
    assert [c["name"] for c in ai_connections.list_connections(s)["connections"]] == ["shared"]
    assert ai_connections.mine(s, who["zhang"])["personal"] is None
    assert ai_connections.mine(s, who["liwei"])["personal"]["api_key_set"] is True


def test_calls_record_user_and_connection(
    s: config.Settings, who: dict[str, projects.Identity], fake: list[tuple[Any, str]]
) -> None:
    ai_connections.create_connection(s, {"name": "shared", "public": True, **BASE, "model_ask": "ask-m"})
    ai_connections.save_mine(s, who["zhang"], {"personal": {**BASE, "model": "z"}, "choice": "personal"})
    ai.complete(s.for_actor(who["liwei"]), "ask", "q", feature="ask-query")
    ai.complete(s.for_actor(who["zhang"]), "extract", "q")
    ai.complete(s, "test", "q")  # 系统自身（没有账号的命令行、测试）
    assert [m for _, m in fake] == ["ask-m", "z", "fake-model"]
    assert fake[1][0].personal and fake[1][0].api_key() == ""
    calls = ai.recent_calls(s.database_url)
    assert [(c["user"], c["connection"], c["source"], c["feature"]) for c in calls] == [
        ("cli", "shared", "connection", "test"),
        ("zhang", "personal", "personal", "extract"),
        ("liwei", "shared", "connection", "ask-query"),
    ]
    assert calls[1]["connection_id"] is None  # 不暴露个人接口编号
    mine = ai.recent_calls(s.database_url, user_id=who["liwei"].user_id)
    assert [c["user"] for c in mine] == ["liwei"]
    # 没有可用接口时不记录、抛出未配置
    ai_connections.save_mine(s, who["liwei"], {"choice": "none"})
    with pytest.raises(ai.AIError, match="not_configured"):
        ai.complete(s.for_actor(who["liwei"]), "ask", "q")
    assert ai.not_configured_data(s.for_actor(who["liwei"]))["reason"] == "disabled_by_user"


def test_background_task_uses_initiator(
    s: config.Settings, who: dict[str, projects.Identity], fake: list[tuple[Any, str]]
) -> None:
    """后台任务带着提交时绑定了发起人的 settings 运行：按发起人的选择，并记录发起人。"""
    from lmesh.core import tasks

    ai_connections.create_connection(s, {"name": "shared", "public": True, **BASE})
    ai_connections.save_mine(s, who["zhang"], {"personal": {**BASE, "model": "z"}, "choice": "personal"})
    bound = s.for_actor(who["zhang"])
    tid = tasks.submit(s.database_url, "t", lambda p: {"m": ai.complete(bound, "ask", "q").model}, created_by="zhang")
    import time

    for _ in range(100):
        t = tasks.get(s.database_url, tid)
        if t and t["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert t and t["result"] == {"m": "z"} and t["created_by"] == "zhang"
    assert ai.recent_calls(s.database_url)[0]["user"] == "zhang"


def test_usage_and_csv(s: config.Settings, who: dict[str, projects.Identity]) -> None:
    today = datetime.now(UTC).date()
    with store.session(s.database_url) as ss:
        conn = AIConnection(name="shared", provider="openai", base_url="http://x/v1", model="m", public=True)
        ss.add(conn)
        ss.flush()
        rows = [
            (0, "liwei", who["liwei"].user_id, "connection", "ask-query", "m", "ok", 100, 10),
            (0, "liwei", who["liwei"].user_id, "connection", "", "m", "error", 0, 0),
            (1, "zhang", who["zhang"].user_id, "personal", "", "z", "ok", 50, 5),
            (40, "zhang", who["zhang"].user_id, "personal", "", "z", "ok", 999, 9),  # 超出默认 30 天
        ]
        for days, actor, uid, source, feature, model, status, tin, tout in rows:
            ss.add(
                AICall(
                    task="ask" if feature else "extract",
                    provider="openai",
                    model=model,
                    tokens_in=tin,
                    tokens_out=tout,
                    status=status,
                    user_id=uid,
                    actor=actor,
                    connection_id=conn.id if source == "connection" else None,
                    connection_name="shared" if source == "connection" else "personal",
                    source=source,
                    feature=feature,
                    created_at=datetime.now(UTC) - timedelta(days=days),
                )
            )
    u = ai.usage(s.database_url)
    assert u["totals"] == {"calls": 3, "errors": 1, "tokens_in": 150, "tokens_out": 15}
    assert len(u["by_day"]) == 30 and u["by_day"][-1]["key"] == today.isoformat()
    assert u["by_day"][-1]["calls"] == 2 and u["by_day"][-2]["tokens_in"] == 50
    assert [(r["key"], r["calls"]) for r in u["by_user"]] == [("liwei", 2), ("zhang", 1)]
    assert [(r["key"], r["id"]) for r in u["by_connection"]] == [("shared", 1), ("personal", None)]
    assert {r["key"] for r in u["by_feature"]} == {"ask-query", "extract"}
    assert [r["key"] for r in u["by_model"]] == ["m", "z"]
    mine = ai.usage(s.database_url, user_id=who["zhang"].user_id, start=today - timedelta(days=60), end=today)
    assert mine["totals"]["calls"] == 2 and len(mine["by_day"]) == 61
    one = ai.usage(s.database_url, date(2026, 1, 2), date(2026, 1, 1))  # 起止颠倒时自动交换
    assert one["from"] == "2026-01-01" and one["totals"]["calls"] == 0
    csv_text = ai.usage_csv(u, "user")
    assert csv_text.startswith("﻿key,calls,errors,tokens_in,tokens_out\r\nliwei,2,1,100,10\r\n")


def test_migration_0009_from_0008(db_url: str) -> None:
    """从 0008 升级：已有的调用记录、任务保留，新列有默认值；新表可用。"""
    from tests.unit.test_project_refs import _upgrade_to

    _upgrade_to(db_url, "0008")
    with store.get_engine(db_url).begin() as c:
        c.execute(
            text(
                "INSERT INTO ai_calls (task, provider, model, tokens_in, tokens_out, status, error, created_at) "
                "VALUES ('ask', 'openai', 'm', 1, 2, 'ok', '', :n)"
            ),
            {"n": "2026-10-19 00:00:00"},
        )
        c.execute(
            text(
                "INSERT INTO tasks (id, kind, status, progress, message, created_at, updated_at) "
                "VALUES ('t1', 'ingest', 'done', 100, '', :n, :n)"
            ),
            {"n": "2026-10-19 00:00:00"},
        )
    store._UPGRADED.discard(db_url)
    store.upgrade(db_url)
    with store.session(db_url) as ss:
        call = ss.scalars(select(AICall)).one()
        assert (call.actor, call.connection_name, call.source, call.feature, call.user_id) == ("", "", "", "", None)
        assert ss.scalar(text("SELECT created_by FROM tasks WHERE id = 't1'")) == ""
        ss.add(AIConnection(name="a", provider="openai", base_url="http://x", model="m"))
    assert "ai_connections" in store.table_names(db_url) and "ai_choices" in store.table_names(db_url)
