"""设备配置分析（REQ-034）：层归类完整性、按键细分、跨层依赖、结构化脚本的区间与引用、隐藏默认值行、分析摘要的数值。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lmesh.core import analysis, checks, layers
from lmesh.core import config_analysis as ca
from lmesh.core import graph as graphmod
from lmesh.core import rules as rulesmod
from lmesh.core.kb import KnowledgeBase
from lmesh.core.kb.validate import validate

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parent.parent.parent
KB_ROOT = ROOT / "knowledge"
SAMPLES = KB_ROOT / "samples"

TEXT = (
    "sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\n"
    "interface GigabitEthernet0/2/1\n description TO AGG-01 port 3\n ip binding vpn-instance RAN\n"
    " ip address 10.1.1.1 255.255.255.252\n#\ninterface GigabitEthernet0/2/1.100\n vlan-type dot1q 100\n#\n"
    "interface LoopBack0\n ip address 10.255.0.1 255.255.255.255\n#\nreturn"
)


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return analysis.load_kb(KB_ROOT)


@pytest.fixture(scope="module")
def lay() -> layers.Layers:
    return layers.load(KB_ROOT)


def _g(kb: KnowledgeBase, text: str, name: str = "R1") -> Any:
    res = analysis.parse_text(text, kb)
    return graphmod.build(res.parsed, kb, res.profile, name)


# ---------------------------------------------------------------- layers.yaml


def test_every_schema_object_is_classified(kb: KnowledgeBase, lay: layers.Layers) -> None:
    """全部现有对象都在 layers.yaml 归层，登记的节点与层都存在（新增 Schema 对象没有归层时这里失败）。"""
    assert lay.ids == ["physical", "datalink", "mpls", "network", "transport", "application"]
    assert layers.problems(kb, lay) == []
    objects = {n for n, s in kb.nodes.items() if s.type == "object"}
    assert objects <= set(lay.objects)
    # 每个属性都能归到一个已定义的层（自己登记或跟随所属对象）
    for nid, s in kb.nodes.items():
        if s.type == "object":
            continue
        owner = rulesmod.owner_object(kb, nid)
        layer = lay.attrs.get(nid) or (lay.objects.get(owner) if owner else None)
        assert layer in lay.ids, nid


def test_unclassified_object_is_reported(kb: KnowledgeBase, lay: layers.Layers) -> None:
    """对象没有登记时：校验提示 layers.unclassified，运行时先按功能域的缺省层归类。"""
    partial = layers.Layers(**{**lay.__dict__, "objects": {k: v for k, v in lay.objects.items() if k != "bfd.session"}})
    codes = [c for c, m in layers.problems(kb, partial) if "bfd.session" in m]
    assert codes == ["layers.unclassified"]
    assert layers.object_layer(kb, partial, "bfd.session") == "transport"  # domains.bfd
    assert layers.object_layer(kb, partial, "no.such") == layers.UNCLASSIFIED
    bad = layers.Layers(**{**lay.__dict__, "attrs": {**lay.attrs, "interface.mtu": "session"}})
    assert ("layers.bad_layer", "layers.yaml 的 attrs.interface.mtu 的层 session 没有定义") in layers.problems(kb, bad)


def test_kb_validate_has_no_layer_warnings(kb: KnowledgeBase) -> None:
    assert not [i for i in validate(kb) if i.code.startswith("layers.")]


def test_key_rules_and_features(kb: KnowledgeBase, lay: layers.Layers) -> None:
    assert layers.object_layer(kb, lay, "interface", "GigabitEthernet0/2/1") == "physical"
    assert layers.object_layer(kb, lay, "interface", "GigabitEthernet0/2/1.100") == "datalink"
    assert layers.object_layer(kb, lay, "interface", "Eth-Trunk1") == "datalink"
    assert layers.object_layer(kb, lay, "interface", "LoopBack0") == "network"
    assert layers.object_layer(kb, lay, "interface", "Vlanif100") == "network"
    assert layers.schema_feature(lay, "qos.policy.rule") == "qos"
    assert layers.schema_feature(lay, "interface.qos_policy.policy") == "qos"
    assert layers.schema_feature(lay, "interface.ptp") == "clock"
    assert layers.schema_feature(lay, "interface.mtu") is None


# ---------------------------------------------------------------- 归类与跨层依赖


def test_classify_small_config(kb: KnowledgeBase, lay: layers.Layers) -> None:
    g = _g(kb, TEXT)
    c = layers.classify(g, kb, lay)
    nodes = c["nodes"]
    assert nodes["interface[GigabitEthernet0/2/1]"] == "physical"
    assert nodes["interface[GigabitEthernet0/2/1]/vrf"] == "network"  # 属性单独登记
    assert nodes["interface[GigabitEthernet0/2/1]/description"] == "physical"  # 跟随对象
    assert nodes["interface[GigabitEthernet0/2/1.100]"] == "datalink"
    assert nodes["interface[LoopBack0]"] == "network"
    assert "raw[1]" not in nodes and c["outside"] == 1  # sysname：功能域外的原文
    by = {r["id"]: r for r in c["layers"]}
    assert by["physical"]["objects"] == 1 and by["datalink"]["objects"] == 1
    cross = {(e["from"], e["to"], e["kind"]) for e in c["cross"]}
    assert ("interface[GigabitEthernet0/2/1]", "vrf.instance[RAN]", "reference") in cross
    assert ("interface[GigabitEthernet0/2/1]", "interface[GigabitEthernet0/2/1]/ipv4[10.1.1.1]", "contains") in cross
    assert not [e for e in c["cross"] if e["kind"] in ("side_effect", "mutex")]
    # LoopBack0 与它的地址都在网络层：不是跨层
    assert not [e for e in c["cross"] if e["from"] == "interface[LoopBack0]"]
    assert c["unclassified"] == []


def test_cross_layer_on_real_sample(kb: KnowledgeBase, lay: layers.Layers) -> None:
    """现网 ATN 样本：各层都有对象，没有未分类；BGP 对等体（传输层）在 BGP 实例（网络层）下。"""
    g = _g(kb, (SAMPLES / "huawei-atn-v800r023" / "atn-access-01.cfg").read_text(encoding="utf-8"))
    c = layers.classify(g, kb, lay)
    assert c["unclassified"] == []
    assert all(r["objects"] > 0 for r in c["layers"])
    pairs = {(x["a"], x["b"]) for x in c["cross_by_layers"]}
    assert ("physical", "datalink") in pairs and ("network", "application") in pairs
    assert {f["id"]: f["objects"] > 0 for f in c["features"]} == {"qos": True, "clock": True}


# ---------------------------------------------------------------- 结构化脚本


def _text(raw: str, sp: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(raw[s["s"] : s["e"]], s["t"]) for s in sp]


def test_spans_keywords_params_and_text_param() -> None:
    raw = " ip address 10.1.1.1 255.255.255.252"
    assert _text(raw, ca.spans(raw, {"ip-address": "10.1.1.1", "mask": "255.255.255.252"})) == [
        ("ip", "kw"),
        ("address", "kw"),
        ("10.1.1.1", "param"),
        ("255.255.255.252", "param"),
    ]
    raw = " description TO AGG-01 port 3"
    assert _text(raw, ca.spans(raw, {"description": "TO AGG-01 port 3"})) == [
        ("description", "kw"),
        ("TO AGG-01 port 3", "param"),
    ]
    # 第一个词总是关键字，即使取值相同
    raw = "vlan 10"
    assert _text(raw, ca.spans(raw, {"vlan": "vlan"})) == [("vlan", "kw"), ("10", "kw")]


def test_script_lines_refs_and_defaults(kb: KnowledgeBase, lay: layers.Layers) -> None:
    g = _g(kb, TEXT)
    s = ca.script(g, kb, lay)
    lines = {r["no"]: r for r in s["lines"]}
    assert len(s["lines"]) == len(TEXT.split("\n"))
    assert lines[1]["kind"] == "raw" and lines[1]["layer"] is None
    assert lines[4]["depth"] == 1 and lines[4]["parent"] == 3 and lines[5]["depth"] == 2
    assert lines[3]["node"] == "vrf.instance[RAN]" and lines[3]["domain"] == "vrf" and lines[3]["layer"] == "network"
    b = lines[9]
    assert _text(b["text"], b["spans"]) == [("ip", "kw"), ("binding", "kw"), ("vpn-instance", "kw"), ("RAN", "ref")]
    assert b["spans"][-1]["ref"] == ["vrf.instance[RAN]"]
    assert s["refs"] == {"vrf.instance[RAN]": [9]} and s["defs"] == {"vrf.instance[RAN]": 3}
    assert ("TO AGG-01 port 3", "param") in _text(lines[8]["text"], lines[8]["spans"])
    # 隐藏的默认值：插在所属对象块的最后一行之后，带该平台的命令写法
    mtu = next(d for d in s["defaults"] if d["node"] == "interface[GigabitEthernet0/2/1]/mtu")
    assert mtu["after"] == 10 and mtu["depth"] == 1 and mtu["text"] == "mtu 1500"
    assert all(d["after"] for d in s["defaults"])
    assert ca.script(g, kb, lay, with_defaults=False)["defaults"] == []


def test_script_cisco_refs(kb: KnowledgeBase, lay: layers.Layers) -> None:
    g = _g(kb, (SAMPLES / "cisco-iosxe-asr920-synthetic" / "pe-asr920-04-advanced.cfg").read_text(encoding="utf-8"))
    s = ca.script(g, kb, lay)
    assert s["family"] == "cisco-iosxe"
    for tgt, at in s["refs"].items():
        assert at and all(any(tgt in sp.get("ref", []) for sp in s["lines"][n - 1].get("spans", [])) for n in at)
    assert "qos.classifier[CM-VOICE]" in s["refs"]


# ---------------------------------------------------------------- 分析摘要


def test_summary_numbers(kb: KnowledgeBase, lay: layers.Layers) -> None:
    g = _g(kb, TEXT)
    rules = rulesmod.load_dir(kb, checks.rules_dir(KB_ROOT))
    chk = ca.run_check(g, kb, rules, checks.load_overrides(checks.rules_dir(KB_ROOT)), None)
    s = ca.summary(g, kb, lay, check=chk, baseline=ca.run_baseline(g, kb, KB_ROOT))
    ln = s["lines"]
    assert (ln["total"], ln["raw"], ln["unknown"], ln["separator"], ln["end"]) == (18, 1, 0, 5, 1)
    assert ln["command"] == 11 and ln["coverage"] == 1.0
    dom = {d["domain"]: d for d in s["domains"]}
    assert dom["interface"]["objects"] == 5  # 3 个接口 + 2 个 IPv4 地址对象
    assert dom["vrf"]["objects"] == 2  # VPN 实例 + 地址族
    assert s["check"]["summary"]["total"] == chk["summary"]["total"]
    assert s["baseline"]["baseline"] == "basic" and isinstance(s["baseline"]["score"], int)
    assert s["history"] is None and s["dangling"] == 0
    d = s["defaults"]
    assert d["total"] == sum(1 for _, x in g.nodes(data=True) if x.get("origin") == "default")
    assert all(it["others"] and it["others"][0]["profile"].startswith("cisco") for it in d["items"])


def test_key_defaults_cross_vendor(kb: KnowledgeBase, lay: layers.Layers) -> None:
    """BGP 邻居变化日志：华为默认开、Cisco 默认关——依赖默认值的关键配置。"""
    g = _g(kb, (SAMPLES / "cisco-iosxe-asr920-synthetic" / "pe-asr920-04-advanced.cfg").read_text(encoding="utf-8"))
    _, owner = layers.node_layers(g, kb, lay)
    d = ca.key_defaults(g, kb, owner)
    item = next(i for i in d["items"] if i["schema"] == "bgp.instance.log_neighbor_changes")
    assert item["value"] is False and {o["value"] for o in item["others"]} == {True}
