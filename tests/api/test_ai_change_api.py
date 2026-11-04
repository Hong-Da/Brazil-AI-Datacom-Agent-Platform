"""变更与割接组 AI skill 的接口（M8-4）：运行（假 AI）→ 采纳 → 由代码在采纳结果上计算的内容（合并后的变更脚本、
割接方案的预览与中英文导出、带 AI 写法的翻译结果）；只读成员能看不能运行；非成员 404。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lmesh.core import ai, config, importer, projects
from tests.conftest import TEST_TOKEN

pytestmark = pytest.mark.api
H = {"Authorization": f"Bearer {TEST_TOKEN}"}
P = "/api/v1/projects/lab"
TO = "cisco-iosxe-asr920-17.15"
PASSWORDS = {"alice": "Alice-pass-1", "bob": "Bob-pass-12", "carol": "Carol-pass-1"}


@pytest.fixture
def env(full_kb_root: Path, projects_root: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    monkeypatch.setenv("LMESH_AI__PROVIDER", "openai")
    monkeypatch.setenv("LMESH_AI__BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("LMESH_AI__MODEL", "fake-model")

    def login(name: str) -> Any:
        c = TestClient(create_app())
        r = c.post("/api/v1/auth/login", json={"username": name, "password": PASSWORDS[name]})
        assert r.status_code == 200, r.text
        return c

    clients = {n: login(n) for n in PASSWORDS}
    url = config.load().database_url
    alice = projects.cli_identity(url, "alice")
    with projects.use(projects.resolve(url, alice, "lab"), alice):
        did = next(d["id"] for d in importer.list_devices(url) if d["name"] == "ATN-CHANGE-01")
    return clients, did


def _fake(monkeypatch: pytest.MonkeyPatch, fn: Any) -> None:
    monkeypatch.setattr(ai, "provider_hook", lambda conn, m, s, p: ai.Reply(fn(s, p), m, 10, 5))


def _ref(prompt: str, label: str) -> str:
    for line in prompt.splitlines():
        parts = [x.strip() for x in line.split("|")]
        if len(parts) >= 3 and parts[2] == label and parts[0].startswith("n"):
            return parts[0]
    raise AssertionError(label)


def _run(c: Any, skill: str, params: dict[str, Any], device_id: int | None = None) -> dict[str, Any]:
    r = c.post(f"{P}/ai/suggestions/run", json={"skill": skill, "device_id": device_id, "params": params, "wait": True})
    assert r.status_code == 200, r.text
    return r.json()["data"]  # type: ignore[no-any-return]


def _items(c: Any, bid: int) -> list[dict[str, Any]]:
    r = c.get(f"{P}/ai/suggestions?batch_id={bid}")
    return sorted(r.json()["data"]["items"], key=lambda x: x["id"])


def test_intent_script_api(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    (cl, did) = env
    alice, bob, carol = cl["alice"], cl["bob"], cl["carol"]

    def reply(system: str, prompt: str) -> str:
        n = _ref(prompt, "GigabitEthernet0/2/2")
        edit = {"op": "set", "target": n, "attr": "interface.description", "value": "OAM-UPLINK"}
        item = {
            "category": "graph_edit",
            "kind": "edit",
            "title": f"Describe [[{n}]]",
            "content": {"edits": [edit]},
            "refs": [{"id": n}],
        }
        return json.dumps({"suggestions": [item]})

    _fake(monkeypatch, reply)
    params = {"intent": "Set the description of GigabitEthernet0/2/2 to OAM-UPLINK"}
    assert (
        bob.post(
            f"{P}/ai/suggestions/run", json={"skill": "intent-script", "device_id": did, "params": params}
        ).status_code
        == 403
    )
    b = _run(alice, "intent-script", params, did)
    assert b["status"] == "done" and b["counts"]["pass"] == 1
    sid = _items(alice, b["id"])[0]["id"]
    r = alice.post(f"{P}/ai/suggestions/{sid}/adopt", json={})
    assert r.status_code == 200 and r.json()["data"]["adopt_info"]["action"] == "script"
    plan = bob.get(f"{P}/ai/change/plan?batch_id={b['id']}")  # 只读成员可以查看
    assert plan.status_code == 200, plan.text
    d = plan.json()["data"]
    assert d["verify"] and d["rollback_verify"] and d["adopted"] == [sid]
    assert [x["text"].strip() for x in d["rows"] if x["k"] == "ai"] == ["description OAM-UPLINK"]
    assert carol.get(f"{P}/ai/change/plan?batch_id={b['id']}").status_code == 404
    # 采纳生成的项目脚本出现在项目脚本里
    groups = alice.get(f"{P}/check-projects").json()["data"]["projects"]
    assert any(g["name"].startswith("AI · ") and g["scripts"] == 2 for g in groups)  # 下发 + 回滚


def test_cutover_plan_api_export(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    (cl, did) = env
    alice = cl["alice"]

    def reply(system: str, prompt: str) -> str:
        sec = {
            "category": "plan_section",
            "kind": "overview",
            "title": "Overview",
            "content": {"section": "overview", "zh": "把 [[d1]] 换成 [[d2]]。", "en": "Replace [[d1]] with [[d2]]."},
            "refs": [{"id": "d1"}],
        }
        return json.dumps({"suggestions": [sec]})

    _fake(monkeypatch, reply)
    b = _run(alice, "cutover-plan", {"to": TO}, did)
    sid = _items(alice, b["id"])[0]["id"]
    pre = alice.get(f"{P}/ai/cutover-plan/{b['id']}?lang=zh-CN").json()["data"]
    assert pre["sections"][0]["parts"][0]["status"] == "pending" and pre["steps"][0]["commands"]
    assert alice.post(f"{P}/ai/suggestions/{sid}/adopt", json={}).status_code == 200
    zh = alice.get(f"{P}/ai/cutover-plan/{b['id']}/export?lang=zh-CN")
    en = alice.get(f"{P}/ai/cutover-plan/{b['id']}/export?lang=en")
    assert zh.status_code == 200 and "attachment" in zh.headers["content-disposition"]
    assert "把 ATN-CHANGE-01 换成" in zh.text and "Replace ATN-CHANGE-01 with" in en.text
    # 没有选新设备现有配置时标题写“替换为”；并入已导入设备时写“并入”（REQ-056-07）
    assert "割接方案：ATN-CHANGE-01 替换为" in zh.text and "Cutover plan: replace ATN-CHANGE-01 with" in en.text
    from lmesh.core import ai_suggest_change as asc

    assert asc._DOC_T["zh-CN"]["title_merge"].format(device="A", target="B") == "割接方案：A 并入 B"
    assert asc._DOC_T["en"]["title_merge"].format(device="A", target="B") == "Cutover plan: merge A into B"
    assert alice.get(f"{P}/ai/cutover-plan/{b['id']}/export?lang=fr").status_code == 422


def test_translate_gap_api_patch(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    (cl, did) = env
    alice = cl["alice"]

    def reply(system: str, prompt: str) -> str:
        item = {
            "category": "translate_eq",
            "kind": "equivalent",
            "title": "L68 → peer group",
            "content": {
                "item": "u1",
                "config": "router bgp 65000\n neighbor RR peer-group",
                "expect": ["bgp.peer_group"],
            },
            "refs": [{"id": "u1"}],
        }
        return json.dumps({"suggestions": [item]})

    _fake(monkeypatch, reply)
    b = _run(alice, "translate-gap", {"to": TO}, did)
    it = _items(alice, b["id"])[0]
    assert it["check_status"] == "warn" and it["check"]["reasons"][0]["code"] == "different_node"
    before = alice.post(f"{P}/translate", json={"device_id": did, "to": TO}).json()["data"]
    assert "ai_lines" not in before
    assert alice.post(f"{P}/ai/suggestions/{it['id']}/adopt", json={}).status_code == 200
    after = alice.post(f"{P}/translate", json={"device_id": did, "to": TO}).json()["data"]
    lines = after["text"].splitlines()
    assert [lines[n - 1] for n in after["ai_lines"]] == ["router bgp 65000", " neighbor RR peer-group"]
    assert any(u.get("ai") for u in after["unsupported"])
    got = alice.get(f"{P}/ai/translate-patches?device_id={did}&to={TO}").json()["data"]["items"]
    assert [p["line"] for p in got] == [68]
