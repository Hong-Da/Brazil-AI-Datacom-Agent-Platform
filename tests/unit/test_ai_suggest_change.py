"""变更与割接组的 AI skill（M8-4）：变更意图转脚本、割接方案文档、翻译未支持项、命名映射建议、模板提取。
每个 skill：正常建议（通过并采纳、撤销）、代码校验拒绝（编造对象 / 校验失败）、未配置 AI 时降级。AI 一律用假的客户端
（替换 ai.provider_hook）或回放，不调用外部服务。"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from lmesh.core import ai, ai_suggest, analysis, checkproj, config, kbservice, projects, skill_runners, skills, store

pytestmark = pytest.mark.unit


@pytest.fixture
def lab(full_kb_root: Path, projects_root: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """alice 的项目 lab（ATN-CHANGE-01 与引用的公共设备 ASR920-BASE），AI 配置为假的接口。"""
    monkeypatch.setenv("LMESH_AI__PROVIDER", "openai")
    monkeypatch.setenv("LMESH_AI__BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("LMESH_AI__MODEL", "fake-model")
    s = config.load()
    url = s.database_url
    alice = projects.cli_identity(url, "alice")
    scope = projects.resolve(url, alice, "lab")
    with projects.use(scope, alice):
        yield s, scope, alice


def _env(s: config.Settings, scope: projects.Scope, who: projects.Identity) -> ai_suggest.Env:
    return ai_suggest.Env(
        s.for_actor(who),
        lambda: analysis.load_kb(kbservice.runtime_root(s)),
        project_id=scope.project_id,
        user_id=who.user_id,
        actor=who.username,
        kb_editor=False,
        admin=False,
        lang="en",
    )


def _fake(monkeypatch: pytest.MonkeyPatch, fn: Callable[[str, str], str]) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    def hook(conn, m, system, prompt):  # type: ignore[no-untyped-def]
        calls.append((system, prompt))
        return ai.Reply(fn(system, prompt), m, 10, 5)

    monkeypatch.setattr(ai, "provider_hook", hook)
    return calls


def _device_id(url: str, name: str = "ATN-CHANGE-01") -> int:
    from lmesh.core import importer

    return int(next(d["id"] for d in importer.list_devices(url) if d["name"] == name))


def _reply(*items: dict[str, Any]) -> str:
    return json.dumps({"suggestions": list(items)})


def _ref_of(facts_or_prompt: str, label: str) -> str:
    """提示词里对象表的一行（编号 | schema | 键 …）→ 编号。"""
    for line in facts_or_prompt.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3 and parts[2] == label and parts[0].startswith("n"):
            return parts[0]
    raise AssertionError(label)


def _why(env: ai_suggest.Env, b: dict[str, Any]) -> list[Any]:
    return [(x["title"], x["check"]["reasons"]) for x in ai_suggest.list_suggestions(env, batch_id=b["id"])["items"]]


# ================================================================ 变更意图转脚本


def _edit(edits: list[dict[str, Any]], refs: list[str], title: str = "Edit [[n1]]") -> dict[str, Any]:
    return {
        "category": "graph_edit",
        "kind": "edit",
        "title": title,
        "content": {"edits": edits, "explain": "Code renders the commands."},
        "refs": [{"id": r} for r in refs],
    }


def test_intent_script_pass_adopt_combined_revert(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)

    def reply(system: str, prompt: str) -> str:
        ge = _ref_of(prompt, "GigabitEthernet0/2/2")
        oam = _ref_of(prompt, "OAM")
        return _reply(
            _edit(
                [
                    {
                        "op": "add",
                        "id": "+1",
                        "parent": "d1",
                        "schema": "interface",
                        "key": "GigabitEthernet0/2/3.200",
                        "attrs": {"interface.dot1q_termination": 200, "interface.vrf": "OAM"},
                    },
                    {
                        "op": "add",
                        "parent": "+1",
                        "schema": "interface.ipv4",
                        "key": "10.9.0.1",
                        "attrs": {"interface.ipv4.prefix_length": 30},
                    },
                ],
                [oam],
                f"New sub-interface in [[{oam}]]",
            ),
            _edit([{"op": "set", "target": ge, "attr": "interface.mtu", "value": 9000}], [ge], f"MTU of [[{ge}]]"),
        )

    calls = _fake(monkeypatch, reply)
    b = ai_suggest.run(
        env, "intent-script", {"device_id": did, "intent": "Add a sub-interface in OAM, MTU 9000 on GE0/2/2"}
    )
    assert b["status"] == "done" and b["counts"]["pass"] == 1 and b["counts"]["warn"] == 1, _why(env, b)
    system, prompt = calls[0]
    assert "interface.vrf | ref -> vrf.instance | parent interface" in prompt and "Add a sub-interface" in prompt
    items = sorted(ai_suggest.list_suggestions(env, skill="intent-script")["items"], key=lambda x: x["id"])
    sub, mtu = items
    assert [r["code"] for r in mtu["check"]["reasons"]] == ["high_risk"]  # 改 MTU 由代码判为高风险：提醒，可逐条采纳
    res = sub["check"]["result"]
    assert res["summary"]["verify"] and res["summary"]["rollback_verify"] and res["summary"]["ai_lines"] >= 3
    texts = {ln["text"].strip(): ln["k"] for ln in res["lines"]}
    assert texts["interface GigabitEthernet0/2/3.200"] == "ai" and texts["ip binding vpn-instance OAM"] == "ai"
    assert texts["ip address 10.9.0.1 255.255.255.252"] == "ai"
    # 采纳第一条：生成项目脚本（下发 + 回滚）
    a1 = ai_suggest.adopt(env, sub["id"])
    info = a1["adopt_info"]
    assert info["action"] == "script" and info["rollback_id"]
    actor = checkproj.Actor(alice.user_id, False, "alice")
    fwd = checkproj.get_script(s.database_url, actor, info["group_id"], info["script_id"])["content"]
    assert "interface GigabitEthernet0/2/3.200" in fwd and "mtu 9000" not in fwd
    # 采纳第二条：同一份脚本更新为两条合并的结果
    a2 = ai_suggest.adopt(env, mtu["id"])
    assert a2["adopt_info"]["group_id"] == info["group_id"] and a2["adopt_info"]["updated"]
    fwd = checkproj.get_script(s.database_url, actor, info["group_id"], info["script_id"])["content"]
    assert "interface GigabitEthernet0/2/3.200" in fwd and "mtu 9000" in fwd
    plan = __import__("lmesh.core.ai_suggest_change", fromlist=["x"]).intent_plan(env, b["id"])
    assert plan["adopted"] == [sub["id"], mtu["id"]] and plan["verify"] and plan["rollback_verify"]
    assert any(r["k"] == "ai" and "mtu 9000" in r["text"] for r in plan["rows"])
    # 撤销第二条：脚本回到只有第一条
    ai_suggest.revert(env, mtu["id"])
    fwd = checkproj.get_script(s.database_url, actor, info["group_id"], info["script_id"])["content"]
    assert "mtu 9000" not in fwd and "GigabitEthernet0/2/3.200" in fwd
    # 人工改过脚本后不能撤销
    checkproj.update_script(s.database_url, actor, info["group_id"], info["script_id"], {"content": fwd + "\n# manual"})
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.revert(env, sub["id"])
    assert e.value.key == "ai_suggest.script_modified"


def test_intent_script_rejects_invented_and_invalid(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)

    def reply(system: str, prompt: str) -> str:
        ge = _ref_of(prompt, "GigabitEthernet0/2/2")
        return _reply(
            _edit([{"op": "set", "target": "n999", "attr": "interface.mtu", "value": 1500}], ["n999"]),  # 编造对象
            _edit([{"op": "set", "target": ge, "attr": "interface.mtu", "value": 99999}], [ge]),  # 超出范围
            _edit([{"op": "set", "target": ge, "attr": "interface.vrf", "value": "RAN-0M"}], [ge]),  # 引用不存在
            _edit([{"op": "set", "target": ge, "attr": "interface.nonexistent", "value": 1}], [ge]),  # 不在 Schema
            _edit([{"op": "add", "parent": "d1", "schema": "interface.ipv4", "key": "10.1.1.1"}], [ge]),  # 父对象不对
        )

    _fake(monkeypatch, reply)
    b = ai_suggest.run(env, "intent-script", {"device_id": did, "intent": "something"})
    assert b["counts"]["reject"] == 5, b
    items = sorted(ai_suggest.list_suggestions(env, batch_id=b["id"])["items"], key=lambda x: x["id"])
    codes = [{r["code"] for r in it["check"]["reasons"]} for it in items]
    assert "ref_not_found" in codes[0]
    assert "bad_value" in codes[1]
    assert "ref_missing" in codes[2]
    assert "schema_unknown" in codes[3]
    assert "schema_mismatch" in codes[4]
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.adopt(env, items[1]["id"])
    assert e.value.key == "ai_suggest.check_failed"


def test_intent_script_params(lab) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.run(env, "intent-script", {"device_id": did})
    assert e.value.key == "ai_suggest.need_intent"
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.run(env, "intent-script", {"device_id": 9999, "intent": "x"})
    assert e.value.key == "ai_suggest.device_not_found"


# ================================================================ 割接方案文档

TO = "cisco-iosxe-asr920-17.15"


def _section(
    section: str, zh: str, en: str, steps: list[dict[str, Any]] | None = None, refs: list[str] | None = None
) -> dict[str, Any]:
    return {
        "category": "plan_section",
        "kind": section,
        "title": section.title(),
        "content": {"section": section, "zh": zh, "en": en, "steps": steps or []},
        "refs": [{"id": r} for r in refs or ["d1"]],
    }


def _step_ids(prompt: str) -> list[str]:
    return [ln.split("|")[0].strip() for ln in prompt.splitlines() if ln.startswith("s") and " | " in ln]


def test_cutover_plan_bilingual_and_export(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    from lmesh.core import ai_suggest_change

    s, scope, alice = lab
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)

    def reply(system: str, prompt: str) -> str:
        sid = _step_ids(prompt)
        return _reply(
            _section(
                "overview", "把 [[d1]] 换成 [[d2]]，共 <<steps>> 步。", "Replace [[d1]] with [[d2]] in <<steps>> steps."
            ),
            _section(
                "steps",
                "按代码生成的步骤执行。",
                "Follow the generated steps.",
                [
                    {
                        "step": sid[0],
                        "zh": "割接前记录",
                        "en": "Record first",
                        "check_zh": "记录完整",
                        "check_en": "All recorded",
                    }
                ],
                [sid[0]],
            ),
            _section("rollback", "回退时在 [[d1]] 上执行 undo shutdown。", "Run undo shutdown on [[d1]]."),  # 写出命令
            _section("window", "凌晨执行。", ""),  # 只有中文
            _section("risks", "注意 [[d1]] 与 CORE-RTR-99 的链路。", "Mind the link to CORE-RTR-99."),  # 编造对象
        )

    calls = _fake(monkeypatch, reply)
    b = ai_suggest.run(env, "cutover-plan", {"device_id": did, "to": TO})
    assert b["counts"] == {"pass": 2, "warn": 0, "reject": 3, "total": 5}, _why(env, b)
    assert "d2 | new device" in calls[0][1] and "Simplified Chinese" in calls[0][0]
    items = sorted(ai_suggest.list_suggestions(env, batch_id=b["id"])["items"], key=lambda x: x["id"])
    codes = [{r["code"] for r in it["check"]["reasons"]} for it in items]
    assert "command_in_text" in codes[2] and "need_bilingual" in codes[3] and "unknown_object" in codes[4]
    steps_item = items[1]
    assert any(ln["k"] == "code" for ln in steps_item["check"]["result"]["lines"])  # 命令由代码按步骤填入
    for it in items[:2]:
        ai_suggest.adopt(env, it["id"])
    zh = ai_suggest_change.plan_doc(env, b["id"], "zh-CN", adopted_only=True)
    en = ai_suggest_change.plan_doc(env, b["id"], "en", adopted_only=True)
    assert zh["markdown"].startswith("# 割接方案：ATN-CHANGE-01") and "把 ATN-CHANGE-01 换成" in zh["markdown"]
    assert "Replace ATN-CHANGE-01 with" in en["markdown"] and "Run undo shutdown" not in en["markdown"]
    assert "（这一节没有采纳的内容，需要人工填写）" in zh["markdown"]
    sec = next(x for x in en["doc"]["sections"] if x["section"] == "steps")
    assert sec["parts"][0]["steps"][0]["commands"] == en["doc"]["steps"][0]["commands"]  # 命令来自代码生成的步骤
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.run(env, "cutover-plan", {"device_id": did, "to": "nope"})
    assert e.value.key == "ai_suggest.need_target_profile"


def test_command_hits() -> None:
    from lmesh.core import ai_suggest_change as m

    kb = analysis.load_kb(Path(__file__).resolve().parents[2] / "knowledge")
    fams = ["huawei-vrp8", "cisco-iosxe"]
    assert m.command_hits("Run `display bgp peer` first", kb, fams)
    assert m.command_hits("然后执行 reset bgp all 观察", kb, fams)
    assert m.command_hits("Then router bgp 65000 is entered", kb, fams)
    assert not m.command_hits(
        "Move the uplink cables of [[d1]] to [[d2]] and check that no new alarms appear.", kb, fams
    )
    assert not m.command_hits("割接前在 [[d1]] 上记录接口与路由，确认 <<steps>> 步都完成。", kb, fams)


# ================================================================ 翻译未支持项


def _gap(item: str, config_: str, kind: str = "equivalent", expect: list[str] | None = None) -> dict[str, Any]:
    c: dict[str, Any] = {"item": item, "config": config_, "reason": "Equivalent on the target."}
    if expect:
        c["expect"] = expect
    return {"category": "translate_eq", "kind": kind, "title": f"{item} → target", "content": c, "refs": [{"id": item}]}


def test_translate_gap_parse_check_and_patch(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    from lmesh.core import ai_suggest_change, compare, translate

    s, scope, alice = lab
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)

    def reply(system: str, prompt: str) -> str:
        assert "u1 | line 68 | node | no_render | schema=bgp.peer_group.type" in prompt
        assert "sysname ATN-CHANGE-01" in prompt
        return _reply(
            _gap(
                "u1",
                "router bgp 65000\n neighbor RR peer-group\n neighbor RR remote-as 65000",
                expect=["bgp.peer_group", "bgp.peer_group.remote_as"],
            ),
            _gap("u1", "router bgp 65000\n neighbor RR peer-group"),  # 映射不到预期的节点
            _gap("u2", "hostname ATN-CHANGE-01 now"),  # 目标命令卡不认识
            _gap("u2", "", kind="none"),
            _gap("u9", "end"),  # 编造的项
        )

    _fake(monkeypatch, reply)
    b = ai_suggest.run(env, "translate-gap", {"device_id": did, "to": TO})
    items = sorted(ai_suggest.list_suggestions(env, batch_id=b["id"])["items"], key=lambda x: x["id"])
    st = [(it["check_status"], sorted(r["code"] for r in it["check"]["reasons"])) for it in items]
    assert st[0] == ("warn", ["different_node"]), st
    assert st[1][0] == "reject" and "node_not_mapped" in st[1][1]
    assert st[2][0] == "reject" and "target_not_recognized" in st[2][1]
    assert st[3] == ("pass", [])
    assert st[4][0] == "reject" and "ref_not_found" in st[4][1]
    ai_suggest.adopt(env, items[0]["id"])
    ai_suggest.adopt(env, items[3]["id"])
    patches = ai_suggest_change.translate_patches(s.database_url, scope.project_id, did, TO)
    assert [p["line"] for p in patches] == [4, 68] and patches[0]["kind"] == "none"
    kb = env.kb
    side = compare.side_from_device(s.database_url, kb, did)
    res = translate.translate(side.graph, kb, str(side.graph.graph["profile"]), TO)
    res = ai_suggest_change.apply_translate_patches(res, patches, kb, TO)
    out = res["text"].splitlines()
    assert out[-1] == "end" and [out[n - 1] for n in res["ai_lines"]][0] == "router bgp 65000"
    marked = [u for u in res["unsupported"] if u.get("ai")]
    assert {u["lines"][0] for u in marked} == {4, 68}


# ================================================================ 命名映射建议


def _rules(names: list[dict[str, Any]], ports: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "category": "naming_rules",
        "kind": "rules",
        "title": "Rules for [[d1]]",
        "content": {"names": names, "ports": ports or [], "naming": [], "explain": "Prefix VRF names on [[d1]]."},
        "refs": [{"id": "d1"}],
    }


def test_naming_map_table_conflicts_and_ruleset(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    from lmesh.core import naming

    s, scope, alice = lab
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)

    def reply(system: str, prompt: str) -> str:
        assert "vrf.instance: OAM, RAN" in prompt
        return _reply(
            _rules([{"type": "vrf.instance", "match": "wildcard", "from": "*", "to": "VRF_{1}"}]),
            _rules([{"type": "vrf.instance", "match": "wildcard", "from": "*", "to": "VRF_ONE"}]),  # 冲突
            _rules([{"type": "vrf.instance", "match": "regex", "from": "(", "to": "X"}]),  # 规则不合法
            _rules(
                [
                    {"type": "vrf.instance", "match": "exact", "from": "RAN", "to": "VRF_RAN"},
                    {"type": "vrf.instance", "match": "exact", "from": "NOPE", "to": "VRF_NOPE"},  # 没用上
                ],
                [{"match": "exact", "from": "GigabitEthernet0/2/0", "to": "GigabitEthernet0/0/0"}],  # 端口遗漏
            ),
        )

    _fake(monkeypatch, reply)
    b = ai_suggest.run(env, "naming-map", {"device_id": did, "to": TO})
    items = sorted(ai_suggest.list_suggestions(env, batch_id=b["id"])["items"], key=lambda x: x["id"])
    ok, clash, bad, partial = items
    assert ok["check_status"] == "pass", ok["check"]
    assert "vrf.instance  RAN → VRF_RAN" in [ln["text"] for ln in ok["check"]["result"]["lines"]]
    assert clash["check_status"] == "reject" and {r["code"] for r in clash["check"]["reasons"]} == {"naming_conflict"}
    assert bad["check_status"] == "reject" and bad["check"]["reasons"][0]["code"] == "bad_rules"
    assert partial["check_status"] == "warn"
    assert {r["code"] for r in partial["check"]["reasons"]} == {"rule_unused", "port_unmapped"}
    a = ai_suggest.adopt(env, ok["id"])
    rid = a["adopt_info"]["id"]
    rs = naming.load(None, rid, env.kb)
    assert rs.names[0].as_dict()["to"] == "VRF_{1}" and (naming.user_dir() / f"{rid}.yaml").is_file()
    ai_suggest.revert(env, ok["id"])
    assert not (naming.user_dir() / f"{rid}.yaml").exists()
    # 采纳后被人改过：不能撤销
    a = ai_suggest.adopt(env, ok["id"])
    f = naming.user_dir() / f"{a['adopt_info']['id']}.yaml"
    f.write_text(f.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.revert(env, ok["id"])
    assert e.value.key == "ai_suggest.asset_modified"


# ================================================================ 模板提取


def _import_second_atn(s: config.Settings, scope: projects.Scope, alice: projects.Identity) -> int:
    from lmesh.core import importer

    root = Path(__file__).resolve().parents[2] / "knowledge" / "samples" / "change"
    text = (root / "atn-base.cfg").read_text(encoding="utf-8")
    text = text.replace("sysname ATN-CHANGE-01", "sysname ATN-CHANGE-02").replace("UPLINK-TO-AGG", "UPLINK-TO-AGG-2")
    text = text.replace("10.1.0.1 255.255.255.252", "10.1.0.5 255.255.255.252")
    with projects.use(scope, alice):
        importer.import_sources(
            [("atn2.cfg", text.encode("utf-8"))], s.database_url, "basic", kbservice.runtime_root(s), actor="alice"
        )
    return _device_id(s.database_url, "ATN-CHANGE-02")


def _tpl(src: str, title: str = "Base template for [[d1]] and [[d2]]") -> dict[str, Any]:
    return {
        "category": "template_draft",
        "kind": "template",
        "title": title,
        "content": {"template": src, "explain": "[[d1]] and [[d2]] share the layout."},
        "refs": [{"id": "d1"}, {"id": "d2"}],
    }


def test_template_extract_render_equivalence(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    from lmesh.core import template as tmod

    s, scope, alice = lab
    env = _env(s, scope, alice)
    d1 = _device_id(s.database_url)
    d2 = _import_second_atn(s, scope, alice)

    def reply(system: str, prompt: str) -> str:
        draft = prompt.split("Template draft from code:\n", 1)[1].split("\n\nCandidate variables", 1)[0]
        assert "{{" in draft
        broken = draft.replace("{{", "<<").replace("}}", ">>")  # 把变量写死成固定值：渲染后与设备不等价
        return _reply(_tpl(draft), _tpl("id: x\nbody: |\n  {% repeat nope %}\n"), _tpl(broken))

    _fake(monkeypatch, reply)
    b = ai_suggest.run(env, "template-extract", {"device_ids": [d1, d2]})
    items = sorted(ai_suggest.list_suggestions(env, batch_id=b["id"])["items"], key=lambda x: x["id"])
    good, invalid, broken = items
    assert good["check_status"] in ("pass", "warn") and not any(
        r["level"] == "reject" for r in good["check"]["reasons"]
    ), good["check"]
    cov = good["check"]["result"]["coverage"]
    assert set(cov) == {"ATN-CHANGE-01", "ATN-CHANGE-02"}
    assert invalid["check_status"] == "reject" and invalid["check"]["reasons"][0]["code"] == "template_invalid"
    assert broken["check_status"] == "reject"
    assert {r["code"] for r in broken["check"]["reasons"]} <= {
        "template_mismatch",
        "render_mismatch",
        "template_invalid",
    }
    a = ai_suggest.adopt(env, good["id"])
    tid = a["adopt_info"]["id"]
    assert tmod.is_private_file(tmod.private_dir() / f"{tid}.yaml")
    assert tmod.load_any(kbservice.runtime_root(s), tid, env.kb).id == tid
    ai_suggest.revert(env, good["id"])
    assert not (tmod.private_dir() / f"{tid}.yaml").exists()
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.run(env, "template-extract", {"device_ids": []})
    assert e.value.key == "ai_suggest.need_devices"


# ================================================================ 未配置 AI 时降级、REQ-033 回放样例


SKILLS = ("intent-script", "cutover-plan", "translate-gap", "naming-map", "template-extract")


def test_degrade_without_ai_and_replay(full_kb_root: Path, projects_root: Path) -> None:
    """未配置 AI：五个 skill 都报 ai.not_configured（409 / 退出码 3），核心功能照常；回放（--replay）同样经过代码校验。"""
    s = config.load()
    url = s.database_url
    alice = projects.cli_identity(url, "alice")
    scope = projects.resolve(url, alice, "lab")
    with projects.use(scope, alice):
        env = _env(s, scope, alice)
        did = _device_id(url)
        params = {
            "intent-script": {"device_id": did, "intent": "x"},
            "cutover-plan": {"device_id": did, "to": TO},
            "translate-gap": {"device_id": did, "to": TO},
            "naming-map": {"device_id": did, "to": TO},
            "template-extract": {"device_ids": [did]},
        }
        for sid in SKILLS:
            with pytest.raises(ai_suggest.SuggestError) as e:
                ai_suggest.run(env, sid, params[sid])
            assert e.value.key == "ai.not_configured" and e.value.kind == "state", sid
        info = ai_suggest.skill_list(env.settings)
        assert not info["ai"]["configured"]
        assert {x["id"]: x["group"] for x in info["skills"] if x["id"] in SKILLS} == dict.fromkeys(SKILLS, "change")
        # 回放：编造对象的回复被拒绝
        bad = _reply(_edit([{"op": "delete", "target": "n999"}], ["n999"]))
        b = ai_suggest.run(env, "intent-script", params["intent-script"], reply=bad)
        assert b["mode"] == "replay" and b["counts"]["reject"] == 1


def test_replay_samples_in_skill_admin(full_kb_root: Path, configured_root: Path) -> None:
    """REQ-033 的试运行（回放）：每个 skill 一条通过、一条被拦截；定义本身通过定义校验。"""
    s = config.load()
    store.upgrade(s.database_url)
    ctx = skill_runners.Ctx(s, lambda: analysis.load_kb(kbservice.runtime_root(s)))
    for sid in SKILLS:
        got = [skill_runners.test(ctx, sid, sample=i, mode="replay")["check"]["status"] for i in range(2)]
        assert got == ["passed", "rejected"], sid
        b = skills.builtin(sid)
        assert b.group == "change" and "retry" in b.templates
        skills.validate(b, b.definition())
