"""日常分析组的 AI skill（M8-3）的接口：手工标注与权限、拓扑整理（推测对端核对后连线、批量采纳）、变化解读与覆盖核对、
问题解读与修复（修复脚本复检、采纳进项目脚本）、交接文档下载（中文 / English）。AI 一律用假的客户端。"""

# ruff: noqa: F811  （env 是从 test_ai_suggest_api 导入的夹具，用例参数同名）
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lmesh.core import config, importer, kbservice, projects
from tests.api.test_ai_suggest_api import P, _fake, env  # noqa: F401

pytestmark = pytest.mark.api
SAMPLES = Path(__file__).resolve().parent.parent.parent / "knowledge" / "samples"


def _reply(*items: dict[str, Any]) -> str:
    return json.dumps({"suggestions": list(items)})


def _did(name: str = "ATN-CHANGE-01") -> int:
    return int(next(d["id"] for d in importer.list_devices(config.load().database_url) if d["name"] == name))


def _run(c: Any, skill: str, **params: Any) -> list[dict[str, Any]]:
    r = c.post(f"{P}/ai/suggestions/run", json={"skill": skill, "params": params, "wait": True})
    assert r.status_code == 200, r.text
    b = r.json()["data"]
    assert b["status"] == "done", b
    items = c.get(f"{P}/ai/suggestions?batch_id={b['id']}").json()["data"]["items"]
    return sorted(items, key=lambda x: x["id"])


def test_annotations_and_topology_peers(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    alice, bob = env["alice"], env["bob"]
    did = _did()
    r = alice.put(f"{P}/view-annotations", json={"target": str(did), "key": "role", "value": "core"})
    assert r.status_code == 200 and r.json()["data"]["item"]["source"] == "user"
    assert bob.put(f"{P}/view-annotations", json={"target": str(did), "key": "role", "value": "pe"}).status_code == 403
    assert env["carol"].put(f"{P}/view-annotations", json={"target": str(did), "key": "role"}).status_code == 404
    assert alice.put(f"{P}/view-annotations", json={"target": str(did), "key": "layer", "value": 12}).status_code == 422
    # 拓扑整理：角色建议覆盖手工标注时警告；推测对端（环回地址）没有直连网段，被拒绝
    items = [
        {
            "category": "view_hint",
            "kind": "role",
            "title": "d1: pe",
            "content": {"target": "d1", "key": "role", "value": "pe"},
            "refs": [{"id": "d1"}],
        },
        {
            "category": "view_hint",
            "kind": "group",
            "title": "d1: East",
            "content": {"target": "d1", "key": "group", "value": "East"},
            "refs": [{"id": "d1"}],
        },
        {
            "category": "peer_link",
            "kind": "peer",
            "title": "u1",
            "content": {"a": "d1", "b": "u1", "external": True},
            "refs": [{"id": "d1"}, {"id": "u1"}],
        },
    ]
    _fake(monkeypatch, _reply(*items))
    rows = _run(alice, "topology-roles")
    by = {r["kind"]: r for r in rows}
    assert by["peer"]["check_status"] == "reject" and by["peer"]["check"]["reasons"][-1]["code"] == "no_shared_subnet"
    role_target = by["role"]["refs"][0]["device_id"]
    if role_target == did:
        assert by["role"]["check_status"] == "warn"
    res = alice.post(f"{P}/ai/suggestions/adopt-batch", json={"category": "view_hint", "skill": "topology-roles"})
    assert by["group"]["id"] in res.json()["data"]["adopted"]
    annos = alice.get(f"{P}/view-annotations").json()["data"]["items"]
    assert {(a["key"], a["source"]) for a in annos} >= {("role", "user"), ("group", "ai")}
    # 清除手工标注
    r = alice.put(f"{P}/view-annotations", json={"target": str(did), "key": "role", "value": None})
    assert r.status_code == 200 and r.json()["data"]["item"] is None


def test_diff_coverage_fix_and_handover(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    alice, bob = env["alice"], env["bob"]
    s = config.load()
    url = s.database_url
    alice_id = projects.cli_identity(url, "alice")
    with projects.use(projects.resolve(url, alice_id, "lab"), alice_id):
        importer.import_sources(
            [("atn.cfg", (SAMPLES / "change" / "atn-add-vrf.cfg").read_bytes())],
            url,
            "basic",
            kbservice.runtime_root(s),
            actor="alice",
        )
    did = _did()
    vers = alice.get(f"{P}/devices/{did}/versions").json()["data"]
    vlist = vers["versions"] if isinstance(vers, dict) else vers
    va, vb = int(vlist[1]["id"]), int(vlist[0]["id"])
    intent = {
        "category": "refs_exist",
        "kind": "intent",
        "title": "New VPN",
        "content": {"text": "[[c1]] adds a service.", "risk": "low"},
        "refs": [{"id": "c1"}],
    }
    _fake(monkeypatch, _reply(intent))
    rows = _run(alice, "diff-explain", source="history", device_id=did, a_version=va, b_version=vb)
    assert rows[0]["check_status"] == "pass" and rows[0]["refs"][0]["type"] == "diff"
    cov = bob.get(f"{P}/ai/suggestions/coverage", params={"scope": f"history:{va}:{vb}"}).json()["data"]
    assert cov["covered"] == ["c1"] and cov["total"] == len(cov["uncovered"]) + 1
    # 问题解读与修复：删除孤儿 VPN 的脚本在模拟图上复检通过，采纳后进入项目脚本
    fix = {
        "category": "script_valid",
        "kind": "fix",
        "title": "Remove OAM",
        "content": {"device": "d1", "script": "undo ip vpn-instance OAM", "fixes": [{"finding": "f1"}]},
        "refs": [{"id": "f1"}],
    }
    _fake(monkeypatch, _reply(fix))
    rows = _run(alice, "finding-fix", source="check", device_id=did)
    assert rows[0]["check_status"] in ("pass", "warn"), rows[0]["check"]
    done = alice.post(f"{P}/ai/suggestions/{rows[0]['id']}/adopt", json={})
    assert done.status_code == 200 and done.json()["data"]["adopt_info"]["action"] == "script"
    # 交接文档：中文 / English 两个下载
    for lang, word in (("zh-CN", "设备交接说明"), ("en", "Device handover note")):
        r = bob.get(f"{P}/devices/{did}/handover", params={"lang": lang, "format": "md"})
        assert r.status_code == 200 and word in r.text and "attachment" in r.headers["content-disposition"]
    assert bob.get(f"{P}/devices/99999/handover").status_code == 404
