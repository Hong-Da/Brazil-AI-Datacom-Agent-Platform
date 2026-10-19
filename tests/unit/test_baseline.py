"""安全基线审计（M4-7）：规则引擎扩展（设备级规则、绝对路径、match / range / key / family、变量与基线覆盖）、
基线文件校验、矩阵与分数、样本基准（现网 ATN 与合成样本，结论已人工核对）、基线报告。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lmesh.core import analysis
from lmesh.core import baseline as blmod
from lmesh.core import graph as graphmod
from lmesh.core import rules as rulesmod
from lmesh.core.kb import KnowledgeBase
from lmesh.core.report_baseline import baseline_report

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parent.parent.parent
KB_ROOT = ROOT / "knowledge"
SAMPLES = KB_ROOT / "samples"
TEXTS = {"zh-CN": "x", "en": "x", "pt-BR": "x"}


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return analysis.load_kb(KB_ROOT)


@pytest.fixture(scope="module")
def bl(kb: KnowledgeBase) -> blmod.Baseline:
    return blmod.load(kb, KB_ROOT / "rules")


def _g(kb: KnowledgeBase, text: str, name: str = "d", profile: str | None = None) -> Any:
    res = analysis.parse_text(text, kb, profile)
    return graphmod.build(res.parsed, kb, res.profile, name)


def _sample(kb: KnowledgeBase, rel: str) -> Any:
    p = SAMPLES / rel
    return _g(kb, p.read_text(encoding="utf-8"), p.stem)


def _rule(**kw: Any) -> dict[str, Any]:
    base = {"id": "t.rule", "target": "device", "severity": "warning", "title": TEXTS, "message": TEXTS}
    base["suggestion"] = TEXTS
    base["assert"] = {"exists": "mgmt.ntp"}
    base.update(kw)
    return base


def _codes(kb: KnowledgeBase, doc: dict[str, Any]) -> list[tuple[str, str]]:
    with pytest.raises(rulesmod.RuleError) as e:
        rulesmod.parse_rules(kb, [("t.yaml", doc)])
    return sorted((i["field"], i["code"]) for i in e.value.issues)


HW = """sysname R1
#
telnet server enable
#
ntp-service unicast-server 10.0.0.1 source-interface GigabitEthernet0/2/1
#
snmp-agent
snmp-agent community read cipher %^%#PLAIN%^%# alias public
snmp-agent community write cipher %^%#SECRET%^%# acl 2000
#
user-interface vty 0 4
 authentication-mode aaa
 idle-timeout 0 0
 protocol inbound all
