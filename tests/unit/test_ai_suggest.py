"""AI 建议框架（M8-2）：每类校验器的通过与拒绝、编造对象被拒、解析失败重试、未配置 AI 时降级、采纳与撤销、取消、
skill 管理页的回放、迁移 0010。AI 一律用假的客户端（替换 ai.provider_hook），不调用外部服务。"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text

from lmesh.core import ai, ai_suggest, analysis, config, kbservice, projects, review, skill_runners, skills, store
from lmesh.core.store.models import AICall, AISuggestion, ReviewItem, SkillCase

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


def _env(s: config.Settings, scope: projects.Scope, who: projects.Identity, kb_editor: bool = False) -> ai_suggest.Env:
    return ai_suggest.Env(
        s.for_actor(who),
        lambda: analysis.load_kb(kbservice.runtime_root(s)),
        project_id=scope.project_id,
        user_id=who.user_id,
        actor=who.username,
        kb_editor=kb_editor,
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


def _summary(text_: str, refs: list[dict[str, Any]] | None = None, title: str = "Summary") -> dict[str, Any]:
    return {"category": "text_only", "kind": "summary", "title": title, "content": {"text": text_}, "refs": refs or []}


def _role(target: str, value: str, reason: str = "") -> dict[str, Any]:
    return {
        "category": "view_hint",
        "kind": "role",
        "title": f"{target}: {value}",
        "content": {"target": target, "key": "role", "value": value, "reason": reason},
        "refs": [{"id": target}],
    }


# ---------------------------------------------------------------- text_only：设备摘要


def test_device_summary_pass_adopt_revert(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)
    calls = _fake(
        monkeypatch,
        lambda sy, p: _reply(
            _summary(
                "[[d1]] has <<count.interface>> interfaces; uplink [[n4]] described UPLINK-TO-AGG.", [{"id": "n4"}]
            )
        ),
    )
    b = ai_suggest.run(env, "device-summary", {"device_id": did})
    assert b["status"] == "done" and b["counts"] == {"pass": 1, "warn": 0, "reject": 0, "total": 1}
    assert b["mode"] == "ai" and b["model"] == "fake-model" and b["ai_call_ids"] and b["skill_run_id"]
    system, prompt = calls[0]
    assert "[[id]]" in system and "<<key>>" in system and "English" in system
    assert "d1 | ATN-CHANGE-01" in prompt and "count.interface = " in prompt
    items = ai_suggest.list_suggestions(env, skill="device-summary")["items"]
    sug = items[0]
    assert sug["check_status"] == "pass" and sug["status"] == "pending" and sug["ai_call_id"] == b["ai_call_ids"][0]
    assert sug["check"]["display"].startswith("ATN-CHANGE-01 has ") and "<<" not in sug["check"]["display"]
    ref = sug["refs"][0]
    assert ref["found"] and ref["device_id"] == did and ref["node"].startswith("interface[") and ref["line"]
    with store.session(s.database_url) as ss:  # 用量按功能（skill 编号）记录，调用记录编号对得上
        call = ss.get(AICall, b["ai_call_ids"][0])
        assert call is not None and call.feature == "device-summary" and call.actor == "alice"
    run = skills.get_run(s.database_url, b["skill_run_id"])
    assert run["source"] == "suggest" and run["status"] == "passed" and run["input"]["facts"]["objects"]["d1"]
    done = ai_suggest.adopt(env, sug["id"])
    assert done["status"] == "adopted" and done["adopt_info"] == {"action": "record"} and done["decided_by"] == "alice"
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.adopt(env, sug["id"])
    assert e.value.key == "ai_suggest.already_adopted"
    assert [x["id"] for x in ai_suggest.adoptions(env)] == [sug["id"]]
    back = ai_suggest.revert(env, sug["id"], "wrong")
    assert back["status"] == "reverted" and back["reverted_by"] == "alice" and back["note"] == "wrong"


def test_invented_objects_rejected_and_enter_regression(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)
    bad = _summary(
        "[[d1]] uplinks via GigabitEthernet9/9/9 to CORE-RTR-99 at 10.99.99.1 and [[n999]]; <<nope>> VPNs.",
        [{"id": "n1"}, {"line": 10_000, "of": "d1"}],
        title="About CORE-RTR-99",
    )
    _fake(monkeypatch, lambda sy, p: _reply(bad))
    b = ai_suggest.run(env, "device-summary", {"device_id": did})
    assert b["counts"]["reject"] == 1
    sug = ai_suggest.list_suggestions(env, batch_id=b["id"])["items"][0]
    codes = {(r["code"], r.get("ref")) for r in sug["check"]["reasons"]}
    assert ("unknown_object", "GigabitEthernet9/9/9") in codes and ("unknown_object", "CORE-RTR-99") in codes
    assert ("unknown_object", "10.99.99.1") in codes and ("ref_not_found", "n999") in codes
    assert ("fact_not_found", "nope") in codes and ("line_not_found", "d1:10000") in codes
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.adopt(env, sug["id"])
    assert e.value.key == "ai_suggest.check_failed" and e.value.data["check"]["status"] == "reject"
    run = skills.get_run(s.database_url, b["skill_run_id"])
    assert run["status"] == "rejected"
    with store.session(s.database_url) as ss:  # 被拦截的线上调用自动进入回归集
        assert ss.scalars(select(SkillCase).where(SkillCase.skill == "device-summary")).first() is not None
    # 编辑后采纳：去掉编造的内容，重新校验通过
    fixed = ai_suggest.adopt(
        env, sug["id"], {"text": "[[d1]] has <<count.interface>> interfaces."}, "Summary", refs=[{"id": "n1"}]
    )
    assert fixed["status"] == "adopted" and fixed["edited"] and fixed["original"]["content"] == bad["content"]
    assert fixed["check_status"] == "pass"


def test_text_check_numbers_and_names() -> None:
    facts = {
        "objects": {"d1": {"type": "device", "label": "ATN-1", "device_id": 1}},
        "numbers": {"count.interface": 12},
        "names": ["UPLINK-TO-AGG", "GigabitEthernet0/1/0", "10.1.0.1"],
    }
    assert ai_suggest.check_text("[[d1]] has <<count.interface>> ports; GigabitEthernet0/1/0 is up.", facts) == []
    assert ai_suggest.check_text("Peer 10.1.0.1/30 runs BGP-4 and IS-IS.", facts) == []
    r = ai_suggest.check_text("It has 12 ports and 7 VLANs.", facts)
    assert [(x["code"], x["level"], x["ref"]) for x in r] == [("number_unverified", "warn", "7")]
    assert ai_suggest.render_text("[[d1]] <<count.interface>> [[x]]", facts) == "ATN-1 12 [[x]]"


def test_bad_reply_retries_once_then_fails(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)
    replies = ["not json at all", _reply(_summary("[[d1]] is a router."))]
    calls = _fake(monkeypatch, lambda sy, p: replies.pop(0))
    b = ai_suggest.run(env, "device-summary", {"device_id": did})
    assert b["status"] == "done" and len(b["ai_call_ids"]) == 2 and b["counts"]["pass"] == 1
    assert "could not be used" in calls[1][1] and "not a JSON object" in calls[1][1]
    _fake(monkeypatch, lambda sy, p: '{"other": 1}')
    b2 = ai_suggest.run(env, "device-summary", {"device_id": did})
    assert b2["status"] == "failed" and b2["error"]["key"] == "ai_suggest.bad_reply" and len(b2["ai_call_ids"]) == 2
    assert ai_suggest.list_suggestions(env, batch_id=b2["id"])["total"] == 0
    # AI 调用失败（网络）也记为失败，不抛出
    monkeypatch.setattr(ai, "provider_hook", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    b3 = ai_suggest.run(env, "device-summary", {"device_id": did})
    assert b3["status"] == "failed" and b3["error"]["key"] == "ai.call_failed"


def test_not_configured_degrades(full_kb_root: Path, projects_root: Path) -> None:
    s = config.load()
    url = s.database_url
    alice = projects.cli_identity(url, "alice")
    scope = projects.resolve(url, alice, "lab")
    with projects.use(scope, alice):
        env = _env(s, scope, alice)
        with pytest.raises(ai_suggest.SuggestError) as e:
            ai_suggest.run(env, "device-summary", {"device_id": _device_id(url)})
        assert e.value.key == "ai.not_configured" and e.value.kind == "state" and e.value.data["reason"]
        info = ai_suggest.skill_list(env.settings)
        assert not info["ai"]["configured"] and {x["id"] for x in info["skills"]} >= {
            "device-summary",
            "topology-roles",
        }
        assert ai_suggest.list_suggestions(env)["total"] == 0
        # 回放不需要 AI（命令行 --replay），同样经过代码校验
        b = ai_suggest.run(env, "device-summary", {"device_id": _device_id(url)}, reply=_reply(_summary("[[d1]].")))
        assert b["mode"] == "replay" and b["status"] == "done" and b["skill_run_id"] is None
        with pytest.raises(ai_suggest.SuggestError) as e2:
            ai_suggest.run(env, "device-summary", {}, reply="{}")
        assert e2.value.key == "ai_suggest.need_device"
        with pytest.raises(ai_suggest.SuggestError) as e3:
            ai_suggest.run(env, "device-summary", {"device_id": 99999}, reply="{}")
        assert e3.value.kind == "not_found"
        with pytest.raises(ai_suggest.SuggestError) as e4:
            ai_suggest.run(env, "ask-query", {}, reply="{}")
        assert e4.value.key == "ai_suggest.skill_unknown"


def test_disabled_skill(lab) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    skills.set_enabled("device-summary", False, "admin")
    try:
        with pytest.raises(ai_suggest.SuggestError) as e:
            ai_suggest.run(_env(s, scope, alice), "device-summary", {"device_id": _device_id(s.database_url)})
        assert e.value.key == "skills.disabled" and e.value.kind == "state"
    finally:
        skills.set_enabled("device-summary", True, "admin")


# ---------------------------------------------------------------- view_hint：拓扑角色


def test_topology_roles_view_hint(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    prompts: list[str] = []

    def reply(sy: str, p: str) -> str:
        prompts.append(p)
        return _reply(
            _role("d1", "access", "[[d1]] has one uplink."),
            _role("d2", "PE"),
            _role("d9", "core"),
            _role("d1", "firewall"),
            {**_role("d2", "core"), "content": {"target": "d2", "key": "color", "value": "red"}},
        )

    _fake(monkeypatch, reply)
    b = ai_suggest.run(env, "topology-roles", {})
    assert b["counts"] == {"pass": 2, "warn": 0, "reject": 3, "total": 5} and b["scope_key"] == "topology"
    assert "d1 | " in prompts[0] and "d2 | " in prompts[0]
    items = {x["title"]: x for x in ai_suggest.list_suggestions(env, skill="topology-roles")["items"]}
    assert {r["code"] for r in items["d9: core"]["check"]["reasons"]} == {"ref_not_found"}
    assert {r["code"] for r in items["d1: firewall"]["check"]["reasons"]} == {"bad_hint_value"}
    assert {r["code"] for r in items["d2: core"]["check"]["reasons"]} == {"bad_hint_key"}
    # 批量采纳只采纳通过的
    res = ai_suggest.adopt_batch(env, "view_hint", skill="topology-roles")
    assert sorted(res["adopted"]) == sorted([items["d1: access"]["id"], items["d2: PE"]["id"]])
    assert len(res["skipped"]) == 3 and res["failed"] == []
    ann = {(a["target"], a["key"]): a for a in ai_suggest.list_annotations(s.database_url, scope.project_id)}
    d1 = str(items["d1: access"]["refs"][0]["device_id"])
    assert ann[(d1, "role")]["value"] == "access" and ann[(d1, "role")]["source"] == "ai"
    # 撤销恢复原状（原来没有标注 → 删除）
    ai_suggest.revert(env, items["d1: access"]["id"])
    assert (d1, "role") not in {
        (a["target"], a["key"]) for a in ai_suggest.list_annotations(s.database_url, scope.project_id)
    }
    # 手工标注：新的 AI 建议校验给出提醒；采纳后撤销恢复手工值；被别的建议覆盖后不能撤销
    from lmesh.core.store.models import ViewAnnotation

    with store.session(s.database_url) as ss:
        ss.add(ViewAnnotation(project_id=scope.project_id, target_type="device", target=d1, key="role", value="core"))
    _fake(monkeypatch, lambda sy, p: _reply(_role("d1", "access")))
    b2 = ai_suggest.run(env, "topology-roles", {})
    s2 = ai_suggest.list_suggestions(env, batch_id=b2["id"])["items"][0]
    assert s2["check_status"] == "warn" and s2["check"]["reasons"][0]["code"] == "overrides_manual"
    assert ai_suggest.adopt_batch(env, "view_hint", batch_id=b2["id"])["adopted"] == []  # warn 不批量采纳
    ai_suggest.adopt(env, s2["id"])
    b3 = ai_suggest.run(env, "topology-roles", {})
    s3 = ai_suggest.list_suggestions(env, batch_id=b3["id"])["items"][0]
    ai_suggest.adopt(env, s3["id"])
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.revert(env, s2["id"])
    assert e.value.key == "ai_suggest.superseded"
    ai_suggest.revert(env, s3["id"])
    ai_suggest.revert(env, s2["id"])
    cur = next(a for a in ai_suggest.list_annotations(s.database_url, scope.project_id) if a["target"] == d1)
    assert cur["value"] == "core" and cur["source"] == "user"
    # 编辑后采纳：改成不允许的取值被拒绝（不保存），改成允许的取值通过
    b4 = ai_suggest.run(env, "topology-roles", {})
    s4 = ai_suggest.list_suggestions(env, batch_id=b4["id"])["items"][0]
    with pytest.raises(ai_suggest.SuggestError):
        ai_suggest.adopt(env, s4["id"], {"target": "d1", "key": "role", "value": "router"})
    assert ai_suggest.get(env, s4["id"])["status"] == "pending"
    ok = ai_suggest.adopt(env, s4["id"], {"target": "d1", "key": "role", "value": "pe"})
    assert (
        ok["status"] == "adopted"
        and ok["adopt_info"]["value"] == "pe"
        and ok["adopt_info"]["prior"]["source"] == "user"
    )
    d = ai_suggest.dismiss
    with pytest.raises(ai_suggest.SuggestError):
        d(env, s4["id"])


# ---------------------------------------------------------------- kb_review、script_valid、refs_exist（用临时 skill 定义）


@pytest.fixture
def any_category(lab, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """把 device-summary 的允许类别临时放宽到全部类别（上下文不变），用回放验证每个校验器。"""
    import dataclasses

    spec = ai_suggest.spec_of("device-summary")
    monkeypatch.setitem(
        ai_suggest.SKILLS, "device-summary", dataclasses.replace(spec, categories=tuple(ai_suggest.CATEGORIES))
    )
    return lab


def _replay(env: ai_suggest.Env, did: int, *items: dict[str, Any]) -> list[dict[str, Any]]:
    b = ai_suggest.run(env, "device-summary", {"device_id": did}, reply=_reply(*items))
    return list(reversed(ai_suggest.list_suggestions(env, batch_id=b["id"])["items"]))


def test_kb_review_category(any_category) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = any_category
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)
    card = {
        "category": "kb_review",
        "kind": "card",
        "title": "Draft for [[n1]]",
        "content": {"review_kind": "suggestion", "target": "commands/huawei-vrp8/x.yaml", "payload": {"note": "x"}},
        "refs": [{"id": "n1"}],
    }
    bad = {**card, "content": {"review_kind": "nope", "payload": {}}}
    good, wrong = _replay(env, did, card, bad)
    assert good["check_status"] == "pass" and good["kb"]
    assert wrong["check"]["reasons"][0]["code"] == "bad_review_kind"
    with pytest.raises(ai_suggest.SuggestError) as e:  # 普通账号不能采纳知识库类建议
        ai_suggest.adopt(env, good["id"])
    assert e.value.kind == "forbidden"
    with pytest.raises(ai_suggest.SuggestError):
        ai_suggest.adopt_batch(env, "kb_review")
    maint = _env(s, scope, alice, kb_editor=True)
    a = ai_suggest.adopt(maint, good["id"])
    rid = a["adopt_info"]["review_item_id"]
    item = review.get(s.database_url, rid)
    assert item and item["status"] == "pending" and item["source"]["method"] == "ai"
    assert item["source"]["suggestion_id"] == good["id"]
    ai_suggest.revert(maint, good["id"])
    assert review.get(s.database_url, rid)["status"] == "rejected"  # type: ignore[index]
    a2 = ai_suggest.adopt(maint, good["id"])
    with store.session(s.database_url) as ss:
        it = ss.get(ReviewItem, a2["adopt_info"]["review_item_id"])
        assert it is not None
        it.status = "approved"
    with pytest.raises(ai_suggest.SuggestError) as e2:
        ai_suggest.revert(maint, good["id"])
    assert e2.value.key == "ai_suggest.review_decided"


def test_script_valid_category(any_category) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = any_category
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)
    ok_script = "interface GigabitEthernet0/2/0\n description UPLINK-TO-AGG-02\nquit"
    good = {"category": "script_valid", "title": "Fix", "content": {"device": "d1", "script": ok_script}}
    bad_vrf = "interface GigabitEthernet0/2/1.101\n ip binding vpn-instance NOPE\nquit"
    broken = {**good, "content": {"device": "d1", "script": bad_vrf}}
    vague = {**good, "content": {"device": "d1", "script": "interface GigabitEthernet0/2/0\n frobnicate now\nquit"}}
    unfixed = {**good, "content": {**good["content"], "fixes": [{"rule": "x.rule", "node": "interface[X]"}]}}
    nodev = {**good, "content": {"device": "d7", "script": ok_script}}
    a, b, c, d, v = _replay(env, did, good, broken, unfixed, nodev, vague)
    assert v["check_status"] == "warn" and v["check"]["reasons"][0]["code"] == "script_unverifiable"
    assert a["check_status"] == "pass" and a["check"]["result"]["summary"]
    assert b["check_status"] == "reject" and b["check"]["reasons"][0]["code"] == "script_error"
    assert {r["code"] for r in c["check"]["reasons"]} == {"problem_not_fixed"}
    assert d["check"]["reasons"][0]["code"] == "ref_not_found"
    done = ai_suggest.adopt(env, a["id"])
    info = done["adopt_info"]
    assert info["action"] == "script" and info["device_id"] == did
    from lmesh.core import checkproj

    actor = checkproj.Actor(alice.user_id, False, "alice")
    assert checkproj.get_script(s.database_url, actor, info["group_id"], info["script_id"])["content"] == ok_script
    ai_suggest.revert(env, a["id"])
    with pytest.raises(checkproj.ProjectError):
        checkproj.get_script(s.database_url, actor, info["group_id"], info["script_id"])
    # 采纳后改过的脚本不能撤销
    again = ai_suggest.adopt(env, a["id"])["adopt_info"]
    checkproj.update_script(
        s.database_url, actor, again["group_id"], again["script_id"], {"content": ok_script + "\n#"}
    )
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.revert(env, a["id"])
    assert e.value.key == "ai_suggest.script_modified"


def test_refs_exist_category_and_structure(any_category) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = any_category
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)
    ok_ = {"category": "refs_exist", "title": "Evidence", "content": {}, "refs": [{"id": "n1"}, {"line": 3}]}
    none = {"category": "refs_exist", "title": "No evidence", "content": {}, "refs": []}
    junk = {"category": "made_up", "title": "?", "content": {}}
    notdict = {"category": "refs_exist", "title": "x", "content": "text", "refs": [{"id": "n1"}]}
    a, b, c, d = _replay(env, did, ok_, none, junk, notdict)
    assert a["check_status"] == "pass" and a["refs"][1]["device_id"] == did
    assert b["check"]["reasons"][0]["code"] == "no_refs"
    assert c["check"]["reasons"][0]["code"] == "bad_category"
    assert d["check"]["reasons"][0]["code"] == "bad_content"
    assert ai_suggest.dismiss(env, a["id"], "no")["status"] == "dismissed"
    assert ai_suggest.restore(env, a["id"])["status"] == "pending"
    with pytest.raises(ai_suggest.SuggestError):
        ai_suggest.restore(env, a["id"])
    ai_suggest.dismiss(env, a["id"])
    assert ai_suggest.adopt(env, a["id"])["status"] == "adopted"  # 忽略之后仍可采纳


def test_cancel_discards_result(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)
    bid = ai_suggest.start(env, "device-summary", {"device_id": did})

    def reply(sy: str, p: str) -> str:
        ai_suggest.cancel(env, bid)  # AI 回复到达之前用户点了取消
        return _reply(_summary("[[d1]]."))

    _fake(monkeypatch, reply)
    b = ai_suggest.execute(env, bid)
    assert b["status"] == "cancelled" and b["ai_call_ids"]
    assert ai_suggest.list_suggestions(env, batch_id=bid)["total"] == 0
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.cancel(env, bid)
    assert e.value.key == "ai_suggest.not_running"


def test_background_task_keeps_project(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    import time

    from lmesh.core import tasks

    s, scope, alice = lab
    env = _env(s, scope, alice)
    _fake(monkeypatch, lambda sy, p: _reply(_role("d1", "pe")))
    r = ai_suggest.run(env, "topology-roles", {}, background=True)
    for _ in range(200):
        t = tasks.get(s.database_url, r["task_id"])
        if t and t["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert t and t["status"] == "done" and t["result"]["id"] == r["batch_id"] and t["created_by"] == "alice"
    assert ai_suggest.get_batch(env, r["batch_id"])["task_id"] == r["task_id"]
    # 别的项目看不到这次运行与建议
    other = ai_suggest.Env(s, env.kb_loader, project_id=scope.project_id + 999)
    with pytest.raises(ai_suggest.SuggestError):
        ai_suggest.get_batch(other, r["batch_id"])
    assert ai_suggest.list_suggestions(other)["total"] == 0


def test_replay_samples_in_skill_admin(configured_root: Path) -> None:
    """REQ-033 的试运行（回放）对新 skill 同样可用：每个 skill 一条通过、一条被拦截。"""
    s = config.load()
    store.upgrade(s.database_url)
    ctx = skill_runners.Ctx(s, lambda: analysis.load_kb(kbservice.runtime_root(s)))
    for sid in ("device-summary", "topology-roles"):
        got = [skill_runners.test(ctx, sid, sample=i, mode="replay")["check"]["status"] for i in range(2)]
        assert got == ["passed", "rejected"], sid
        b = skills.builtin(sid)
        assert b.group == "analysis" and "retry" in b.templates
        skills.validate(b, b.definition())  # 内置定义本身通过定义校验（变量都已登记）


def test_migration_0010_from_0009(db_url: str) -> None:
    from tests.unit.test_project_refs import _upgrade_to

    _upgrade_to(db_url, "0009")
    with store.get_engine(db_url).begin() as c:
        c.execute(
            text(
                "INSERT INTO tasks (id, kind, status, progress, message, created_by, created_at, updated_at) "
                "VALUES ('t1', 'ingest', 'done', 100, '', '', :n, :n)"
            ),
            {"n": "2026-10-19 00:00:00"},
        )
    store._UPGRADED.discard(db_url)
    store.upgrade(db_url)
    names = store.table_names(db_url)
    assert {"ai_suggestions", "ai_suggestion_batches", "view_annotations"} <= set(names)
    with store.session(db_url) as ss:
        assert ss.scalars(select(AISuggestion)).first() is None
        assert ss.scalar(text("SELECT count(*) FROM tasks")) == 1


def test_estimate_and_revert_window(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime, timedelta

    s, scope, alice = lab
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)
    est = ai_suggest.estimate(env, "device-summary", {"device_id": did})
    assert 100 < est["tokens"] < ai_suggest.TOKEN_WARN and est["warn"] is False
    assert ai_suggest.estimate_tokens("abcd" * 10) == 10 and ai_suggest.estimate_tokens("中文") == 2
    _fake(monkeypatch, lambda sy, p: _reply(_summary("[[d1]].")))
    b = ai_suggest.run(env, "device-summary", {"device_id": did})
    assert b["params"]["estimate"] > 100 and b["connection"]  # 运行中就记下接口与预计输入量
    sid = ai_suggest.list_suggestions(env, batch_id=b["id"])["items"][0]["id"]
    # 大请求提示线：全局 ai.warn_tokens（默认 50000，0 = 不提示）；本人关闭提示优先
    from lmesh.core import ai_connections

    assert s.get("ai.warn_tokens") == 50000 and est["threshold"] == 50000
    monkeypatch.setenv("LMESH_AI__WARN_TOKENS", "100")
    env100 = _env(config.load(), scope, alice)
    assert ai_suggest.estimate(env100, "device-summary", {"device_id": did})["warn"] is True
    ai_connections.save_mine(env100.settings, alice, {"no_token_warn": True})
    off = ai_suggest.estimate(env100, "device-summary", {"device_id": did})
    assert off["warn"] is False and off["threshold"] == 0
    assert ai_suggest.skill_list(env100.settings)["ai"]["warn_tokens"] == 0
    assert ai_connections.mine(env100.settings, alice)["no_token_warn"] is True
    ai_connections.save_mine(env100.settings, alice, {"no_token_warn": False})
    assert ai_suggest.skill_list(env100.settings)["ai"]["warn_tokens"] == 100
    monkeypatch.setenv("LMESH_AI__WARN_TOKENS", "0")
    assert ai_suggest.estimate(_env(config.load(), scope, alice), "device-summary", {"device_id": did})["warn"] is False
    ai_suggest.adopt(env, sid)
    with store.session(s.database_url) as ss:
        row = ss.get(AISuggestion, sid)
        assert row is not None
        row.decided_at = datetime.now(UTC) - timedelta(days=ai_suggest.REVERT_DAYS + 1)
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.revert(env, sid)
    assert e.value.key == "ai_suggest.revert_expired"


def test_text_segments() -> None:
    facts = {"objects": {"d1": {"type": "device", "label": "ATN-1"}}, "numbers": {"n": 3}}
    segs = ai_suggest.text_segments("[[d1]] has <<n>> links and [[x9]].", facts)
    assert [(s["t"], s["v"]) for s in segs] == [
        ("ref", "ATN-1"),
        ("text", " has "),
        ("num", "3"),
        ("text", " links and "),
        ("ref", "x9"),
        ("text", "."),
    ]
    assert segs[4]["found"] is False and segs[0]["found"] is True


def test_render_title() -> None:
    facts = {"objects": {"d1": {"type": "device", "label": "ATN-1"}}}
    assert ai_suggest.render_title("d1: access", facts) == "ATN-1: access"
    assert ai_suggest.render_title("[[d1]] and d9 and bgp4", facts) == "ATN-1 and d9 and bgp4"
