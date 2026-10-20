"""规范与合规、知识库构建、报告三组 AI skill（M8-5）：每个 skill 的正常建议、代码校验拒绝（编造对象 / 校验失败）、
未配置 AI 时降级；审核队列的新动作（rule、unknown_card、card_maps）；脱敏复核只允许本地模型；报告摘要进入导出的报告。
AI 一律用假的客户端（替换 ai.provider_hook），不调用外部服务。"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from lmesh.core import (
    ai,
    ai_report_summary,
    ai_suggest,
    ai_suggest_kb,
    analysis,
    ask,
    config,
    kbservice,
    projects,
    report,
    review,
    skill_runners,
    skills,
    store,
)
from lmesh.core.store.models import Project

pytestmark = pytest.mark.unit
KB_SKILLS = (
    "rule-draft",
    "baseline-waiver",
    "sanitize-review",
    "unknown-triage",
    "card-review",
    "mapping-suggest",
    "report-summary",
)


@pytest.fixture
def lab(full_kb_root: Path, projects_root: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """alice 的项目 lab（ATN-CHANGE-01），AI 配置为假的接口（provider openai，不是本地模型）。"""
    monkeypatch.setenv("LMESH_AI__PROVIDER", "openai")
    monkeypatch.setenv("LMESH_AI__BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("LMESH_AI__MODEL", "fake-model")
    s = config.load()
    url = s.database_url
    alice = projects.cli_identity(url, "alice")
    scope = projects.resolve(url, alice, "lab")
    with projects.use(scope, alice):
        yield s, scope, alice


def _env(s: config.Settings, scope: projects.Scope, who: projects.Identity, kb_editor: bool = True) -> ai_suggest.Env:
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


def _reply(*items: dict[str, Any]) -> str:
    return json.dumps({"suggestions": list(items)})


def _device_id(url: str, name: str = "ATN-CHANGE-01") -> int:
    from lmesh.core import importer

    return int(next(d["id"] for d in importer.list_devices(url) if d["name"] == name))


def _items(env: ai_suggest.Env, batch_id: int) -> list[dict[str, Any]]:
    return sorted(ai_suggest.list_suggestions(env, batch_id=batch_id)["items"], key=lambda x: x["id"])


def _codes(item: dict[str, Any]) -> set[str]:
    return {r["code"] for r in item["check"].get("reasons", [])}


RULE_YAML = """id: std.interface_l3_description
target: interface
when: {exists: ipv4}
assert: {exists: description}
severity: warning
title: {zh-CN: 三层接口没有描述, en: Layer 3 interface without description, pt-BR: Interface L3 sem descrição}
message: {zh-CN: "接口 {key} 没有描述", en: "Interface {key} has no description", pt-BR: "A interface {key} não tem descrição"}
suggestion: {zh-CN: 写明对端, en: Name the peer, pt-BR: Cite o par}
"""


def _rule(yaml_text: str, rid: str, title: str = "4.2.1 → Layer 3 interfaces need a description") -> dict[str, Any]:
    return {
        "category": "kb_review",
        "kind": "rule",
        "title": title,
        "content": {"review_kind": "rule", "target": rid, "payload": {"yaml": yaml_text, "clause": "s1"}},
        "refs": [{"id": "s1"}],
    }


# ---------------------------------------------------------------- REQ-033 的样例回放、未配置 AI 降级


def test_replay_samples_pass_and_reject(full_kb_root: Path, configured_root: Path) -> None:
    """skill 管理页的试运行（回放）：每个新 skill 一条通过、一条被拦截；内置定义本身通过定义校验。"""
    s = config.load()
    store.upgrade(s.database_url)
    ctx = skill_runners.Ctx(s, lambda: analysis.load_kb(kbservice.runtime_root(s)))
    groups = {"rule-draft": "compliance", "baseline-waiver": "compliance", "sanitize-review": "compliance"}
    groups |= {"unknown-triage": "kb", "card-review": "kb", "mapping-suggest": "kb", "report-summary": "report"}
    for sid in KB_SKILLS:
        got = [skill_runners.test(ctx, sid, sample=i, mode="replay")["check"]["status"] for i in range(2)]
        assert got == ["passed", "rejected"], sid
        b = skills.builtin(sid)
        assert b.group == groups[sid] and "retry" in b.templates
        skills.validate(b, b.definition())
        assert sid in skills.ORDER


def test_not_configured_degrades(full_kb_root: Path, projects_root: Path) -> None:
    s = config.load()
    url = s.database_url
    alice = projects.cli_identity(url, "alice")
    scope = projects.resolve(url, alice, "lab")
    did = _device_id(url)
    params = {
        "rule-draft": {"sentence": "Every BGP peer needs a description"},
        "baseline-waiver": {"device_id": did, "rule": "x"},
        "sanitize-review": {"device_id": did},
        "unknown-triage": {},
        "card-review": {"card_id": "huawei-vrp8.carrier"},
        "mapping-suggest": {"family": "nokia-sros-md"},
        "report-summary": {"kind": "check", "device_id": did},
    }
    with projects.use(scope, alice):
        env = _env(s, scope, alice)
        for sid in KB_SKILLS:
            with pytest.raises(ai_suggest.SuggestError) as e:
                ai_suggest.run(env, sid, params[sid])
            assert e.value.key == "ai.not_configured", sid
        info = ai_suggest.skill_list(env.settings)
        assert not info["ai"]["configured"] and set(KB_SKILLS) <= {x["id"] for x in info["skills"]}
        # 脱敏复核的门槛：没有配置 AI 时不按“非本地”拦（由未配置的提示处理）
        assert ai_suggest_kb.local_gate(env, "sanitize-review")["allowed"]


# ---------------------------------------------------------------- 规范转规则


def test_extract_text_txt_md_docx() -> None:
    assert ai_suggest_kb.extract_text("a.txt", "4.1 规则一\n".encode())["text"] == "4.1 规则一"
    assert ai_suggest_kb.extract_text("a.md", b"\xef\xbb\xbf# Title\n\n1. x")["text"].startswith("# Title")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        z.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{ns}"><w:body><w:p><w:r><w:t>4.2.1 上联接口</w:t></w:r><w:r><w:t>必须有描述</w:t></w:r></w:p>'
            f"<w:p><w:r><w:t>4.3 BGP 认证</w:t></w:r></w:p></w:body></w:document>",
        )
    got = ai_suggest_kb.extract_text("std.docx", buf.getvalue())
    assert got["text"] == "4.2.1 上联接口必须有描述\n4.3 BGP 认证" and not got["truncated"]
    for name, data in (("x.pdf", b"%PDF"), ("x.docx", b"not a zip"), ("x.txt", b"   ")):
        with pytest.raises(ai_suggest.SuggestError):
            ai_suggest_kb.extract_text(name, data)
    clauses = ai_suggest_kb.split_clauses("4.2.1 上联接口必须有描述\n续行\n\n§4.3 BGP 必须认证\n第五条 SNMP")
    assert [c[0] for c in clauses] == ["4.2.1", "4.3", "第五条"] and clauses[0][1] == "4.2.1 上联接口必须有描述 续行"


def test_rule_draft_trial_review_and_approve(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    bad_yaml = RULE_YAML.replace("std.interface_l3_description", "std.storm").replace("description}", "storm_control}")
    zero = RULE_YAML.replace("std.interface_l3_description", "std.never").replace(
        "assert: {exists: description}", "assert: {any: [{exists: description}, {not: {exists: description}}]}"
    )
    calls = _fake(
        monkeypatch,
        lambda sy, p: _reply(
            _rule(RULE_YAML, "std.interface_l3_description"),
            _rule(bad_yaml, "std.storm", "4.4 → Storm control"),
            _rule("id: [broken", "std.x", "4.5 → Broken"),
            _rule(
                RULE_YAML.replace("std.interface_l3_description", "interface.vrf_without_ip"),
                "interface.vrf_without_ip",
            ),
        ),
    )
    text = "4.2.1 Every layer 3 interface must have a description.\n4.4 Customer ports need storm control."
    b = ai_suggest.run(env, "rule-draft", {"text": text, "doc_name": "std.md"})
    assert b["status"] == "done" and b["scope_key"] == "rules:standard"
    system, prompt = calls[0]
    assert "s1 | 4.2.1 |" in prompt and "s2 | 4.4 |" in prompt and "interface |" in prompt and "{key}" in system
    ok, storm, broken, dup = _items(env, b["id"])
    assert ok["check_status"] == "pass", ok["check"]
    trial = ok["check"]["result"]["trial"]
    assert trial["hits"] > 0 and trial["samples"] > 0 and trial["items"][0]["sample"]
    assert storm["check_status"] == "reject" and "rule_invalid" in _codes(storm)
    assert broken["check_status"] == "reject" and "rule_yaml" in _codes(broken)
    assert dup["check_status"] == "reject" and "rule_invalid" in _codes(dup)  # 与知识库已有规则编号重复
    # 零命中给提醒
    _fake(monkeypatch, lambda sy, p: _reply(_rule(zero, "std.never")))
    b2 = ai_suggest.run(env, "rule-draft", {"sentence": "Interfaces may have a description"})
    (z,) = _items(env, b2["id"])
    assert z["check_status"] == "warn" and "rule_no_hits" in _codes(z)
    # 采纳 = 进审核队列（只有维护员与管理员）
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.adopt(_env(s, scope, alice, kb_editor=False), ok["id"])
    assert e.value.kind == "forbidden"
    done = ai_suggest.adopt(env, ok["id"])
    rid = done["adopt_info"]["review_item_id"]
    item = review.get(s.database_url, rid)
    assert item is not None and item["kind"] == "rule" and item["target"] == "std.interface_l3_description"
    assert item["payload"]["yaml"] == RULE_YAML and item["source"]["method"] == "ai"
    # 审核通过：写进 rules/standards.yaml，检查规则能加载
    root = kbservice.runtime_root(s)
    review.decide(s.database_url, root, rid, True)
    from lmesh.core import checks
    from lmesh.core import rules as rulesmod

    path = root / "rules" / ai_suggest_kb.RULES_FILE
    assert path.is_file() and "std.interface_l3_description" in path.read_text(encoding="utf-8")
    loaded = rulesmod.load_dir(analysis.load_kb(root), checks.rules_dir(root))
    assert "std.interface_l3_description" in {r.id for r in loaded}
    with pytest.raises(ai_suggest.SuggestError) as e:  # 审核项已处理，不能撤销
        ai_suggest.revert(env, ok["id"])
    assert e.value.key == "ai_suggest.review_decided"


def test_rule_review_action_restores_on_error(lab) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    root = kbservice.runtime_root(s)
    bad = RULE_YAML.replace("description}", "storm_control}")
    rid = review.add(s.database_url, "rule", "x", "std.interface_l3_description", {"yaml": bad})
    with pytest.raises(review.ReviewError):
        review.decide(s.database_url, root, rid, True)
    assert not (root / "rules" / ai_suggest_kb.RULES_FILE).exists()  # 出错时恢复原状（文件本来没有）


# ---------------------------------------------------------------- 基线例外说明


def _failed_rule(s: config.Settings, did: int) -> str:
    from lmesh.core import baseline as blmod
    from lmesh.core import graphstore

    root = kbservice.runtime_root(s)
    kb = analysis.load_kb(root)
    bl = blmod.load(kb, blmod.baseline_dir(root))
    rules, over = blmod.select(bl, "basic")
    g = graphstore.build_for_version(s.database_url, graphstore.latest_version(s.database_url, did).id, kb)[0]
    res = blmod.audit_device(g, rules, over)
    return next(rid for rid, v in res["results"].items() if v == "fail")


def test_baseline_waiver_text(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)
    rid = _failed_rule(s, did)
    good = {
        "category": "text_only",
        "kind": "reason",
        "title": "Legacy NMS",
        "content": {"text": "[[d1]] fails [[r1]] because the legacy NMS still needs it; [[n1]] is the object."},
        "refs": [{"id": "r1"}, {"id": "n1"}],
    }
    comp = {
        "category": "text_only",
        "kind": "compensating",
        "title": "ACL",
        "content": {"text": "Limit access to [[d1]] from GigabitEthernet0/9/9 and 10.250.0.9 only."},
        "refs": [{"id": "r1"}],
    }
    calls = _fake(monkeypatch, lambda sy, p: _reply(good, comp))
    b = ai_suggest.run(env, "baseline-waiver", {"device_id": did, "rule": rid})
    assert b["status"] == "done" and b["scope_key"] == f"waiver:{did}:basic:{rid}"
    assert f"r1 | {rid}" in calls[0][1]
    g, c = _items(env, b["id"])
    assert g["check_status"] == "pass" and "ATN-CHANGE-01" in g["check"]["display"]
    assert c["check_status"] == "reject" and "unknown_object" in _codes(c)  # 编造的接口与地址
    assert ai_suggest.adopt(env, g["id"])["adopt_info"] == {"action": "record"}
    # 满足的规则不能起草例外；不存在的规则 404
    from lmesh.core import baseline as blmod

    root = kbservice.runtime_root(s)
    bl = blmod.load(analysis.load_kb(root), blmod.baseline_dir(root))
    rules, _ = blmod.select(bl, "basic")
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.run(env, "baseline-waiver", {"device_id": did, "rule": "no.such.rule"})
    assert e.value.key == "ai_kb.rule_not_found"
    passing = [r.id for r in rules if r.id != rid]
    hit = None
    for r in passing:
        try:
            ai_suggest.run(env, "baseline-waiver", {"device_id": did, "rule": r})
        except ai_suggest.SuggestError as err:
            if err.key == "ai_kb.rule_not_failed":
                hit = err
                break
    assert hit is not None


# ---------------------------------------------------------------- 脱敏复核（只允许本地模型）


def _san(line: int, text: str, kind: str = "person", pattern: str | None = None) -> dict[str, Any]:
    c: dict[str, Any] = {"line": line, "text": text, "kind": kind, "explain": "Customer site name."}
    if pattern:
        c["pattern"] = pattern
    return {
        "category": "sanitize_rule",
        "kind": kind,
        "title": f"L{line}: customer site",
        "content": c,
        "refs": [{"line": line, "of": "d1"}],
    }


def test_sanitize_review_local_only(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)
    gate = ai_suggest_kb.local_gate(env, "sanitize-review")
    assert not gate["allowed"] and gate["reason"] == "local_only" and gate["provider"] == "openai"
    assert ai_suggest_kb.local_gate(env, "rule-draft")["allowed"]
    calls = _fake(monkeypatch, lambda sy, p: _reply())
    for fn in (
        lambda: ai_suggest.run(env, "sanitize-review", {"device_id": did}),
        lambda: ai_suggest.estimate(env, "sanitize-review", {"device_id": did}),
    ):
        with pytest.raises(ai_suggest.SuggestError) as e:
            fn()
        assert e.value.key == "ai_kb.local_only" and e.value.kind == "state" and e.value.data["provider"] == "openai"
    assert calls == []  # 一个字也没有发出去


def test_sanitize_review_resanitize_adopt_revert(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    monkeypatch.setenv("LMESH_AI__PROVIDER", "local")
    s = config.load()
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)
    assert ai_suggest_kb.local_gate(env, "sanitize-review")["allowed"]
    calls = _fake(
        monkeypatch,
        lambda sy, p: _reply(
            _san(32, "RAN-SITE", "site"),
            _san(32, "ACME-Bank", "customer"),  # 这一行没有
            _san(24, "LMESH-SECRET-ABCDEF", "other"),  # 不是发给 AI 的行或已是占位符
            _san(40, "OAM-LINK", "site", pattern="O.*"),  # 规则太宽 / 匹配不到也拒绝
        ),
    )
    b = ai_suggest.run(env, "sanitize-review", {"device_id": did})
    assert b["status"] == "done"
    sent = calls[0][1]
    assert "   32   description RAN-SITE" in sent and "interface GigabitEthernet0/2/0" not in sent  # 只发含自由文本的行
    ok, invented, ph, broad = _items(env, b["id"])
    assert ok["check_status"] == "pass" and ok["check"]["result"]["pattern"] == "RAN\\-SITE"
    assert invented["check_status"] == "reject" and "san_not_in_line" in _codes(invented)
    assert ph["check_status"] == "reject"
    assert broad["check_status"] in ("warn", "reject")
    # 采纳：写进项目的脱敏补充；之后发给 AI 的文字按它替换
    done = ai_suggest.adopt(env, ok["id"])
    assert done["adopt_info"]["action"] == "redact" and not done["adopt_info"]["existed"]
    assert ai_suggest_kb.project_redact(s.database_url, scope.project_id) == ["RAN\\-SITE"]
    with projects.use(projects.resolve(s.database_url, alice, "lab"), alice):
        out = ask.sanitize_text("interface X\n description RAN-SITE\n")
        assert "RAN-SITE" not in out and "ORG-" in out
    back = ai_suggest.revert(env, ok["id"])
    assert back["revert_info"]["action"] == "redact_removed"
    with store.session(s.database_url) as ss:
        p = ss.get(Project, scope.project_id)
        assert p is not None and p.settings.get("sanitize_redact") == []


# ---------------------------------------------------------------- 未识别行归因


UNKNOWN_CFG = """sysname ATN-UNK-01
#
interface GigabitEthernet0/2/1
 mtu jumbo
