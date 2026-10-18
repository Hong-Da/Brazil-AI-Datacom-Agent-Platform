"""割接迁移（M4-5）：接口分类、端口清单、映射建议（依据与置信度）、管理口、聚合口、合并现有配置与冲突、步骤、映射表 CSV。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmesh.core import analysis, migration
from lmesh.core import graph as graphmod

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
CISCO = "cisco-iosxe-asr920-17.15"
HUAWEI = "huawei-atn-v800r025"

OLD_HW = """#
sysname OLD-ATN
#
interface Ethernet0/0/0
 ip address 192.168.1.2 255.255.255.0
#
interface Eth-Trunk2
 ip address 10.0.9.1 255.255.255.252
#
interface GigabitEthernet0/2/1
 description UPLINK
 ip address 10.0.0.1 255.255.255.252
#
interface GigabitEthernet0/2/2
 eth-trunk 2
#
interface GigabitEthernet0/2/3
 eth-trunk 2
#
interface GigabitEthernet0/2/4.100
 vlan-type dot1q 100
 ip address 10.0.1.1 255.255.255.252
#
interface LoopBack0
 ip address 10.255.0.1 255.255.255.255
#
ip route-static 0.0.0.0 0.0.0.0 10.0.0.2
ip route-static 192.168.0.0 255.255.0.0 Ethernet0/0/0 192.168.1.1
#
return
"""


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


def graph(kb, text: str, profile: str):  # type: ignore[no-untyped-def]
    res = analysis.parse_text(text, kb, profile)
    return graphmod.build(res.parsed, kb, res.profile, "dev")


# ---------- 接口名与端口清单 ----------


def test_parse_port_classes_and_speed() -> None:
    p = migration.parse_port("GE0/2/1")
    assert (p.canon, p.cls, p.speed, p.index) == ("GigabitEthernet0/2/1", "physical", 1, 1)
    assert migration.parse_port("100GE0/2/24").speed == 100
    assert migration.parse_port("Te0/0/12").speed == 10
    assert migration.parse_port("Eth-Trunk1").cls == "lag"
    assert migration.parse_port("Port-channel1").cls == "lag"
    assert migration.parse_port("LoopBack0").cls == migration.parse_port("Loopback0").cls == "loopback"
    assert migration.parse_port("Vbdif10").cls == migration.parse_port("BDI10").cls == "bdi"
    assert migration.parse_port("Null0").cls == "null"
    assert migration.parse_port("Ethernet0/0/0", ["^Ethernet0/0/0$"]).cls == "management"


def test_expand_range_and_inventory(kb) -> None:  # type: ignore[no-untyped-def]
    assert migration._expand("Gi0/0/{0-2}") == ["Gi0/0/0", "Gi0/0/1", "Gi0/0/2"]
    assert "ASR-920-12CZ-A" in migration.models(kb, CISCO)
    inv = migration.port_inventory(kb, CISCO)
    assert inv is not None
    ports = migration._models_ports(inv, "ASR-920-12CZ-A")
    assert len(ports) == 14 and ports[-1] == ("TenGigabitEthernet0/0/13", 10.0)
    assert migration.port_inventory(kb, HUAWEI) is None  # 华为暂无清单：用新设备现有配置或按类型换写法


# ---------- 映射建议 ----------


def test_suggest_basis_confidence_and_management(kb) -> None:  # type: ignore[no-untyped-def]
    g = graph(kb, OLD_HW, HUAWEI)
    s = migration.suggest_map(g, kb, HUAWEI, CISCO, {"GE0/2/3": "TenGigabitEthernet0/0/13"}, model="ASR-920-12CZ-A")
    m = {r["source"]: r for r in s["map"]}
    assert m["GigabitEthernet0/2/3"]["basis"] == "user" and m["GigabitEthernet0/2/3"]["confidence"] == 1.0
    assert m["GigabitEthernet0/2/1"]["target"] == "GigabitEthernet0/0/1"
    assert m["GigabitEthernet0/2/1"]["basis"] == "same_index"
    assert m["Eth-Trunk2"]["target"] == "Port-channel2" and m["Eth-Trunk2"]["basis"] == "logical"
    assert m["LoopBack0"]["target"] == "Loopback0"
    # 只有子接口的主接口也参与映射，子接口列在 subinterfaces
    assert m["GigabitEthernet0/2/4"]["subinterfaces"] == ["GigabitEthernet0/2/4.100"]
    assert {u["source"]: u["reason"] for u in s["unmapped"]} == {"Ethernet0/0/0": "management"}
    kinds = {w["kind"] for w in s["warnings"]}
    assert {"speed_mismatch", "mgmt_not_migrated"} <= kinds
    assert s["inventory"] == {"source": "kb", "model": "ASR-920-12CZ-A", "ports": 14, "verified": False}


def test_suggest_without_inventory_converts_type(kb) -> None:  # type: ignore[no-untyped-def]
    old = graph(
        kb, "hostname R\n!\ninterface GigabitEthernet0/0/5\n ip address 10.0.0.1 255.255.255.0\n!\nend\n", CISCO
    )
    s = migration.suggest_map(old, kb, CISCO, HUAWEI)
    assert s["map"][0]["target"] == "GigabitEthernet0/0/5" and s["map"][0]["basis"] == "type_convert"
    assert s["inventory"]["source"] == "none"
    assert "port_inventory_missing" in {w["kind"] for w in s["warnings"]}


def test_suggest_default_model_is_reported(kb) -> None:  # type: ignore[no-untyped-def]
    s = migration.suggest_map(graph(kb, OLD_HW, HUAWEI), kb, HUAWEI, CISCO)
    assert s["inventory"]["model"] == "ASR-920-12CZ-A"
    assert "port_inventory_assumed" in {w["kind"] for w in s["warnings"]}


def test_suggest_errors(kb) -> None:  # type: ignore[no-untyped-def]
    g = graph(kb, OLD_HW, HUAWEI)
    with pytest.raises(migration.MigrateError) as e:
        migration.suggest_map(g, kb, HUAWEI, CISCO, model="NOPE")
    assert e.value.key == "migrate.model_unknown"
    with pytest.raises(migration.MigrateError):
        migration.suggest_map(g, kb, HUAWEI, "nope")


def test_user_exclude_and_duplicate_target(kb) -> None:  # type: ignore[no-untyped-def]
    g = graph(kb, OLD_HW, HUAWEI)
    s = migration.suggest_map(
        g, kb, HUAWEI, CISCO, {"GE0/2/1": "-", "GE0/2/2": "Gi0/0/7", "GE0/2/3": "Gi0/0/7"}, model="ASR-920-12CZ-A"
    )
    reasons = {u["source"]: u["reason"] for u in s["unmapped"]}
    assert reasons["GigabitEthernet0/2/1"] == "user_excluded"
    assert reasons["GigabitEthernet0/2/3"] == "duplicate_target"
    assert "duplicate_target" in {w["kind"] for w in s["warnings"]}


# ---------- 迁移 ----------


def test_migrate_lag_renumber_mgmt_and_refs(kb) -> None:  # type: ignore[no-untyped-def]
    g = graph(kb, OLD_HW, HUAWEI)
    r = migration.migrate(g, kb, HUAWEI, CISCO, {"Eth-Trunk2": "Port-channel5"}, model="ASR-920-12CZ-A")
    assert r["verify"]["checked"] and r["verify"]["unexplained"] == 0
    text = r["text"]
    assert "interface Port-channel5" in text and "channel-group 5" in text
    assert "Ethernet0/0/0" not in text and "192.168.1.2" not in text  # 管理口与引用它的静态路由不迁移
    assert "interface GigabitEthernet0/0/4.100" in text  # 子接口跟随主接口
    kinds = {w["kind"] for w in r["warnings"]}
    assert {"lag_renumbered", "mgmt_not_migrated", "ref_not_migrated", "subinterfaces_follow"} <= kinds
    assert r["delta"] == r["text"] and r["merge"] is None
    assert r["script"] == {"available": False, "reason": "change_module_unavailable"} or r["script"]["available"]


def test_migrate_merge_conflicts_keep_and_migrate(kb) -> None:  # type: ignore[no-untyped-def]
    old = graph(kb, "hostname OLD\n!\ninterface GigabitEthernet0/0/1\n description UP\n mtu 9000\n!\nend\n", CISCO)
    existing = "#\nsysname NEW\n#\ninterface GigabitEthernet0/2/1\n mtu 1600\n#\nreturn\n"
    tg = migration.target_graph_from_text(existing, kb, HUAWEI)
    r = migration.migrate(old, kb, CISCO, HUAWEI, {"Gi0/0/1": "GigabitEthernet0/2/1"}, tg)
    assert r["verify"]["unexplained"] == 0
    assert r["merge"]["conflicts"] >= 1 and " mtu 9000" in r["delta"] and "sysname NEW" not in r["delta"]
    assert "sysname NEW" in r["text"]
    conflict = next(w for w in r["warnings"] if w["kind"] == "target_conflict" and "mtu" in w["params"]["target_node"])
    assert conflict["params"]["resolution"] == "migrated"
    k = migration.migrate(old, kb, CISCO, HUAWEI, {"Gi0/0/1": "GigabitEthernet0/2/1"}, tg, on_conflict="keep")
    assert k["merge"]["kept"] >= 1 and " mtu 1600" in k["text"] and k["verify"]["unexplained"] == 0
    with pytest.raises(migration.MigrateError):
        migration.migrate(old, kb, CISCO, HUAWEI, None, tg, on_conflict="bad")


def test_steps_order(kb) -> None:  # type: ignore[no-untyped-def]
    text = (KB_ROOT / "samples" / "cisco-iosxe-asr920-synthetic" / "pe-asr920-01.cfg").read_text(encoding="utf-8")
    g = graph(kb, text, CISCO)
    r = migration.migrate(g, kb, CISCO, HUAWEI, verify=False)
    keys = [s["key"].rsplit(".", 1)[-1] for s in r["steps"]]
    assert keys.index("drain_bgp") < keys.index("shutdown_old") < keys.index("move_cables")
    assert keys.index("enable_core") < keys.index("enable_access") < keys.index("restore_bgp")
    hold = next(s for s in r["steps"] if s["key"] == "migrate.step.hold_new")
    assert hold["commands"][0] == "system-view" and hold["commands"][-2:] == ["commit", "return"]
    drain = next(s for s in r["steps"] if s["key"] == "migrate.step.drain_bgp")
    assert drain["commands"][0] == "configure terminal" and " neighbor 10.255.0.1 shutdown" in drain["commands"]


def test_map_csv_roundtrip(kb, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    g = graph(kb, OLD_HW, HUAWEI)
    r = migration.migrate(g, kb, HUAWEI, CISCO, model="ASR-920-12CZ-A", verify=False)
    f = tmp_path / "map.csv"
    f.write_text(migration.map_csv(r), encoding="utf-8")
    back = migration.load_map_file(f)
    assert back["GigabitEthernet0/2/1"] == "GigabitEthernet0/0/1"
    assert "Ethernet0/0/0" not in back  # 未映射的行 target 为空，跳过
    assert f.read_text(encoding="utf-8").splitlines()[0].startswith("source,target,kind")
