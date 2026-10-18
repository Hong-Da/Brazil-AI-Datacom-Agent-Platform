"""特性能力查询（M5-4）：按关键词查各 Profile 的支持情况、默认值、命令写法与来源；详情；两个 Profile 对比（默认值不同的在前）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmesh.core import analysis, features, terms

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
HW, CS = "huawei-atn-v800r025", "cisco-iosxe-asr920-17.15"


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


def test_search_by_keyword(kb) -> None:  # type: ignore[no-untyped-def]
    r = features.search(kb, "mtu", [HW, CS])
    first = r["items"][0]
    assert first["node"] == "interface.mtu" and first["score"] == 80
    assert first["profiles"][HW]["state"] == "supported" and first["profiles"][HW]["default"] == 1500
    assert first["profiles"][CS]["syntax"] and first["profiles"][CS]["credibility"] in ("draft", "reviewed", "verified")
    assert [p["id"] for p in r["profiles"]] == [HW, CS] and r["kb_version"] == kb.version
    # 叫法（显示风格的命令关键字与名称）也能查到：华为 connect-interface 对应 update_source
    r2 = features.search(kb, "connect-interface", terms=terms.load(KB_ROOT, kb))
    assert any(i["node"].endswith("update_source") for i in r2["items"])
    # 按命令写法查（华为命令关键字 route-distinguisher → RD）
    assert any(i["node"] == "vrf.instance.af.rd" for i in features.search(kb, "route-distinguisher")["items"])


def test_inherited_and_filters(kb) -> None:  # type: ignore[no-untyped-def]
    r = features.search(kb, "interface.mtu", ["huawei-atn-v800r023"])
    cell = r["items"][0]["profiles"]["huawei-atn-v800r023"]
    assert cell["inherited"] and cell["origin"] == HW
    fam = features.search(kb, "mtu", family="cisco-iosxe")
    assert {p["family"] for p in fam["profiles"]} == {"cisco-iosxe"}
    gaps = features.search(kb, "", [HW, CS], state="unfilled", limit=5)
    assert all(any(c["state"] == "unfilled" for c in i["profiles"].values()) for i in gaps["items"])
    browse = features.search(kb, "", [HW, CS])
    assert browse["hidden_same"] > 0 and all(i["kind"] != "same" for i in browse["items"])
    assert features.search(kb, "", [HW, CS], include_same=True)["hidden_same"] == 0
    for kw, key in (
        ({"profiles": ["nope"]}, "feature.bad_profile"),
        ({"family": "nope"}, "feature.bad_family"),
        ({"state": "nope"}, "feature.bad_state"),
        ({"domain": "nope"}, "feature.bad_domain"),
    ):
        with pytest.raises(features.FeatureError) as e:
            features.search(kb, "mtu", **kw)
        assert e.value.key == key


def test_detail(kb) -> None:  # type: ignore[no-untyped-def]
    d = features.detail(kb, "interface.vrf", [HW, CS])
    assert d["type"] == "ref" and d["ref"] == "vrf.instance"
    assert d["profiles"][HW]["cards"] and any(x["kind"] == "reference" for x in d["deps"])
    with pytest.raises(features.FeatureError) as e:
        features.detail(kb, "nope")
    assert e.value.kind == "not_found"


def test_profile_diff_order(kb) -> None:  # type: ignore[no-untyped-def]
    d = features.diff(kb, HW, CS)
    kinds = [r["kind"] for r in d["rows"]]
    assert kinds == sorted(kinds, key=features.KINDS.index) and kinds[0] == "default"
    label = next(r for r in d["rows"] if r["node"] == "vrf.instance.af.label_mode")
    assert (label["a"]["default"], label["b"]["default"]) == ("per-instance", "per-route")
    assert d["hidden_same"] == d["counts"]["same"] > 0 and "same" not in kinds
    d2 = features.diff(kb, HW, CS, domain="bgp", include_same=True)
    assert d2["hidden_same"] == 0 and {r["domain"] for r in d2["rows"]} == {"bgp"}
    with pytest.raises(features.FeatureError):
        features.diff(kb, HW, "nope")
