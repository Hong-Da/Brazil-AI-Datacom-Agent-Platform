"""规范与合规、知识库构建、报告三组 AI skill 的接口（M8-5）：脱敏复核只允许本地模型（gate、run、estimate 都拦）、
规范文件转文字、知识库类建议只有维护员与管理员能采纳、报告导出包含 / 不包含已采纳的 AI 摘要、项目的脱敏补充。
AI 一律用假的客户端（替换 ai.provider_hook）。"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from lmesh.core import ai, config, importer, projects, users

pytestmark = pytest.mark.api
P = "/api/v1/projects/lab"
PASSWORDS = {"alice": "Alice-pass-1", "bob": "Bob-pass-12", "dave": "Dave-pass-12"}


@pytest.fixture
def env(full_kb_root: Path, projects_root: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """alice 的项目 lab：bob 只读、dave 是知识库维护员且为可编辑成员；AI 为假的 openai 接口（不是本地模型）。"""
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

    clients = {n: login(n) for n in PASSWORDS}
    clients["login"] = login
    clients["device_id"] = next(d["id"] for d in importer.list_devices(url) if d["name"] == "ATN-CHANGE-01")
    return clients


def _fake(monkeypatch: pytest.MonkeyPatch, reply: str) -> list[str]:
    sent: list[str] = []

    def hook(conn, m, s, p):  # type: ignore[no-untyped-def]
        sent.append(p)
        return ai.Reply(reply, m, 10, 5)

    monkeypatch.setattr(ai, "provider_hook", hook)
    return sent


RULE = """id: std.interface_l3_description
target: interface
when: {exists: ipv4}
assert: {exists: description}
severity: warning
title: {zh-CN: 三层接口没有描述, en: Layer 3 interface without description, pt-BR: Interface L3 sem descrição}
message: {zh-CN: "接口 {key} 没有描述", en: "Interface {key} has no description", pt-BR: "A interface {key} não tem descrição"}
suggestion: {zh-CN: 写明对端, en: Name the peer, pt-BR: Cite o par}
"""


def test_sanitize_review_local_only(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    alice, did = env["alice"], env["device_id"]
    g = alice.get(f"{P}/ai/kb/gate?skill=sanitize-review").json()["data"]
    assert g == {**g, "allowed": False, "local_only": True, "provider": "openai", "reason": "local_only"}
    assert alice.get(f"{P}/ai/kb/gate?skill=rule-draft").json()["data"]["allowed"]
    assert alice.get(f"{P}/ai/kb/gate?skill=nope").status_code == 404
    sent = _fake(monkeypatch, json.dumps({"suggestions": []}))
    for path in ("run", "estimate"):
        r = alice.post(f"{P}/ai/suggestions/{path}", json={"skill": "sanitize-review", "device_id": did, "wait": True})
        assert r.status_code == 409 and r.json()["data"]["reason"] == "local_only", r.text
    assert sent == []
    # 换成本地模型：可以运行，采纳后进入项目的脱敏补充
    from lmesh.core import store
    from lmesh.core.store.models import AIConnection

    with store.session(config.load().database_url) as ss:  # 管理员把公共接口改成本地模型
        for c in ss.query(AIConnection).all():
            c.provider = "local"
    assert alice.get(f"{P}/ai/kb/gate?skill=sanitize-review").json()["data"]["allowed"]
    reply = {
        "category": "sanitize_rule",
        "kind": "site",
        "title": "L32: site",
        "content": {"line": 32, "text": "RAN-SITE", "kind": "site"},
        "refs": [{"line": 32, "of": "d1"}],
    }
    _fake(monkeypatch, json.dumps({"suggestions": [reply]}))
    b = alice.post(f"{P}/ai/suggestions/run", json={"skill": "sanitize-review", "device_id": did, "wait": True})
    assert b.status_code == 200 and b.json()["data"]["counts"]["pass"] == 1, b.text
    sid = alice.get(f"{P}/ai/suggestions?skill=sanitize-review").json()["data"]["items"][0]["id"]
    assert alice.post(f"{P}/ai/suggestions/{sid}/adopt", json={}).status_code == 200
    assert alice.get(f"{P}/ai/kb/sanitize-redact").json()["data"]["patterns"] == ["RAN\\-SITE"]


def test_extract_text_upload(env) -> None:  # type: ignore[no-untyped-def]
    alice, bob = env["alice"], env["bob"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        z.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{ns}"><w:body><w:p><w:r><w:t>4.2.1 上联接口必须有描述</w:t></w:r></w:p></w:body></w:document>',
        )
    r = alice.post(f"{P}/ai/kb/extract-text", files={"file": ("std.docx", buf.getvalue())})
    assert r.status_code == 200 and r.json()["data"]["text"] == "4.2.1 上联接口必须有描述", r.text
    r = bob.post(f"{P}/ai/kb/extract-text", files={"file": ("std.md", b"# x\n4.1 y")})
    assert r.status_code == 200  # 只是计算，只读成员也可以
    assert alice.post(f"{P}/ai/kb/extract-text", files={"file": ("x.pdf", b"%PDF")}).status_code == 422


def test_rule_draft_kb_permission(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    alice, bob, dave = env["alice"], env["bob"], env["dave"]
    sug = {
        "category": "kb_review",
        "kind": "rule",
        "title": "4.2.1 → Layer 3 interfaces need a description",
        "content": {"review_kind": "rule", "target": "std.interface_l3_description", "payload": {"yaml": RULE}},
        "refs": [{"id": "s1"}],
    }
    _fake(monkeypatch, json.dumps({"suggestions": [sug]}))
    body = {"skill": "rule-draft", "params": {"text": "4.2.1 Every L3 interface needs a description."}, "wait": True}
    assert bob.post(f"{P}/ai/suggestions/run", json=body).status_code == 403
    b = alice.post(f"{P}/ai/suggestions/run", json=body)
    assert b.status_code == 200 and b.json()["data"]["counts"]["pass"] == 1, b.text
    it = alice.get(f"{P}/ai/suggestions?skill=rule-draft").json()["data"]["items"][0]
    assert it["kb"] and it["check"]["result"]["trial"]["hits"] > 0
    assert alice.post(f"{P}/ai/suggestions/{it['id']}/adopt", json={}).status_code == 403  # 不是维护员
    r = dave.post(f"{P}/ai/suggestions/{it['id']}/adopt", json={})
    assert r.status_code == 200, r.text
    rid = r.json()["data"]["adopt_info"]["review_item_id"]
    item = dave.get(f"/api/v1/review/{rid}").json()["data"]
    assert item["kind"] == "rule" and item["payload"]["yaml"] == RULE


def test_report_include_ai_summary(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    alice, did = env["alice"], env["device_id"]
    items = [
        {"category": "text_only", "kind": k, "title": "S", "content": {"text": t}, "refs": [{"id": "d1"}]}
        for k, t in (
            ("zh-CN", "[[d1]] 共 <<findings.total>> 个问题。"),
            ("en", "[[d1]] has <<findings.total>> issues."),
        )
    ]
    _fake(monkeypatch, json.dumps({"suggestions": items}))
    b = alice.post(
        f"{P}/ai/suggestions/run",
        json={"skill": "report-summary", "params": {"kind": "check", "device_id": did}, "wait": True},
    )
    assert b.status_code == 200 and b.json()["data"]["scope_key"] == f"report:check:{did}", b.text
    for s in alice.get(f"{P}/ai/suggestions?skill=report-summary").json()["data"]["items"]:
        assert alice.post(f"{P}/ai/suggestions/{s['id']}/adopt", json={}).status_code == 200
    body = {"kind": "check", "lang": "en", "format": "html", "check": {"device_id": did}}
    r = alice.post(f"{P}/reports", json=body)
    assert r.status_code == 200 and 'class="ai-summary"' in r.text and "skill report-summary" in r.text
    assert "ATN-CHANGE-01</b> has <b" in r.text.replace('<b class="cv">', "<b>")
    r = alice.post(f"{P}/reports", json={**body, "include_ai_summary": False})
    assert r.status_code == 200 and 'class="ai-summary"' not in r.text
    # 基线报告：没有采纳的摘要时与原来一样
    r = alice.post(f"{P}/baseline/report", json={"device_ids": [did], "lang": "zh-CN"})
    assert r.status_code == 200 and 'class="ai-summary"' not in r.text