#
return
"""


# ---------- 规则引擎扩展 ----------


def test_rule_extensions(kb: KnowledgeBase) -> None:
    """设备级规则、绝对路径、match / range（min_sec）/ key（忽略大小写、正则）/ family、文件变量与覆盖。"""
    doc = {
        "vars": {"weak": ["PUBLIC"], "max_idle": 900},
        "rules": [
            _rule(id="t.telnet", **{"assert": {"not": {"exists": "mgmt.telnet/enabled"}}}),
            _rule(
                id="t.weak",
                target="mgmt.snmp.community",
                **{"assert": {"not": {"key": {"values": "$weak", "ignore_case": True}}}},
            ),
            _rule(id="t.cipher", target="mgmt.snmp.community", **{"assert": {"not": {"key": {"pattern": "^%"}}}}),
            _rule(
                id="t.idle",
                target="mgmt.line",
                **{"assert": {"range": {"path": "idle_timeout", "min": 1, "max": "$max_idle", "unit": "min_sec"}}},
            ),
            _rule(
                id="t.proto",
                target="mgmt.line",
                **{"assert": {"not": {"match": {"path": "protocols", "pattern": r"\b(all|telnet)\b"}}}},
            ),
            _rule(id="t.abs", target="mgmt.line", **{"assert": {"exists": "/mgmt.ntp/server"}}),
            _rule(
                id="t.src",
                target="mgmt.ntp.server",
                **{"assert": {"match": {"path": "source_interface", "pattern": "^loop", "ignore_case": True}}},
            ),
            _rule(id="t.family", **{"assert": {"family": ["cisco-iosxe"]}}),
        ],
    }
    rules = rulesmod.parse_rules(kb, [("t.yaml", doc)])
    g = _g(kb, HW)
    failed = sorted((r.id, n) for r, n in rulesmod.evaluate(g, rules))
    assert failed == [
        ("t.cipher", "mgmt.snmp[_]/community[%^%#SECRET%^%#]"),
        ("t.family", "device"),
        ("t.idle", "mgmt.line[vty 0 4]"),
        ("t.proto", "mgmt.line[vty 0 4]"),
        ("t.src", "mgmt.ntp[_]/server[10.0.0.1]"),
        ("t.telnet", "device"),
        ("t.weak", "mgmt.snmp[_]/community[public]"),
    ]
    # 变量覆盖：同一张图，把弱值清单换掉后 public 不再命中
    ev = rulesmod.Evaluator(g, {"weak": ["nothing"]})
    weak = next(r for r in rules if r.id == "t.weak")
    assert ev.test(weak, "mgmt.snmp[_]/community[public]", weak.assert_)


def test_evidence_trace(kb: KnowledgeBase) -> None:
    """证据：取反条件只记命中的节点，正向条件记路径上找到的节点。"""
    doc = {"rules": [_rule(target="mgmt.line", **{"assert": {"equals": {"path": "protocols", "value": "ssh"}}})]}
    r = rulesmod.parse_rules(kb, [("t.yaml", doc)])[0]
    g = _g(kb, HW)
    ev = rulesmod.Evaluator(g)
    assert not ev.test(r, "mgmt.line[vty 0 4]", r.assert_)
    assert ev.trace == {"mgmt.line[vty 0 4]/protocols"}


def test_extension_validation(kb: KnowledgeBase) -> None:
    assert _codes(kb, {"rules": [_rule(**{"assert": {"match": {"path": "mgmt.ntp", "pattern": "("}}})]}) == [
        ("assert", "rules.err.bad_pattern")
    ]
    assert _codes(kb, {"rules": [_rule(**{"assert": {"in": {"path": "mgmt.ntp", "values": "$nope"}}})]}) == [
        ("assert", "rules.err.cond_args"),
        ("assert", "rules.err.unknown_var"),
    ]
    assert _codes(kb, {"rules": [_rule(**{"assert": {"range": {"path": "mgmt.ntp", "max": 1, "unit": "hours"}}})]}) == [
        ("assert", "rules.err.bad_unit")
    ]
    assert _codes(kb, {"rules": [_rule(**{"assert": {"family": ["juniper"]}})]}) == [
        ("assert", "rules.err.unknown_family")
    ]
    assert _codes(kb, {"rules": [_rule(**{"assert": {"key": {"path": "mgmt.ntp"}}})]}) == [
        ("assert", "rules.err.cond_args")
    ]
    assert _codes(kb, {"rules": [_rule(**{"assert": {"exists": "/mgmt.nope"}})]}) == [
        ("assert", "rules.err.path_unknown")
    ]
    assert _codes(kb, {"rules": [_rule(remedy={"juniper": ["x"]})]}) == [("remedy.juniper", "rules.err.bad_remedy")]
    assert _codes(kb, {"rules": [_rule(remedy={"huawei": ["undo {foo}"]})]}) == [
        ("remedy.huawei", "rules.err.placeholder")
    ]
    assert _codes(kb, {"rules": [_rule(profiles=["basic"])]}) == [("profiles", "rules.err.unknown_profile")]
    assert _codes(kb, {"kind": "baseline", "rules": [_rule()]}) == [
        ("profiles", "rules.err.missing_field"),
        ("profiles", "rules.err.missing_field"),
    ]
    prof = {"basic": {"title": TEXTS, "description": TEXTS, "includes": ["x"], "vars": {"v": 1}}}
    assert _codes(kb, {"kind": "baseline", "profiles": prof, "rules": [_rule(profiles=["basic"])]}) == [
        ("profiles.basic.includes", "rules.err.unknown_profile"),
        ("profiles.basic.vars", "rules.err.unknown_var"),
    ]
    assert _codes(kb, {"kind": "audit", "rules": [_rule()]}) == [("kind", "rules.err.bad_kind")]


def test_check_does_not_load_baseline(kb: KnowledgeBase) -> None:
    """lmesh check 只读检查规则；基线文件只由基线加载。"""
    check_ids = {r.id for r in rulesmod.load_dir(kb, KB_ROOT / "rules")}
    base_ids = {r.id for r in rulesmod.load_dir(kb, KB_ROOT / "rules", "baseline")}
    assert check_ids and base_ids and not check_ids & base_ids
    assert all(i.startswith("sec.") for i in base_ids)


# ---------- 基线文件、分组与结果结构 ----------


def test_baseline_file(bl: blmod.Baseline) -> None:
    assert set(bl.profiles) == {"basic", "strict"}
    basic, _ = blmod.select(bl, "basic")
    strict, over = blmod.select(bl, "strict")
    assert len(basic) >= 15 and {r.id for r in basic} < {r.id for r in strict}
    assert blmod.expand(bl, "strict") == ["basic", "strict"]
    assert over["baseline-security.yaml"]["max_idle_seconds"] == 600
    for (
        r
    ) in strict:  # 每条规则：三语说明；参考命令有华为、Cisco 两种写法，Nokia 适用的另有 Classic 与 MD-CLI 两种（M7-5）
        assert set(r.remedy) in (
            {"huawei", "cisco"},
            {"huawei", "cisco", "nokia", "nokia-sros-md"},
            {"nokia", "nokia-sros-md"},
        ), r.id
        assert all(r.title[lang] and r.suggestion[lang] for lang in ("zh-CN", "en", "pt-BR"))
    with pytest.raises(blmod.BaselineError):
        blmod.select(bl, "nope")
    listing = blmod.list_rules(bl)
    assert [p["id"] for p in listing["profiles"]] == ["basic", "strict"]
    assert listing["total"] == len(strict)


def test_audit_structure(kb: KnowledgeBase, bl: blmod.Baseline) -> None:
    res = blmod.audit([_g(kb, HW, "R1")], bl, "basic")
    d = res["devices"][0]
    assert res["matrix"]["devices"] == ["R1"] and len(res["matrix"]["cells"]) == res["summary"]["rules"]
    assert d["style"] == "huawei" and d["results"]["sec.telnet_disabled"] == "fail"
    assert d["results"]["sec.tacacs_key"] == "na"
    weak = next(f for f in d["failures"] if f["rule"] == "sec.snmp_weak_community")
    assert weak["node"] == "mgmt.snmp[_]/community[public]" and weak["lines"] == [8]
    assert weak["remedy"][0] == "undo snmp-agent community public"
    telnet = next(f for f in d["failures"] if f["rule"] == "sec.telnet_disabled")
    assert telnet["lines"] == [3] and telnet["evidence"] == ["mgmt.telnet[_]/enabled"]
    idle = next(f for f in d["failures"] if f["rule"] == "sec.line_idle_timeout")
    assert idle["lines"] == [11, 13]
    assert {f["rule"] for f in d["failures"]} >= {"sec.snmp_community_acl", "sec.snmp_community_read_only"}
    assert d["summary"]["has_errors"] and res["summary"]["has_errors"]
    assert res["texts"]["baseline.sec.telnet_disabled.message"]["pt-BR"]


# ---------- 样本基准（每条结论都人工核对过，误报应改规则） ----------

BASIC = {
    "huawei-atn-v800r023/atn-access-01.cfg": (95, ["syslog_server"]),
    "cisco-iosxe-asr920-synthetic/pe-asr920-01.cfg": (
        31,
        ["aaa_enabled", "aaa_server", "ntp_server", "ssh_enabled", "syslog_server"],
    ),
    "cisco-iosxe-asr920-synthetic/pe-asr920-02-igp-mgmt.cfg": (100, []),
    "huawei-atn-v800r025-synthetic/atn-igp-mgmt-01.cfg": (89, ["aaa_server", "vty_acl"]),
    "cisco-iosxe-asr920-synthetic/pe-asr920-03-mpls-l2vpn-acl.cfg": (
        63,
        ["aaa_enabled", "aaa_server", "ntp_server", "ssh_v2", "syslog_server", "vty_auth_aaa"],
    ),
    "huawei-atn-v800r025-synthetic/atn-mpls-l2vpn-acl-01.cfg": (
        66,
        ["aaa_enabled", "aaa_server", "ntp_server", "ssh_enabled", "syslog_server"],
    ),
    "cisco-ios-public/batfish_hybrid-cloud_lhr-border-02.txt": (
        52,
        [
            "aaa_server",
            "line_idle_timeout",
            "ntp_server",
            "syslog_server",
            "telnet_disabled",
            "vty_acl",
            "vty_ssh_only",
        ],
    ),
}
STRICT = {
    "huawei-atn-v800r023/atn-access-01.cfg": (
        81,
        ["line_idle_timeout", "ntp_server_key", "snmp_v3_only", "ssh_strong_algorithms", "syslog_server"],
    ),
    "cisco-iosxe-asr920-synthetic/pe-asr920-02-igp-mgmt.cfg": (
        91,
        ["line_idle_timeout", "local_user_top_level", "snmp_v3_only"],
    ),
    "huawei-atn-v800r025-synthetic/atn-igp-mgmt-01.cfg": (87, ["aaa_server", "ntp_server_key", "vty_acl"]),
}


@pytest.mark.parametrize(("profile", "table"), [("basic", BASIC), ("strict", STRICT)])
def test_samples_benchmark(kb: KnowledgeBase, bl: blmod.Baseline, profile: str, table: dict[str, Any]) -> None:
    graphs = [_sample(kb, rel) for rel in table]
    res = blmod.audit(graphs, bl, profile)
    for rel, d in zip(table, res["devices"], strict=True):
        score, fails = table[rel]
        got = sorted(k.removeprefix("sec.") for k, v in d["results"].items() if v == "fail")
        assert (d["score"], got) == (score, fails), rel


def test_atn_details(kb: KnowledgeBase, bl: blmod.Baseline) -> None:
    """现网 ATN：Telnet 已关闭、SSH 只允许 SSH 且有 ACL、团体字为脱敏别名且绑定 ACL；被锁定的用户不检查服务类型。"""
    d = blmod.audit([_sample(kb, "huawei-atn-v800r023/atn-access-01.cfg")], bl, "strict")["devices"][0]
    assert d["results"]["sec.local_user_secure_service"] == "na"
    ntp = [f for f in d["failures"] if f["rule"] == "sec.ntp_server_key"]
    assert [f["lines"] for f in ntp] == [[33], [34]]
    assert ntp[0]["remedy"] == ["ntp-service unicast-server 10.0.179.30 authentication-keyid 1"]
    snmp = next(f for f in d["failures"] if f["rule"] == "sec.snmp_v3_only")
    assert snmp["lines"] == [2180, 2182, 2183, 2184, 2188, 2190, 2191]


def test_baseline_report(kb: KnowledgeBase, bl: blmod.Baseline) -> None:
    graphs = [_sample(kb, rel) for rel in list(BASIC)[:2]]
    res = blmod.audit(graphs, bl, "basic")
    html = baseline_report(res, "zh-CN", "html", kb_version="t").content
    assert "安全基线报告" in html and "设备 × 规则" in html and "info-center loghost &lt;IP&gt;" in html
    assert "由透网 LucidMesh 生成。结论由代码在配置图上按基线规则计算。" in html
    rep = baseline_report(res, "en", "md")
    assert rep.filename == "baseline-basic-2-devices.en.md"
    assert "| `sec.syslog_server` Log server configured | Warning | ✗ | ✗ |" in rep.content
    assert "`ip ssh version 2`<br>`crypto key generate rsa modulus 3072`" in rep.content
