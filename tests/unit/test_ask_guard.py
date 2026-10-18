"""图查询语言、配置护栏、AI 自然语言查询与生成（M5-5）。AI 一律用假的客户端（不调用外部服务）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lmesh.core import ai, analysis, ask, config, gquery, guard, store, topology

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
BASE = (KB_ROOT / "samples" / "change" / "atn-base.cfg").read_text(encoding="utf-8")
RR = (KB_ROOT / "samples" / "topology" / "rr-01.cfg").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


@pytest.fixture(scope="module")
def devices(kb):  # type: ignore[no-untyped-def]
    return topology.from_texts([{"name": "a.cfg", "text": BASE}, {"name": "rr.cfg", "text": RR}], kb)


# ---------------------------------------------------------------- 查询语言


def test_parse_and_text_roundtrip() -> None:
    q = gquery.parse(
        'find interface on ATN-CHANGE-01 where vrf = "RAN" and mtu >= 1500 and name !~ ^loop and description exists '
        "return name, ipv4.address with defaults limit 10"
    )
    assert q.find == "interface" and q.on == ["ATN-CHANGE-01"] and q.with_defaults and q.limit == 10
    assert [c.op for c in q.where] == ["=", ">=", "!~", "exists"]
    assert gquery.parse(q.text()).as_dict() == q.as_dict()
    q2 = gquery.parse("FIND bgp.peer ON * WHERE remote_as IN (64512, 65000) AND group NOT EXISTS")
    assert q2.on == [] and q2.where[0].value == ["64512", "65000"] and q2.where[1].op == "not_exists"
    assert (
        gquery.from_dict({"find": "interface", "on": "*", "where": [{"field": "mtu", "op": "=", "value": 9000}]}).on
        == []
    )


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("", "query.empty"),
        ("SELECT * FROM x", "query.syntax"),
        ("FIND interface WHERE mtu", "query.syntax"),
        ("FIND interface LIMIT abc", "query.bad_limit"),
    ],
)
def test_parse_errors(text: str, key: str) -> None:
    with pytest.raises(gquery.QueryError) as e:
        gquery.parse(text)
    assert e.value.key == key


def test_execute(kb, devices) -> None:  # type: ignore[no-untyped-def]
    r = gquery.execute("FIND interface WHERE vrf EXISTS RETURN name, vrf, ipv4.address, mtu", devices, kb)
    assert r["count"] == 1 and r["rows"][0]["device"] == "ATN-CHANGE-01"
    row = r["rows"][0]
    assert row["n"] == 1 and row["node"] == "interface[GigabitEthernet0/2/1.101]" and 34 in row["lines"]
    assert row["cells"]["vrf"] == {
        "value": "RAN",
        "origin": "explicit",
        "nodes": ["interface[GigabitEthernet0/2/1.101]/vrf"],
        "lines": [36],
    }
    assert row["cells"]["mtu"]["origin"] == "none"  # 没有 WITH DEFAULTS：默认值不填
    r2 = gquery.execute("FIND interface WHERE vrf EXISTS RETURN mtu WITH DEFAULTS", devices, kb)
    assert r2["rows"][0]["cells"]["mtu"] == {
        "value": 1500,
        "origin": "default",
        "nodes": r2["rows"][0]["cells"]["mtu"]["nodes"],
        "lines": [],
    }
    # WHERE 按有效值（含默认值）比较；接口名写法不同也能匹配
    assert gquery.execute("FIND interface ON ATN-CHANGE-01 WHERE mtu = 1500", devices, kb)["count"] == 4
    assert gquery.execute("FIND interface WHERE name = GE0/2/0", devices, kb)["count"] == 1
    # 敏感字段：只给出已配置
    pw = gquery.execute("FIND bgp.peer WHERE password EXISTS RETURN address, password", devices, kb)
    assert pw["rows"][0]["cells"]["password"]["value"] is True and pw["rows"][0]["cells"]["password"]["secret"]
    assert "LMESH-SECRET" not in json.dumps(pw)
    lim = gquery.execute("FIND interface LIMIT 2", devices, kb)
    assert len(lim["rows"]) == 2 and lim["truncated"] and lim["count"] > 2


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("FIND nope", "query.bad_object"),
        ("FIND interface RETURN nope", "query.bad_field"),
        ("FIND interface ON NOPE", "query.bad_device"),
        ("FIND interface WHERE name ~ '['", "query.bad_regex"),
        ("FIND interface LIMIT 5000", "query.bad_limit"),
    ],
)
def test_execute_errors(kb, devices, text: str, key: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(gquery.QueryError) as e:
        gquery.execute(text, devices, kb)
    assert e.value.key == key


# ---------------------------------------------------------------- 护栏

BAD = """system-view
ip vpn-instance RAN-5G
 ipv4-family
  route-distinguisher 65000:100
  vpn-target 65000:105 both-direction
