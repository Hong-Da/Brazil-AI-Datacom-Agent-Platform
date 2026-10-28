"""配置检查项目（REQ-031）：变更脚本 / 完整配置的检查、顺序核查开关、按依赖重排、AI 结果的代码校验、文本差异、项目与修订存储。
AI 一律用假的客户端（替换 ai.provider_hook），不调用外部服务。"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

import pytest

from lmesh.core import ai, analysis, checkproj, config, script_check, store, textdiff
from lmesh.core import rules as rulesmod

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parent.parent.parent
KB_ROOT = ROOT / "knowledge"
SCRIPTS = ROOT / "tests" / "inputs" / "scripts"
CHANGE = KB_ROOT / "samples" / "change"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


@pytest.fixture(scope="module")
def atn(kb):  # type: ignore[no-untyped-def]
    return script_check.baseline_from_text(_read(CHANGE / "atn-base.cfg"), kb, device="ATN-CHANGE-01")


@pytest.fixture(scope="module")
def asr(kb):  # type: ignore[no-untyped-def]
    return script_check.baseline_from_text(_read(CHANGE / "asr920-base.cfg"), kb, device="PE-CHANGE-01")


def _codes(r: dict) -> list[tuple[int | None, str]]:  # type: ignore[type-arg]
    return [(i["line"], i["code"]) for i in r["issues"]]


# ---------------------------------------------------------------- 逐行视图跟踪


def test_track_views_and_kinds(kb) -> None:  # type: ignore[no-untyped-def]
    lines = script_check.track(_read(SCRIPTS / "atn-change-order.txt"), kb, "huawei-vrp8")
    kinds = [sl.kind for sl in lines]
    assert kinds[0] == "session" and kinds[5] == "exit" and kinds[-2] == "session" and kinds[-1] == "blank"
    ip = lines[2]
    assert ip.kind == "command" and ip.view == "interface" and ip.ctx == [2]
    rd = lines[8]
    assert rd.view != "system" and rd.ctx == [7, 8]
    peer = lines[13]
    assert peer.kind == "wrong_view" and peer.belongs == "bgp"


def test_track_unindented_script_falls_back_to_outer_view(kb) -> None:  # type: ignore[no-untyped-def]
    text = "interface GigabitEthernet0/2/2\ndescription X\nip vpn-instance A\nipv4-family\nroute-distinguisher 1:1\n"
    lines = script_check.track(text, kb, "huawei-vrp8")
    assert [sl.ctx for sl in lines[:5]] == [[], [1], [], [3], [3, 4]]
    assert lines[2].implicit_from == "interface"


# ---------------------------------------------------------------- 变更脚本：顺序核查开 / 关


def test_change_script_order_on(kb, atn) -> None:  # type: ignore[no-untyped-def]
    r = script_check.check_text(_read(SCRIPTS / "atn-change-order.txt"), kb, atn, "change", order=True)
    codes = _codes(r)
    assert (3, "side_effect_lost") in codes  # 先配地址再绑定 VPN：地址被副作用删除
    assert (4, "order_missing_reference") in codes  # 绑定的 VPN 实例在第 7 行才创建
    assert (13, "undo_no_match") in codes
    assert (14, "wrong_view") in codes
    assert r["order"] == {**r["order"], "enabled": True, "violations": 2}
    assert r["summary"]["errors"] == 3 and not r["summary"]["ok"]
    # 顺序错误时附上按依赖重排的建议
    re_ = r["order"]["reorder"]
    assert re_["changed"] and {m["line"] for m in re_["moves"]} == {3, 4}
    lost = next(i for i in r["issues"] if i["code"] == "side_effect_lost")
    assert lost["category"] == "order" and lost["lines"] == [3, 4] and lost["message"]["params"]["by"] == 4


def test_change_script_order_off_checks_content_only(kb, atn) -> None:  # type: ignore[no-untyped-def]
    r = script_check.check_text(_read(SCRIPTS / "atn-change-order.txt"), kb, atn, "change", order=False)
    cats = {i["category"] for i in r["issues"]}
    assert "order" not in cats and r["order"]["violations"] == 0 and "reorder" not in r["order"]
    # 按依赖顺序执行：绑定之后重新配置了地址
    assert (4, "side_effect_ok") in _codes(r)
    assert r["summary"]["errors"] == 1  # 只剩视图错误
    res = r["result"]
    assert res["side_effect_removed"] == 1 and res["removed"][-1]["base_line"] == 41


def test_good_script_has_no_errors_and_records_override(kb, atn) -> None:  # type: ignore[no-untyped-def]
    r = script_check.check_text(_read(SCRIPTS / "atn-change-good.txt"), kb, atn, "change", order=True)
    assert r["summary"]["errors"] == 0 and r["summary"]["warnings"] == 0
    ov = next(i for i in r["issues"] if i["code"] == "override")
    assert ov["line"] == 10 and ov["message"]["params"] == {"base_line": 40, "old": "description OAM-LINK"}
    assert r["result"]["lines_overridden"] == 1 and r["result"]["findings_new"] == []


def test_undo_removes_baseline_line_and_new_dangling_found(kb, atn) -> None:  # type: ignore[no-untyped-def]
    text = "system-view\nundo ip ip-prefix LOOPBACKS index 10\ncommit\n"
    r = script_check.check_text(text, kb, atn, "change")
    assert r["result"]["lines_removed"] == 1 and r["result"]["removed"][0]["how"] == "undo"
    # 路由策略仍引用这个前缀列表：执行后出现悬空引用，标在取消命令上
    rule = [f["rule"] for f in r["result"]["findings_new"]]
    assert any(x.startswith("ref.dangling") for x in rule)


def test_deleting_referenced_policy_counts_as_issue(kb) -> None:  # type: ignore[no-untyped-def]
    """REQ-055-02：删掉仍被引用的 route-policy，悬空引用计入问题和错误数，标在删除命令上。"""
    base = (
        "route-policy RP permit node 10\n#\nbgp 65000\n peer 10.1.1.1 as-number 65001\n #\n"
        " ipv4-family unicast\n  peer 10.1.1.1 enable\n  peer 10.1.1.1 route-policy RP import\n#\n"
    )
    b = script_check.baseline_from_text(base, kb, "huawei-atn-v800r025", device="RP-DEL")
    r = script_check.check_text("undo route-policy RP\n", kb, b)
    assert [f["script_lines"] for f in r["result"]["findings_new"] if f["rule"] == "ref.dangling"] == [[1]]
    assert [(i["line"], i["rule"]) for i in r["issues"] if i["severity"] == "error"] == [(1, "ref.dangling")]
    assert r["summary"]["errors"] >= 1 and not r["summary"]["ok"]


def test_cisco_change_script(kb, asr) -> None:  # type: ignore[no-untyped-def]
    text = _read(SCRIPTS / "asr-change-order.txt")
    on = script_check.check_text(text, kb, asr, "change", order=True)
    assert (3, "order_missing_reference") in _codes(on)
    off = script_check.check_text(text, kb, asr, "change", order=False)
    assert off["summary"]["errors"] == 0 and (3, "side_effect_ok") in _codes(off)


def test_reorder_moves_and_reasons(kb, asr) -> None:  # type: ignore[no-untyped-def]
    r = script_check.reorder_text(_read(SCRIPTS / "asr-change-order.txt"), kb, asr, lang="en")
    assert r["before"]["order_violations"] == 1 and r["after"]["order_violations"] == 0
    lines = r["script"].splitlines()
    assert lines[0] == "configure terminal" and lines[1] == "vrf definition OAM" and lines[-1] == "end"
    assert lines.index(" vrf forwarding OAM") < lines.index(" ip address 10.3.0.2 255.255.255.252")
    # 只进入已有接口视图的行随子命令一起写出，不会留下空的接口块
    assert lines.count("interface GigabitEthernet0/0/2") == 1
    moved = {m["line"]: m for m in r["moves"]}
    why = moved[3]["reasons"][0] if 3 in moved else next(m for m in r["moves"])["reasons"][0]
    assert why["kind"] in ("reference", "side_effect", "contains") and why["text"]
    assert all(m["new_line"] for m in r["moves"])


def test_reorder_keeps_same_target_order(kb, atn) -> None:  # type: ignore[no-untyped-def]
    text = "system-view\ninterface GigabitEthernet0/2/0\n undo description\n description NEW\nquit\ncommit\n"
    r = script_check.reorder_text(text, kb, atn, recheck=False)
    assert not r["changed"]


def test_full_config(kb, atn) -> None:  # type: ignore[no-untyped-def]
    r = script_check.check_text(_read(SCRIPTS / "atn-full.cfg"), kb, atn, "full")
    assert (26, "unknown_command") in _codes(r)
    assert r["order"]["applicable"] is False
    cmp = r["result"]["compare"]
    assert not cmp["equal"] and cmp["summary"]["by_kind"]["changed"] == 1
    assert r["result"]["raw"] >= 1 and not any(i["code"] == "out_of_scope" for i in r["issues"])


def test_errors(kb, atn) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(script_check.ScriptCheckError) as e:
        script_check.check_text("  \n", kb, atn)
    assert e.value.key == "script_check.empty"
    with pytest.raises(script_check.ScriptCheckError) as e:
        script_check.check_text("interface X\n", kb, None, "change")
    assert e.value.key == "script_check.need_baseline"


def test_check_is_fast_enough_for_live_editing(kb) -> None:  # type: ignore[no-untyped-def]
    """几百行脚本、两千多行的现网基线：缓存基线后单次检查在 1 秒内（防抖后的实时调用）。"""
    base = script_check.baseline_from_text(
        _read(KB_ROOT / "samples" / "huawei-atn-v800r023" / "atn-access-01.cfg"), kb, device="ATN-REAL"
    )
    parts = ["system-view"]
    for i in range(1, 41):
        parts += [f"interface LoopBack{100 + i}", f" ip binding vpn-instance V{i}", f" description t{i}"]
        parts += [f" ip address 10.200.{i}.1 255.255.255.255", "quit"]
    for i in range(1, 41):
        parts += [f"ip vpn-instance V{i}", " ipv4-family", f"  route-distinguisher 65000:{1000 + i}", "quit"]
    text = "\n".join(parts) + "\n"
    script_check.check_text(text, kb, base, "change", True)  # 预热：基线检查结果、命令卡索引
    t0 = time.monotonic()
    r = script_check.check_text(text, kb, base, "change", True)
    assert time.monotonic() - t0 < 1.5  # 留出测试机波动的余量（开发机约 0.5 秒）
    assert r["order"]["violations"] == 40


# ---------------------------------------------------------------- 规则文件的 ai 标记


AI_RULES = """
rules:
  - id: style.interface_description
    ai: true
    target: interface
    severity: info
    title: {zh-CN: 接口描述规范, en: Interface description convention, pt-BR: Convenção de descrição}
    message: {zh-CN: 接口描述应写明对端设备与端口, en: Descriptions should name the peer device and port, pt-BR: A descrição deve citar o par}
    suggestion: {zh-CN: 按 TO-<设备>-<端口> 书写, en: Use TO-<device>-<port>, pt-BR: Use TO-<dispositivo>-<porta>}
  - id: style.vrf_ip
    ai: true
    target: interface
    when: {exists: vrf}
    assert: {exists: ipv4}
    severity: warning
    title: {zh-CN: 绑定 VPN 后要有地址, en: Address after VPN binding, pt-BR: Endereço após VPN}
    message: {zh-CN: 绑定 VPN 的接口应有地址, en: Interfaces bound to a VPN need an address, pt-BR: Interfaces em VPN precisam de endereço}
    suggestion: {zh-CN: 补配地址, en: Add the address, pt-BR: Adicione o endereço}
