"""检查与清理接口：导入设备后按设备检查、按 device_id 清理；运行时知识库的规则文件写错时返回 409 与问题清单。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import INPUTS, TEST_TOKEN, prepare

H = {"Authorization": f"Bearer {TEST_TOKEN}"}


def _client():  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    return TestClient(create_app())


@pytest.mark.api
def test_device_check_and_cleanup(tmp_root: Path, request: pytest.FixtureRequest) -> None:
    prepare("configured-fullkb", request)
    client = _client()
    cfg = (INPUTS / "configs" / "check" / "cisco-issues.cfg").read_bytes()
    r = client.post(
        "/api/v1/configs", headers=H, files=[("files", ("c.cfg", cfg, "text/plain"))], data={"level": "basic"}
    )
    assert r.status_code == 200, r.text
    dev = client.get("/api/v1/devices", headers=H).json()["data"]["devices"][0]
    res = client.get(f"/api/v1/devices/{dev['id']}/check?severity=error", headers=H).json()["data"]
    assert res["summary"]["has_errors"] and {f["severity"] for f in res["findings"]} == {"error"}
    assert res["summary"]["by_rule"]["bgp.peer.remote_as_missing"] == 1
    body = client.post("/api/v1/check", headers=H, json={"device_id": dev["id"], "domain": "vrf"}).json()["data"]
    assert {f["domain"] for f in body["findings"]} == {"vrf"}
    clean = client.post("/api/v1/cleanup", headers=H, json={"device_id": dev["id"]}).json()["data"]
    assert clean["fallbacks"] == 0 and clean["verify"]["ok"]
    assert clean["commands"][-1]["text"] == "no ip prefix-list ONLY-UNUSED seq 5 permit 10.0.0.0/8"


@pytest.mark.api
def test_broken_rules_409(tmp_root: Path, request: pytest.FixtureRequest) -> None:
    prepare("configured", request)
    client = _client()
    from lmesh.core import config, kbservice

    root = kbservice.runtime_root(config.load())
    (root / "rules" / "zz-bad.yaml").write_text(
        (INPUTS / "rules" / "bad" / "bad.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    r = client.get("/api/v1/kb/rules", headers={**H, "Accept-Language": "en"})
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["code"] == 1003 and body["message"].startswith("The rule files have 2 error(s)")
    codes = sorted(i["code"] for i in body["data"]["issues"])
    assert codes == ["rules.err.bad_severity", "rules.err.path_unknown"]
    assert client.post("/api/v1/check", headers=H, json={"text": "sysname R1"}).status_code == 409
