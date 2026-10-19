"""AI 建议接口（M8-2）：权限矩阵（属主 / 可编辑 / 只读 / 非成员 / 维护员 / 只读令牌）、后台任务、批量采纳只采纳通过的、
编辑后采纳重新校验、撤销、采纳记录、视图标注、未配置 AI 时 409。AI 一律用假的客户端（替换 ai.provider_hook）。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from lmesh.core import ai, config, projects, users
from tests.conftest import TEST_TOKEN

pytestmark = pytest.mark.api
H = {"Authorization": f"Bearer {TEST_TOKEN}"}
P = "/api/v1/projects/lab"
PASSWORDS = {"alice": "Alice-pass-1", "bob": "Bob-pass-12", "carol": "Carol-pass-1", "dave": "Dave-pass-12"}


@pytest.fixture
def env(full_kb_root: Path, projects_root: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """alice 的项目 lab：bob 只读、carol 不是成员、dave 是知识库维护员且为可编辑成员；AI 为假的接口。"""
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    monkeypatch.setenv("LMESH_AI__PROVIDER", "openai")
    monkeypatch.setenv("LMESH_AI__BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("LMESH_AI__MODEL", "fake-model")
    url = config.load().database_url
    users.create_user(url, "dave", PASSWORDS["dave"], "maintainer")
    alice = projects.cli_identity(url, "alice")
    projects.set_member(url, projects.resolve(url, alice, "lab"), "dave", "edit")

    def login(name: str) -> Any:
        c = TestClient(create_app())
        r = c.post("/api/v1/auth/login", json={"username": name, "password": PASSWORDS[name]})
        assert r.status_code == 200, r.text
        return c

    return {n: login(n) for n in PASSWORDS}


def _fake(monkeypatch: pytest.MonkeyPatch, reply: str) -> None:
    monkeypatch.setattr(ai, "provider_hook", lambda conn, m, s, p: ai.Reply(reply, m, 10, 5))


def _roles(*pairs: tuple[str, str]) -> str:
    return json.dumps(
        {
            "suggestions": [
                {
                    "category": "view_hint",
                    "kind": "role",
                    "title": f"{t}: {v}",
                    "content": {"target": t, "key": "role", "value": v},
                    "refs": [{"id": t}],
                }
                for t, v in pairs
            ]
        }
    )


def _wait(c: Any, task_id: str) -> dict[str, Any]:
    for _ in range(200):
        t = c.get(f"/api/v1/tasks/{task_id}").json()["data"]
        if t["status"] in ("done", "failed"):
            return t  # type: ignore[no-any-return]
        time.sleep(0.05)
    raise AssertionError("task timeout")


def test_permission_matrix_and_batch_adopt(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    alice, bob, carol, dave = env["alice"], env["bob"], env["carol"], env["dave"]
    sk = alice.get(f"{P}/ai/suggestions/skills")
    assert sk.status_code == 200 and sk.json()["data"]["ai"]["configured"]
    assert {"device-summary", "topology-roles"} <= {x["id"] for x in sk.json()["data"]["skills"]}
    _fake(monkeypatch, _roles(("d1", "pe"), ("d2", "access"), ("d9", "core")))
    # 只读成员不能运行，非成员看不到项目
    assert bob.post(f"{P}/ai/suggestions/run", json={"skill": "topology-roles"}).status_code == 403
    assert carol.get(f"{P}/ai/suggestions").status_code == 404
    # 属主运行（后台任务）
    r = alice.post(f"{P}/ai/suggestions/run", json={"skill": "topology-roles"})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    t = _wait(alice, d["task_id"])
    assert t["status"] == "done" and t["result"]["counts"] == {"pass": 2, "warn": 0, "reject": 1, "total": 3}
    b = alice.get(f"{P}/ai/suggestions/batches/{d['batch_id']}").json()["data"]
    assert b["status"] == "done" and b["connection"] and b["model"] == "fake-model" and b["created_by"] == "alice"
    # 只读成员可以查看，不能采纳 / 忽略 / 撤销 / 批量采纳
    lst = bob.get(f"{P}/ai/suggestions", params={"skill": "topology-roles"})
    assert lst.status_code == 200 and lst.json()["data"]["total"] == 3
    items = lst.json()["data"]["items"]
    one = items[0]["id"]
    assert bob.post(f"{P}/ai/suggestions/{one}/adopt", json={}).status_code == 403
    assert bob.post(f"{P}/ai/suggestions/{one}/dismiss", json={}).status_code == 403
    assert bob.post(f"{P}/ai/suggestions/adopt-batch", json={"category": "view_hint"}).status_code == 403
    rej = next(x for x in items if x["check_status"] == "reject")
    assert alice.post(f"{P}/ai/suggestions/{rej['id']}/adopt", json={}).status_code == 409
    # 可编辑成员（dave）批量采纳：只采纳通过的
    ba = dave.post(f"{P}/ai/suggestions/adopt-batch", json={"category": "view_hint", "skill": "topology-roles"})
    assert ba.status_code == 200, ba.text
    res = ba.json()["data"]
    assert len(res["adopted"]) == 2 and [x["id"] for x in res["skipped"]] == [rej["id"]]
    ann = bob.get(f"{P}/view-annotations").json()["data"]["items"]
    assert sorted(a["value"] for a in ann) == ["access", "pe"] and {a["source"] for a in ann} == {"ai"}
    hist = bob.get(f"{P}/ai/suggestions/adoptions").json()["data"]["items"]
    assert {h["id"] for h in hist} == set(res["adopted"]) and hist[0]["decided_by"] == "dave"
    # 撤销（属主），再撤销 409
    rv = alice.post(f"{P}/ai/suggestions/{res['adopted'][0]}/revert", json={"note": "no"})
    assert rv.status_code == 200 and rv.json()["data"]["status"] == "reverted"
    assert alice.post(f"{P}/ai/suggestions/{res['adopted'][0]}/revert", json={}).status_code == 409
    assert len(bob.get(f"{P}/view-annotations").json()["data"]["items"]) == 1
    # 过滤
    q = alice.get(f"{P}/ai/suggestions", params={"status": "pending", "check": "reject"}).json()["data"]
    assert q["total"] == 1 and q["counts"]["pending"] == 1
    q2 = alice.get(f"{P}/ai/suggestions", params={"status": "pending"}).json()["data"]  # 页签计数不受状态过滤影响
    assert q2["total"] == 1 and q2["counts"] == {"pending": 1, "adopted": 1, "dismissed": 0, "reverted": 1}
    assert alice.get(f"{P}/ai/suggestions/999999").status_code == 404
    assert alice.get(f"{P}/ai/suggestions", params={"status": "nope"}).status_code == 422


def test_edit_adopt_kb_permission_and_errors(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    import dataclasses

    from lmesh.core import ai_suggest

    alice, dave = env["alice"], env["dave"]
    # 编辑后采纳：不允许的取值 409（data.check），允许的取值通过
    _fake(monkeypatch, _roles(("d1", "pe")))
    r = alice.post(f"{P}/ai/suggestions/run", json={"skill": "topology-roles", "wait": True})
    assert r.status_code == 200, r.text
    sid = alice.get(f"{P}/ai/suggestions", params={"batch_id": r.json()["data"]["id"]}).json()["data"]["items"][0]["id"]
    bad = alice.post(f"{P}/ai/suggestions/{sid}/adopt", json={"content": {"target": "d1", "key": "role", "value": "x"}})
    assert bad.status_code == 409 and bad.json()["data"]["check"]["reasons"][0]["code"] == "bad_hint_value"
    good = alice.post(
        f"{P}/ai/suggestions/{sid}/adopt", json={"content": {"target": "d1", "key": "role", "value": "p"}}
    )
    assert (
        good.status_code == 200 and good.json()["data"]["edited"] and good.json()["data"]["adopt_info"]["value"] == "p"
    )
    # 知识库类建议：可编辑的普通账号 403，维护员可以
    spec = ai_suggest.spec_of("topology-roles")
    monkeypatch.setitem(
        ai_suggest.SKILLS, "topology-roles", dataclasses.replace(spec, categories=("view_hint", "kb_review"))
    )
    draft = {
        "category": "kb_review",
        "title": "Rule draft",
        "content": {"review_kind": "suggestion", "target": "rules/x.yaml", "payload": {"text": "x"}},
        "refs": [{"id": "d1"}],
    }
    _fake(monkeypatch, json.dumps({"suggestions": [draft]}))
    r2 = alice.post(f"{P}/ai/suggestions/run", json={"skill": "topology-roles", "wait": True})
    kid = alice.get(f"{P}/ai/suggestions", params={"batch_id": r2.json()["data"]["id"]}).json()["data"]["items"][0]
    assert kid["kb"] and kid["check_status"] == "pass"
    assert alice.post(f"{P}/ai/suggestions/{kid['id']}/adopt", json={}).status_code == 403
    ok = dave.post(f"{P}/ai/suggestions/{kid['id']}/adopt", json={})
    assert ok.status_code == 200, ok.text
    rid = ok.json()["data"]["adopt_info"]["review_item_id"]
    item = alice.get(f"/api/v1/review/{rid}", headers=H).json()["data"]
    assert item["status"] == "pending" and item["source"]["method"] == "ai"
    # 参数与状态错误
    assert alice.post(f"{P}/ai/suggestions/run", json={"skill": "nope", "wait": True}).status_code == 404
    assert alice.post(f"{P}/ai/suggestions/run", json={"skill": "device-summary", "wait": True}).status_code == 422
    nf = alice.post(f"{P}/ai/suggestions/run", json={"skill": "device-summary", "device_id": 99999, "wait": True})
    assert nf.status_code == 404
    done = r2.json()["data"]["id"]
    assert alice.post(f"{P}/ai/suggestions/batches/{done}/cancel", json={}).status_code == 409
    assert alice.post(f"{P}/ai/suggestions/adopt-batch", json={"category": "nope"}).status_code == 422


def test_device_summary_and_not_configured(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    alice = env["alice"]
    devs = alice.get(f"{P}/devices").json()["data"]
    did = next(d["id"] for d in (devs["devices"] if isinstance(devs, dict) else devs) if d["name"] == "ATN-CHANGE-01")
    reply = {
        "suggestions": [
            {"category": "text_only", "title": "S", "content": {"text": "[[d1]] has <<count.interface>> interfaces."}}
        ]
    }
    _fake(monkeypatch, json.dumps(reply))
    r = alice.post(f"{P}/ai/suggestions/run", json={"skill": "device-summary", "device_id": did, "wait": True})
    assert r.status_code == 200 and r.json()["data"]["scope_key"] == f"device:{did}"
    lst = alice.get(f"{P}/ai/suggestions", params={"device_id": did}).json()["data"]["items"]
    assert lst[0]["check"]["display"].startswith("ATN-CHANGE-01 has ") and lst[0]["refs"] == []


def test_not_configured_409(full_kb_root: Path, projects_root: Path) -> None:
    """未配置 AI：运行 409（data.reason 给出原因），查看与 skill 列表照常（入口按钮据此显示不可用的原因）。"""
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    c = TestClient(create_app())
    lab = "/api/v1/projects/alice~lab"
    sk = c.get(f"{lab}/ai/suggestions/skills", headers=H).json()["data"]
    assert sk["ai"]["configured"] is False and sk["ai"]["reason"]
    off = c.post(f"{lab}/ai/suggestions/run", headers=H, json={"skill": "topology-roles"})
    assert off.status_code == 409 and off.json()["data"]["status"] == "not_configured"
    assert c.get(f"{lab}/ai/suggestions", headers=H).json()["data"]["total"] == 0
    assert c.get(f"{lab}/ai/suggestions/skills").status_code == 401


def test_personal_token_warn(env) -> None:  # type: ignore[no-untyped-def]
    """“我的 AI”里的个人开关“不提示大请求”：保存后 skill 列表的 warn_tokens 为 0（优先于全局 ai.warn_tokens）。"""
    alice = env["alice"]
    assert alice.get(f"{P}/ai/suggestions/skills").json()["data"]["ai"]["warn_tokens"] == 50000
    r = alice.put("/api/v1/me/ai", json={"no_token_warn": True})
    assert r.status_code == 200 and r.json()["data"]["no_token_warn"] is True
    assert alice.get("/api/v1/me/ai").json()["data"]["no_token_warn"] is True
    assert alice.get(f"{P}/ai/suggestions/skills").json()["data"]["ai"]["warn_tokens"] == 0
    est = alice.post(f"{P}/ai/suggestions/estimate", json={"skill": "topology-roles"}).json()["data"]
    assert est["tokens"] > 0 and est["warn"] is False and est["threshold"] == 0
    assert env["bob"].post(f"{P}/ai/suggestions/estimate", json={"skill": "topology-roles"}).status_code == 200