#
interface GigabitEthernet0/2/2.105
 vlan-type dot1q 105
 ip address 10.3.0.1 255.255.255.252
 ip binding vpn-instance RAN-5G
#
interface GigabitEthernet0/2/1.102
 vlan-type dot1q 101
#
bgp 65000
 ipv4-family vpn-instance RAN-5G
  import-route direct route-policy RP-NOPE
commit
"""
GOOD = """interface GigabitEthernet0/2/2.105
 vlan-type dot1q 105
 description RAN-SITE-105
 ip binding vpn-instance RAN
 ip address 10.3.5.1 255.255.255.252
#
"""


def test_guard_blocks(kb) -> None:  # type: ignore[no-untyped-def]
    r = guard.guard(BAD, kb, base_text=BASE, device="ATN", lang="en")
    assert r["verdict"] == "blocked" and "script" not in r
    rules = {(i["rule"], i["line"]) for i in r["issues"]}
    assert ("unknown_line", 5) in rules  # 命令卡没有 both-direction
    assert ("rd_duplicate", 4) in rules  # RD 与 VPN 实例 RAN 重复
    assert ("side_effect_order", 10) in rules  # 先配地址再绑定 VPN：地址会被删除
    assert ("vlan_duplicate", 13) in rules  # 同一主接口下 dot1q 101 重复
    assert ("dangling_ref", 17) in rules  # 引用了不存在的路由策略
    st = r["stages"]
    assert st["parse"]["status"] == "bad" and st["template"]["status"] == "skipped" and st["conflict"]["bad"] == 2
    by_no = {ln["no"]: ln for ln in r["lines"]}
    assert by_no[1]["status"] == "skip" and by_no[18]["status"] == "skip"
    assert by_no[2]["status"] == "ok" and by_no[2]["nodes"] == ["vrf.instance[RAN-5G]"]
    assert by_no[5]["status"] == "bad" and by_no[5]["nodes"] == []
    unknown = next(i for i in r["issues"] if i["rule"] == "unknown_line")
    assert unknown["message"]["key"] == "guard.unknown_line" and "both-direction" in unknown["text"]


def test_guard_passes_with_script(kb) -> None:  # type: ignore[no-untyped-def]
    r = guard.guard(GOOD, kb, base_text=BASE, device="ATN")
    assert r["verdict"] == "passed" and r["summary"]["bad"] == 0
    assert [i["rule"] for i in r["issues"]] == ["side_effect_ok"]
    assert r["script"]["available"] and r["script"]["verify_ok"]
    assert r["script"]["script_plain"].startswith("system-view\ninterface GigabitEthernet0/2/2.105\n")


def test_guard_cross_device_ip(kb, devices) -> None:  # type: ignore[no-untyped-def]
    other = [d for d in devices if d.name != "ATN-CHANGE-01"]
    addr = "10.255.1.21"  # rr-01 上已有的对等体地址不算；用 RR 的 Loopback0
    rr_lo = next(
        d.g.nodes[n]["key"]
        for d in other
        for n, data in d.g.nodes(data=True)
        if data.get("schema") == "interface.ipv4" and "Loopback0" in n
    )
    text = f"interface LoopBack9\n ip address {rr_lo} 255.255.255.255\n#\n"
    r = guard.guard(text, kb, base_text=BASE, device="ATN", others=other)
    assert r["verdict"] == "blocked" and r["issues"][0]["rule"] == "ip_duplicate" and addr
    with pytest.raises(guard.GuardError):
        guard.guard("system-view\ncommit\n", kb, base_text=BASE)
    # 没有当前配置也没有 Profile：识别不了
    with pytest.raises(guard.GuardError):
        guard.guard("interface X\n", kb)


# ---------------------------------------------------------------- AI（假的客户端）


class FakeAI:
    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.prompts: list[tuple[str, str]] = []

    def __call__(self, settings, model, system, prompt):  # type: ignore[no-untyped-def]
        self.prompts.append((system, prompt))
        return ai.Reply(self.replies.pop(0), model, 100, 20)


@pytest.fixture
def ai_on(configured_root: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LMESH_AI__PROVIDER", "openai")
    monkeypatch.setenv("LMESH_AI__BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("LMESH_AI__MODEL", "fake-model")
    s = config.load()
    store.upgrade(s.database_url)

    def install(replies: list[str]) -> FakeAI:
        fake = FakeAI(replies)
        monkeypatch.setattr(ai, "provider_hook", fake)
        return fake

    return s, install


def test_not_configured(configured_root: Path, kb, devices) -> None:  # type: ignore[no-untyped-def]
    s = config.load()
    assert ask.status(s) == {**ask.status(s), "configured": False, "status": "not_configured"}
    with pytest.raises(ask.AskError) as e:
        ask.ask("哪些接口？", devices, kb, s)
    assert e.value.key == "ai.not_configured" and e.value.kind == "state" and e.value.data["status"] == "not_configured"
    with pytest.raises(ask.AskError):
        ask.generate("加一个接口", kb, s, BASE, "ATN", None)


def test_ask_verified_corrected_unverifiable(ai_on, kb, devices) -> None:  # type: ignore[no-untyped-def]
    s, install = ai_on
    answer = {
        "statements": [
            {"text": "共有 1 个接口绑定了 VPN 实例。", "cites": [], "facts": [], "count": 1},
            {
                "text": "它是 GE0/2/1.101，地址 172.16.1.1。",
                "cites": [1],
                "facts": [
                    {"row": 1, "field": "name", "value": "GE0/2/1.101"},
                    {"row": 1, "field": "ipv4.address", "value": "172.16.1.1"},
                ],
            },
            {"text": "它的 MTU 是 9000。", "cites": [1], "facts": [{"row": 1, "field": "mtu", "value": "9000"}]},
            {"text": "建议以后统一规划。", "cites": [], "facts": []},
        ]
    }
    fake = install(
        [
            '```json\n{"query": "FIND interface WHERE vrf EXISTS RETURN name, ipv4.address, mtu WITH DEFAULTS"}\n```',
            json.dumps(answer, ensure_ascii=False),
        ]
    )
    r = ask.ask("哪些接口绑定了 VPN 实例？公网地址 203.0.113.9 呢？", devices, kb, s, "zh-CN")
    assert r["status"] == "answered" and r["result"]["count"] == 1
    sts = r["answer"]["statements"]
    assert [x["status"] for x in sts] == ["passed", "passed", "corrected", "unverifiable"]
    assert r["answer"]["summary"] == {"passed": 2, "corrected": 1, "unverifiable": 1}
    assert "实际是 1500" in sts[2]["corrected_text"] and sts[2]["facts"][0]["actual"] == 1500
    assert sts[1]["nodes"] == ["interface[GigabitEthernet0/2/1.101]"]
    assert r["ai"]["calls"] == 2 and r["ai"]["tokens_in"] == 200 and r["ai"]["model"] == "fake-model"
    # 发给 AI 的内容已脱敏：公网地址被替换，sent 中可查看
    assert "203.0.113.9" not in r["question_sent"] and "203.0.113.9" not in fake.prompts[0][1]
    assert r["sent"][0]["prompt"] == fake.prompts[0][1] and "Schema" in r["sent"][0]["prompt"]


def test_ask_retries_bad_query(ai_on, kb, devices) -> None:  # type: ignore[no-untyped-def]
    s, install = ai_on
    install(['{"query": "FIND nope"}', "not json", '{"query": "FIND interface"}'])
    r = ask.ask("x", devices, kb, s, attempts=2)
    assert r["status"] == "query_invalid" and r["answer"] is None
    assert [a["error"]["key"] for a in r["attempts"]] == ["query.bad_object", "ask.bad_reply"]
    fake = install(
        [
            '{"query": "FIND interface WHERE nope = 1"}',
            '{"query": "FIND interface ON ATN-CHANGE-01"}',
            '{"statements": []}',
        ]
    )
    r2 = ask.ask("x", devices, kb, s)
    assert r2["status"] == "answered" and len(r2["attempts"]) == 2
    assert "rejected by the validator" in fake.prompts[1][1]


def test_generate_with_guard_rounds(ai_on, kb) -> None:  # type: ignore[no-untyped-def]
    s, install = ai_on
    bad = "```\ninterface GigabitEthernet0/2/2.105\n vlan-type dot1q 105\n ip binding vpn-instance RAN-5G\n#\n```"
    good = "```\n" + GOOD + "```"
    fake = install([bad, good])
    r = ask.generate("在 GE0/2/2 上新增 105 号子接口并绑定 RAN", kb, s, BASE, "ATN", None, lang="en")
    assert [x["guard"]["verdict"] for x in r["rounds"]] == ["blocked", "passed"] and r["verdict"] == "passed"
    assert r["final"]["round"] == 2 and r["final"]["guard"]["script"]["available"]
    assert "blocked by the checks" in fake.prompts[1][1] and "RAN-5G" in fake.prompts[1][1]
    assert "interface: " in fake.prompts[0][1]  # 上下文只有对象名清单
    install([bad, bad])
    r2 = ask.generate("x", kb, s, BASE, "ATN", None, rounds=2)
    assert r2["verdict"] == "blocked" and len(r2["rounds"]) == 2
