"""M4-7 接口流程：导入两台设备 → 按 device_ids / all 跑基线 → 导出基线报告（文件）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.api.test_report_api import H, _client, _import
from tests.conftest import SAMPLES, prepare


@pytest.mark.api
def test_baseline_devices_and_report(tmp_root: Path, request: pytest.FixtureRequest) -> None:
    prepare("configured-fullkb", request)
    client = _client()
    atn = _import(client, SAMPLES / "huawei-atn-v800r023" / "atn-access-01.cfg")
    asr = _import(client, SAMPLES / "cisco-iosxe-asr920-synthetic" / "pe-asr920-02-igp-mgmt.cfg")

    r = client.post("/api/v1/baseline", headers=H, json={"baseline": "strict", "device_ids": [atn["id"]]})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["devices"][0]["score"] == 84 and data["summary"]["devices"] == 1

    r = client.post("/api/v1/baseline", headers=H, json={"all": True})
    data = r.json()["data"]
    assert data["summary"]["devices"] == 2 and data["baseline"] == "basic"
    assert sorted(d["score"] for d in data["devices"]) == [95, 100]
    assert len(data["matrix"]["cells"][0]) == 2

    body = {"device_ids": [atn["id"], asr["id"]], "lang": "en", "format": "html", "style": "cisco"}
    r = client.post("/api/v1/baseline/report", headers=H, json=body)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    assert "baseline-basic-2-devices.en.html" in r.headers["content-disposition"]
    assert "Security Baseline Report" in r.text and "Devices × rules" in r.text
