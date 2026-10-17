"""脱敏：秘密不残留、行数不变、映射一致、IP 前缀保持、误伤检查、厂商识别、导入入库。"""

from __future__ import annotations

import ipaddress
from pathlib import Path

import pytest

from lmesh.core import importer, store
from lmesh.core.sanitize import Sanitizer, detect_vendor, detect_version

pytestmark = pytest.mark.unit
INPUTS = Path(__file__).resolve().parent.parent / "inputs" / "configs"
HW = (INPUTS / "huawei" / "basic.cfg").read_text(encoding="utf-8")
CS = (INPUTS / "cisco" / "basic.cfg").read_text(encoding="utf-8")
KEY = b"k" * 32


def test_detect_vendor_and_version() -> None:
    assert detect_vendor(HW) == "huawei" and detect_version(HW, "huawei") == "V800R023C00SPC500"
    assert detect_vendor(CS) == "cisco" and detect_version(CS, "cisco") == "15.5"
    assert detect_vendor("just notes\n") is None


@pytest.mark.parametrize("text", [HW, CS], ids=["huawei", "cisco"])
@pytest.mark.parametrize("level", ["basic", "strict"])
def test_line_count_kept(text: str, level: str) -> None:
    out = Sanitizer(level, KEY).sanitize(text).text  # type: ignore[arg-type]
    assert out.count("\n") == text.count("\n")


@pytest.mark.parametrize("secret", ["FakeCipherValue", "AnotherFake", "$1a$FakeHash$", "3082010A"])
def test_huawei_secrets_removed(secret: str) -> None:
    assert secret not in Sanitizer("basic", KEY).sanitize(HW).text


@pytest.mark.parametrize(
    "secret", ["$1$fake$abcdefghijklmnop", "$9$fakefakefake", "0822455D0A16", "s3cr3tRO", "plainVtyPass"]
)
def test_cisco_secrets_removed(secret: str) -> None:
    assert secret not in Sanitizer("basic", KEY).sanitize(CS).text


def test_no_false_positives() -> None:
    out = Sanitizer("strict", KEY).sanitize(HW).text
    for keep in (
        "ssh server cipher aes256_gcm aes128_gcm",
        "snmp-agent community complexity-check disable",
        "user-password password-force-change disable",
        "255.255.255.252",
        "0.0.0.0 0.0.0.0",
        "65000:100",
    ):
        assert keep in out, keep


def test_basic_keeps_private_strict_replaces_all() -> None:
    basic = Sanitizer("basic", KEY).sanitize(HW).text
    assert "10.20.30.1" in basic and "203.0.113.9" not in basic
    assert "PE-SÃO-PAULO-01" in basic  # basic 不动主机名
    strict = Sanitizer("strict", KEY).sanitize(HW).text
    for gone in ("10.20.30.1", "PE-SÃO-PAULO-01", "São João", "operador.teste", "1a2b3c"):
        assert gone not in strict, gone


def test_consistent_mapping_across_files() -> None:
    s = Sanitizer("strict", KEY)
    a = s.sanitize(HW).text
    b = s.sanitize(HW.replace("sysname PE-SÃO-PAULO-01", "sysname PE-RIO-02")).text
    # 同一原值在两份配置中替换成同一个值
    assert s.anon_ip("203.0.113.10") in a and s.anon_ip("203.0.113.10") in b
    assert a.count(s.anon_ip("10.20.30.1")) == 2  # router-id 与 Loopback 地址保持一致


def test_prefix_preserving() -> None:
    s = Sanitizer("strict", KEY)
    x, y, z = (ipaddress.IPv4Address(s.anon_ip(i)) for i in ("203.0.113.9", "203.0.113.10", "198.51.100.1"))
    assert ipaddress.ip_network(f"{x}/24", strict=False) == ipaddress.ip_network(f"{y}/24", strict=False)
    assert ipaddress.ip_network(f"{x}/24", strict=False) != ipaddress.ip_network(f"{z}/24", strict=False)
    assert ipaddress.IPv4Address(s.anon_ip("10.20.30.1")) in ipaddress.ip_network("10.0.0.0/8")


def test_public_report_has_no_originals() -> None:
    r = Sanitizer("basic", KEY).sanitize(HW)
    assert r.summary()["secret"] >= 3
    assert "FakeCipherValue" not in str(r.public_report())


def test_decode_variants() -> None:
    assert importer.decode("ação\r\nlinha".encode("gb18030")) == "ação\nlinha"
    assert importer.decode(b"\xef\xbb\xbfsysname X\r\n") == "sysname X\n"


def test_import_sources(db_url: str) -> None:
    store.upgrade(db_url)
    srcs = [("hw.cfg", HW.encode()), ("cs.cfg", CS.encode()), ("bad.txt", b"notes")]
    res = importer.import_sources(srcs, db_url, "strict")
    assert [r.ok for r in res] == [True, True, False]
    assert res[0].vendor == "huawei" and res[0].profile == "huawei-atn-v800r023"
    assert res[2].error == "import.unknown_vendor"
    devices = importer.list_devices(db_url)
    assert len(devices) == 2 and all(d["name"].startswith("DEVICE-") for d in devices)
    # 再导入一次：同名设备追加版本
    importer.import_sources([("hw.cfg", HW.encode())], db_url, "strict")  # 新的一批：同一设备得到同一个名称
    assert any(d["versions"] == 2 for d in importer.list_devices(db_url))


def test_redact_custom_terms_and_inline_description() -> None:
    text = (
        HW
        + "\nospf 1\n area 0.0.0.0\n  network 10.9.8.7 0.0.0.0 description TO_SITEX01-RMP01-1/1/1\ntraffic policy ACME_NNI\n"
    )
    out = Sanitizer("strict", KEY, redact=["ACME", r"<站点编码规则>"]).sanitize(text).text
    assert "ACME" not in out and "SITEX01" not in out
    assert "traffic policy ORG-" in out and "description DESC-" in out


def test_engine_id_and_forbidden_word() -> None:
    text = "sysname X\n#\nsnmp-agent local-engineid 800007DB0350AABBCC\nuser-password\n forbidden word changeme_123\n#\nreturn"
    out = Sanitizer("strict", KEY).sanitize(text).text
    assert "800007DB0350AABBCC" not in out and "changeme_123" not in out
