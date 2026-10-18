"""M5 接口中不便写成用例数据的部分：AI 查询与生成（假的 AI 客户端）、文件下载（CSV / XLSX / 差异报告）、导入时重复内容不存新快照。"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from lmesh.core import ai
from tests.conftest import TEST_TOKEN, prepare

pytestmark = pytest.mark.api
H = {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture
def client(tmp_root: Path, request: pytest.FixtureRequest):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    prepare("configured-fullkb-history", request)
    return TestClient(create_app())


def _ai(monkeypatch: pytest.MonkeyPatch, replies: list[str]):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    monkeypatch.setenv("LMESH_AI__PROVIDER", "openai")
    monkeypatch.setenv("LMESH_AI__BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("LMESH_AI__MODEL", "fake-model")
    queue = list(replies)
    monkeypatch.setattr(ai, "provider_hook", lambda s, m, sy, p: ai.Reply(queue.pop(0), m, 10, 5))
    return TestClient(create_app())


def test_ask_with_fake_ai(client, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    answer = {
        "statements": [
            {"text": "MTU 是 9216。", "cites": [1], "facts": [{"row": 1, "field": "mtu", "value": "9216"}]},
            {"text": "描述是 X。", "cites": [1], "facts": [{"row": 1, "field": "description", "value": "X"}]},
        ]
    }
    c = _ai(
        monkeypatch, ['{"query": "FIND interface WHERE mtu = 9216 RETURN name, description, mtu"}', json.dumps(answer)]
    )
    assert c.get("/api/v1/ask/status", headers=H).json()["data"]["configured"]
    r = c.post("/api/v1/ask", headers=H, json={"question": "哪个接口 MTU 是 9216？", "lang": "en"})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["status"] == "answered" and d["result"]["rows"][0]["device"] == "ATN-CHANGE-01"
    assert [s["status"] for s in d["answer"]["statements"]] == ["passed", "corrected"]
    assert "UPLINK-TO-AGG-01" in d["answer"]["statements"][1]["corrected_text"]
    assert len(d["sent"]) == 2 and d["ai"]["calls"] == 2


def test_generate_with_fake_ai(client, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    good = "```\ninterface GigabitEthernet0/2/2.105\n vlan-type dot1q 105\n ip binding vpn-instance RAN\n ip address 10.3.5.1 255.255.255.252\n#\n```"
    c = _ai(monkeypatch, [good])
    r = c.post("/api/v1/generate", headers=H, json={"request": "新增 105 子接口", "device": "ATN-CHANGE-01"})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["verdict"] == "passed" and len(d["rounds"]) == 1 and "merged_text" not in d["final"]["guard"]


def test_downloads(client) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/export/table", headers=H, json={"preset": "ip", "format": "csv", "lang": "en"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert (
        r.content.startswith(b"\xef\xbb\xbfDevice,Interface")
        and "lmesh-ip-address-en.csv" in r.headers["content-disposition"]
    )
    r = client.post("/api/v1/export/table", headers=H, json={"preset": "bgp", "format": "xlsx", "lang": "pt-BR"})
    assert r.status_code == 200
    from openpyxl import load_workbook

    assert load_workbook(io.BytesIO(r.content)).sheetnames[0] == "Sobre"
    r = client.post("/api/v1/devices/1/history/report", headers=H, json={"lang": "en", "format": "md"})
    assert r.status_code == 200 and "history-ATN-CHANGE-01-1-2.en.md" in r.headers["content-disposition"]
    assert "Configuration Version Diff Report" in r.text and "mtu: 9000 → 9216" in r.text


def test_import_duplicate_via_api(client) -> None:  # type: ignore[no-untyped-def]
    from tests.conftest import SAMPLES

    text = (
        (SAMPLES / "change" / "atn-base.cfg")
        .read_bytes()
        .replace(b"UPLINK-TO-AGG", b"UPLINK-TO-AGG-01")
        .replace(b" mtu 9000", b" mtu 9216")
    )
    r = client.post("/api/v1/configs", headers=H, files=[("files", ("again.cfg", text, "text/plain"))])
    f = r.json()["data"]["files"][0]
    assert f["duplicate"] and f["version_id"] == 2
    tl = client.get("/api/v1/devices/1/history", headers=H).json()["data"]
    assert tl["count"] == 2 and tl["snapshots"][1]["imports"][-1]["source_kind"] == "api"


def test_history_diff_context(client) -> None:  # type: ignore[no-untyped-def]
    """context 取大值时原文差异只有一块且从第 1 行开始（界面在本地折叠）；默认仍只给变化附近的行。"""
    full = client.get("/api/v1/devices/1/history/diff?context=100000", headers=H).json()["data"]["text"]
    assert len(full["hunks"]) == 1 and full["hunks"][0]["a_start"] == 1
    last_a = max(x["a"] for x in full["hunks"][0]["lines"] if x["a"])
    assert last_a == full["hunks"][0]["a_len"]
    short = client.get("/api/v1/devices/1/history/diff", headers=H).json()["data"]["text"]
    assert sum(len(h["lines"]) for h in short["hunks"]) < len(full["hunks"][0]["lines"])
    assert client.get("/api/v1/devices/1/history/diff?context=-1", headers=H).status_code == 422


def test_guard_merged_text(client) -> None:  # type: ignore[no-untyped-def]
    """merged=true 时护栏另返回合并后的完整配置（交给增量变更用）；默认不返回。"""
    body = {
        "text": "interface GigabitEthernet0/2/2.105\n vlan-type dot1q 105\n description SITE-105\n#",
        "device": "ATN-CHANGE-01",
    }
    d = client.post("/api/v1/guard", headers=H, json=body).json()["data"]
    assert d["verdict"] == "passed" and "merged_text" not in d
    d = client.post("/api/v1/guard", headers=H, json={**body, "merged": True}).json()["data"]
    assert "sysname ATN-CHANGE-01" in d["merged_text"] and " description SITE-105" in d["merged_text"]


def test_generate_merged_text(client, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    good = "```\ninterface GigabitEthernet0/2/2.105\n vlan-type dot1q 105\n#\n```"
    c = _ai(monkeypatch, [good])
    d = c.post("/api/v1/generate", headers=H, json={"request": "x", "device": "ATN-CHANGE-01", "merged": True}).json()[
        "data"
    ]
    assert d["verdict"] == "passed" and "vlan-type dot1q 105" in d["final"]["guard"]["merged_text"]
