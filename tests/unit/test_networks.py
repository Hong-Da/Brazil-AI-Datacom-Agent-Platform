"""项目内的网络（M9，REQ-045）：迁移 0012（从 0011 的样本数据升级，默认网络与工作数据归属）、成员与版本策略、
网络之间的隔离（A 网络的数据在 B 网络看不到）、自动加入、复制与删除、建网建议的各依据、网络外的对端；
SQLite 与 PostgreSQL 各一次。拓扑样本用 knowledge/samples/topology（5 台，互相连通，OSPF + IS-IS，AS 64512）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select, text

from lmesh.core import (
    ai_suggest,
    analysis,
    checkproj,
    graphstore,
    ignores,
    importer,
    networks,
    projects,
    store,
    topology,
    users,
    workbench,
)
from lmesh.core.store.models import (
    CheckIgnore,
    CheckProject,
    Network,
    NetworkMember,
    ProjectRuleOverride,
    ViewAnnotation,
)

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
TOPO = KB_ROOT / "samples" / "topology"
FILES = ["atn-a1.cfg", "atn-a2.cfg", "agg-01.cfg", "agg-02.cfg", "rr-01.cfg"]
PW = "Pass-word-123"


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


@pytest.fixture
def url(db_url: str) -> str:
    store.upgrade(db_url)
    return db_url


def _imp(url: str, files: list[str], texts: dict[str, str] | None = None) -> list[importer.ImportResult]:
    src = [(f, (texts or {}).get(f, (TOPO / f).read_text(encoding="utf-8")).encode()) for f in files]
    res = importer.import_sources(src, url, "basic", KB_ROOT, actor="t", keep=50)
    assert all(r.ok for r in res), [r.error for r in res]
    return res


@pytest.fixture
def lab(url: str):  # type: ignore[no-untyped-def]
    """liwei 的项目 lab，导入 5 台拓扑样本。"""
    users.create_user(url, "boss", PW, "admin")
    users.create_user(url, "liwei", PW, "user")
    liwei = projects.cli_identity(url, "liwei")
    projects.create_project(url, liwei, {"name": "Lab", "slug": "lab"})
    sc = projects.resolve(url, liwei, "lab")
    with projects.use(sc, liwei):
        res = _imp(url, FILES)
    ids = {r.device: int(r.device_id or 0) for r in res}
    return url, sc, liwei, ids


def _net(url: str, sc: projects.Scope, slug: str) -> projects.Scope:
    return projects.with_network(url, sc, slug)


# ---------------------------------------------------------------- 迁移


def test_migration_0012_from_0011_sample(db_url: str) -> None:
    from tests.unit.test_project_refs import _upgrade_to

    _upgrade_to(db_url, "0011")
    n = "2026-10-19 00:00:00"
    with store.get_engine(db_url).begin() as c:
        for sql in (
            "INSERT INTO users (id, username, role, disabled, password_hash, failed_count, password_changed_at, "
            "created_at) VALUES (1, 'boss', 'admin', false, 'x', 0, :n, :n)",
            "INSERT INTO projects (id, slug, name, description, owner_id, created_at, updated_at) VALUES "
            "(1, 'default', '默认项目', '', 1, :n, :n), (2, 'oam', 'OAM', '', 1, :n, :n)",
            "INSERT INTO devices (id, name, vendor, platform, sw_version, profile, created_at, origin, project_id) VALUES "
            "(1, 'a', 'huawei', '', '', '', :n, 'import', 1), (2, 'b', 'huawei', '', '', '', :n, 'import', 1), "
            "(3, 'pub', 'cisco', '', '', '', :n, 'import', NULL)",
            "INSERT INTO project_device_refs (project_id, device_id, version_id, created_at) VALUES (2, 3, NULL, :n)",
            "INSERT INTO check_ignores (device_id, project_id, rule, node, reason, created_at) "
            "VALUES (1, 1, 'ref.orphan', 'n', 'why', :n)",
            "INSERT INTO project_rule_overrides (project_id, rule, enabled, reason, updated_by, updated_at) "
            "VALUES (1, 'r1', false, 'why', 'boss', :n)",
            "INSERT INTO view_annotations (project_id, target_type, target, key, value, source, updated_by, updated_at) "
            "VALUES (1, 'device', '1', 'role', '\"pe\"', 'user', 'boss', :n)",
            "INSERT INTO check_projects (id, name, description, device_id, profile, default_kind, order_check, ai_check, "
            "project_id, created_at, updated_at) VALUES (1, 'g', '', 1, '', 'change', true, false, 2, :n, :n)",
        ):
            c.execute(text(sql), {"n": n})
    store._UPGRADED.discard(db_url)
    store.upgrade(db_url)
    assert {"networks", "network_members", "network_rules", "network_folders"} <= set(store.table_names(db_url))
    with store.session(db_url) as s:
        nets = {n.project_id: n for n in s.scalars(select(Network))}
        assert set(nets) == {1, 2} and all(x.is_default and x.slug == "default" for x in nets.values())
        mem = {(m.network_id, m.device_id): m.join_source for m in s.scalars(select(NetworkMember))}
        assert mem == {(nets[1].id, 1): "upgrade", (nets[1].id, 2): "upgrade", (nets[2].id, 3): "upgrade"}
        assert s.scalar(select(CheckIgnore.network_id)) == nets[1].id
        assert s.scalar(select(ProjectRuleOverride.network_id)) == nets[1].id
        assert s.scalar(select(ViewAnnotation.network_id)) == nets[1].id
        assert s.scalar(select(CheckProject.network_id)) == nets[2].id


# ---------------------------------------------------------------- 默认网络、成员与版本


def test_default_network_and_members(lab, kb) -> None:  # type: ignore[no-untyped-def]
    url, sc, liwei, ids = lab
    assert sc.network_slug == "default" and sc.network_default and not sc.network_explicit
    data = networks.list_networks(url, sc)
    assert [n["slug"] for n in data["networks"]] == ["default"]
    assert data["networks"][0]["counts"]["devices"] == 5 and data["overview"]["only_default"] == 5
    # 新网络：两台设备；网络里只看得到成员
    core = networks.create_network(
        url, sc, {"name": "核心", "slug": "core", "device_ids": [ids["TOPO-AGG-01"], ids["TOPO-RR-01"]]}
    )
    assert core["color"] == "indigo" and core["counts"]["devices"] == 2  # 第二个网络的颜色
    nc = _net(url, sc, "core")
    with projects.use(nc, liwei):
        assert sorted(d["name"] for d in importer.list_devices(url)) == ["TOPO-AGG-01", "TOPO-RR-01"]
        assert graphstore.latest_version(url, ids["TOPO-ATN-A1"]) is None  # 不是成员：按不存在处理
    # 版本：导入新版本后，固定的网络仍用旧版本，默认网络跟随最新
    with projects.use(sc, liwei):
        v1 = graphstore.latest_version(url, ids["TOPO-AGG-01"]).id  # type: ignore[union-attr]
    networks.set_policy(url, nc, "core", [ids["TOPO-AGG-01"]], "pin")
    agg = (TOPO / "agg-01.cfg").read_text(encoding="utf-8").replace("description", "description x", 1)
    with projects.use(sc, liwei):
        _imp(url, ["agg-01.cfg"], {"agg-01.cfg": agg})
        v2 = graphstore.latest_version(url, ids["TOPO-AGG-01"]).id  # type: ignore[union-attr]
    assert v2 != v1
    with projects.use(nc, liwei):
        assert graphstore.latest_version(url, ids["TOPO-AGG-01"]).id == v1  # type: ignore[union-attr]
        row = next(r for r in workbench.device_rows(url, kb.version) if r["id"] == ids["TOPO-AGG-01"])
        assert row["network_policy"] == "pin" and row["network_newer_available"]
    members = networks.list_members(url, sc, "core")["members"]
    m = next(x for x in members if x["device_id"] == ids["TOPO-AGG-01"])
    assert m["policy"] == "pin" and m["newer_available"] and [x["slug"] for x in m["also_in"]] == ["default"]
    # 默认网络：不能移出、不能删除；可以改名
    with pytest.raises(projects.ProjectError) as e:
        networks.remove_members(url, sc, "default", [ids["TOPO-AGG-01"]])
    assert e.value.key == "networks.default_all_devices"
    with pytest.raises(projects.ProjectError) as e:
        networks.delete_network(url, sc, "default", "默认网络")
    assert e.value.key == "networks.default_undeletable"
    assert networks.update_network(url, sc, "default", {"name": "管理网"})["name"] == "管理网"
    # 移出：记为排除，规则不再加入
    networks.remove_members(url, sc, "core", [ids["TOPO-RR-01"]])
    networks.add_rule(url, sc, "core", "name", "TOPO-RR-*")
    with projects.use(sc, liwei):
        res = _imp(url, ["rr-01.cfg"], {"rr-01.cfg": (TOPO / "rr-01.cfg").read_text(encoding="utf-8") + "\n!\n"})
    assert res[0].joined_networks == []
    assert networks.list_rules(url, sc, "core")["excluded"][0]["id"] == ids["TOPO-RR-01"]


def test_auto_join_on_import(url: str) -> None:
    users.create_user(url, "liwei", PW, "user")
    liwei = projects.cli_identity(url, "liwei")
    projects.create_project(url, liwei, {"name": "P", "slug": "pp"})
    sc = projects.resolve(url, liwei, "pp")
    networks.create_network(
        url, sc, {"name": "ATN", "slug": "atn", "rules": [{"kind": "name", "pattern": "topo-atn-*"}]}
    )
    networks.create_network(url, sc, {"name": "空", "slug": "empty"})
    with projects.use(sc, liwei):
        res = _imp(url, ["atn-a1.cfg", "agg-01.cfg"])
    joined = {r.device: [(x["slug"], x["via"]) for x in r.joined_networks] for r in res}
    assert joined == {"TOPO-ATN-A1": [("default", "default"), ("atn", "rule")], "TOPO-AGG-01": [("default", "default")]}
    # 在网络里导入：直接加入当前网络
    with projects.use(_net(url, sc, "empty"), liwei):
        res = _imp(url, ["rr-01.cfg"])
    assert [(x["slug"], x["via"]) for x in res[0].joined_networks] == [("default", "default"), ("empty", "current")]
    # 规则预览与 apply_existing
    pv = networks.preview_rule(url, sc, "empty", "name", "TOPO-A*")
    assert pv["matches"] == 2 and pv["not_in_network"] == 2
    r = networks.add_rule(url, sc, "empty", "name", "TOPO-A*", apply_existing=True)
    assert sorted(x["name"] for x in r["added"]) == ["TOPO-AGG-01", "TOPO-ATN-A1"]
    m = {x["name"]: x["join_source"] for x in networks.list_members(url, sc, "empty")["members"]}
    assert m == {"TOPO-RR-01": "import", "TOPO-ATN-A1": "rule", "TOPO-AGG-01": "rule"}
    with pytest.raises(projects.ProjectError):
        networks.add_rule(url, sc, "empty", "subnet", "not-a-net")


# ---------------------------------------------------------------- 隔离、复制与删除


def test_isolation_copy_and_delete(lab) -> None:  # type: ignore[no-untyped-def]
    url, sc, liwei, ids = lab
    atn = ids["TOPO-ATN-A1"]
    networks.create_network(url, sc, {"name": "A", "slug": "a", "device_ids": [atn, ids["TOPO-AGG-01"]]})
    networks.create_network(url, sc, {"name": "B", "slug": "b", "device_ids": [atn]})
    na, nb = _net(url, sc, "a"), _net(url, sc, "b")
    with projects.use(na, liwei):
        ignores.add_ignore(url, atn, "ref.orphan", "x", "只在 A")
        projects.set_override(url, projects.current(), "ref.orphan", False, None, "A 不看", None)  # type: ignore[arg-type]
        checkproj.create_project_script(
            url, checkproj.Actor(liwei.user_id, False, "liwei"), {"name": "s.txt", "device_id": atn}
        )
    with store.session(url) as ss:
        ss.add(
            ViewAnnotation(
                project_id=na.project_id,
                network_id=na.network_id,
                target_type="device",
                target=str(atn),
                key="role",
                value="access",
            )
        )
    with projects.use(nb, liwei):
        assert ignores.list_ignores(url) == []
        assert projects.list_overrides(url, projects.current()) == []  # type: ignore[arg-type]
        assert checkproj.list_scripts(url, checkproj.Actor(liwei.user_id, False, "liwei")) == []
        assert ai_suggest.list_annotations(url, nb.project_id, None, nb.network_id) == []
        # 不是 B 的成员的设备：作为基线也不行
        with pytest.raises(checkproj.ProjectError):
            checkproj.create_project_script(
                url, checkproj.Actor(liwei.user_id, False, "liwei"), {"name": "x", "device_id": ids["TOPO-AGG-01"]}
            )
    with projects.use(na, liwei):
        assert len(ignores.list_ignores(url)) == 1 and len(checkproj.list_scripts(url, checkproj.Actor(None))) == 1
        assert projects.list_overrides(url, na)[0]["enabled"] is False
    assert _net(url, sc, "a").overrides["ref.orphan"]["enabled"] is False  # 解析网络时载入本网络的规则调整
    # 不带网络（默认网络）也看不到 A 的
    with projects.use(sc, liwei):
        assert ignores.list_ignores(url) == []
    # 复制 A：工作数据一起复制
    cp = networks.copy_network(url, sc, "a", {"name": "A2", "slug": "a2"})
    assert cp["copied_from"]["slug"] == "a" and cp["counts"]["devices"] == 2
    assert cp["copied"]["ignores"] == 1 and cp["copied"]["scripts"] == 1 and cp["copied"]["annotations"] == 1
    with projects.use(_net(url, sc, "a2"), liwei):
        assert len(ignores.list_ignores(url)) == 1
    # 删除 A：确认名称；工作数据删除，设备不删
    pv = networks.delete_preview(url, sc, "a")
    assert pv["counts"]["ignores"] == 1 and pv["counts"]["scripts"] == 1
    with pytest.raises(projects.ProjectError):
        networks.delete_network(url, sc, "a", "wrong")
    networks.delete_network(url, sc, "a", "A")
    with store.session(url) as ss:
        assert ss.scalar(select(CheckIgnore).where(CheckIgnore.network_id == na.network_id)) is None
    with projects.use(sc, liwei):
        assert len(importer.list_devices(url)) == 5
    with pytest.raises(projects.ProjectError):
        projects.with_network(url, sc, "a")


def test_copy_project_keeps_networks(lab) -> None:  # type: ignore[no-untyped-def]
    url, sc, liwei, ids = lab
    networks.create_network(url, sc, {"name": "A", "slug": "a", "device_ids": [ids["TOPO-ATN-A1"]]})
    out = projects.copy_project(url, sc, liwei, {"name": "Lab2", "slug": "lab2"})
    sc2 = projects.resolve(url, liwei, "lab2")
    nets = {n["slug"]: n for n in networks.list_networks(url, sc2)["networks"]}
    assert set(nets) == {"default", "a"} and nets["a"]["counts"]["devices"] == 1 and out["counts"]["networks"] == 2


# ---------------------------------------------------------------- 建网建议


def test_suggestions(lab, kb) -> None:  # type: ignore[no-untyped-def]
    url, sc, liwei, ids = lab
    comp = networks.suggest(url, sc, "components", {}, kb)
    assert comp["total"] == 1 and comp["suggestions"][0]["count"] == 5
    assert comp["suggestions"][0]["same_as"]["slug"] == "default" and not comp["suggestions"][0]["adoptable"]
    igp = {g["key"]: g["count"] for g in networks.suggest(url, sc, "igp", {}, kb)["suggestions"]}
    assert any(k.startswith("isis:") for k in igp) and any(k.startswith("ospf:") for k in igp)
    isis_only = networks.suggest(url, sc, "igp", {"protocol": "isis"}, kb)["suggestions"]
    assert all(g["key"].startswith("isis:") for g in isis_only)
    bgp = networks.suggest(url, sc, "bgp", {}, kb)["suggestions"]
    assert bgp and bgp[0]["key"].startswith("as:")
    name = {g["key"]: g for g in networks.suggest(url, sc, "name", {}, None)["suggestions"]}
    assert set(name) == {"name:TOPO-AGG", "name:TOPO-ATN", "name:TOPO-RR"}
    assert name["name:TOPO-ATN"]["rule"] == {"kind": "name", "pattern": "TOPO-ATN-*"}
    sub = networks.suggest(url, sc, "subnet", {"prefix": 16}, kb)["suggestions"]
    assert sum(g["count"] for g in sub) == 5 and all(g["rule"]["kind"] == "subnet" for g in sub)
    with pytest.raises(projects.ProjectError):
        networks.suggest(url, sc, "nope", {}, kb)
    with pytest.raises(projects.ProjectError):
        networks.suggest(url, sc, "igp", {}, None)
    # 采纳：设备名依据，带自动加入规则；再预览时标出与现有网络相同
    res = networks.adopt(url, sc, "name", {}, ["name:TOPO-ATN"], None, with_rules=True)
    assert [c["network"]["slug"] for c in res["created"]] == ["topo-atn"]
    assert networks.list_rules(url, sc, "topo-atn")["rules"][0]["pattern"] == "TOPO-ATN-*"
    again = {g["key"]: g for g in networks.suggest(url, sc, "name", {}, None)["suggestions"]}
    assert again["name:TOPO-ATN"]["same_as"]["slug"] == "topo-atn"
    assert again["name:TOPO-AGG"]["overlap_existing"] == []
    res2 = networks.adopt(url, sc, "name", {}, [], None)
    assert {c["key"] for c in res2["created"]} == {"name:TOPO-AGG", "name:TOPO-RR"}
    assert {"key": "name:TOPO-ATN", "reason": "same_as_existing"} in res2["skipped"]
    m = networks.list_members(url, sc, "topo-agg")["members"]
    assert {x["join_source"] for x in m} == {"suggestion"}


def test_ai_group_suggestions_checked(lab, kb) -> None:  # type: ignore[no-untyped-def]
    url, sc, liwei, ids = lab
    with store.session(url) as s:
        for dev, grp in (("TOPO-ATN-A1", "环 A"), ("TOPO-ATN-A2", "环 A"), ("TOPO-ATN-A1", "x"), ("TOPO-RR-01", "散")):
            if grp == "x":
                continue
            s.add(
                ViewAnnotation(
                    project_id=sc.project_id,
                    network_id=sc.network_id,
                    target_type="device",
                    target=str(ids[dev]),
                    key="group",
                    value=grp,
                    source="ai",
                )
            )
        s.add(
            ViewAnnotation(
                project_id=sc.project_id,
                network_id=sc.network_id,
                target_type="device",
                target=str(ids["TOPO-ATN-A1"] + 1000),
                key="group",
                value="散",
                source="ai",
            )
        )
    res = {g["name"]: g for g in networks.suggest(url, sc, "ai", {}, kb)["suggestions"]}
    assert res["环 A"]["check"]["status"] == "pass" and res["环 A"]["count"] == 2
    assert res["散"]["check"]["status"] == "reject" and not res["散"]["adoptable"]
    assert res["散"]["check"]["reasons"][0]["code"] == "device_not_in_project"
    out = networks.adopt(url, sc, "ai", {}, [], kb)
    assert [c["key"] for c in out["created"]] == ["ai:环 A"] and out["skipped"][0]["reason"] == "check_failed"


# ---------------------------------------------------------------- 网络外的对端、管理地址


def test_outside_peers_and_mgmt(lab, kb) -> None:  # type: ignore[no-untyped-def]
    url, sc, liwei, ids = lab
    networks.create_network(
        url, sc, {"name": "接入", "slug": "acc", "device_ids": [ids["TOPO-ATN-A1"], ids["TOPO-ATN-A2"]]}
    )
    networks.create_network(url, sc, {"name": "汇聚", "slug": "agg", "device_ids": [ids["TOPO-AGG-01"]]})
    na = _net(url, sc, "acc")
    with projects.use(na, liwei):
        devs, _ = topology.from_db(url, kb, None)
        assert sorted(d.name for d in devs) == ["TOPO-ATN-A1", "TOPO-ATN-A2"]
        out = networks.outside_peers(url, na, kb, devs)
    assert out["count"] > 0
    peers = {lk["peer"]["device"]: lk["peer"]["networks"] for lk in out["links"]}
    assert "TOPO-AGG-01" in peers and [n["slug"] for n in peers["TOPO-AGG-01"]] == ["agg"]
    assert all(lk["inside"]["device"].startswith("TOPO-ATN") for lk in out["links"])
    # 默认网络没有“网络外”
    assert networks.outside_peers(url, sc, kb, devs)["count"] == 0
    mg = networks.mgmt_addresses(url, list(ids.values()), kb)
    assert all(m and m["address"] for m in mg.values())
