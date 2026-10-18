"""配置检查与冗余清理：悬空引用、孤儿与级联孤儿、互斥、规则约束、规则文件校验、清理脚本（华为与 Cisco 逐字）、删除后验证、样本基准。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lmesh.core import analysis, checks, cleanup
from lmesh.core import graph as graphmod
from lmesh.core import rules as rulesmod
from lmesh.core.kb import KnowledgeBase
from lmesh.core.kb.model import Card

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parent.parent.parent
KB_ROOT = ROOT / "knowledge"
CHECK_INPUTS = ROOT / "tests" / "inputs" / "configs" / "check"
SAMPLES = KB_ROOT / "samples"


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return analysis.load_kb(KB_ROOT)


@pytest.fixture(scope="module")
def rules(kb: KnowledgeBase) -> list[rulesmod.Rule]:
    return rulesmod.load_dir(kb, KB_ROOT / "rules")


def _graph(kb: KnowledgeBase, path: Path) -> Any:
    res = analysis.parse_text(path.read_text(encoding="utf-8"), kb)
    return graphmod.build(res.parsed, kb, res.profile, path.stem)


def _pairs(res: dict[str, Any]) -> list[tuple[str, str]]:
    return sorted((f["rule"], f["node"]) for f in res["findings"])


# ---------- 各类检查 ----------

HW_EXPECTED = [
    ("bgp.peer.remote_as_missing", "bgp.instance[65000]/bgp.peer[192.0.2.2]"),
    ("dep.mutex", "interface[GigabitEthernet0/2/1]/l2"),
    ("interface.lag_member_with_ip", "interface[GigabitEthernet0/2/3]"),
    ("interface.vrf_without_ip", "interface[GigabitEthernet0/2/2]"),
    ("ref.dangling", "bgp.instance[65000]/bgp.af[afi=ipv4,vrf=]/peer[192.0.2.6]/import_policy"),
    ("ref.orphan", "bgp.instance[65000]/bgp.peer_group[SPARE]"),
    ("ref.orphan", "bridge_domain[300]"),
    ("ref.orphan", "rp.policy[UNUSED-POLICY]"),
    ("ref.orphan", "vrf.instance[UNUSED-VRF]"),
    ("ref.orphan_cascade", "rp.prefix_list[ONLY-UNUSED]"),
    ("ref.orphan_unsure", "rp.policy[NH-POLICY]"),
    ("vrf.rd_without_rt", "vrf.instance[NO-RT]/af[ipv4]"),
    ("vrf.rt_without_rd", "vrf.instance[NO-RD]/af[ipv4]"),
]

CISCO_EXPECTED = [
    ("bgp.peer.remote_as_missing", "bgp.instance[64512]/bgp.peer[192.0.2.2]"),
    ("interface.lag_member_with_ip", "interface[GigabitEthernet0/0/2]"),
    ("interface.vrf_without_ip", "interface[GigabitEthernet0/0/1]"),
    ("ref.dangling", "bgp.instance[64512]/bgp.af[afi=ipv4,vrf=]/peer[192.0.2.6]/import_policy"),
    ("ref.dangling_unsure", "rp.policy[USED-MAP]/node[20]/match_prefix_list"),
    ("ref.orphan", "bgp.instance[64512]/bgp.peer_group[SPARE]"),
    ("ref.orphan", "rp.community_list[UNUSED-COMM]"),
    ("ref.orphan", "rp.policy[UNUSED-MAP]"),
    ("ref.orphan", "vrf.instance[UNUSED-VRF]"),
    ("ref.orphan_cascade", "rp.prefix_list[ONLY-UNUSED]"),
    ("vrf.rd_without_rt", "vrf.instance[NO-RT]/af[ipv4]"),
]


def test_huawei_findings(kb: KnowledgeBase, rules: list[rulesmod.Rule]) -> None:
    res = checks.check(_graph(kb, CHECK_INPUTS / "huawei-issues.cfg"), kb, rules)
    assert _pairs(res) == sorted(HW_EXPECTED)
    s = res["summary"]
    assert s["by_severity"] == {"error": 4, "warning": 8, "info": 1} and s["has_errors"]
    assert s["by_domain"] == {"bgp": 3, "interface": 4, "routing-policy": 3, "vrf": 3}
    assert s["by_rule"]["ref.orphan"] == 4
    by = {(f["rule"], f["node"]): f for f in res["findings"]}
    dang = by[("ref.dangling", HW_EXPECTED[4][1])]
    assert dang["lines"] == [52] and dang["severity"] == "error" and dang["domain"] == "bgp"
    assert dang["message"]["params"]["referrer"] == "bgp.instance[65000]/bgp.af[afi=ipv4,vrf=]/peer[192.0.2.6]"
    assert dang["message"]["params"]["value"] == "MISSING-POLICY"
    # 级联孤儿：只被孤儿策略引用的前缀列表；SHARED 还被在用的策略引用，不算
    casc = by[("ref.orphan_cascade", "rp.prefix_list[ONLY-UNUSED]")]
    assert casc["message"]["params"]["via"] == "rp.policy[UNUSED-POLICY]" and casc["lines"] == [59]
    assert by[("ref.orphan_unsure", "rp.policy[NH-POLICY]")]["lines"] == [54, 75]
    assert (
        by[("dep.mutex", "interface[GigabitEthernet0/2/1]/l2")]["nodes"][1]
        == "interface[GigabitEthernet0/2/1]/ipv4[192.0.2.1]"
    )
    # 以键使用的对象不算孤儿：只在 BGP 地址族中使用的 VRF、有 Vbdif 接口的桥域
    nodes = {n for _, n in _pairs(res)}
    assert "vrf.instance[BGP-ONLY]" not in nodes and "bridge_domain[400]" not in nodes
    # 规则文案随结果给出三种语言
    rk = by[("vrf.rd_without_rt", "vrf.instance[NO-RT]/af[ipv4]")]["message"]["key"]
    assert set(res["texts"][rk]) == {"zh-CN", "en", "pt-BR"}


def test_cisco_findings(kb: KnowledgeBase, rules: list[rulesmod.Rule]) -> None:
    res = checks.check(_graph(kb, CHECK_INPUTS / "cisco-issues.cfg"), kb, rules)
    assert _pairs(res) == sorted(CISCO_EXPECTED)
    by = {(f["rule"], f["node"]): f for f in res["findings"]}
    # 引用的前缀列表只在未映射的命令（description）里出现：降为 warning 并给出行号
    unsure = by[("ref.dangling_unsure", "rp.policy[USED-MAP]/node[20]/match_prefix_list")]
    assert unsure["severity"] == "warning" and unsure["message"]["params"]["mentions"] == "40"


def test_filters_and_text(kb: KnowledgeBase, rules: list[rulesmod.Rule]) -> None:
    g = _graph(kb, CHECK_INPUTS / "huawei-issues.cfg")
    only_err = checks.check(g, kb, rules, severity="error")
    assert {f["severity"] for f in only_err["findings"]} == {"error"} and only_err["summary"]["total"] == 4
    assert only_err["summary"]["unfiltered"] == 13
    vrf = checks.check(g, kb, rules, domain="vrf")
    assert {f["domain"] for f in vrf["findings"]} == {"vrf"} and vrf["summary"]["total"] == 3
    f = next(x for x in vrf["findings"] if x["rule"] == "ref.orphan")
    assert checks.render_text(f["message"], "en", vrf["texts"]) == "vrf.instance UNUSED-VRF is not referenced anywhere"
    r = next(x for x in vrf["findings"] if x["rule"] == "vrf.rt_without_rd")
    assert checks.render_text(r["message"], "pt-BR", vrf["texts"]).startswith("A família de endereços da VRF")


def test_implicit_object_not_dangling(kb: KnowledgeBase, rules: list[rulesmod.Rule]) -> None:
    """ASR 920 的业务实例引用的桥域由 Profile 声明为隐式对象：不算悬空，也不算孤儿。"""
    g = _graph(kb, SAMPLES / "cisco-iosxe-asr920-synthetic" / "pe-asr920-01.cfg")
    assert any(d.get("origin") == "derived" for _, d in g.nodes(data=True))
    res = checks.check(g, kb, rules)
    assert not [f for f in res["findings"] if f["rule"].startswith("ref.dangling") or "bridge_domain" in f["node"]]


# ---------- 样本基准（发现均已人工确认是真问题，见 docs/project-spec.md） ----------


def test_sample_baseline_atn(kb: KnowledgeBase, rules: list[rulesmod.Rule]) -> None:
    res = checks.check(_graph(kb, SAMPLES / "huawei-atn-v800r023" / "atn-access-01.cfg"), kb, rules)
    # 桥域 1500：两个 .1500 二层子接口都没有加入它；VERIFICA-NEXTHOP 被 nexthop recursive-lookup 引用（已映射），不是孤儿
    # ACL_MCAST_SSM（0.3.0 起 ACL 是功能域）只被范围外的 pim ssm-policy 使用：降级为 unsure，不进清理脚本
    # M4-2 起 QoS 进入功能域：7 个流策略、7 个 QoS 模板没有接口应用（已在原文中逐个核对），它们独占的流分类 / 流行为 /
    # 流队列按级联孤儿报出
    pairs = sorted(_pairs(res))
    assert [x for x in pairs if not x[1].startswith("qos.")] == [
        ("ref.orphan", "bridge_domain[1500]"),
        ("ref.orphan_unsure", "acl.instance[ACL_MCAST_SSM]"),
    ]
    qos = [x for x in pairs if x[1].startswith("qos.")]
    assert sum(1 for r, n in qos if r == "ref.orphan" and n.startswith("qos.policy[")) == 7
    assert sum(1 for r, n in qos if r == "ref.orphan" and n.startswith("qos.profile[")) == 7
    assert ("ref.orphan", "qos.policy[TC20_VOIP_IN]") in qos
    clean = cleanup.cleanup(_graph(kb, SAMPLES / "huawei-atn-v800r023" / "atn-access-01.cfg"), kb)
    texts = [c["text"] for c in clean["commands"]]
    assert "undo bridge-domain 1500" in texts and clean["verify"]["ok"]
    # 先删流策略，再删它独占的流分类 / 流行为
    assert texts.index("undo traffic policy TC20_VOIP_IN") < texts.index("undo traffic classifier VOIP_RT")
    assert [s["node"] for s in clean["skipped"]] == ["acl.instance[ACL_MCAST_SSM]"]  # maybe_referenced


def test_sample_baseline_asr920(kb: KnowledgeBase, rules: list[rulesmod.Rule]) -> None:
    g = _graph(kb, SAMPLES / "cisco-iosxe-asr920-synthetic" / "pe-asr920-01.cfg")
    res = checks.check(g, kb, rules)
    # RAN-COMM：定义了团体属性列表，但 route-map 只 set community，没有 match
    assert _pairs(res) == [("ref.orphan", "rp.community_list[RAN-COMM]")]
    clean = cleanup.cleanup(g, kb)
    assert [c["text"] for c in clean["commands"]] == ["no ip community-list standard RAN-COMM"]
    assert clean["verify"]["ok"]


# ---------- 清理脚本 ----------

HW_SCRIPT = """! lmesh cleanup: huawei-issues (huawei-atn-v800r023), 6 command(s)
! [1] vrf.instance[UNUSED-VRF] @13
undo ip vpn-instance UNUSED-VRF
! [2] bridge_domain[300] @23
undo bridge-domain 300
! [3] bgp.instance[65000]/bgp.peer_group[SPARE] @47
bgp 65000
 undo group SPARE
