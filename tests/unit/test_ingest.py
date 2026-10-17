"""文档导入：格式行转换、规则抽取、HTML 转换、合并进知识库、审核写回、批量审核、AI 通道与调用记录、后台任务。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmesh.core import ai, config, kbservice, review, store, tasks
from lmesh.core import kb as kbmod
from lmesh.core.ingest import convert
from lmesh.core.ingest.extractor import extract, load_rules
from lmesh.core.ingest.markdown import format_to_syntax, params_in_cell
from lmesh.core.ingest.service import approve_matching, ingest
from lmesh.core.kb import files as kbfiles
from lmesh.core.kb.validate import validate

pytestmark = pytest.mark.unit
DOCS = Path(__file__).resolve().parent.parent / "inputs" / "docs"
REAL_RULES = Path(__file__).resolve().parent.parent.parent / "knowledge" / "extractors"


@pytest.mark.parametrize(
    ("md", "syntax"),
    [
        (
            "**peer** *ipv4-address* **timer** **keepalive** *keepalive-time*",
            "peer <ipv4-address> timer keepalive <keepalive-time>",
        ),
        (
            "**neighbor** {*ip-address* | *ipv6-address***%** | *peer-group-name*}**remote-as** *asn*",
            "neighbor { <ip-address> | <ipv6-address> % | <peer-group-name> } remote-as <asn>",
        ),
        ("**interface** *interface-type interface-number*", "interface <interface-type> <interface-number>"),
        (
            "**vpn-target** { *vpn-target* } &<1-8> [ *vrfRtType* ]",
            "vpn-target { <vpn-target> } &<1-8> [ <vrfRtType> ]",
        ),
    ],
)
def test_format_to_syntax(md: str, syntax: str) -> None:
    assert format_to_syntax(md) == syntax


def test_params_in_cell() -> None:
    assert params_in_cell("**keepalive** *keepalive-time*") == ["keepalive-time"]
    assert params_in_cell("*interface-type interface-number*") == ["interface-type", "interface-number"]


@pytest.mark.parametrize("name", ["huawei-vrp8-md", "cisco-iosxe-md"])
def test_real_rules_load(name: str) -> None:
    r = load_rules(REAL_RULES / f"{name}.yaml")
    assert r.family and r.raw["views_map"] and r.raw["domains"]


def _huawei():  # type: ignore[no-untyped-def]
    return extract(DOCS / "huawei", load_rules(DOCS / "rules-huawei-test.yaml"), source_version="V800R025")


def test_extract_huawei_fixture() -> None:
    res = _huawei()
    by_syntax = {c["syntax"]: c for c in res.cards}
    assert res.skipped["excluded"] == 1  # display
    assert res.skipped["view_unmapped"] == 1  # 只在多实例视图中的命令
    vpn = by_syntax["ip vpn-instance <vpn-instance-name>"]
    assert vpn["view"] == "system" and vpn["enters_view"] == "vpn-instance"
    assert vpn["undo"] == "undo ip vpn-instance <vpn-instance-name>"
    assert vpn["default"] == "By default, no VPN instance is configured."
    assert vpn["source"]["version"] == "V800R025" and vpn["source"]["line"] > 0
    rt = [c for c in res.cards if c["syntax"].startswith("vpn-target")]
    assert {c["view"] for c in rt} == {"vpn-instance", "vpn-instance-af-ipv4"}  # 多个视图各一张卡
    assert rt[0]["params"]["vrfRtType"] == {
        "type": "enum",
        "choices": ["both", "export-extcommunity", "import-extcommunity"],
    }
    timer = next(c for c in res.cards if c["syntax"].startswith("peer <ipv4-address> timer keepalive"))
    assert timer["view"] == "bgp"
    assert timer["params"]["keepalive-time"] == {"type": "integer", "range": [0, 21845]}
    assert timer["params"]["ipv4-address"] == {"type": "ipv4"}
    assert len({c["id"] for c in res.cards}) == len(res.cards)


def test_extract_cisco_fixture() -> None:
    res = extract(DOCS / "cisco", load_rules(DOCS / "rules-cisco-test.yaml"))
    assert len(res.cards) == 1
    c = res.cards[0]
    assert c["view"] == "router-bgp" and c["undo"].startswith("no neighbor")
    assert c["params"]["autonomous-system-number"] == {"type": "asn"}
    assert c["default"] == "There are no BGP neighbor peers."


def test_html_conversion_extracts_same(tmp_path: Path) -> None:
    md = convert.html_to_md((DOCS / "html" / "chapter.html").read_text(encoding="utf-8"))
    assert "**ip vpn-instance** *vpn-instance-name*" in md and "| *vpn-instance-name* |" in md
    work = convert.prepare(DOCS / "html", tmp_path / "work")
    rules = load_rules(DOCS / "rules-huawei-test.yaml")
    rules.raw["domains"] = {"vrf": [{"path": "*.md"}]}
    res = extract(work, rules)
    assert [c["syntax"] for c in res.cards] == ["ip vpn-instance <vpn-instance-name>"]


@pytest.fixture
def kb_root(configured_root: Path) -> Path:
    return kbservice.runtime_root(config.load())


def test_ingest_merge_and_review(kb_root: Path) -> None:
    s = config.load()
    rules = str(DOCS / "rules-huawei-test.yaml")
    r1 = ingest(DOCS / "huawei", rules, kb_root, s.database_url, s)
    n = r1["merge"]["new"]
    assert n == len(r1 and _huawei().cards) and r1["review_items"] == n and r1["commit"]
    assert not [i for i in validate(kbmod.load(kb_root)) if i.level == "error"]
    # 再导入一次：没有变化
    r2 = ingest(DOCS / "huawei", rules, kb_root, s.database_url, s)
    assert r2["merge"] == {"unchanged": n} and r2["review_items"] == 0 and r2["commit"] is None
    # 审核通过一张：状态写回 reviewed，并可在审核时修改字段
    items = review.list_items(s.database_url, kind="card")["items"]
    first = next(i for i in items if "ip-vpn-instance" in i["target"])
    review.decide(s.database_url, kb_root, first["id"], True, edited={"note": "已核对文档"})
    card = kbmod.load(kb_root).cards[first["target"]]
    assert card.status == "reviewed" and card.note == "已核对文档"
    # 已审核的卡在文档中变化：不改文件，产生“更新”审核记录
    path, doc, idx = kbfiles.find_card(kb_root, first["target"])  # type: ignore[misc]
    doc["cards"][idx]["default"] = "人工改过的缺省值"
    kbfiles.dump_rt(path, doc)
    r3 = ingest(DOCS / "huawei", rules, kb_root, s.database_url, s)
    assert r3["merge"]["changed_reviewed"] == 1 and r3["review_items"] == 1
    assert kbmod.load(kb_root).cards[first["target"]].default == "人工改过的缺省值"


def test_review_edit_with_bad_syntax_rejected(kb_root: Path) -> None:
    s = config.load()
    ingest(DOCS / "huawei", str(DOCS / "rules-huawei-test.yaml"), kb_root, s.database_url, s)
    item = review.list_items(s.database_url, kind="card")["items"][0]
    from lmesh.core.kb.syntax import SyntaxErrorKB

    with pytest.raises(SyntaxErrorKB):
        review.decide(s.database_url, kb_root, item["id"], True, edited={"syntax": "peer [ <a>"})


def test_batch_approve(kb_root: Path) -> None:
    s = config.load()
    ingest(DOCS / "huawei", str(DOCS / "rules-huawei-test.yaml"), kb_root, s.database_url, s)
    res = approve_matching(s.database_url, kb_root, "card", title_contains="vpn-target")
    assert res == {"approved": 2, "failed": 0}
    statuses = {c.id: c.status for c in kbmod.load(kb_root).cards.values() if c.syntax.startswith("vpn-target")}
    assert set(statuses.values()) == {"reviewed"}


def _fake_ai(monkeypatch: pytest.MonkeyPatch, text: str | Exception) -> None:
    def hook(settings, model, system, prompt):  # type: ignore[no-untyped-def]
        if isinstance(text, Exception):
            raise text
        return ai.Reply(text, model, 11, 7)

    monkeypatch.setattr(ai, "provider_hook", hook)
    monkeypatch.setenv("LMESH_AI__PROVIDER", "openai")
    monkeypatch.setenv("LMESH_AI__BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("LMESH_AI__MODEL", "fake-model")
    monkeypatch.setenv("LMESH_AI__MODEL_EXTRACT", "fake-cheap")


def test_ai_not_configured(configured_root: Path) -> None:
    s = config.load()
    assert not ai.is_configured(s)
    with pytest.raises(ai.AIError):
        ai.complete(s, "test", "hi")


def test_ai_calls_logged(configured_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_ai(monkeypatch, "OK")
    s = config.load()
    assert ai.test(s)["reply"] == "OK"
    assert ai.model_for(s, "extract") == "fake-cheap" and ai.model_for(s, "merge") == "fake-model"
    _fake_ai(monkeypatch, ConnectionError("down"))
    with pytest.raises(ai.AIError):
        ai.complete(config.load(), "merge", "x")
    calls = ai.recent_calls(s.database_url)
    assert [c["status"] for c in calls[:2]] == ["error", "ok"] and calls[1]["tokens_in"] == 11


def test_ai_channel_fixes_syntax(kb_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    doc = tmp_path / "doc"
    doc.mkdir()
    (doc / "c.md").write_text(
        "# T\n## Basic Commands\n### bad cmd\n#### Format\n**bad** [ *a* ] ] *b*\n#### Views\nSystem view\n",
        encoding="utf-8",
    )
    _fake_ai(monkeypatch, "bad [ <a> ] <b>")
    s = config.load()
    res = ingest(doc, str(DOCS / "rules-huawei-test.yaml"), kb_root, s.database_url, s, use_ai=True)
    assert res["ai_cards"] == 1 and res["skipped"]["syntax_error"] == 1
    card = next(c for c in kbmod.load(kb_root).cards.values() if c.source.get("extracted_by") == "ai")
    assert card.syntax == "bad [ <a> ] <b>" and card.status == "draft"


def test_task_runner(configured_root: Path) -> None:
    url = config.load().database_url
    store.upgrade(url)
    ok = tasks.submit(url, "demo", lambda p: (p(50, "half"), {"answer": 42})[1], wait=True)
    assert tasks.get(url, ok)["result"] == {"answer": 42}  # type: ignore[index]
    bad = tasks.submit(url, "demo", lambda p: 1 / 0, wait=True)  # type: ignore[arg-type,return-value]
    t = tasks.get(url, bad)
    assert t["status"] == "failed" and "ZeroDivisionError" in t["message"]  # type: ignore[index]
