"""M7-3：Nokia SR OS Classic CLI 的映射表达式扩展、建图、Profile 条件缺省值、规范渲染（exit 分块、容器、引号）、
三层接口与 IS-IS NET 的换结构、清理与脚本检查的平台族写法；并确认华为 / Cisco 的表达式结果不变。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmesh.core import analysis, canon, change, cleanup, script_check, terms, translate
from lmesh.core import compare as cmp
from lmesh.core import graph as graphmod
from lmesh.core.kb import mapping

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parent.parent.parent
KB_ROOT = ROOT / "knowledge"
SAMPLES = KB_ROOT / "samples" / "nokia-sros-classic-synthetic"
PID = "nokia-sros-classic-7750-25.10"


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


def _graph(kb, text: str):  # type: ignore[no-untyped-def]
    res = analysis.parse_text(text, kb, PID)
    return graphmod.build(res.parsed, kb, PID)


def _sample(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- 映射表达式


def test_ctx_param_and_split_expressions() -> None:
    ctx = {"params": {"ip-prefix/prefix-length": "0.0.0.0/0", "area-id": "0.0.0.0"}}
    assert mapping.evaluate("ctx:ip-prefix/prefix-length", {}, [], False, ctx=ctx) == "0.0.0.0/0"
    assert mapping.evaluate("ctx:ospf-instance||0", {}, [], False, ctx=ctx) == "0"
    vals = {"sap-id": "1/1/4:3001.10", "port-name": "lag-1", "ip-address/mask": "10.0.0.1/30"}
    assert mapping.evaluate("sap:port:$sap-id", vals, [], False) == "1/1/4"
    assert mapping.evaluate("sap:vlan:$sap-id", vals, [], False) == "3001"
    assert mapping.evaluate("sap:inner:$sap-id", vals, [], False) == "10"
    assert mapping.evaluate("sap:encap:$sap-id", vals, [], False) == "qinq"
    assert mapping.evaluate("sap:tag:$port-name", vals, [], False) == "_"
    assert mapping.evaluate("sap:vlan:$port-name", vals, [], False) is None
    assert mapping.evaluate("pfx:addr:$ip-address/mask", vals, [], False) == "10.0.0.1"
    assert mapping.evaluate("pfx:len:$ip-address/mask", vals, [], False) == "30"
    assert mapping.evaluate("pfx:wild:$ip-address/mask", vals, [], False) == "0.0.0.3"
    assert mapping.evaluate("pre:target:$rt", {"rt": "target:64500:1"}, [], False) == "64500:1"
    assert mapping.evaluate("!flag", {}, [], True) is True and mapping.evaluate("!flag", {}, [], False) is False
    look = {"lookup": lambda s, k, a: "10.255.0.2" if (s, k, a) == ("service.sdp", "12", "far_end") else None}
    expr = "via:service.sdp:far_end:sap:port:$sdp-id:vc-id"
    assert mapping.evaluate(expr, {"sdp-id:vc-id": "12:1001"}, [], False, ctx=look) == "10.255.0.2"
    assert mapping.join_sap({"port": "1/1/4", "vlan": "3001", "inner": "10"}) == "1/1/4:3001.10"
    assert mapping.wildcard("24") == "0.0.0.255" and mapping.wildcard_len("0.0.0.255") == "24"


def test_tokens_targets_and_params() -> None:
    assert mapping.tokens('description "to P1 link"', True) == ["description", "to P1 link"]
    assert mapping.tokens('description "to P1"', False) == ["description", '"to', 'P1"']
    t = mapping.parse_target("interface{name=$port-id}.lag")[0]
    assert t.node == "interface.lag" and t.dynamic() == {"interface": {"name": "$port-id"}}
    assert mapping.parse_target("vrf.instance.af{afi=ipv4}.rd")[0].dynamic() == {}
    assert mapping.is_directive("@container") and mapping.is_container({"@container": ""})
    assert {"sdp-id:vc-id", "sdp-id"} <= mapping.params_in_expr("sap:port:$sdp-id:vc-id")
    assert "ip-address/mask" in mapping.params_in_expr("pfx:addr:$ip-address/mask||$ip-address")


def test_huawei_cisco_expressions_unchanged() -> None:
    """华为 / Cisco 用到的写法在 M7-3 扩展后结果不变（ctx 由 None 变成字典也一样）。"""
    toks = ["rewrite", "pop", "single"]
    assert mapping.evaluate("kw:single=pop 1|double=pop 2", {}, toks, False) == "pop 1"
    assert mapping.evaluate("ctx:subif", {}, [], False, ctx=None) == "_"
    assert mapping.evaluate("ctx:subif", {}, [], False, ctx={"lookup": None}) == "_"
    assert mapping.evaluate("ctx:subif", {}, [], False, ctx={"interface": "GE0/2/1.101"}) == "101"
    assert (
        mapping.evaluate(
            "fmt:{ip-address}/{mask|mask-length}", {"ip-address": "10.0.0.0", "mask-length": "8"}, [], False
        )
        == "10.0.0.0/8"
    )
    assert mapping.evaluate("if:$host:0.0.0.0", {"host": "1.1.1.1"}, [], False) == "0.0.0.0"
    assert mapping.params_in_expr("if:$host:0.0.0.0") >= {"host"}


# ---------------------------------------------------------------- 建图


def test_graph_lag_ospf_static_bgp(kb) -> None:  # type: ignore[no-untyped-def]
    g = _graph(kb, _sample("classic-pe-basic.cfg"))
    nodes = dict(g.nodes(data=True))
    # lag 下的 port 写到成员口上；容器行不产生节点也不是未映射命令
    assert nodes["interface[1/1/2]/lag"]["value"] == 1 and nodes["interface[1/1/3]/lag"]["value"] == 1
    assert not any("router" in n and "ext[" in n for n in g.nodes if "@" in n and ".router@" in n)
    # OSPF 区域下的 interface 写到接口的 OSPF 参数（进程、区域取自外层行）
    assert nodes["interface[to-P1]/ospf[_]/area"]["value"] == "0.0.0.0"
    assert nodes["interface[to-P1]/ospf[_]/process"]["value"] == "0"
    # static-route-entry <前缀> 下的 next-hop：前缀取自容器行
    assert "static.route[vrf=,prefix=0.0.0.0/0,nexthop=10.0.12.2]/preference" in g
    # 路由器接口的 port：绑定端口与终结的 VLAN
    assert nodes["interface[to-P2]/bind_port"]["value"] == "lag-1"
    # Profile 的条件缺省值：端口缺省 shutdown；路由器逻辑接口（when.else）缺省 no shutdown
    shut = {n: d["value"] for n, d in nodes.items() if n.endswith("/shutdown") and d.get("origin") == "default"}
    assert all(v is True for n, v in shut.items() if n.startswith("interface[1/1/")) or not shut
    assert g.graph["dangling"] == []


def test_graph_share_services_and_syslog(kb) -> None:  # type: ignore[no-untyped-def]
    g = _graph(kb, _sample("classic-pe-routing-mgmt.cfg"))
    # router 下的 autonomous-system（@share）是后面 bgp 块（在另一个 router Base 块里）的 BGP 实例
    assert "bgp.instance[64500]/bgp.peer_group[IBGP-RR]" in g and "bgp.instance[_]" not in g
    assert g.nodes["bgp.instance[64500]/bgp.peer[10.255.0.100]/group"]["value"] == "IBGP-RR"
    assert g.nodes["mgmt.syslog[_]/host[192.0.2.20]/level"]["value"] == "warning"
    assert g.nodes["isis.process[0]/area_id"]["value"] == "49.0001"
    s = _graph(kb, _sample("classic-pe-services.cfg"))
    # Epipe 的 spoke-sdp：伪线对端取 SDP 的 far-end；VPLS 的 SAP 绑定 VSI；VPRN 的接口绑定 VRF、SAP 拆成端口与 VLAN
    assert "l2vpn.xconnect[EPIPE-1001]/pw[peer=10.255.0.2,vc_id=1001]" in s
    assert s.nodes["interface[1/1/4]/access[2001]/vsi"]["value"] == "VPLS-2001"
    assert s.nodes["interface[to-CE1]/vrf"]["value"] == "VPRN-3001"
    assert s.nodes["interface[to-CE2]/dot1q_termination"]["value"] == 3001
    assert (
        s.nodes["vrf.instance[VPRN-3001]/af[ipv4]/rt[value=64500:3001,direction=both]/value"]["value"] == "64500:3001"
    )
    assert s.graph["dangling"] == []


# ---------------------------------------------------------------- 规范渲染


def test_canonical_nokia_blocks(kb) -> None:  # type: ignore[no-untyped-def]
    g = _graph(kb, _sample("classic-pe-routing-mgmt.cfg"))
    r = canon.render_full(g, kb, PID)
    lines = r.text.split("\n")
    assert lines[:2] == ["exit all", "configure"] and lines[-1] == "exit all"
    assert 'echo "BGP Configuration"' in lines
    assert '        interface "to-PE1"' in lines  # 名称加引号，configure 下缩进 1 级（4 个空格）
    assert "            begin" in lines and "            commit" in lines  # policy-options 包在 begin … commit 里
    # 每个进入视图的行都由同列的 exit 关闭（设备按 exit 而不是缩进分块）：重新解析时 exit 都配得上、没有多余的
    parsed = analysis.parse_text(r.text, kb, PID).parsed
    enters = [ln for ln in parsed.lines if ln.kind == "command" and ln.card and not ln.card.startswith("@")
              and kb.cards[ln.card].enters_view and not ln.negated]  # fmt: skip
    closed = {ln.parent for ln in parsed.lines if ln.card == "@exit:exit"}
    assert [ln.text for ln in enters if ln.no not in closed] == []
    assert [ln.no for ln in parsed.lines if ln.kind == "raw" and ln.text == "exit"] == []
    back = cmp.side_from_text(r.text, kb, PID, "b")
    assert cmp.compare(cmp.Side(g, "a"), back, kb)["equal"]


def test_merge_containers() -> None:
    rl = canon.RLine
    lines = [
        rl(0, "router Base", opens=True, container=True),
        rl(1, "a"),
        rl(0, "exit", "exit"),
        rl(0, "router Base", opens=True, container=True),
        rl(1, "b"),
        rl(0, "exit", "exit"),
    ]
    assert [x.text for x in canon.merge_containers(lines)] == ["router Base", "a", "b", "exit"]


# ---------------------------------------------------------------- 翻译的换结构


def test_reshape_l3_and_net(kb) -> None:  # type: ignore[no-untyped-def]
    g = _graph(kb, _sample("classic-pe-basic.cfg"))
    h = g.copy()
    translate.reshape_l3(h, kb, "physical")
    assert "interface[to-P1]" not in h and "interface[1/1/1]/ipv4[10.0.12.1]" in h
    assert "interface[lag-1]/ipv4[10.0.13.5]" in h  # 绑定 LAG 的接口并到 LAG
    g2 = _graph(kb, _sample("classic-pe-routing-mgmt.cfg"))
    translate.reshape_l3(g2, kb, "physical")
    assert "interface[1/1/2.100]/dot1q_termination" in g2  # port 1/1/2:100 → 子接口
    translate.reshape_isis_net(g2, True)
    assert "isis.process[0]/net[49.0001.0102.5500.0002.00]" in g2  # area-id + Router ID 推出的系统 ID
    cs = cmp.side_from_text(
        (KB_ROOT / "samples/cisco-iosxe-asr920-synthetic/pe-asr920-02-igp-mgmt.cfg").read_text(encoding="utf-8"),
        kb,
        None,
        "c",
    ).graph
    translate.reshape_ospf_networks(cs)
    assert cs.nodes["interface[GigabitEthernet0/0/2]/ospf[_]/area"]["value"] == "10"
    translate.reshape_l3(cs, kb, "logical", lambda k: {"GigabitEthernet0/0/1": "1/1/1"}.get(k, k))
    assert cs.nodes["interface[if-GigabitEthernet0/0/1]/bind_port"]["value"] == "1/1/1"


def test_translate_nokia_to_huawei_and_back(kb) -> None:  # type: ignore[no-untyped-def]
    ifmap = {"1/1/1": "GigabitEthernet0/2/1", "lag-1": "Eth-Trunk1", "system": "LoopBack0"}
    r = translate.translate_text(_sample("classic-pe-basic.cfg"), kb, "huawei-atn-v800r025", PID, ifmap)
    assert r["verify"]["unexplained"] == 0
    assert "interface Eth-Trunk1" in r["text"] and " ip address 10.0.13.5 255.255.255.252 sub" in r["text"]
    # Nokia 的基本实例 0 → 进程 1（instance_keys；华为缺省进程 1 不写编号）
    assert "ospf router-id 10.255.0.1" in r["text"] and " area 0.0.0.0" in r["text"]
    src = (KB_ROOT / "samples/cisco-iosxe-asr920-synthetic/pe-asr920-02-igp-mgmt.cfg").read_text(encoding="utf-8")
    r2 = translate.translate_text(src, kb, PID, "cisco-iosxe-asr920-17.15", {"GigabitEthernet0/0/1": "1/1/1"})
    assert r2["verify"]["unexplained"] == 0
    assert '        interface "if-GigabitEthernet0/0/1"' in r2["text"].split("\n")
    # 华为 / Cisco 没有管理状态的 OSPF、NTP：按 assume 显式写 no shutdown 并告警
    assert any(
        w["kind"] == "default_differs" and w["params"]["schema"] == "ospf.process.shutdown" for w in r2["warnings"]
    )


# ---------------------------------------------------------------- 清理、变更、脚本检查、显示风格


def test_cleanup_change_script_check(kb) -> None:  # type: ignore[no-untyped-def]
    base = (KB_ROOT / "samples/change/nokia-base.cfg").read_text(encoding="utf-8")
    g = _graph(kb, base.replace('export "IBGP-OUT"', ""))
    r = cleanup.cleanup(g, kb)
    assert r["verify"]["ok"] and r["fallbacks"] == 0
    lines = r["script"].split("\n")
    assert lines[1:3] == ["exit all", "configure"] and "        begin" in lines and lines[0].startswith("# ")
    tgt = (KB_ROOT / "samples/change/nokia-add-vprn.cfg").read_text(encoding="utf-8")
    c = change.change_text(tgt, base, kb, rollback=False)
    assert c["verify"]["ok"]
    plain = [ln.strip() for ln in c["script_plain"].split("\n")]
    assert plain.index("shutdown") < plain.index("no vprn 3001")  # 删除业务前先 shutdown
    out = script_check.check_text(c["script"], kb, script_check.baseline_from_text(tgt, kb), "change")
    assert out["summary"]["errors"] == 0 and out["summary"]["unknown"] == 0


def test_terms_nokia_style(kb) -> None:  # type: ignore[no-untyped-def]
    t = terms.load(KB_ROOT, kb)
    assert terms.check(kb, t) == []
    assert t.label("vrf.instance", "RAN", "nokia") == "vprn RAN"
    assert t.label("rp.community_list", "X", "nokia") == t.label(
        "rp.community_list", "X", "huawei"
    )  # 没登记时用华为风格
    assert "nokia" in t.styles
