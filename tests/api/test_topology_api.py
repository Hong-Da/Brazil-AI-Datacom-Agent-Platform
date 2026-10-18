"""拓扑与一致性接口：导入样本网络的五台设备 → GET /topology（全部、按名称与编号）→ POST /consistency（设备 + 上传混合）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import SAMPLES, TEST_TOKEN, prepare

pytestmark = pytest.mark.api
TOPO = SAMPLES / "topology"


def test_topology_and_consistency_of_imported_devices(tmp_root: Path, request: pytest.FixtureRequest) -> None:
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    prepare("configured-fullkb", request)
    client = TestClient(create_app())
    h = {"Authorization": f"Bearer {TEST_TOKEN}"}
    names = ["atn-a1.cfg", "atn-a2.cfg", "agg-01.cfg", "agg-02.cfg"]
    files = [("files", (n, (TOPO / n).read_bytes(), "text/plain")) for n in names]
    r = client.post("/api/v1/configs", headers=h, files=files, data={"level": "basic"})
    assert r.status_code == 200, r.text
    devs = {d["name"]: d["id"] for d in client.get("/api/v1/devices", headers=h).json()["data"]["devices"]}
    assert set(devs) == {"TOPO-ATN-A1", "TOPO-ATN-A2", "TOPO-AGG-01", "TOPO-AGG-02"}

    r = client.get("/api/v1/topology", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["summary"]["devices"] == 4 and data["summary"]["by_type"]["pw"] == 2
    node = next(n for n in data["nodes"] if n["id"] == "TOPO-AGG-01")
    assert node["device_id"] == devs["TOPO-AGG-01"] and node["version_id"] and node["lsr_id"] == "10.255.1.21"

    r = client.get(f"/api/v1/topology?devices=TOPO-ATN-A1,{devs['TOPO-AGG-01']}", headers=h)
    assert r.status_code == 200, r.text
    assert {n["id"] for n in r.json()["data"]["nodes"]} == {"TOPO-ATN-A1", "TOPO-AGG-01"}

    # 已导入的四台 + 上传的 RR：与样本目录的结果一致
    rr = (TOPO / "rr-01.cfg").read_text(encoding="utf-8")
    body = {"device_ids": list(devs.values()), "configs": [{"name": "rr-01.cfg", "text": rr}]}
    r = client.post("/api/v1/consistency", headers=h, json=body)
    assert r.status_code == 200, r.text
    res = r.json()["data"]
    assert res["summary"]["topology"]["links"] == 26 and res["summary"]["total"] == 13
    assert res["summary"]["by_rule"]["xd.bgp.auth"] == 1  # 导入时只脱敏（basic），口令仍然存在

    r = client.post("/api/v1/consistency", headers=h, json={"device_ids": [999]})
    assert r.status_code == 404 and r.json()["code"] == 1004
