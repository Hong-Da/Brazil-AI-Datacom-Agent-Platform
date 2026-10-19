"""Nokia SR OS Classic CLI（M7-2）：分块方式（缩进单位、exit 关闭同列的块、注释与版式行、结构行）、引号分词、
端口与 SAP 参数类型、厂商 / 版本 / 格式识别、Nokia 密文写法的脱敏、导入的缺省 Profile。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmesh.core import analysis, importer, parser
from lmesh.core.kb import syntax as syn
from lmesh.core.sanitize import Sanitizer, detect_format, detect_vendor, detect_version, family_of

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
FAM = "nokia-sros-classic"
HEAD = "# TiMOS-B-25.10.R1 both/x86_64 Nokia 7750 SR Copyright (c) 2000-2025 Nokia.\n"
KEY = b"k" * 32


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


def _lines(kb, text: str) -> dict[int, parser.Line]:  # type: ignore[no-untyped-def]
    return {ln.no: ln for ln in parser.parse(text, kb, FAM).lines}


def test_family_settings_drive_the_block_style(kb) -> None:  # type: ignore[no-untyped-def]
    fam = kb.families[FAM]
    assert (fam.block, fam.indent, fam.quotes, fam.begin, fam.comment) == ("exit", 4, True, ["configure"], ["#"])
    # 华为 / Cisco 不设这些键：缺省的缩进分块
    for other in ("huawei-vrp8", "cisco-iosxe"):
        f = kb.families[other]
        assert (f.block, f.quotes, f.begin, f.comment, f.layout) == ("indent", False, [], [], [])


def test_layout_lines_keep_the_view_stack(kb) -> None:  # type: ignore[no-untyped-def]
    text = (
        HEAD + "exit all\n"
        "configure\n"
        "    router Base\n"
        '        interface "system"\n'
        "            address 10.255.0.1/32\n"
        "        exit\n"
        "#--------------------------------------------------\n"
        'echo "Static Route Configuration"\n'
        "#--------------------------------------------------\n"
        "        static-route-entry 0.0.0.0/0\n"
        "            black-hole\n"
        "                no shutdown\n"
        "            exit\n"
        "        exit\n"
        "    exit\n"
        "exit all\n"
    )
    ls = _lines(kb, text)
    assert ls[1].kind == "comment" and ls[2].kind == "end" and ls[3].kind == "separator"  # 文件头、exit all、configure
    assert ls[4].view == "configure" and ls[4].card and kb.cards[ls[4].card].enters_view == "router"
    assert ls[5].view == "router" and ls[6].view == "router-if"
    assert ls[7].card == "@exit:exit" and ls[7].view == "router-if"
    assert [ls[n].kind for n in (8, 9, 10)] == ["separator", "comment", "separator"]
    # 第 0 列的分隔行与 echo 夹在 router 上下文中间，不清空视图栈：静态路由仍在 router 视图
    assert ls[11].view == "router" and ls[12].view == "static-route-entry" and ls[13].view == "static-bh"
    assert ls[16].card == "@exit:exit" and ls[16].view == "router" and ls[16].parent == 4
    assert ls[17].kind == "end"
    assert all(ln.kind != "unknown" for ln in ls.values())


def test_exit_closes_the_raw_block_of_its_own_column(kb) -> None:  # type: ignore[no-untyped-def]
    # pim 没有命令卡：整块按原文保留，块内的 exit 只关闭原文块里的子块，块尾 exit 关闭 pim，不会提前退出 router
    text = (
        "configure\n"
        "    router Base\n"
        "        pim\n"
        '            interface "to-P1"\n'
        "            exit\n"
        "            no shutdown\n"
        "        exit\n"
        "        static-route-entry 10.0.0.0/8\n"
        "            black-hole\n"
        "            exit\n"
        "        exit\n"
        "    exit\n"
    )
    ls = _lines(kb, text)
    assert [ls[n].kind for n in range(3, 8)] == ["raw"] * 5
    assert ls[4].parent == 3 and ls[5].parent == 4 and ls[7].parent == 3
    assert ls[8].kind == "command" and ls[8].view == "router" and ls[9].view == "static-route-entry"
    assert ls[12].card == "@exit:exit" and ls[12].view == "router"


def test_children_of_a_command_without_view_are_raw(kb) -> None:  # type: ignore[no-untyped-def]
    # 卡没有进入视图（bfd 是叶子命令），下一行却缩进更深：子行按原文保留，同列的 exit 关闭它
    text = (
        "configure\n"
        "    router Base\n"
        '        interface "to-P1"\n'
        "            bfd 100 receive 100 multiplier 3\n"
        "                vendor-extension 1\n"
        "            exit\n"
        "            no shutdown\n"
        "        exit\n"
        "    exit\n"
        "    exit\n"
    )
    ls = _lines(kb, text)
    assert ls[4].kind == "command" and not kb.cards[str(ls[4].card)].enters_view
    assert ls[5].kind == "raw" and ls[5].parent == 4
    assert ls[6].kind == "raw" and ls[6].parent == 4
    assert ls[7].kind == "command" and ls[7].view == "router-if" and ls[7].negated
    assert ls[9].card == "@exit:exit" and ls[9].view == "router"
    assert ls[10].kind == "raw"  # 多余的 exit：没有对应的块，原文保留


def test_quoted_names_are_one_token_and_unquoted_in_values(kb) -> None:  # type: ignore[no-untyped-def]
    text = 'configure\n    router Base\n        interface "to P1 core"\n            description "core link to P1"\n'
    ls = _lines(kb, text)
    assert ls[3].values() == {"interface-name": "to P1 core"} and ls[3].fmt is None
    assert ls[4].values() == {"long-description-string": "core link to P1"} and ls[4].fmt is None
    card = kb.cards[str(ls[3].card)]
    assert ls[3].match is not None and syn.render(card.parsed, ls[3].match) == 'interface "to P1 core"'


def test_quote_aware_tokenizer_and_render() -> None:
    s = syn.parse("name <system-name>")
    m = syn.match(s, 'name "PE 1"', {"system-name": {"type": "word"}}, quotes=True)
    assert m is not None and m.values == {"system-name": "PE 1"} and m.quoted == {"system-name"}
    assert syn.render(s, m) == 'name "PE 1"'
    m2 = syn.match(s, "name PE1", {}, quotes=True)
    assert m2 is not None and m2.quoted == set() and syn.render(s, m2) == "name PE1"
    # 不开引号（华为 / Cisco）：照旧按空白分词，引号是取值的一部分
    assert syn.match(s, 'name "PE 1"', {}) is None
    m3 = syn.match(s, 'name "PE1"', {})
    assert m3 is not None and m3.values == {"system-name": '"PE1"'}
    assert syn.tokenize_line('a "b c" d', quotes=True) == [("a", 0), ('"b c"', 2), ("d", 8)]
    # 重复组里的引号各自记录
    r = syn.parse("export <p> [ <p> ] &<1-4>")
    mr = syn.match(r, 'export "A" B "C D"', {}, quotes=True)
    assert mr is not None and mr.all_values() == {"p": ["A", "B", "C D"]}
    assert syn.render(r, mr) == 'export "A" B "C D"'


@pytest.mark.parametrize(
    "value,kind,ok",
    [
        ("1/1/1", "port", True),
        ("1/1/c1/1", "port", True),
        ("lag-1", "port", True),
        ("esat-1/1/1", "port", True),
        ("esat-1/1/u1", "port", True),
        ("pxc-1.a", "port", True),
        ("1/1/1:100", "port", False),
        ("system", "port", False),
        ("1/1/1:100", "sap", True),
        ("1/1/1:100.200", "sap", True),
        ("lag-1:10", "sap", True),
        ("1/1/1:*", "sap", True),
        ("1/1/1", "sap", True),
        ("1/1/1:abc", "sap", False),
    ],
)
def test_port_and_sap_types(value: str, kind: str, ok: bool) -> None:
    assert syn.type_ok(value, {"type": kind}) is ok


def test_detect_nokia_vendor_version_and_format() -> None:
    classic = HEAD + 'exit all\nconfigure\n    system\n        name "PE1"\n    exit\nexit all\n'
    assert detect_vendor(classic) == "nokia" and detect_version(classic, "nokia") == "25.10.R1"
    assert detect_format(classic, "nokia") == "classic" and family_of("nokia", "classic") == FAM
    md = HEAD + 'configure {\n    system {\n        name "PE1"\n    }\n}\n'
    assert detect_format(md, "nokia") == "md" and family_of("nokia", "md") == "nokia-sros-md"
    # 没有文件头：靠版式特征
    assert (
        detect_vendor('exit all\nconfigure\n#--------------------------------------------------\necho "x"\n') == "nokia"
    )
    assert detect_format("hostname R1\n", "cisco") == "" and family_of("cisco", "") is None


def test_sanitize_nokia_secrets_keep_quotes() -> None:
    text = (
        HEAD + "# Generated 2026-10-19T08:00:00.0+00:00 by opsadmin from Console\n"
        "configure\n"
        "    system\n"
        '        name "PE-REAL-9"\n'
        "        security\n"
        '            user "alice"\n'
        '                password "$2y$10$abcdefghijklmnopqrstuv"\n'
        "            exit\n"
        "            snmp\n"
        '                community "s3cretComm" rwa version both\n'
        "            exit\n"
        "            tacplus\n"
        '                server 1 address 203.0.113.9 secret "tacKey99" hash2\n'
        "            exit\n"
        "        exit\n"
        "    exit\n"
        "    router Base\n"
        '        interface "to-PE-REAL-9"\n'
        '            description "uplink to PE-REAL-9 site X"\n'
        "        exit\n"
        "        bgp\n"
        '            group "IBGP"\n'
        "                authentication-key ABCDEF0123 hash2\n"
        "            exit\n"
        "        exit\n"
        "        policy-options\n"
        '            community "RT-100"\n'
        '                members "target:64500:100"\n'
        "            exit\n"
        "        exit\n"
        "    exit\n"
    )
    r = Sanitizer("strict", KEY).sanitize(text)
    out = r.text
    assert r.vendor == "nokia" and out.count("\n") == text.count("\n")
    for leaked in (
        "$2y$10$abcdefghijklmnopqrstuv",
        "s3cretComm",
        "tacKey99",
        "ABCDEF0123",
        "PE-REAL-9",
        "alice",
        "opsadmin",
    ):
        assert leaked not in out
    assert '        name "DEVICE-' in out and '            user "user-' in out
    assert '                password "LMESH-SECRET-' in out and ' secret "LMESH-SECRET-' in out
    assert '                community "LMESH-COMM-' in out and " rwa version both" in out
    assert '            description "DESC-' in out  # 描述替换后仍带引号
    # 路由策略里的 community 是名称，不是秘密
    assert '            community "RT-100"' in out and 'members "target:64500:100"' in out
    # 华为 / Cisco 的规则不套到 Nokia（例如 cipher 后面的词不当作密文）
    keep = (
        HEAD + "configure\n    system\n        security\n            ssh\n                cipher 190 name aes256-ctr\n"
    )
    assert "cipher 190 name aes256-ctr" in Sanitizer("basic", KEY).sanitize(keep).text


def test_import_guesses_nokia_profile_and_device_name() -> None:
    assert importer.guess_profile("nokia", "25.10.R1", None, "classic") == "nokia-sros-classic-7750-25.10"
    assert importer.guess_profile("nokia", "25.10.R1", None, "md") == "nokia-sros-md-7750-25.10"
    raw = (HEAD + 'exit all\nconfigure\n    system\n        name "PE7"\n    exit\nexit all\n').encode()
    res, text = importer.sanitize_one("pe7.cfg", raw, Sanitizer("basic", KEY))
    assert res.ok and (res.vendor, res.version, res.device) == ("nokia", "25.10.R1", "PE7")
    assert res.profile == "nokia-sros-classic-7750-25.10" and text.count("\n") == raw.decode().count("\n")
