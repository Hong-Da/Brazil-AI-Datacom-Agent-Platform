"""内置 AI skill（REQ-033）：提示词与原来逐字相同（回归）、渲染、版本 / 回滚 / 恢复内置、调用记录与反馈、回归集与候选示例、
试运行（回放与假的 AI）、进化（假的 AI）与批准。AI 一律用假的客户端（替换 ai.provider_hook）。"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from lmesh.core import ai, analysis, ask, config, script_check_ai, skill_runners, skills, store, topology
from lmesh.core import rules as rulesmod

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
BASE = (KB_ROOT / "samples" / "change" / "atn-base.cfg").read_text(encoding="utf-8")

# ---------------------------------------------------------------- 改造前写在代码里的提示词（逐字复制，用于回归比对）

ORIG_EXTRACT_SYSTEM = (
    "You convert router command syntax from vendor documentation into a strict notation: keywords as plain words, "
    "parameters as <name>, optional parts in [ ], required choices in { a | b }, repetition as &<1-N> after an element. "
    "Reply with the corrected syntax only, on one line, nothing else."
)
ORIG_Q_SYSTEM = """You turn a network engineer's question about router configurations into ONE read-only query in the
LucidMesh graph query language. The query is validated and executed by code; never answer the question yourself.
Grammar: {syntax}
Operators: {ops}
Notes: {notes}
Reply with JSON only: {{"query": "<query text>"}}"""
ORIG_A_SYSTEM = """You answer a network engineer's question using ONLY the query result below. Every statement must cite the
result rows it relies on (row numbers), and list the facts it states as {{"row": n, "field": "<column>", "value": "<value>"}};
a statement about how many rows match uses "count". Statements that are not configuration facts (advice, opinions)
have no facts. Answer in {lang}. Reply with JSON only:
{{"statements": [{{"text": "...", "cites": [1], "facts": [{{"row": 1, "field": "description", "value": "..."}}], "count": null}}]}}"""
ORIG_G_SYSTEM = """You write router configuration for the platform family {family} (profile {profile}). Output only the
configuration lines to add, in the device's own syntax, inside one ``` code block, without session commands
(no system-view / configure terminal / commit / end). The configuration will be parsed and checked by code before
anyone sees it."""
ORIG_REVIEW_SYSTEM = (
    "You review router configuration scripts (Huawei VRP / Cisco IOS-XE) against the given rules only. "
    "Values in the script were anonymised; never guess real values. "
    'Reply with JSON only: {"findings": [{"rule": "<rule id>", "line": <line number>, '
    '"evidence": "<exact text copied from that line>", "message": "<one sentence>", "suggestion": "<one sentence>"}]}. '
    "Report only lines that violate a listed rule; an empty list is fine. Every finding must quote evidence from its line."
)


def orig_q_prompt(question: str, devices: list[Any], catalog: str, error: str | None) -> str:
    devs = "\n".join(
        f"- {d.name} (profile {d.g.graph.get('profile')}, family {d.g.graph.get('family')})" for d in devices
    )
    out = f"Devices:\n{devs}\n\nSchema (object -> fields):\n{catalog}\n\nQuestion: {question}"
    if error:
        out += f"\n\nYour previous query was rejected by the validator: {error}\nWrite a corrected query."
    return out


def orig_review_prompt(text: str, rules: list[rulesmod.Rule]) -> str:
    parts = ["Rules:"]
    for r in rules:
        title = r.title.get("en") or r.title.get("zh-CN") or r.id
        msg = r.message.get("en") or ""
        sug = r.suggestion.get("en") or ""
        parts.append(f"- {r.id} (applies to: {r.target}; severity {r.severity}): {title}. {msg} {sug}".strip())
    parts.append("")
    parts.append("Script (line number | text):")
    for i, ln in enumerate(text.split("\n"), start=1):
        if ln.strip():
            parts.append(f"{i} | {ln}")
    return "\n".join(parts)


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


@pytest.fixture(scope="module")
def devices(kb):  # type: ignore[no-untyped-def]
    return topology.from_texts([{"name": "a.cfg", "text": BASE}], kb)


def test_builtin_prompts_identical_to_previous_code(tmp_root: Path, kb, devices, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert skills.list_ids() == list(skills.ORDER)
    # 命令卡抽取
    s = skills.current("card-extract")
    assert s.system_text() == ORIG_EXTRACT_SYSTEM and s.active == "builtin" and s.enabled
    f = {"title": "ip address {x}", "format": "**ip address** *ip* { *mask* }"}
    assert s.prompt_text(**f) == (
        f"Command: {f['title']}\nDocumentation syntax line (Markdown, bold = keyword, italic = parameter):\n{f['format']}\n"
    )
    # 问答：查询（目录换成固定文字，只比较拼接）
    monkeypatch.setattr(ask, "catalog", lambda kb_: "interface -> name:string")
    from lmesh.core import gquery

    g = gquery.grammar()
    devs = ask.devices_list(devices)
    for err in (None, "unknown field {x}"):
        system, prompt = ask.query_messages(skills.current("ask-query"), "哪些 {接口}？", devs, kb, err)
        assert system == ORIG_Q_SYSTEM.format(syntax=g["syntax"], ops=", ".join(g["ops"]), notes="; ".join(g["notes"]))
        assert prompt == orig_q_prompt("哪些 {接口}？", devices, "interface -> name:string", err)
    # 问答：回答
    result = {
        "text": "FIND interface",
        "columns": [{"field": "mtu"}],
        "rows": [
            {
                "n": 1,
                "device": "D",
                "label": "GE0/1",
                "node": "interface[GE0/1]",
                "cells": {"mtu": {"value": 1500, "origin": "default"}},
            }
        ],
        "count": 1,
    }
    for lang, name in (("zh-CN", "Simplified Chinese"), ("pt-BR", "Brazilian Portuguese"), ("xx", "English")):
        system, prompt = ask.answer_messages(skills.current("ask-answer"), "Q?", result, lang)
        assert system == ORIG_A_SYSTEM.format(lang=name)
        assert prompt == f"Question: Q?\n\nQuery:\nFIND interface\n\nResult:\n{ask.result_body(result)}"
        assert '"1500 (default)"' in prompt
    # 生成
    for ctx, fb in (("", ""), ("interface: GE0/1", "- line 2: blocked")):
        system, prompt = ask.generate_messages(
            skills.current("config-generate"), "huawei-vrp8", "p1", "D1", ctx, "加 {子接口}", fb
        )
        assert system == ORIG_G_SYSTEM.format(family="huawei-vrp8", profile="p1")
        want = f"Device: D1\nExisting objects:\n{ctx or '(empty configuration)'}\n\nRequest: 加 {{子接口}}"
        if fb:
            want += (
                f"\n\nThe previous attempt was blocked by the checks:\n{fb}\nReturn the full corrected configuration."
            )
        assert prompt == want
    # 脚本审查
    rules = [r for r in rulesmod.load_dir(kb, KB_ROOT / "rules") if r.ai][:2]
    assert rules
    for text in ("interface GE0/1\n description x\n\n#", "", "\n  \n"):
        system, prompt = script_check_ai.messages(
            skills.current("script-review"), text, [script_check_ai.rule_info(r) for r in rules]
        )
        assert system == ORIG_REVIEW_SYSTEM and prompt == orig_review_prompt(text, rules)


def test_render_and_examples() -> None:
    assert skills.render("a {x} {{y}} {z} {{", {"x": "{z}", "z": 1}) == "a {z} {y} 1 {"
    assert skills.render('{"k": 1} { a | b }', {"a": 2}) == '{"k": 1} { a | b }'
    assert skills.placeholders("{a} {{b}} {c_1} { d }") == {"a", "c_1"}
    s = skills.builtin("card-extract").with_definition({"examples": [{"input": "IN", "output": "OUT", "note": "n"}]})
    assert s.system_text() == ORIG_EXTRACT_SYSTEM + "\n\nExamples:\n\nNote: n\nInput:\nIN\nOutput:\nOUT"


def test_versions_rollback_restore_and_validation(tmp_root: Path) -> None:
    sid = "ask-answer"
    b = skills.builtin(sid)
    r = skills.save(sid, {"system": b.system + "\nBe brief."}, "admin", "简短")
    assert r == {"version": "1", "unchanged": False, "warnings": []}
    assert skills.current(sid).active == "1" and skills.current(sid).system.endswith("Be brief.")
    assert skills.save(sid, {"system": b.system + "\nBe brief."}, "admin")["unchanged"] is True
    r2 = skills.save(sid, {"system": "Answer in {lang} only.", "examples": [{"input": "i", "output": "o"}]}, "admin")
    assert r2["version"] == "2" and r2["warnings"] == []
    vs = skills.versions(sid)
    assert [v["version"] for v in vs] == ["builtin", "1", "2"] and vs[2]["active"] and vs[2]["based_on"] == "1"
    assert vs[1]["author"] == "admin" and vs[1]["note"] == "简短" and vs[1]["source"] == "edit"
    d = skills.diff(sid, "builtin", "2")
    by = {f["field"]: f for f in d["fields"]}
    assert by["system"]["changed"] and not by["prompt"]["changed"] and by["examples"]["changed"]
    assert any(x["op"] == "add" and x["text"] == "Answer in {lang} only." for x in by["system"]["lines"])
    assert skills.rollback(sid, "1")["active"] == "1" and skills.current(sid).system.endswith("Be brief.")
    assert skills.restore(sid)["active"] == "builtin" and skills.current(sid).system == b.system
    assert len(skills.versions(sid)) == 3  # 版本文件不删除
    with pytest.raises(skills.SkillError) as e:
        skills.rollback(sid, "9")
    assert e.value.kind == "not_found"
    with pytest.raises(skills.SkillError) as e:
        skills.save(sid, {"system": "Use {nope}", "prompt": "", "tools": ["shell"], "output": {"format": "xml"}})
    keys = {i["key"] for i in e.value.data["issues"]}
    assert e.value.kind == "invalid" and keys == {
        "skills.issue.unknown_var",
        "skills.issue.empty",
        "skills.issue.tools",
        "skills.issue.output",
    }
    with pytest.raises(skills.SkillError) as e:
        skills.save("ask-query", {"templates": {}})
    assert e.value.data["issues"][0]["key"] == "skills.issue.template_missing"
    w = skills.save("ask-query", {"prompt": "Question: {question}"})["warnings"]
    assert {x["params"]["name"] for x in w} == {"devices", "catalog"}
    with pytest.raises(skills.SkillError):
        skills.builtin("../etc")
    # 生效的版本文件丢失时退回内置版本
    (skills.user_dir() / "ask-query" / "versions" / "0001.yaml").unlink()
    assert skills.current("ask-query").active == "builtin"


class _S:
    """只带数据库地址与保留天数的设置（PostgreSQL 用例用）。"""

    def __init__(self, url: str):
        self.database_url = url

    def get(self, key: str) -> Any:
        return {"ai.skill_log_days": 90}.get(key)


def test_runs_feedback_cases_stats(db_url: str) -> None:
    store.upgrade(db_url)
    st: Any = _S(db_url)
    s = skills.current("ask-query")
    from lmesh.core import users

    alice = users.create_user(db_url, "alice", "Alice-pass-1", "user")
    bob = users.create_user(db_url, "bob", "Bob-pass-12", "user")
    a = skills.Actor(alice["id"], "alice")
    r_ok = skills.log_run(
        st, s, "ask", "passed", {"question": "Q1"}, '{"query": "FIND interface"}', {"summary": {"status": "passed"}}
    )
    r_bad = skills.log_run(st, s, "ask", "rejected", {"question": "Q2"}, "nope", {"error": {"key": "ask.bad_reply"}})
    r_test = skills.log_run(st, s, "test", "rejected", {"question": "Q3"}, "x", {})
    assert r_ok and r_bad and r_test
    c = skills.cases(db_url, "ask-query")
    assert [x["reason"] for x in c["regression"]] == ["rejected"] and c["candidates"] == []  # 试运行不自动入集
    fb = skills.feedback(db_url, r_ok, "up", actor=a)
    assert fb["case"]["kind"] == "candidate"
    fb2 = skills.feedback(db_url, r_bad, "down", "FIND interface WHERE mtu = 9216", actor=a)
    assert fb2["case"]["existing"] is True  # 同样的输入只留一条，更正写到已有的案例上
    c = skills.cases(db_url, "ask-query")
    assert (
        c["regression"][0]["expect"] == "FIND interface WHERE mtu = 9216"
        and c["regression"][0]["reason"] == "correction"
    )
    with pytest.raises(skills.SkillError):
        skills.feedback(db_url, 99999, "up")
    with pytest.raises(skills.SkillError):
        skills.feedback(db_url, r_ok, "meh")
    # 普通账号只能评价自己的调用
    r_mine = skills.log_run(st, s, "ask", "passed", {"question": "Q4"}, "{}", {}, actor=skills.Actor(bob["id"], "bob"))
    assert r_mine
    with pytest.raises(skills.SkillError):
        skills.feedback(db_url, r_mine, "up", actor=a, is_admin=False)
    stat = skills.stats(db_url, 30)["ask-query"]
    assert (
        stat["calls"] == 3 and stat["passed"] == 2 and stat["rejected"] == 1 and stat["up"] == 1 and stat["down"] == 1
    )
    assert stat["corrections"] == 1 and stat["pass_rate"] == round(2 / 3, 4) and stat["regression_cases"] == 1
    assert stat["candidates"] == 1
    det = skills.stats_detail(db_url, "ask-query", 7)
    assert len(det["daily"]) == 7 and det["daily"][-1]["calls"] == 3 and det["by_version"][0]["version"] == "builtin"
    assert [x["source"] for x in skills.runs(db_url, "ask-query", 10)] == ["ask", "test", "ask", "ask"]
    # 手动加入、删除、清理
    case = skills.add_case(db_url, "ask-query", r_test, "regression", a, "手动")
    assert case["reason"] == "manual" and case["note"] == "手动"
    skills.delete_case(db_url, "ask-query", case["id"])
    with pytest.raises(skills.SkillError):
        skills.get_case(db_url, "ask-query", case["id"])
    from lmesh.core.store.models import SkillRun, utcnow

    with store.session(db_url) as ss:
        old = ss.get(SkillRun, r_test)
        assert old is not None
        old.created_at = utcnow() - timedelta(days=200)
    assert skills.cleanup(db_url, 90, force=True) == 1
    assert len(skills.cases(db_url, "ask-query")["regression"]) == 1  # 案例有自己的副本


def test_log_run_sanitizes(configured_root: Path) -> None:
    s = config.load()
    store.upgrade(s.database_url)
    rid = skills.log_run(
        s,
        skills.current("config-generate"),
        "generate",
        "passed",
        {"request": "snmp-agent community read cipher pub123"},
        "x",
        {},
    )
    assert rid
    run = skills.get_run(s.database_url, rid)
    assert "pub123" not in json.dumps(run["input"]) and "LMESH-SECRET" in run["input"]["request"]


def _ctx(kb) -> skill_runners.Ctx:  # type: ignore[no-untyped-def]
    return skill_runners.Ctx(config.load(), lambda: kb, "en")


def test_replay_samples_without_ai(configured_root: Path, kb) -> None:  # type: ignore[no-untyped-def]
    store.upgrade(config.load().database_url)
    ctx = _ctx(kb)
    expect = {
        "card-extract": ["passed", "rejected"],
        "ask-query": ["passed", "rejected"],
        "ask-answer": ["passed", "corrected"],
        "config-generate": ["passed", "rejected"],
        "script-review": ["passed", "rejected"],
    }
    for sid, statuses in expect.items():
        got = [skill_runners.test(ctx, sid, sample=i, mode="replay")["check"]["status"] for i in range(2)]
        assert got == statuses, sid
    r = skill_runners.test(ctx, "ask-query", sample=0, mode="replay")
    assert r["mode"] == "replay" and r["run_id"] is None and r["sent"][0]["step"] == "replay"
    assert "Question: 哪些接口的 MTU 是 9216？" in r["sent"][0]["prompt"]
    with pytest.raises(skills.SkillError) as e:
        skill_runners.test(ctx, "ask-query", sample=0, mode="ai")
    assert e.value.key == "ai.not_configured"
    with pytest.raises(skills.SkillError):
        skill_runners.test(ctx, "ask-query", sample=9, mode="replay")
    # 草稿定义：未保存的提示词直接试运行
    r = skill_runners.test(ctx, "card-extract", sample=0, mode="replay", definition={"system": "DRAFT"})
    assert r["version"] == "draft" and r["sent"][0]["system"] == "DRAFT"


class FakeAI:
    def __init__(self, replies: list[str] | None = None, fn: Any = None):
        self.replies = list(replies or [])
        self.fn = fn
        self.calls: list[tuple[str, str]] = []

    def __call__(self, settings, model, system, prompt):  # type: ignore[no-untyped-def]
        self.calls.append((system, prompt))
        text = self.fn(system, prompt) if self.fn else self.replies.pop(0)
        return ai.Reply(text, model, 10, 5)


@pytest.fixture
def ai_on(configured_root: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LMESH_AI__PROVIDER", "openai")
    monkeypatch.setenv("LMESH_AI__BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("LMESH_AI__MODEL", "fake-model")
    s = config.load()
    store.upgrade(s.database_url)

    def install(replies: list[str] | None = None, fn: Any = None) -> FakeAI:
        fake = FakeAI(replies, fn)
        monkeypatch.setattr(ai, "provider_hook", fake)
        return fake

    return s, install


def test_live_ask_logs_runs_and_disable(ai_on, kb, devices) -> None:  # type: ignore[no-untyped-def]
    s, install = ai_on
    answer = {"statements": [{"text": "MTU 9000", "cites": [1], "facts": [{"row": 1, "field": "mtu", "value": "1"}]}]}
    install(
        [
            '{"query": "FIND interface WHERE nope = 1"}',
            '{"query": "FIND interface WHERE mtu = 9000 RETURN name, mtu"}',
            json.dumps(answer),
        ]
    )
    r = ask.ask("MTU 9000?", devices, kb, s, "en", actor=skills.Actor(None, "tester"))
    assert [(x["skill"], x["status"]) for x in r["skill_runs"]] == [
        ("ask-query", "rejected"),
        ("ask-query", "passed"),
        ("ask-answer", "corrected"),
    ]
    reg = skills.cases(s.database_url, "ask-query")["regression"]
    assert len(reg) == 1 and reg[0]["input"]["question"] == "MTU 9000?"
    assert len(skills.cases(s.database_url, "ask-answer")["regression"]) == 1
    run = skills.get_run(s.database_url, r["skill_runs"][2]["run_id"])
    assert run["actor"] == "tester" and run["input"]["result"]["rows"][0]["n"] == 1
    # 管理员保存的版本立即生效：提示词带上示例
    skills.save("ask-answer", {"examples": [{"input": "EX-IN", "output": "EX-OUT"}]}, "admin")
    fake = install(['{"query": "FIND interface RETURN name"}', '{"statements": []}'])
    r = ask.ask("names?", devices, kb, s, "en")
    assert "EX-OUT" in fake.calls[1][0] and r["skill_runs"][1]["version"] == "1"
    # 停用：返回 skill_disabled 状态
    skills.set_enabled("ask-query", False)
    with pytest.raises(ask.AskError) as e:
        ask.ask("x?", devices, kb, s, "en")
    assert e.value.kind == "state" and e.value.data == {"status": "skill_disabled", "skill": "ask-query"}
    skills.set_enabled("ask-query", True)


def test_live_generate_logs_runs(ai_on, kb) -> None:  # type: ignore[no-untyped-def]
    s, install = ai_on
    bad = "```\ninterface GigabitEthernet0/2/2.105\n vlan-type dot1q 105\n ip binding vpn-instance NOPE\n#\n```"
    good = "```\ninterface GigabitEthernet0/2/2.105\n vlan-type dot1q 105\n ip binding vpn-instance RAN\n ip address 10.3.5.1 255.255.255.252\n#\n```"
    install([bad, good])
    r = ask.generate("新增 105", kb, s, BASE, "ATN-CHANGE-01", None)
    assert [x["status"] for x in r["skill_runs"]] == ["rejected", "passed"] and r["rounds"][1]["skill_run"]
    reg = skills.cases(s.database_url, "config-generate")["regression"]
    assert reg[0]["detail"]["verdict"] == "blocked" and reg[0]["input"]["device"] == "ATN-CHANGE-01"


def test_evolve_scores_and_approval(ai_on, kb) -> None:  # type: ignore[no-untyped-def]
    s, install = ai_on
    ctx = _ctx(kb)
    sid = "card-extract"
    with pytest.raises(skills.SkillError) as e:
        skill_runners.evolve(ctx, sid)
    assert e.value.key == "skills.evolve_no_cases"
    sk = skills.current(sid)
    for i, fmt in enumerate(("**a** *x*", "**b** *y*")):
        skills.log_run(s, sk, "ingest", "rejected", {"title": f"t{i}", "format": fmt}, "a { x", {"error": "syntax"})
    proposal = {
        "system": sk.system + " Never leave a brace unclosed.",
        "prompt": sk.prompt,
        "examples": [{"input": "**c** *z*", "output": "c <z>"}],
        "rationale": "close braces",
    }

    def reply(system: str, prompt: str) -> str:
        if "You improve the prompts" in system:
            return json.dumps(proposal)
        return "a <x>" if "Never leave a brace unclosed." in system else "a { x"

    fake = install(fn=reply)
    ev = skill_runners.evolve(ctx, sid, skills.Actor(None, "admin"))
    assert ev["status"] == "pending" and ev["rationale"] == "close braces"
    assert ev["scores"]["summary"] == {"old": 0.0, "new": 1.0, "cases": 2, "better": 2, "worse": 0, "same": 0}
    assert len(fake.calls) == 1 + 2 * 2
    assert "Failed cases (sanitised):" in fake.calls[0][1] and '"reason": "rejected"' in fake.calls[0][1]
    assert skills.current(sid).active == "builtin"  # 不自动上线
    d = skills.get_evolution(s.database_url, sid, ev["id"])
    assert any(f["field"] == "system" and f["changed"] for f in d["diff"])
    assert skills.stats(s.database_url, 30)[sid]["pending_evolutions"] == 1
    done = skills.decide(s.database_url, sid, ev["id"], True, "admin")
    assert done["status"] == "approved" and done["published_version"] == "1"
    cur = skills.current(sid)
    assert cur.active == "1" and cur.examples == [{"input": "**c** *z*", "output": "c <z>"}]
    assert skills.versions(sid)[1]["source"] == "evolution" and skills.versions(sid)[1]["evolution"] == ev["id"]
    with pytest.raises(skills.SkillError) as e:
        skills.decide(s.database_url, sid, ev["id"], False)
    assert e.value.kind == "state"
    # 候选去掉了变量 → 失败，不进入待批准
    install(fn=lambda sy, p: json.dumps({"system": "x", "prompt": "Command only", "rationale": "r"}))
    ev2 = skill_runners.evolve(ctx, sid)
    assert ev2["status"] == "failed" and {i["params"]["name"] for i in ev2["error"]["issues"]} == {"title", "format"}
    # 回归运行与进化调用不计入统计
    assert skills.stats(s.database_url, 30)[sid]["calls"] == 2


def test_case_to_example(ai_on, kb) -> None:  # type: ignore[no-untyped-def]
    s, _ = ai_on
    ctx = _ctx(kb)
    sk = skills.current("card-extract")
    rid = skills.log_run(s, sk, "ingest", "passed", {"title": "t", "format": "**t** *v*"}, "t <v>", {})
    assert rid
    fb = skills.feedback(s.database_url, rid, "up")
    r = skills.case_to_example(
        s.database_url,
        "card-extract",
        fb["case"]["id"],
        "admin",
        lambda sk_, inp: skill_runners.prompt_for(sk_, inp, ctx),
    )
    ex = skills.current("card-extract").examples
    assert r["version"] == "1" and ex[0]["output"] == "t <v>" and ex[0]["input"].startswith("Command: t")
    assert skills.versions("card-extract")[1]["source"] == "example"
