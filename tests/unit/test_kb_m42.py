"""M4-2 知识库补缺与新功能域：管理面（SSH 算法、明文团体字、RADIUS、SNMPv3、aaa new-model 取反、缺省值）、
VRF 内的 BGP 对等体（拓扑）、Cisco IS-IS 被动接口与 BFD min_rx、VRRP / SR-MPLS / EVPN / QoS / 时钟同步的解析与建图、
跨设备 VRRP 一致性，以及现网 ATN 样本的原文行数（QoS、时钟同步进入功能域后显著减少）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lmesh.core import analysis
from lmesh.core import baseline as blmod
from lmesh.core import consistency as consmod
from lmesh.core import graph as graphmod
from lmesh.core import topology as topomod
from lmesh.core.kb import KnowledgeBase

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
SAMPLES = KB_ROOT / "samples"
ATN = SAMPLES / "huawei-atn-v800r023" / "atn-access-01.cfg"
HW_ADV = SAMPLES / "huawei-atn-v800r025-synthetic" / "atn-advanced-01.cfg"
CS_ADV = SAMPLES / "cisco-iosxe-asr920-synthetic" / "pe-asr920-04-advanced.cfg"


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return analysis.load_kb(KB_ROOT)


def _graph(kb: KnowledgeBase, text: str, name: str = "d") -> Any:
    res = analysis.parse_text(text, kb)
    assert res.parsed.counts().get("unknown", 0) == 0, [ln.text for ln in res.parsed.unknown()]
    return graphmod.build(res.parsed, kb, res.profile, name)


def _vals(g: Any) -> dict[str, Any]:
    return {n: d.get("value") for n, d in g.nodes(data=True) if d.get("kind") in ("object", "attr")}


def _explicit(g: Any) -> dict[str, Any]:
    return {
        n: d.get("value")
        for n, d in g.nodes(data=True)
        if d.get("kind") in ("object", "attr") and d.get("origin") == "explicit"
    }


# ---------- 管理面 ----------

HW_MGMT = """sysname HW-A1
#
snmp-agent
snmp-agent community read public acl 2000
snmp-agent group v3 NMS privacy acl 2000
snmp-agent usm-user v3 nmsuser group NMS
snmp-agent usm-user v3 nmsuser authentication-mode sha2-256 cipher %^%#X%^%#
#
stelnet server enable
ssh server compatible-ssh1x enable
ssh server cipher aes256_ctr aes128_cbc
#
radius-server group RAD1
 radius-server authentication 10.1.1.10 1812 weight 0
 radius-server shared-key-cipher %^%#Z%^%#
#
acl number 2000
 rule 5 permit source 10.0.0.0 0.255.255.255
#
return
"""

CS_MGMT = """hostname CS-A1
!
no aaa new-model
!
ip ssh server algorithm encryption aes256-ctr aes128-cbc
ip ssh server algorithm mac hmac-sha2-256 hmac-sha1
radius server RAD1
 address ipv4 10.1.1.10 auth-port 1812 acct-port 1813
 key 7 0822455D0A16
!
radius-server host 10.2.2.2 auth-port 1645 key 7 1234
snmp-server group NMS v3 priv
!
line vty 0 4
 transport input telnet ssh
