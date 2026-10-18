"""映射表达式、解析器、建图：用程序自带的知识库（含抽取出的命令卡与映射）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmesh.core import analysis
from lmesh.core import graph as graphmod
from lmesh.core.kb import mapping
from lmesh.core.parser import parse
from lmesh.core.renderer import render_roundtrip

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


# ---------- 映射表达式 ----------


def test_parse_target() -> None:
    alts = mapping.parse_target("vrf.instance.af{afi=ipv4}.rd | x.y")
    assert alts[0].node == "vrf.instance.af.rd" and alts[0].fixed == {"vrf.instance.af": {"afi": "ipv4"}}
    assert alts[1].node == "x.y"


@pytest.mark.parametrize(
    ("expr", "values", "line", "neg", "want"),
    [
        ("$a", {"a": "1"}, "x", False, "1"),
        ("$a||$b||lit", {"b": "2"}, "x", False, "2"),
        ("$a||$b||lit", {}, "x", False, "lit"),
        ("fmt:{ip}/{mask|len}", {"ip": "10.0.0.0", "len": "8"}, "x", False, "10.0.0.0/8"),
        ("fmt:{ip}/{mask}", {"ip": "10.0.0.0"}, "x", False, "10.0.0.0"),
        ("kw:import|export|both:both", {}, "route-target export 1:1", False, "export"),
        ("kw:import|export|both:both", {}, "route-target 1:1", False, "both"),
        ("kw:single=pop 1|double=pop 2", {}, "rewrite pop double", False, "pop 2"),
        ("if:in:$m", {"m": "P"}, "neighbor x route-map P in", False, "P"),
        ("if:in:$m", {"m": "P"}, "neighbor x route-map P out", False, None),
        ("flag", {}, "shutdown", False, True),
        ("flag", {}, "undo shutdown", True, False),
    ],
)
def test_evaluate(expr, values, line, neg, want) -> None:  # type: ignore[no-untyped-def]
    assert mapping.evaluate(expr, values, line.split(), neg) == want


def test_normalize_and_branch() -> None:
    assert mapping.normalize("integer", "x", "255.255.255.0") == 24
    assert mapping.normalize("prefix", "x", "10.0.0.0/255.0.0.0") == "10.0.0.0/8"
    assert mapping.choose_branch(["10.0.0.1"]) == 0 and mapping.choose_branch(["Client"]) == 1


# ---------- 解析器 ----------

HW = """sysname PE-01
#
interface GigabitEthernet0/2/1.101 mode l2
 encapsulation dot1q vid 101
 rewrite pop single
 bridge-domain 101
#
interface Vbdif101
 ip binding vpn-instance RAN
 ip address 10.1.1.1 255.255.255.0
 undo shutdown
 mpls
#
ip vpn-instance RAN
 ipv4-family
  route-distinguisher 65000:101
  vpn-target 65000:101 65000:1 export-extcommunity
#
bgp 65000
 group RR internal
 peer RR connect-interface LoopBack0
 peer 10.0.0.1 as-number 65000
 peer 10.0.0.1 group RR
 #
 ipv4-family vpnv4
  peer RR enable
                  peer RR route-policy IMPORT-ALL import
#
route-policy IMPORT-ALL permit node 10
 if-match ip-prefix NOPE
#
ospf 1
 area 0.0.0.0
  network 10.0.0.0 0.255.255.255
