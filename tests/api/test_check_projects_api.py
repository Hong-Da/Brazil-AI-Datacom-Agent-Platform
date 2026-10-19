"""配置检查项目接口（REQ-031）中不适合写成 TOML 用例的部分：差异下载（文件）、按账号的项目归属、经接口的 AI 一起校验（假的 AI）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import TEST_TOKEN, TEST_USERS

pytestmark = pytest.mark.api
H = {"Authorization": f"Bearer {TEST_TOKEN}"}


def _client():  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    return TestClient(create_app())


def test_diff_downloads(full_kb_root: Path, checkproj_root: Path) -> None:
    c = _client()
    body = {
        "a": {"type": "revision", "revision_id": 1},
        "b": {"type": "baseline", "project_id": 1},
        "report_lang": "en",
    }
    r = c.post("/api/v1/check-projects/diff/report", headers=H, json={**body, "format": "unified"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/x-diff")
    assert r.text.startswith("--- 绑定 VPN #1\n+++ ATN-CHANGE-01@")
    r = c.post("/api/v1/check-projects/diff/report", headers=H, json={**body, "format": "html"})
    assert r.status_code == 200 and "Configuration text diff report" in r.text
    assert "attachment" in r.headers["content-disposition"]
    r = c.post("/api/v1/check-projects/diff/report", headers=H, json={**body, "format": "html", "report_lang": "zh-CN"})
    assert "配置文本差异报告" in r.text


def test_projects_belong_to_their_user(full_kb_root: Path, users_root: Path) -> None:
    """M6 起检查项目属于项目：alice 在自己的默认项目里导入设备并建检查项目；不是成员的 bob 看不到；
    管理员的旧路径落到自己的默认项目（看不到），经项目路径访问 alice 的项目可以看到。"""
    from lmesh.core import config, users

    s = config.load()
    users.create_user(s.database_url, "bob", "Bob-pass-12", "user")
    alice, bob, admin = _client(), _client(), _client()
    for cl, name, pw in (
        (alice, "alice", TEST_USERS["alice"][0]),
        (bob, "bob", "Bob-pass-12"),
        (admin, "admin", TEST_USERS["admin"][0]),
    ):
        assert cl.post("/api/v1/auth/login", json={"username": name, "password": pw}).status_code == 200
    text = (full_kb_root / "knowledge" / "samples" / "change" / "atn-base.cfg").read_bytes()
    r = alice.post("/api/v1/configs", files=[("files", ("atn-base.cfg", text, "text/plain"))])
    assert r.status_code == 200 and r.json()["data"]["files"][0]["ok"], r.text
    dev = alice.get("/api/v1/devices").json()["data"]["devices"][0]["id"]
    r = alice.post("/api/v1/check-projects", json={"name": "alice 的项目", "device_id": dev})
    assert r.status_code == 200 and r.json()["data"]["owner"]["username"] == "alice"
    pid = r.json()["data"]["id"]
    assert [p["id"] for p in alice.get("/api/v1/check-projects").json()["data"]["projects"]] == [pid]
    assert bob.get("/api/v1/check-projects").json()["data"]["projects"] == []
    assert bob.get(f"/api/v1/check-projects/{pid}").status_code == 404
    slug = alice.get("/api/v1/workspace").json()["data"]["default_project"]
    assert admin.get("/api/v1/check-projects").json()["data"]["projects"] == []
    assert len(admin.get(f"/api/v1/projects/{slug}/check-projects").json()["data"]["projects"]) == 1
    sc = alice.post(f"/api/v1/check-projects/{pid}/scripts", json={"name": "s", "content": "system-view\n"}).json()
    revs = alice.get(f"/api/v1/check-projects/{pid}/scripts/{sc['data']['id']}/revisions").json()["data"]["revisions"]
    assert revs[0]["author"] == "alice"


def test_check_with_fake_ai(full_kb_root: Path, checkproj_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """规则目录里有 ai: true 的规则时，经接口勾选后交给（假的）AI；AI 结果经代码校验后带来源与状态返回。"""
    from lmesh.core import ai, config, kbservice, rules

    monkeypatch.setenv("LMESH_AI__PROVIDER", "openai")
    monkeypatch.setenv("LMESH_AI__BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("LMESH_AI__MODEL", "fake-model")
    rd = kbservice.runtime_root(config.load()) / "rules"
    t = {"zh-CN": "接口描述规范", "en": "Description convention", "pt-BR": "Convenção"}
    doc = {
        "rules": [
            {
                "id": "style.desc",
                "ai": True,
                "target": "interface",
                "severity": "info",
                "title": t,
                "message": t,
                "suggestion": t,
            }
        ]
    }
    (rd / "ai-test.yaml").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    rules._cache.clear()

    def fake(settings, model, system, prompt):  # type: ignore[no-untyped-def]
        line = next(x for x in prompt.splitlines() if x.startswith("5 | "))[4:].strip()
        reply = {
            "findings": [
                {"rule": "style.desc", "line": 5, "evidence": line, "message": "描述不规范"},
                {"rule": "style.desc", "line": 2},
            ]
        }
        return ai.Reply(json.dumps(reply, ensure_ascii=False), model, 10, 10)

    monkeypatch.setattr(ai, "provider_hook", fake)
    c = _client()
    r = c.get("/api/v1/check-projects/ai-rules", headers=H).json()["data"]
    assert r["configured"] and "style.desc" in [x["id"] for x in r["rules"]]
    c.put("/api/v1/check-projects/1", headers=H, json={"ai_check": True, "ai_rules": ["style.desc"]})
    d = c.post("/api/v1/check-projects/1/scripts/1/check", headers=H, json={"ai": True}).json()["data"]
    assert d["ai"]["status"] == "ok" and d["ai"]["accepted"] == 2
    got = [(i["line"], i["status"], i["source"]) for i in d["issues"] if i["source"] == "ai"]
    assert got == [(2, "unverifiable", "ai"), (5, "passed", "ai")]


def test_ai_rules_lists_knowledge_rules(configured_root: Path) -> None:
    """知识库自带的 style-ai.yaml 中的规则出现在可勾选列表中（未配置 AI 时 configured 为 false）。"""
    d = _client().get("/api/v1/check-projects/ai-rules", headers=H).json()["data"]
    ids = [r["id"] for r in d["rules"]]
    assert d["configured"] is False and "style.interface_description" in ids and "style.policy_naming" in ids
