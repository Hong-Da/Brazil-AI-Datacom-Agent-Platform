"""显示风格（REQ-026）：术语表完整、命令写法模板、规范编号 → 命令路径。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmesh.core import terms
from lmesh.core.kb import load

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"


@pytest.fixture(scope="module")
def kbt():  # type: ignore[no-untyped-def]
    kb = load(KB_ROOT)
    return kb, terms.load(KB_ROOT, kb)


def test_every_object_has_both_styles(kbt) -> None:  # type: ignore[no-untyped-def]
    kb, t = kbt
    assert terms.check(kb, t) == []
    assert t.default == "huawei"


@pytest.mark.parametrize(
    ("schema", "key", "hw", "cs"),
    [
        ("vrf.instance", "RAN", "ip vpn-instance RAN", "vrf definition RAN"),
        ("bgp.af", {"afi": "ipv4", "vrf": "RAN"}, "ipv4-family vpn-instance RAN", "address-family ipv4 vrf RAN"),
        ("bgp.af", {"afi": "ipv4", "vrf": ""}, "ipv4-family unicast", "address-family ipv4"),
        (
            "vrf.instance.af.rt",
            {"value": "1:1", "direction": "export"},
            "vpn-target 1:1 export-extcommunity",
            "route-target export 1:1",
        ),
        ("rp.prefix_list", "LO", "ip ip-prefix LO", "ip prefix-list LO"),
        ("mgmt.line", {"type": "vty", "range": "0 4"}, "user-interface vty 0 4", "line vty 0 4"),
    ],
)
def test_labels(kbt, schema, key, hw, cs) -> None:  # type: ignore[no-untyped-def]
    _, t = kbt
    assert t.label(schema, key, "huawei") == hw
    assert t.label(schema, key, "cisco") == cs


def test_describe_node_ids(kbt) -> None:  # type: ignore[no-untyped-def]
    kb, t = kbt
    nid = "bgp.instance[65000]/bgp.af[afi=ipv4,vrf=]/peer[RR]/export_policy"
    assert terms.describe(nid, kb, t, "huawei") == "bgp 65000 › ipv4-family unicast › peer RR › route-policy … export"
    assert (
        terms.describe(nid, kb, t, "cisco") == "router bgp 65000 › address-family ipv4 › neighbor RR › route-map … out"
    )
    # 接口名里的 / 不拆层
    assert terms.split_node_id("interface[GigabitEthernet0/2/1]/ospf[_]/cost") == [
        ("interface", "GigabitEthernet0/2/1"),
        ("ospf", "_"),
        ("cost", None),
    ]
    assert (
        terms.describe("interface[Gi0/0/1]/ospf[_]/cost", kb, t, "cisco")
        == "interface Gi0/0/1 › ip ospf › ip ospf cost"
    )
