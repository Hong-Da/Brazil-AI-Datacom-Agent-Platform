"""规范渲染与配置翻译（M3-3）：表达式反解、按语法生成、规范渲染的结构、含默认值、默认值差异、不支持的项、接口映射。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmesh.core import analysis, canon, compare, translate
from lmesh.core import graph as graphmod
from lmesh.core.kb import syntax as syn

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
CISCO = "cisco-iosxe-asr920-17.15"
HUAWEI = "huawei-atn-v800r025"
SMALL = (Path(__file__).resolve().parent.parent / "inputs" / "translate" / "cs-small.cfg").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


def graph(kb, text: str, profile: str):  # type: ignore[no-untyped-def]
    res = analysis.parse_text(text, kb, profile)
    return graphmod.build(res.parsed, kb, res.profile, "dev")


# ---------- 表达式反解与生成 ----------


def _card(**kw):  # type: ignore[no-untyped-def]
    from lmesh.core.kb.model import Card

    return Card(id="t", family="x", domain="d", syntax=kw.pop("syntax", "x"), view="system", **kw)


def test_invert_param_fmt_and_mask_conversion() -> None:
    card = _card(params={"ip": {"type": "ipv4"}, "mask": {"type": "mask"}, "len": {"type": "mask-length"}})
    inv = canon._Inverter(card)
    sols = inv.run("fmt:{ip}/{mask|len}", "10.0.0.0/8", "prefix")
    got = {tuple(sorted(s.values)) for s in sols}
    assert (("ip", "10.0.0.0"), ("mask", "255.0.0.0")) in got  # 掩码长度换成点分掩码
    assert (("ip", "10.0.0.0"), ("len", "8")) in got


def test_invert_kw_flag_if_tail() -> None:
    inv = canon._Inverter(_card())
    assert inv.run("kw:export-extcommunity=export|import-extcommunity=import|both=both:both", "export", "enum")[
        0
    ].kws == {"export-extcommunity"}
    both = inv.run("kw:a=x|b=y:y", "y", "enum")
    assert any(s.kws == {"b"} for s in both) and any(s.forbid == {"a", "b"} for s in both)  # 缺省值可以不写关键字
    assert inv.run("flag", False, "boolean")[0].neg is True
    assert inv.run("if:prefer:flag", True, "boolean")[0].kws == {"prefer"}
    assert inv.run("if:prefer:flag", None, "boolean")[0].forbid == {"prefer"}
    assert inv.run("tail:version", "v2c v3", "string")[0].tail == ("version", "v2c v3")
    assert inv.run("dot1q", "untagged", "string") == []  # 常量不相等：这张卡写不出


def test_generate_lines_follow_syntax() -> None:
    s = syn.parse("ip route-static <ip> { <mask> | <len> } <nh> [ preference <pref> ] [ tag <tag> ]")
    gen = canon._Gen(canon._Sol(values=(("ip", "0.0.0.0"), ("mask", "0.0.0.0"), ("nh", "10.0.0.2"), ("tag", "5"))))
    lines = gen.lines(s)
    assert lines[0] == "ip route-static 0.0.0.0 0.0.0.0 10.0.0.2 tag 5"
    rep = syn.parse("apply community { <c> } &<1-32> [ additive ]")
    gen2 = canon._Gen(canon._Sol(values=(("c", ("1:1", "2:2")),), kws=frozenset({"additive"})))
    assert gen2.lines(rep)[0] == "apply community 1:1 2:2 additive"


# ---------- 规范渲染 ----------


def test_canonical_structure_cisco(kb) -> None:  # type: ignore[no-untyped-def]
    text = (KB_ROOT / "samples" / "cisco-iosxe-asr920-synthetic" / "pe-asr920-01.cfg").read_text(encoding="utf-8")
    g = graph(kb, text, CISCO)
    r = canon.render_full(g, kb, CISCO)
    lines = r.text.split("\n")
    assert lines[0] == "!" and lines[-1] == "end"
    assert " exit-address-family" in lines
    # 被引用的先出现：VRF 在接口前，前缀列表在路由策略前，路由策略在 BGP 前
    idx = {
        k: next(i for i, ln in enumerate(lines) if ln.startswith(k))
        for k in ("vrf definition", "interface", "ip prefix-list", "route-map", "router bgp")
    }
    assert idx["vrf definition"] < idx["interface"] and idx["ip prefix-list"] < idx["route-map"] < idx["router bgp"]
    assert r.uncovered == [] and canon.render(g, kb, CISCO) == r.text


def test_canonical_structure_huawei(kb) -> None:  # type: ignore[no-untyped-def]
    text = (KB_ROOT / "samples" / "translate" / "atn-l3vpn-synth.cfg").read_text(encoding="utf-8")
    r = canon.render_full(graph(kb, text, HUAWEI), kb, HUAWEI)
    lines = r.text.split("\n")
    assert lines[0] == "#" and lines[-1] == "return"
    assert " #" in lines  # BGP 块内的地址族之间
    assert "group RR internal" in [ln.strip() for ln in lines]


def test_with_defaults_marks_default_lines(kb) -> None:  # type: ignore[no-untyped-def]
    g = graph(kb, SMALL, CISCO)
    r = canon.render_full(g, kb, CISCO, include_defaults=True)
    kinds = [(ln.kind, ln.origin, ln.text) for ln in r.lines]
    i = kinds.index(("comment", "default", canon.DEFAULT_MARK))
    assert kinds[i + 1][1] == "default" and kinds[i + 1][0] == "command"
    assert "no shutdown" in [k[2] for k in kinds]
    # 重新解析：默认值写成显式后，有效值不变
    c = compare.compare(compare.Side(g, "a"), compare.side_from_text(r.text, kb, CISCO, "b"), kb)
    assert c["equal"]


def test_render_from_json_graph(kb) -> None:  # type: ignore[no-untyped-def]
    g = graph(kb, SMALL, CISCO)
    data = graphmod.to_json(g)
    text = canon.render(data, kb, CISCO)  # 只有节点数据（模板生成用）：原文节点带 text 时照样写回
    assert "interface GigabitEthernet0/0/1" in text and "hostname R1" in text
    c = compare.compare(compare.Side(g, "a"), compare.side_from_text(text, kb, CISCO, "b"), kb)
    assert c["equal"]


def test_unknown_schema_does_not_crash(kb) -> None:  # type: ignore[no-untyped-def]
    g = graph(kb, SMALL, CISCO)
    data = graphmod.to_json(g)
    data["nodes"].append({"id": "future.obj[x]", "kind": "object", "schema": "future.obj", "key": "x"})
    data["edges"].append({"from": "device", "to": "future.obj[x]", "kind": "contains"})
    r = canon.render_full(data, kb, CISCO)
    assert "future.obj[x]" in r.uncovered  # 没有生成知识的节点报出来，不崩


def test_bad_graph(kb) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(canon.CanonError):
        canon.render("not a graph", kb, CISCO)


# ---------- 翻译 ----------


def test_translate_basic(kb) -> None:  # type: ignore[no-untyped-def]
    r = translate.translate(graph(kb, SMALL, CISCO), kb, CISCO, HUAWEI, {"Port-channel1": "Eth-Trunk1"})
    assert r["verify"]["checked"] and r["verify"]["unexplained"] == 0
    assert "interface Eth-Trunk1" in r["text"] and "ip route-static 0.0.0.0 0.0.0.0 10.0.0.2" in r["text"]
    assert " mtu 1500" not in r["text"]  # 显式值等于目标默认值：省略
    assert r["defaults"][0]["kind"] == "explicit_equals_default" and r["defaults"][0]["lines"] == [8]
    raw = [u for u in r["unsupported"] if u["kind"] == "raw"]
    assert raw and raw[0]["params"]["text"] == "hostname R1" and raw[0]["lines"] == [4]
    assert not any(w["kind"] == "interface_type" for w in r["warnings"])


def test_translate_interface_type_warning(kb) -> None:  # type: ignore[no-untyped-def]
    r = translate.translate(graph(kb, SMALL, CISCO), kb, CISCO, HUAWEI)
    w = [x for x in r["warnings"] if x["kind"] == "interface_type"]
    assert w and w[0]["params"]["name"] == "Port-channel1"


def test_translate_default_differs(kb, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    """源设备依赖默认值而目标默认值不同：显式写出并告警；两边默认值相同时不写。"""
    entry = kb.profiles[HUAWEI].entries["interface.mtu"]
    monkeypatch.setattr(entry, "default", 9600)
    text = "hostname R1\n!\ninterface GigabitEthernet0/0/2\n description X\n!\nend"
    r = translate.translate(graph(kb, text, CISCO), kb, CISCO, HUAWEI)
    w = [x for x in r["warnings"] if x["kind"] == "default_differs" and x["schema"] == "interface.mtu"]
    assert w and w[0]["params"]["src_default"] == 1500 and w[0]["params"]["dst_default"] == 9600
    assert " mtu 1500" in r["text"].split("\n")
    assert r["verify"]["unexplained"] == 0
    assert not any(x["schema"] == "interface.shutdown" for x in r["warnings"])  # 默认值相同：不写不报


def test_translate_profile_unsupported(kb, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    entry = kb.profiles[HUAWEI].entries["interface.description"]
    monkeypatch.setattr(entry, "supported", False)
    r = translate.translate(graph(kb, SMALL, CISCO), kb, CISCO, HUAWEI)
    u = [x for x in r["unsupported"] if x["params"].get("reason") == "profile_unsupported"]
    assert {x["node"] for x in u} == {
        "interface[GigabitEthernet0/0/1]/description",
        "interface[Port-channel1]/description",
    }
    assert u[0]["lines"] and "description" not in r["text"]
    assert r["verify"]["unexplained"] == 0


def test_translate_no_render_and_inferred(kb) -> None:  # type: ignore[no-untyped-def]
    text = (KB_ROOT / "samples" / "cisco-iosxe-asr920-synthetic" / "pe-asr920-01.cfg").read_text(encoding="utf-8")
    r = translate.translate(graph(kb, text, CISCO), kb, CISCO, HUAWEI)
    nr = {u["schema"] for u in r["unsupported"] if u["params"].get("reason") == "no_render"}
    assert "interface.access" not in nr  # 业务实例 → 华为二层子接口：换结构后能写出（M3 知识库补缺）
    assert "interface GigabitEthernet0/0/1.101 mode l2" in r["text"]
    inf = [w for w in r["warnings"] if w["kind"] == "inferred_value"]
    assert inf and inf[0]["params"]["value"] == "internal"
    assert "group RR internal" in [ln.strip() for ln in r["text"].split("\n")]
    assert r["verify"]["unexplained"] == 0


def test_translate_errors(kb) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(translate.TranslateError):
        translate.translate_text(SMALL, kb, "nope")
    with pytest.raises(translate.TranslateError):
        translate.translate_text("random text", kb, HUAWEI)


def test_translate_secret_not_reused(kb) -> None:  # type: ignore[no-untyped-def]
    """密码类取值是源平台的密文：跨平台族不写，列为 unsupported（reason=secret）。"""
    text = "#\nbgp 100\n group G internal\n peer G password cipher %^%#LMESH-SECRET-1%^%#\n#\nreturn"
    r = translate.translate(graph(kb, text, HUAWEI), kb, HUAWEI, CISCO)
    sec = [u for u in r["unsupported"] if u["params"].get("reason") == "secret"]
    assert sec and sec[0]["schema"] == "bgp.peer_group.password" and sec[0]["lines"] == [4]
    assert "LMESH-SECRET" not in r["text"] and "neighbor G peer-group" in r["text"]
    assert r["verify"]["unexplained"] == 0
