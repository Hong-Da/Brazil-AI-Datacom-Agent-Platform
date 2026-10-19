"""用户自助注册（REQ-039）的接口：默认关闭时注册被拒、管理员开关与审核设置（写入配置文件）、注册后待审核不能登录、
批准后能登录并有默认项目、拒绝即删除、不需审核时注册即登录、同一来源地址的频率限制、审计记录。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmesh.core import users
from tests.api.test_projects_api import PW, Client, _app, _audit, _users
from tests.conftest import TEST_TOKEN

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def _fresh_limiter() -> None:
    users.REGISTER_LIMITER.reset()


def test_registration_flow(configured_root: Path) -> None:
    _users({"boss": "admin"})
    app = _app()
    anon = Client(app)
    boss = Client(app, "boss")

    # 默认关闭：登录页不显示入口，注册接口明确拒绝
    st = anon.get("/auth/status").json()["data"]
    assert st["registration"] == {"open": False, "approval": True}
    r = anon.post("/auth/register", json={"username": "newbie", "password": PW})
    assert r.status_code == 403 and r.json()["code"] == 1006

    # 普通用户不能改设置；管理员开启（写入配置文件 [auth]）
    _users({"liwei": "user"})
    assert Client(app, "liwei").put("/auth/settings", json={"registration": True}).status_code == 403
    r = boss.put("/auth/settings", json={"registration": True, "rate_per_hour": 3})
    assert r.status_code == 200 and r.json()["data"]["registration"] is True
    assert r.json()["data"]["approval"] is True and r.json()["data"]["rate_per_hour"] == 3
    assert "registration = true" in (configured_root / "config" / "config.toml").read_text(encoding="utf-8")
    assert anon.get("/auth/status").json()["data"]["registration"]["open"] is True

    # 注册：需要审核，不发会话；待审核不能登录
    r = anon.post("/auth/register", json={"username": "newbie", "password": PW})
    assert r.status_code == 200 and r.json()["data"] == {"username": "newbie", "status": "pending"}
    assert "lmesh_session" not in r.cookies
    r = anon.post("/auth/login", json={"username": "newbie", "password": PW})
    assert r.status_code == 403 and "审核" in r.json()["message"]
    r = anon.post("/auth/register", json={"username": "newbie", "password": PW})
    assert r.status_code == 409  # 用户名已存在
    assert anon.post("/auth/register", json={"username": "x", "password": PW}).status_code == 422

    # 管理员：待审核列表、批准；批准后能登录并有自己的默认项目
    lst = boss.get("/users", params={"status": "pending"}).json()["data"]
    assert [u["username"] for u in lst["users"]] == ["newbie"] and lst["pending"] == 1
    assert lst["users"][0]["origin"] == "register"
    assert boss.post("/users/newbie/approve").status_code == 200
    assert boss.post("/users/newbie/approve").status_code == 409
    me = Client(app, "newbie")
    projs = me.get("/projects").json()["data"]
    assert [p["ref"] for p in projs["mine"]] == ["default"] and projs["default_project"] == "default"
    assert me.get("/projects/default/devices").status_code == 200

    # 频率限制：同一地址每小时 3 次（已用 3 次：newbie、重复、x）
    r = anon.post("/auth/register", json={"username": "fourth", "password": PW})
    assert r.status_code == 429 and r.json()["data"] == {"per_hour": 3}
    users.REGISTER_LIMITER.reset()

    # 拒绝：删除待审核账号，用户名可以再注册；只能拒绝待审核的
    assert anon.post("/auth/register", json={"username": "spam", "password": PW}).status_code == 200
    assert boss.post("/users/spam/reject").json()["data"]["deleted"] is True
    assert boss.post("/users/newbie/reject").status_code == 409
    assert anon.post("/auth/register", json={"username": "spam", "password": PW}).status_code == 200

    # 不需要审核：注册即登录
    assert boss.put("/auth/settings", json={"approval": False}).status_code == 200
    quick = Client(app)
    r = quick.post("/auth/register", json={"username": "quick", "password": PW})
    assert r.status_code == 200 and r.json()["data"]["status"] == "active"
    assert quick.get("/auth/me").json()["data"]["username"] == "quick"

    # 审计：注册、批准、拒绝、改设置（不含密码）
    events = [(e["actor"], e["action"]) for e in _audit(app)]
    for want in [("newbie", "user.register"), ("boss", "user.approve"), ("boss", "user.reject")]:
        assert want in events
    assert ("boss", "settings.registration") in events
    assert all(PW not in str(e) for e in _audit(app))

    # 关闭后：注册被拒，已有的待审核账号仍可处理
    assert boss.put("/auth/settings", json={"registration": False}).status_code == 200
    assert anon.post("/auth/register", json={"username": "late", "password": PW}).status_code == 403
    assert boss.post("/users/spam/approve").status_code == 200
    # 全局令牌也能读设置
    s = Client(app, token=TEST_TOKEN).get("/auth/settings").json()["data"]
    assert s["registration"] is False and s["approval"] is False