line vty 5 15
!
end
"""


def test_huawei_mgmt_nodes(kb: KnowledgeBase) -> None:
    v = _vals(_graph(kb, HW_MGMT))
    assert "mgmt.snmp[_]/community[public]" in v  # 明文团体字：团体字就是键
    assert v["mgmt.snmp[_]/group[NMS]/security_level"] == "priv"
    assert v["mgmt.snmp[_]/user[nmsuser]/group"] == "NMS"
    assert v["mgmt.snmp[_]/user[nmsuser]/auth_protocol"] == "sha2-256"
    assert v["mgmt.ssh[_]/compat_v1"] is True
    assert v["mgmt.ssh[_]/ciphers"] == "aes256_ctr aes128_cbc"
    assert v["mgmt.ssh[_]/hmacs"].startswith("sha2_512")  # Profile 缺省值
    assert v["mgmt.ssh[_]/version"] == "2"
    assert v["mgmt.radius[RAD1]/server[role=authentication,address=10.1.1.10]/port"] == 1812
    assert v["mgmt.radius[RAD1]/key_set"] is True


def test_cisco_mgmt_nodes(kb: KnowledgeBase) -> None:
    g = _graph(kb, CS_MGMT)
    v = _vals(g)
    assert v["mgmt.aaa[_]/enabled"] is False  # no aaa new-model 取反
    assert v["mgmt.ssh[_]/ciphers"] == "aes256-ctr aes128-cbc"
    assert v["mgmt.radius[RAD1]/server[role=all,address=10.1.1.10]/port"] == 1812
    assert v["mgmt.radius[_]/server[role=all,address=10.2.2.2]/port"] == 1645
    assert v["mgmt.line[vty 5 15]/protocols"] == "none"  # Cisco 缺省不允许任何协议
    assert g.nodes["mgmt.line[vty 5 15]/protocols"]["origin"] == "default"


def test_baseline_without_family_branches(kb: KnowledgeBase) -> None:
    """Telnet / SSH 按 Profile 是否支持服务开关判断；版本与 AAA 按缺省值判断；强算法规则报出现网 ATN 的弱算法。"""
    bl = blmod.load(kb, KB_ROOT / "rules")
    assert not any("family" in str(r.assert_) + str(r.when) for r in bl.rules)
    res = blmod.audit([_graph(kb, CS_MGMT, "c"), _graph(kb, HW_MGMT, "h")], bl, "strict")
    cs, hw = res["devices"]
    assert cs["results"]["sec.telnet_disabled"] == "fail"  # transport input telnet
    assert cs["results"]["sec.aaa_enabled"] == "fail"
    assert cs["results"]["sec.ssh_strong_algorithms"] == "fail"
    assert hw["results"]["sec.ssh_v2"] == "fail"  # compatible-ssh1x
    assert hw["results"]["sec.telnet_disabled"] == "pass"
    assert hw["results"]["sec.aaa_server"] == "pass"  # RADIUS 服务器组
    atn = blmod.audit([_graph(kb, ATN.read_text(encoding="utf-8"), "atn")], bl, "strict")["devices"][0]
    algo = next(f for f in atn["failures"] if f["rule"] == "sec.ssh_strong_algorithms")
    assert {2221, 2222, 2223} <= set(algo["lines"])


# ---------- 拓扑：VRF 内的 BGP、IS-IS 被动接口、BFD min_rx ----------

PE = """sysname PE1
#
ip vpn-instance CUST
 ipv4-family
  route-distinguisher 65000:1
#
interface GigabitEthernet0/2/1
 ip binding vpn-instance CUST
 ip address 192.168.1.1 255.255.255.252
#
bgp 65000
 #
 ipv4-family vpn-instance CUST
  peer 192.168.1.2 as-number 65101
#
return
"""

CE = """hostname CE1
!
vrf definition CUST
 rd 65000:1
 address-family ipv4
 exit-address-family
!
interface GigabitEthernet0/0/1
 vrf forwarding CUST
 ip address 192.168.1.2 255.255.255.252
!
router bgp 65101
 address-family ipv4 vrf CUST
  neighbor 192.168.1.1 remote-as 65000
  neighbor 192.168.1.1 activate
 exit-address-family
!
router isis CORE
 net 49.0001.0100.0000.0009.00
 passive-interface default
!
interface GigabitEthernet0/0/2
 ip address 10.1.9.1 255.255.255.252
 ip router isis CORE
 bfd interval 100 min_rx 120 multiplier 3
