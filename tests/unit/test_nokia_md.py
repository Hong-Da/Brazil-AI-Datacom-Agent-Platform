"""M7-4：Nokia SR OS MD-CLI——花括号与扁平格式的解析、映射表达式扩展（list: / by: / scale: / strip: / @first）、
Classic 版与 MD-CLI 版建出的图等价（列明允许的差异）、Profile 复用 Classic 的缺省值、规范渲染（花括号）、变更脚本、
格式识别与脱敏。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmesh.core import analysis, canon, change, cleanup, parser, sanitize, script_check
from lmesh.core import compare as cmp
from lmesh.core import graph as graphmod
from lmesh.core.kb import mapping
from lmesh.core.kb import syntax as syn
from lmesh.core.renderer import render_roundtrip

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parent.parent.parent
KB_ROOT = ROOT / "knowledge"
MD = KB_ROOT / "samples" / "nokia-sros-md-synthetic"
CLASSIC = KB_ROOT / "samples" / "nokia-sros-classic-synthetic"
PID = "nokia-sros-md-7750-25.10"
CPID = "nokia-sros-classic-7750-25.10"
FAMILY = "nokia-sros-md"
NL = chr(10)

# Classic 版与 MD-CLI 版的图允许的差异（kind, 节点）：
#   - acl.instance.filter_name：MD-CLI 的过滤器以名称为列表键（记到 filter_name），Classic 的映射不记 name（M7-3，结果不能变）
#   - destination_port（range 161 162）：MD-CLI 的端口范围拆成 range { start end } 两个叶子，暂不归并
#   - bgp.instance.family：MD-CLI 的 family 是逐个地址族的布尔叶子，暂不归并（MD 取 Profile 缺省值 ipv4）
#   - rt import：Classic 的 vrf-target export X import Y 一行只记了 export（M7-3 的已知限制），MD-CLI 两行都记
#   - aaa 用户的 service_type：MD-CLI 的 access 是逐个布尔叶子，暂不归并
ALLOWED = {
    "basic": set(),
    "services": {
        ("added", "acl.instance[10]/filter_name"),
        ("removed", "acl.instance[10]/rule[20]/destination_port"),
        ("changed", "bgp.instance[64500]/family"),
        ("added", "vrf.instance[VPRN-3002]/af[ipv4]/rt[value=64500:3002,direction=import]"),
    },
    "routing-mgmt": {
        ("changed", "bgp.instance[64500]/family"),
        ("removed", "mgmt.aaa[_]/user[operator1]/service_type"),
    },
}


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


def _graph(kb, text: str, pid: str = PID):  # type: ignore[no-untyped-def]
    res = analysis.parse_text(text, kb, pid)
    return res.parsed, graphmod.build(res.parsed, kb, pid, "d")


def _full_context(text: str) -> str:
    """花括号格式 → admin show configuration full-context（每行 /configure 开头的完整路径，空块写 { }）。"""
    out: list[str] = []
    path: list[str] = []
    empty: list[bool] = []
    inside = False
    for ln in text.split("\n"):
        s = ln.strip()
        if not inside:
            if s == "configure {":
                inside = True
            else:
                out.append(ln)
            continue
        if s == "}":
            if not path:
                inside = False
                continue
            if empty[-1]:
                out.append("/configure " + " ".join(path) + " { }")
            path.pop()
            empty.pop()
            if empty:
                empty[-1] = False
        elif s.endswith("{"):
            path.append(s[:-1].strip())
            empty.append(True)
        else:
            out.append("/configure " + " ".join([*path, s]))
            if empty:
                empty[-1] = False
    return "\n".join(out)


def _semantic(g) -> dict[str, object]:  # type: ignore[no-untyped-def]
    return {n: d.get("value") for n, d in g.nodes(data=True) if d.get("kind") in ("object", "attr")}


# ---------------------------------------------------------------- 解析：花括号、扁平、full-context


def test_braces_parse_and_roundtrip(kb) -> None:  # type: ignore[no-untyped-def]
    text = (MD / "md-pe-basic.cfg").read_text(encoding="utf-8")
    parsed, g = _graph(kb, text)
    c = parsed.counts()
    assert c.get("unknown", 0) == 0 and c["command"] > 150
    assert not any(ln.virtual for ln in parsed.lines)
    assert render_roundtrip(g, kb) == text
    head = next(ln for ln in parsed.lines if ln.text == 'interface "to-P1"')
    assert head.tail == " {" and head.view == "router" and head.card == "nokia-sros-md.router-interface"
    close = [ln for ln in parsed.lines if ln.card == "@exit:}" and ln.parent == head.no]
    assert len(close) == 1 and close[0].indent == head.indent and close[0].view == "router.interface"
    # 结构行 configure { 下的行仍是顶层行；范围外的块（card）整块原文保留
    assert next(ln for ln in parsed.lines if ln.text == "card 1").kind == "raw"
    assert next(ln for ln in parsed.lines if ln.text == 'lag "lag-1"').parent is None


def test_flat_and_full_context_same_graph(kb) -> None:  # type: ignore[no-untyped-def]
    braces = (MD / "md-pe-basic.cfg").read_text(encoding="utf-8")
    flat = (MD / "md-pe-basic-flat.cfg").read_text(encoding="utf-8")
    full = _full_context(braces)
    _, gb = _graph(kb, braces)
    for text in (flat, full):
        parsed, g = _graph(kb, text)
        assert parsed.counts().get("unknown", 0) == 0
        assert render_roundtrip(g, kb) == text  # 补出的路径行不输出，原文行按 prefix + 命令重放
        assert _semantic(g) == _semantic(gb)
        virtual = [ln for ln in parsed.lines if ln.virtual]
        assert virtual and min(ln.no for ln in virtual) > len(text.split("\n"))  # 编号接在最后一行之后
    parsed, _ = _graph(kb, full)
    addr = next(ln for ln in parsed.lines if ln.text == "address 10.0.12.1")
    assert addr.prefix == '/configure router "Base" interface "to-P1" ipv4 primary '
    assert addr.view == "router.interface.ipv4.primary"
    # 相邻行共用同一路径行：prefix-length 的父行与 address 的相同
    plen = next(ln for ln in parsed.lines if ln.no == addr.no + 1)
    assert plen.parent == addr.parent


def test_leaflist_and_brace_tail_syntax() -> None:
    s = syn.parse("policy <policy>")
    params = {"policy": {"type": "leaflist"}}
    m = syn.match(s, 'policy ["a b" "c"]', params, True)
    assert m is not None and m.values["policy"] == '["a b" "c"]'
    assert syn.render(s, m) == 'policy ["a b" "c"]'
    assert syn.match(s, 'policy "one"', params, True).values["policy"] == "one"  # type: ignore[union-attr]
    assert mapping.split_leaflist('["a b" "c"]') == ["a b", "c"] and mapping.split_leaflist("x") == ["x"]
    assert mapping.join_leaflist(["IBGP-OUT"]) == '["IBGP-OUT"]' and mapping.join_leaflist(["10.0.0.1"]) == "[10.0.0.1]"
    assert syn.type_ok("1/1/1", {"type": "port", "pattern": "(?!lag-).+"})
    assert not syn.type_ok("lag-1", {"type": "port", "pattern": "(?!lag-).+"})


def test_detect_format() -> None:
    braces = (MD / "md-pe-basic.cfg").read_text(encoding="utf-8")
    flat = (MD / "md-pe-basic-flat.cfg").read_text(encoding="utf-8")
    classic = (CLASSIC / "classic-pe-basic.cfg").read_text(encoding="utf-8")
    for text, fmt in ((braces, "md"), (flat, "md"), (_full_context(braces), "md"), (classic, "classic")):
        assert sanitize.detect_vendor(text) == "nokia"
        assert sanitize.detect_format(text, "nokia") == fmt
    assert sanitize.family_of("nokia", "md") == FAMILY


# ---------------------------------------------------------------- 映射表达式与建图


def test_md_expressions() -> None:
    rl = {"rlookup": lambda s, a, w: ["100"] if (s, a, w) == ("service.customer", "name", "ACME") else []}
    assert mapping.evaluate("by:service.customer:name:$customer", {"customer": "ACME"}, [], False, ctx=rl) == "100"
    assert mapping.evaluate("by:service.customer:name:$customer", {"customer": "X"}, [], False, ctx=rl) == "X"
    assert mapping.evaluate("list:$p", {"p": '["a" "b"]'}, [], False) == ["a", "b"]
    assert mapping.evaluate("scale:0.1:$m", {"m": "100"}, [], False) == "10"
    assert mapping.evaluate("scale:0.1:$m", {"m": "15"}, [], False) is None
    assert mapping.evaluate("strip:lag-:ctx:lag-name", {}, [], False, ctx={"params": {"lag-name": "lag-1"}}) == "1"
    toks = ["admin-state", "disable"]
    assert mapping.evaluate("kw:disable=true|enable=false", {}, toks, False) == "true"
    assert mapping.is_directive(mapping.FIRST)


def test_first_and_second_pass(kb) -> None:  # type: ignore[no-untyped-def]
    text = (MD / "md-pe-services.cfg").read_text(encoding="utf-8")
    parsed, g = _graph(kb, text)
    # customer-id 写在描述之后（字母序）：@first 先建对象，描述写到同一个客户上；业务按名称引用换成编号
    assert g.nodes["service.customer[100]"]["key"] == "100"
    assert g.nodes["service.customer[100]/name"]["value"] == "ACME"
    assert g.nodes["service.customer[100]/description"]["value"] == "ACME Corp (synthetic)"
    assert g.nodes["l2vpn.xconnect[EPIPE-1001]/customer"]["value"] == "100"
    assert g.nodes["interface[1/1/4]/access[1001]/qos_in"]["value"] == "100"
    assert g.nodes["interface[1/1/4]/access[1001]/acl_in"]["value"] == "10"
    # spoke-sdp 在 sdp 之前（字母序）：第二遍建图取到 SDP 的 far-end
    assert "l2vpn.xconnect[EPIPE-1001]/pw[peer=10.255.0.2,vc_id=1001]" in g
    assert g.graph["dangling"] == []
    # 语句按原文顺序（往返）
    assert [st.line.no for st in g.graph["statements"]] == [ln.no for ln in parsed.lines]
    assert render_roundtrip(g, kb) == text


@pytest.mark.parametrize("name", ["basic", "services", "routing-mgmt"])
def test_classic_and_md_graphs_equivalent(kb, name: str) -> None:  # type: ignore[no-untyped-def]
    """同一配置的 Classic 版与 MD-CLI 版建出的图等价（按有效值对比，列明允许的差异）。"""
    _, gc = _graph(kb, (CLASSIC / f"classic-pe-{name}.cfg").read_text(encoding="utf-8"), CPID)
    _, gm = _graph(kb, (MD / f"md-pe-{name}.cfg").read_text(encoding="utf-8"))
    r = cmp.compare(cmp.Side(gc, "classic"), cmp.Side(gm, "md"), kb)
    got = {(d["kind"], d["node"]) for d in r["diffs"]}
    assert got == ALLOWED[name]


def test_profile_defaults_from_classic(kb) -> None:  # type: ignore[no-untyped-def]
    md = kb.resolve_profile(PID)
    cl = kb.resolve_profile(CPID)
    assert kb.profiles[PID].defaults_from == CPID
    for node in ("static.route.preference", "interface.shutdown", "bgp.instance.keepalive"):
        e, c = md.entries[node], cl.entries[node]
        assert (e.default, e.when, e.assume) == (c.default, c.when, c.assume)
        assert all(x.startswith("nokia-sros-md.") for x in e.cards)  # 命令卡仍是本平台族的
    assert md.entries["acl.instance.filter_name"].supported


# ---------------------------------------------------------------- 规范渲染、变更脚本


def test_canonical_braces(kb) -> None:  # type: ignore[no-untyped-def]
    text = (MD / "md-pe-basic.cfg").read_text(encoding="utf-8")
    _, g = _graph(kb, text)
    r = canon.render_full(g, kb, PID)
    lines = r.text.split("\n")
    assert lines[0] == "configure {" and lines[-1] == "}"
    assert lines.count('    router "Base" {') == 1  # 同一容器的块合并
    assert "        port 1/1/2 {" in lines  # lag 下的成员口：只写原来在块里的 priority
    assert sum(ln.count("{") for ln in lines) == sum(ln.count("}") for ln in lines)
    c = cmp.compare(cmp.Side(g, "a"), cmp.side_from_text(r.text, kb, PID, "b"), kb, include_raw=True)
    assert c["equal"]


def test_change_script_md(kb) -> None:  # type: ignore[no-untyped-def]
    base = KB_ROOT / "samples" / "change"
    r = change.change_text(
        (base / "md-base.cfg").read_text(encoding="utf-8"), (base / "md-del-peer.cfg").read_text(encoding="utf-8"), kb
    )
    plain = r["script_plain"].split("\n")
    assert plain[0] == "edit-config private" and "commit" in plain and "quit-config" in plain
    assert '        delete neighbor "10.255.0.102"' in plain
    assert r["verify"]["ok"] and r["rollback"]["verify"]["ok"]


def test_cleanup_and_script_check_md(kb) -> None:  # type: ignore[no-untyped-def]
    base = (KB_ROOT / "samples" / "change" / "md-base.cfg").read_text(encoding="utf-8")
    text = base.replace(
        "                export {" + NL + '                    policy ["IBGP-OUT"]' + NL + "                }" + NL, ""
    )
    assert text != base
    _, g = _graph(kb, text)
    r = cleanup.cleanup(g, kb)
    assert r["verify"]["ok"] and r["fallbacks"] == 0
    lines = r["script"].split(NL)
    assert lines[1] == "edit-config private" and "commit" in lines and "quit-config" in lines
    assert "policy-options {" in lines and '    delete policy-statement "IBGP-OUT"' in lines
    # 客户由容器里的 customer-id 建立：删除整个容器
    assert '    delete customer "ACME"' in lines and "delete customer-id" not in r["script"]
    tgt = (KB_ROOT / "samples" / "change" / "md-add-vprn.cfg").read_text(encoding="utf-8")
    c = change.change_text(tgt, base, kb, rollback=False)
    assert c["verify"]["ok"]
    plain = [ln.strip() for ln in c["script_plain"].split(NL)]
    assert plain.index("admin-state disable") < plain.index('delete vprn "IOT"')  # 删除业务前先 admin-state disable
    out = script_check.check_text(c["script"], kb, script_check.baseline_from_text(tgt, kb), "change")
    assert out["summary"]["errors"] == 0 and out["summary"]["unknown"] == 0


def test_sanitize_md_secrets() -> None:
    text = "\n".join(
        [
            "# TiMOS-B-25.10.R1 both/x86_64 Nokia 7750 SR Copyright (c) 2000-2025 Nokia.",
            "configure {",
            "    policy-options {",
            '        community "RT-1" {',
            "        }",
            "    }",
            "    system {",
            '        name "REALPE"',
            "        security {",
            "            snmp {",
            '                community "s3cret" {',
            "                    access-permissions r",
            "                }",
            "            }",
            "        }",
            "    }",
            "}",
            '/configure system security snmp community "flat-s3cret" access-permissions r',
            '/configure system security user-params local-user user "bob" password "$2y$10$abc"',
            '/configure system name "FLATPE"',
        ]
    )
    out = sanitize.Sanitizer("strict").sanitize(text).text
    assert "s3cret" not in out and "flat-s3cret" not in out and "$2y$10$abc" not in out
    assert "REALPE" not in out and "FLATPE" not in out and '"bob"' not in out
    assert 'community "RT-1" {' in out  # 路由策略里的 community 名称不是秘密


def test_parser_family_settings(kb) -> None:  # type: ignore[no-untyped-def]
    fam = kb.families[FAMILY]
    assert (fam.block, fam.negative, fam.root_view, fam.quotes) == ("braces", "delete", "configure", True)
    idx = parser.CardIndex(kb, FAMILY)
    hit = parser.match_line(idx, "router", 'interface "to P1"')
    assert hit is not None and hit[1].values["interface-name"] == "to P1"
    neg = parser.match_undo(idx, "router.bgp", 'delete neighbor "10.0.0.1"')
    assert neg is not None and neg[0].id == "nokia-sros-md.router-bgp-neighbor"
