"""翻译规则集接口（REQ-032）：保存 → 读取 → 合并写回保留注释 → 导出 → 普通用户也能保存 → 删除。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import TEST_TOKEN, TEST_USERS, prepare

pytestmark = pytest.mark.api


def test_save_get_export_delete(tmp_root: Path, request: pytest.FixtureRequest) -> None:
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    prepare("configured-users", request)
    client = TestClient(create_app())
    h = {"Authorization": f"Bearer {TEST_TOKEN}"}
    src = "# 注释保留\nid: flow\nnames:\n  - {match: exact, from: A, to: B}  # 行尾注释\n"
    r = client.put("/api/v1/translate-rules/flow", headers=h, json={"source": src})
    assert r.status_code == 200, r.text
    data = client.get("/api/v1/translate-rules/flow", headers=h).json()["data"]
    assert data["source"] == src and data["builtin"] is False
    rules = data["rules"]
    rules["names"].append({"match": "wildcard", "from": "X*", "to": "Y{1}"})
    r = client.put("/api/v1/translate-rules/flow", headers=h, json={"rules": rules})
    assert r.status_code == 200, r.text
    saved = r.json()["data"]["source"]
    assert "# 注释保留" in saved and "# 行尾注释" in saved and "Y{1}" in saved
    r = client.get("/api/v1/translate-rules/flow/export", headers=h)
    assert r.status_code == 200 and "Y{1}" in r.text
    assert 'filename="flow.yaml"' in r.headers["content-disposition"]
    ids = [i["id"] for i in client.get("/api/v1/translate-rules", headers=h).json()["data"]["items"]]
    assert "flow" in ids
    # 普通用户（会话登录）也能保存、删除规则集（D-0135）
    user = TestClient(create_app())
    pw = TEST_USERS["alice"][0]
    assert user.post("/api/v1/auth/login", json={"username": "alice", "password": pw}).status_code == 200
    r = user.put("/api/v1/translate-rules/alice-rules", json={"rules": {"names": []}})
    assert r.status_code == 200, r.text
    assert user.delete("/api/v1/translate-rules/alice-rules").status_code == 200
    assert client.delete("/api/v1/translate-rules/flow", headers=h).status_code == 200
    assert client.get("/api/v1/translate-rules/flow", headers=h).status_code == 404
