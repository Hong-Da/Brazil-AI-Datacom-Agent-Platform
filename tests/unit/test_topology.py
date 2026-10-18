"""拓扑还原与跨设备一致性（M4-6）：样本网络的链路、推导依据、跨设备依赖边、故意放的不一致、规则文件校验与扩展格式。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lmesh.core import analysis, checks, consistency, topology
from lmesh.core import rules as rulesmod
from lmesh.core.kb import KnowledgeBase, read_yaml

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parent.parent.parent
KB_ROOT = ROOT / "knowledge"
TOPO = KB_ROOT / "samples" / "topology"
MANIFEST = read_yaml(TOPO / "manifest.yaml")


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return analysis.load_kb(KB_ROOT)


def _devices(kb: KnowledgeBase, files: list[str] | None = None) -> list[topology.Device]:
    names = files or [s["file"] for s in MANIFEST["samples"]]
    items = [{"name": f, "text": (TOPO / f).read_text(encoding="utf-8")} for f in names]
    return topology.from_texts(items, kb)


@pytest.fixture(scope="module")
def topo(kb: KnowledgeBase) -> topology.Topology:
    return topology.build(_devices(kb), kb)


@pytest.fixture(scope="module")
def ruleset(kb: KnowledgeBase) -> consistency.RuleSet:
    return consistency.load(kb, KB_ROOT / "rules" / consistency.RULES_FILE)


def _rules(kb: KnowledgeBase, text: str) -> consistency.RuleSet:
    from io import StringIO

    from ruamel.yaml import YAML

    return consistency.parse(kb, YAML(typ="safe").load(StringIO(text)), "test.yaml")


TEXTS = """
    title: {zh-CN: 标题, en: Title, pt-BR: Título}
    message: {zh-CN: "{a_device} {a_value}", en: "{a_device} {a_value}", pt-BR: "{a_device} {a_value}"}
    suggestion: {zh-CN: 建议, en: Fix, pt-BR: Corrija}