"""


@pytest.fixture
def ai_rules_dir(tmp_path: Path) -> Path:
    d = tmp_path / "rules"
    shutil.copytree(KB_ROOT / "rules", d)
    (d / "style-ai.yaml").write_text(AI_RULES, encoding="utf-8")
    return d


def test_rules_ai_flag(kb, ai_rules_dir: Path) -> None:  # type: ignore[no-untyped-def]
    rules = rulesmod.load_dir(kb, ai_rules_dir)
    by = {r.id: r for r in rules}
    assert by["style.interface_description"].ai and by["style.interface_description"].assert_ is None
    assert by["style.vrf_ip"].ai and by["style.vrf_ip"].as_dict()["ai"] is True
    assert not by["bgp.peer.remote_as_missing"].ai
    listed = script_check.ai_rules(kb, ai_rules_dir)
    assert [r["id"] for r in listed] == ["style.interface_description", "style.vrf_ip"]
    assert listed[0]["code"] is False and listed[1]["code"] is True
    bad = [("x.yaml", {"rules": [{**rulesmod_raw(), "ai": "yes"}]})]
    with pytest.raises(rulesmod.RuleError) as e:
        rulesmod.parse_rules(kb, bad)
    assert any(i["field"] == "ai" for i in e.value.issues)
    # 不是 ai 规则时仍然必须有 assert
    with pytest.raises(rulesmod.RuleError):
        rulesmod.parse_rules(kb, [("y.yaml", {"rules": [{k: v for k, v in rulesmod_raw().items() if k != "assert"}]})])


def rulesmod_raw() -> dict:  # type: ignore[type-arg]
    t = {"zh-CN": "x", "en": "x", "pt-BR": "x"}
    return {
        "id": "t.r",
        "target": "interface",
        "assert": {"exists": "ipv4"},
        "severity": "info",
        "title": t,
        "message": t,
        "suggestion": t,
    }


class _FakeAI:
    """按发给 AI 的脚本（脱敏后、带行号）构造回复：引用第 10 行的原文作为证据。"""

    def __init__(self) -> None:
        self.prompts: list[tuple[str, str]] = []

    def __call__(self, settings, model, system, prompt):  # type: ignore[no-untyped-def]
        self.prompts.append((system, prompt))
        line10 = re.search(r"^10 \| (.*)$", prompt, re.M)
        quote = line10.group(1).strip() if line10 else ""
        findings = [
            {"rule": "style.interface_description", "line": 10, "evidence": quote, "message": "描述没有写明对端端口"},
            {"rule": "style.interface_description", "line": 10, "message": "建议统一描述格式"},
            {"rule": "style.interface_description", "line": 999, "evidence": "x", "message": "不存在的行"},
            {"rule": "bgp.peer.remote_as_missing", "line": 10, "evidence": quote, "message": "未勾选的规则"},
            {"rule": "style.interface_description", "line": 10, "evidence": "TO-RNC-01", "message": "证据与原文不符"},
            {
                "rule": "style.interface_description",
                "line": 4,
                "evidence": "route-distinguisher",
                "message": "不是接口",
            },
            {"rule": "style.vrf_ip", "line": 11, "evidence": "ip binding", "message": "接口没有地址"},
        ]
        return ai.Reply(json.dumps({"findings": findings}, ensure_ascii=False), model, 50, 30)


@pytest.fixture
def ai_settings(configured_root: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LMESH_AI__PROVIDER", "openai")
    monkeypatch.setenv("LMESH_AI__BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("LMESH_AI__MODEL", "fake-model")
    s = config.load()
    store.upgrade(s.database_url)
    fake = _FakeAI()
    monkeypatch.setattr(ai, "provider_hook", fake)
    return s, fake


def test_ai_findings_are_verified_by_code(kb, atn, ai_rules_dir: Path, ai_settings) -> None:  # type: ignore[no-untyped-def]
    s, fake = ai_settings
    text = _read(SCRIPTS / "atn-change-good.txt")
    cfg = {"settings": s, "rules": ["style.interface_description", "style.vrf_ip"]}
    r = script_check.check_text(text, kb, atn, "change", True, rules_dir=ai_rules_dir, ai=cfg)
    info = r["ai"]
    assert info["status"] == "ok" and info["configured"] and info["accepted"] == 2
    got = [i for i in r["issues"] if i["source"] == "ai"]
    assert [(i["line"], i["status"]) for i in got] == [(10, "passed"), (10, "unverifiable")]
    assert got[0]["category"] == "ai" and got[0]["node"] == "interface[GigabitEthernet0/2/2]"
    reasons = sorted(x["reason"] for x in info["rejected"])
    assert reasons == sorted(
        ["line_invalid", "rule_not_selected", "evidence_mismatch", "target_mismatch", "code_disagrees"]
    )
    # 只发送勾选的规则；发送的内容可查看（脱敏后）
    system, prompt = fake.prompts[0]
    assert "style.interface_description" in prompt and "bgp.peer.remote_as_missing" not in prompt
    assert info["sent"][0]["prompt"] == prompt
    # 同一份请求再次检查：用缓存，不再调用 AI
    r2 = script_check.check_text(text, kb, atn, "change", True, rules_dir=ai_rules_dir, ai=cfg)
    assert len(fake.prompts) == 1 and r2["ai"]["cached"] and r2["ai"]["accepted"] == 2


def test_ai_not_configured_keeps_other_checks(kb, atn, configured_root: Path, ai_rules_dir: Path) -> None:  # type: ignore[no-untyped-def]
    s = config.load()
    r = script_check.check_text(
        _read(SCRIPTS / "atn-change-order.txt"),
        kb,
        atn,
        "change",
        True,
        rules_dir=ai_rules_dir,
        ai={"settings": s, "rules": ["style.interface_description"]},
    )
    assert r["ai"]["status"] == "not_configured" and r["summary"]["errors"] == 3


# ---------------------------------------------------------------- 文本差异


def test_textdiff_moves_changes_and_ignore_order() -> None:
    a = "a\nb\nc\nd\ne x\n"
    b = "c\na\nb\nd\ne y\nf\n"
    r = textdiff.diff(a, b, ignore_order=True)
    assert r["stats"]["move"] == 1 and r["stats"]["change"] == 1 and r["stats"]["add"] == 1 and r["stats"]["del"] == 0
    assert r["moves"] == [{"from": 3, "to": 1, "text": "c"}]
    ch = next(x for x in r["rows"] if x["t"] == "change")
    assert ch["sa"] == [[2, 3]] and ch["sb"] == [[2, 3]]
    uo = r["unordered"]
    assert [x["text"] for x in uo["only_a"]] == ["e x"] and [x["text"] for x in uo["only_b"]] == ["e y", "f"]
    assert r["unified"].startswith("--- a\n+++ b\n")


def test_textdiff_reorder_is_moves_only(kb, asr) -> None:  # type: ignore[no-untyped-def]
    before = _read(SCRIPTS / "asr-change-order.txt")
    after = script_check.reorder_text(before, kb, asr, recheck=False)["script"]
    r = textdiff.diff(before, after, ignore_order=True)
    assert r["stats"]["move"] >= 2 and r["stats"]["change"] == 0
    assert r["unordered"]["equal"] is False or r["unordered"]["only_a"] == []


def test_textdiff_reports() -> None:
    r = textdiff.diff("x 1\ny\n", "y\nx 2\n")
    zh = textdiff.report(
        r,
        "旧",
        "新",
        "zh-CN",
        "html",
        {"equal": False, "diffs": [{"kind": "changed", "node": "n", "a": {"value": 1}, "b": {"value": 2}}]},
    )
    assert zh.media_type.startswith("text/html") and "配置文本差异报告" in zh.content and "语义差异" in zh.content
    en = textdiff.report(r, "old", "new", "en", "html")
    assert "Configuration text diff report" in en.content and en.filename == "diff-en.html"
    u = textdiff.report(r, "old.txt", "new.txt", "en", "unified")
    assert u.content.startswith("--- old.txt\n+++ new.txt") and u.filename.endswith(".diff")


# ---------------------------------------------------------------- 项目、脚本、修订（SQLite 与 PostgreSQL）


@pytest.fixture
def proj_db(db_url: str, full_kb_root: Path):  # type: ignore[no-untyped-def]
    from lmesh.core import importer

    store.upgrade(db_url)
    importer.import_sources([("atn-base.cfg", (CHANGE / "atn-base.cfg").read_bytes())], db_url, "basic", KB_ROOT)
    return db_url


def test_projects_scripts_revisions(proj_db: str, kb) -> None:  # type: ignore[no-untyped-def]
    db = proj_db
    me = checkproj.Actor(None, True, "api")
    p = checkproj.create_project(db, me, {"name": "割接检查", "device_id": 1})
    assert p["device"]["name"] == "ATN-CHANGE-01" and p["order_check"] and p["scripts"] == 0
    sc = checkproj.create_script(
        db, me, p["id"], {"name": "绑定 VPN", "content": _read(SCRIPTS / "atn-change-order.txt")}
    )
    assert sc["kind"] == "change" and sc["revisions"] == 1
    # 检查保存的内容：摘要记在脚本上
    r = checkproj.check(db, kb, me, p["id"], sc["id"])
    assert r["summary"]["errors"] == 3 and r["script"]["saved"]
    assert checkproj.get_project(db, me, p["id"])["last_check"]["errors"] == 3
    # 编辑器里的未保存内容、关闭顺序核查
    r2 = checkproj.check(db, kb, me, p["id"], sc["id"], content=_read(SCRIPTS / "atn-change-order.txt"), order=False)
    assert r2["summary"]["errors"] == 1
    # 手动保存（内容不变不形成修订）
    same = checkproj.update_script(db, me, p["id"], sc["id"], {"content": _read(SCRIPTS / "atn-change-order.txt")})
    assert same["revision"] is None
    edited = _read(SCRIPTS / "atn-change-order.txt").replace("OAM-LINK-NEW", "OAM-LINK-3")
    up = checkproj.update_script(db, me, p["id"], sc["id"], {"content": edited})
    assert up["revision"]["seq"] == 2 and up["revision"]["source"] == "manual"
    # 重排（未保存的编辑先存一条，再存重排后的一条）
    unsaved = edited.replace("OAM-LINK-3", "OAM-LINK-4")
    ro = checkproj.reorder(db, kb, me, p["id"], sc["id"], content=unsaved, apply=True)
    assert ro["applied"] and ro["before_revision"]["seq"] == 3 and ro["revision"]["seq"] == 4
    assert ro["revision"]["source"] == "reorder" and ro["revision"]["note"]["moves"]
    revs = checkproj.revisions(db, me, p["id"], sc["id"])
    assert [x["source"] for x in revs] == ["reorder", "manual", "manual", "create"]
    # 两个修订的对比：重排造成的位置变化识别为移动；语义上与重排前相同（按依赖顺序执行的结果）
    d = checkproj.diff(
        db,
        kb,
        me,
        {"type": "revision", "revision_id": revs[1]["id"]},
        {"type": "revision", "revision_id": revs[0]["id"]},
        ignore_order=True,
    )
    assert d["stats"]["move"] >= 2 and d["semantic"] is not None and d["semantic"]["equal"]
    # 脚本与基线配置的对比
    d2 = checkproj.diff(
        db,
        kb,
        me,
        {"type": "baseline", "project_id": p["id"]},
        {"type": "script", "script_id": sc["id"]},
        semantic=False,
    )
    assert d2["a"]["kind"] == "baseline" and d2["stats"]["lines_a"] > 90
    # 恢复到第一条修订
    rs = checkproj.restore(db, me, p["id"], sc["id"], revs[-1]["id"])
    assert rs["revision"]["source"] == "restore" and rs["revision"]["note"]["from_seq"] == 1
    assert checkproj.get_script(db, me, p["id"], sc["id"])["content"] == _read(SCRIPTS / "atn-change-order.txt")


def test_project_ownership(proj_db: str) -> None:
    from lmesh.core import users

    db = proj_db
    alice = users.create_user(db, "alice", "Alice-pass-1", "user")
    bob = users.create_user(db, "bob", "Bob-pass-12", "user")
    a = checkproj.Actor(alice["id"], False, "alice")
    b = checkproj.Actor(bob["id"], False, "bob")
    admin = checkproj.Actor(None, True, "api")
    p = checkproj.create_project(db, a, {"name": "alice 的项目", "device_id": 1})
    assert p["owner"]["username"] == "alice"
    assert [x["id"] for x in checkproj.list_projects(db, a)] == [p["id"]]
    assert checkproj.list_projects(db, b) == []
    assert len(checkproj.list_projects(db, admin)) == 1
    with pytest.raises(checkproj.ProjectError) as e:
        checkproj.get_project(db, b, p["id"])
    assert e.value.kind == "not_found"
    checkproj.delete_project(db, a, p["id"])
    assert checkproj.list_projects(db, admin) == []


def test_project_validation(proj_db: str) -> None:
    me = checkproj.Actor()
    with pytest.raises(checkproj.ProjectError) as e:
        checkproj.create_project(proj_db, me, {"name": "x", "device_id": 99})
    assert e.value.key == "script_check.device_not_found"
    with pytest.raises(checkproj.ProjectError) as e:
        checkproj.create_project(proj_db, me, {"name": " "})
    assert e.value.key == "check_project.bad_name"
    p = checkproj.create_project(proj_db, me, {"name": "无基线", "default_kind": "full"})
    sc = checkproj.create_script(proj_db, me, p["id"], {"name": "s", "content": "interface X\n"})
    assert sc["kind"] == "full"
    with pytest.raises(checkproj.ProjectError) as e:
        checkproj.reorder(proj_db, analysis.load_kb(KB_ROOT), me, p["id"], sc["id"])
    assert e.value.key == "check_project.reorder_change_only"


# ---------------------------------------------------------------- 知识库自带的 AI 规则（knowledge/rules/style-ai.yaml）

AI_REVIEW_IDS = [
    "style.interface_description",
    "style.bgp_peer_description",
    "style.vrf_naming",
    "style.policy_naming",
    "style.prefix_list_naming",
]


def test_builtin_ai_review_rules(kb, atn) -> None:  # type: ignore[no-untyped-def]
    from lmesh.core import checks

    listed = script_check.ai_rules(kb)
    assert [r["id"] for r in listed] == AI_REVIEW_IDS and all(not r["code"] for r in listed)
    assert all(set(r["title"]) == {"zh-CN", "en", "pt-BR"} for r in listed)
    # 普通的配置检查：AI 专属规则不求值、不报错，也不计入已加载的规则数
    rules = rulesmod.load_dir(kb, KB_ROOT / "rules")
    res = checks.check(atn.graph, kb, rules)
    assert not any(f["rule"].startswith("style.") for f in res["findings"])
    assert res["rules_loaded"] == len([r for r in rules if r.enabled and r.assert_ is not None])
    assert "style.vrf_naming" in {r["id"] for r in checks.list_rules(kb, KB_ROOT / "rules")["rules"]}


def test_load_style_cached(kb, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    from lmesh.core import canon

    canon._STYLE_CACHE.clear()
    calls = []
    real = canon.read_yaml
    monkeypatch.setattr(canon, "read_yaml", lambda f: calls.append(f) or real(f))
    a = canon.load_style(kb, "huawei-vrp8")
    a["exits"]["x"] = "changed"
    b = canon.load_style(kb, "huawei-vrp8")
    assert len(calls) == 1 and "x" not in b["exits"] and b["exits"] == canon._read_style(Path(calls[0]))["exits"]
