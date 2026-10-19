"""M7-5（REQ-037）：Nokia 显示风格、端口与业务检查规则、安全基线、跨设备一致性、补齐的写法。

样本都是合成配置（tests/inputs/configs/check/nokia-*-issues.cfg、tests/inputs/configs/nokia/*.cfg，已过 lmesh sanitize）；
Classic 与 MD-CLI 两种格式各一份，规则写在统一 Schema 上，两种格式的结论必须相同。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lmesh.core import analysis, baseline, canon, checks, consistency, terms, topology, translate
from lmesh.core import graph as graphmod
from lmesh.core import rules as rulesmod

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parent.parent.parent
KB_ROOT = ROOT / "knowledge"
INPUTS = ROOT / "tests" / "inputs" / "configs"
SAMPLES = KB_ROOT / "samples"


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


def _graph(kb: Any, path: Path, profile: str | None = None) -> Any:
    res = analysis.parse_text(path.read_text(encoding="utf-8"), kb, profile)
    assert res.parsed.counts().get("unknown", 0) == 0
    return graphmod.build(res.parsed, kb, res.profile, path.stem)


# ---------- 显示风格 ----------


def test_every_object_has_nokia_style(kb) -> None:  # type: ignore[no-untyped-def]
    t = terms.load(KB_ROOT, kb)
    assert terms.check(kb, t) == []
    assert "nokia" in terms.REQUIRED_STYLES
    missing = [n for n, s in t.objects.items() if "nokia" not in (s or {})]
    assert missing == []


@pytest.mark.parametrize(
    ("schema", "key", "nokia"),
    [
        ("interface", "1/1/4", "port 1/1/4"),
        ("interface", "lag-1", "lag-1"),
        ("interface", "to-CE1", 'interface "to-CE1"'),
        ("vrf.instance.af.rt", {"value": "64500:1", "direction": "both"}, "vrf-target target:64500:1"),
        ("vrf.instance.af.rt", {"value": "64500:1", "direction": "export"}, "vrf-target export target:64500:1"),
        ("l2vpn.xconnect", "EPIPE-1", "epipe EPIPE-1"),
        ("acl.instance", "10", "filter ip-filter 10"),
        ("mgmt.maf", "_", "system security management-access-filter"),
    ],
)
def test_nokia_labels(kb, schema, key, nokia) -> None:  # type: ignore[no-untyped-def]
    assert terms.load(KB_ROOT, kb).label(schema, key, "nokia") == nokia


def test_nokia_contexts(kb) -> None:  # type: ignore[no-untyped-def]
    t = terms.load(KB_ROOT, kb)
    assert t.context("interface", "1/1/4", {}, "nokia") == ["port"]
    assert t.context("interface", "system", {}, "nokia") == ["router Base"]
    assert t.context("interface", "to-CE1", {"vrf": "VPRN-1"}, "nokia") == ["service", "vprn VPRN-1"]
    assert t.context("rp.policy", "P", {}, "nokia") == ["router Base", "policy-options"]
    assert t.context("mgmt.syslog", "_", {}, "nokia") == ["log"]
    assert t.context("interface", "system", {}, "huawei") == []  # 华为 / Cisco 不分组


# ---------- 规则引擎扩展 ----------


def test_lookup_path_and_default_condition(kb) -> None:  # type: ignore[no-untyped-def]
    docs = [
        (
            "t.yaml",
            {
                "rules": [
                    {
                        "id": "t.bound",
                        "target": "interface",
                        "when": {"exists": "bind_port"},
                        "assert": {"not": {"equals": {"path": "bind_port=>shutdown", "value": True}}},
                        "severity": "error",
                        "title": {"zh-CN": "x", "en": "x", "pt-BR": "x"},
                        "message": {"zh-CN": "x", "en": "x", "pt-BR": "x"},
                        "suggestion": {"zh-CN": "x", "en": "x", "pt-BR": "x"},
                        "remedy": {"nokia": ["c {key}"], "nokia-sros-md": ["m {key}"]},
                    },
                    {
                        "id": "t.default",
                        "target": "device",
                        "assert": {"default": {"node": "mgmt.ssh.enabled", "value": True}},
                        "severity": "info",
                        "title": {"zh-CN": "x", "en": "x", "pt-BR": "x"},
                        "message": {"zh-CN": "x", "en": "x", "pt-BR": "x"},
                        "suggestion": {"zh-CN": "x", "en": "x", "pt-BR": "x"},
                    },
                ]
            },
        )
    ]
    rules = rulesmod.parse_rules(kb, docs)
    gc = _graph(kb, INPUTS / "check" / "nokia-classic-issues.cfg")
    gm = _graph(kb, INPUTS / "check" / "nokia-md-issues.cfg")
    for g, cmd in ((gc, "c to-SIDE"), (gm, "m to-SIDE")):
        res = checks.check(g, kb, rules)
        hit = [f for f in res["findings"] if f["rule"] == "t.bound"]
        assert [f["node"] for f in hit] == ["interface[to-SIDE]"]
        assert hit[0]["remedy"] == [cmd]  # 平台族名优先于风格名
        assert not [f for f in res["findings"] if f["rule"] == "t.default"]  # Nokia SSH 缺省开启
    with pytest.raises(rulesmod.RuleError):
        rulesmod.parse_rules(
            kb, [("x.yaml", {"rules": [{**docs[0][1]["rules"][0], "assert": {"exists": "description=>x"}}]})]
        )


# ---------- 检查规则 ----------

EXPECTED_CHECK = {
    ("port.shutdown_bound", "interface[to-SIDE]"),
    ("port.shutdown_with_sap", "interface[1/1/5]/access[200]"),
    ("port.lag_member_shutdown", "interface[1/1/3]"),
    ("sdp.far_end_missing", "service.sdp[10]"),
    ("sdp.keep_alive_disabled", "service.sdp[10]"),
    ("service.pw_sdp_shutdown", "l2vpn.xconnect[EPIPE-100]/pw[peer=10.255.8.2,vc_id=100]"),
    ("service.vpls_sdp_shutdown", "l2vpn.vsi[VPLS-200]/peer[10.255.8.2]"),
    ("service.epipe_shutdown", "l2vpn.xconnect[EPIPE-100]"),
    ("service.sap_shutdown", "interface[1/1/4]/access[100]"),
    ("service.vpls_customer_missing", "l2vpn.vsi[VPLS-200]"),
    ("vprn.no_rd_rt", "vrf.instance[VPRN-300]"),
    # SAP 引用的 QoS 策略与过滤器、业务引用的客户不存在：内置检查报出
    ("ref.dangling", "interface[1/1/4]/access[101]/qos_in"),
    ("ref.dangling", "interface[1/1/4]/access[101]/acl_in"),
    ("ref.dangling", "vrf.instance[VPRN-300]/customer"),
}


@pytest.mark.parametrize("name", ["nokia-classic-issues.cfg", "nokia-md-issues.cfg"])
def test_nokia_check_rules(kb, name: str) -> None:  # type: ignore[no-untyped-def]
    rules = rulesmod.load_dir(kb, checks.rules_dir(KB_ROOT))
    res = checks.check(_graph(kb, INPUTS / "check" / name), kb, rules)
    got = {(f["rule"], f["node"]) for f in res["findings"]}
    assert got == EXPECTED_CHECK
    remedy = next(f["remedy"] for f in res["findings"] if f["rule"] == "sdp.far_end_missing")
    assert remedy == (
        ["configure service sdp 10 far-end <SYSTEM-IP>"]
        if "classic" in name
        else ["configure service sdp 10 far-end ip-address <SYSTEM-IP>"]
    )
    assert all("remedy" not in f for f in res["findings"] if f["rule"] == "ref.dangling")


@pytest.mark.parametrize(
    "rel",
    ["nokia-sros-classic-synthetic/classic-pe-basic.cfg", "nokia-sros-md-synthetic/md-pe-basic.cfg"],
)
def test_nokia_clean_samples(kb, rel: str) -> None:  # type: ignore[no-untyped-def]
    """端口都 no shutdown、业务都启用的样本没有发现（不误报）。"""
    rules = rulesmod.load_dir(kb, checks.rules_dir(KB_ROOT))
    res = checks.check(_graph(kb, SAMPLES / rel), kb, rules)
    assert res["findings"] == []


def test_service_rules_silent_on_huawei_cisco(kb) -> None:  # type: ignore[no-untyped-def]
    rules = [r for r in rulesmod.load_dir(kb, checks.rules_dir(KB_ROOT)) if r.file == "service.yaml"]
    assert len(rules) == 17
    for rel in (
        "huawei-atn-v800r023/atn-access-01.cfg",
        "huawei-atn-v800r025-synthetic/atn-mpls-l2vpn-acl-01.cfg",
        "cisco-iosxe-asr920-synthetic/pe-asr920-03-mpls-l2vpn-acl.cfg",
    ):
        assert rulesmod.evaluate(_graph(kb, SAMPLES / rel), rules) == []


# ---------- 安全基线 ----------


def _audit(kb: Any, paths: list[Path], profile: str) -> dict[str, Any]:
    bl = baseline.load(kb, baseline.baseline_dir(KB_ROOT))
    return baseline.audit([_graph(kb, p) for p in paths], bl, profile)


def test_baseline_hardened_nokia(kb) -> None:  # type: ignore[no-untyped-def]
    paths = [INPUTS / "nokia" / "baseline-classic-hardened.cfg", INPUTS / "nokia" / "baseline-md-hardened.cfg"]
    basic = _audit(kb, paths, "basic")
    for d in basic["devices"]:
        assert d["score"] == 100, d["failures"]
        for rid in (
            "sec.mgmt_access_filter",
            "sec.login_idle_timeout",
            "sec.ssh_v2",
            "sec.aaa_enabled",
            "sec.ntp_auth",
        ):
            assert d["results"][rid] == "pass"
        for rid in ("sec.vty_ssh_only", "sec.line_idle_timeout"):  # 没有登录线路
            assert d["results"][rid] == "na"
    strict = _audit(kb, paths, "strict")
    assert [sorted(f["rule"] for f in d["failures"]) for d in strict["devices"]] == [["sec.snmp_v3_only"]] * 2
    c, m = strict["devices"]
    assert c["results"]["sec.password_aging"] == "pass"
    assert m["results"]["sec.password_aging"] == "na"  # MD-CLI 的口令策略在命令卡范围外


def test_baseline_nokia_failures_and_remedy(kb) -> None:  # type: ignore[no-untyped-def]
    paths = [
        SAMPLES / "nokia-sros-classic-synthetic" / "classic-pe-routing-mgmt.cfg",
        SAMPLES / "nokia-sros-md-synthetic" / "md-pe-routing-mgmt.cfg",
    ]
    res = _audit(kb, paths, "basic")
    c, m = res["devices"]
    common = {
        "sec.telnet_disabled",
        "sec.ftp_disabled",
        "sec.snmp_community_acl",
        "sec.ntp_auth",
        "sec.mgmt_access_filter",
    }
    assert {r for r, v in c["results"].items() if v == "fail"} == common | {"sec.local_user_secure_service"}
    assert {r for r, v in m["results"].items() if v == "fail"} == common  # MD 的用户 access 是布尔叶子，未归并
    tel = {d["family"]: next(f for f in d["failures"] if f["rule"] == "sec.telnet_disabled") for d in (c, m)}
    assert tel["nokia-sros-classic"]["remedy"][0] == "configure system security no telnet-server"
    assert tel["nokia-sros-md"]["remedy"][0] == "/configure system security telnet-server false"
    rule = next(r for r in res["rules"] if r["id"] == "sec.telnet_disabled")
    assert set(rule["remedy"]) == {"huawei", "cisco", "nokia", "nokia-sros-md"}


# ---------- 跨设备一致性 ----------


def test_topology_nokia_classic_md(kb) -> None:  # type: ignore[no-untyped-def]
    items = [
        {"name": f.name, "text": f.read_text(encoding="utf-8"), "profile": None}
        for f in (INPUTS / "nokia" / "topo-pe-a.cfg", INPUTS / "nokia" / "topo-pe-b.cfg")
    ]
    topo = topology.build(topology.from_texts(items, kb), kb)
    data = topology.to_json(topo)
    assert sorted(d["id"] for d in data["nodes"]) == ["NK-TOPO-A", "NK-TOPO-B"]  # 设备名取 system name
    assert {lk["type"] for lk in data["links"]} == {"subnet", "ospf", "ldp", "bgp", "pw"}
    assert data["unresolved"] == []
    res = consistency.check(topo, kb, consistency.load(kb, consistency.rules_file(KB_ROOT)))
    assert {f["rule"] for f in res["findings"]} == {"xd.ospf.hello", "xd.ospf.dead", "xd.pw.vc_id"}
    assert res["rules_skipped"] == []
    a = topo.facts["NK-TOPO-A"]
    assert a.lsr_id == "10.255.9.1" and a.ifaces["system"].loopback
    assert next(p for p in a.bgp_peers())["afs"] == ["vpnv4"]  # Classic 的 family vpn-ipv4
    assert next(p for p in topo.facts["NK-TOPO-B"].bgp_peers())["afs"] is None  # MD-CLI 的 family 未归并：不比较


# ---------- 补齐的写法 ----------


def test_vrf_target_export_import(kb) -> None:  # type: ignore[no-untyped-def]
    g = _graph(kb, SAMPLES / "nokia-sros-classic-synthetic" / "classic-pe-services.cfg")
    rts = sorted(n for n, d in g.nodes(data=True) if d.get("schema") == "vrf.instance.af.rt" and "VPRN-3002" in n)
    assert rts == [
        "vrf.instance[VPRN-3002]/af[ipv4]/rt[value=64500:3002,direction=export]",
        "vrf.instance[VPRN-3002]/af[ipv4]/rt[value=64500:3002,direction=import]",
    ]
    assert g.nodes[rts[1] + "/direction"]["value"] == "import"
    text = canon.render_full(g, kb, "nokia-sros-classic-7750-25.10").text
    assert "vrf-target export target:64500:3002" in text and "vrf-target import target:64500:3002" in text


def test_flag_inverted_is_not_negated(kb) -> None:  # type: ignore[no-untyped-def]
    """no shutdown → 启用（!flag）：节点取值为 true，不是取消形式（检查、拓扑按有效值判断）。"""
    g = _graph(kb, SAMPLES / "nokia-sros-classic-synthetic" / "classic-pe-basic.cfg")
    d = g.nodes["interface[to-P1]/mpls[_]/ldp"]
    assert d["value"] is True and not d.get("negated")


def test_bgp_family_translation(kb) -> None:  # type: ignore[no-untyped-def]
    src = (SAMPLES / "cisco-iosxe-asr920-synthetic" / "pe-asr920-01.cfg").read_text(encoding="utf-8")
    r = translate.translate_text(src, kb, "nokia-sros-classic-7750-25.10", "cisco-iosxe-asr920-17.15")
    assert "family ipv4 vpn-ipv4" in r["text"]
    assert r["verify"]["unexplained"] == 0
    src = (SAMPLES / "nokia-sros-classic-synthetic" / "classic-pe-routing-mgmt.cfg").read_text(encoding="utf-8")
    r = translate.translate_text(src, kb, "huawei-atn-v800r025", "nokia-sros-classic-7750-25.10")
    assert "ipv4-family vpnv4" in r["text"] and "peer IBGP-RR enable" in r["text"]
    assert r["verify"]["unexplained"] == 0