!
end
"""


def test_vrf_bgp_link_and_isis_bfd(kb: KnowledgeBase) -> None:
    devs = topomod.from_texts([{"name": "pe", "text": PE}, {"name": "ce", "text": CE}], kb)
    topo = topomod.build(devs, kb)
    bgp = [lk for lk in topo.links if lk["type"] == "bgp"]
    assert len(bgp) == 1 and bgp[0]["vrf"] == "CUST" and bgp[0]["confidence"] == "high"
    assert {bgp[0]["a"]["facts"]["remote_as"], bgp[0]["b"]["facts"]["remote_as"]} == {"65000", "65101"}
    v = _vals(_graph(kb, CE))
    assert v["isis.process[CORE]/passive_default"] is True
    assert v["interface[GigabitEthernet0/0/2]/bfd[_]/min_rx"] == 120
    assert v["interface[GigabitEthernet0/0/2]/bfd[_]/min_tx"] == 100
    ce = next(f for name, f in topo.facts.items() if name == "CE1")
    itf = ce.ifaces["GigabitEthernet0/0/2"]
    assert ce.isis(itf)["passive"] is True  # 进程缺省被动


# ---------- 新功能域 ----------


def test_advanced_samples_huawei(kb: KnowledgeBase) -> None:
    e = _explicit(_graph(kb, HW_ADV.read_text(encoding="utf-8")))
    assert e["interface[GigabitEthernet0/2/5]/vrrp[10]/priority"] == 120
    assert "interface[GigabitEthernet0/2/5]/vrrp[10]/virtual_ip[10.20.1.1]" in e
    assert e["interface[GigabitEthernet0/2/5]/vrrp[10]/track[interface GigabitEthernet0/2/1]/reduce"] == 30
    assert e["isis.process[1]/sr_mpls"] is True and e["isis.process[1]/ti_lfa"] is True
    assert e["interface[LoopBack0]/prefix_sid[isis]/index"] == 4
    assert e["evpn.instance[EVPN10]/mode"] == "bd-mode"
    assert e["bridge_domain[10]/evpn_instance"] == "EVPN10"
    assert e["evpn.evpl[20]/remote_service_id"] == 200
    assert "bgp.instance[65000]/bgp.af[afi=evpn,vrf=]/peer[10.255.0.9]" in e
    assert e["qos.policy[TP-UNI-IN]/rule[TC-VOICE]/behavior"] == "TB-VOICE"
    assert e["qos.behavior[TB-DATA]/car_cir"] == 50000
    assert e["interface[GigabitEthernet0/2/1]/port_queue[ef]/shaping_pct"] == 40
    assert e["clock.ptp[_]/device_type"] == "bc"
    assert e["clock.sync[_]/source[ptp]/priority"] == 2


def test_advanced_samples_cisco(kb: KnowledgeBase) -> None:
    e = _explicit(_graph(kb, CS_ADV.read_text(encoding="utf-8")))
    assert e["interface[GigabitEthernet0/0/5]/vrrp[10]/priority"] == 110
    assert e["interface[GigabitEthernet0/0/6]/vrrp[20]/preempt"] is False
    assert e["sr.global[_]/conn_map[_]/af[ipv4]/prefix[10.255.0.9/32]/index"] == 9
    assert e["isis.process[CORE]/sr_mpls"] is True
    assert e["evpn.instance[10]/mode"] == "bd-mode"
    assert e["qos.classifier[CM-DATA]/operator"] == "and"
    assert e["qos.policy[PM-OUT]/rule[class-default]/child_policy"] == "PM-CHILD"
    assert e["interface[GigabitEthernet0/0/1]/qos_policy[outbound]/policy"] == "PM-OUT"
    assert e["qos.policy[PM-CHILD]/rule[CM-DATA]/bandwidth_remaining_pct"] == 40
    assert e["clock.ptp[_]/port[SLAVE1]/role"] == "slave"
    assert e["clock.sync[_]/source[ptp]/priority"] == 2
    assert e["isis.process[CORE]/passive[Loopback0]/enabled"] is True


def test_vrrp_consistency(kb: KnowledgeBase) -> None:
    hw = HW_ADV.read_text(encoding="utf-8").replace(
        "vrrp vrid 10 virtual-ip 10.20.1.1", "vrrp vrid 10 virtual-ip 10.20.1.100"
    )
    hw = hw.replace(" vrrp vrid 10 timer advertise 2\n", "")
    devs = topomod.from_texts(
        [{"name": "a", "text": hw}, {"name": "b", "text": CS_ADV.read_text(encoding="utf-8")}], kb
    )
    topo = topomod.build(devs, kb)
    res = consmod.check(topo, kb, consmod.load(kb, consmod.rules_file(KB_ROOT)))
    rules = {f["rule"] for f in res["findings"]}
    assert {"xd.vrrp.virtual_ip", "xd.vrrp.advertise"} <= rules
    assert "xd.vrrp.one_side" not in rules and not res.get("rules_skipped")


def test_atn_raw_lines_reduced(kb: KnowledgeBase) -> None:
    """QoS 与时钟同步进入功能域后，现网 ATN 样本的原文行从 774 降到 200 以下，仍然没有未识别行。"""
    c = analysis.parse_text(ATN.read_text(encoding="utf-8"), kb).parsed.counts()
    assert c.get("unknown", 0) == 0
    assert c["raw"] < 200 and c["command"] > 1700
