"""参数化模板（M3-4 / M3-5）：模板格式与校验、过滤器与取值检查、约束匹配与变量提取、模板外的配置、
重复块与可选块、模板制作辅助、批量生成（正文替换与规范渲染器）。"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from lmesh.core import analysis, template_draft, template_gen, template_match
from lmesh.core import template as tmod

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parent.parent.parent
KB_ROOT = ROOT / "knowledge"
INPUTS = ROOT / "tests" / "inputs" / "templates"
ASR_SAMPLE = (KB_ROOT / "samples" / "cisco-iosxe-asr920-synthetic" / "pe-asr920-01.cfg").read_text(encoding="utf-8")
ATN_SAMPLE = (KB_ROOT / "samples" / "huawei-atn-v800r023" / "atn-access-01.cfg").read_text(encoding="utf-8")
ASR_ROW = {
    "device": "PE-07",
    "hostname": "PE-ASR920-07",
    "asn": 64512,
    "loopback": "10.255.0.27",
    "uplink": "GigabitEthernet0/0/0",
    "uplink_net": "10.1.0.8/30",
    "access": "GigabitEthernet0/0/1",
    "access_desc": "RAN-SITE-007",
    "rr1": "10.255.0.1",
    "rr2": "10.255.0.2",
    "svc": [
        {"vlan": 101, "vrf": "RAN-2G", "rt": 101, "desc": "RAN-2G-SITE-007", "lan": "172.16.7.0/24"},
        {"vlan": 102, "vrf": "MGMT", "rt": 10, "desc": "MGMT-SITE-007", "lan": "172.17.7.0/28"},
    ],
}


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


@pytest.fixture(scope="module")
def asr(kb):  # type: ignore[no-untyped-def]
    return tmod.load(KB_ROOT, "cisco-asr920-efp-bdi-vrf", kb)


def kinds(r) -> list[tuple[str, str | None]]:  # type: ignore[no-untyped-def]
    return [(f["kind"], f["node"] or f["actual_node"]) for f in r["findings"]]


# ---------- 格式与校验 ----------


def test_builtin_templates_are_valid(kb) -> None:  # type: ignore[no-untyped-def]
    items = tmod.list_templates(KB_ROOT, kb)
    assert {i["id"] for i in items} >= {"cisco-asr920-efp-bdi-vrf", "huawei-atn-l2-bd-vbdif", "huawei-atn-l3vpn-subif"}
    assert all(i["valid"] for i in items), [i for i in items if not i["valid"]]
    for i in items:  # 正文都能解析建图，且没有未识别行
        comp = template_match.compile_template(tmod.load(KB_ROOT, i["id"], kb), kb)
        assert comp.warnings == [], (i["id"], comp.warnings)
        assert comp.items


def test_invalid_template_lists_issues(kb) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(tmod.TemplateError) as e:
        tmod.parse((INPUTS / "bad-template.yaml").read_text(encoding="utf-8"), kb)
    keys = {i["key"] for i in e.value.issues}
    assert e.value.kind == "invalid"
    assert {"template.issue.bad_type", "template.issue.unclosed_block", "template.unknown_var"} <= keys


@pytest.mark.parametrize(
    ("body", "key"),
    [
        ("{% repeat svc %}\n{% optional x %}\n{% end %}\n{% end %}", "template.issue.nested_block"),
        ("{% end %}", "template.issue.stray_end"),
        ("hostname {{h|nope}}", "template.bad_filter"),
    ],
)
def test_body_problems(kb, body: str, key: str) -> None:  # type: ignore[no-untyped-def]
    src = (
        "id: x\nprofile: cisco-iosxe-asr920-17.15\nvars: {h: word}\n"
        "blocks: {svc: {repeat: {min: 0}}, x: {optional: true}}\nbody: |\n"
        + "".join(f"  {ln}\n" for ln in body.split("\n"))
    )
    with pytest.raises(tmod.TemplateError) as e:
        tmod.parse(src, kb)
    assert key in {i["key"] for i in e.value.issues}


def test_unknown_profile_and_bad_extra(kb) -> None:  # type: ignore[no-untyped-def]
    src = "id: x\nprofile: nope\nmatch: {extra: maybe}\nbody: |\n  hostname R1\n"
    with pytest.raises(tmod.TemplateError) as e:
        tmod.parse(src, kb)
    assert {"template.issue.unknown_profile", "template.issue.bad_extra"} <= {i["key"] for i in e.value.issues}


# ---------- 过滤器与取值检查 ----------


@pytest.mark.parametrize(
    ("value", "flt", "arg", "want"),
    [
        ("10.0.182.128/29", "host", 1, "10.0.182.129"),
        ("10.0.182.128/29", "host", -1, "10.0.182.134"),
        ("10.0.182.128/29", "mask", None, "255.255.255.248"),
        ("10.0.182.128/29", "len", None, "29"),
        ("10.0.182.130/29", "network", None, "10.0.182.128"),
        ("10.0.182.130/29", "ip", None, "10.0.182.130"),
        ("10.0.0.0/24", "wildcard", None, "0.0.0.255"),
        ("101", "add", 1000, "1101"),
        ("10.0.0.1", "add", 2, "10.0.0.3"),
        ("abc", "upper", None, "ABC"),
    ],
)
def test_filters(value: str, flt: str, arg: int | None, want: str) -> None:
    assert tmod.apply_filter(value, flt, arg) == want


def test_host_out_of_range() -> None:
    with pytest.raises(tmod.TemplateError):
        tmod.apply_filter("10.0.0.0/30", "host", 9)


@pytest.mark.parametrize(
    ("spec", "value", "problem"),
    [
        ({"type": "vlan"}, "4095", "template.value.out_of_range"),
        ({"type": "vlan"}, "abc", "template.value.not_integer"),
        ({"type": "integer", "min": 1, "max": 10}, "10", None),
        ({"type": "prefix", "network": True}, "10.0.0.1/30", "template.value.not_network"),
        ({"type": "prefix", "length": [24, 30]}, "10.0.0.0/31", "template.value.bad_length"),
        ({"type": "prefix", "within": ["10.0.0.0/8"]}, "11.0.0.0/30", "template.value.not_within"),
        ({"type": "ipv4"}, "10.0.0.256", "template.value.bad_ipv4"),
        ({"type": "enum", "choices": ["import", "export"]}, "IMPORT", None),
        ({"type": "enum", "choices": ["import", "export"]}, "both", "template.value.not_choice"),
        ({"type": "word", "pattern": "[A-Z0-9-]+"}, "abc", "template.value.pattern"),
        ({"type": "word"}, "a b", "template.value.has_space"),
        ({"type": "rd"}, "65000:1", None),
        ({"type": "rd"}, "65000", "template.value.bad_rd"),
        ({"type": "asn"}, "1.10", None),
    ],
)
def test_check_value(spec: dict, value: str, problem: str | None) -> None:
    issues: list = []
    v = tmod._var("v", spec, None, issues)
    assert not issues
    assert tmod.check_value(v, value)[1] == problem


# ---------- 约束匹配与变量提取 ----------


def test_generated_config_is_compliant_and_extracts_input(kb, asr) -> None:  # type: ignore[no-untyped-def]
    row, errors = template_gen.prepare_row(asr, ASR_ROW)
    assert errors == []
    r = template_match.check_text(asr, tmod.render_text(asr, row), kb, label="PE-07")
    assert r["compliant"], r["findings"]
    assert r["findings"] == []
    assert r["variables"]["uplink_ip"] == "10.1.0.10"  # 派生变量
    assert r["variables"]["uplink_net"] == "10.1.0.8/30"  # 由 host(2) 与 mask 反推
    assert [i["vlan"] for i in r["blocks"]["svc"]] == [101, 102]
    assert r["blocks"]["svc"][1]["lan"] == "172.17.7.0/28"
    assert template_gen._mismatch(asr, row, r["row"]) == []


def test_sample_findings_with_lines(kb, asr) -> None:  # type: ignore[no-untyped-def]
    r = template_match.check_text(asr, ASR_SAMPLE, kb, label="pe01")
    assert not r["compliant"]
    errors = [f for f in r["findings"] if f["severity"] == "error"]
    assert [(f["kind"], f["node"], f["block"], f["instance"], f["parent"]) for f in errors] == [
        ("missing", "interface[BDI{svc.vlan}]/description", "svc", 1, "interface[BDI102]")
    ]
    assert errors[0]["template_lines"] == [34]
    extras = {f["actual_node"]: f for f in r["findings"] if f["kind"] == "extra"}
    assert extras["vrf.instance[RAN-2G]/af[ipv4]/rt[value=64512:1,direction=import]"]["lines"] == [29]
    assert "bgp.instance[64512]/bgp.af[afi=ipv4,vrf=]" in extras
    assert all(f["severity"] == "info" for f in extras.values())
    # 显式写出、等于默认值的 negotiation auto 不算模板外的配置
    assert "interface[GigabitEthernet0/0/0]/negotiation" not in extras
    assert r["blocks"]["svc"][0]["vrf"] == "RAN-2G" and r["blocks"]["svc"][1]["vrf"] == "MGMT"


def test_extra_deny_and_scope(kb, asr) -> None:  # type: ignore[no-untyped-def]
    r = template_match.check_text(asr, ASR_SAMPLE, kb, extra="deny")
    assert r["summary"]["by_severity"]["error"] == 1 + r["summary"]["extra"]
    r = template_match.check_text(asr, ASR_SAMPLE, kb, extra_scope="none")
    assert r["summary"]["extra"] == 0
    r = template_match.check_text(asr, ASR_SAMPLE, kb, extra_scope="domains")
    nodes = {f["actual_node"] for f in r["findings"] if f["kind"] == "extra"}
    assert "interface[Port-channel1]" in nodes and "static.route[vrf=,prefix=0.0.0.0/0,nexthop=10.1.0.1]" not in nodes


def test_value_inconsistent_and_extra(kb, asr) -> None:  # type: ignore[no-untyped-def]
    text = (INPUTS / "pe-asr920-11-bad.cfg").read_text(encoding="utf-8")
    r = template_match.check_text(asr, text, kb)
    got = {(f["kind"], f["node"]) for f in r["findings"] if f["severity"] == "error"}
    assert ("value", "interface[{uplink}]/mtu") in got
    assert ("inconsistent", "interface[{access}]/access[{svc.vlan}]/vlan") in got
    mtu = next(f for f in r["findings"] if f["kind"] == "value")
    assert (mtu["expected"], mtu["actual"], mtu["lines"], mtu["template_lines"]) == ("9216", 9000, [23], [17])
    assert any(f["kind"] == "extra" and "10.255.0.9" in (f["actual_node"] or "") for f in r["findings"])


def test_constraint_and_count(kb, asr) -> None:  # type: ignore[no-untyped-def]
    row, _ = template_gen.prepare_row(asr, ASR_ROW)
    text = tmod.render_text(asr, row).replace("10.255.0.27", "10.99.0.27")
    r = template_match.check_text(asr, text, kb)
    c = [f for f in r["findings"] if f["kind"] == "constraint"]
    assert c and c[0]["var"] == "loopback" and c[0]["problem"] == "template.value.not_within" and c[0]["lines"]
    # 一个业务都没有：实例个数违反 min
    zero = copy.deepcopy(row)
    zero["svc"] = []
    r = template_match.check_text(asr, tmod.render_text(asr, zero), kb)
    assert ("count", "interface[{access}]/access[{svc.vlan}]") in kinds(r)


def test_repeat_block_binds_base_var_from_anchor(kb) -> None:  # type: ignore[no-untyped-def]
    """L2 模板的 {{port}} 只出现在块里：按锚点的匹配分组决定；现网样本上找出真实的偏差。"""
    t = tmod.load(KB_ROOT, "huawei-atn-l2-bd-vbdif", kb)
    r = template_match.check_text(t, ATN_SAMPLE, kb)
    assert r["variables"]["port"] == "GigabitEthernet0/2/0"
    assert [i["bd"] for i in r["blocks"]["svc"]] == [1584, 1585, 1586, 1587, 1588, 1589, 1591, 1592, 1598, 1599]
    first = r["blocks"]["svc"][0]
    assert (first["vrf"], first["lan"], first["gw"]) == ("GERENCIA", "10.0.182.128/29", "10.0.182.134")
    missing_vrf = [f["instance"] for f in r["findings"] if f["kind"] == "missing"]
    assert missing_vrf == [4, 5, 8, 9]  # Vbdif1588 / 1589 / 1598 / 1599 没有绑定 VPN 实例
    gw = [f for f in r["findings"] if f["kind"] == "inconsistent"]
    assert gw and all(f["var"] == "svc.lan|host(-1)" and f["lines"] for f in gw)


def test_optional_block(kb) -> None:  # type: ignore[no-untyped-def]
    t = tmod.load_any(KB_ROOT, str(INPUTS / "optional-demo.yaml"), kb)
    rows = [
        {"device": "R1", "hostname": "R1", "port": "GigabitEthernet0/0/5", "net": "10.9.0.0/30", "shut": "true"},
        {"device": "R2", "hostname": "R2", "port": "GigabitEthernet0/0/6", "net": "10.9.0.4/30", "shut": "false"},
    ]
    r = template_gen.generate(t, rows, kb)
    assert r["summary"] == {"total": 2, "ok": 2, "failed": 0}, r["rows"]
    assert " shutdown" in r["rows"][0]["text"] and " shutdown" not in r["rows"][1]["text"]
    chk = template_match.check_text(t, r["rows"][0]["text"], kb)
    assert chk["blocks"]["shut"] is True and chk["variables"]["ip"] == "10.9.0.1"
    # extra: deny —— 模板外的配置算不符合
    chk = template_match.check_text(t, r["rows"][1]["text"].replace(" ip address", " mtu 9000\n ip address"), kb)
    assert not chk["compliant"] and ("extra", "interface[GigabitEthernet0/0/6]/mtu") in kinds(chk)


def test_cross_family_note(kb, asr) -> None:  # type: ignore[no-untyped-def]
    r = template_match.check_text(asr, ATN_SAMPLE, kb)
    assert {n["key"] for n in r["notes"]} >= {"template.note.family", "template.note.profile"}
    assert not r["compliant"]


# ---------- 模板制作辅助 ----------


def test_draft_from_two_configs_round_trips(kb, asr) -> None:  # type: ignore[no-untyped-def]
    other = copy.deepcopy(ASR_ROW)
    other.update(device="PE-08", hostname="PE-ASR920-08", loopback="10.255.0.28", uplink_net="10.1.0.12/30")
    other["svc"] = [
        {"vlan": 201, "vrf": "RAN-3G", "rt": 103, "desc": "RAN-3G-SITE-008", "lan": "172.16.8.0/24"},
        {"vlan": 202, "vrf": "MGMT", "rt": 10, "desc": "MGMT-SITE-008", "lan": "172.17.8.0/28"},
    ]
    texts = [(r["device"], tmod.render_text(asr, template_gen.prepare_row(asr, r)[0])) for r in (ASR_ROW, other)]
    d = template_draft.draft(texts, kb, template_id="asr-draft")
    assert d["valid"], d["issues"]
    names = {v["name"]: v for v in d["vars"]}
    assert names["hostname"]["values"] == ["PE-ASR920-07", "PE-ASR920-08"]
    assert names["vlan"]["type"] == "vlan" and names["vlan"]["values"] == ["101", "201"]
    assert names["ip"]["type"] == "ipv4"
    assert all(v["compliant"] and not v["mismatched"] for v in d["verify"]), d["verify"]
    # 草稿 + 参数表 → 生成，结果与源配置相同
    t = tmod.parse(d["source"], kb)
    g = template_gen.generate(t, d["params"], kb)
    assert g["summary"]["failed"] == 0
    assert [r["text"] for r in g["rows"]] == [x[1] for x in texts]


def test_draft_single_config_identity(kb) -> None:  # type: ignore[no-untyped-def]
    d = template_draft.draft([("pe01", ASR_SAMPLE)], kb, template_id="single")
    assert d["valid"]
    by_reason = {v["name"]: v["reason"] for v in d["vars"]}
    assert by_reason["hostname"] == "identity"
    assert any(v["values"] == ["10.255.0.21"] for v in d["vars"])
    assert d["verify"][0]["compliant"] and not d["verify"][0]["mismatched"]


def test_draft_rejects_mixed_families(kb) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(tmod.TemplateError) as e:
        template_draft.draft([("a", ASR_SAMPLE), ("b", ATN_SAMPLE)], kb)
    assert e.value.key == "template.draft_family"


# ---------- 批量生成 ----------


def test_generate_csv_reports_bad_rows(kb, asr) -> None:  # type: ignore[no-untyped-def]
    rows = template_gen.parse_params((INPUTS / "asr920-sites.csv").read_text(encoding="utf-8"))
    r = template_gen.generate(asr, rows, kb)
    assert r["summary"] == {"total": 3, "ok": 2, "failed": 1}
    bad = r["rows"][2]
    assert {(e["var"], e["problem"]) for e in bad["errors"]} == {
        ("loopback", "template.value.not_within"),
        ("svc.vlan", "template.value.not_unique"),
    }
    good = r["rows"][0]
    assert good["checks"]["roundtrip"] and good["checks"]["parse"]["unknown"] == 0
    assert good["checks"]["template"]["compliant"] and good["file"] == "PE-ASR920-11.cfg"


def test_generate_json_huawei(kb) -> None:  # type: ignore[no-untyped-def]
    t = tmod.load(KB_ROOT, "huawei-atn-l3vpn-subif", kb)
    rows = template_gen.parse_params((INPUTS / "atn-l3-sites.json").read_text(encoding="utf-8"))
    r = template_gen.generate(t, rows, kb)
    assert r["summary"]["failed"] == 0, r["rows"]
    assert "interface GigabitEthernet0/2/4.2401" in r["rows"][0]["text"]


def test_generate_single_instance_extracts_block_only_base_var(kb) -> None:  # type: ignore[no-untyped-def]
    """REQ-055-04：只在重复块里出现的基础变量（{{port}}），块只有 1 个实例时也能从生成结果里提取，校验通过。"""
    t = tmod.load(KB_ROOT, "huawei-atn-l2-bd-vbdif", kb)
    csv_text = (
        "device,port,svc.bd,svc.bd_desc,svc.desc,svc.vrf,svc.lan\n"
        "S1,GigabitEthernet0/2/0,1584,BD-OAM,RAN-OAM,GERENCIA,10.0.183.128/29\n"
    )
    r = template_gen.generate(t, template_gen.parse_params(csv_text), kb)
    assert r["summary"]["failed"] == 0, r["rows"][0]["errors"]
    assert r["rows"][0]["checks"]["template"]["mismatched"] == []


def test_param_errors(kb, asr) -> None:  # type: ignore[no-untyped-def]
    raw = {"device": "X", "hostname": "X1", "nope": "1", "svc.vlan": "1;2", "svc.vrf": "A"}
    _, errors = template_gen.prepare_row(asr, raw)
    problems = {e["problem"] for e in errors}
    assert {"template.param.unknown_column", "template.param.count_mismatch", "template.value.required"} <= problems
    _, errors = template_gen.prepare_row(asr, {**ASR_ROW, "uplink_ip": "1.1.1.1"})
    assert {e["problem"] for e in errors} == {"template.param.derived"}


def test_generate_options(kb, asr) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(tmod.TemplateError) as e:
        template_gen.generate(asr, [ASR_ROW], kb, target_profile="huawei-atn-v800r025")
    assert e.value.key == "template.target_needs_canon"
    with pytest.raises(tmod.TemplateError):
        template_gen.generate(asr, [], kb)
    with pytest.raises(tmod.TemplateError):
        template_gen.parse_params("[1, 2]")


def test_generate_with_canon_renderer(kb, asr) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("lmesh.core.canon")
    r = template_gen.generate(asr, [ASR_ROW], kb, engine="canon")
    row = r["rows"][0]
    assert row["ok"], row["errors"]
    assert row["checks"]["canon"]["uncovered"] == []
    assert row["checks"]["template"]["compliant"]


# ---------- 保存 ----------


def test_save_and_reload(tmp_path: Path, kb) -> None:  # type: ignore[no-untyped-def]
    src = (INPUTS / "optional-demo.yaml").read_text(encoding="utf-8")
    t = tmod.save(tmp_path, "optional-demo", src, kb)
    assert (tmp_path / "templates" / "optional-demo.yaml").exists()
    # 运行时目录原来没有 templates/：先复制程序自带的模板
    assert (tmp_path / "templates" / "cisco-asr920-efp-bdi-vrf.yaml").exists()
    assert tmod.load(tmp_path, "optional-demo", kb).digest == t.digest
    with pytest.raises(tmod.TemplateError) as e:
        tmod.save(tmp_path, "other-id", src, kb)
    assert e.value.key == "template.id_mismatch"
