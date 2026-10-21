"""创建项目的权限与加入项目（M9-8，REQ-050）的接口流程：系统设置的总开关立即生效、自助注册不自动建项目、
没有项目的账号的工作空间、邀请链接只返回一次令牌、通过申请后项目出现在“共享给我的”、审计记录。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import JOIN_TOKEN, TEST_TOKEN

pytestmark = pytest.mark.api
API = "/api/v1"
ADMIN_H = {"Authorization": f"Bearer {TEST_TOKEN}"}


def _client(user: str | None = None, pw: str | None = None) -> Any:
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    c = TestClient(create_app())
    if user:
        r = c.post(f"{API}/auth/login", json={"username": user, "password": pw})
        assert r.status_code == 200, r.text
    return c


def test_switch_applies_immediately(joining_root: Path) -> None:
    dave = _client("dave", "Dave-pass-12")
    assert dave.post(f"{API}/projects", json={"name": "a"}).status_code == 403
    ws = dave.get(f"{API}/workspace").json()["data"]
    assert ws["default_project"] is None and ws["can_create"] is False
    admin = _client()
    r = admin.put(f"{API}/settings", headers=ADMIN_H, json={"values": {"auth.user_create_projects": True}})
    assert r.status_code == 200, r.text
    # 同一进程里的其他会话立即按新开关判断
    assert dave.get(f"{API}/me/create-permission").json()["data"]["open"] is True
    assert dave.post(f"{API}/projects", json={"name": "a", "slug": "proj-a"}).status_code == 200
    admin.put(f"{API}/settings", headers=ADMIN_H, json={"values": {"auth.user_create_projects": False}})
    assert dave.post(f"{API}/projects", json={"name": "b"}).status_code == 403
    assert dave.get(f"{API}/projects/proj-a").status_code == 200  # 已有的项目照常使用


def test_registration_does_not_create_project(joining_root: Path) -> None:
    from lmesh.core import config, projects

    config.update_file({"auth.registration": True, "auth.registration_approval": False})
    c = _client()
    r = c.post(f"{API}/auth/register", json={"username": "newbie", "password": "Newbie-pass-1"})
    assert r.status_code == 200, r.text
    assert projects.owned_projects(config.load().database_url, "newbie") == []
    assert c.get(f"{API}/projects").json()["data"]["mine"] == []


def test_invite_and_request_flow(joining_root: Path) -> None:
    alice = _client("alice", "Alice-pass-1")
    r = alice.post(f"{API}/projects/lab/invites", json={"role": "edit", "days": 1, "requires_approval": False})
    inv = r.json()["data"]
    assert inv["token"].startswith("lmi_") and inv["path"].endswith(inv["token"])
    listed = alice.get(f"{API}/projects/lab/invites").json()["data"]["invites"]
    assert all("token" not in i for i in listed)
    dave = _client("dave", "Dave-pass-12")
    assert dave.post(f"{API}/invites/{inv['token']}/accept", json={}).json()["data"]["status"] == "joined"
    shared = dave.get(f"{API}/projects").json()["data"]["shared"]
    assert [(p["ref"], p["role"]) for p in shared] == [("alice/lab", "edit")]
    assert dave.get(f"{API}/workspace").json()["data"]["default_project"] == "alice/lab"
    # carol 的申请：属主通过后出现在共享给我的
    carol = _client("carol", "Carol-pass-1")
    assert alice.post(f"{API}/projects/lab/join-requests/1/approve", json={}).status_code == 200
    assert carol.get(f"{API}/projects").json()["data"]["shared"][0]["role"] == "read"
    assert carol.get(f"{API}/me/join-requests").json()["data"]["requests"][0]["status"] == "approved"
    # 管理员的通知：创建权限申请 1 个
    admin = _client("admin", "Admin-pass-1")
    n = admin.get(f"{API}/me/notifications").json()["data"]
    assert n["create_requests"] == 1 and n["total"] == 1
    actions = {e["action"] for e in admin.get(f"{API}/admin/audit").json()["data"]["events"]}
    assert {"invite.create", "invite.join", "join.approve", "join.request", "create.request"} <= actions


def test_global_token_and_readonly_token(joining_root: Path) -> None:
    from lmesh.core import config, tokens

    c = _client()
    r = c.post(f"{API}/invites/{JOIN_TOKEN}/accept", headers=ADMIN_H, json={})
    assert r.status_code == 409 and r.json()["code"] == 1003  # 全局令牌没有账号
    tok = tokens.create(config.load().database_url, "dave", "ro", True, 7)["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert c.get(f"{API}/discover", headers=h).status_code == 200
    assert c.post(f"{API}/invites/{JOIN_TOKEN}/accept", headers=h, json={}).status_code == 403