"""


def test_devices_named_by_hostname(topo: topology.Topology) -> None:
    assert [d.name for d in topo.devices] == ["TOPO-ATN-A1", "TOPO-ATN-A2", "TOPO-AGG-01", "TOPO-AGG-02", "TOPO-RR-01"]
    assert topo.facts["TOPO-AGG-01"].lsr_id == "10.255.1.21"  # Cisco：mpls ldp router-id Loopback0 → 接口地址
    assert topo.facts["TOPO-ATN-A1"].lsr_id == "10.255.1.11"  # 华为：mpls lsr-id


def test_link_counts_and_basis(topo: topology.Topology) -> None:
    data = topology.to_json(topo)
    assert data["summary"]["by_type"] == MANIFEST["expect_links"]
    assert data["summary"]["unresolved"] == 0 and data["summary"]["duplicates"] == 0
    by_id = {lk["id"]: lk for lk in data["links"]}
    p2p = by_id["subnet:TOPO-AGG-01:GigabitEthernet0/0/1~TOPO-ATN-A1:GigabitEthernet0/2/1"]
    assert p2p["p2p"] and p2p["confidence"] == "high" and p2p["segment"] == "10.10.11.0/30"
    assert p2p["basis"] == {
        "rule": "subnet.p2p",
        "a_node": "interface[GigabitEthernet0/0/1]/ipv4[10.10.11.2]/address",
        "b_node": "interface[GigabitEthernet0/2/1]/ipv4[10.10.11.1]/address",
        "detail": "10.10.11.2/30 ~ 10.10.11.1/30",
    }
    mask = by_id["subnet:TOPO-AGG-02:GigabitEthernet0/0/3~TOPO-RR-01:GigabitEthernet0/0/2"]
    assert mask["basis"]["rule"] == "subnet.mask_overlap" and mask["confidence"] == "low"
    # OSPF：华为靠进程下的 network 语句启用，区域统一成点分写法
    ospf = by_id["ospf:TOPO-AGG-02:GigabitEthernet0/0/1~TOPO-ATN-A2:GigabitEthernet0/2/1"]
    assert (ospf["a"]["facts"]["area"], ospf["b"]["facts"]["area"]) == ("0.0.0.20", "0.0.0.10")
    assert ospf["b"]["facts"]["via"] == "network" and ospf["confidence"] == "medium"
    # BGP：本端地址取 update-source / connect-interface，两端互相配置
    bgp = by_id["bgp:TOPO-ATN-A1:LoopBack0~TOPO-RR-01:Loopback0"]
    assert bgp["a"]["facts"]["afs"] == ["ipv4", "vpnv4"] and bgp["a"]["facts"]["update_source"] == "LoopBack0"
    assert bgp["a"]["node"] == "bgp.instance[64512]/bgp.peer[10.255.1.1]" and bgp["confidence"] == "high"
    # 伪线：对端 = LSR ID，华为 l2vc 与 Cisco xconnect 按 VC ID 配对
    pw = by_id["pw:TOPO-AGG-01:GigabitEthernet0/0/5~TOPO-ATN-A1:GigabitEthernet0/2/5.100#1100"]
    assert pw["basis"]["rule"] == "pw.peer_lsr_id_vc_id"
    assert pw["a"]["node"] == "interface[GigabitEthernet0/0/5]/access[100]/pw[primary]"
    bad_pw = by_id["pw:TOPO-AGG-02:GigabitEthernet0/0/5~TOPO-ATN-A2:GigabitEthernet0/2/5.200#1201"]
    assert bad_pw["basis"]["rule"] == "pw.peer_lsr_id_vc_mismatch" and bad_pw["confidence"] == "low"


def test_cross_device_edges_follow_schema_rules(topo: topology.Topology, kb: KnowledgeBase) -> None:
    rules = {f"{d.src}->{d.dst}" for d in kb.deps if d.kind == "cross_device"}
    edges = topo.cross_edges
    assert {e["rule"] for e in edges} <= rules
    got = {(e["rule"], e["src"]["device"], e["dst"]["device"]) for e in edges}
    assert ("bgp.peer->interface.ipv4.address", "TOPO-RR-01", "TOPO-ATN-A1") in got
    assert ("interface.access.pw.peer->mpls.global.lsr_id", "TOPO-AGG-01", "TOPO-ATN-A1") in got
    assert ("mpls.ldp.remote_peer.remote_ip->mpls.global.lsr_id", "TOPO-AGG-01", "TOPO-ATN-A1") in got
    assert ("bfd.session.peer->interface.ipv4.address", "TOPO-ATN-A1", "TOPO-ATN-A2") in got
    assert all(e["kind"] == "cross_device" and e["src"]["device"] != e["dst"]["device"] for e in edges)


def test_subset_reports_unresolved_peers(kb: KnowledgeBase) -> None:
    t = topology.build(_devices(kb, ["atn-a1.cfg", "atn-a2.cfg"]), kb)
    data = topology.to_json(t)
    assert data["summary"]["by_type"]["bgp"] == 0
    kinds = {(u["type"], u["device"], u["address"]) for u in data["unresolved"]}
    assert ("bgp", "TOPO-ATN-A1", "10.255.1.1") in kinds and ("pw", "TOPO-ATN-A1", "10.255.1.21") in kinds


def test_expected_findings(topo: topology.Topology, kb: KnowledgeBase, ruleset: consistency.RuleSet) -> None:
    res = consistency.check(topo, kb, ruleset)
    got = sorted((f["rule"], f["link"]) for f in res["findings"])
    want = sorted((e["rule"], e["link"]) for e in MANIFEST["expect_findings"])
    assert got == want
    assert res["summary"]["has_errors"] and res["summary"]["by_severity"] == {"error": 10, "warning": 3, "info": 0}
    assert {s["id"] for s in res["rules_skipped"]} == {"xd.vrrp.virtual_ip", "xd.vrrp.one_side"}  # 还没有 VRRP 功能域
    # 问题挂在链路上
    lk = next(
        x for x in res["links"] if x["id"] == "ospf:TOPO-ATN-A1:GigabitEthernet0/2/2~TOPO-ATN-A2:GigabitEthernet0/2/2"
    )
    assert lk["severity"] == "error" and len(lk["issues"]) == 2
    f = next(x for x in res["findings"] if x["rule"] == "xd.bgp.remote_as")
    assert f["ends"][0]["device"] == "TOPO-ATN-A2" and f["ends"][0]["value"] == "64513"
    assert f["ends"][0]["lines"] and f["node"] == "bgp.instance[64512]/bgp.peer[10.255.1.1]"
    text = checks.render_text(f["message"], "zh-CN", res["texts"])
    assert text == "TOPO-ATN-A2 把 TOPO-RR-01 配置为 AS 64513，但 TOPO-RR-01 的 AS 是 64512"
    assert res["summary"]["by_device"]["TOPO-ATN-A2"] == 6
    warn = consistency.check(topo, kb, ruleset, "error")
    assert warn["summary"]["total"] == 10 and warn["summary"]["unfiltered"] == 13


def test_duplicate_address(kb: KnowledgeBase, ruleset: consistency.RuleSet) -> None:
    a = (TOPO / "atn-a1.cfg").read_text(encoding="utf-8")
    b = a.replace("TOPO-ATN-A1", "TOPO-ATN-DUP")
    t = topology.build(topology.from_texts([{"name": "a", "text": a}, {"name": "b", "text": b}], kb), kb)
    res = consistency.check(t, kb, ruleset)
    dup = [f for f in res["findings"] if f["rule"] == "xd.ip_duplicate"]
    assert {f["ends"][0]["value"] for f in dup} == {"10.10.11.1", "10.10.12.1", "10.255.1.11"}
    assert "TOPO-ATN-DUP" in checks.render_text(dup[0]["message"], "en", res["texts"])


def test_check_rules_skip_cross_device_file(kb: KnowledgeBase) -> None:
    ids = {r.id for r in rulesmod.load_dir(kb, KB_ROOT / "rules")}
    assert ids and not any(i.startswith("xd.") for i in ids)


def test_rule_file_errors(kb: KnowledgeBase) -> None:
    with pytest.raises(rulesmod.RuleError) as e:
        _rules(
            kb,
            f"""
