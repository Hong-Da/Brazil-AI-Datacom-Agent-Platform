"""翻译自定义规则（REQ-032）：名称映射（精确 / 通配符 / 正则捕获组 / 大小写 / 顺序）、命名规范（整理动作、截断、告警）、
端口映射（精确 / 模式偏移与范围 / 按类型速率、子接口跟随）、在图上改名（引用同步、编号、冲突）、翻译与迁移的接入、规则集读写。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmesh.core import analysis, migration, naming, translate
from lmesh.core import graph as graphmod

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
CISCO = "cisco-iosxe-asr920-17.15"
HUAWEI = "huawei-atn-v800r025"
L3VPN = (KB_ROOT / "samples" / "translate" / "atn-l3vpn-synth.cfg").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


def graph(kb, text: str, profile: str):  # type: ignore[no-untyped-def]
    res = analysis.parse_text(text, kb, profile)
    return graphmod.build(res.parsed, kb, res.profile, "dev")


def rules(**sections) -> naming.RuleSet:  # type: ignore[no-untyped-def]
    return naming.parse({"id": "t", **sections})


# ---------- 名称映射 ----------


def test_exact_and_ignore_case() -> None:
    rs = rules(names=[{"type": "vrf.instance", "match": "exact", "from": "ran", "to": "RAN-NEW", "ignore_case": True}])
    assert naming.map_name(rs, "vrf.instance", "RAN") == ("RAN-NEW", 0)
    assert naming.map_name(rs, "rp.policy", "RAN") == ("RAN", None)  # 类型不同不命中
    strict = rules(names=[{"match": "exact", "from": "ran", "to": "X"}])
    assert naming.map_name(strict, "vrf.instance", "RAN") == ("RAN", None)


def test_wildcard_captures() -> None:
    rs = rules(names=[{"match": "wildcard", "from": "RAN-*-?", "to": "VRF_{1}_{2}"}])
    assert naming.map_name(rs, "vrf.instance", "RAN-4G-A") == ("VRF_4G_A", 0)
    assert naming.map_name(rs, "vrf.instance", "XRAN-4G-A")[1] is None  # 整串匹配


def test_regex_groups_named_backslash_and_whole() -> None:
    rs = rules(
        names=[
            {"match": "regex", "from": r"(?P<base>\w+)-(IN|OUT)", "to": r"RP_{base}_\2"},
            {"match": "regex", "from": "tmp.*", "to": "{0}_OLD", "ignore_case": True},
        ]
    )
    assert naming.map_name(rs, "rp.policy", "BGP-IN") == ("RP_BGP_IN", 0)
    assert naming.map_name(rs, "rp.policy", "TMP1") == ("TMP1_OLD", 1)


def test_order_first_hit_and_disabled() -> None:
    rs = rules(
        names=[
            {"match": "exact", "from": "A", "to": "SKIPPED", "enabled": False},
            {"match": "wildcard", "from": "A*", "to": "FIRST"},
            {"match": "exact", "from": "A", "to": "SECOND"},
        ]
    )
    assert naming.map_name(rs, "vrf.instance", "A") == ("FIRST", 1)


def test_parse_issues() -> None:
    with pytest.raises(naming.RulesError) as ei:
        naming.parse(
            {
                "id": "bad id",
                "names": [
                    {"match": "regex", "from": "(", "to": "x"},
                    {"match": "wildcard", "from": "A*", "to": "{2}"},
                    {"match": "fuzzy", "from": "a", "to": "b"},
                ],
                "ports": [
                    {"match": "pattern", "from": "Gi0/0/1", "to": "x"},
                    {"match": "exact", "from": None, "to": "x"},
                ],
                "naming": [{"type": "nope.type", "max_length": 0}],
            },
            analysis.load_kb(KB_ROOT),
        )
    keys = {(i["where"], i["key"]) for i in ei.value.issues}
    assert ("id", "naming.issue.id") in keys
    assert ("names[0].from", "naming.issue.regex") in keys
    assert ("names[1].to", "naming.issue.group") in keys
    assert ("names[2].match", "naming.issue.match") in keys
    assert ("ports[0].from", "naming.issue.pattern_n") in keys
    assert ("ports[1].from", "naming.issue.empty") in keys  # YAML 的 NULL 读成空值
    assert ("naming[0].type", "naming.issue.type") in keys
    assert ("naming[0].max_length", "naming.issue.max_length") in keys


# ---------- 命名规范 ----------


def test_naming_fix_actions_and_truncate() -> None:
    rs = rules(
        naming=[
            {
                "type": "rp.policy",
                "pattern": "RP_[A-Z0-9_]+_V",
                "fix": True,
                "case": "upper",
                "prefix": "RP_",
                "suffix": "_V",
                "replace": [{"from": "[-.]", "to": "_"}],
                "max_length": 12,
            }
        ]
    )
    r = naming.resolve_name(rs, "rp.policy", "export-loopback.1")
    assert r["fixes"] == ["replace", "upper", "prefix", "suffix", "truncate"]
    assert r["result"] == "RP_EXPORT__V" and len(r["result"]) == 12  # 截断时保留后缀
    assert r["problems"] == [] and r["limit_source"] == "rule"


def test_naming_warnings_without_fix_and_knowledge_limit() -> None:
    rs = rules(naming=[{"type": "vrf.instance", "pattern": "[A-Z]+"}])
    r = naming.resolve_name(rs, "vrf.instance", "ran-4g-long", {"vrf.instance": 5})
    assert r["result"] == "ran-4g-long" and r["fixes"] == []
    assert [p["problem"] for p in r["problems"]] == ["pattern", "length"]
    assert r["max_length"] == 5 and r["limit_source"] == "knowledge"
    fixed = rules(naming=[{"type": "vrf.instance", "fix": True}])
    assert naming.resolve_name(fixed, "vrf.instance", "ABCDEFGH", {"vrf.instance": 5})["result"] == "ABCDE"


# ---------- 端口映射 ----------


def test_port_exact_pattern_type() -> None:
    rs = rules(
        ports=[
            {"match": "exact", "from": "GE0/2/0", "to": "TenGigabitEthernet0/0/24"},
            {"match": "pattern", "from": "GE0/2/{n}", "to": "GigabitEthernet0/0/{n+1}", "range": [1, 7]},
            {"match": "type", "from": "100GE", "to": "HundredGigE"},
            {"match": "type", "from": "GigabitEthernet", "speed": 1, "to": "Gi9/{n-1}"},
        ]
    )
    assert naming.map_port(rs, "GigabitEthernet0/2/0") == ("TenGigabitEthernet0/0/24", 0)  # 统一写法后精确匹配
    assert naming.map_port(rs, "GigabitEthernet0/2/3") == ("GigabitEthernet0/0/4", 1)
    assert naming.map_port(rs, "100GE0/2/24") == ("HundredGigE0/2/24", 2)
    assert naming.map_port(rs, "GigabitEthernet0/2/9") == ("Gi9/8", 3)  # 超出模式的范围，落到按类型
    assert naming.map_port(rs, "Eth-Trunk1") == ("Eth-Trunk1", None)
    t = naming.test_input(rs, "port", "GigabitEthernet0/2/3.101")
    assert t["result"] == "GigabitEthernet0/0/4.101" and t["rule"] == 1  # 子接口随主接口


# ---------- 在图上改名 ----------


def _rs_l3vpn() -> naming.RuleSet:
    return rules(
        names=[
            {"type": "vrf.instance", "match": "wildcard", "from": "RA*", "to": "VRF_RA{1}"},
            {"type": "rp.policy", "match": "regex", "from": r"(\w+)-(\w+)", "to": "RP_{1}_{2}"},
        ],
        ports=[{"match": "pattern", "from": "GE0/2/{n}", "to": "GigabitEthernet0/0/{n+1}", "range": [0, 1]}],
    )


def test_run_renames_object_and_all_references(kb) -> None:  # type: ignore[no-untyped-def]
    g = graph(kb, L3VPN, HUAWEI)
    before = set(g.nodes)
    g2, pmap, rep = naming.run(g, kb, _rs_l3vpn(), CISCO)
    assert set(g.nodes) == before  # 源图不变
    vrf = next(r for r in rep["renames"] if r["type"] == "vrf.instance")
    assert (vrf["from"], vrf["to"], vrf["applied"]) == ("RAN", "VRF_RAN", True)
    assert vrf["rule"] == {"section": "names", "index": 0}
    schemas = {x["schema"] for x in vrf["ref_nodes"]}
    assert {"interface.vrf", "static.route", "bgp.af"} <= schemas  # 属性取值与复合键里的引用都改
    assert "vrf.instance[VRF_RAN]" in g2 and "vrf.instance[RAN]" not in g2
    assert g2.nodes["interface[GigabitEthernet0/2/1.101]/vrf"]["value"] == "VRF_RAN"
    assert "bgp.instance[65000]/bgp.af[afi=ipv4,vrf=VRF_RAN]" in g2
    assert not any("vrf=RAN" in n for n in g2.nodes)
    pol = {r["from"]: r for r in rep["renames"] if r["type"] == "rp.policy"}
    assert pol["EXPORT-LOOPBACK"]["to"] == "RP_EXPORT_LOOPBACK" and pol["EXPORT-LOOPBACK"]["refs"] == 1
    assert "rp.policy[RP_EXPORT_LOOPBACK]/node[10]" in g2  # 子树编号随对象改
    stmt_nodes = {n for st in g2.graph["statements"] for n in st.nodes}
    assert "vrf.instance[VRF_RAN]" in stmt_nodes and "vrf.instance[RAN]" not in stmt_nodes
    assert pmap == {"GigabitEthernet0/2/0": "GigabitEthernet0/0/1", "GigabitEthernet0/2/1": "GigabitEthernet0/0/2"}
    port = next(p for p in rep["ports"] if p["from"] == "GigabitEthernet0/2/1")
    assert port["subinterfaces"] == 1
    assert rep["summary"]["renamed"] == 3 and rep["summary"]["conflicts"] == 0


def test_conflicts_many_to_one_exists_target(kb) -> None:  # type: ignore[no-untyped-def]
    g = graph(kb, L3VPN, HUAWEI)
    rs = rules(names=[{"type": "vrf.instance", "match": "wildcard", "from": "*", "to": "SAME"}])
    _, _, rep = naming.run(g, kb, rs, CISCO)
    assert [c["kind"] for c in rep["conflicts"]] == ["many_to_one"]
    assert rep["conflicts"][0]["from"] == ["OAM", "RAN"]
    assert not any(r["applied"] for r in rep["renames"])  # 不静默合并
    exists = rules(names=[{"type": "vrf.instance", "match": "exact", "from": "RAN", "to": "OAM"}])
    _, _, rep2 = naming.run(g, kb, exists, CISCO)
    assert rep2["conflicts"][0]["kind"] == "exists"
    tg = graph(kb, "vrf definition NEW-RAN\n rd 1:1\n!\nend\n", CISCO)
    tgt = rules(names=[{"type": "vrf.instance", "match": "exact", "from": "RAN", "to": "NEW-RAN"}])
    g3, _, rep3 = naming.run(g, kb, tgt, CISCO, tg)
    assert rep3["conflicts"][0]["kind"] == "target_exists" and "vrf.instance[RAN]" in g3
    ports = rules(
        ports=[
            {"match": "exact", "from": "GE0/2/0", "to": "GigabitEthernet0/0/9"},
            {"match": "exact", "from": "GE0/2/1", "to": "Gi0/0/9"},
        ]
    )
    _, pmap, rep4 = naming.run(g, kb, ports, CISCO)
    assert pmap == {} and rep4["conflicts"][0]["kind"] == "port_many_to_one"


def test_gap_when_limit_unknown_and_text_refs(kb) -> None:  # type: ignore[no-untyped-def]
    g = graph(kb, L3VPN + "\nsnmp-agent trap source-route-policy IMPORT-RAN\n", HUAWEI)
    rs = rules(
        names=[{"type": "rp.policy", "match": "exact", "from": "IMPORT-RAN", "to": "IMP"}],
        naming=[{"type": "rp.policy", "pattern": "[A-Z]+"}],
    )
    _, _, rep = naming.run(g, kb, rs, CISCO)
    if not naming.name_limits(kb, "cisco-iosxe").get("rp.policy"):
        assert {"kind": "name_limit_unknown", "type": "rp.policy", "family": "cisco-iosxe"} in rep["gaps"]
    assert any(x["name"] == "IMPORT-RAN" for x in rep["text_refs"])  # 未识别行里的旧名列出，不改


# ---------- 接入翻译、迁移、批量生成 ----------


def test_translate_without_rules_unchanged(kb) -> None:  # type: ignore[no-untyped-def]
    g = graph(kb, L3VPN, HUAWEI)
    base = translate.translate(g, kb, HUAWEI, CISCO, {"LoopBack0": "Loopback0"})
    assert "naming" not in base
    empty = translate.translate(g, kb, HUAWEI, CISCO, {"LoopBack0": "Loopback0"}, rules=rules())
    assert empty["text"] == base["text"] and empty["warnings"] == base["warnings"]
    assert empty["naming"]["summary"]["renamed"] == 0


def test_translate_with_rules(kb) -> None:  # type: ignore[no-untyped-def]
    g = graph(kb, L3VPN, HUAWEI)
    r = translate.translate(g, kb, HUAWEI, CISCO, {"LoopBack0": "Loopback0"}, rules=_rs_l3vpn())
    assert r["verify"]["unexplained"] == 0
    assert "vrf definition VRF_RAN" in r["text"] and "ip route vrf VRF_RAN" in r["text"]
    assert "route-map RP_EXPORT_LOOPBACK" in r["text"] and "route-map RP_EXPORT_LOOPBACK out" in r["text"]
    assert "interface GigabitEthernet0/0/2.101" in r["text"] and "vrf definition RAN\n" not in r["text"]
    assert r["naming"]["summary"]["renamed"] == 3
    # 显式给出的接口映射优先于端口规则
    r2 = translate.translate(g, kb, HUAWEI, CISCO, {"GE0/2/1": "GigabitEthernet0/0/9"}, rules=_rs_l3vpn(), verify=False)
    assert "interface GigabitEthernet0/0/9.101" in r2["text"]


def test_builtin_rule_sets_translate_samples(kb) -> None:  # type: ignore[no-untyped-def]
    text = (KB_ROOT / "samples" / "cisco-iosxe-asr920-synthetic" / "pe-asr920-01.cfg").read_text(encoding="utf-8")
    g = graph(kb, text, CISCO)
    rs = naming.load(KB_ROOT, "asr920-to-atn", kb)
    assert rs.builtin
    r = translate.translate(g, kb, CISCO, HUAWEI, rules=rs)
    assert r["verify"]["unexplained"] == 0
    assert "interface Eth-Trunk1" in r["text"] and "route-policy RP_EXPORT-LOOPBACK" in r["text"]
    naming.load(KB_ROOT, "atn-to-asr920", kb)  # 另一个内置规则集能通过校验


def test_migrate_with_rules(kb) -> None:  # type: ignore[no-untyped-def]
    g = graph(kb, L3VPN, HUAWEI)
    rs = _rs_l3vpn()
    r = migration.migrate(g, kb, HUAWEI, CISCO, {"GE0/2/0": "GigabitEthernet0/0/5"}, rules=rs, verify=False)
    targets = {m["source"]: m["target"] for m in r["interface_map"]}
    src = {k.lower(): v for k, v in targets.items()}
    assert src["gigabitethernet0/2/0"] == "GigabitEthernet0/0/5"  # 用户映射优先
    assert src["gigabitethernet0/2/1"] == "GigabitEthernet0/0/2"  # 规则其次
    assert "vrf definition VRF_RAN" in r["text"] and r["naming"]["summary"]["renamed"] == 3
    assert "naming" not in migration.migrate(g, kb, HUAWEI, CISCO, verify=False)


def test_template_generate_rules_need_canon(kb) -> None:  # type: ignore[no-untyped-def]
    from lmesh.core import template as tmod
    from lmesh.core import template_gen

    t = tmod.load(KB_ROOT, "huawei-atn-l3vpn-subif", kb)
    with pytest.raises(tmod.TemplateError) as ei:
        template_gen.generate(t, [{"device": "x"}], kb, "text", None, True, rules())
    assert ei.value.key == "template.rules_need_canon"


# ---------- 规则集读写 ----------


def test_save_load_delete_keeps_comments(tmp_root: Path, kb) -> None:  # type: ignore[no-untyped-def]
    root = tmp_root / "knowledge"
    assert {i["id"] for i in naming.list_sets(root, kb)} >= {"atn-to-asr920", "asr920-to-atn"}
    with pytest.raises(naming.RulesError) as ei:
        naming.save(root, "atn-to-asr920", {"names": []}, kb)
    assert ei.value.kind == "readonly"
    src = "# 我的规则\nid: mine\nnames:\n  # 第一条\n  - {match: exact, from: A, to: B}\n"
    naming.save(root, "mine", src, kb)
    path = tmp_root / "data" / "translate-rules" / "mine.yaml"
    assert path.read_text(encoding="utf-8") == src
    data = naming.load(root, "mine", kb).as_dict()
    data["names"].append({"match": "wildcard", "from": "X*", "to": "Y{1}"})
    naming.save(root, "mine", data, kb)
    text = path.read_text(encoding="utf-8")
    assert "# 我的规则" in text and "# 第一条" in text and "Y{1}" in text  # 合并写回保留注释
    assert len(naming.load(root, "mine", kb).names) == 2
    with pytest.raises(naming.RulesError):
        naming.save(root, "mine", src, kb, overwrite=False)
    naming.delete(root, "mine")
    assert not path.exists()
    with pytest.raises(naming.RulesError) as e2:
        naming.delete(root, "atn-to-asr920")
    assert e2.value.kind == "readonly"
