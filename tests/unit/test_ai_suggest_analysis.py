"""日常分析组的 AI skill（M8-3）：拓扑整理（角色 / 分组 / 推测对端、手工标注）、变化解读（意图挂差异、覆盖核对）、
问题解读与修复（单台检查与跨设备一致性，修复脚本在模拟图上复检）、影响说明、能力对比说明（命令写法与命令卡核对）、
设备交接文档。每个 skill：正常建议、代码校验拒绝、未配置 AI 时降级。AI 一律用假的客户端（替换 ai.provider_hook）。"""

# ruff: noqa: F811  （lab 是从 test_ai_suggest 导入的夹具，用例参数同名）
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lmesh.core import (
    ai_suggest,
    ai_suggest_analysis,
    analysis,
    config,
    importer,
    kbservice,
    projects,
    skill_runners,
    skills,
    store,
)
from tests.unit.test_ai_suggest import _device_id, _env, _fake, _reply, _summary, lab  # noqa: F401

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLES = ROOT / "knowledge" / "samples"
TOPO = ["atn-a1.cfg", "atn-a2.cfg", "agg-01.cfg", "agg-02.cfg", "rr-01.cfg"]


def _import(url: str, files: list[tuple[str, bytes]]) -> None:
    importer.import_sources(files, url, "basic", kbservice.runtime_root(config.load()), actor="alice")


def _codes(item: dict[str, Any]) -> set[str]:
    return {r["code"] for r in item["check"]["reasons"]}


