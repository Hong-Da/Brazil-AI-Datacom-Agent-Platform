"""删除设备与单个配置版本（REQ-038）：连带删除（版本、快照、节点、边、未识别行、导入记录、忽略项）、
被检查项目作基线时拒绝 / force 清空基线、最后一个版本不能单独删除、删除最新版本后“最新”指向上一个、
删除中间版本后下一个版本的变化计数重算、删除预览不删除；SQLite 与 PostgreSQL 各跑一次。"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from lmesh.core import analysis, checkproj, device_delete, graphstore, history, ignores, importer, store
from lmesh.core.store.models import (
    CheckIgnore,
    CheckProject,
    CheckScript,
    ConfigImport,
    ConfigVersion,
    Device,
    Edge,
    Node,
    UnknownLine,
)

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
BASE = (KB_ROOT / "samples" / "change" / "atn-base.cfg").read_text(encoding="utf-8")
V2 = BASE.replace("UPLINK-TO-AGG", "UPLINK-TO-AGG-01").replace(" mtu 9000", " mtu 9216")
V3 = V2.replace("ip address 10.3.0.1 255.255.255.252", "ip address 10.3.0.1 30")  # 只是掩码写法不同
OTHER = (KB_ROOT / "samples" / "change" / "asr920-base.cfg").read_text(encoding="utf-8")
ME = checkproj.Actor(None, True, "tester")


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


@pytest.fixture
def url(db_url: str) -> str:
    store.upgrade(db_url)
    return db_url


def _import(url: str, *texts: str) -> list[int]:
    out = []
    for i, t in enumerate(texts):
        res = importer.import_sources([(f"v{i}.cfg", t.encode())], url, "basic", KB_ROOT, actor="tester", keep=50)
        out.append(res[0].version_id)
    return out


def _rows(url: str, model, col, ids) -> int:  # type: ignore[no-untyped-def]
    with store.session(url) as s:
        return int(s.scalar(select(func.count()).select_from(model).where(col.in_(ids))) or 0)


def test_delete_device_cascades_and_keeps_others(url: str) -> None:
    vids = _import(url, BASE, BASE, V2)  # 第二次是重复导入：只多一条导入记录
    other = _import(url, OTHER)
    dev_id = next(d["id"] for d in importer.list_devices(url) if d["latest_version_id"] == vids[-1])
    other_dev = next(d["id"] for d in importer.list_devices(url) if d["latest_version_id"] == other[0])
    ignores.add_ignore(url, dev_id, "orphan", "interface[X]", "test")
    ignores.add_ignore(url, other_dev, "orphan", "interface[Y]", "keep")
    with store.session(url) as s:  # 测试数据：给每个版本补一条未识别行（建图时 ATN 样本没有未识别行）
        for v in sorted(set(vids)):
            s.add(UnknownLine(version_id=v, line_no=1, text="foo", view="", pattern="foo"))
    pv = device_delete.preview(url, dev_id)
    assert pv["counts"]["versions"] == 2 and pv["counts"]["imports"] == 3
    assert pv["counts"]["check_ignores"] == 1 and pv["counts"]["unknown_lines"] == 2
    assert pv["counts"]["nodes"] > 100 and pv["counts"]["edges"] > 0
    assert [v["seq"] for v in pv["versions"]] == [1, 2] and pv["versions"][1]["latest"]
    assert pv["versions"][0]["imports"] == 2 and not pv["blocked"]
    # 预览不删除
    assert device_delete.preview(url, dev_id)["counts"] == pv["counts"]

    r = device_delete.delete_device(url, dev_id, actor="tester")
    assert r["deleted"] and r["counts"] == pv["counts"] and r["baseline_cleared"] == []
    ids = sorted(set(vids))
    for model, col in (
        (ConfigVersion, ConfigVersion.id),
        (Node, Node.version_id),
        (Edge, Edge.version_id),
        (UnknownLine, UnknownLine.version_id),
        (ConfigImport, ConfigImport.version_id),
    ):
        assert _rows(url, model, col, ids) == 0, model.__tablename__
    assert _rows(url, CheckIgnore, CheckIgnore.device_id, [dev_id]) == 0
    assert _rows(url, Device, Device.id, [dev_id]) == 0
    # 另一台设备不受影响
    assert [d["id"] for d in importer.list_devices(url)] == [other_dev]
    assert _rows(url, Node, Node.version_id, other) > 0
    assert len(ignores.list_ignores(url, other_dev)) == 1
    with pytest.raises(device_delete.DeleteError) as e:
        device_delete.preview(url, dev_id)
    assert e.value.kind == "not_found"


def test_delete_device_baseline_refused_then_forced(url: str) -> None:
    _import(url, BASE, V2)
    dev_id = importer.list_devices(url)[0]["id"]
    p = checkproj.create_project(url, ME, {"name": "割接", "device_id": dev_id})
    checkproj.create_script(url, ME, p["id"], {"name": "s1", "kind": "change", "content": "interface X\n"})
    with pytest.raises(device_delete.DeleteError) as e:
        device_delete.delete_device(url, dev_id)
    assert e.value.kind == "conflict" and e.value.key == "device_delete.baseline_in_use"
    data = e.value.data
    assert data["blocked"] and data["baseline"]["scripts"] == 1
    assert data["baseline"]["projects"][0]["name"] == "割接" and data["baseline"]["projects"][0]["follows_latest"]
    assert data["baseline"]["projects"][0]["scripts"][0]["name"] == "s1"
    assert importer.list_devices(url), "拒绝时不删除任何内容"

    r = device_delete.delete_device(url, dev_id, force=True)
    assert [x["id"] for x in r["baseline_cleared"]] == [p["id"]]
    with store.session(url) as s:
        proj = s.get(CheckProject, p["id"])
        assert proj is not None and proj.device_id is None and proj.version_id is None
        assert s.scalar(select(func.count()).select_from(CheckScript)) == 1  # 脚本保留
    assert importer.list_devices(url) == []


def test_last_version_cannot_be_deleted(url: str) -> None:
    (vid,) = _import(url, BASE)
    dev_id = importer.list_devices(url)[0]["id"]
    with pytest.raises(device_delete.DeleteError) as e:
        device_delete.delete_version(url, dev_id, vid)
    assert e.value.key == "device_delete.last_version" and e.value.kind == "conflict"
    with pytest.raises(device_delete.DeleteError) as e:
        device_delete.delete_version(url, dev_id, vid + 999)
    assert e.value.kind == "not_found"


def test_delete_latest_moves_latest_back(url: str, kb) -> None:  # type: ignore[no-untyped-def]
    v1, v2 = _import(url, BASE, V2)
    dev_id = importer.list_devices(url)[0]["id"]
    p = checkproj.create_project(url, ME, {"name": "跟随最新", "device_id": dev_id})
    r = device_delete.delete_version(url, dev_id, v2, kb=kb)
    assert r["version"] == {"id": v2, "seq": 2, "latest": True} and r["latest_version_id"] == v1
    assert r["versions_left"] == 1 and r["recomputed"] is None and r["counts"]["imports"] == 1
    assert [x["id"] for x in r["baseline_moved"]] == [p["id"]] and r["baseline_cleared"] == []
    assert graphstore.latest_version(url, dev_id).id == v1  # type: ignore[union-attr]
    tl = history.timeline(url, dev_id, kb)
    assert tl["count"] == 1 and tl["snapshots"][0]["latest"]
    assert _rows(url, Node, Node.version_id, [v2]) == 0 and _rows(url, Node, Node.version_id, [v1]) > 0


def test_delete_middle_recomputes_next_summary(url: str, kb) -> None:  # type: ignore[no-untyped-def]
    v1, v2, v3 = _import(url, BASE, V2, V3)
    dev_id = importer.list_devices(url)[0]["id"]
    before = history.timeline(url, dev_id, kb)["snapshots"][2]["vs_previous"]
    assert before["modified"] == 0 and before["noneff"] == 1  # 相对 V2 只是写法不同
    r = device_delete.delete_version(url, dev_id, v2, kb=kb)
    assert r["recomputed"] == v3 and r["latest_version_id"] == v3 and not r["version"]["latest"]
    with store.session(url) as s:
        ver = s.get(ConfigVersion, v3)
        assert ver is not None and ver.change_summary["vs_previous"]["modified"] == 1  # 已按 V1 重算
    tl = history.timeline(url, dev_id, kb)
    assert [s["id"] for s in tl["snapshots"]] == [v1, v3] and [s["seq"] for s in tl["snapshots"]] == [1, 2]
    assert tl["snapshots"][1]["vs_previous"]["modified"] == 1 and tl["imports"] == 2


def test_delete_middle_without_kb_recomputes_lazily(url: str, kb) -> None:  # type: ignore[no-untyped-def]
    v1, v2, v3 = _import(url, BASE, V2, V3)
    dev_id = importer.list_devices(url)[0]["id"]
    device_delete.delete_version(url, dev_id, v2)
    with store.session(url) as s:
        assert s.get(ConfigVersion, v3).change_summary is None  # type: ignore[union-attr]
    assert history.timeline(url, dev_id, kb)["snapshots"][1]["vs_previous"]["modified"] == 1


def test_pinned_version_refused_then_forced(url: str) -> None:
    v1, v2 = _import(url, BASE, V2)
    dev_id = importer.list_devices(url)[0]["id"]
    p = checkproj.create_project(url, ME, {"name": "固定 v1", "device_id": dev_id, "version_id": v1})
    pv = device_delete.preview(url, dev_id)
    assert pv["versions"][0]["pinned_by"] == [p["id"]] and pv["versions"][1]["pinned_by"] == []
    with pytest.raises(device_delete.DeleteError) as e:
        device_delete.delete_version(url, dev_id, v1)
    assert e.value.key == "device_delete.version_pinned" and e.value.data["baseline"]["projects"][0]["id"] == p["id"]
    assert graphstore.latest_version(url, dev_id) is not None and _rows(url, ConfigVersion, ConfigVersion.id, [v1]) == 1
    r = device_delete.delete_version(url, dev_id, v1, force=True)
    assert [x["id"] for x in r["baseline_cleared"]] == [p["id"]] and r["recomputed"] == v2
    with store.session(url) as s:
        proj = s.get(CheckProject, p["id"])
        assert proj is not None and proj.device_id == dev_id and proj.version_id is None


def test_version_of_other_device_is_not_found(url: str) -> None:
    a = _import(url, BASE, V2)
    b = _import(url, OTHER)
    dev_a = next(d["id"] for d in importer.list_devices(url) if d["latest_version_id"] == a[-1])
    with pytest.raises(device_delete.DeleteError) as e:
        device_delete.delete_version(url, dev_a, b[0])
    assert e.value.kind == "not_found"
    assert _rows(url, ConfigVersion, ConfigVersion.id, b) == 1
