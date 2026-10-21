"""创建项目的权限与加入项目（M9-8，REQ-050）：总开关与单独授权、不自动建默认项目、创建权限申请、“管理”角色的权限、
发现项目只给公开信息、加入申请（申请 / 撤回 / 通过改角色 / 拒绝）、邀请链接（只存哈希、直接加入、仍需审批、撤销、
过期）、通知数、审计；SQLite 与 PostgreSQL 各一次。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from lmesh.core import joining, projects, store, users
from lmesh.core.store.models import AuditEvent, Project, ProjectInvite

pytestmark = pytest.mark.unit
PW = "Pass-word-123"


@pytest.fixture
def url(db_url: str) -> Any:
    store.upgrade(db_url)
    for name, role in (("boss", "admin"), ("alice", "user"), ("bob", "user"), ("carol", "user"), ("dave", "user")):
        users.create_user(db_url, name, PW, role)
    yield db_url
    projects.set_create_open(None)


def _id(url: str, name: str) -> projects.Identity:
    return projects.cli_identity(url, name)


def _actions(url: str) -> list[str]:
    with store.session(url) as s:
        return [e.action for e in s.scalars(select(AuditEvent).order_by(AuditEvent.id))]


def _lab(url: str) -> projects.Scope:
    """alice 的项目 lab（总开关打开时建），bob 是“管理”成员，可被搜索。"""
    projects.set_create_open(True)
    alice = _id(url, "alice")
    projects.create_project(url, alice, {"name": "实验局", "slug": "lab", "description": "实验室"})
    sc = projects.resolve(url, alice, "lab")
    projects.update_project(url, sc, {"discoverable": True})
    projects.set_member(url, sc, "bob", "manage")
    projects.set_create_open(False)
    return sc


# ---------------------------------------------------------------- 创建权限


def test_create_permission_switch_and_grant(url: str) -> None:
    projects.set_create_open(False)
    carol = _id(url, "carol")
    with pytest.raises(projects.ProjectError) as e:
        projects.create_project(url, carol, {"name": "x"})
    assert e.value.key == "projects.create_forbidden" and e.value.kind == "forbidden"
    # 没有项目也不能创建：不自动建默认项目
    with pytest.raises(projects.ProjectError) as e:
        projects.default_project(url, carol)
    assert e.value.key == "projects.no_project"
    assert projects.default_project_or_none(url, carol) is None
    st = joining.creation_status(url, carol)
    assert st == {"can_create": False, "open": False, "admin": False, "granted": False, "request": None}
    # 管理员始终可以
    assert projects.create_project(url, _id(url, "boss"), {"name": "admin-p"})["owner"] == "boss"
    # 总开关打开：所有人可以
    projects.set_create_open(True)
    assert joining.creation_status(url, carol)["can_create"] is True
    projects.set_create_open(False)
    # 单独授权
    assert joining.set_create_permission(url, _id(url, "boss"), "carol", True)["can_create_projects"] is True
    assert users.get_user(url, "carol")["can_create_projects"] is True
    p = projects.create_project(url, carol, {"name": "c1", "slug": "c1"})
    assert p["owner"] == "carol"
    joining.set_create_permission(url, _id(url, "boss"), "carol", False)
    with pytest.raises(projects.ProjectError):
        projects.create_project(url, carol, {"name": "c2"})
    # 已有项目照常使用
    assert projects.resolve(url, carol, "c1").role == "owner"
    assert projects.default_project(url, carol)["slug"] == "c1"
    assert {"create.grant", "create.revoke"} <= set(_actions(url))


def test_register_without_permission_gets_no_project(url: str) -> None:
    projects.set_create_open(False)
    u = users.register(url, "erin", "Erin-pass-12", approval=False)
    assert projects.owned_projects(url, u["username"]) == []
    users.register(url, "fay", "Fay-pass-123", approval=True)
    users.approve(url, "fay")
    assert projects.owned_projects(url, "fay") == []
    projects.set_create_open(True)
    users.register(url, "gus", "Gus-pass-123", approval=False)
    assert len(projects.owned_projects(url, "gus")) == 1


def test_default_project_falls_back_to_joined_project(url: str) -> None:
    sc = _lab(url)
    projects.set_member(url, sc, "carol", "read")
    assert projects.default_project(url, _id(url, "carol"))["ref"] == "alice/lab"


def test_copy_project_needs_create_permission(url: str) -> None:
    sc = _lab(url)
    projects.set_member(url, sc, "carol", "read")
    carol = _id(url, "carol")
    with pytest.raises(projects.ProjectError) as e:
        projects.copy_project(url, projects.resolve(url, carol, "alice/lab"), carol, {"name": "copy"})
    assert e.value.key == "projects.create_forbidden"


def test_create_request_flow(url: str) -> None:
    projects.set_create_open(False)
    dave, boss = _id(url, "dave"), _id(url, "boss")
    r = joining.request_create(url, dave, "需要自己建项目")
    assert r["status"] == "pending" and r["username"] == "dave"
    with pytest.raises(projects.ProjectError) as e:
        joining.request_create(url, dave)
    assert e.value.key == "create_request.pending"
    assert joining.notifications(url, boss)["create_requests"] == 1
    assert joining.notifications(url, dave)["create_requests"] == 0
    assert joining.cancel_create_request(url, dave)["status"] == "cancelled"
    r = joining.request_create(url, dave)
    out = joining.decide_create(url, boss, r["id"], True)
    assert out["status"] == "approved" and out["decided_by"] == "boss"
    assert joining.creation_status(url, dave)["can_create"] is True
    with pytest.raises(projects.ProjectError) as e:
        joining.decide_create(url, boss, r["id"], False)
    assert e.value.key == "create_request.decided"
    with pytest.raises(projects.ProjectError) as e:
        joining.request_create(url, dave)
    assert e.value.key == "create_request.not_needed"
    # 拒绝
    r2 = joining.request_create(url, _id(url, "carol"), "")
    assert joining.decide_create(url, boss, r2["id"], False, "暂不开放")["note"] == "暂不开放"
    assert joining.list_create_requests(url) == []
    assert len(joining.list_create_requests(url, None)) == 3
    with pytest.raises(projects.ProjectError) as e:
        joining.request_create(url, projects.SYSTEM)
    assert e.value.key == "joining.need_account"
    acts = _actions(url)
    assert {"create.request", "create.cancel", "create.grant", "create.decline"} <= set(acts)


# ---------------------------------------------------------------- “管理”角色


def test_manage_role_permissions(url: str) -> None:
    sc = _lab(url)
    bob = projects.resolve(url, _id(url, "bob"), "alice/lab")
    assert bob.role == "manage" and bob.can_write and bob.can_manage and not bob.can_own
    projects.set_member(url, bob, "carol", "edit")
    projects.set_member(url, bob, "dave", "manage")
    projects.remove_member(url, bob, "dave")
    for fn in (
        lambda: projects.delete_project(url, bob, "lab"),
        lambda: projects.transfer(url, bob, "carol"),
        lambda: projects.update_project(url, bob, {"slug": "lab2"}),
    ):
        with pytest.raises(projects.ProjectError) as e:
            fn()
        assert e.value.key == "projects.owner_only"
    projects.update_project(url, bob, {"discoverable": False, "name": "实验局 2"})
    carol = projects.resolve(url, _id(url, "carol"), "alice/lab")
    with pytest.raises(projects.ProjectError) as e:
        projects.set_member(url, carol, "dave", "read")
    assert e.value.key == "projects.manager_only"
    with pytest.raises(projects.ProjectError):
        projects.update_project(url, carol, {"discoverable": True})
    assert projects.list_projects(url, _id(url, "bob"))["shared"][0]["role"] == "manage"
    assert sc.can_own


# ---------------------------------------------------------------- 发现与申请


def test_discover_shows_public_info_only(url: str) -> None:
    _lab(url)
    projects.set_create_open(True)
    projects.create_project(url, _id(url, "dave"), {"name": "私有项目", "slug": "secret"})
    d = joining.discover(url, _id(url, "carol"))
    assert [p["ref"] for p in d["projects"]] == ["alice/lab"]
    card = d["projects"][0]
    assert set(card) == {"id", "ref", "name", "description", "owner", "devices", "my_status", "my_role", "request_id"}
    assert card["my_status"] == "none" and card["owner"] == "alice" and card["devices"] == 0
    assert joining.discover(url, _id(url, "carol"), "ALICE")["count"] == 1
    assert joining.discover(url, _id(url, "carol"), "nothing")["count"] == 0
    assert joining.discover(url, _id(url, "bob"))["projects"][0]["my_status"] == "member"
    assert joining.discover(url, _id(url, "alice"))["projects"][0]["my_status"] == "owner"
    # 不可被搜索的项目：申请时当作不存在
    with pytest.raises(projects.ProjectError) as e:
        joining.request_join(url, _id(url, "carol"), "dave/secret")
    assert e.value.kind == "not_found"


def test_join_request_flow(url: str) -> None:
    sc = _lab(url)
    carol, bob = _id(url, "carol"), _id(url, "bob")
    with pytest.raises(projects.ProjectError) as e:
        joining.request_join(url, carol, "alice/lab", "manage")
    assert e.value.key == "joining.bad_role"
    r = joining.request_join(url, carol, "alice/lab", "read", "参与评审")
    assert r["status"] == "pending" and r["project"]["ref"] == "alice/lab" and r["via"] == "search"
    with pytest.raises(projects.ProjectError) as e:
        joining.request_join(url, carol, sc.project_id)
    assert e.value.key == "joining.already_pending"
    assert joining.discover(url, carol)["projects"][0]["my_status"] == "pending"
    # 通知：属主与管理成员各看到 1 个；不相关的人 0 个
    assert joining.notifications(url, _id(url, "alice"))["join_requests"] == 1
    n = joining.notifications(url, bob)
    assert n["join_requests"] == 1 and n["by_project"][0]["ref"] == "alice/lab"
    assert joining.notifications(url, _id(url, "dave"))["total"] == 0
    # 只读成员不能审批
    projects.set_member(url, sc, "dave", "read")
    with pytest.raises(projects.ProjectError):
        joining.list_requests(url, projects.resolve(url, _id(url, "dave"), "alice/lab"))
    # 管理成员通过并改角色
    bsc = projects.resolve(url, bob, "alice/lab")
    assert [x["username"] for x in joining.list_requests(url, bsc)] == ["carol"]
    out = joining.decide(url, bsc, r["id"], True, "edit")
    assert out["status"] == "approved" and out["decided_role"] == "edit" and out["decided_by"] == "bob"
    assert projects.resolve(url, carol, "alice/lab").role == "edit"
    assert projects.default_project(url, carol)["ref"] == "alice/lab"
    with pytest.raises(projects.ProjectError) as e:
        joining.decide(url, bsc, r["id"], False)
    assert e.value.key == "joining.request_decided"
    with pytest.raises(projects.ProjectError) as e:
        joining.request_join(url, carol, "alice/lab")
    assert e.value.key == "joining.already_member"
    # 拒绝与撤回
    projects.remove_member(url, sc, "dave")
    r2 = joining.request_join(url, _id(url, "dave"), "alice/lab")
    assert joining.decide(url, sc, r2["id"], False, note="人数已满")["note"] == "人数已满"
    assert joining.discover(url, _id(url, "dave"))["projects"][0]["my_status"] == "declined"
    r3 = joining.request_join(url, _id(url, "dave"), "alice/lab")
    with pytest.raises(projects.ProjectError):
        joining.cancel_request(url, carol, r3["id"])  # 不是自己的
    assert joining.cancel_request(url, _id(url, "dave"), r3["id"])["status"] == "cancelled"
    mine = joining.my_requests(url, _id(url, "dave"))
    assert [x["status"] for x in mine] == ["cancelled", "declined"]
    assert {"join.request", "join.approve", "join.decline", "join.cancel"} <= set(_actions(url))


# ---------------------------------------------------------------- 邀请链接


def test_invites(url: str) -> None:
    sc = _lab(url)
    bsc = projects.resolve(url, _id(url, "bob"), "alice/lab")
    inv = joining.create_invite(url, bsc, "edit", 3, False, "二组")
    token = inv["token"]
    assert token.startswith("lmi_") and inv["path"] == f"/invite/{token}" and inv["state"] == "active"
    with store.session(url) as s:  # 数据库里没有令牌明文
        row = s.get(ProjectInvite, inv["id"])
        assert row is not None and row.token_hash != token and token not in (row.prefix, row.note)
    info = joining.invite_info(url, _id(url, "carol"), token)
    assert info["project"]["name"] == "实验局" and info["role"] == "edit" and info["state"] == "active"
    assert info["my_status"] == "none" and "member_list" not in info["project"]
    out = joining.accept_invite(url, _id(url, "carol"), token)
    assert out == {"status": "joined", "project": "alice/lab", "role": "edit"}
    assert joining.accept_invite(url, _id(url, "carol"), token)["status"] == "member"
    # 仍需审批的链接：提交申请
    inv2 = joining.create_invite(url, sc, "read", 7, True)
    out = joining.accept_invite(url, _id(url, "dave"), inv2["token"], "来自邮件")
    assert out["status"] == "pending"
    req = joining.list_requests(url, sc)[0]
    assert req["via"] == "invite" and req["invite_prefix"] == inv2["prefix"] and req["reason"] == "来自邮件"
    assert joining.accept_invite(url, _id(url, "dave"), inv2["token"])["request_id"] == out["request_id"]
    rows = {i["id"]: i for i in joining.list_invites(url, sc)}
    assert rows[inv["id"]]["uses"] == 1 and rows[inv2["id"]]["uses"] == 1
    # 撤销与过期
    assert joining.revoke_invite(url, bsc, inv["id"])["state"] == "revoked"
    with pytest.raises(projects.ProjectError) as e:
        joining.accept_invite(url, _id(url, "boss"), token)
    assert e.value.key == "invites.revoked"
    with store.session(url) as s:
        row = s.get(ProjectInvite, inv2["id"])
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    assert joining.invite_info(url, _id(url, "boss"), inv2["token"])["state"] == "expired"
    with pytest.raises(projects.ProjectError) as e:
        joining.accept_invite(url, _id(url, "boss"), inv2["token"])
    assert e.value.key == "invites.expired"
    with pytest.raises(projects.ProjectError) as e:
        joining.invite_info(url, _id(url, "boss"), "lmi_nope")
    assert e.value.kind == "not_found"
    with pytest.raises(projects.ProjectError) as e:
        joining.create_invite(url, sc, "read", 91)
    assert e.value.key == "invites.bad_days"
    with pytest.raises(projects.ProjectError):
        joining.create_invite(url, projects.resolve(url, _id(url, "carol"), "alice/lab"))  # 可编辑成员不能
    assert {"invite.create", "invite.join", "invite.revoke"} <= set(_actions(url))


def test_delete_project_removes_requests_and_invites(url: str) -> None:
    sc = _lab(url)
    joining.request_join(url, _id(url, "carol"), "alice/lab")
    joining.create_invite(url, sc)
    projects.delete_project(url, sc, "lab")
    with store.session(url) as s:
        assert s.scalar(select(Project.id)) is None
        assert s.scalar(select(ProjectInvite.id)) is None
    assert joining.my_requests(url, _id(url, "carol")) == []
