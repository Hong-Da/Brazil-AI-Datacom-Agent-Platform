"""M2-5：对比的身份差异过滤、检查规则的开关与级别写回、忽略检查发现、对比 / 检查报告（中英文、HTML / Markdown）。"""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from lmesh.core import analysis, checks, compare, ignores, report, rule_edit, store
from lmesh.core import graph as graphmod
from lmesh.core import rules as rulesmod
from lmesh.core.kb import KnowledgeBase, repo

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parent.parent.parent
KB_ROOT = ROOT / "knowledge"
CHECK_INPUTS = ROOT / "tests" / "inputs" / "configs" / "check"
CISCO = "cisco-iosxe-asr920-17.15"
ASR = (KB_ROOT / "samples" / "cisco-iosxe-asr920-synthetic" / "pe-asr920-01.cfg").read_text(encoding="utf-8")
# 另一台同角色设备：主机名、环回地址与 Router ID、一个对等体地址不同（身份），外加一处真实修改（MTU）
ASR_B = (
    ASR.replace("hostname PE-ASR920-01", "hostname PE-ASR920-02")
    .replace("10.255.0.21", "10.255.0.22")
    .replace("10.255.0.2\n", "10.255.0.3\n")
    .replace("10.255.0.2 ", "10.255.0.3 ")
    .replace(" mtu 9216\n ip address 10.1.0.2", " mtu 9000\n ip address 10.1.0.2")
)
NOW = datetime(2026, 10, 18, 9, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return analysis.load_kb(KB_ROOT)


def _cmp(kb: KnowledgeBase, **kw: Any) -> dict[str, Any]:
    a = compare.side_from_text(ASR, kb, CISCO, "PE-ASR920-01")
    b = compare.side_from_text(ASR_B, kb, CISCO, "PE-ASR920-02")
    return compare.compare(a, b, kb, include_raw=True, **kw)


def _graph(kb: KnowledgeBase, path: Path) -> Any:
    res = analysis.parse_text(path.read_text(encoding="utf-8"), kb)
    return graphmod.build(res.parsed, kb, res.profile, path.stem)


# ---------- 隐藏身份差异 ----------


def test_hide_identity(kb: KnowledgeBase) -> None:
    full = _cmp(kb)
    assert full["summary"]["total"] == 12 and full["summary"]["hidden_identity"] == 0 and full["hidden_diffs"] == []
    hidden = _cmp(kb, hide_identity=True)
    # 只剩真实修改；被隐藏的差异单独给出，个数在 summary
    assert [(d["kind"], d["node"]) for d in hidden["diffs"]] == [("changed", "interface[GigabitEthernet0/0/0]/mtu")]
    assert hidden["summary"]["total"] == 1 and hidden["summary"]["hidden_identity"] == 11
    nodes = {d["node"] for d in hidden["hidden_diffs"]}
    assert {
        "bgp.instance[64512]/router_id",
        "interface[Loopback0]/ipv4[10.255.0.21]",
        "bgp.instance[64512]/bgp.peer[10.255.0.3]",
        "bgp.instance[64512]/bgp.af[afi=vpnv4,vrf=]/peer[10.255.0.2]",
        "raw[hostname PE-ASR920-01]",
    } <= nodes
    opts = hidden["options"]
    assert opts["hide_identity"] is True
    assert {"schema": "bgp.instance.router_id", "match": "attr"} in opts["hidden_identity"]
    assert any(x["match"] == "raw" for x in opts["hidden_identity"])
    # 只过滤结果：配对与改名不受影响
    assert hidden["renames"] == full["renames"] and hidden["unknown"] == full["unknown"]


def test_identity_af_peer_by_group_is_kept() -> None:
    by_group = {"kind": "added", "node_kind": "object", "schema": "bgp.af.peer", "a": None, "b": {"value": "RR"}}
    by_ip = {**by_group, "b": {"value": "10.0.0.1"}}
    assert not compare.is_identity(by_group) and compare.is_identity(by_ip)


# ---------- 规则的开关与级别 ----------


@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    root = tmp_path / "kb"
    shutil.copytree(KB_ROOT / "rules", root / "rules")
    repo.ensure_repo(root)
    return root


def test_set_builtin_and_custom_rule(kb: KnowledgeBase, kb_root: Path) -> None:
    g = _graph(kb, CHECK_INPUTS / "huawei-issues.cfg")
    d = kb_root / "rules"
    before = checks.check(g, kb, rulesmod.load_dir(kb, d), overrides=checks.load_overrides(d))
    assert before["summary"]["by_rule"]["ref.orphan"] == 4

    view = rule_edit.set_rule(kb_root, kb, "ref.orphan", enabled=False)
    assert view["source"] == "builtin" and view["enabled"] is False and view["default_severity"] == "warning"
    view = rule_edit.set_rule(kb_root, kb, "vrf.rd_without_rt", severity="error")
    assert view["source"] == "common.yaml" and view["severity"] == "error" and view["enabled"] is True

    # 写回的文件：覆盖文件只有内置检查；规则文件保留注释，只改了这一条
    text = (d / "builtin.yaml").read_text(encoding="utf-8")
    assert "builtin:" in text and "ref.orphan:" in text and "enabled: false" in text
    common = (d / "common.yaml").read_text(encoding="utf-8")
    assert common.startswith("# 通用配置检查规则")
    assert re.search(r"id: vrf\.rd_without_rt\n(?:.*\n)*?\s+severity: error", common)

    # 重新加载后生效
    after = checks.check(g, kb, rulesmod.load_dir(kb, d), overrides=checks.load_overrides(d))
    assert "ref.orphan" not in after["summary"]["by_rule"]
    rd = next(f for f in after["findings"] if f["rule"] == "vrf.rd_without_rt")
    assert rd["severity"] == "error"
    assert after["summary"]["by_severity"]["error"] == before["summary"]["by_severity"]["error"] + 1
    listed = {r["id"]: r for r in checks.list_rules(kb, d)["rules"]}
    assert listed["ref.orphan"]["enabled"] is False and listed["vrf.rd_without_rt"]["severity"] == "error"

    # 每次修改提交一次
    msgs = [str(c["message"]) for c in repo.history(kb_root)]
    assert msgs[0] == "修改检查规则 vrf.rd_without_rt：severity=error"
    assert msgs[1] == "修改检查规则 ref.orphan：enabled=False"


def test_set_rule_errors(kb: KnowledgeBase, kb_root: Path) -> None:
    with pytest.raises(rule_edit.RuleEditError) as e:
        rule_edit.set_rule(kb_root, kb, "no.such.rule", enabled=False)
    assert e.value.kind == "not_found" and e.value.key == "rules.not_found"
    with pytest.raises(rule_edit.RuleEditError) as e:
        rule_edit.set_rule(kb_root, kb, "ref.orphan")
    assert e.value.key == "rules.edit_empty"
    with pytest.raises(rule_edit.RuleEditError):
        rule_edit.set_rule(kb_root, kb, "ref.orphan", severity="fatal")


def test_bad_override_file(kb: KnowledgeBase, tmp_path: Path) -> None:
    (tmp_path / "builtin.yaml").write_text("builtin:\n  no.such: {enabled: false}\n  ref.orphan: {severity: x}\n")
    with pytest.raises(rulesmod.RuleError) as e:
        checks.load_overrides(tmp_path)
    assert sorted(i["code"] for i in e.value.issues) == ["rules.err.bad_severity", "rules.err.unknown_builtin"]
    assert rulesmod.load_dir(kb, tmp_path) == []  # 覆盖文件不当作规则文件读


# ---------- 忽略检查发现（SQLite 与 PostgreSQL） ----------


def test_ignores(kb: KnowledgeBase, db_url: str) -> None:
    from lmesh.core.store.models import Device

    store.upgrade(db_url)
    assert "check_ignores" in store.table_names(db_url)
    with store.session(db_url) as s:
        dev = Device(name="HW-ISSUES", vendor="huawei")
        s.add(dev)
        s.flush()
        dev_id = dev.id
    known = set(checks.BUILTIN) | {"vrf.rd_without_rt"}
    node = "bgp.instance[65000]/bgp.af[afi=ipv4,vrf=]/peer[192.0.2.6]/import_policy"
    row = ignores.add_ignore(db_url, dev_id, "ref.dangling", node, "  上线前会补策略  ", known)
    assert row["created"] and row["reason"] == "上线前会补策略"
    again = ignores.add_ignore(db_url, dev_id, "ref.dangling", node, "改期", known)  # 唯一：更新原因
    assert not again["created"] and again["id"] == row["id"] and again["reason"] == "改期"
    assert [r["id"] for r in ignores.list_ignores(db_url, dev_id)] == [row["id"]]

    g = _graph(kb, CHECK_INPUTS / "huawei-issues.cfg")
    rules = rulesmod.load_dir(kb, KB_ROOT / "rules")
    plain = checks.check(g, kb, rules)
    res = checks.check(g, kb, rules, ignores=ignores.index(db_url, dev_id))
    hit = next(f for f in res["findings"] if f["rule"] == "ref.dangling")
    assert hit["ignored"] and hit["ignore_reason"] == "改期" and hit["ignore_id"] == row["id"]
    assert all(not f["ignored"] and f["ignore_id"] is None for f in plain["findings"])
    s0, s1 = plain["summary"], res["summary"]
    assert s1["total"] == s0["total"] and s1["ignored"] == 1 and s0["ignored"] == 0
    assert s1["by_severity"]["error"] == s0["by_severity"]["error"] - 1
    assert s1["by_rule"].get("ref.dangling", 0) == s0["by_rule"]["ref.dangling"] - 1

    with pytest.raises(ignores.IgnoreError) as e:
        ignores.add_ignore(db_url, dev_id, "ref.orphan", "x", "   ", known)
    assert e.value.key == "check.ignore_reason_required"
    with pytest.raises(ignores.IgnoreError) as e:
        ignores.add_ignore(db_url, dev_id, "no.rule", "x", "r", known)
    assert e.value.kind == "not_found"
    with pytest.raises(ignores.IgnoreError) as e:
        ignores.add_ignore(db_url, 9999, "ref.orphan", "x", "r", known)
    assert e.value.key == "compare.device_not_found"

    assert ignores.remove_ignore(db_url, row["id"])["deleted"]
    assert ignores.list_ignores(db_url, dev_id) == []
    with pytest.raises(ignores.IgnoreError):
        ignores.remove_ignore(db_url, row["id"])


# ---------- 报告 ----------


def test_compare_report_html(kb: KnowledgeBase) -> None:
    r = _cmp(kb, hide_identity=True)
    zh = report.compare_report(r, "zh-CN", "html", now=NOW)
    assert zh.filename == "compare-PE-ASR920-01-PE-ASR920-02.zh-CN.html"
    assert zh.media_type.startswith("text/html")
    c = zh.content
    assert c.startswith("<!doctype html>") and '<html lang="zh-CN">' in c and "<style>" in c and "@media print" in c
    # 自包含：不引用外部脚本、样式、图片
    assert not re.search(r"<(script|link|img)\b", c) and "http://" not in c and "https://" not in c
    assert "<h1>配置对比报告</h1>" in c and "2026-10-18 09:30:00 +0000" in c
    assert "<th>Profile</th>" in c or ">Profile<" in c
    assert CISCO in c and "隐藏身份差异" in c and "已隐藏的身份差异：11 处" in c
    # 按功能域分表；差异标出两侧有效值、来源与原文行号
    assert "<h3>interface (1)</h3>" in c and '<table class="diffs">' in c
    row = re.search(r'<tr class="k-changed">.*?</tr>', c, re.S)
    assert row is not None
    cells = row.group(0)
    assert '<span class="badge">修改</span>' in cells and "interface[GigabitEthernet0/0/0]/mtu" in cells
    assert "<code>9216</code>" in cells and "<code>9000</code>" in cells and "显式 · 行 39" in cells
    for title in ("<h2>改名</h2>", "<h2>不可比（只有一侧 Profile 有默认值）</h2>", "<h2>未识别行</h2>"):
        assert title in c

    en = report.compare_report(r, "en", "html", now=NOW).content
    assert "<h1>Configuration Comparison Report</h1>" in en and '<span class="badge">Changed</span>' in en
    assert "explicit · line 39" in en and "Not comparable (default on one side only)" in en
    assert "Unrecognized lines" in en and "配置" not in en


def test_compare_report_markdown(kb: KnowledgeBase) -> None:
    r = _cmp(kb)
    md = report.compare_report(r, "zh-CN", "md", now=NOW)
    assert md.filename.endswith(".zh-CN.md") and md.media_type.startswith("text/markdown")
    c = md.content
    assert c.startswith("# 配置对比报告\n")
    assert "| 项目 | A | B |\n|---|---|---|" in c
    assert "| 类型 | 节点 | A | B |\n|---|---|---|---|" in c
    assert "| 修改 | `interface[GigabitEthernet0/0/0]/mtu` | `9216` · 显式 · 行 39 | `9000` · 显式 · 行 39 |" in c
    assert "| 删除 | `raw[hostname PE-ASR920-01]` |" in c
    assert "### bgp (" in c and "## 改名" in c and "## 未识别行" in c
    # 表格每行的列数一致（单元格里的 | 已转义）
    for block in re.findall(r"(\| 类型 .*?)(?:\n\n|\Z)", c, re.S):
        widths = {len(re.findall(r"(?<!\\)\|", ln)) for ln in block.strip().splitlines()}
        assert len(widths) == 1, block
    en = report.compare_report(r, "en", "md", now=NOW).content
    assert en.startswith("# Configuration Comparison Report") and "| Kind | Node | A | B |" in en


def test_check_report(kb: KnowledgeBase) -> None:
    g = _graph(kb, CHECK_INPUTS / "huawei-issues.cfg")
    rules = rulesmod.load_dir(kb, KB_ROOT / "rules")
    node = "bgp.instance[65000]/bgp.af[afi=ipv4,vrf=]/peer[192.0.2.6]/import_policy"
    res = checks.check(g, kb, rules, ignores={("ref.dangling", node): {"id": 7, "reason": "上线前补策略"}})
    meta = {"version_id": 3, "sw_version": "V800R023C00", "collected_at": "2026-10-17T08:00:00+00:00"}
    html_zh = report.build_check_report(g, kb, res, "zh-CN", "html", meta, now=NOW)
    assert html_zh.filename == "check-huawei-issues.zh-CN.html"
    c = html_zh.content
    assert "<h1>配置检查报告</h1>" in c and "V800R023C00" in c and "#3 (2026-10-17T08:00:00+00:00)" in c
    # 按严重度分组；被忽略的单独列出并写明原因
    assert "<h3>错误 (3)</h3>" in c and "<h3>警告 (8)</h3>" in c and "<h3>提示 (1)</h3>" in c
    assert "<h2>已忽略的发现 (1)</h2>" in c and "上线前补策略" in c
    assert 'class="s-error ignored"' in c
    # 有孤儿：附清理脚本与验证结论
    assert "<h2>清理脚本</h2>" in c and "undo route-policy UNUSED-POLICY" in c and "验证通过" in c
    assert "BGP 对等体 192.0.2.2 没有对端 AS" in c

    md_en = report.build_check_report(g, kb, res, "en", "md", meta, now=NOW).content
    assert md_en.startswith("# Configuration Check Report")
    assert "### Error (3)" in md_en and "## Ignored findings (1)" in md_en
    assert "| Severity | Rule | Domain | Node | Line | Description | Suggestion |" in md_en
    assert "## Cleanup script\n" in md_en and "```text\n! lmesh cleanup" in md_en


def test_check_report_without_orphans(kb: KnowledgeBase) -> None:
    res = analysis.parse_text("sysname R1\n#\nreturn\n", kb, "huawei-atn-v800r023")
    g = graphmod.build(res.parsed, kb, res.profile, "R1")
    out = report.build_check_report(g, kb, checks.check(g, kb, []), "zh-CN", "md", now=NOW).content
    assert "没有发现问题。" in out and "清理脚本" not in out


def test_report_args() -> None:
    assert report.report_lang("pt-BR") == "en" and report.report_lang("zh-CN") == "zh-CN"
    with pytest.raises(report.ReportError):
        report.check_report({"summary": {}, "findings": []}, "pt-BR", "html")
    with pytest.raises(report.ReportError):
        report.check_report({"summary": {}, "findings": []}, "en", "pdf")
    rep = report.Report("check-路由器1.zh-CN.html", "", "text/html")
    disp = rep.disposition()
    assert 'filename="check-___1.zh-CN.html"' in disp and "filename*=UTF-8''check-%E8%B7%AF" in disp


# ---------- 冗余清理：只清理选中的对象、兜底原因 ----------


def test_cleanup_selected_objects(kb: KnowledgeBase) -> None:
    from lmesh.core import cleanup

    g = _graph(kb, CHECK_INPUTS / "huawei-issues.cfg")
    # 选父对象：只被它引用的级联孤儿随之删除
    res = cleanup.cleanup(g, kb, objects=["rp.policy[UNUSED-POLICY]"])
    assert res["selected"] is True
    assert [o["node"] for o in res["objects"]] == ["rp.policy[UNUSED-POLICY]", "rp.prefix_list[ONLY-UNUSED]"]
    assert res["skipped"] == [] and res["verify"]["ok"]  # 没选的孤儿删除后仍是孤儿，不算新问题
    assert all(c["fallback_reason"] is None for c in res["commands"])
    # 只选子对象、父对象仍在：不能删
    child = cleanup.cleanup(g, kb, objects=["rp.prefix_list[ONLY-UNUSED]"])
    assert child["commands"] == [] and child["objects"] == []
    assert child["skipped"] == [
        {
            "node": "rp.prefix_list[ONLY-UNUSED]",
            "reason": "parent_kept",
            "lines": [],
            "via": ["rp.policy[UNUSED-POLICY]"],
        }
    ]
    # 不是孤儿 / 可能被使用
    other = cleanup.cleanup(
        g, kb, objects=["vrf.instance[BGP-ONLY]", "rp.policy[NH-POLICY]", "vrf.instance[UNUSED-VRF]"]
    )
    assert [o["node"] for o in other["objects"]] == ["vrf.instance[UNUSED-VRF]"]
    assert [(s["node"], s["reason"]) for s in other["skipped"]] == [
        ("vrf.instance[BGP-ONLY]", "not_orphan"),
        ("rp.policy[NH-POLICY]", "maybe_referenced"),
    ]
    assert other["verify"]["ok"]
    # 不给 objects：与以前相同，全部清理
    full = cleanup.cleanup(g, kb)
    assert full["selected"] is False and len(full["objects"]) == 5


def test_fallback_reason(kb: KnowledgeBase) -> None:
    from lmesh.core import cleanup
    from lmesh.core.kb.model import Card

    g = _graph(kb, CHECK_INPUTS / "cisco-issues.cfg")
    lines = {st.line.no: st.line for st in g.graph["statements"]}
    card = kb.cards["cisco-iosxe.ip-prefix-list"]
    assert cleanup.render_undo_reason(card, lines[39], "no")[1] is None
    bare = Card(id="x", family="cisco-iosxe", domain="d", syntax="x", view="system")
    assert cleanup.render_undo_reason(bare, lines[39], "no") == (
        "no ip prefix-list SHARED seq 5 permit 10.1.0.0/16",
        "no_undo",
    )
    broken = Card(
        id="y", family="cisco-iosxe", domain="d", syntax="x", view="system", undo="no ip prefix-list <name> ["
    )
    assert cleanup.render_undo_reason(broken, lines[39], "no")[1] == "undo_invalid"
    other = Card(
        id="z", family="cisco-iosxe", domain="d", syntax="x", view="system", undo="no ip community-list <name>"
    )
    assert cleanup.render_undo_reason(other, lines[39], "no")[1] == "render_failed"