rules:
  - id: x.bad_link
    link: vxlan
    compare: {{value: "fact:x"}}
    severity: warning
{TEXTS}
  - id: x.fact_only
    link: pw
    compare: {{value: vc_id}}
    severity: fatal
{TEXTS}
  - id: x.path
    link: subnet
    compare: {{value: mtux}}
    op: similar
    severity: info
    title: {{zh-CN: "{{nope}}", en: T, pt-BR: T}}
    message: {{zh-CN: M, en: M}}
    suggestion: {{zh-CN: S, en: S, pt-BR: S}}
""",
        )
    codes = {(i["rule"], i["code"]) for i in e.value.issues}
    assert codes == {
        ("x.bad_link", "consistency.err.bad_link"),
        ("x.fact_only", "consistency.err.fact_only"),
        ("x.fact_only", "rules.err.bad_severity"),
        ("x.path", "rules.err.path_unknown"),
        ("x.path", "consistency.err.bad_op"),
        ("x.path", "rules.err.placeholder"),
        ("x.path", "rules.err.missing_lang"),
    }


def test_pair_and_requires(kb: KnowledgeBase, topo: topology.Topology) -> None:
    rs = _rules(
        kb,
        f"""
rules:
  - id: x.pair_hello
    link: subnet
    pair: ospf
    compare: {{value: hello}}
    severity: warning
{TEXTS}
  - id: x.future
    link: subnet
    pair: vrrp
    requires: [interface.vrrp]
    compare: {{value: "fact:paired"}}
    op: same_presence
    severity: warning
{TEXTS}
""",
    )
    assert rs.skipped == [{"id": "x.future", "missing": ["interface.vrrp"]}]
    res = consistency.check(topo, kb, rs)
    got = {(f["rule"], f["link"], f["id"].rsplit("[", 1)[-1]) for f in res["findings"]}
    # A1 ospf[_] hello 1 / A2 默认 10；AGG-01 与 A1 都是 1
    assert got == {("x.pair_hello", "subnet:TOPO-ATN-A1:GigabitEthernet0/2/2~TOPO-ATN-A2:GigabitEthernet0/2/2", "_]")}


def test_ops() -> None:
    v: Any = consistency._violates
    assert v("equal", "1", "2") and not v("equal", "1", None) and not v("equal", ["b", "a"], ["a", "b"])
    assert v("same_presence", True, False) and not v("same_presence", False, None)
    assert v("both", True, False) and not v("both", True, True)
    assert v("overlap", ["level-1"], ["level-2"]) and not v("overlap", ["level-1", "level-2"], ["level-2"])
    assert not v("overlap", [], ["level-2"])
