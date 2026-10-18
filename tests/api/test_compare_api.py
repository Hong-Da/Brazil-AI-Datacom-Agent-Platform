"""配置对比接口：导入同一设备的两个版本 → GET /devices/{id}/versions → 按版本 / 按设备对比。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import SAMPLES, TEST_TOKEN, prepare

pytestmark = pytest.mark.api


def test_versions_and_compare_by_version(tmp_root: Path, request: pytest.FixtureRequest) -> None:
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    prepare("configured-fullkb", request)
    client = TestClient(create_app())
    h = {"Authorization": f"Bearer {TEST_TOKEN}"}
    src = (SAMPLES / "cisco-iosxe-asr920-synthetic" / "pe-asr920-01.cfg").read_text(encoding="utf-8")
    changed = src.replace("  route-target import 64512:1\n", "").replace("EXPORT-LOOPBACK", "EXPORT-LO")
    files = [("files", ("v1.cfg", src.encode(), "text/plain")), ("files", ("v2.cfg", changed.encode(), "text/plain"))]
    r = client.post("/api/v1/configs", headers=h, files=files, data={"level": "basic"})
    assert r.status_code == 200, r.text
    dev = client.get("/api/v1/devices", headers=h).json()["data"]["devices"][0]

    r = client.get(f"/api/v1/devices/{dev['id']}/versions", headers=h)
    assert r.status_code == 200, r.text
    vers = r.json()["data"]["versions"]
    assert [v["seq"] for v in vers] == [2, 1] and vers[0]["latest"] and not vers[1]["latest"]
    assert {"id", "seq", "source_name", "collected_at", "kb_version", "lines", "latest"} <= set(vers[0])

    body = {"a": {"version_id": vers[1]["id"]}, "b": {"device_id": dev["id"]}}
    r = client.post("/api/v1/compare", headers=h, json=body)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    got = {(d["kind"], d["node"]) for d in data["diffs"]}
    assert got == {
        ("removed", "vrf.instance[RAN-2G]/af[ipv4]/rt[value=64512:1,direction=import]"),
        ("renamed", "rp.policy[EXPORT-LO]"),
    }
    assert data["renames"] == [{"schema": "rp.policy", "from": "EXPORT-LOOPBACK", "to": "EXPORT-LO", "similarity": 1.0}]
    assert data["a"]["version_id"] == vers[1]["id"] and data["b"]["version_id"] == vers[0]["id"]

    # 版本不属于给出的设备
    bad = {"a": {"device_id": dev["id"] + 1, "version_id": vers[1]["id"]}, "b": {"device_id": dev["id"]}}
    r = client.post("/api/v1/compare", headers=h, json=bad)
    assert r.status_code == 404 and r.json()["code"] == 1004
