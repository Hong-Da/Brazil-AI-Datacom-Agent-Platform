"""API 多步用例：用户账号（REQ-030）——Cookie 属性、锁定、登出与停用后会话失效、向导中创建管理员。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import TEST_TOKEN, TEST_USERS

pytestmark = pytest.mark.api
LOGIN = "/api/v1/auth/login"


def _client() -> Any:
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    return TestClient(create_app())


def _login(client: Any, name: str) -> Any:
    return client.post(LOGIN, json={"username": name, "password": TEST_USERS[name][0]})


def test_cookie_attributes(users_root: Path) -> None:
    c = _client()
    r = _login(c, "alice")
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("lmesh_session=")
    low = cookie.lower()
    assert "httponly" in low and "samesite=strict" in low and "path=/" in low and "max-age=43200" in low
    token = cookie.split(";", 1)[0].split("=", 1)[1]
    assert token not in r.text  # 令牌只在 Cookie 里，不在返回体


def test_lockout(users_root: Path) -> None:
    c = _client()
    for _ in range(4):
        r = c.post(LOGIN, json={"username": "alice", "password": "bad-password"})
        assert r.status_code == 401
    r = c.post(LOGIN, json={"username": "alice", "password": "bad-password"})
    assert r.status_code == 429 and r.json()["code"] == 1002
    assert r.json()["data"]["locked_until"]
    r = _login(c, "alice")  # 锁定期间正确密码也不行
    assert r.status_code == 429
    # 管理员解除锁定后可以登录
    h = {"Authorization": f"Bearer {TEST_TOKEN}"}
    assert c.put("/api/v1/users/alice", json={"unlock": True}, headers=h).status_code == 200
    assert _login(c, "alice").status_code == 200


def test_logout_and_disable_end_sessions(users_root: Path) -> None:
    c = _client()
    assert _login(c, "alice").status_code == 200
    assert c.get("/api/v1/auth/me").status_code == 200
    assert c.post("/api/v1/auth/logout").json()["data"]["logged_out"] is True
    assert c.get("/api/v1/auth/me").status_code == 401
    # 停用：已登录的会话立即失效
    alice = _client()
    assert _login(alice, "alice").status_code == 200
    admin = _client()
    assert _login(admin, "admin").status_code == 200
    assert admin.put("/api/v1/users/alice", json={"disabled": True}).status_code == 200
    assert alice.get("/api/v1/auth/me").status_code == 401
    r = _login(alice, "alice")
    assert r.status_code == 403 and r.json()["message"] == "账号已停用，请联系管理员"


def test_bad_bearer_beats_cookie(users_root: Path) -> None:
    c = _client()
    assert _login(c, "admin").status_code == 200
    r = c.get("/api/v1/auth/me", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_user_admin_endpoints_403(users_root: Path) -> None:
    c = _client()
    assert _login(c, "alice").status_code == 200
    for method, path, body in [
        ("POST", "/api/v1/ai/test", None),
        ("GET", "/api/v1/ai/settings", None),
        ("POST", "/api/v1/kb/rollback", {"ref": "0.1.0"}),
        ("POST", "/api/v1/users", {"username": "x1", "password": "Whatever-123"}),
        ("POST", "/api/v1/users/admin/password", {"password": "Whatever-123"}),
        ("DELETE", "/api/v1/users/admin", None),
    ]:
        r = c.request(method, path, json=body)
        assert r.status_code == 403, (path, r.text)
    assert c.get("/api/v1/summary").status_code == 200


def test_setup_with_admin_signs_in(tmp_root: Path) -> None:
    c = _client()
    bad = c.post("/api/v1/setup", json={"admin": {"username": "a", "password": "x"}, "dry_run": True})
    assert bad.status_code == 422
    assert set(bad.json()["data"]["errors"]) >= {"admin.username", "admin.password"}
    r = c.post(
        "/api/v1/setup",
        json={"values": {"security.api_token": TEST_TOKEN}, "admin": {"username": "admin", "password": "Admin-pass-1"}},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["admin"]["username"] == "admin" and data["session_expires_at"]
    assert "Admin-pass-1" not in r.text
    me = c.get("/api/v1/auth/me").json()["data"]
    assert me == {
        "username": "admin",
        "role": "admin",
        "via": "session",
        "expires_at": me["expires_at"],
        "read_only": False,
        "token_prefix": None,
    }
    assert c.get("/api/v1/auth/status").json()["data"]["has_users"] is True


def test_status_config_file_only_before_first_admin(configured_root: Path) -> None:
    """还没有账号时返回实际读取的配置文件（LMESH_ROOT 下）与 token_set；有账号后不再返回，令牌内容始终不返回。"""
    from lmesh.core import config, users

    c = _client()
    d = c.get("/api/v1/auth/status").json()["data"]
    assert Path(d["config_file"]) == (configured_root / "config" / "config.toml").resolve()
    assert d["token_set"] is True
    assert TEST_TOKEN not in str(d)
    users.create_user(config.load().database_url, "admin", "Admin-pass-1", "admin")
    d = c.get("/api/v1/auth/status").json()["data"]
    assert "config_file" not in d and "token_set" not in d
