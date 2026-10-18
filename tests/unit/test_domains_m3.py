"""0.3.0 功能域扩展（MPLS LDP、L3VPN 完善、VPWS / VPLS、ACL）与随之而来的通用改动：
单关键字命令卡不再把同前缀的范围外命令算作缺口、刚进入子视图后的分页痕迹行、映射表达式 if:$参数 / tail 截止词 / $序号||auto、
抽取合并时的编号避让、抽取规则里丢弃模式的 views_map。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from lmesh.core import analysis, checks
from lmesh.core import graph as graphmod
from lmesh.core import rules as rulesmod
from lmesh.core.ingest.extractor import Rules, _map_views
from lmesh.core.ingest.service import _resolve_ids
from lmesh.core.kb import mapping
from lmesh.core.parser import parse
from lmesh.core.renderer import render_roundtrip

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
SAMPLES = KB_ROOT / "samples"


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


def _graph(kb, text: str, profile: str):  # type: ignore[no-untyped-def]
    res = analysis.parse_text(text, kb, profile)
    return res, graphmod.build(res.parsed, kb, res.profile)


def _values(g, prefix: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return {n: d.get("value") for n, d in g.nodes(data=True) if n.startswith(prefix) and d.get("kind") == "attr"}


# ---------- 映射表达式 ----------


@pytest.mark.parametrize(
    ("expr", "values", "line", "want"),
    [
        ("$w||if:$h:0.0.0.0", {"h": "10.0.0.1"}, "permit host 10.0.0.1", "0.0.0.0"),
        ("$w||if:$h:0.0.0.0", {"w": "0.0.0.255"}, "permit 10.0.0.0 0.0.0.255", "0.0.0.255"),
        ("$w||if:$h:0.0.0.0", {}, "permit any", None),
        ("$s||$h||any", {}, "deny any", "any"),
        ("tail:select-seq:load-balance-number", {}, "tunnel select-seq cr-lsp lsp load-balance-number 1", "cr-lsp lsp"),
        ("tail:select-seq:load-balance-number", {}, "tunnel select-seq lsp", "lsp"),
        ("tail:inbound", {}, "protocol inbound ssh telnet", "ssh telnet"),
    ],
)
def test_evaluate_m3(expr: str, values: dict[str, Any], line: str, want: Any) -> None:
    assert mapping.evaluate(expr, values, line.split(), False) == want


# ---------- 解析器的通用改动 ----------


def test_single_keyword_card_does_not_claim_prefix(kb) -> None:  # type: ignore[no-untyped-def]
    """华为接口下的 mpls（只有一个关键字的卡）：mpls te / mpls rsvp-te 属于范围外的 MPLS TE，按原文保留，不算未识别行。"""
    text = "interface GigabitEthernet0/2/1\n mpls\n mpls te\n mpls rsvp-te\n mpls ldp\n mpls ldp foo\n#\nreturn"
    lines = {ln.text: ln.kind for ln in parse(text, kb, "huawei-vrp8").lines}
    assert lines["mpls"] == "command" and lines["mpls ldp"] == "command"
    assert lines["mpls te"] == "raw" and lines["mpls rsvp-te"] == "raw"
    assert lines["mpls ldp foo"] == "unknown"  # 已知前缀（mpls ldp …）却匹配不上：仍是知识库缺口


def test_paging_indent_right_after_entering_view(kb) -> None:  # type: ignore[no-untyped-def]
    """ipv4-family 刚进入子视图，下一行是分页痕迹缩进的 ipv6-family：子视图里匹配不到、外层 VPN 实例视图匹配得到。"""
    text = "ip vpn-instance OAM\n ipv4-family\n                 ipv6-family\n#\nreturn"
    p = parse(text, kb, "huawei-vrp8")
    ln = next(x for x in p.lines if x.text == "ipv6-family")
    assert ln.kind == "command" and ln.view == "vpn-instance"
    # 往返仍逐字一致（异常缩进原样保留）
    res, g = _graph(kb, text, "huawei-atn-v800r025")
    assert render_roundtrip(g, kb) == text
    assert "vrf.instance[OAM]/af[ipv6]" in g


# ---------- MPLS LDP ----------


def test_huawei_mpls_ldp_graph(kb) -> None:  # type: ignore[no-untyped-def]
    text = (
        "mpls lsr-id 10.255.0.3\n#\nmpls\n#\nmpls ldp\n graceful-restart\n accept target-hello all\n#\n"
        "mpls ldp remote-peer RP1\n remote-ip 10.255.0.1\n#\n"
        "interface GigabitEthernet0/2/1\n mpls\n mpls mtu 1600\n mpls ldp\n mpls ldp transport-address interface\n#\nreturn"
    )
    _, g = _graph(kb, text, "huawei-atn-v800r025")
    v = _values(g, "mpls.")
    assert v["mpls.global[_]/lsr_id"] == "10.255.0.3"
    assert v["mpls.ldp[_]/graceful_restart"] is True and v["mpls.ldp[_]/accept_target_hello"] == "all"
    assert v["mpls.ldp[_]/remote_peer[RP1]/remote_ip"] == "10.255.0.1"
    assert v["mpls.ldp[_]/igp_sync_delay"] == 10  # Profile 缺省值（隐藏节点）
    iv = _values(g, "interface[GigabitEthernet0/2/1]/mpls[_]")
    assert iv["interface[GigabitEthernet0/2/1]/mpls[_]/ldp"] is True
    assert iv["interface[GigabitEthernet0/2/1]/mpls[_]/mtu"] == 1600
    assert iv["interface[GigabitEthernet0/2/1]/mpls[_]/ldp_transport_address"] == "interface"
    assert not g.graph["missing_prerequisites"]


def test_huawei_mpls_prerequisites(kb) -> None:  # type: ignore[no-untyped-def]
    """华为：接口 mpls 前要全局 mpls，全局 mpls 前要 mpls lsr-id（前置条件只在华为 Profile 生效）。"""
    _, g = _graph(kb, "mpls\n#\ninterface GigabitEthernet0/2/1\n mpls\n#\nreturn", "huawei-atn-v800r025")
    missing = {m["requires"] for m in g.graph["missing_prerequisites"]}
    assert "mpls.global.lsr_id" in missing
    _, g2 = _graph(kb, "interface GigabitEthernet0/0/1\n mpls ip\n!\nend", "cisco-iosxe-asr920-17.15")
    assert not g2.graph["missing_prerequisites"]


def test_cisco_mpls_ldp_graph(kb) -> None:  # type: ignore[no-untyped-def]
    text = (
        "mpls ldp router-id Loopback0 force\nmpls ldp neighbor 10.255.0.1 targeted ldp\n!\n"
        "interface GigabitEthernet0/0/0\n mpls ip\n mpls mtu 9100\n!\nend"
    )
    _, g = _graph(kb, text, "cisco-iosxe-asr920-17.15")
    v = _values(g, "")
    assert v["mpls.ldp[_]/router_id_interface"] == "Loopback0" and v["mpls.ldp[_]/router_id_force"] is True
    assert v["mpls.ldp[_]/remote_peer[10.255.0.1]/remote_ip"] == "10.255.0.1"
    assert v["interface[GigabitEthernet0/0/0]/mpls[_]/ldp"] is True  # Cisco mpls ip = 华为 mpls + mpls ldp
    assert v["interface[GigabitEthernet0/0/0]/mpls[_]/mtu"] == 9100


# ---------- L2VPN ----------


def test_vpws_pw_under_access_point(kb) -> None:  # type: ignore[no-untyped-def]
    """两家的伪线都挂在接入点下：华为子接口（编号 "_"）、Cisco 业务实例；备用伪线 role=backup。"""
    hw = (
        "interface GigabitEthernet0/2/5.100\n vlan-type dot1q 100\n"
        " mpls l2vc 10.255.0.1 1100 tunnel-policy TP\n mpls l2vc 10.255.0.2 1100 secondary\n#\nreturn"
    )
    _, g = _graph(kb, hw, "huawei-atn-v800r025")
    base = "interface[GigabitEthernet0/2/5.100]/access[_]"
    assert g.nodes[f"{base}/pw[primary]/tunnel_policy"]["value"] == "TP"
    assert g.nodes[f"{base}/pw[backup]/peer"]["value"] == "10.255.0.2"
    assert [d["value"] for d in g.graph["dangling"]] == ["TP"]  # 隧道策略没有定义
    cs = (
        "interface GigabitEthernet0/0/5\n service instance 100 ethernet\n  encapsulation dot1q 100\n"
        "  xconnect 10.255.0.1 1100 encapsulation mpls\n   backup peer 10.255.0.2 1100\n!\nend"
    )
    _, g2 = _graph(kb, cs, "cisco-iosxe-asr920-17.15")
    base2 = "interface[GigabitEthernet0/0/5]/access[100]"
    assert g2.nodes[f"{base2}/pw[primary]/vc_id"]["value"] == 1100
    assert g2.nodes[f"{base2}/pw[backup]/peer"]["value"] == "10.255.0.2"


def test_vpls_bridge_domain_references(kb) -> None:  # type: ignore[no-untyped-def]
    hw = (
        "vsi V1 bd-mode\n pwsignal ldp\n  vsi-id 10\n  peer 10.255.0.1\n#\n"
        "bridge-domain 10\n l2 binding vsi V1\n#\nbridge-domain 20\n l2 binding vsi NOPE\n#\nreturn"
    )
    _, g = _graph(kb, hw, "huawei-atn-v800r025")
    assert g.nodes["l2vpn.vsi[V1]/vsi_id"]["value"] == 10
    assert "l2vpn.vsi[V1]/peer[10.255.0.1]" in g
    refs = {(a, b) for a, b, d in g.edges(data=True) if d.get("kind") == "reference"}
    assert ("bridge_domain[10]/vsi", "l2vpn.vsi[V1]") in refs
    assert [d["value"] for d in g.graph["dangling"]] == ["NOPE"]
    cs = "l2vpn vfi context V1\n vpn id 10\n member 10.255.0.1 encapsulation mpls\n!\nbridge-domain 10\n member vfi V1\n!\nend"
    _, g2 = _graph(kb, cs, "cisco-iosxe-asr920-17.15")
    assert g2.nodes["l2vpn.vsi[V1]/vsi_id"]["value"] == 10 and g2.nodes["bridge_domain[10]/vsi"]["value"] == "V1"


# ---------- ACL ----------


def test_acl_rules_normalized_across_vendors(kb) -> None:  # type: ignore[no-untyped-def]
    """源 / 目的统一为“地址 + 反掩码”：华为 X 0 与 Cisco host X 都是 X 0.0.0.0；不写或 any 记为 any。"""
    _, g = _graph(
        kb, "acl number 2001\n rule 5 permit source 10.0.0.1 0\n rule 10 deny\n#\nreturn", "huawei-atn-v800r025"
    )
    v = _values(g, "acl.instance[2001]")
    assert v["acl.instance[2001]/type"] == "basic"
    assert v["acl.instance[2001]/rule[5]/source_ip"] == "10.0.0.1"
    assert v["acl.instance[2001]/rule[5]/source_wildcard"] == "0.0.0.0"
    assert v["acl.instance[2001]/rule[10]/source_ip"] == "any"
    cs = "ip access-list standard A\n 10 permit host 10.0.0.1\n 20 deny   any\n!\naccess-list 110 permit tcp any host 10.0.0.2 eq 22\n!\nend"
    _, g2 = _graph(kb, cs, "cisco-iosxe-asr920-17.15")
    v2 = _values(g2, "acl.instance")
    assert v2["acl.instance[A]/type"] == "basic"
    assert v2["acl.instance[A]/rule[10]/source_ip"] == "10.0.0.1"
    assert v2["acl.instance[A]/rule[10]/source_wildcard"] == "0.0.0.0"
    assert v2["acl.instance[A]/rule[20]/source_ip"] == "any"
    # 编号 ACL 没有序号：按出现顺序编为 10、20…
    assert v2["acl.instance[110]/rule[10]/protocol"] == "tcp"
    assert v2["acl.instance[110]/rule[10]/destination_port"] == "eq 22"


def test_acl_dangling_and_orphan(kb) -> None:  # type: ignore[no-untyped-def]
    """接口 / VTY / SNMP 对 ACL 的引用是引用依赖：引用了不存在的 ACL 是悬空引用，没有被引用的 ACL 是孤儿。"""
    rules = rulesmod.load_dir(kb, KB_ROOT / "rules")
    cs = (
        "ip access-list extended USED\n 10 permit ip any any\nip access-list extended SPARE\n 10 deny ip any any\n!\n"
        "interface GigabitEthernet0/0/0\n ip access-group USED in\n ip access-group MISSING out\n!\n"
        "line vty 0 4\n access-class 99 in\n!\nend"
    )
    _, g = _graph(kb, cs, "cisco-iosxe-asr920-17.15")
    res = checks.check(g, kb, rules)
    by = Counter((f["rule"], f["node"]) for f in res["findings"])
    assert by[("ref.orphan", "acl.instance[SPARE]")] == 1
    assert ("ref.orphan", "acl.instance[USED]") not in by
    dangling = sorted(str(d["value"]) for d in g.graph["dangling"])
    assert dangling == ["99", "MISSING"]


@pytest.mark.parametrize(
    "sample",
    [
        "huawei-atn-v800r025-synthetic/atn-mpls-l2vpn-acl-01.cfg",
        "cisco-iosxe-asr920-synthetic/pe-asr920-03-mpls-l2vpn-acl.cfg",
    ],
)
def test_m3_samples_cover_domains(kb, sample: str) -> None:  # type: ignore[no-untyped-def]
    text = (SAMPLES / sample).read_text(encoding="utf-8")
    res, g = _graph(kb, text, None)
    assert res.parsed.counts().get("unknown", 0) == 0
    assert render_roundtrip(g, kb) == text
    schemas = {str(d.get("schema") or "") for _, d in g.nodes(data=True)}
    for root in (
        "mpls.global",
        "mpls.ldp",
        "interface.mpls",
        "l2vpn.pw_class",
        "interface.access.pw",
        "l2vpn.vsi",
        "acl.instance.rule",
    ):
        assert root in schemas, root


def test_atn_sample_mpls_acl_lines_are_commands(kb) -> None:  # type: ignore[no-untyped-def]
    """现网 ATN 样本里 mpls / mpls ldp / mpls l2vpn / acl 的行都成为命令（M2 时是原文）。"""
    text = (SAMPLES / "huawei-atn-v800r023" / "atn-access-01.cfg").read_text(encoding="utf-8")
    p = parse(text, kb, "huawei-vrp8")
    rules = 0
    for ln in p.lines:
        t = ln.text
        in_acl = ln.view == "acl" and t.startswith("rule ")
        rules += in_acl
        if in_acl or t.startswith(("mpls lsr-id", "mpls ldp", "mpls l2vpn", "acl number", "acl name")) or t == "mpls":
            assert ln.kind == "command", (ln.no, t)
    assert rules == 130  # 5 个 ACL 的全部规则


# ---------- 抽取 ----------


def test_resolve_ids_does_not_overwrite_claimed_card() -> None:
    """新视图让同名命令多了一个变体、抽取编号整体后移：编号被别的卡按内容认领时改号，不覆盖已有的卡。"""
    items = [
        {"id": "x.shutdown~2", "syntax": "shutdown", "view": "bridge-domain"},
        {"id": "x.shutdown~3", "syntax": "shutdown", "view": "interface"},
    ]
    stats: Counter[str] = Counter()
    _resolve_ids(items, {("shutdown", "interface"): "x.shutdown~2"}, {"x.shutdown~2", "x.shutdown~4"}, stats)
    assert items[1]["id"] == "x.shutdown~2"  # 按内容对上已有的卡
    assert items[0]["id"] == "x.shutdown~5"  # 避开已有编号（含其他功能域的 ~4）
    assert stats["matched_by_content"] == 1 and stats["renumbered"] == 1


def test_views_map_null_drops_mode() -> None:
    rules = Rules("t", "cisco-iosxe", {"views_map": [{"match": r"\(config-if\)", "view": "interface"}]})
    local = [{"match": r"\(config-pw-class\)", "view": "pseudowire-class"}, {"match": ".", "view": None}]
    text = "Interface configuration (config-if)\nPseudowire class configuration (config-pw-class)"
    assert _map_views(text, rules, local) == ["pseudowire-class"]
    assert _map_views(text, rules) == ["interface"]
