"""AI skill 接口中不便写成用例数据的部分（REQ-033）：假的 AI 客户端下的问答 → 反馈 → 回归集、试运行、进化（同步与后台任务）与批准。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from lmesh.core import ai
from tests.conftest import TEST_TOKEN, prepare

pytestmark = pytest.mark.api
H = {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture
def client(tmp_root: Path, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    prepare("configured-fullkb-history", request)
    request.getfixturevalue("users_root")
    monkeypatch.setenv("LMESH_AI__PROVIDER", "openai")
    monkeypatch.setenv("LMESH_AI__BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("LMESH_AI__MODEL", "fake-model")
    return TestClient(create_app())


def _fake(monkeypatch: pytest.MonkeyPatch, fn) -> list[tuple[str, str]]:  # type: ignore[no-untyped-def]
    calls: list[tuple[str, str]] = []

    def hook(s, m, system, prompt):  # type: ignore[no-untyped-def]
        calls.append((system, prompt))
        return ai.Reply(fn(system, prompt), m, 10, 5)

    monkeypatch.setattr(ai, "provider_hook", hook)
    return calls


def test_ask_feedback_regression_and_evolve(client, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    answer = {"statements": [{"text": "MTU 1", "cites": [1], "facts": [{"row": 1, "field": "mtu", "value": "1"}]}]}
    replies = ['{"query": "FIND interface WHERE mtu = 9216 RETURN name, mtu"}', json.dumps(answer)]
    _fake(monkeypatch, lambda s, p: replies.pop(0))
    r = client.post("/api/v1/ask", headers=H, json={"question": "MTU?", "lang": "en"})
    assert r.status_code == 200, r.text
    runs = r.json()["data"]["skill_runs"]
    assert [(x["skill"], x["status"]) for x in runs] == [("ask-query", "passed"), ("ask-answer", "corrected")]
    # 普通账号对结果反馈（会话 Cookie）
    alice = TestClient(create_app())
    assert alice.post("/api/v1/auth/login", json={"username": "alice", "password": "Alice-pass-1"}).status_code == 200
    fb = alice.post(
        "/api/v1/ai/skills/feedback",
        json={"run_id": runs[0]["run_id"], "rating": "down", "correction": "FIND interface"},
    )
    assert fb.status_code == 200, fb.text
    assert fb.json()["data"]["case"]["kind"] == "regression"
    undo = alice.post("/api/v1/ai/skills/feedback", json={"run_id": runs[1]["run_id"], "rating": None})
    assert undo.status_code == 200 and undo.json()["data"]["case"] is None
    st = client.get("/api/v1/ai/skills", headers=H).json()["data"]
    q = next(x for x in st["skills"] if x["id"] == "ask-query")
    assert (
        st["ai"]["configured"]
        and q["stats"]["calls"] == 1
        and q["stats"]["down"] == 1
        and q["stats"]["regression_cases"] == 1
    )
    a = client.get("/api/v1/ai/skills/ask-answer/cases", headers=H).json()["data"]
    assert a["regression"][0]["reason"] == "corrected"
    run = client.get(f"/api/v1/ai/skills/ask-query/runs/{runs[0]['run_id']}", headers=H).json()["data"]
    assert run["rating"] == "down" and run["feedback_by"] == "alice" and run["input"]["question"] == "MTU?"

    # 试运行（真实调用，假的 AI）记入调用记录但不计入统计
    _fake(monkeypatch, lambda s, p: '{"query": "FIND interface RETURN name"}')
    t = client.post("/api/v1/ai/skills/ask-query/test", headers=H, json={"sample": 0, "mode": "ai"})
    assert t.status_code == 200 and t.json()["data"]["check"]["status"] == "passed" and t.json()["data"]["run_id"]
    assert client.get("/api/v1/ai/skills/ask-query/stats", headers=H).json()["data"]["totals"]["calls"] == 1

    # 进化（同步）：候选让回归案例通过
    def evo(system: str, prompt: str) -> str:
        if "You improve the prompts" in system:
            cur = client.get("/api/v1/ai/skills/ask-query", headers=H).json()["data"]["definition"]
            return json.dumps(
                {"system": cur["system"] + "\nPrefer RETURN name.", "prompt": cur["prompt"], "rationale": "r"}
            )
        return (
            '{"query": "FIND interface RETURN name"}' if "Prefer RETURN name." in system else '{"query": "FIND nope"}'
        )

    _fake(monkeypatch, evo)
    ev = client.post("/api/v1/ai/skills/ask-query/evolve", headers=H, json={"wait": True})
    assert ev.status_code == 200, ev.text
    e = ev.json()["data"]["evolution"]
    assert e["status"] == "pending" and e["scores"]["summary"]["old"] == 0.0 and e["scores"]["summary"]["new"] == 1.0
    lst = client.get("/api/v1/ai/skills/ask-query/evolutions", headers=H).json()["data"]["evolutions"]
    assert lst[0]["id"] == e["id"] and lst[0]["summary"]["better"] == 1
    det = client.get(f"/api/v1/ai/skills/ask-query/evolutions/{e['id']}", headers=H).json()["data"]
    assert any(f["field"] == "system" and f["changed"] for f in det["diff"])
    assert alice.post(f"/api/v1/ai/skills/ask-query/evolutions/{e['id']}/approve", json={}).status_code == 403
    ap = client.post(f"/api/v1/ai/skills/ask-query/evolutions/{e['id']}/approve", headers=H, json={"note": "ok"})
    assert ap.status_code == 200 and ap.json()["data"]["published_version"] == "1"
    assert client.get("/api/v1/ai/skills/ask-query", headers=H).json()["data"]["active"] == "1"
    again = client.post(f"/api/v1/ai/skills/ask-query/evolutions/{e['id']}/reject", headers=H, json={})
    assert again.status_code == 409

    # 后台任务形式
    task = client.post("/api/v1/ai/skills/ask-query/evolve", headers=H, json={})
    tid = task.json()["data"]["task_id"]
    for _ in range(100):
        t2 = client.get(f"/api/v1/tasks/{tid}", headers=H).json()["data"]
        if t2["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert t2["status"] == "done" and t2["result"]["skill"] == "ask-query"

    # 回滚 / 恢复内置
    assert (
        client.post("/api/v1/ai/skills/ask-query/rollback", headers=H, json={"version": "builtin"}).json()["data"][
            "active"
        ]
        == "builtin"
    )
    vs = client.get("/api/v1/ai/skills/ask-query/versions", headers=H).json()["data"]["versions"]
    assert [v["source"] for v in vs] == ["builtin", "evolution"] and vs[0]["active"]


def test_generate_and_skill_disabled(client, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    good = "```\ninterface GigabitEthernet0/2/2.105\n vlan-type dot1q 105\n ip binding vpn-instance RAN\n ip address 10.3.5.1 255.255.255.252\n#\n```"
    _fake(monkeypatch, lambda s, p: good)
    r = client.post("/api/v1/generate", headers=H, json={"request": "新增 105 子接口", "device": "ATN-CHANGE-01"})
    assert r.status_code == 200 and r.json()["data"]["skill_runs"][0]["status"] == "passed"
    assert (
        client.put("/api/v1/ai/skills/config-generate/enabled", headers=H, json={"enabled": False}).status_code == 200
    )
    r = client.post("/api/v1/generate", headers=H, json={"request": "新增 105 子接口", "device": "ATN-CHANGE-01"})
    assert r.status_code == 409 and r.json()["data"] == {"status": "skill_disabled", "skill": "config-generate"}
