"""删除设备与配置版本接口的流程用例（REQ-038）：导入 → 普通用户删除一个版本 → 最后一个版本 409 → 删除设备 → 列表与时间线随之变化。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import SAMPLES, TEST_TOKEN, TEST_USERS

pytestmark = pytest.mark.api
BASE = (SAMPLES / "change" / "atn-base.cfg").read_text(encoding="utf-8")
V2 = BASE.replace(" mtu 9000", " mtu 9216")


def test_delete_flow_as_normal_user(full_kb_root: Path, users_root: Path) -> None:
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    client = TestClient(create_app())
    h = {"Authorization": f"Bearer {TEST_TOKEN}"}
    for name, text in (("a.cfg", BASE), ("b.cfg", V2)):
        r = client.post("/api/v1/configs", headers=h, files=[("files", (name, text.encode(), "text/plain"))])
        assert r.status_code == 200 and r.json()["data"]["files"][0]["ok"], r.text
    dev = client.get("/api/v1/devices", headers=h).json()["data"]["devices"][0]
    assert dev["versions"] == 2

    # 普通用户（会话登录）也可以删除
    pw = TEST_USERS["alice"][0]
    assert client.post("/api/v1/auth/login", json={"username": "alice", "password": pw}).status_code == 200
    r = client.delete(f"/api/v1/devices/{dev['id']}/versions/{dev['latest_version_id']}")
    assert r.status_code == 200, r.text
    left = r.json()["data"]["latest_version_id"]
    r = client.get(f"/api/v1/devices/{dev['id']}/history")
    assert r.json()["data"]["count"] == 1 and r.json()["data"]["snapshots"][0]["id"] == left

    r = client.delete(f"/api/v1/devices/{dev['id']}/versions/{left}")
    assert r.status_code == 409 and r.json()["code"] == 1003
    assert "不能单独删除" in r.json()["message"]

    r = client.delete(f"/api/v1/devices/{dev['id']}")
    assert r.status_code == 200 and r.json()["data"]["counts"]["versions"] == 1
    assert client.get("/api/v1/devices").json()["data"]["devices"] == []
    assert client.get(f"/api/v1/devices/{dev['id']}/history").status_code == 404
