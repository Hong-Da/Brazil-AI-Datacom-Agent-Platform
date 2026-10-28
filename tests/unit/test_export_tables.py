"""审计表格导出（M5-3）：预置模板、每格的来源与追溯（节点、行号）、派生列、筛选、敏感字段只写已配置、
CSV（UTF-8 BOM、三语表头、来源列）与 XLSX（说明页、批注标默认值）、自定义列与错误。"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from lmesh.core import analysis, export_tables, topology

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
TOPO = KB_ROOT / "samples" / "topology"


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


@pytest.fixture(scope="module")
def devices(kb):  # type: ignore[no-untyped-def]
    items = [{"name": f.name, "text": f.read_text(encoding="utf-8")} for f in sorted(TOPO.glob("*.cfg"))]
    items.append({"name": "atn-base.cfg", "text": (KB_ROOT / "samples" / "change" / "atn-base.cfg").read_text("utf-8")})
    return topology.from_texts(items, kb)


def build(kb, devices, **kw):  # type: ignore[no-untyped-def]
    return export_tables.build(devices, kb, KB_ROOT, **kw)


def col(t, key):  # type: ignore[no-untyped-def]
    return next(i for i, c in enumerate(t["columns"]) if c["key"] == key)


def test_presets_listed(kb) -> None:  # type: ignore[no-untyped-def]
    ps = {p["id"]: p for p in export_tables.presets(KB_ROOT, kb, "cisco")}
    assert set(ps) == {"ip-address", "bridge-domain", "bgp-peer", "interface-description", "vrf", "static-route"}
    assert all(p["available"] for p in ps.values())
    vrf_col = next(c for c in ps["ip-address"]["columns"] if c["field"] == "vrf")
    assert vrf_col["label"] == {"zh-CN": "VRF", "en": "VRF", "pt-BR": "VRF"}
    assert ps["vrf"]["title"]["zh-CN"] == "VRF 表"
    assert {f["id"] for f in ps["ip-address"]["filters"]} >= {"has-ip", "no-loopback", "in-vrf"}


def test_ip_table_cells_trace_and_defaults(kb, devices) -> None:  # type: ignore[no-untyped-def]
    t = build(kb, devices, preset="ip")
    assert t["preset"] == "ip-address" and t["object"] == "interface"
    rows = {(r["device"], r["key"]): r for r in t["rows"]}
    r = rows[("ATN-CHANGE-01", "GigabitEthernet0/2/1.101")]
    cells = {c["key"]: cell for c, cell in zip(t["columns"], r["cells"], strict=True)}
    assert cells["ipv4.address"]["value"] == "172.16.1.1" and cells["ipv4.address"]["lines"] == [37]
    assert cells["ipv4.address"]["nodes"] == ["interface[GigabitEthernet0/2/1.101]/ipv4[172.16.1.1]/address"]
    assert cells["derive:mask"] == {
        "value": "255.255.255.0",
        "origin": "derived",
        "nodes": cells["derive:mask"]["nodes"],
        "lines": [37],
    }
    assert cells["vrf"]["value"] == "RAN" and cells["shutdown"]["origin"] == "default"
    assert r["node"] == "interface[GigabitEthernet0/2/1.101]" and 34 in r["lines"]
    # where has-ip：没有地址的接口不出现
    assert ("ATN-CHANGE-01", "GigabitEthernet0/2/1") not in rows
    assert t["summary"]["default_cells"] > 0 and t["summary"]["devices"] == 6
    # 不填默认值
    t2 = build(kb, devices, preset="ip", defaults=False)
    assert t2["summary"]["default_cells"] == 0


def test_bgp_secret_and_derives(kb, devices) -> None:  # type: ignore[no-untyped-def]
    t = build(kb, devices, preset="bgp")
    pw = col(t, "derive:peer_password")
    assert t["columns"][pw]["secret"] and t["summary"]["secret_columns"] == 1
    rr = [r for r in t["rows"] if r["device"] == "TOPO-RR-01" and r["key"] == "10.255.1.21"][0]
    assert rr["cells"][pw] == {
        "value": True,
        "origin": "explicit",
        "nodes": rr["cells"][pw]["nodes"],
        "lines": [47],
        "secret": True,
    }
    assert rr["cells"][col(t, "derive:peer_type")]["value"] == "iBGP"
    name, data = export_tables.to_csv(t, "zh-CN")
    text = data.decode("utf-8")
    assert "LMESH-SECRET-EXAMPLE" not in text and "已配置" in text and "未配置" in text


def test_bgp_peer_inherits_from_group_and_groups_are_not_rows(kb) -> None:  # type: ignore[no-untyped-def]
    """REQ-055-13、28：对等体的连接接口与认证密码从对等体组继承；组上的 description 不把组变成“对等体”行。"""
    text = (
        "bgp 65019\n group G1 internal\n peer G1 description GRP\n peer G1 connect-interface LoopBack100\n"
        " peer G1 password cipher LMESH-SECRET-EXAMPLE\n peer 10.1.1.1 as-number 65019\n peer 10.1.1.1 group G1\n#\n"
    )
    devs = topology.from_texts([{"name": "hw.cfg", "text": text}], kb)
    t = build(kb, devs, preset="bgp")
    assert [r["key"] for r in t["rows"]] == ["10.1.1.1"]
    cells = t["rows"][0]["cells"]
    src = cells[col(t, "derive:peer_update_source")]
    assert src["value"] == "LoopBack100" and src["origin"] == "derived" and src["lines"] == [4]
    pw = cells[col(t, "derive:peer_password")]
    assert pw["value"] is True and pw["secret"] and t["columns"][col(t, "derive:peer_password")]["secret"]
    assert "LMESH-SECRET-EXAMPLE" not in export_tables.to_csv(t, "en")[1].decode("utf-8")


def test_csv_bom_headers_and_source(kb, devices) -> None:  # type: ignore[no-untyped-def]
    t = build(kb, devices, preset="desc")
    for lang, first, src in (("zh-CN", "设备", "来源"), ("en", "Device", "Source"), ("pt-BR", "Dispositivo", "Origem")):
        name, data = export_tables.to_csv(t, lang)
        assert name == f"lmesh-interface-description-{lang}.csv" and data.startswith(b"\xef\xbb\xbf")
        rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
        assert rows[0][0] == first and rows[0][-3:] == [
            src,
            export_tables.TEXTS[lang]["node"],
            export_tables.TEXTS[lang]["lines"],
        ]
        assert len(rows) == t["summary"]["rows"] + 1
    rows = list(csv.reader(io.StringIO(export_tables.to_csv(t, "en")[1].decode("utf-8-sig"))))
    lo = next(r for r in rows if r[1] == "LoopBack0" and r[0] == "ATN-CHANGE-01")
    assert lo[-3].startswith("default: ") and "MTU" in lo[-3]
    with pytest.raises(export_tables.ExportError):
        export_tables.to_csv(t, "fr")


def test_xlsx_about_sheet_and_comments(kb, devices) -> None:  # type: ignore[no-untyped-def]
    from openpyxl import load_workbook

    t = build(kb, devices, preset="ip")
    name, data = export_tables.to_xlsx(t, "en")
    assert name == "lmesh-ip-address-en.xlsx"
    wb = load_workbook(io.BytesIO(data))
    assert wb.sheetnames[0] == "About" and "ATN-CHANGE-01" in wb.sheetnames
    ws = wb["ATN-CHANGE-01"]
    assert [c.value for c in ws[1]][:3] == ["Interface", "IPv4 address", "Prefix length"]
    comments = [c.comment.text for row in ws.iter_rows() for c in row if c.comment]
    assert comments and all("Profile" in x for x in comments)
    _, data1 = export_tables.to_xlsx(t, "pt-BR", "single")
    wb1 = load_workbook(io.BytesIO(data1))
    assert wb1.sheetnames == ["Sobre", "Tabela de endereços IP"] and wb1.worksheets[1].cell(1, 1).value == "Dispositivo"
    with pytest.raises(export_tables.ExportError):
        export_tables.to_xlsx(t, "en", "nope")


def test_other_presets(kb, devices) -> None:  # type: ignore[no-untyped-def]
    vrf = build(kb, devices, preset="vrf")
    ran = next(r for r in vrf["rows"] if r["device"] == "ATN-CHANGE-01" and r["key"] == "RAN")
    vals = {c["key"]: cell["value"] for c, cell in zip(vrf["columns"], ran["cells"], strict=True)}
    assert (
        vals["af.rd"] == "65000:100"
        and vals["derive:vrf_rt_import"] == "65000:100"
        and vals["derive:vrf_interfaces"] == 1
    )
    st = build(kb, devices, preset="static")
    assert st["object"] == "static.route"
    bd = build(kb, devices, preset="vlan")
    assert bd["object"] == "bridge_domain"


def test_custom_columns_filters_and_errors(kb, devices) -> None:  # type: ignore[no-untyped-def]
    t = build(
        kb,
        devices,
        obj="interface",
        columns=["name", "mtu", "derive:mask"],
        filters=[{"field": "mtu", "op": ">", "value": "1500"}],
    )
    assert [c["key"] for c in t["columns"]] == ["name", "mtu", "derive:mask"]
    assert t["rows"] and all(r["cells"][1]["value"] > 1500 for r in t["rows"])
    t2 = build(kb, devices, preset="ip", where=["has-ip", "no-loopback"], canonical_names=True)
    assert all(not str(r["cells"][0]["value"]).lower().startswith("loop") for r in t2["rows"])
    plain = build(kb, devices, obj="vrf.instance")
    assert plain["columns"][0]["key"] == "name"
    for kw, key in (
        ({"preset": "nope"}, "export.bad_preset"),
        ({"obj": "nope"}, "export.bad_object"),
        ({"obj": "interface", "columns": ["nope"]}, "export.bad_field"),
        ({"obj": "interface", "columns": ["derive:peer_type"]}, "export.bad_derive"),
        ({"preset": "ip", "where": ["nope"]}, "export.bad_filter"),
        ({}, "export.need_object"),
    ):
        with pytest.raises(export_tables.ExportError) as e:
            build(kb, devices, **kw)
        assert e.value.key == key
