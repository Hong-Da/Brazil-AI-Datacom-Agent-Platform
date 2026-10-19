"""项目标识按属主唯一（M6 评审改选，2026-10-19）的接口：两个用户的同名项目互不影响、成员访问别人的同名项目
（属主%2F标识 / 属主~标识）、只写标识时的歧义（409，data.candidates）、管理员与全局令牌、转交时新属主重名、
旧路径的 Link 头使用规范引用。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.api.test_projects_api import BASE, OTHER, Client, _app, team  # noqa: F401
from tests.conftest import TEST_TOKEN

pytestmark = pytest.mark.api


def test_same_slug_for_two_owners(full_kb_root: Path, team: Path) -> None:  # noqa: F811
    app = _app()
    liwei, zhang, wang, boss = (Client(app, u) for u in ("liwei", "zhang", "wang", "boss"))
    glob = Client(app, token=TEST_TOKEN)

    # 两个人都建 oam-vpn：互不影响
    a = liwei.post("/projects", json={"name": "李伟 OAM", "slug": "oam-vpn"})
    b = zhang.post("/projects", json={"name": "张 OAM", "slug": "oam-vpn"})
    assert a.status_code == 200 and b.status_code == 200, b.text
    assert a.json()["data"]["ref"] == "oam-vpn" and a.json()["data"]["full_ref"] == "liwei/oam-vpn"
    r = liwei.post("/projects", json={"name": "再建", "slug": "oam-vpn"})
    assert r.status_code == 409 and r.json()["code"] == 1003
    assert liwei.upload("/projects/oam-vpn/configs", "a.cfg", BASE).json()["data"]["files"][0]["ok"]
    assert zhang.upload("/projects/oam-vpn/configs", "b.cfg", OTHER).json()["data"]["files"][0]["ok"]
    la = liwei.get("/projects/oam-vpn/devices").json()["data"]["devices"]
    za = zhang.get("/projects/oam-vpn/devices").json()["data"]["devices"]
    assert len(la) == 1 and len(za) == 1 and la[0]["id"] != za[0]["id"]
    # 不是成员：写全也看不到
    assert liwei.get("/projects/zhang%2Foam-vpn").status_code == 404

    # 成员访问别人的同名项目：只写标识仍是自己的；写全（%2F 或 ~）才是别人的
    assert zhang.put("/projects/oam-vpn/members/liwei", json={"role": "read"}).status_code == 200
    r = liwei.get("/projects/zhang%2Foam-vpn")
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["owner"] == "zhang" and d["role"] == "read" and d["ref"] == "zhang/oam-vpn"
    assert liwei.get("/projects/zhang~oam-vpn/devices").json()["data"]["devices"][0]["id"] == za[0]["id"]
    assert liwei.get("/projects/zhang%2Foam-vpn/devices").json()["data"]["devices"][0]["id"] == za[0]["id"]
    assert liwei.get("/projects/oam-vpn/devices").json()["data"]["devices"][0]["id"] == la[0]["id"]
    shared = liwei.get("/projects").json()["data"]["shared"]
    assert [(p["slug"], p["ref"]) for p in shared] == [("oam-vpn", "zhang/oam-vpn")]
    # 只读：写操作仍 403
    assert liwei.upload("/projects/zhang%2Foam-vpn/configs", "c.cfg", BASE).status_code == 403

    # 只在一个能访问的项目里匹配：唯一就用它；两个都能访问：歧义 409，列出候选
    assert liwei.put("/projects/oam-vpn/members/wang", json={"role": "read"}).status_code == 200
    r = wang.get("/projects/oam-vpn")
    assert r.status_code == 200 and r.json()["data"]["ref"] == "liwei/oam-vpn"
    assert zhang.put("/projects/oam-vpn/members/wang", json={"role": "read"}).status_code == 200
    r = wang.c.get("/api/v1/projects/oam-vpn/devices", headers={"Accept-Language": "zh-CN"})
    assert r.status_code == 409 and r.json()["code"] == 1003
    assert r.json()["data"] == {"candidates": ["liwei/oam-vpn", "zhang/oam-vpn"]}
    assert "属主/标识" in r.json()["message"]

    # 管理员与全局令牌：自己（第一个管理员）没有时在全部项目里找，多个时歧义；写全可以进入
    for c in (boss, glob):
        assert c.get("/projects/oam-vpn").status_code == 409
        assert c.get("/projects/liwei%2Foam-vpn").json()["data"]["role"] == "admin"
    assert boss.post("/projects", json={"name": "管理员的", "slug": "oam-vpn"}).status_code == 200
    for c in (boss, glob):
        d = c.get("/projects/oam-vpn").json()["data"]
        assert d["owner"] == "boss" and d["ref"] == "oam-vpn"

    # 转交：新属主已有同名标识时 409（提示改名，data.suggested），带 slug 改名后成功
    liwei.post("/projects", json={"name": "B", "slug": "beta"})
    zhang.post("/projects", json={"name": "B", "slug": "beta"})
    r = liwei.post("/projects/beta/transfer", json={"to": "zhang"})
    assert r.status_code == 409 and r.json()["data"] == {"suggested": "beta-2"}
    r = liwei.post("/projects/beta/transfer", json={"to": "zhang", "slug": "beta-li"})
    assert r.status_code == 200 and r.json()["data"]["full_ref"] == "zhang/beta-li"
    assert liwei.get("/projects/zhang%2Fbeta-li").json()["data"]["role"] == "edit"


def test_legacy_link_uses_ref(full_kb_root: Path, team: Path) -> None:  # noqa: F811
    app = _app()
    liwei = Client(app, "liwei")
    r = liwei.upload("/configs", "a.cfg", BASE)
    default = liwei.get("/workspace").json()["data"]["default_project"]
    assert default == "default"  # 每个人的默认项目都可以叫 default
    assert r.headers["Link"] == '</api/v1/projects/default/configs>; rel="successor-version"'
