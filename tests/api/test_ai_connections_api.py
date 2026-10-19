"""AI 接口：公共与个人（REQ-040）的 API：管理员 / 普通账号权限、公共开关关闭后的降级、个人 Key 不可被他人与管理员读取、
调用记录与用量的归属、旧接口兼容。AI 一律用假的客户端（替换 ai.provider_hook），不调用外部服务。
准备：ai_root（管理员 admin、普通用户 alice / bob；管理员接口 shared 公共、internal 不公开；alice 选用个人接口）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import TEST_TOKEN, TEST_USERS

pytestmark = pytest.mark.api
H = {"Authorization": f"Bearer {TEST_TOKEN}"}


def data(r: Any) -> Any:
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _client(name: str | None = None) -> Any:
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    c = TestClient(create_app())
    if name:
        pw = TEST_USERS.get(name, ("Bob-pass-12",))[0]
        assert c.post("/api/v1/auth/login", json={"username": name, "password": pw}).status_code == 200
    return c


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from lmesh.core import ai

    models: list[str] = []

    def hook(conn, model, system, prompt):  # type: ignore[no-untyped-def]
        models.append(f"{conn.name}:{model}")
        return ai.Reply("OK", model, 5, 2)

    monkeypatch.setattr(ai, "provider_hook", hook)
    return models


def _conn_id(admin: Any, name: str) -> int:
    return next(c["id"] for c in data(admin.get("/api/v1/ai/connections"))["connections"] if c["name"] == name)


def test_admin_crud_and_user_forbidden(ai_root: Path) -> None:
    admin, alice = _client("admin"), _client("alice")
    lst = data(admin.get("/api/v1/ai/connections"))
    assert [(c["name"], c["public"], c["is_default"]) for c in lst["connections"]] == [
        ("shared", True, True),
        ("internal", False, False),
    ]
    assert lst["limits"] == {"timeout": 60, "max_tokens": 4096}
    body = {"name": "lab", "provider": "local", "base_url": "http://127.0.0.1:9/v1", "model": "qwen", "public": True}
    new = data(admin.post("/api/v1/ai/connections", json=body))
    assert new["public"] and not new["api_key_set"] and new["chosen_by"] == 0
    assert admin.post("/api/v1/ai/connections", json=body).status_code == 409
    bad = admin.post("/api/v1/ai/connections", json={**body, "name": "x", "provider": "anthropic"})
    assert bad.status_code == 422 and bad.json()["code"] == 1001
    upd = data(admin.put(f"/api/v1/ai/connections/{new['id']}", json={"model_ask": "qwen-ask", "api_key": "k-1"}))
    assert upd["model_ask"] == "qwen-ask" and upd["api_key_set"] and "k-1" not in json.dumps(upd)
    assert data(admin.get(f"/api/v1/ai/connections/{new['id']}"))["model"] == "qwen"
    for method, path in (
        ("GET", "/api/v1/ai/connections"),
        ("POST", "/api/v1/ai/connections"),
        ("GET", f"/api/v1/ai/connections/{new['id']}"),
        ("PUT", f"/api/v1/ai/connections/{new['id']}"),
        ("DELETE", f"/api/v1/ai/connections/{new['id']}"),
        ("POST", f"/api/v1/ai/connections/{new['id']}/test"),
    ):
        r = alice.request(method, path, json=body if method in ("POST", "PUT") else None)
        assert r.status_code == 403 and r.json()["code"] == 1006, (method, path)
    assert data(admin.delete(f"/api/v1/ai/connections/{new['id']}")) == {"deleted": new["id"], "affected_users": 0}
    assert admin.get(f"/api/v1/ai/connections/{new['id']}").status_code == 404


def test_user_sees_only_public_and_degrades_when_closed(ai_root: Path, fake: list[str]) -> None:
    admin, bob = _client("admin"), _client("bob")
    mine = data(bob.get("/api/v1/me/ai"))
    assert mine["choice"] == "auto" and [o["name"] for o in mine["options"]] == ["shared"]
    assert mine["effective"]["connection"]["name"] == "shared" and mine["personal"] is None
    # 管理员能看到全部启用的接口
    assert [o["name"] for o in data(admin.get("/api/v1/me/ai"))["options"]] == ["shared", "internal"]
    internal = _conn_id(admin, "internal")
    r = bob.put("/api/v1/me/ai", json={"choice": "connection", "connection_id": internal})
    assert r.status_code == 422
    shared = _conn_id(admin, "shared")
    assert (
        data(bob.put("/api/v1/me/ai", json={"choice": "connection", "connection_id": shared}))["choice"] == "connection"
    )
    assert data(bob.get("/api/v1/summary"))["ai"] == {"configured": True, "reason": None}
    # 管理员关闭公共使用 → bob 看到改选提示，AI 功能按未配置降级
    data(admin.put(f"/api/v1/ai/connections/{shared}", json={"public": False}))
    st = data(bob.get("/api/v1/ai/status"))
    assert st["configured"] is False and st["reason"] == "public_closed"
    assert data(bob.get("/api/v1/summary"))["ai"] == {"configured": False, "reason": "public_closed"}
    closed = data(bob.get("/api/v1/me/ai"))
    assert closed["options"] == [] and closed["chosen_name"] == "shared"  # 仍能告诉用户是哪一个
    r = bob.post("/api/v1/me/ai/test", json={"target": "effective"})
    assert r.status_code == 409 and r.json()["data"]["reason"] == "public_closed"
    # 选了个人接口的 alice 不受影响
    assert data(_client("alice").get("/api/v1/ai/status"))["effective"]["source"] == "personal"


def test_personal_key_private(ai_root: Path, fake: list[str]) -> None:
    admin, alice, bob = _client("admin"), _client("alice"), _client("bob")
    a = data(alice.get("/api/v1/me/ai"))
    assert a["personal"]["api_key_set"] is True and a["personal"]["model"] == "alice-model"
    texts = [
        admin.get("/api/v1/ai/connections").text,
        admin.get("/api/v1/me/ai").text,
        bob.get("/api/v1/me/ai").text,
        alice.get("/api/v1/me/ai").text,
        admin.get("/api/v1/ai/settings").text,
    ]
    assert not any("alice-secret-key" in t or "shared-secret-key" in t for t in texts)
    assert not any("alice-model" in t for t in texts[:3])  # 管理员与别人看不到 alice 的个人接口
    # 测试个人接口：用的是 alice 自己的接口
    assert data(alice.post("/api/v1/me/ai/test", json={"target": "personal"}))["model"] == "alice-model"
    assert fake == ["personal:alice-model"]
    assert bob.post("/api/v1/me/ai/test").status_code == 409  # bob 没有个人接口
    # 改个人接口：不传 Key 保留原值；清除后不完整的 openai 仍可用（openai 不要求 Key）
    p = data(alice.put("/api/v1/me/ai", json={"personal": {"model": "alice-2"}}))["personal"]
    assert p["model"] == "alice-2" and p["api_key_set"]
    # 全局 API 令牌没有账号：可以查看，不能修改
    tok = _client()
    assert data(tok.get("/api/v1/me/ai", headers=H))["has_account"] is False
    r = tok.put("/api/v1/me/ai", headers=H, json={"choice": "none"})
    assert r.status_code == 409 and r.json()["code"] == 1003


def test_read_only_token_cannot_change(ai_root: Path) -> None:
    alice = _client("alice")
    ro = data(alice.post("/api/v1/tokens", json={"name": "ro", "read_only": True}))["token"]
    c = _client()
    h = {"Authorization": f"Bearer {ro}"}
    assert data(c.get("/api/v1/me/ai", headers=h))["choice"] == "personal"
    assert c.put("/api/v1/me/ai", headers=h, json={"choice": "none"}).status_code == 403


def test_calls_and_usage_scoped(ai_root: Path, fake: list[str]) -> None:
    admin, alice, bob = _client("admin"), _client("alice"), _client("bob")
    data(admin.post(f"/api/v1/ai/connections/{_conn_id(admin, 'internal')}/test"))
    data(alice.post("/api/v1/me/ai/test", json={"target": "effective"}))
    data(bob.post("/api/v1/me/ai/test", json={"target": "effective"}))
    assert fake == ["internal:fake-big", "personal:alice-model", "shared:fake-model"]
    all_calls = data(admin.get("/api/v1/ai/calls"))
    assert all_calls["scope"] == "all"
    assert [(c["user"], c["connection"]) for c in all_calls["calls"]] == [
        ("bob", "shared"),
        ("alice", "personal"),
        ("admin", "internal"),
    ]
    assert [c["user"] for c in data(admin.get("/api/v1/ai/calls?user=alice"))["calls"]] == ["alice"]
    b = data(bob.get("/api/v1/ai/calls?user=alice"))  # 普通账号的 user 参数无效：只看自己的
    assert b["scope"] == "mine" and [c["user"] for c in b["calls"]] == ["bob"]
    shared = _conn_id(admin, "shared")
    assert [c["user"] for c in data(admin.get(f"/api/v1/ai/calls?connection_id={shared}"))["calls"]] == ["bob"]
    u = data(admin.get("/api/v1/ai/usage"))
    assert u["scope"] == "all" and u["totals"]["calls"] == 3 and len(u["by_day"]) == 30
    assert {r["key"] for r in u["by_connection"]} == {"shared", "internal", "personal"}
    ub = data(bob.get("/api/v1/ai/usage"))
    assert ub["scope"] == "mine" and ub["totals"] == {"calls": 1, "errors": 0, "tokens_in": 5, "tokens_out": 2}
    assert data(admin.get("/api/v1/ai/connections"))["connections"][0]["usage"]["calls"] == 1
    r = bob.get("/api/v1/ai/usage/export?group=connection")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.content.decode("utf-8-sig").splitlines() == ["key,calls,errors,tokens_in,tokens_out", "shared,1,0,5,2"]
    assert "attachment" in r.headers["content-disposition"]
    assert bob.get("/api/v1/ai/usage?from=2026-13-01").status_code == 422


def test_legacy_settings_map_to_first_connection(ai_root: Path) -> None:
    admin = _client("admin")
    s = data(admin.get("/api/v1/ai/settings"))
    assert s["provider"] == "openai" and s["model"] == "fake-model" and s["deprecated"] is True
    data(admin.put("/api/v1/ai/settings", json={"model": "renamed"}))
    first = data(admin.get("/api/v1/ai/connections"))["connections"][0]
    assert first["name"] == "shared" and first["model"] == "renamed"
