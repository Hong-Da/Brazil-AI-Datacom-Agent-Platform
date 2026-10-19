"""Web 界面用的接口：概况、设备状态与重建、Schema / Profile 编辑、草稿区、未识别行送审、AI 设置。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import INPUTS, TEST_TOKEN, prepare

pytestmark = pytest.mark.api
H = {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture
def client(tmp_root: Path, request: pytest.FixtureRequest):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    prepare("configured-fullkb", request)
    return TestClient(create_app())


def data(r):  # type: ignore[no-untyped-def]
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_summary_devices_rebuild(client) -> None:  # type: ignore[no-untyped-def]
    s = data(client.get("/api/v1/summary", headers=H))
    assert s["devices"]["count"] == 0 and s["kb"]["profiles"] == 5 and s["regression"] is None
    files = [
        ("files", (n, (INPUTS / "configs" / v / "basic.cfg").read_bytes(), "text/plain"))
        for n, v in (("hw.cfg", "huawei"), ("cs.cfg", "cisco"))
    ]
    data(client.post("/api/v1/configs", headers=H, files=files, data={"level": "basic"}))
    devs = data(client.get("/api/v1/devices", headers=H))["devices"]
    assert len(devs) == 2 and all(d["parsed"] and d["roundtrip"] is True and d["unknown"] == 0 for d in devs)
    r = data(client.post(f"/api/v1/devices/{devs[0]['id']}/rebuild", headers=H))
    assert r["parsed"] and r["roundtrip"] is True
    assert client.post("/api/v1/devices/999/rebuild", headers=H).status_code == 404
    s = data(client.get("/api/v1/summary", headers=H))
    assert s["devices"]["count"] == 2 and len(s["devices"]["recent"]) == 2


def test_schema_edit_and_usage(client) -> None:  # type: ignore[no-untyped-def]
    tree = data(client.get("/api/v1/kb/schema", headers=H))
    assert sum(len(d["nodes"]) for d in tree["domains"]) >= 90
    u = data(client.get("/api/v1/kb/schema/nodes/vrf.instance.af.rd/usage", headers=H))
    assert u["blocking"] and u["cards"]
    r = client.delete("/api/v1/kb/schema/nodes/vrf.instance.af.rd", headers=H)
    assert r.status_code == 409 and r.json()["data"]["cards"]
    body = {"parent": "vrf.instance", "type": "text", "semantic": {"zh-CN": "备注", "en": "Note"}}
    assert data(client.put("/api/v1/kb/schema/nodes/vrf.instance.note", headers=H, json=body))["created"]
    assert data(client.get("/api/v1/kb/schema/nodes/vrf.instance.note/usage", headers=H))["blocking"] is False
    assert data(client.delete("/api/v1/kb/schema/nodes/vrf.instance.note", headers=H))["deleted"]
    bad = client.put("/api/v1/kb/schema/nodes/vrf.x", headers=H, json={"type": "nope"})
    assert bad.status_code == 422
    orphan = client.put("/api/v1/kb/schema/nodes/vrf.y", headers=H, json={"type": "text", "parent": "no.such"})
    assert orphan.status_code == 422


def test_profiles_entries_compare_create(client) -> None:  # type: ignore[no-untyped-def]
    rows = data(client.get("/api/v1/kb/profiles", headers=H))["profiles"]
    r023 = next(p for p in rows if p["id"] == "huawei-atn-v800r023")
    assert r023["inherits"] == "huawei-atn-v800r025" and r023["coverage"] > 0.5
    d = data(client.get("/api/v1/kb/profiles/huawei-atn-v800r023", headers=H))
    mtu = next(e for e in d["entries"] if e["node"] == "interface.mtu")
    assert mtu["inherited"] and mtu["origin"] == "huawei-atn-v800r025"
    data(client.put("/api/v1/kb/profiles/huawei-atn-v800r023/entries/interface.mtu", headers=H, json={"default": 9000}))
    d = data(client.get("/api/v1/kb/profiles/huawei-atn-v800r023", headers=H))
    mtu = next(e for e in d["entries"] if e["node"] == "interface.mtu")
    assert mtu["default"] == 9000 and not mtu["inherited"] and mtu["manual"]
    cmp = data(client.get("/api/v1/kb/profile-compare?a=huawei-atn-v800r025&b=huawei-atn-v800r023", headers=H))
    assert next(r for r in cmp["rows"] if r["node"] == "interface.mtu")["kind"] == "default"
    data(client.delete("/api/v1/kb/profiles/huawei-atn-v800r023/entries/interface.mtu", headers=H))
    assert client.delete("/api/v1/kb/profiles/huawei-atn-v800r023/entries/interface.mtu", headers=H).status_code == 422
    new = {"id": "huawei-atn-v800r026", "inherits": "huawei-atn-v800r025", "version": "V800R026"}
    assert data(client.post("/api/v1/kb/profiles", headers=H, json=new))["profile"] == "huawei-atn-v800r026"
    assert client.post("/api/v1/kb/profiles", headers=H, json=new).status_code == 422
    assert client.get("/api/v1/kb/profiles/nope", headers=H).status_code == 404


def test_draft_extractors_tasks(client) -> None:  # type: ignore[no-untyped-def]
    d = data(client.get("/api/v1/kb/draft", headers=H))
    assert d["base"] is None and isinstance(d["commits"], list)
    ex = data(client.get("/api/v1/kb/extractors", headers=H))["extractors"]
    assert {"huawei-vrp8-md", "cisco-iosxe-md"} <= {e["name"] for e in ex}
    assert data(client.get("/api/v1/tasks", headers=H))["tasks"] == []


def test_unknown_to_review(client) -> None:  # type: ignore[no-untyped-def]
    cfg = b"sysname X\n#\ninterface GigabitEthernet0/2/1\n mtu notanumber\n#\nreturn\n"
    data(client.post("/api/v1/configs", headers=H, files=[("files", ("x.cfg", cfg, "text/plain"))]))
    pats = data(client.get("/api/v1/unknown-lines", headers=H))["patterns"]
    assert pats, "应有未识别行"
    p = pats[0]["pattern"]
    r = data(client.post("/api/v1/unknown-lines/review", headers=H, json={"patterns": [p]}))
    assert r["added"] == 1
    assert data(client.post("/api/v1/unknown-lines/review", headers=H, json={"patterns": [p]}))["skipped"] == [p]
    assert data(client.get("/api/v1/unknown-lines/states", headers=H))["states"][p] == "pending"
    item = data(client.post(f"/api/v1/review/{r['ids'][0]}", headers=H, json={"action": "approve"}))
    assert item["status"] == "approved"


def test_ai_settings_roundtrip(client) -> None:  # type: ignore[no-untyped-def]
    s = data(client.get("/api/v1/ai/settings", headers=H))
    assert s["provider"] == "" and s["api_key_set"] is False
    body = {"provider": "openai", "base_url": "http://127.0.0.1:11434/v1", "model": "qwen", "api_key": "sk-secret"}
    s = data(client.put("/api/v1/ai/settings", headers=H, json=body))
    assert s["provider"] == "openai" and s["api_key_set"] and "sk-secret" not in str(s)
    assert data(client.get("/api/v1/ai/status", headers=H))["configured"] is True
    s = data(client.put("/api/v1/ai/settings", headers=H, json={"model": "qwen2"}))
    assert s["api_key_set"] and s["model"] == "qwen2"  # 不传 API Key 时保留原值
    assert client.put("/api/v1/ai/settings", headers=H, json={"provider": "bogus"}).status_code == 422
    # 令牌仍然有效（只改了 AI 分组）
    assert client.get("/api/v1/config", headers=H).status_code == 200
