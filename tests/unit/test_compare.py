"""配置对比：值的规范化、有效值（显式 / 默认）、有序列表、改名识别、语义等价、原文与未识别行、跨厂商接口映射。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lmesh.core import analysis, compare

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
CISCO = "cisco-iosxe-asr920-17.15"
HUAWEI = "huawei-atn-v800r023"
ASR = (KB_ROOT / "samples" / "cisco-iosxe-asr920-synthetic" / "pe-asr920-01.cfg").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


def run(kb, a: str, b: str, pa: str = CISCO, pb: str = CISCO, **kw):  # type: ignore[no-untyped-def]
    return compare.compare(compare.side_from_text(a, kb, pa, "A"), compare.side_from_text(b, kb, pb, "B"), kb, **kw)


def kinds(r) -> set[tuple[str, str]]:  # type: ignore[no-untyped-def]
    return {(d["kind"], d["node"]) for d in r["diffs"]}


# ---------- 值的规范化 ----------


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("GE0/2/1", "GigabitEthernet0/2/1"),
        ("Gi0/0/1.100", "GigabitEthernet0/0/1.100"),
        ("gigabitethernet 0/0/1", "GigabitEthernet0/0/1"),
        ("LoopBack100", "Loopback100"),
        ("Lo0", "Loopback0"),
        ("Po1", "Port-channel1"),
        ("Eth-Trunk1.1302", "Eth-Trunk1.1302"),
        ("100GE0/2/24", "100GE0/2/24"),
        ("Vbdif1585", "Vbdif1585"),
        ("Te0/0/24", "TenGigabitEthernet0/0/24"),
    ],
)
def test_interface_name(raw: str, want: str) -> None:
    assert compare.interface_name(raw) == want


@pytest.mark.parametrize(
    ("node_type", "raw", "want"),
    [
        ("integer", "255.255.255.252", 30),
        ("mask", "255.255.0.0", 16),
        ("prefix", "10.0.0.0/255.255.255.0", "10.0.0.0/24"),
        ("prefix", "10.0.0.0 255.0.0.0", "10.0.0.0/8"),
        ("rd", "1.2:0100", "65538:100"),
        ("rd", "10.0.0.1:5", "10.0.0.1:5"),
        ("asn", "1.10", "65546"),
        ("enum", "Permit", "permit"),
        ("boolean", "enable", True),
        ("ipv4", "10.0.0.1", "10.0.0.1"),
    ],
)
def test_norm_scalar(node_type: str, raw: str, want: object) -> None:
    assert compare.norm_scalar(node_type, raw) == want


def test_norm_value_lists_and_interface_map() -> None:
    assert compare.norm_value("rd", ["65000:1"]) == "65000:1"  # 单元素列表等同于标量
    assert compare.norm_value("ref", ["B", "A"]) == compare.norm_value("ref", ["A", "B"])  # 无序
    assert compare.norm_value("ref", ["B", "A"], ordered=True) != compare.norm_value("ref", ["A", "B"], ordered=True)
    ifmap = {"gigabitethernet0/2/1": "GigabitEthernet0/0/1"}
    assert compare.norm_scalar("interface", "GE0/2/1.101", ifmap) == "GigabitEthernet0/0/1.101"


# ---------- 有效值 ----------


def test_self_compare_is_empty(kb) -> None:  # type: ignore[no-untyped-def]
    r = run(kb, ASR, ASR, include_raw=True)
    assert r["equal"] and r["summary"]["total"] == 0
    json.dumps(r)  # 结果可直接序列化


BASE = """hostname x
!
interface GigabitEthernet0/0/1
 description up
{extra} ip address 10.0.0.1 255.255.255.0
!
end
"""


def test_explicit_default_equals_implicit(kb) -> None:  # type: ignore[no-untyped-def]
    a = BASE.format(extra="")
    assert run(kb, a, BASE.format(extra=" mtu 1500\n no shutdown\n"))["equal"]
    r = run(kb, a, BASE.format(extra=" mtu 9000\n"))
    (d,) = r["diffs"]
    assert (d["kind"], d["node"], d["schema"], d["domain"]) == (
        "changed",
        "interface[GigabitEthernet0/0/1]/mtu",
        "interface.mtu",
        "interface",
    )
    assert d["a"]["value"] == 1500 and d["a"]["origin"] == "default" and d["a"]["lines"] == []
    assert d["b"]["value"] == 9000 and d["b"]["origin"] == "explicit" and d["b"]["lines"] == [5]


def test_cross_vendor_uses_each_profile_and_interface_map(kb) -> None:  # type: ignore[no-untyped-def]
    hw = "sysname x\n#\ninterface GigabitEthernet0/2/1\n ip address 10.0.0.1 255.255.255.252\n#\nreturn\n"
    cs = "hostname x\n!\ninterface GigabitEthernet0/0/1\n ip address 10.0.0.1 255.255.255.252\n mtu 1500\n!\nend\n"
    r = run(kb, hw, cs, HUAWEI, CISCO, interface_map={"GE0/2/1": "Gi0/0/1"})
    nodes = {d["node"] for d in r["diffs"]}
    assert not any(n.startswith("interface[") and "/" not in n for n in nodes)  # 接口按映射配对
    assert "interface[GigabitEthernet0/0/1]/mtu" not in nodes  # 华为用自己的默认值 1500
    assert not any("/ipv4[" in n for n in nodes)  # 地址与掩码长度一致
    assert r["options"]["compare_ext"] is False and r["options"]["interface_map"] == 1
    # 只有 Cisco Profile 定义了默认值的属性（negotiation）两边不可比：不算差异，单独列出
    neg = [x for x in r["default_only"] if x["schema"] == "interface.negotiation"]
    assert neg and neg[0]["side"] == "b" and r["summary"]["default_only"] == len(r["default_only"])
    assert not any(n.endswith("/negotiation") for n in nodes)
    # 没有映射时接口名不同，整个接口一删一增
    r2 = run(kb, hw, cs, HUAWEI, CISCO)
    assert ("removed", "interface[GigabitEthernet0/2/1]") in kinds(r2)


# ---------- 有序列表、语义等价 ----------

RP = """hostname x
!
ip prefix-list P1 seq 10 permit 10.0.0.0/8
ip prefix-list P1 seq 20 permit 172.16.0.0/12
!
route-map RM permit 10
 match ip address prefix-list P1