#
ptp clock-source local priority 1
#
return
"""


def _import_unknown(s: config.Settings, alice: projects.Identity) -> None:
    from lmesh.core import importer

    scope = projects.resolve(s.database_url, alice, "lab")
    with projects.use(scope, alice):
        importer.import_sources(
            [("unk.cfg", UNKNOWN_CFG.encode())], s.database_url, "basic", kbservice.runtime_root(s), actor="alice"
        )


def _card_sug(group: str, cid: str, syntax: str, view: str, domain: str = "clock") -> dict[str, Any]:
    return {
        "category": "kb_review",
        "kind": "missing",
        "title": f"{syntax}: missing card",
        "content": {
            "review_kind": "unknown_card",
            "target": cid,
            "payload": {
                "group": group,
                "cause": "missing",
                "domain": domain,
                "card": {"id": cid, "syntax": syntax, "view": view},
            },
        },
        "refs": [{"id": group}],
    }


def test_unknown_triage_reparse_and_approve(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    _import_unknown(s, alice)
    env = _env(s, scope, alice)

    def reply(sy: str, p: str) -> str:
        gid = next(ln.split(" | ")[0] for ln in p.splitlines() if "ptp clock-source local priority" in ln)
        return _reply(
            _card_sug(
                gid, "huawei-vrp8.ptp-clock-source-local-ai", "ptp clock-source local priority <priority>", "system"
            ),
            _card_sug(gid, "huawei-vrp8.ptp-clock-source-local-ai2", "ptp clock-source local", "system"),
            _card_sug("u99", "huawei-vrp8.x-ai", "x", "system"),
            _card_sug(gid, "huawei-vrp8.carrier", "carrier", "system"),
        )

    calls = _fake(monkeypatch, reply)
    b = ai_suggest.run(env, "unknown-triage", {})
    assert b["status"] == "done" and "ptp clock-source local priority" in calls[0][1]
    ok, short, invented, exists = _items(env, b["id"])
    assert ok["check_status"] == "pass", ok["check"]
    assert ok["check"]["result"]["reparse"]["recognized"] == ok["check"]["result"]["reparse"]["lines"] >= 1
    assert short["check_status"] == "reject" and "still_unknown" in _codes(short)  # 草稿少了参数
    assert invented["check_status"] == "reject" and "ref_not_found" in _codes(invented)
    assert exists["check_status"] == "reject" and "card_exists" in _codes(exists)
    done = ai_suggest.adopt(env, ok["id"])
    rid = done["adopt_info"]["review_item_id"]
    assert review.get(s.database_url, rid)["kind"] == "unknown_card"
    root = kbservice.runtime_root(s)
    review.decide(s.database_url, root, rid, True)
    kb = analysis.load_kb(root)
    card = kb.cards["huawei-vrp8.ptp-clock-source-local-ai"]
    assert card.status == "reviewed" and card.domain == "clock"


# ---------------------------------------------------------------- 命令卡审核助手


def test_card_review_flags_only(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    doc = "carrier down-hold-time\nThe value is an integer ranging from 0 to 86400000, in milliseconds.\nDefault: 0"

    def sug(text_: str, refs: list[dict[str, Any]], quote: str = "", kind: str = "default") -> dict[str, Any]:
        c: dict[str, Any] = {"text": text_}
        if quote:
            c["quote"] = quote
        return {"category": "text_only", "kind": kind, "title": "Default", "content": c, "refs": refs}

    def reply(sy: str, p: str) -> str:
        fid = next(ln.split(" | ")[0] for ln in p.splitlines() if " | default:" in ln)
        return _reply(
            sug(f"[[{fid}]] should say 0 ms.", [{"id": fid}, {"line": 3, "of": "doc"}], "Default: 0"),
            sug(f"[[{fid}]] is wrong.", [{"id": fid}, {"line": 2, "of": "doc"}], "priority 7 is the default"),
            sug("The card is odd.", [{"line": 2, "of": "doc"}]),
            sug(f"[[{fid}]] is wrong.", [{"id": fid}, {"line": 99, "of": "doc"}]),
        )

    calls = _fake(monkeypatch, reply)
    b = ai_suggest.run(env, "card-review", {"card_id": "huawei-vrp8.carrier", "doc_text": doc})
    assert (
        b["status"] == "done" and b["scope_key"] == "card:huawei-vrp8.carrier" and "   2  The value is" in calls[0][1]
    )
    ok, quote, nofield, badline = _items(env, b["id"])
    assert ok["check_status"] == "pass", ok["check"]
    assert quote["check_status"] == "reject" and "quote_not_in_doc" in _codes(quote)
    assert nofield["check_status"] == "reject" and "no_field_ref" in _codes(nofield)
    assert badline["check_status"] == "reject" and "line_not_found" in _codes(badline)
    assert ai_suggest.adopt(env, ok["id"])["adopt_info"] == {"action": "record"}  # 只标注，不改卡
    with pytest.raises(ai_suggest.SuggestError):
        ai_suggest.run(env, "card-review", {"card_id": "no.such.card"})


# ---------------------------------------------------------------- 映射建议


def _maps(card: str, cid: str, maps: dict[str, str]) -> dict[str, Any]:
    return {
        "category": "kb_review",
        "kind": "interface",
        "title": f"{cid} mapping",
        "content": {"review_kind": "card_maps", "target": cid, "payload": {"card": card, "maps": maps}},
        "refs": [{"id": card}],
    }


def test_mapping_suggest_checks_and_approve(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    egress, etype = "nokia-sros-md.port-ethernet-egress", "nokia-sros-md.port-ethernet-dot1q-etype"
    _fake(
        monkeypatch,
        lambda sy, p: _reply(
            _maps("c1", egress, {"@container": ""}),
            _maps("c2", etype, {"interface.storm_control": "$dot1q-etype"}),
            _maps("c2", etype, {"interface.mtu": "$no-such-param"}),
            _maps("c9", "nokia-sros-md.nope", {"@container": ""}),
        ),
    )
    b = ai_suggest.run(env, "mapping-suggest", {"family": "nokia-sros-md", "card_ids": [egress, etype]})
    assert b["status"] == "done" and b["scope_key"] == "mapping:nokia-sros-md"
    ok, node, param, invented = _items(env, b["id"])
    assert ok["check_status"] == "pass", ok["check"]
    assert ok["check"]["result"]["checks"] == {"kb": "pass", "roundtrip": "pass", "translate": "pass"}
    assert node["check_status"] == "reject" and "maps_unknown_node" in _codes(node)
    assert param["check_status"] == "reject" and "maps_bad_param" in _codes(param)
    assert invented["check_status"] == "reject" and "ref_not_found" in _codes(invented)
    done = ai_suggest.adopt(env, ok["id"])
    rid = done["adopt_info"]["review_item_id"]
    root = kbservice.runtime_root(s)
    review.decide(s.database_url, root, rid, True)
    card = analysis.load_kb(root).cards[egress]
    assert card.maps == {"@container": ""}
    from lmesh.core.kb import files as kbfiles

    found = kbfiles.find_card(root, egress)
    assert found is not None and found[1]["cards"][found[2]]["maps_manual"] is True
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.run(env, "mapping-suggest", {"family": "no-such-family"})
    assert e.value.key == "ai_kb.bad_family"


# ---------------------------------------------------------------- 报告摘要


def _summary(kind: str, text_: str) -> dict[str, Any]:
    return {"category": "text_only", "kind": kind, "title": f"Summary {kind}", "content": {"text": text_}, "refs": []}


def test_report_summary_numbers_and_export(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)
    calls = _fake(
        monkeypatch,
        lambda sy, p: _reply(
            _summary("zh-CN", "本次检查 [[d1]] 共 <<findings.total>> 个问题，严重 <<findings.error>> 个。"),
            _summary("en", "The check of [[d1]] found <<findings.total>> issues."),
            _summary("en", "[[d1]] is 96% compliant."),
            _summary("fr", "[[d1]] ok."),
        ),
    )
    params = {"kind": "check", "device_id": did}
    b = ai_suggest.run(env, "report-summary", params)
    assert b["status"] == "done" and b["scope_key"] == f"report:check:{did}"
    assert "findings.total = " in calls[0][1] and "d1 | device | ATN-CHANGE-01" in calls[0][1]
    zh, en, typed, lang = _items(env, b["id"])
    assert zh["check_status"] == "pass" and en["check_status"] == "pass"
    assert typed["check_status"] == "reject" and "number_not_from_code" in _codes(typed)
    assert lang["check_status"] == "reject" and "bad_report_lang" in _codes(lang)
    # 还没采纳时导出不含摘要
    res = ai_report_summary.compute_result(env, "check", params)
    assert ai_report_summary.for_export(s.database_url, scope.project_id, "check", params, "en", res) is None
    ai_suggest.adopt(env, zh["id"])
    ai_suggest.adopt(env, en["id"])
    got = ai_report_summary.for_export(s.database_url, scope.project_id, "check", params, "en", res)
    assert got is not None and not got["stale"] and got["skill"] == "report-summary" and got["connection"]
    total = str(res["summary"]["total"])
    assert f'<b class="cv">{total}</b>' in got["html"] and "ATN-CHANGE-01" in got["html"]
    rep = report.check_report(res, "en", "html", ai=got)
    assert 'class="ai-summary"' in rep.content and "Summary (written by AI)" in rep.content
    assert "skill report-summary" in rep.content and "fake-model" in rep.content
    md = report.check_report(
        res,
        "zh-CN",
        "md",
        ai=ai_report_summary.for_export(s.database_url, scope.project_id, "check", params, "zh-CN", res),
    )
    assert "> [AI]" in md.content and "摘要（AI 撰写）" in md.content and "由 AI 撰写" in md.content
    plain = report.check_report(res, "en", "html")
    assert 'class="ai-summary"' not in plain.content
    # 数据变了（数字与采纳时不一致）：不放正文，只给说明
    changed = json.loads(json.dumps(res))
    changed["summary"]["total"] += 1
    stale = ai_report_summary.for_export(s.database_url, scope.project_id, "check", params, "en", changed)
    assert stale is not None and stale["stale"]
    assert "no longer matches" in report.check_report(changed, "en", "html", ai=stale).content
    # 没有导入的设备（配置文本）不支持摘要
    with pytest.raises(ai_suggest.SuggestError) as e:
        ai_suggest.run(env, "report-summary", {"kind": "baseline", "configs": [{"text": "x"}]})
    assert e.value.key == "ai_kb.report_needs_devices"


def test_report_summary_other_kinds(lab, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, scope, alice = lab
    env = _env(s, scope, alice)
    did = _device_id(s.database_url)
    _fake(monkeypatch, lambda sy, p: _reply(_summary("en", "[[d1]] summary.")))
    for params, key in (
        ({"kind": "baseline", "device_ids": [did], "baseline": "basic"}, f"report:baseline:basic:{did}"),
        ({"kind": "compare", "a": {"device_id": did}, "b": {"device_id": did}}, f"report:compare:d{did}:d{did}"),
        (
            {"kind": "change", "current": {"device_id": did}, "target": {"device_id": did}},
            f"report:change:d{did}:d{did}",
        ),
    ):
        b = ai_suggest.run(env, "report-summary", params)
        assert b["status"] == "done" and b["scope_key"] == key and b["counts"]["pass"] == 1, (params, b)
