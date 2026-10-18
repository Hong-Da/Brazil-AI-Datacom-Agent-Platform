"""M2-5 接口流程：导入设备 → 检查 → 忽略发现 → 统计变化 → 导出报告（文件）→ 取消忽略；规则开关写回后检查生效；按版本检查。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import INPUTS, SAMPLES, TEST_TOKEN, prepare

H = {"Authorization": f"Bearer {TEST_TOKEN}"}


def _client():  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    return TestClient(create_app())


def _import(client: Any, path: Path) -> dict[str, Any]:
    r = client.post(
        "/api/v1/configs",
        headers=H,
        files=[("files", (path.name, path.read_bytes(), "text/plain"))],
        data={"level": "basic"},
    )
    assert r.status_code == 200, r.text
    devs = client.get("/api/v1/devices", headers=H).json()["data"]["devices"]
    return next(d for d in devs if d["latest_version_id"] == max(x["latest_version_id"] for x in devs))


@pytest.mark.api
def test_ignore_and_check_report(tmp_root: Path, request: pytest.FixtureRequest) -> None:
    prepare("configured-fullkb", request)
    client = _client()
    dev = _import(client, INPUTS / "configs" / "check" / "cisco-issues.cfg")
    before = client.get(f"/api/v1/devices/{dev['id']}/check", headers=H).json()["data"]
    orphan = next(f for f in before["findings"] if f["rule"] == "ref.orphan")
    assert orphan["ignored"] is False and before["summary"]["ignored"] == 0

    body = {"device_id": dev["id"], "rule": "ref.orphan", "node": orphan["node"], "reason": "保留给新业务"}
    r = client.post("/api/v1/check/ignores", headers=H, json=body)
    assert r.status_code == 200, r.text
    ig = r.json()["data"]
    assert ig["created"] and ig["reason"] == "保留给新业务"

    after = client.post("/api/v1/check", headers=H, json={"device_id": dev["id"]}).json()["data"]
    hit = next(f for f in after["findings"] if f["node"] == orphan["node"] and f["rule"] == "ref.orphan")
    assert hit["ignored"] and hit["ignore_reason"] == "保留给新业务" and hit["ignore_id"] == ig["id"]
    s0, s1 = before["summary"], after["summary"]
    assert s1["ignored"] == 1 and s1["total"] == s0["total"]
    assert s1["by_severity"]["warning"] == s0["by_severity"]["warning"] - 1
    listed = client.get(f"/api/v1/check/ignores?device_id={dev['id']}", headers=H).json()["data"]["ignores"]
    assert [x["id"] for x in listed] == [ig["id"]]

    # 检查报告：直接返回文件
    rep = client.post(
        "/api/v1/reports",
        headers=H,
        json={"kind": "check", "lang": "zh-CN", "format": "html", "check": {"device_id": dev["id"]}},
    )
    assert rep.status_code == 200, rep.text
    assert rep.headers["content-type"].startswith("text/html")
    disp = rep.headers["content-disposition"]
    assert disp.startswith("attachment;") and f"check-{dev['name']}.zh-CN.html" in disp
    text = rep.text
    assert text.startswith("<!doctype html>") and "<h1>配置检查报告</h1>" in text
    assert "已忽略的发现 (1)" in text and "保留给新业务" in text and "<h2>清理脚本</h2>" in text
    md = client.post(
        "/api/v1/reports",
        headers=H,
        json={"kind": "check", "lang": "en", "format": "md", "check": {"device_id": dev["id"], "severity": "error"}},
    )
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert md.text.startswith("# Configuration Check Report") and "| Minimum severity | Error |" in md.text

    # 取消忽略后统计恢复
    assert client.delete(f"/api/v1/check/ignores/{ig['id']}", headers=H).json()["data"]["deleted"]
    again = client.get(f"/api/v1/devices/{dev['id']}/check", headers=H).json()["data"]
    assert again["summary"]["ignored"] == 0 and again["summary"]["by_severity"] == s0["by_severity"]


@pytest.mark.api
def test_rule_switch_takes_effect(tmp_root: Path, request: pytest.FixtureRequest) -> None:
    prepare("configured-fullkb", request)
    client = _client()
    text = (INPUTS / "configs" / "check" / "huawei-issues.cfg").read_text(encoding="utf-8")
    first = client.post("/api/v1/check", headers=H, json={"text": text}).json()["data"]
    assert first["summary"]["by_rule"]["ref.orphan"] == 4
    r = client.put("/api/v1/kb/rules/ref.orphan", headers=H, json={"enabled": False})
    assert r.status_code == 200 and r.json()["data"]["enabled"] is False
    r = client.put("/api/v1/kb/rules/vrf.rd_without_rt", headers=H, json={"severity": "error"})
    assert r.json()["data"]["severity"] == "error"
    second = client.post("/api/v1/check", headers=H, json={"text": text}).json()["data"]
    assert "ref.orphan" not in second["summary"]["by_rule"]
    assert next(f for f in second["findings"] if f["rule"] == "vrf.rd_without_rt")["severity"] == "error"
    rules = {x["id"]: x for x in client.get("/api/v1/kb/rules", headers=H).json()["data"]["rules"]}
    assert rules["ref.orphan"]["enabled"] is False and rules["ref.orphan"]["source"] == "builtin"
    assert rules["vrf.rd_without_rt"]["severity"] == "error" and rules["vrf.rd_without_rt"]["source"] == "common.yaml"
    # 修改已提交到运行时知识库
    from lmesh.core import config, kbservice
    from lmesh.core.kb import repo

    msgs = [str(c["message"]) for c in repo.history(kbservice.runtime_root(config.load()))]
    assert msgs[0].startswith("修改检查规则 vrf.rd_without_rt") and msgs[1].startswith("修改检查规则 ref.orphan")


@pytest.mark.api
def test_compare_report_and_version_check(tmp_root: Path, request: pytest.FixtureRequest) -> None:
    prepare("configured-fullkb", request)
    client = _client()
    a = _import(client, SAMPLES / "cisco-iosxe-asr920-synthetic" / "pe-asr920-01.cfg")
    b = _import(client, INPUTS / "configs" / "report" / "pe-asr920-02.cfg")
    assert a["id"] != b["id"]
    body = {"a": {"device_id": a["id"]}, "b": {"device_id": b["id"]}, "hide_identity": True, "include_raw": True}
    cmp = client.post("/api/v1/compare", headers=H, json=body).json()["data"]
    assert cmp["summary"]["total"] == 1 and cmp["summary"]["hidden_identity"] == 11

    rep = client.post(
        "/api/v1/reports", headers=H, json={"kind": "compare", "lang": "en", "format": "md", "compare": body}
    )
    assert rep.status_code == 200, rep.text
    name = f"compare-{a['name']}_{a['latest_version_id']}-{b['name']}_{b['latest_version_id']}.en.md"
    assert re.search(r"filename\*=UTF-8''" + re.escape(name.replace("_", "%40")), rep.headers["content-disposition"])
    md = rep.text
    assert md.startswith("# Configuration Comparison Report")
    assert f"| Config version | #{a['latest_version_id']} (" in md and "| Hide identity differences | Yes |" in md
    assert "Hidden identity differences: 11" in md and "`9216` · explicit · line 39" in md

    # 按版本检查：版本必须属于这台设备
    ok = client.get(f"/api/v1/devices/{a['id']}/check?version_id={a['latest_version_id']}", headers=H)
    assert ok.status_code == 200 and ok.json()["data"]["device"] == a["name"]
    bad = client.get(f"/api/v1/devices/{a['id']}/check?version_id={b['latest_version_id']}", headers=H)
    assert bad.status_code == 404

    # 按版本取原文与配置图
    t = client.get(f"/api/v1/devices/{b['id']}/versions/{b['latest_version_id']}/text", headers=H)
    assert t.status_code == 200 and "hostname PE-ASR920-02" in t.json()["data"]["text"]
    assert t.json()["data"]["version_id"] == b["latest_version_id"] and t.json()["data"]["source_name"]
    other = client.get(f"/api/v1/devices/{a['id']}/versions/{b['latest_version_id']}/text", headers=H)
    assert other.status_code == 404
    gr = client.get(f"/api/v1/devices/{a['id']}/graph?version_id={a['latest_version_id']}", headers=H)
    assert gr.status_code == 200 and gr.json()["data"]["version_id"] == a["latest_version_id"]
    assert (
        client.get(f"/api/v1/devices/{a['id']}/graph?version_id={b['latest_version_id']}", headers=H).status_code == 404
    )