!
route-map RM deny 20
!
end
"""


def test_order_of_keyed_entries(kb) -> None:  # type: ignore[no-untyped-def]
    swapped_lines = RP.replace(
        "ip prefix-list P1 seq 10 permit 10.0.0.0/8\nip prefix-list P1 seq 20 permit 172.16.0.0/12",
        "ip prefix-list P1 seq 20 permit 172.16.0.0/12\nip prefix-list P1 seq 10 permit 10.0.0.0/8",
    )
    assert run(kb, RP, swapped_lines)["equal"]  # 序号不变、只是书写顺序不同
    swapped_seq = RP.replace("seq 10 permit 10.0.0.0/8", "seq 10 permit 172.16.0.0/12").replace(
        "seq 20 permit 172.16.0.0/12", "seq 20 permit 10.0.0.0/8"
    )
    r = run(kb, RP, swapped_seq)  # 有序列表（ordered）：同一序号的内容变了就是差异
    assert ("changed", "rp.prefix_list[P1]/entry[10]/prefix") in kinds(r)
    assert ("changed", "rp.prefix_list[P1]/entry[20]/prefix") in kinds(r)


VRF = """hostname x
!
vrf definition V
 rd 65000:1
 address-family ipv4
{rt} exit-address-family
!
end
"""


def test_rt_both_equals_import_plus_export(kb) -> None:  # type: ignore[no-untyped-def]
    split = VRF.format(rt="  route-target export 65000:1\n  route-target import 65000:1\n")
    both = VRF.format(rt="  route-target both 65000:1\n")
    assert run(kb, split, both)["equal"]
    only_export = VRF.format(rt="  route-target export 65000:1\n")
    r = run(kb, only_export, both)
    assert kinds(r) == {("added", "vrf.instance[V]/af[ipv4]/rt[value=65000:1,direction=import]")}


# ---------- 改名识别 ----------


def test_rename_chain_and_references(kb) -> None:  # type: ignore[no-untyped-def]
    b = RP.replace("RM", "RM2").replace("P1", "P9")
    bgp = (
        "router bgp 1\n neighbor 10.0.0.2 remote-as 2\n neighbor 10.0.0.2 route-map RM out\n"  # 未映射命令（ext）
        " address-family ipv4\n  neighbor 10.0.0.2 activate\n  neighbor 10.0.0.2 route-map RM out\n"
        " exit-address-family\n"
    )
    a, b = RP + bgp, b + bgp.replace("RM", "RM2")
    r = run(kb, a, b)
    assert kinds(r) == {("renamed", "rp.policy[RM2]"), ("renamed", "rp.prefix_list[P9]")}
    d = next(x for x in r["diffs"] if x["node"] == "rp.policy[RM2]")
    assert (d["from"], d["to"], d["similarity"]) == ("RM", "RM2", 1.0)
    assert d["a"]["cid"] == "rp.policy[RM]" and d["a"]["value"] == "RM"
    assert "bgp.instance[1]/bgp.af[afi=ipv4,vrf=]/peer[10.0.0.2]/export_policy" in d["related"]
    assert {x["schema"] for x in r["renames"]} == {"rp.policy", "rp.prefix_list"}


def test_rename_threshold(kb) -> None:  # type: ignore[no-untyped-def]
    b = RP.replace("route-map RM", "route-map RMX").replace("route-map RMX deny 20", "route-map RMX permit 20")
    r = run(kb, RP, b)  # 默认只认内容完全相同：内容也变了，按删除 + 新增报
    assert kinds(r) == {("removed", "rp.policy[RM]"), ("added", "rp.policy[RMX]")}
    r = run(kb, RP, b, rename_threshold=0.5)
    assert kinds(r) == {("renamed", "rp.policy[RMX]"), ("changed", "rp.policy[RMX]/node[20]/action")}
    with pytest.raises(compare.CompareError):
        run(kb, RP, b, rename_threshold=0)


def test_ambiguous_rename_not_guessed(kb) -> None:  # type: ignore[no-untyped-def]
    a = "hostname x\n!\nip prefix-list A seq 10 permit 10.0.0.0/8\nip prefix-list B seq 10 permit 10.0.0.0/8\n!\nend\n"
    b = a.replace("list A", "list C").replace("list B", "list D")
    r = run(kb, a, b)
    assert not r["renames"] and {d["kind"] for d in r["diffs"]} == {"removed", "added"}


def test_related_diffs(kb) -> None:  # type: ignore[no-untyped-def]
    b = RP.replace("ip prefix-list P1 seq 20 permit 172.16.0.0/12\n", "ip prefix-list P2 seq 5 permit 192.168.0.0/16\n")
    b = b.replace("ip prefix-list P1 seq 10 permit 10.0.0.0/8\n", "").replace("prefix-list P1\n", "prefix-list P2\n")
    r = run(kb, RP, b)
    attr = "rp.policy[RM]/node[10]/match_prefix_list"
    by = {(d["kind"], d["node"]): d for d in r["diffs"]}
    assert set(by[("changed", attr)]["related"]) == {"rp.prefix_list[P1]", "rp.prefix_list[P2]"}
    assert by[("removed", "rp.prefix_list[P1]")]["related"] == [attr]
    assert by[("removed", "rp.prefix_list[P1]")]["count"] == 6  # 两个条目，各有条目对象 + 动作 + 前缀


# ---------- 原文行、未识别行、功能域过滤、统计 ----------


def test_raw_lines_and_unknown(kb) -> None:  # type: ignore[no-untyped-def]
    a = BASE.format(extra="") + ""
    b = (
        BASE.format(extra="")
        .replace("hostname x", "hostname y")
        .replace(" description up\n", " description up\n ip address 10.0.0.9 255.255.255.0 bogus extra\n")
    )
    r = run(kb, a, b)
    assert r["equal"]  # 原文行默认不比
    assert r["unknown"]["b"] == [
        {"line": 5, "text": "ip address 10.0.0.9 255.255.255.0 bogus extra", "owner": "interface[GigabitEthernet0/0/1]"}
    ]
    assert r["summary"]["unknown"] == {"a": 0, "b": 1}
    r = run(kb, a, b, include_raw=True)
    assert kinds(r) == {("removed", "raw[hostname x]"), ("added", "raw[hostname y]")}
    assert {d["node_kind"] for d in r["diffs"]} == {"raw"} and r["summary"]["by_object"][0]["object"] == ""


def test_domain_filter_and_summary(kb) -> None:  # type: ignore[no-untyped-def]
    b = ASR.replace(" mtu 9216\n ip address 10.1.0.2", " mtu 9000\n ip address 10.1.0.2").replace(
        "  route-target import 64512:1\n", ""
    )
    r = run(kb, ASR, b)
    s = r["summary"]
    assert s["total"] == 2 and s["by_kind"]["changed"] == 1 and s["by_kind"]["removed"] == 1
    assert s["by_domain"]["interface"]["changed"] == 1 and s["by_domain"]["vrf"]["removed"] == 1
    assert {o["object"] for o in s["by_object"]} == {"interface[GigabitEthernet0/0/0]", "vrf.instance[RAN-2G]"}
    r = run(kb, ASR, b, domain="vrf")
    assert [d["domain"] for d in r["diffs"]] == ["vrf"] and r["options"]["domain"] == "vrf"
    with pytest.raises(compare.CompareError) as e:
        run(kb, ASR, b, domain="nope")
    assert e.value.key == "compare.bad_domain" and e.value.kind == "param"


def test_ext_commands_compared_within_family(kb) -> None:  # type: ignore[no-untyped-def]
    atn = (KB_ROOT / "samples" / "huawei-atn-v800r023" / "atn-access-01.cfg").read_text(encoding="utf-8")
    b = atn.replace("  nexthop recursive-lookup delay 1\n", "  nexthop recursive-lookup delay 5\n")
    r = run(kb, atn, b, HUAWEI, HUAWEI)
    (d,) = r["diffs"]
    assert d["kind"] == "changed" and d["node_kind"] == "ext" and d["domain"] == "bgp"
    assert d["a"]["value"] != d["b"]["value"]


# ---------- 接口映射表文件 ----------


def test_load_interface_map(tmp_path: Path) -> None:
    j = tmp_path / "m.json"
    j.write_text('{"GE0/2/1": "Gi0/0/1"}', encoding="utf-8")
    assert compare.load_interface_map(j) == {"GE0/2/1": "Gi0/0/1"}
    t = tmp_path / "m.txt"
    t.write_text("# A B\nGE0/2/1  Gi0/0/1\nGE0/2/2,Gi0/0/2\n", encoding="utf-8")
    assert compare.load_interface_map(t) == {"GE0/2/1": "Gi0/0/1", "GE0/2/2": "Gi0/0/2"}
    y = tmp_path / "m.yaml"
    y.write_text("GE0/2/1: Gi0/0/1\n", encoding="utf-8")
    assert compare.load_interface_map(y) == {"GE0/2/1": "Gi0/0/1"}
    bad = tmp_path / "bad.txt"
    bad.write_text("a b c\n", encoding="utf-8")
    with pytest.raises(compare.CompareError) as e:
        compare.load_interface_map(bad)
    assert e.value.key == "compare.ifmap_invalid"
    with pytest.raises(compare.CompareError) as e:
        compare.load_interface_map(tmp_path / "none.json")
    assert e.value.kind == "not_found"


def test_versions_and_sides_from_db(tmp_root: Path, kb) -> None:  # type: ignore[no-untyped-def]
    """同一设备导入两次 → 版本列表新的在前 → 按版本、按设备（最新版本）取图对比。"""
    from lmesh.core import importer, store

    url = f"sqlite:///{(tmp_root / 'data' / 'c.db').as_posix()}"
    store.upgrade(url)
    assert compare.versions(url, 999) is None
    changed = ASR.replace(" mtu 9216\n ip address 10.1.0.2", " mtu 9000\n ip address 10.1.0.2")
    res = importer.import_sources([("v1.cfg", ASR.encode()), ("v2.cfg", changed.encode())], url, kb_root=KB_ROOT)
    assert all(r.ok for r in res)
    dev_id = compare.device_id_by_name(url, res[0].device)
    assert dev_id is not None and compare.device_id_by_name(url, "nope") is None
    vers = compare.versions(url, dev_id)
    assert vers is not None and [v["seq"] for v in vers] == [2, 1] and vers[0]["latest"]
    old = compare.side_from_version(url, kb, vers[1]["id"], device_id=dev_id)
    new = compare.side_from_device(url, kb, dev_id)
    assert new.version_id == vers[0]["id"] and old.label.endswith(f"@{vers[1]['id']}")
    r = compare.compare(old, new, kb)
    assert kinds(r) == {("changed", "interface[GigabitEthernet0/0/0]/mtu")}
    assert r["a"]["version_id"] == vers[1]["id"] and r["b"]["device_id"] == dev_id
    with pytest.raises(compare.CompareError) as e:
        compare.side_from_version(url, kb, 999)
    assert e.value.key == "compare.version_not_found" and e.value.kind == "not_found"
    with pytest.raises(compare.CompareError):
        compare.side_from_version(url, kb, vers[0]["id"], device_id=dev_id + 1)  # 版本不属于该设备