#
return"""


def test_parser_views_negation_raw(kb) -> None:  # type: ignore[no-untyped-def]
    p = parse(HW, kb, "huawei-vrp8")
    by_no = {ln.no: ln for ln in p.lines}
    assert by_no[3].view == "system" and by_no[4].view == "interface" and by_no[4].card
    assert by_no[11].negated and by_no[11].kind == "command"  # undo shutdown
    assert by_no[12].kind == "command" and by_no[12].domain == "mpls"  # mpls：0.3.0 起是功能域（M3-2）
    assert by_no[16].view == "vpn-instance-af-ipv4"
    # 异常缩进（终端分页痕迹）仍归在上一行的视图里，原始空白保留
    weird = next(ln for ln in p.lines if "IMPORT-ALL import" in ln.text)
    assert weird.view == "bgp-af-vpnv4" and weird.kind == "command" and weird.indent.startswith(" " * 10)
    # ospf 块（0.2.0 起是功能域）：进程、区域、network 逐级进入视图
    assert [by_no[n].view for n in (32, 33, 34)] == ["system", "ospf", "ospf-area"]
    assert all(by_no[n].kind == "command" for n in (32, 33, 34))
    assert p.counts().get("unknown", 0) == 0


def test_cisco_exit_and_bare_negation(kb) -> None:  # type: ignore[no-untyped-def]
    text = "hostname R1\n!\nrouter bgp 1\n address-family ipv4 vrf A\n  redistribute connected\n exit-address-family\n neighbor 1.1.1.1 remote-as 2\n!\ninterface Gi0/0/1\n no ip address\n!\nend"
    p = parse(text, kb, "cisco-iosxe")
    by_no = {ln.no: ln for ln in p.lines}
    assert by_no[6].card == "@exit:exit-address-family"
    assert by_no[7].view == "router-bgp" and by_no[7].kind == "command"  # 退出地址族后回到 BGP 模式
    assert by_no[10].negated and by_no[10].card


# ---------- 建图与往返 ----------


def test_graph_objects_defaults_deps(kb) -> None:  # type: ignore[no-untyped-def]
    res = analysis.parse_text(HW, kb, "huawei-atn-v800r025")
    g = graphmod.build(res.parsed, kb, res.profile, "PE-01")
    n = g.nodes
    assert n["interface[Vbdif101]/vrf"]["value"] == "RAN"
    assert n["interface[Vbdif101]/ipv4[10.1.1.1]/prefix_length"]["value"] == 24  # 掩码换算成长度
    assert n["interface[Vbdif101]/shutdown"]["value"] is False
    assert n["interface[Vbdif101]/mtu"]["origin"] == "default" and n["interface[Vbdif101]/mtu"]["value"] == 1500
    # 华为二层子接口上的业务接入点
    assert n["interface[GigabitEthernet0/2/1.101]/access[_]/vlan"]["value"] == 101
    assert n["interface[GigabitEthernet0/2/1.101]/access[_]/rewrite"]["value"] == "pop 1"
    # vpn-target 一行两个值 → 两个 RT 对象
    rts = [k for k in n if k.startswith("vrf.instance[RAN]/af[ipv4]/rt[") and n[k]["kind"] == "object"]
    assert len(rts) == 2
    # 对等体与组按取值区分；依赖边；悬空引用
    assert n["bgp.instance[65000]/bgp.peer[10.0.0.1]/group"]["value"] == "RR"
    kinds = {(a, d["kind"]) for a, _, d in g.edges(data=True)}
    assert ("interface[Vbdif101]/vrf", "prerequisite") in kinds
    assert ("interface[Vbdif101]/vrf", "side_effect") in kinds  # 华为：绑定 VPN 会清除接口 IP
    # 华为的桥域必须在系统视图声明，这段配置没有声明 bridge-domain 101；if-match ip-prefix 引用了不存在的前缀列表
    assert sorted(str(d["value"]) for d in g.graph["dangling"]) == ["101", "NOPE"]
    assert render_roundtrip(g, kb) == HW


def test_cisco_implicit_bridge_domain(kb) -> None:  # type: ignore[no-untyped-def]
    text = "hostname R1\n!\ninterface GigabitEthernet0/0/1\n service instance 10 ethernet\n  encapsulation dot1q 10\n  bridge-domain 10\n !\n!\nend"
    res = analysis.parse_text(text, kb)
    g = graphmod.build(res.parsed, kb, res.profile)
    assert g.nodes["bridge_domain[10]"]["origin"] == "derived" and not g.graph["dangling"]
    assert render_roundtrip(g, kb) == text


# ---------- 0.2.0：IGP、BFD、管理面相关的机制 ----------


@pytest.mark.parametrize(
    ("expr", "values", "line", "want"),
    [
        ("tail:service-type", {}, "local-user u1 service-type ftp terminal ssh", "ftp terminal ssh"),
        ("tail:inbound", {}, "protocol inbound", None),
        (
            "kw:default=authentication default||fmt:authentication {list-name}",
            {"list-name": "CON"},
            "aaa authentication login CON local",
            "authentication CON",
        ),
        (
            "kw:default=authentication default||fmt:authentication {list-name}",
            {},
            "aaa authentication login default local",
            "authentication default",
        ),
        ("if:disable:false||flag", {}, "ip ospf bfd", True),
        ("if:disable:false||flag", {}, "ip ospf bfd disable", "false"),
        ("$a||fmt:{b}{c}", {}, "x", None),
        ("fmt:{m1} {m2} {m3}", {"m1": "group", "m2": "tacacs+"}, "x", "group tacacs+"),
    ],
)
def test_evaluate_m2(expr, values, line, want) -> None:  # type: ignore[no-untyped-def]
    assert mapping.evaluate(expr, values, line.split(), False) == want


def test_normalize_repeated_group_values() -> None:
    assert mapping.normalize("ipv4", "x", ["10.0.0.1"]) == "10.0.0.1"
    assert mapping.normalize("string", "x", ["v2c", "v3"]) == "v2c v3"


def test_abnormal_indent_falls_back_to_outer_view(kb) -> None:  # type: ignore[no-untyped-def]
    # 分页痕迹出现在子视图（frr）块之后的第一行：area 应回到 ospf 视图，其下的 network 进入区域视图
    text = "ospf 8\n frr\n  loop-free-alternate\n                 area 0.0.0.8\n  network 10.0.0.1 0.0.0.0\n#\nreturn"
    p = parse(text, kb, "huawei-vrp8")
    by_no = {ln.no: ln for ln in p.lines}
    assert by_no[4].view == "ospf" and by_no[4].kind == "command"
    assert by_no[5].view == "ospf-area" and by_no[5].kind == "command"
    res = analysis.parse_text(text, kb, "huawei-atn-v800r025")
    g = graphmod.build(res.parsed, kb, res.profile)
    assert render_roundtrip(g, kb) == text


def test_conditional_defaults_and_object_prerequisite(kb) -> None:  # type: ignore[no-untyped-def]
    text = (
        "hostname R1\n!\ninterface Loopback0\n ip address 10.0.0.1 255.255.255.255\n!\n"
        "interface GigabitEthernet0/0/1\n ip address 10.1.1.1 255.255.255.252\n ip ospf network point-to-point\n!\nend"
    )
    res = analysis.parse_text(text, kb, "cisco-iosxe-asr920-17.15")
    g = graphmod.build(res.parsed, kb, res.profile)
    n = g.nodes
    # negotiation 只对物理口补默认值；hello 按（显式的）网络类型补
    assert n["interface[GigabitEthernet0/0/1]/negotiation"]["origin"] == "default"
    assert "interface[Loopback0]/negotiation" not in n
    assert n["interface[GigabitEthernet0/0/1]/ospf[_]/hello"]["value"] == 10
    # 华为 BFD 会话需要先全局使能 bfd：缺少时记为缺少前置条件，不是悬空引用
    hw = "sysname X\n#\nbfd S1 bind peer-ip 10.0.0.2\n detect-multiplier 5\n#\nreturn"
    res = analysis.parse_text(hw, kb, "huawei-atn-v800r025")
    g = graphmod.build(res.parsed, kb, res.profile)
    assert g.graph["missing_prerequisites"] and not g.graph["dangling"]
    assert g.nodes["bfd.session[S1]/multiplier"]["value"] == 5
    assert render_roundtrip(g, kb) == hw


def test_trailing_whitespace_kept_on_matched_lines(kb) -> None:  # type: ignore[no-untyped-def]
    text = "hostname R1\n!\naaa new-model\naaa authorization exec default local \n!\nend"
    res = analysis.parse_text(text, kb, "cisco-iosxe-asr920-17.15")
    g = graphmod.build(res.parsed, kb, res.profile)
    assert render_roundtrip(g, kb) == text
