"""用户工作空间与项目、权限、个人令牌的接口流程（M6，REQ-035 / REQ-036）。

- 项目：新建、成员（可编辑 / 只读）、只读成员写操作 403、非成员 404、管理员访问他人项目写审计、转交、复制、删除；
- 设备：项目内导入（私有）、公共设备库（管理员导入）、引用（跟随最新 / 固定版本）、复制为私有、解除引用；
- 兼容别名：旧路径落到默认项目，响应头 Deprecation 与 Link；
- 个人令牌：权限同本人、只读令牌不能写、撤销后 401；
- 知识库：普通用户 403、维护员可改、普通用户提交建议进审核队列。
权限矩阵（三种账号角色 × 项目角色 × 主要接口）见 test_permission_matrix。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import SAMPLES, TEST_TOKEN

pytestmark = pytest.mark.api
BASE = (SAMPLES / "change" / "atn-base.cfg").read_text(encoding="utf-8")
V2 = BASE.replace(" mtu 9000", " mtu 9216")
OTHER = (SAMPLES / "change" / "asr920-base.cfg").read_text(encoding="utf-8")
PW = "Pass-word-123"
API = "/api/v1"
ADMIN_H = {"Authorization": f"Bearer {TEST_TOKEN}"}


def _users(names: dict[str, str]) -> None:
    from lmesh.core import config, store, users

    url = config.load().database_url
    store.upgrade(url)
    for name, role in names.items():
        users.create_user(url, name, PW, role)


@pytest.fixture
def team(configured_root: Path) -> Path:
    """boss（管理员）、kbm（知识库维护员）、liwei / zhang / wang / chen（普通用户）。"""
    _users(
        {
            "boss": "admin",
            "kbm": "maintainer",
            "liwei": "user",
            "zhang": "user",
            "wang": "user",
            "chen": "user",
            "extra": "user",
        }
    )
    return configured_root


class Client:
    """一个账号的会话（Cookie 保存在各自的 TestClient 里）。"""

    def __init__(self, app: Any, user: str | None = None, token: str | None = None):
        from fastapi.testclient import TestClient

        self.c = TestClient(app)
        self.h: dict[str, str] = {}
        if user:
            r = self.c.post(f"{API}/auth/login", json={"username": user, "password": PW})
            assert r.status_code == 200, r.text
        if token:
            self.h = {"Authorization": f"Bearer {token}"}

    def req(self, method: str, path: str, **kw: Any) -> Any:
        return self.c.request(method, API + path, headers=self.h, **kw)

    def get(self, path: str, **kw: Any) -> Any:
        return self.req("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> Any:
        return self.req("POST", path, **kw)

    def put(self, path: str, **kw: Any) -> Any:
        return self.req("PUT", path, **kw)

    def delete(self, path: str, **kw: Any) -> Any:
        return self.req("DELETE", path, **kw)

    def upload(self, path: str, name: str, text: str) -> Any:
        return self.post(path, files=[("files", (name, text.encode(), "text/plain"))])


def _app() -> Any:
    from lmesh.api import create_app

    return create_app()


def _audit(app: Any) -> list[dict[str, Any]]:
    return Client(app, token=TEST_TOKEN).get("/admin/audit").json()["data"]["events"]


def test_project_flow(full_kb_root: Path, team: Path) -> None:
    app = _app()
    liwei, zhang, wang, chen, boss = (Client(app, u) for u in ("liwei", "zhang", "wang", "chen", "boss"))

    # 新建项目：标识全站唯一
    r = liwei.post("/projects", json={"name": "城域 OAM", "slug": "oam-vpn", "settings": {"style": "huawei"}})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["role"] == "owner" and r.json()["data"]["settings"]["style"] == "huawei"
    assert zhang.post("/projects", json={"name": "x", "slug": "oam-vpn"}).status_code == 409
    assert liwei.post("/projects", json={"name": "x", "slug": "Bad Slug"}).status_code == 422

    # 项目内导入：设备是项目私有的
    r = liwei.upload("/projects/oam-vpn/configs", "a.cfg", BASE)
    assert r.status_code == 200 and r.json()["data"]["files"][0]["ok"], r.text
    devs = liwei.get("/projects/oam-vpn/devices").json()["data"]["devices"]
    assert len(devs) == 1 and devs[0]["source"] == "private"
    dev_id = devs[0]["id"]

    # 非成员：项目与设备都是 404（不暴露是否存在）
    assert zhang.get("/projects/oam-vpn").status_code == 404
    assert zhang.get("/projects/oam-vpn/devices").status_code == 404
    assert zhang.get(f"/projects/{zhang_default(zhang)}/devices/{dev_id}/graph").status_code == 404

    # 成员：zhang 可编辑、wang 只读
    assert liwei.put("/projects/oam-vpn/members/zhang", json={"role": "edit"}).status_code == 200
    assert liwei.put("/projects/oam-vpn/members/wang", json={"role": "read"}).status_code == 200
    assert zhang.put("/projects/oam-vpn/members/chen", json={"role": "read"}).status_code == 403  # 只限属主
    mine = zhang.get("/projects").json()["data"]
    assert [p["slug"] for p in mine["shared"]] == ["oam-vpn"] and mine["shared"][0]["role"] == "edit"

    # 可编辑成员可以导入与改设置；只读成员只能看与计算
    assert zhang.upload("/projects/oam-vpn/configs", "b.cfg", V2).status_code == 200
    assert zhang.put("/projects/oam-vpn", json={"description": "两步下发"}).status_code == 200
    assert wang.get(f"/projects/oam-vpn/devices/{dev_id}/graph").status_code == 200
    assert wang.post("/projects/oam-vpn/check", json={"device_id": dev_id}).status_code == 200
    r = wang.upload("/projects/oam-vpn/configs", "c.cfg", OTHER)
    assert r.status_code == 403 and r.json()["code"] == 1006
    assert wang.delete(f"/projects/oam-vpn/devices/{dev_id}").status_code == 403
    assert wang.put("/projects/oam-vpn", json={"description": "x"}).status_code == 403
    assert wang.put("/projects/oam-vpn/rules/ref.orphan", json={"enabled": False, "reason": "x"}).status_code == 403

    # 项目级规则调整：只影响本项目
    r = zhang.put("/projects/oam-vpn/rules/ref.orphan", json={"severity": "error", "reason": "割接期间严格"})
    assert r.status_code == 200, r.text
    rules = zhang.get("/projects/oam-vpn/rules").json()["data"]
    hit = next(x for x in rules["rules"] if x["id"] == "ref.orphan")
    assert hit["effective"]["severity"] == "error" and rules["adjusted"] == 1
    assert zhang.put("/projects/oam-vpn/rules/no.such", json={"enabled": False, "reason": "x"}).status_code == 404
    assert zhang.put("/projects/oam-vpn/rules/ref.orphan", json={"enabled": False, "reason": ""}).status_code == 422

    # 管理员访问他人项目：完全权限，写审计（进入、修改）
    assert boss.get("/projects/oam-vpn/devices").status_code == 200
    assert boss.put("/projects/oam-vpn", json={"description": "管理员改"}).status_code == 200
    actions = [(e["actor"], e["action"], e["project"]) for e in _audit(app)]
    assert ("boss", "enter", "oam-vpn") in actions and ("boss", "write", "oam-vpn") in actions
    assert not any(a[0] == "liwei" for a in actions)  # 属主自己的访问不审计

    # 复制：只读成员也可以把项目复制为自己的新项目
    r = wang.post("/projects/oam-vpn/copy", json={"name": "我的副本", "slug": "wang-copy"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["role"] == "owner" and r.json()["data"]["counts"]["private"] == 1
    # 只读成员把设备复制到自己的项目（来源可读即可）
    r = wang.post("/projects/wang-copy/devices/copy-in", json={"device_id": dev_id})
    assert r.status_code == 200 and r.json()["data"]["renamed"] is True  # 同名时自动改名

    # 转交：原属主留作可编辑成员
    r = liwei.post("/projects/oam-vpn/transfer", json={"to": "zhang"})
    assert r.status_code == 200 and r.json()["data"]["owner"] == "zhang"
    assert liwei.get("/projects/oam-vpn").json()["data"]["role"] == "edit"
    assert liwei.post("/projects/oam-vpn/transfer", json={"to": "chen"}).status_code == 403

    # 删除：只限属主，确认标识必须一致；私有设备一起删除
    pre = zhang.get("/projects/oam-vpn/delete-preview").json()["data"]
    assert pre["counts"]["private_devices"] == 1 and pre["counts"]["versions"] == 2
    assert liwei.delete("/projects/oam-vpn", params={"confirm": "oam-vpn"}).status_code == 403
    assert zhang.delete("/projects/oam-vpn", params={"confirm": "wrong"}).status_code == 422
    assert zhang.delete("/projects/oam-vpn", params={"confirm": "oam-vpn"}).status_code == 200
    assert zhang.get("/projects/oam-vpn").status_code == 404
    assert wang.get("/projects/wang-copy/devices").json()["data"]["devices"]  # 复制出的项目不受影响


def zhang_default(c: Client) -> str:
    return str(c.get("/workspace").json()["data"]["default_project"])


def test_public_library_refs_and_pins(full_kb_root: Path, team: Path) -> None:
    app = _app()
    boss, liwei = Client(app, "boss"), Client(app, "liwei")
    # 只有管理员能导入公共设备库
    assert liwei.upload("/public-devices", "p.cfg", BASE).status_code == 403
    r = boss.upload("/public-devices", "p.cfg", BASE)
    assert r.status_code == 200 and r.json()["data"]["files"][0]["ok"], r.text
    v1 = r.json()["data"]["files"][0]["version_id"]
    pub = liwei.get("/public-devices").json()["data"]["devices"]
    assert len(pub) == 1 and pub[0]["versions"] == 1
    pid = pub[0]["id"]

    liwei.post("/projects", json={"name": "割接", "slug": "cutover"})
    liwei.post("/projects", json={"name": "巡检", "slug": "patrol"})
    assert liwei.post("/projects/cutover/refs", json={"device_id": pid, "version_id": v1}).status_code == 200
    assert liwei.post("/projects/patrol/refs", json={"device_id": pid}).status_code == 200
    # 公共库有新版本：固定的项目仍用 v1，跟随最新的项目用新版本
    v2 = boss.upload("/public-devices", "p2.cfg", V2).json()["data"]["files"][0]["version_id"]
    a = liwei.get("/projects/cutover/devices").json()["data"]["devices"][0]
    b = liwei.get("/projects/patrol/devices").json()["data"]["devices"][0]
    assert a["source"] == "public" and a["policy"] == "pin" and a["latest_version_id"] == v1 and a["newer_available"]
    assert a["pinned_seq"] == 1 and a["versions"] == 2  # 界面显示“固定在 v1”，公共库有 v2（M6-5）
    assert b["policy"] == "follow" and b["latest_version_id"] == v2 and b["pinned_seq"] is None
    g = liwei.get(f"/projects/cutover/devices/{pid}/graph").json()["data"]
    assert g["version_id"] == v1

    # 项目里不能改公共设备的快照（标签），只能解除引用
    assert liwei.put(f"/projects/cutover/devices/{pid}/history/{v1}/tag", json={"tag": "x"}).status_code == 403
    # 项目里同名导入被拒（设备名与引用的公共设备相同）
    r = liwei.upload("/projects/cutover/configs", "same.cfg", BASE)
    assert r.json()["data"]["files"][0]["ok"] is False
    # 复制为私有：同名时自动改名
    r = liwei.post("/projects/cutover/devices/copy-in", json={"device_id": pid, "version_id": v1})
    assert r.status_code == 200 and r.json()["data"]["renamed"]
    # 还有引用：管理员删除被拒，列出项目
    r = boss.delete(f"/public-devices/{pid}")
    assert r.status_code == 409 and set(r.json()["data"]["projects"]) == {"cutover", "patrol"}
    # 项目里“删除”引用的公共设备 = 解除引用
    r = liwei.delete(f"/projects/patrol/devices/{pid}")
    assert r.status_code == 200 and r.json()["data"]["unreferenced"] is True
    assert liwei.get("/projects/patrol/devices").json()["data"]["devices"] == []
    assert liwei.put(f"/projects/cutover/refs/{pid}", json={"version_id": None}).status_code == 200
    assert liwei.get("/projects/cutover/refs").json()["data"]["refs"][0]["policy"] == "follow"
    r = boss.delete(f"/public-devices/{pid}", params={"force": True})
    assert r.status_code == 200 and r.json()["data"]["unreferenced"] == ["cutover"]


def test_legacy_alias_and_default_project(full_kb_root: Path, team: Path) -> None:
    app = _app()
    liwei = Client(app, "liwei")
    r = liwei.upload("/configs", "a.cfg", BASE)
    assert r.status_code == 200
    assert r.headers.get("Deprecation") == "true"
    default = zhang_default(liwei)
    assert r.headers["Link"] == f'</api/v1/projects/{default}/configs>; rel="successor-version"'
    # 旧路径与默认项目的项目路径看到同样的设备
    old = liwei.get("/devices").json()["data"]["devices"]
    new = liwei.get(f"/projects/{default}/devices").json()["data"]["devices"]
    assert [d["id"] for d in old] == [d["id"] for d in new] and len(old) == 1
    assert "Deprecation" not in liwei.get(f"/projects/{default}/devices").headers
    # 另一个账号的默认项目看不到
    assert Client(app, "zhang").get("/devices").json()["data"]["devices"] == []
    # 改默认项目
    liwei.post("/projects", json={"name": "新项目", "slug": "newp"})
    assert liwei.put("/workspace/default-project", json={"project": "newp"}).status_code == 200
    assert liwei.get("/devices").json()["data"]["devices"] == []


def test_personal_tokens(full_kb_root: Path, team: Path) -> None:
    app = _app()
    liwei = Client(app, "liwei")
    liwei.post("/projects", json={"name": "p", "slug": "tokp"})
    r = liwei.post("/tokens", json={"name": "jenkins"})
    assert r.status_code == 200
    tok = r.json()["data"]
    assert tok["token"].startswith("lmp_") and tok["prefix"] == tok["token"][:8] and tok["read_only"] is False
    assert tok["expires_at"] is not None  # 默认 90 天
    ro = liwei.post("/tokens", json={"name": "audit", "read_only": True, "days": 0}).json()["data"]
    assert ro["expires_at"] is None

    rw = Client(app, token=tok["token"])
    assert rw.get("/auth/me").json()["data"]["username"] == "liwei"
    assert rw.upload("/projects/tokp/configs", "a.cfg", BASE).status_code == 200
    assert rw.get("/projects/oam-x/devices").status_code == 404  # 没有权限的项目
    assert rw.get("/users").status_code == 403  # 权限同本人（不是管理员）

    reader = Client(app, token=ro["token"])
    devs = reader.get("/projects/tokp/devices").json()["data"]["devices"]
    assert len(devs) == 1
    assert reader.post("/projects/tokp/check", json={"device_id": devs[0]["id"]}).status_code == 200  # 计算可以
    r = reader.upload("/projects/tokp/configs", "b.cfg", V2)
    assert r.status_code == 403 and r.json()["code"] == 1006
    assert reader.post("/projects", json={"name": "x"}).status_code == 403

    rows = liwei.get("/tokens").json()["data"]["tokens"]
    assert {t["prefix"] for t in rows} == {tok["prefix"], ro["prefix"]} and all("token" not in t for t in rows)
    used = next(t for t in rows if t["id"] == tok["id"])
    assert used["last_used_at"] and used["last_used_ip"]
    assert liwei.delete(f"/tokens/{tok['id']}").status_code == 409  # 有效的先撤销
    assert liwei.post(f"/tokens/{tok['id']}/revoke").status_code == 200
    assert rw.get("/auth/me").status_code == 401
    assert liwei.delete(f"/tokens/{tok['id']}").status_code == 200
    # 全局令牌没有账号
    assert Client(app, token=TEST_TOKEN).get("/tokens").status_code == 409


def test_kb_permissions_and_suggestions(full_kb_root: Path, team: Path) -> None:
    app = _app()
    liwei, kbm = Client(app, "liwei"), Client(app, "kbm")
    body = {"enabled": False}
    r = liwei.put("/kb/rules/ref.orphan", json=body)
    assert r.status_code == 403 and r.json()["code"] == 1006
    assert kbm.put("/kb/rules/ref.orphan", json=body).status_code == 200
    assert liwei.post("/kb/releases", json={"version": "9.9.9"}).status_code == 403
    assert kbm.get("/users").status_code == 403  # 维护员不是管理员

    r = liwei.post(
        "/kb/suggestions",
        json={
            "target": "l3vpn.vpn_instance.label_mode",
            "kind": "default",
            "current": "per-route",
            "proposed": "per-instance",
            "reason": "V800R022 起默认按实例",
        },
    )
    assert r.status_code == 200
    sid = r.json()["data"]["id"]
    mine = liwei.get("/kb/suggestions").json()["data"]["items"]
    assert [i["id"] for i in mine] == [sid] and mine[0]["payload"]["proposed"] == "per-instance"
    assert liwei.post(f"/review/{sid}", json={"action": "approve"}).status_code == 403
    r = kbm.post(f"/review/{sid}", json={"action": "reject", "note": "随单板不同"})
    assert r.status_code == 200 and r.json()["data"]["status"] == "rejected"
    assert liwei.get("/kb/suggestions").json()["data"]["items"][0]["note"] == "随单板不同"


def test_private_templates_and_rulesets(full_kb_root: Path, team: Path) -> None:
    app = _app()
    liwei, zhang, kbm = Client(app, "liwei"), Client(app, "zhang"), Client(app, "kbm")
    shared = liwei.get("/templates").json()["data"]["templates"]
    assert shared and all(t["scope"] == "shared" and not t["editable"] for t in shared)
    tid = shared[0]["id"]
    src = liwei.get(f"/templates/{tid}").json()["data"]["source"]
    # 普通用户不能改共享模板，可以复制为我的
    assert liwei.put(f"/templates/{tid}", json={"source": src}).status_code == 403
    r = liwei.post(f"/templates/{tid}/copy", json={"new_id": "liwei-tpl"})
    assert r.status_code == 200, r.text
    mine = [t for t in liwei.get("/templates").json()["data"]["templates"] if t["scope"] == "mine"]
    assert [t["id"] for t in mine] == ["liwei-tpl"]
    assert not any(t["id"] == "liwei-tpl" for t in zhang.get("/templates").json()["data"]["templates"])
    assert zhang.get("/templates/liwei-tpl").status_code == 404
    assert kbm.put(f"/templates/{tid}", json={"source": src}).status_code == 200  # 维护员可改共享模板
    assert liwei.delete("/templates/liwei-tpl").status_code == 200

    rules = {"names": [], "naming": [], "ports": []}
    assert liwei.put("/translate-rules/liwei-rs", json={"rules": rules}).status_code == 200
    items = {i["id"]: i for i in liwei.get("/translate-rules").json()["data"]["items"]}
    assert items["liwei-rs"]["scope"] == "mine" and items["liwei-rs"]["owner"] == "liwei"
    assert "liwei-rs" not in {i["id"] for i in zhang.get("/translate-rules").json()["data"]["items"]}
    assert zhang.put("/translate-rules/liwei-rs", json={"rules": rules}).status_code == 404
    # 转交项目时，项目用到的私有规则集复制给新属主
    liwei.post("/projects", json={"name": "p", "slug": "rsp", "settings": {"rule_set": "liwei-rs"}})
    r = liwei.post("/projects/rsp/transfer", json={"to": "zhang"})
    copied = r.json()["data"]["rule_set_copied"]
    assert copied and copied != "liwei-rs"
    zitems = {i["id"]: i for i in zhang.get("/translate-rules").json()["data"]["items"]}
    assert zitems[copied]["scope"] == "mine"
    assert zhang.get("/projects/rsp").json()["data"]["settings"]["rule_set"] == copied


def test_delete_user_with_projects(full_kb_root: Path, team: Path) -> None:
    app = _app()
    liwei = Client(app, "liwei")
    liwei.post("/projects", json={"name": "p", "slug": "lp"})
    liwei.upload("/projects/lp/configs", "a.cfg", BASE)
    admin = Client(app, token=TEST_TOKEN)
    r = admin.delete("/users/liwei")
    assert r.status_code == 409 and [p["slug"] for p in r.json()["data"]["projects"]] == ["lp"]
    r = admin.delete("/users/liwei", params={"transfer_to": "zhang"})
    assert r.status_code == 200, r.text
    zhang = Client(app, "zhang")
    assert zhang.get("/projects/lp").json()["data"]["role"] == "owner"


# ---------------------------------------------------------------- 权限矩阵


MATRIX_ROLES = ("admin", "maintainer", "owner", "edit", "read", "outsider")
# (说明, 方法, 路径, 期望：按 MATRIX_ROLES 顺序的 HTTP 状态)
MATRIX: list[tuple[str, str, str, tuple[int, ...]]] = [
    ("查看设备", "GET", "/projects/mx/devices", (200, 404, 200, 200, 200, 404)),
    ("检查（计算）", "POST", "/projects/mx/check", (200, 404, 200, 200, 200, 404)),
    ("导入", "POST", "/projects/mx/configs", (200, 404, 200, 200, 403, 404)),
    ("改项目设置", "PUT", "/projects/mx", (200, 404, 200, 200, 403, 404)),
    ("规则调整", "PUT", "/projects/mx/rules/ref.orphan", (200, 404, 200, 200, 403, 404)),
    ("重新解析本项目", "POST", "/projects/mx/devices/rebuild", (200, 404, 200, 200, 403, 404)),
    ("邀请成员", "PUT", "/projects/mx/members/extra", (200, 404, 200, 403, 403, 404)),
    ("复制项目", "POST", "/projects/mx/copy", (200, 404, 200, 200, 200, 404)),
    ("全部重新解析", "POST", "/devices/rebuild", (200, 403, 403, 403, 403, 403)),
    ("改共享规则", "PUT", "/kb/rules/ref.orphan", (200, 200, 403, 403, 403, 403)),
    ("公共设备库导入", "POST", "/public-devices", (200, 403, 403, 403, 403, 403)),
    ("所有项目", "GET", "/admin/projects", (200, 403, 403, 403, 403, 403)),
]


def test_permission_matrix(full_kb_root: Path, team: Path) -> None:
    app = _app()
    owner = Client(app, "liwei")
    owner.post("/projects", json={"name": "矩阵", "slug": "mx"})
    owner.put("/projects/mx/members/zhang", json={"role": "edit"})
    owner.put("/projects/mx/members/wang", json={"role": "read"})
    assert owner.upload("/projects/mx/configs", "a.cfg", BASE).status_code == 200
    dev_id = owner.get("/projects/mx/devices").json()["data"]["devices"][0]["id"]
    who = {
        "admin": Client(app, "boss"),
        "maintainer": Client(app, "kbm"),
        "owner": owner,
        "edit": Client(app, "zhang"),
        "read": Client(app, "wang"),
        "outsider": Client(app, "chen"),
    }
    bodies: dict[str, Any] = {
        "/projects/mx/check": {"json": {"device_id": dev_id}},
        "/projects/mx": {"json": {"description": "x"}},
        "/projects/mx/rules/ref.orphan": {"json": {"severity": "info", "reason": "矩阵"}},
        "/projects/mx/members/extra": {"json": {"role": "read"}},
        "/kb/rules/ref.orphan": {"json": {"enabled": True}},
        "/projects/mx/devices/rebuild": {},
        "/devices/rebuild": {},
    }
    failures = []
    for title, method, path, expect in MATRIX:
        for role, status in zip(MATRIX_ROLES, expect, strict=True):
            c = who[role]
            if path in ("/projects/mx/configs", "/public-devices"):
                r = c.upload(path, "m.cfg", BASE)
            elif path == "/projects/mx/copy":
                r = c.post(path, json={"name": f"copy-{role}"})
            else:
                r = c.req(method, path, **bodies.get(path, {}))
            if r.status_code != status:
                failures.append(f"{title} {role}: {r.status_code} != {status} {r.text[:200]}")
    assert not failures, "\n".join(failures)
