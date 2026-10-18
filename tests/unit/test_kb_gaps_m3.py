"""M3 知识库补缺：接入点编号与形态换结构、子接口 VLAN、团体字多值、BGP 计时器、线路认证拆分、敏感取值拦截、
ACL 端口与别名、render/ 进入知识库缓存签名。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from lmesh.core import analysis, translate
from lmesh.core import graph as graphmod
from lmesh.core.kb import mapping

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
CISCO = "cisco-iosxe-asr920-17.15"
HUAWEI = "huawei-atn-v800r025"

HW_L2 = """\
#
bridge-domain 101
#
interface GigabitEthernet0/2/1.101 mode l2
 description SITE-A
 encapsulation dot1q vid 101
 rewrite pop single
 bridge-domain 101
#
return
"""

CS_EFP = """\
!
interface GigabitEthernet0/0/1
 description UPLINK
 service instance 101 ethernet
  description SITE-A
  encapsulation dot1q 101
  rewrite ingress tag pop 1 symmetric
  bridge-domain 101
 !
!
end
"""


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


def graph(kb, text: str, profile: str):  # type: ignore[no-untyped-def]
    res = analysis.parse_text(text, kb, profile)
    return graphmod.build(res.parsed, kb, res.profile, "dev")


def test_ctx_subif_expression() -> None:
    ev = mapping.evaluate
    assert ev("ctx:subif", {}, [], False, ctx={"interface": "GigabitEthernet0/2/1.101"}) == "101"
    assert ev("ctx:subif", {}, [], False, ctx={"interface": "GigabitEthernet0/2/1"}) == "_"
    assert ev("$x||ctx:subif", {}, [], False, ctx={"interface": "Eth-Trunk1.7"}) == "7"


def test_huawei_access_point_keyed_by_subinterface(kb) -> None:  # type: ignore[no-untyped-def]
    g = graph(kb, HW_L2, HUAWEI)
    assert "interface[GigabitEthernet0/2/1.101]/access[101]/vlan" in g
    assert "interface[GigabitEthernet0/2/1.101]/access[_]" not in g


def test_reshape_access_both_directions(kb) -> None:  # type: ignore[no-untyped-def]
    g = graph(kb, HW_L2, HUAWEI)
    ren = translate.reshape_access(g, "instance")
    assert ren["interface[GigabitEthernet0/2/1.101]/access[101]"] == "interface[GigabitEthernet0/2/1]/access[101]"
    assert g.nodes["interface[GigabitEthernet0/2/1]/access[101]/description"]["value"] == "SITE-A"
    assert "interface[GigabitEthernet0/2/1.101]" not in g  # 只承载接入点的二层子接口一并去掉
    g2 = graph(kb, CS_EFP, CISCO)
    translate.reshape_access(g2, "subinterface")
    assert g2.nodes["interface[GigabitEthernet0/0/1.101]/l2"]["value"] is True
    assert g2.nodes["interface[GigabitEthernet0/0/1.101]/description"]["value"] == "SITE-A"
    assert "interface[GigabitEthernet0/0/1.101]/access[101]/bridge_domain" in g2
    assert "interface[GigabitEthernet0/0/1]" in g2  # 父接口还有描述，保留


def test_translate_access_points_both_ways(kb) -> None:  # type: ignore[no-untyped-def]
    r = translate.translate_text(HW_L2, kb, CISCO, HUAWEI, {"GigabitEthernet0/2/1": "GigabitEthernet0/0/1"})
    assert r["verify"]["unexplained"] == 0
    assert " service instance 101 ethernet" in r["text"] and "  bridge-domain 101" in r["text"]
    assert "interface GigabitEthernet0/0/1.101" not in r["text"]
    r2 = translate.translate_text(CS_EFP, kb, HUAWEI, CISCO)
    assert r2["verify"]["unexplained"] == 0
    assert "interface GigabitEthernet0/0/1.101 mode l2" in r2["text"]
    assert " encapsulation dot1q vid 101" in r2["text"] and " description SITE-A" in r2["text"]


def test_l3_subif_vpws_becomes_service_instance(kb) -> None:  # type: ignore[no-untyped-def]
    hw = "#\ninterface GigabitEthernet0/2/5.100\n vlan-type dot1q 100\n mpls l2vc 10.255.0.1 1100\n#\nreturn\n"
    r = translate.translate_text(hw, kb, CISCO, HUAWEI)
    assert r["verify"]["unexplained"] == 0
    text = r["text"]
    assert " service instance 100 ethernet" in text and "  encapsulation dot1q 100" in text
    assert "  xconnect 10.255.0.1 1100 encapsulation mpls" in text


def test_cisco_subif_dot1q_and_multi_community(kb) -> None:  # type: ignore[no-untyped-def]
    cs = (
        "!\ninterface GigabitEthernet0/0/1.10\n encapsulation dot1Q 10\n ip address 10.0.0.1 255.255.255.252\n!\n"
        "route-map X permit 10\n set community 65000:1 65000:2 additive\n!\nend\n"
    )
    g = graph(kb, cs, CISCO)
    assert g.nodes["interface[GigabitEthernet0/0/1.10]/dot1q_termination"]["value"] == 10
    assert g.nodes["rp.policy[X]/node[10]/set_community"]["value"] == "65000:1 65000:2"
    r = translate.translate_text(cs, kb, HUAWEI, CISCO)
    assert " vlan-type dot1q 10" in r["text"]
    assert " apply community 65000:1 65000:2 additive" in r["text"]


def test_bgp_timers_and_log_neighbor_changes(kb) -> None:  # type: ignore[no-untyped-def]
    cs = (
        "!\nrouter bgp 65000\n bgp log-neighbor-changes\n timers bgp 10 30\n"
        " neighbor 10.0.0.2 remote-as 65001\n neighbor 10.0.0.2 timers 5 15\n!\nend\n"
    )
    g = graph(kb, cs, CISCO)
    assert g.nodes["bgp.instance[65000]/keepalive"]["value"] == 10
    assert g.nodes["bgp.instance[65000]/bgp.peer[10.0.0.2]/hold"]["value"] == 15
    r = translate.translate_text(cs, kb, HUAWEI, CISCO)
    assert r["verify"]["unexplained"] == 0
    assert " timer keepalive 10 hold 30" in r["text"]
    # 华为默认记录邻居变化：Cisco 显式写的 log-neighbor-changes 等于目标默认值，省略并说明
    assert any(d["schema"] == "bgp.instance.log_neighbor_changes" for d in r["defaults"])


def test_line_auth_split(kb) -> None:  # type: ignore[no-untyped-def]
    g = graph(kb, "!\nline con 0\n login authentication CONSOLE\n!\nend\n", CISCO)
    assert g.nodes["mgmt.line[con 0]/auth"]["value"] == "aaa"
    assert g.nodes["mgmt.line[con 0]/auth_list"]["value"] == "CONSOLE"


def test_snmp_community_is_secret_across_families(kb) -> None:  # type: ignore[no-untyped-def]
    assert kb.nodes["mgmt.snmp.community"].secret
    r = translate.translate_text("!\nsnmp-server community PUBLIC-RO RO\n!\nend\n", kb, HUAWEI, CISCO)
    assert "PUBLIC-RO" not in r["text"]
    assert any(u["params"].get("reason") == "secret" for u in r["unsupported"])
    assert r["verify"]["unexplained"] == 0


def test_huawei_acl_ports_and_alias(kb) -> None:  # type: ignore[no-untyped-def]
    hw = (
        "#\nacl name VTY number 3001\n rule 5 permit tcp source 10.0.0.0 0.0.0.255 destination-port eq 22\n"
        " rule 10 permit udp source-port range 1000 2000\n#\nuser-interface vty 0 4\n acl 3001 inbound\n#\nreturn\n"
    )
    g = graph(kb, hw, HUAWEI)
    assert g.nodes["acl.instance[VTY]/rule[5]/destination_port"]["value"] == "eq 22"
    assert g.nodes["acl.instance[VTY]/rule[10]/source_port"]["value"] == "range 1000 2000"
    assert "acl.instance[VTY]/rule[5]/source_port" not in g
    # acl name X number N 按编号 N 被引用：引用边连到这个 ACL，不算悬空
    refs = [(a, b) for a, b, d in g.edges(data=True) if d.get("kind") == "reference" and b == "acl.instance[VTY]"]
    assert refs
    assert not any(x.get("value") == "3001" for x in g.graph.get("dangling", []))


def test_cisco_named_acl_without_type(kb) -> None:  # type: ignore[no-untyped-def]
    g = graph(kb, "!\nip access-list MGMT\n 10 permit tcp any any eq 22\n!\nend\n", CISCO)
    assert g.nodes["acl.instance[MGMT]/type"]["value"] == "advanced"


def test_render_dir_in_kb_signature() -> None:
    root = KB_ROOT.parent / "tmp" / "test-kb-signature"  # 临时文件放在项目内的 tmp/
    shutil.rmtree(root, ignore_errors=True)
    (root / "render").mkdir(parents=True)
    (root / "kb.yaml").write_text("version: 1\n", encoding="utf-8")
    f = root / "render" / "x.yaml"
    f.write_text("family: x\n", encoding="utf-8")
    before = analysis._signature(root)
    os.utime(f, (before[0] + 10, before[0] + 10))
    assert analysis._signature(root) != before
    shutil.rmtree(root)
