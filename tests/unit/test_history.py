"""版本历史（M5-2）：快照保存（重复导入不存新快照）、时间线、两个快照的差异（按对象归并、只是写法不同、原文差异）、
对象历史、标签与保留策略、知识库版本不同时按当前知识库重建、回到某个快照的变更脚本、差异报告、迁移在两种数据库上可用。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmesh.core import analysis, compare, history, importer, report_history, store

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
BASE = (KB_ROOT / "samples" / "change" / "atn-base.cfg").read_text(encoding="utf-8")
V2 = BASE.replace("UPLINK-TO-AGG", "UPLINK-TO-AGG-01").replace(" mtu 9000", " mtu 9216")
V3 = V2.replace("ip address 10.3.0.1 255.255.255.252", "ip address 10.3.0.1 30")  # 只是掩码写法不同


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


def _import(url: str, *texts: str, keep: int = 50) -> list[importer.ImportResult]:
    out = []
    for i, t in enumerate(texts):
        out += importer.import_sources([(f"v{i}.cfg", t.encode())], url, "basic", KB_ROOT, actor="tester", keep=keep)
    return out


@pytest.fixture
def url(db_url: str) -> str:
    store.upgrade(db_url)
    return db_url


def test_graph_dump_roundtrip(kb) -> None:  # type: ignore[no-untyped-def]
    """保存的图读回后与原图按有效值完全一致。"""
    side = compare.side_from_text(BASE, kb, None, "a")
    g2 = history.load_graph(history.dump_graph(side.graph))
    assert g2.number_of_nodes() == side.graph.number_of_nodes()
    assert g2.graph["profile"] == side.graph.graph["profile"] and "statements" not in g2.graph
    assert compare.compare(side, compare.Side(g2, "b"), kb)["equal"]


def test_content_hash_ignores_trailing_space() -> None:
    assert history.content_hash("a \nb\n\n") == history.content_hash("a\nb")
    assert history.content_hash("a\nb") != history.content_hash("a\nc")


def test_duplicate_import_and_timeline(url: str, kb) -> None:  # type: ignore[no-untyped-def]
    res = _import(url, BASE, BASE, V2, V3)
    assert [r.duplicate for r in res] == [False, True, False, False]
    assert res[0].version_id == res[1].version_id and res[1].coverage == res[0].coverage
    dev = importer.list_devices(url)[0]
    assert dev["versions"] == 3
    tl = history.timeline(url, dev["id"], kb)
    s1, s2, s3 = tl["snapshots"]
    assert tl["count"] == 3 and tl["imports"] == 4
    assert s1["import_count"] == 2 and s1["imports"][1]["duplicate"] and s1["imports"][0]["actor"] == "tester"
    assert s1["vs_previous"] is None and s1["nodes"] > 100 and s1["graph_stored"]
    assert s2["vs_previous"] == {"added": 0, "modified": 1, "removed": 0, "renamed": 0, "noneff": 0, "fmt": 0}
    assert s3["vs_previous"]["noneff"] == 1 and s3["vs_previous"]["modified"] == 0
    assert s3["latest"] and s3["kb_current"] and s3["fingerprint"] == history.content_hash(V3)


def test_diff_items_noneff_and_text(url: str, kb) -> None:  # type: ignore[no-untyped-def]
    _import(url, BASE, V2, V3)
    dev_id = importer.list_devices(url)[0]["id"]
    d = history.diff(url, dev_id, kb, "#1", "latest")
    assert d["summary"]["modified"] == 1 and d["summary"]["noneff"] == 1 and d["noneff"] == []
    it = d["items"][0]
    assert it["object"] == "interface[GigabitEthernet0/2/0]" and it["kind"] == "modified"
    assert {(c["field"], c["a"]["value"], c["b"]["value"]) for c in it["changes"]} == {
        ("description", "UPLINK-TO-AGG", "UPLINK-TO-AGG-01"),
        ("mtu", 9000, 9216),
    }
    assert d["summary"]["by_domain"]["interface"]["modified"] == 1
    # 只是写法不同：打开后列出（掩码 255.255.255.252 与 30）
    d2 = history.diff(url, dev_id, kb, "#2", "#3", show_noneff=True)
    assert d2["equal"] and d2["summary"]["noneff"] == 1
    assert d2["noneff"][0]["reason"] == "spelling" and d2["noneff"][0]["a"]["raw"] == "255.255.255.252"
    # 原文差异：每行带行号与所属节点
    lines = [ln for h in d["text"]["hunks"] for ln in h["lines"] if ln["op"] != "equal"]
    assert {ln["op"] for ln in lines} == {"add", "del"}
    assert any(ln["node"] == "interface[GigabitEthernet0/2/0]/mtu" and ln["op"] == "add" for ln in lines)
    # A 总是较早的一侧（给反了也一样）
    d3 = history.diff(url, dev_id, kb, "latest", "#1")
    assert d3["a"]["seq"] == 1 and d3["b"]["seq"] == 3
    with pytest.raises(history.HistoryError) as e:
        history.diff(url, dev_id, kb, "#9")
    assert e.value.kind == "not_found"
    with pytest.raises(history.HistoryError):
        history.diff(url, dev_id, kb, domain="nope")


def test_object_history_tags_and_retention(url: str, kb) -> None:  # type: ignore[no-untyped-def]
    _import(url, BASE, V2, V3)
    dev_id = importer.list_devices(url)[0]["id"]
    oh = history.object_history(url, dev_id, "interface[GigabitEthernet0/2/0]", kb)
    assert [r["changed"] for r in oh["snapshots"]] == [[], ["description", "mtu"], []]
    assert oh["snapshots"][1]["values"]["mtu"]["value"] == 9216 and oh["changes"] == 1
    with pytest.raises(history.HistoryError):
        history.object_history(url, dev_id, "interface[Nope0]", kb)
    first = history.resolve_snapshot(url, dev_id, "#1")
    assert history.set_tag(url, dev_id, first, "割接前基线")["tag"] == "割接前基线"
    assert history.resolve_snapshot(url, dev_id, "tag:割接前基线") == first
    with pytest.raises(history.HistoryError):
        history.set_tag(url, dev_id, first, "x" * 300)
    # 只保留 1 个：贴了标签的 #1 与最新的保留，#2 被删除
    removed = history.apply_retention(url, dev_id, 1)
    assert len(removed) == 1
    tl = history.timeline(url, dev_id, kb)
    assert [s["tag"] for s in tl["snapshots"]] == ["割接前基线", None]
    assert history.apply_retention(url, dev_id, 0) == []
    history.set_tag(url, dev_id, first, None)
    assert history.timeline(url, dev_id, kb)["tagged"] == 0


def test_retention_on_import(url: str, kb) -> None:  # type: ignore[no-untyped-def]
    texts = [BASE.replace(" mtu 9000", f" mtu {9000 + i}") for i in range(4)]
    _import(url, *texts, keep=2)
    dev_id = importer.list_devices(url)[0]["id"]
    tl = history.timeline(url, dev_id, kb)
    assert tl["count"] == 2 and tl["snapshots"][-1]["fingerprint"] == history.content_hash(texts[-1])


def test_rebuild_with_current_kb(url: str, kb) -> None:  # type: ignore[no-untyped-def]
    """快照保存时的知识库版本不同：提示，并可按当前知识库重建后比较。"""
    from lmesh.core.store.models import ConfigVersion

    _import(url, BASE, V2)
    dev_id = importer.list_devices(url)[0]["id"]
    with store.session(url) as s:
        v = s.get(ConfigVersion, history.resolve_snapshot(url, dev_id, "#1"))
        assert v is not None
        v.kb_version, v.graph_gz = "0.0.1", None  # 旧数据：没有保存图
    d = history.diff(url, dev_id, kb, "#1", "#2")
    assert d["kb"]["differs"] and d["a"]["graph"] == "rebuilt" and d["b"]["graph"] == "stored"
    d2 = history.diff(url, dev_id, kb, "#1", "#2", rebuild=True)
    assert d2["kb"]["rebuilt"] and d2["b"]["graph"] == "rebuilt" and d2["summary"]["modified"] == 1


def test_restore_script_and_report(url: str, kb) -> None:  # type: ignore[no-untyped-def]
    _import(url, BASE, V2)
    dev_id = importer.list_devices(url)[0]["id"]
    r = history.restore(url, dev_id, kb, "#1")
    assert r["from"]["seq"] == 2 and r["to"]["seq"] == 1
    ch = r["change"]
    assert ch["script_plain"] == (
        "system-view\ninterface GigabitEthernet0/2/0\n description UPLINK-TO-AGG\n mtu 9000\nquit\ncommit\nreturn\n"
    )
    assert ch["verify"]["ok"] and ch["rollback"]["verify"]["ok"]
    d = history.diff(url, dev_id, kb)
    for lang, fmt in (("zh-CN", "md"), ("en", "html")):
        rep = report_history.history_report(d, lang, fmt)
        assert rep.filename == f"history-ATN-CHANGE-01-1-2.{lang}.{fmt}"
        assert "interface[GigabitEthernet0/2/0]" in rep.content and "mtu 9216" in rep.content


def test_device_loaders(url: str, kb) -> None:  # type: ignore[no-untyped-def]
    _import(url, BASE)
    devs, missing = history.devices_from_db(url, kb, ["ATN-CHANGE-01", "nope"])
    assert [d.name for d in devs] == ["ATN-CHANGE-01"] and missing == ["nope"]
    assert devs[0].g.number_of_nodes() > 100
    hit = history.latest_text(url, "ATN-CHANGE-01")
    assert hit is not None and hit[1] == "ATN-CHANGE-01" and hit[3] == BASE
    assert history.latest_text(url, "nope") is None
    assert "config_imports" in store.table_names(url)
