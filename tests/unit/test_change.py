"""增量变更脚本（M4-3）与影响分析（M4-4）：差异来源、命令与顺序、副作用、取消写法、脚本分块、模拟验证、影响范围、报告。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmesh.core import analysis, change, compare, impact, report_change

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
SAMPLES = KB_ROOT / "samples"
CHG = SAMPLES / "change"


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


def _read(name: str) -> str:
    return (CHG / name).read_text(encoding="utf-8")


def _side(kb, name: str) -> compare.Side:  # type: ignore[no-untyped-def]
    return compare.side_from_text(_read(name), kb, None, Path(name).stem)


# ---------- 差异与命令 ----------


def test_equal_no_ops(kb) -> None:  # type: ignore[no-untyped-def]
    r = change.change_text(_read("atn-base.cfg"), _read("atn-base.cfg"), kb)
    assert r["equal"] and r["ops"] == []
    assert r["script_plain"].split() == ["system-view", "commit", "return"]
    assert r["verify"]["ok"]


def test_default_only_difference_not_sent(kb) -> None:  # type: ignore[no-untyped-def]
    """显式写出默认值（mtu 1500、timer keepalive 60 hold 180 等）与不写有效值相同：不下发。"""
    a = (SAMPLES / "huawei-atn-v800r023" / "atn-access-01.cfg").read_text(encoding="utf-8")
    b = (SAMPLES / "compare" / "atn-defaults.cfg").read_text(encoding="utf-8")
    r = change.change_text(a, b, kb, profile="huawei-atn-v800r023", rollback=False, with_impact=False)
    assert r["ops"] == [], [d["text"] for d in r["ops"]]


def test_family_mismatch(kb) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(change.ChangeError) as e:
        change.change(_side(kb, "atn-base.cfg"), _side(kb, "asr920-base.cfg"), kb)
    assert e.value.key == "change.family_mismatch"


def test_huawei_blocks_and_commit(kb) -> None:  # type: ignore[no-untyped-def]
    r = change.change_text(_read("atn-base.cfg"), _read("atn-add-vrf.cfg"), kb, rollback=False)
    lines = r["script_plain"].splitlines()
    assert lines[0] == "system-view" and lines[-2:] == ["commit", "return"]
    i = lines.index("ip vpn-instance IOT")
    assert lines[i + 1] == " ipv4-family" and lines[i + 2].startswith("  route-distinguisher")
    assert "quit" in [ln.strip() for ln in lines]
    # 带说明的脚本：每条命令前一行说明（华为用 # 开头）
    annotated = r["script"].splitlines()
    assert any(ln.strip().startswith("# [1]") for ln in annotated)


def test_cisco_blocks(kb) -> None:  # type: ignore[no-untyped-def]
    r = change.change_text(_read("asr920-base.cfg"), _read("asr920-add-vrf.cfg"), kb, rollback=False)
    lines = r["script_plain"].splitlines()
    assert lines[0] == "configure terminal" and lines[-1] == "end"
    assert " exit-address-family" in lines  # 离开地址族视图按 Cisco 习惯
    assert any(ln.strip().startswith("! [1]") for ln in r["script"].splitlines())


def test_dependency_reasons(kb) -> None:  # type: ignore[no-untyped-def]
    r = change.change_text(_read("atn-base.cfg"), _read("atn-add-vrf.cfg"), kb, rollback=False)
    bind = next(d for d in r["ops"] if d["text"] == "ip binding vpn-instance IOT")
    kinds = {(a["kind"], a["node"]) for a in bind["after"]}
    assert ("reference", "vrf.instance[IOT]") in kinds or ("prerequisite", "vrf.instance[IOT]") in kinds
    assert bind["action"] == "add" and bind["context"] == ["interface GigabitEthernet0/2/1.300"]


def test_side_effect_restore_and_verify_catches_missing(kb) -> None:  # type: ignore[no-untyped-def]
    a, b = _side(kb, "atn-base.cfg"), _side(kb, "atn-bind-vpn.cfg")
    r = change.change(a, b, kb, rollback=False)
    acts = [(d["action"], d["text"]) for d in r["ops"]]
    assert acts == [("add", "ip binding vpn-instance OAM"), ("side_effect", "ip address 10.3.0.1 255.255.255.252")]
    assert r["ops"][1]["risk"] == "high" and "side_effect" in r["ops"][1]["risk_reasons"]
    assert r["verify"]["ok"]
    # 去掉补发的那条命令：模拟执行时副作用删除了接口地址，验证必须失败
    p = change._Planner(a.graph, b.graph, kb)
    ops = [op for op in p.run() if op.action != "side_effect"]
    v = change.verify(p, ops)
    assert not v["ok"] and not v["equal"]


def test_new_subinterface_keeps_ext_lines_and_binds_vpn_first(kb) -> None:  # type: ignore[no-untyped-def]
    """REQ-055-15、16：新建子接口里未映射的命令（statistic enable）也要下发；目标配置先写地址后绑 VPN 时，
    脚本仍先绑定 VPN 再配地址（绑定会清掉地址），并且地址命令依赖绑定命令。"""
    cur = "ip vpn-instance V1\n ipv4-family\n  route-distinguisher 1:1\n#\ninterface GigabitEthernet0/1/1\n undo shutdown\n#\n"
    tgt = cur + (
        "interface GigabitEthernet0/1/1.1599\n vlan-type dot1q 1599\n ip address 10.1.1.1 255.255.255.248\n"
        " ip binding vpn-instance V1\n statistic enable\n#\n"
    )
    r = change.change_text(cur, tgt, kb, "huawei-atn-v800r025", rollback=False, with_impact=False)
    texts = [d["text"] for d in r["ops"]]
    assert "statistic enable" in texts and r["verify"]["ok"]
    bind, addr = texts.index("ip binding vpn-instance V1"), texts.index("ip address 10.1.1.1 255.255.255.248")
    assert bind < addr
    assert any(x["kind"] == "side_effect" and x["seq"] == r["ops"][bind]["seq"] for x in r["ops"][addr]["after"])


def test_modify_records_current_line(kb) -> None:  # type: ignore[no-untyped-def]
    """REQ-055-20：修改已有取值的命令带上当前配置里被改的行号（界面“当前配置第 N 行”）。"""
    cur = "interface GigabitEthernet0/1/9\n description X\n mtu 1500\n#\n"
    r = change.change_text(cur, cur.replace("mtu 1500", "mtu 9208"), kb, "huawei-atn-v800r025", rollback=False)
    assert [(o["action"], o["lines"]) for o in r["ops"]] == [("modify", {"current": [3], "target": [3]})]


def test_verify_catches_bad_order(kb) -> None:  # type: ignore[no-untyped-def]
    """先删前缀列表、后改路由策略的引用：模拟执行发现“删除了还被引用的对象”。"""
    a, b = _side(kb, "atn-base.cfg"), _side(kb, "atn-policy-rename.cfg")
    p = change._Planner(a.graph, b.graph, kb)
    ops = p.run()
    bad = sorted(ops, key=lambda op: 0 if op.action == "delete" else 1)
    v = change.verify(p, bad)
    assert not v["ok"] and any(x["kind"] == "still_referenced" for x in v["order_violations"])


def test_undo_prefers_key(kb) -> None:  # type: ignore[no-untyped-def]
    r = change.change_text(_read("atn-base.cfg"), _read("atn-acl.cfg"), kb, rollback=False)
    assert "undo rule 10" in [d["text"] for d in r["ops"]]
    r2 = change.change_text(_read("asr920-base.cfg"), _read("asr920-del-peer.cfg"), kb, rollback=False)
    assert "no neighbor 10.255.0.2" in [d["text"] for d in r2["ops"]]


def test_undo_first_replaces_object(kb) -> None:  # type: ignore[no-untyped-def]
    r = change.change_text(_read("asr920-base.cfg"), _read("asr920-acl.cfg"), kb, rollback=False)
    texts = [d["text"] for d in r["ops"]]
    i, j = texts.index("no 10"), texts.index("10 permit tcp 10.90.0.0 0.0.0.255 host 10.255.0.22 eq 22")
    assert i < j
    assert any(a["kind"] == "undo_first" for a in r["ops"][j]["after"])


def test_style_only_affects_labels(kb) -> None:  # type: ignore[no-untyped-def]
    from lmesh.core import terms

    a, b = _side(kb, "atn-base.cfg"), _side(kb, "atn-bind-vpn.cfg")
    hw = change.change(a, b, kb, rollback=False, namer=terms.namer(KB_ROOT, kb, "huawei"))
    cs = change.change(a, b, kb, rollback=False, namer=terms.namer(KB_ROOT, kb, "cisco"))
    assert hw["script_plain"] == cs["script_plain"]
    assert hw["ops"][0]["label"] != cs["ops"][0]["label"]


def test_rollback_restores(kb) -> None:  # type: ignore[no-untyped-def]
    r = change.change_text(_read("atn-base.cfg"), _read("atn-del-peer.cfg"), kb)
    rb = [d["text"] for d in r["rollback"]["ops"]]
    assert rb.index("peer 10.255.0.102 as-number 65000") < rb.index("peer 10.255.0.102 enable")
    assert r["rollback"]["verify"]["ok"]


def test_negated_set_command_simulated(kb) -> None:  # type: ignore[no-untyped-def]
    """回滚里的 undo shutdown（取消形式的设置命令）在模拟执行中能解析，不报 unparsable。"""
    r = change.change_text(_read("atn-base.cfg"), _read("atn-shutdown.cfg"), kb)
    assert "undo shutdown" in [d["text"] for d in r["rollback"]["ops"]]
    assert r["verify"]["ok"] and r["rollback"]["verify"]["ok"], r["rollback"]["verify"]


def test_plan_entry(kb) -> None:  # type: ignore[no-untyped-def]
    a, b = _side(kb, "atn-base.cfg"), _side(kb, "atn-bind-vpn.cfg")
    p = change.plan(a.graph, b.graph, kb, "huawei-atn-v800r025")
    assert set(p) >= {"script", "rollback", "items", "verify", "rollback_verify"}
    assert p["items"][1]["action"] == "side_effect" and p["verify"]["ok"] and p["rollback_verify"]["ok"]
    assert p["rollback"].startswith("system-view")


# ---------- 影响分析 ----------


def test_impact_prefix_list_up(kb) -> None:  # type: ignore[no-untyped-def]
    g = _side(kb, "atn-base.cfg").graph
    r = impact.analyze(g, kb, ["rp.prefix_list[LOOPBACKS]"])
    nodes = {x["node"] for x in r["objects"]}
    assert "rp.policy[EXPORT-LOOPBACK]" in nodes
    biz = {b["node"]: b for b in r["business"]}
    peer = "bgp.instance[65000]/bgp.af[afi=ipv4,vrf=]/peer[RR]"
    assert peer in biz and biz[peer]["type"] == "peer"
    assert biz[peer]["path"][0] == "rp.prefix_list[LOOPBACKS]" and biz[peer]["path"][-1] == peer
    assert "bgp.instance[65000]/bgp.peer[10.255.0.101]" in biz  # 对等体组的成员
    assert set(r["by_domain"]) >= {"routing-policy", "bgp"}


def test_impact_vrf_key_reference(kb) -> None:  # type: ignore[no-untyped-def]
    g = _side(kb, "atn-base.cfg").graph
    r = impact.analyze(g, kb, ["vrf.instance[RAN]"])
    nodes = {x["node"] for x in r["objects"]}
    assert "interface[GigabitEthernet0/2/1.101]" in nodes
    assert "bgp.instance[65000]/bgp.af[afi=ipv4,vrf=RAN]" in nodes  # 键字段引用


def test_impact_down_and_partial_name(kb) -> None:  # type: ignore[no-untyped-def]
    g = _side(kb, "atn-base.cfg").graph
    r = impact.analyze(g, kb, ["rp.policy[EXPORT-LOOPBACK]"], "down")
    assert "rp.prefix_list[LOOPBACKS]" in {x["node"] for x in r["objects"]}
    r2 = impact.analyze(g, kb, ["GigabitEthernet0/2/1.101"], "both")
    assert r2["seeds"][0]["node"] == "interface[GigabitEthernet0/2/1.101]"


def test_impact_loopback_source_and_own_protocol_settings(kb) -> None:  # type: ignore[no-untyped-def]
    """REQ-055-17、18：对等体组靠 connect-interface 建连，环回口的影响能到对等体组与组内对等体；
    接口自身的 OSPF / MPLS 设置算作受影响。"""
    g = _side(kb, "atn-base.cfg").graph
    up = impact.analyze(g, kb, ["interface[LoopBack0]"], "up")
    hit = {x["node"] for x in up["nodes"]}
    assert "bgp.instance[65000]/bgp.peer_group[RR]" in hit
    assert any(e["edge"] == "reference" and "update_source" in e["node"] for e in up["nodes"])
    text = "interface GigabitEthernet0/1/9\n ip address 10.1.1.1 255.255.255.252\n ospf network-type p2p\n mpls\n mpls ldp\n#\n"
    g2 = compare.side_from_text(text, kb, "huawei-atn-v800r025", "x").graph
    own = {x["node"] for x in impact.analyze(g2, kb, ["interface[GigabitEthernet0/1/9]"], "up")["nodes"]}
    assert {"interface[GigabitEthernet0/1/9]/ospf[_]", "interface[GigabitEthernet0/1/9]/mpls[_]"} <= own


def test_impact_errors(kb) -> None:  # type: ignore[no-untyped-def]
    g = _side(kb, "atn-base.cfg").graph
    with pytest.raises(impact.ImpactError) as e:
        impact.analyze(g, kb, ["nope[x]"])
    assert e.value.key == "impact.node_not_found" and e.value.kind == "not_found"
    with pytest.raises(impact.ImpactError) as e:
        impact.analyze(g, kb, ["rp.prefix_list[LOOPBACKS]"], "sideways")
    assert e.value.key == "impact.bad_direction"


def test_change_impact(kb) -> None:  # type: ignore[no-untyped-def]
    r = change.change_text(_read("atn-base.cfg"), _read("atn-policy-rename.cfg"), kb)
    biz = {b["node"] for b in r["impact"]["business"]}
    assert "bgp.instance[65000]/bgp.af[afi=ipv4,vrf=]/peer[RR]" in biz


# ---------- 报告 ----------


@pytest.mark.parametrize("lang,fmt", [("zh-CN", "html"), ("en", "md")])
def test_change_report(kb, lang: str, fmt: str) -> None:  # type: ignore[no-untyped-def]
    r = change.change_text(_read("atn-base.cfg"), _read("atn-bind-vpn.cfg"), kb)
    rep = report_change.change_report(r, lang, fmt)
    title = "配置变更报告" if lang == "zh-CN" else "Configuration Change Report"
    assert title in rep.content and "ip binding vpn-instance OAM" in rep.content
    assert rep.filename.endswith(f".{lang}.{fmt}")