quit
! [4] rp.policy[UNUSED-POLICY] @63
undo route-policy UNUSED-POLICY node 10
! [5] rp.policy[UNUSED-POLICY] @66
undo route-policy UNUSED-POLICY node 20
! [6] rp.prefix_list[ONLY-UNUSED] @59
undo ip ip-prefix ONLY-UNUSED index 10
"""

CISCO_SCRIPT = """! lmesh cleanup: cisco-issues (cisco-iosxe-asr920-17.15), 6 command(s)
! [1] vrf.instance[UNUSED-VRF] @11
no vrf definition UNUSED-VRF
! [2] bgp.instance[64512]/bgp.peer_group[SPARE] @27
router bgp 64512
 no neighbor SPARE peer-group
exit
! [3] rp.community_list[UNUSED-COMM] @41
no ip community-list standard UNUSED-COMM
! [4] rp.policy[UNUSED-MAP] @43
no route-map UNUSED-MAP permit 10
! [5] rp.policy[UNUSED-MAP] @46
no route-map UNUSED-MAP deny 20
! [6] rp.prefix_list[ONLY-UNUSED] @38
no ip prefix-list ONLY-UNUSED seq 5 permit 10.0.0.0/8
"""


def test_cleanup_huawei_script(kb: KnowledgeBase) -> None:
    res = cleanup.cleanup(_graph(kb, CHECK_INPUTS / "huawei-issues.cfg"), kb)
    assert res["script"] == HW_SCRIPT
    assert res["fallbacks"] == 0
    objs = {o["node"]: o for o in res["objects"]}
    assert objs["rp.prefix_list[ONLY-UNUSED]"]["reason"] == "cascade"
    assert objs["rp.prefix_list[ONLY-UNUSED]"]["via"] == ["rp.policy[UNUSED-POLICY]"]
    assert objs["rp.policy[UNUSED-POLICY]"]["lines"] == [63, 64, 66, 67]
    grp = next(c for c in res["commands"] if c["object"].endswith("peer_group[SPARE]"))
    assert grp["context"] == ["bgp 65000"] and grp["card"] == "huawei-vrp8.group.1" and grp["lines"] == [47]
    assert res["skipped"] == [{"node": "rp.policy[NH-POLICY]", "reason": "maybe_referenced", "lines": [54]}]


def test_cleanup_cisco_script(kb: KnowledgeBase) -> None:
    res = cleanup.cleanup(_graph(kb, CHECK_INPUTS / "cisco-issues.cfg"), kb)
    assert res["script"] == CISCO_SCRIPT
    # route-map 的取消语法已在修正文件中改为 no route-map 名称 permit|deny [序号]，不再兜底
    assert res["fallbacks"] == 0
    assert [c["fallback"] for c in res["commands"]] == [False] * 6


def test_cleanup_verify_no_new_dangling(kb: KnowledgeBase) -> None:
    """把删除脚本应用到图上（去掉这些对象及其子行）后重新建图：没有新的悬空引用，也没有剩下的孤儿。"""
    for name in ("huawei-issues.cfg", "cisco-issues.cfg"):
        g = _graph(kb, CHECK_INPUTS / name)
        res = cleanup.cleanup(g, kb)
        v = res["verify"]
        assert v["ok"] and v["new_dangling"] == [] and v["remaining_objects"] == [] and v["new_orphans"] == []
        assert v["dangling_after"] == v["dangling_before"]
        text = cleanup.removal_text(g, kb, [o["node"] for o in res["objects"]])
        assert "ONLY-UNUSED" not in text and "UNUSED-VRF" not in text


def test_verify_detects_wrong_order(kb: KnowledgeBase) -> None:
    """反例：只删被引用的前缀列表、不删引用它的策略，验证会报出新的悬空引用。"""
    g = _graph(kb, CHECK_INPUTS / "huawei-issues.cfg")
    v = cleanup.verify_removal(g, kb, ["rp.prefix_list[ONLY-UNUSED]"])
    assert not v["ok"]
    assert v["new_dangling"] == [
        {"referrer": "rp.policy[UNUSED-POLICY]/node[10]", "target_type": "rp.prefix_list", "value": "ONLY-UNUSED"}
    ]


def test_render_undo(kb: KnowledgeBase) -> None:
    g = _graph(kb, CHECK_INPUTS / "cisco-issues.cfg")
    lines = {st.line.no: st.line for st in g.graph["statements"]}
    # 多选一里有不带参数的分支（sequence-number），只能选原行出现过关键字的那一支
    card = kb.cards["cisco-iosxe.ip-prefix-list"]
    assert cleanup.render_undo(card, lines[39], "no") == ("no ip prefix-list SHARED seq 5 permit 10.1.0.0/16", False)
    # 命令卡没有取消语法：取消前缀 + 原命令
    bare = Card(id="x", family="cisco-iosxe", domain="d", syntax="x", view="system")
    assert cleanup.render_undo(bare, lines[39], "no") == ("no ip prefix-list SHARED seq 5 permit 10.1.0.0/16", True)


# ---------- 规则文件 ----------


def _rule(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "t.rule",
        "target": "interface",
        "assert": {"exists": "ipv4"},
        "severity": "warning",
        "title": {"zh-CN": "标题", "en": "Title", "pt-BR": "Título"},
        "message": {"zh-CN": "接口 {key}", "en": "Interface {key}", "pt-BR": "Interface {key}"},
        "suggestion": {"zh-CN": "建议", "en": "Fix", "pt-BR": "Corrigir"},
    }
    base.update(over)
    return base


def _codes(kb: KnowledgeBase, *rs: dict[str, Any]) -> list[tuple[str, str, str]]:
    with pytest.raises(rulesmod.RuleError) as e:
        rulesmod.parse_rules(kb, [("t.yaml", {"rules": list(rs)})])
    return [(i["rule"], i["field"], i["code"]) for i in e.value.issues]


def test_builtin_rule_file_valid(rules: list[rulesmod.Rule]) -> None:
    assert len(rules) >= 6 and all(r.title and r.message and r.suggestion for r in rules)
    assert {r.target for r in rules} >= {"bgp.peer", "interface", "vrf.instance.af", "rp.policy.node"}


def test_rule_validation_errors(kb: KnowledgeBase) -> None:
    assert _codes(kb, _rule(severity="fatal")) == [("t.rule", "severity", "rules.err.bad_severity")]
    assert _codes(kb, _rule(target="interface.mtu")) == [("t.rule", "target", "rules.err.unknown_target")]
    assert _codes(kb, _rule(**{"assert": {"exists": "ipv5"}})) == [("t.rule", "assert", "rules.err.path_unknown")]
    assert _codes(kb, _rule(**{"assert": {"exists": "mtu->x"}})) == [("t.rule", "assert", "rules.err.path_not_ref")]
    assert _codes(kb, _rule(**{"assert": {"exists": "mtu/x"}})) == [("t.rule", "assert", "rules.err.path_not_object")]
    assert _codes(kb, _rule(**{"assert": {"exists": "vrf/"}})) == [("t.rule", "assert", "rules.err.path_syntax")]
    assert _codes(kb, _rule(**{"assert": {"regex": "x"}})) == [("t.rule", "assert", "rules.err.bad_operator")]
    assert _codes(kb, _rule(**{"assert": {"count": {"path": "ipv4"}}})) == [("t.rule", "assert", "rules.err.cond_args")]
    assert _codes(kb, _rule(**{"assert": {"any": []}})) == [("t.rule", "assert", "rules.err.cond_list")]
    assert _codes(kb, _rule(**{"assert": {"exists": "ipv4", "not": {"exists": "vrf"}}})) == [
        ("t.rule", "assert", "rules.err.cond_shape")
    ]
    assert _codes(kb, _rule(message={"zh-CN": "x", "en": "x"})) == [("t.rule", "message", "rules.err.missing_lang")]
    assert _codes(kb, _rule(message={"zh-CN": "{foo}", "en": "x", "pt-BR": "x"})) == [
        ("t.rule", "message.zh-CN", "rules.err.placeholder")
    ]
    assert _codes(kb, _rule(), _rule()) == [("t.rule", "id", "rules.err.duplicate_id")]
    assert _codes(kb, _rule(id="Bad Id", extra=1)) == [
        ("Bad Id", "extra", "rules.err.unknown_field"),
        ("Bad Id", "id", "rules.err.bad_id"),
    ]
    nested = _rule(**{"assert": {"all": [{"exists": "ipv4"}, {"not": {"exists": "nope"}}]}})
    assert _codes(kb, nested) == [("t.rule", "assert.all[1].not", "rules.err.path_unknown")]


def test_rule_dir_yaml_error(kb: KnowledgeBase, tmp_path: Path) -> None:
    (tmp_path / "bad.yaml").write_text("rules: [\n  - id: x\n", encoding="utf-8")
    with pytest.raises(rulesmod.RuleError) as e:
        rulesmod.load_dir(kb, tmp_path)
    assert e.value.issues[0]["file"] == "bad.yaml" and e.value.issues[0]["code"] == "rules.err.yaml"
    assert rulesmod.load_dir(kb, tmp_path / "missing") == []


def test_evaluator_paths(kb: KnowledgeBase) -> None:
    """求值器：-> 取被引用对象、^ 取上级对象、count 的上下限、equals / in。"""
    g = _graph(kb, CHECK_INPUTS / "huawei-issues.cfg")
    rs = rulesmod.parse_rules(
        kb,
        [
            (
                "t.yaml",
                {
                    "rules": [
                        _rule(
                            id="empty-list",
                            target="rp.policy.node",
                            **{"when": {"exists": "match_prefix_list->"}},
                            **{"assert": {"count": {"path": "match_prefix_list->entry", "min": 1}}},
                        ),
                        _rule(
                            id="parent-up",
                            target="vrf.instance.af",
                            **{"assert": {"not": {"equals": {"path": "^", "value": "x"}}}},
                        ),
                        _rule(id="no-rt", target="vrf.instance.af", **{"assert": {"count": {"path": "rt", "max": 0}}}),
                        _rule(
                            id="group-type",
                            target="bgp.peer",
                            **{"when": {"exists": "group"}},
                            **{"assert": {"in": {"path": "group->type", "values": ["internal"]}}},
                        ),
                    ]
                },
            )
        ],
    )
    hits = sorted((r.id, n) for r, n in rulesmod.evaluate(g, rs))
    assert hits == [
        ("group-type", "bgp.instance[65000]/bgp.peer[192.0.2.2]"),
        ("no-rt", "vrf.instance[BGP-ONLY]/af[ipv4]"),
        ("no-rt", "vrf.instance[NO-RD]/af[ipv4]"),
        ("no-rt", "vrf.instance[UNUSED-VRF]/af[ipv4]"),
    ]
    # 去掉前缀列表的全部规则，空列表规则才会命中
    for n in [n for n in g.nodes if n.startswith("rp.prefix_list[SHARED]/entry")]:
        g.remove_node(n)
    hits = sorted((r.id, n) for r, n in rulesmod.evaluate(g, rs) if r.id == "empty-list")
    assert hits == [
        ("empty-list", "rp.policy[UNUSED-POLICY]/node[20]"),
        ("empty-list", "rp.policy[USED-POLICY]/node[10]"),
    ]


def test_list_rules(kb: KnowledgeBase) -> None:
    data = checks.list_rules(kb, KB_ROOT / "rules")
    assert data["builtin"] == len(checks.BUILTIN) and data["custom"] >= 6
    for r in data["rules"]:
        for f in ("title", "message", "suggestion"):
            assert all(r[f].get(lang) for lang in ("zh-CN", "en", "pt-BR")), (r["id"], f)