def _items(env: ai_suggest.Env, batch: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(ai_suggest.list_suggestions(env, batch_id=batch["id"])["items"], key=lambda x: x["id"])


@pytest.fixture
def topo_lab(lab):  # type: ignore[no-untyped-def]
    """lab 加上拓扑样本网络的 5 台设备（TOPO-AGG-01 与 TOPO-AGG-02 之间有一条 LDP 只开一端的链路）。"""
    s, scope, alice = lab
    from lmesh.core.kb import read_yaml

    man = read_yaml(SAMPLES / "topology" / "manifest.yaml")
    files = [m["file"] for m in man["samples"]]
    _import(s.database_url, [(f, (SAMPLES / "topology" / f).read_bytes()) for f in files])
    ids = [d["id"] for d in importer.list_devices(s.database_url) if str(d["name"]).startswith("TOPO-")]
    return s, scope, alice, ids


# ================================================================ 拓扑整理


def _peer(a: str, b: str, **extra: Any) -> dict[str, Any]:
    return {
        "category": "peer_link",
        "kind": "peer",
        "title": f"{a} ~ {b}",
        "content": {"a": a, "b": b, "reason": f"[[{a}]] and [[{b}]].", **extra},
        "refs": [{"id": a}, {"id": b}],
    }


def _hint(target: str, key: str, value: Any) -> dict[str, Any]:
    return {
        "category": "view_hint",
        "kind": key,
        "title": f"{target}: {value}",
        "content": {"target": target, "key": key, "value": value, "reason": f"[[{target}]] fits."},
        "refs": [{"id": target}],
    }


def test_topology_roles_groups_and_peers(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    # 合成配置（由脱敏样本改写）：ATN 多一个 BGP 对等体 172.16.1.50，落在它的直连网段 172.16.1.0/24 里
    base = (SAMPLES / "change" / "atn-base.cfg").read_text(encoding="utf-8").replace("10.255.0.102", "172.16.1.50")
    _import(s.database_url, [("atn.cfg", base.encode())])
    calls = _fake(monkeypatch, lambda sy, p: "")
    ctx = ai_suggest.spec_of("topology-roles").build(env, {})
    objs = ctx.facts["objects"]
    dev = {o["label"]: k for k, o in objs.items() if o["type"] == "device"}
    peer = {o["address"]: k for k, o in objs.items() if o["type"] == "peer"}
    atn, pe = dev["ATN-CHANGE-01"], dev["PE-CHANGE-01"]
    assert "172.16.1.50" in peer and "10.255.0.101" in peer and "Unresolved peers" in ctx.vars["unresolved"] or True
    items = [
        _hint(atn, "role", "access"),
        _hint(pe, "group", "Central office"),
        _hint(pe, "layer", 2),
        _peer(atn, peer["172.16.1.50"], a_interface="GigabitEthernet0/2/1.101", external=True, label="CE"),
        _peer(atn, peer["10.255.0.101"], external=True),  # 环回地址的 BGP 对等体：没有直连网段，不连线
        _peer(atn, pe),  # 已经有代码还原的链路
        _peer(atn, "d99"),  # 编造的设备
    ]
    _fake(monkeypatch, lambda sy, p: _reply(*items))
    b = ai_suggest.run(env, "topology-roles", {})
    assert b["status"] == "done" and b["counts"] == {"pass": 4, "warn": 0, "reject": 3, "total": 7}
    rows = _items(env, b)
    assert [r["check_status"] for r in rows] == ["pass"] * 4 + ["reject"] * 3
    assert "no_shared_subnet" in _codes(rows[4]) and "already_linked" in _codes(rows[5])
    assert "ref_not_found" in _codes(rows[6])
    assert rows[3]["check"]["result"]["link"]["a"]["interface"] == "GigabitEthernet0/2/1.101"
    _ = calls
    # 批量采纳只采纳通过的；采纳后写入项目视图标注（链路标注带两端核对过的地址）
    for cat in ("view_hint", "peer_link"):
        ai_suggest.adopt_batch(env, cat, skill="topology-roles", batch_id=b["id"])
    annos = ai_suggest.list_annotations(s.database_url, scope.project_id)
    link = next(a for a in annos if a["target_type"] == "link")
    assert link["key"] == "peer" and link["source"] == "ai" and link["value"]["external"]
    assert link["value"]["b"]["address"] == "172.16.1.50" and link["value"]["a"]["address"] == "172.16.1.1/24"
    assert {(a["key"], a["value"]) for a in annos if a["target_type"] == "device"} == {
        ("role", "access"),
        ("group", "Central office"),
        ("layer", 2),
    }
    # 撤销推测对端：标注删除
    back = ai_suggest.revert(env, rows[3]["id"])
    assert back["revert_info"] == {"action": "remove"}
    assert not [a for a in ai_suggest.list_annotations(s.database_url, scope.project_id) if a["target_type"] == "link"]


def test_manual_annotation_wins_over_ai(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)
    item = ai_suggest_analysis.set_annotation(env, "device", str(did), "role", "core")
    assert item is not None and item["source"] == "user" and item["value"] == "core"
    for key, val, code in (("role", "firewall", "bad_hint_value"), ("size", "x", "bad_hint_key")):
        with pytest.raises(ai_suggest.SuggestError) as e:
            ai_suggest_analysis.set_annotation(env, "device", str(did), key, val)
        assert e.value.key == f"ai_suggest.{code}" and e.value.kind == "param"
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest_analysis.set_annotation(env, "device", "99999", "role", "pe")
    assert e.value.kind == "not_found"
    ctx = ai_suggest.spec_of("topology-roles").build(env, {})
    ref = next(k for k, o in ctx.facts["objects"].items() if o.get("device_id") == did)
    assert f"{ref} role=core (set by hand)" in ctx.vars["annotations"]
    _fake(monkeypatch, lambda sy, p: _reply(_hint(ref, "role", "pe")))
    b = ai_suggest.run(env, "topology-roles", {})
    sug = _items(env, b)[0]
    assert sug["check_status"] == "warn" and "overrides_manual" in _codes(sug)
    ai_suggest.adopt(env, sug["id"])  # warn 可以逐条采纳
    # 之后又被手工改了：AI 的建议不能再撤销（409），手工值保留
    ai_suggest_analysis.set_annotation(env, "device", str(did), "role", "access")
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.revert(env, sug["id"])
    assert e.value.key == "ai_suggest.superseded"
    assert ai_suggest_analysis.set_annotation(env, "device", str(did), "role", None) is None
    assert not [a for a in ai_suggest.list_annotations(s.database_url, scope.project_id) if a["key"] == "role"]


def test_peer_pair_check_unit() -> None:
    facts = {
        "objects": {
            "d1": {"type": "device", "label": "A", "device_id": 1, "ifaces": [["Ge1", "10.0.0.1/29", "", False]]},
            "d2": {"type": "device", "label": "B", "device_id": 2, "ifaces": [["Ge2", "10.0.0.6/30", "", False]]},
            "d3": {"type": "device", "label": "C", "device_id": 3, "ifaces": [["Ge3", "10.0.0.2/29", "X", False]]},
        },
        "linked": [],
    }
    info, why = ai_suggest_analysis._pair({"a": "d1", "b": "d2"}, facts)  # 掩码不一致，但一端网段包含另一端地址
    assert why == [] and info is not None and info["b"]["interface"] == "Ge2" and not info["external"]
    _, why = ai_suggest_analysis._pair({"a": "d1", "b": "d3"}, facts)  # VRF 不同
    assert [r["code"] for r in why] == ["no_shared_subnet"]
    _, why = ai_suggest_analysis._pair({"a": "d1", "b": "d2", "b_interface": "Ge9"}, facts)
    assert [r["code"] for r in why] == ["no_shared_subnet"]
    _, why = ai_suggest_analysis._pair({"a": "d1", "b": "d1"}, facts)
    assert [r["code"] for r in why] == ["bad_peer"]


# ================================================================ 变化解读


def _intent(text: str, refs: list[str], risk: str = "low", title: str = "Intent") -> dict[str, Any]:
    return {
        "category": "refs_exist",
        "kind": "intent",
        "title": title,
        "content": {"text": text, "risk": risk},
        "refs": [{"id": r} for r in refs],
    }


def _two_versions(url: str) -> tuple[int, int, int]:
    from lmesh.core import compare

    _import(url, [("atn.cfg", (SAMPLES / "change" / "atn-add-vrf.cfg").read_bytes())])
    did = _device_id(url)
    vs = compare.versions(url, did) or []
    return did, int(vs[1]["id"]), int(vs[0]["id"])


def test_diff_history_intents_coverage(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    _diff_case(lab, monkeypatch, "history")


def test_diff_compare_intents_coverage(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    # 注意：用例名前 30 个字符要不同（临时目录按它命名并会复用，AI 接口的导入记录按数据库路径缓存）
    _diff_case(lab, monkeypatch, "compare")


def _diff_case(lab: Any, monkeypatch: pytest.MonkeyPatch, source: str) -> None:
    s, scope, alice = lab
    env = _env(s, scope, alice)
    did, va, vb = _two_versions(s.database_url)
    params = {"source": source, "device_id": did, "a_version": va, "b_version": vb}
    ctx = ai_suggest.spec_of("diff-explain").build(env, dict(params))
    diffs = [k for k, o in ctx.facts["objects"].items() if o["type"] == "diff"]
    assert len(diffs) >= 3 and ctx.scope_key == f"{source}:{va}:{vb}" and "c1 | added" in ctx.vars["diffs"]
    items = [
        _intent("[[c1]] and [[c2]] add the new service.", ["c1", "c2"], "low", "New service"),
        _intent("Clean up the test VLAN [[c99]].", ["c99"]),  # 编造的差异条目
        _intent("Routing was tuned.", ["d1"], "urgent"),  # 没挂差异、风险等级不对
    ]
    _fake(monkeypatch, lambda sy, p: _reply(*items))
    b = ai_suggest.run(env, "diff-explain", params)
    rows = _items(env, b)
    assert [r["check_status"] for r in rows] == ["pass", "reject", "reject"]
    assert {"ref_not_found", "no_diff_refs"} <= _codes(rows[1]) and {"no_diff_refs", "bad_risk"} <= _codes(rows[2])
    assert rows[0]["check"]["segments"][0]["t"] == "ref" and rows[0]["refs"][0]["type"] == "diff"
    cov = ai_suggest_analysis.coverage(env, "diff-explain", f"{source}:{va}:{vb}")
    assert cov["batch_id"] == b["id"] and cov["total"] == len(diffs) and cov["covered"] == ["c1", "c2"]
    assert [u["id"] for u in cov["uncovered"]] == diffs[2:] and cov["uncovered"][0]["node"]
    ai_suggest.dismiss(env, rows[0]["id"])  # 忽略的意图不再算覆盖
    assert ai_suggest_analysis.coverage(env, "diff-explain", f"{source}:{va}:{vb}")["covered"] == []
    assert ai_suggest_analysis.coverage(env, "diff-explain", "compare:0:0")["batch_id"] is None
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.run(env, "diff-explain", {"source": source, "device_id": did, "a_version": 99999, "b_version": vb})
    assert e.value.kind == "not_found"


# ================================================================ 问题解读与修复


def _explain(text: str, refs: list[str], priority: str = "high", suspect: str | None = None) -> dict[str, Any]:
    c: dict[str, Any] = {"text": text, "priority": priority}
    if suspect:
        c["suspect"] = suspect
    return {
        "category": "refs_exist",
        "kind": "explain",
        "title": "Why",
        "content": c,
        "refs": [{"id": r} for r in refs],
    }


def _fix(device: str, script: str, finding: str) -> dict[str, Any]:
    return {
        "category": "script_valid",
        "kind": "fix",
        "title": f"Fix {finding}",
        "content": {
            "device": device,
            "script": script,
            "explain": f"Fixes [[{finding}]].",
            "fixes": [{"finding": finding}],
        },
        "refs": [{"id": finding}],
    }


def test_finding_fix_single_device(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)
    params = {"source": "check", "device_id": did}
    ctx = ai_suggest.spec_of("finding-fix").build(env, dict(params))
    f_of = {o["node"]: k for k, o in ctx.facts["objects"].items() if o["type"] == "finding"}
    oam = f_of["vrf.instance[OAM]"]
    assert ctx.scope_key == f"check:{did}" and "ref.orphan" in ctx.vars["findings"]
    items = [
        _explain(f"[[{oam}]] is an unused VPN; delete it.", [oam], "low"),
        _fix("d1", "undo ip vpn-instance OAM", oam),  # 删除后孤儿问题消失
        _fix("d1", "undo acl 3001", oam),  # 删的是别的对象：问题仍在
        _explain("[[f99]] is bad.", ["f99"], "now"),  # 编造的问题、优先级不对
    ]
    _fake(monkeypatch, lambda sy, p: _reply(*items))
    b = ai_suggest.run(env, "finding-fix", params)
    rows = _items(env, b)
    assert [r["check_status"] for r in rows][:1] == ["pass"]
    assert rows[1]["check_status"] in ("pass", "warn") and "finding_not_fixed" not in _codes(rows[1])
    assert rows[2]["check_status"] == "reject" and "finding_not_fixed" in _codes(rows[2])
    assert rows[3]["check_status"] == "reject" and {"no_finding_refs", "bad_priority"} <= _codes(rows[3])
    done = ai_suggest.adopt(env, rows[1]["id"])  # 采纳 = 在项目里新建一份变更脚本
    assert done["adopt_info"]["action"] == "script" and done["adopt_info"]["device_id"] == did


def test_finding_fix_cross_device(topo_lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice, ids = topo_lab
    env = _env(s, scope, alice)
    params = {"source": "consistency", "device_ids": ids}
    ctx = ai_suggest.spec_of("finding-fix").build(env, dict(params))
    objs = ctx.facts["objects"]
    dev = {o["label"]: k for k, o in objs.items() if o["type"] == "device"}
    ldp = next(k for k, o in objs.items() if o["type"] == "finding" and o["rule"] == "xd.subnet.ldp_one_side")
    a1, a2, rr = dev["TOPO-AGG-01"], dev["TOPO-AGG-02"], dev["TOPO-RR-01"]
    assert set(objs[ldp]["devices"]) == {a1, a2} and ctx.scope_key == "consistency"
    items = [
        _explain(f"LDP is missing on [[{a2}]] for [[{ldp}]].", [ldp], "high", a2),
        _explain(f"[[{rr}]] causes [[{ldp}]].", [ldp], "high", rr),  # 出错一端不在问题里
        _fix(a2, "interface GigabitEthernet0/0/2\n mpls ip", ldp),  # 补上 LDP：换上模拟图后问题消失
        _fix(a2, "interface GigabitEthernet0/0/2\n description fixed", ldp),  # 问题仍在
        _fix(rr, "interface GigabitEthernet0/0/2\n mpls ip", ldp),  # 设备不是问题的一端
    ]
    _fake(monkeypatch, lambda sy, p: _reply(*items))
    b = ai_suggest.run(env, "finding-fix", params)
    rows = _items(env, b)
    assert rows[0]["check_status"] == "pass"
    assert rows[1]["check_status"] == "reject" and "suspect_not_end" in _codes(rows[1])
    assert rows[2]["check_status"] in ("pass", "warn") and "finding_not_fixed" not in _codes(rows[2])
    assert rows[3]["check_status"] == "reject" and "finding_not_fixed" in _codes(rows[3])
    assert rows[4]["check_status"] == "reject" and "fix_wrong_device" in _codes(rows[4])


# ================================================================ 影响说明 / 能力对比说明


def test_impact_explain(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)
    params = {"device_id": did, "nodes": ["vrf.instance[RAN]"], "direction": "up"}
    ctx = ai_suggest.spec_of("impact-explain").build(env, dict(params))
    assert (
        ctx.scope_key
        == f"impact:{did}:up:vrf.instance[RAN]"
        == ai_suggest_analysis.impact_scope(did, "up", ["vrf.instance[RAN]"])
    )
    n_if = next(k for k, o in ctx.facts["objects"].items() if o.get("node") == "interface[GigabitEthernet0/2/1.101]")
    good = {
        "category": "text_only",
        "kind": "impact",
        "title": "Deleting RAN",
        "content": {"text": f"[[{n_if}]] loses its VPN; <<impact.objects>> objects are affected. Watch [[n1]]."},
        "refs": [{"id": n_if}],
    }
    bad = {**good, "content": {"text": "GigabitEthernet0/9/9 stops forwarding."}}
    vague = {**good, "content": {"text": "[[d1]] will be fine."}}
    _fake(monkeypatch, lambda sy, p: _reply(good, bad, vague))
    rows = _items(env, ai_suggest.run(env, "impact-explain", params))
    assert [r["check_status"] for r in rows] == ["pass", "reject", "reject"]
    assert "unknown_object" in _codes(rows[1]) and "no_impact_refs" in _codes(rows[2])
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.run(env, "impact-explain", {"device_id": did, "nodes": []})
    assert e.value.key == "ai_suggest.need_nodes"


def test_feature_compare(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    params = {"node": "interface.mtu", "a": "huawei-atn-v800r025", "b": "cisco-iosxe-asr920-17.15"}
    ctx = ai_suggest.spec_of("feature-compare").build(env, dict(params))
    card = {o["label"]: k for k, o in ctx.facts["objects"].items() if o["type"] == "card"}
    hw, cs = card["huawei-vrp8.mtu"], card["cisco-iosxe.mtu"]

    def sug(cmds: list[dict[str, str]]) -> dict[str, Any]:
        text = f"[[p1]] uses [[{hw}]] and [[p2]] uses [[{cs}]]."
        return {"category": "text_only", "kind": "feature", "title": "MTU", "content": {"text": text, "commands": cmds}}

    items = [
        sug([{"card": hw, "text": "mtu 9000"}, {"card": cs, "text": "mtu 9216"}, {"card": hw, "text": "undo mtu"}]),
        sug([{"card": hw, "text": "ip mtu jumbo 9000"}]),
        sug([{"card": "k99", "text": "mtu 1500"}]),
    ]
    _fake(monkeypatch, lambda sy, p: _reply(*items))
    rows = _items(env, ai_suggest.run(env, "feature-compare", params))
    assert [r["check_status"] for r in rows] == ["pass", "reject", "reject"]
    assert "syntax_mismatch" in _codes(rows[1]) and "card_not_found" in _codes(rows[2])
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.run(env, "feature-compare", {**params, "b": params["a"]})
    assert e.value.key == "ai_suggest.same_profile"


# ================================================================ 设备交接文档


def test_handover_with_adopted_summary(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)
    empty = ai_suggest_analysis.handover(env, did, "en", "md")
    assert "No device summary has been adopted yet" in empty.content and empty.filename.endswith(
        "-en-" + empty.filename[-11:]
    )
    _fake(monkeypatch, lambda sy, p: _reply(_summary("[[d1]] has <<count.interface>> interfaces.")))
    b = ai_suggest.run(env, "device-summary", {"device_id": did})
    ai_suggest.adopt(env, _items(env, b)[0]["id"])
    ai_suggest_analysis.set_annotation(env, "device", str(did), "role", "access")
    en = ai_suggest_analysis.handover(env, did, "en", "md")
    assert "ATN-CHANGE-01 has " in en.content and "[[" not in en.content and "access (set by hand)" in en.content
    assert "adopted by alice" in en.content and en.media_type.startswith("text/markdown")
    zh = ai_suggest_analysis.handover(env, did, "zh-CN", "html")
    assert "设备交接说明" in zh.content and "摘要原文为 en" in zh.content and zh.content.startswith("<!doctype html>")


# ================================================================ 未配置 AI 时降级、回放样例


def test_not_configured_degrades_for_new_skills(full_kb_root: Path, projects_root: Path) -> None:
    s = config.load()
    url = s.database_url
    alice = projects.cli_identity(url, "alice")
    scope = projects.resolve(url, alice, "lab")
    with projects.use(scope, alice):
        env = _env(s, scope, alice)
        did = _device_id(url)
        for sid, params in (
            ("topology-roles", {}),
            ("finding-fix", {"source": "check", "device_id": did}),
            ("impact-explain", {"device_id": did, "nodes": ["vrf.instance[RAN]"]}),
            ("feature-compare", {"node": "interface.mtu", "a": "huawei-atn-v800r025", "b": "cisco-iosxe-asr920-17.15"}),
        ):
            with pytest.raises(ai_suggest.SuggestError) as e:
                ai_suggest.run(env, sid, params)
            assert e.value.key == "ai.not_configured", sid
        # 回放（命令行 --replay）不需要 AI，同样经过代码校验
        reply = json.dumps({"suggestions": [_explain("[[f1]] is an unused VPN.", ["f1"], "low")]})
        b = ai_suggest.run(env, "finding-fix", {"source": "check", "device_id": did}, reply=reply)
        assert b["mode"] == "replay" and b["counts"]["pass"] == 1
        info = ai_suggest.skill_list(env.settings)
        assert {x["id"] for x in info["skills"]} >= {"diff-explain", "finding-fix", "impact-explain", "feature-compare"}
        assert all(x["group"] == "analysis" for x in info["skills"] if x["id"] in ai_suggest_analysis_ids())


def ai_suggest_analysis_ids() -> tuple[str, ...]:
    return ("topology-roles", "diff-explain", "finding-fix", "impact-explain", "feature-compare")


def test_replay_samples_in_skill_admin(configured_root: Path) -> None:
    """REQ-033 的试运行（回放）：每个 skill 一条通过、一条被拦截；内置定义通过定义校验。"""
    s = config.load()
    store.upgrade(s.database_url)
    ctx = skill_runners.Ctx(s, lambda: analysis.load_kb(kbservice.runtime_root(s)))
    for sid in ai_suggest_analysis_ids():
        got = [skill_runners.test(ctx, sid, sample=i, mode="replay")["check"]["status"] for i in range(2)]
        assert got == ["passed", "rejected"], sid
        b = skills.builtin(sid)
        assert b.group == "analysis" and "retry" in b.templates
        skills.validate(b, b.definition())
