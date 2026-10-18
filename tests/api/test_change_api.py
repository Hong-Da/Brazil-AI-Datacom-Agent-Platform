"""M4-3 接口流程：导入同一设备的两个版本 → 按配置版本生成变更脚本 → 导出变更报告（中文 HTML / English Markdown）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import SAMPLES, TEST_TOKEN, prepare

H = {"Authorization": f"Bearer {TEST_TOKEN}"}
CHG = SAMPLES / "change"


def _client():  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    return TestClient(create_app())


def _import(client: Any, path: Path, name: str) -> int:
    r = client.post(
        "/api/v1/configs",
        headers=H,
        files=[("files", (name, path.read_bytes(), "text/plain"))],
        data={"level": "basic"},
    )
    assert r.status_code == 200, r.text
    return max(d["latest_version_id"] for d in client.get("/api/v1/devices", headers=H).json()["data"]["devices"])


@pytest.mark.api
def test_change_by_version_and_report(tmp_root: Path, request: pytest.FixtureRequest) -> None:
    prepare("configured-fullkb", request)
    client = _client()
    v1 = _import(client, CHG / "atn-base.cfg", "atn-change-01.cfg")
    v2 = _import(client, CHG / "atn-del-peer.cfg", "atn-change-02.cfg")
    body = {"current": {"version_id": v1}, "target": {"version_id": v2}}
    r = client.post("/api/v1/change", headers=H, json=body)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["verify"]["ok"] and data["rollback"]["verify"]["ok"]
    assert [d["action"] for d in data["ops"]] == ["delete", "delete", "delete"]
    assert data["ops"][-1]["text"] == "undo peer 10.255.0.102"
    assert data["current"]["version_id"] == v1

    for lang, fmt, title in (("zh-CN", "html", "配置变更报告"), ("en", "md", "Configuration Change Report")):
        rep = client.post("/api/v1/change/report", headers=H, json={**body, "report_lang": lang, "format": fmt})
        assert rep.status_code == 200, rep.text
        assert title in rep.text and "undo peer 10.255.0.102" in rep.text
        assert "attachment" in rep.headers["content-disposition"]
        assert f".{lang}.{fmt}" in rep.headers["content-disposition"]


@pytest.mark.api
def test_change_version_not_found(tmp_root: Path, request: pytest.FixtureRequest) -> None:
    prepare("configured-fullkb", request)
    r = _client().post(
        "/api/v1/change", headers=H, json={"current": {"version_id": 999}, "target": {"text": "sysname A"}}
    )
    assert r.status_code == 404 and r.json()["code"] == 1004
