"""用户工作空间与项目（M6，REQ-035 / REQ-036）：迁移 0007（从 0006 的样本数据升级，归属正确）、项目内的设备可见性、
引用与固定版本、复制设备、删除项目、转交、项目级规则调整、个人令牌、第一个管理员接管默认项目；SQLite 与 PostgreSQL 各一次。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text

from lmesh.core import analysis, checkproj, checks, graphstore, ignores, importer, projects, store, tokens, users
from lmesh.core.store.models import ApiToken, CheckProject, ConfigVersion, Device, Project

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
BASE = (KB_ROOT / "samples" / "change" / "atn-base.cfg").read_text(encoding="utf-8")
V2 = BASE.replace(" mtu 9000", " mtu 9216")
PW = "Pass-word-123"


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


@pytest.fixture
def url(db_url: str) -> str:
    store.upgrade(db_url)
    return db_url


def _imp(url: str, text_: str, name: str = "a.cfg", public: bool = False) -> int:
    res = importer.import_sources([(name, text_.encode())], url, "basic", KB_ROOT, actor="t", keep=50, public=public)
    assert res[0].ok, res[0].error
    return int(res[0].version_id or 0)


def _ident(url: str, name: str) -> projects.Identity:
    return projects.cli_identity(url, name)


# ---------------------------------------------------------------- 迁移


def _upgrade_to_0006(url: str) -> None:
    from alembic import command

    cfg = store._alembic_config(url)
    with store.get_engine(url).connect() as conn:
        if url.startswith("sqlite"):
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()
        with conn.begin():
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "0006")


SAMPLE_0006 = [
    "INSERT INTO users (id, username, role, disabled, password_hash, failed_count, password_changed_at, created_at) "
    "VALUES (1, 'old', 'admin', true, 'x', 0, :n, :n), (2, 'boss', 'admin', false, 'x', 0, :n, :n), "
    "(3, 'liwei', 'user', false, 'x', 0, :n, :n)",
    "INSERT INTO devices (id, name, vendor, platform, sw_version, profile, created_at) "
    "VALUES (1, 'atn1', 'huawei', '', '', '', :n), (2, 'pe1', 'cisco', '', '', '', :n)",
    "INSERT INTO config_versions (id, device_id, source_name, raw_text, sanitized, kb_version, collected_at) "
    "VALUES (1, 1, 'a', 'sysname atn1', true, '', :n), (2, 1, 'b', 'sysname atn1\n#', true, '', :n), "
    "(3, 2, 'c', 'hostname pe1', true, '', :n)",
    "INSERT INTO nodes (version_id, node_key, schema_type, origin) VALUES (1, 'k1', 't', 'explicit'), (2, 'k2', 't', 'explicit')",
    "INSERT INTO unknown_lines (version_id, line_no, text, view, pattern) VALUES (1, 3, 'foo', '', 'foo')",
    "INSERT INTO config_imports (device_id, version_id, imported_at, source_kind, source_name, actor, duplicate) "
    "VALUES (1, 1, :n, 'file', 'a', 'x', false), (1, 2, :n, 'file', 'b', 'x', false)",
    "INSERT INTO check_ignores (device_id, rule, node, reason, created_at) VALUES (1, 'ref.orphan', 'n', 'why', :n)",
    "INSERT INTO check_projects (id, name, description, device_id, version_id, profile, default_kind, order_check, "
    "ai_check, user_id, created_at, updated_at) VALUES "
    "(1, 'OAM 开通', 'd', 1, 1, '', 'change', true, false, 3, :n, :n), "
    "(2, 'Orphan', '', 1, NULL, '', 'change', true, false, NULL, :n, :n), "
    "(3, 'OAM 开通', '', NULL, NULL, '', 'full', true, false, 3, :n, :n)",
    "INSERT INTO check_scripts (id, project_id, name, kind, content, position, created_at, updated_at) "
    "VALUES (1, 1, 's1', 'change', 'x', 1, :n, :n)",
]


def test_migration_0007_from_0006_sample(db_url: str) -> None:
    _upgrade_to_0006(db_url)
    eng = store.get_engine(db_url)
    with eng.begin() as c:
        for sql in SAMPLE_0006:
            c.execute(text(sql), {"n": "2026-10-01 00:00:00"})
        if db_url.startswith("postgresql"):  # 显式插入了编号：把序列推到最大值之后
            for t in ("users", "devices", "config_versions", "check_projects", "check_scripts"):
                c.execute(text(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), (SELECT MAX(id) FROM {t}))"))
    store._UPGRADED.discard(db_url)
    store.upgrade(db_url)
    with store.session(db_url) as s:
        ps = {p.slug: p for p in s.scalars(select(Project))}
        # 默认项目属于第一个启用的管理员（boss），旧数据都移入
        assert ps["default"].owner_id == 2 and ps["default"].migrated_from["type"] == "upgrade"
        devs = list(s.scalars(select(Device).order_by(Device.id)))
        assert [(d.name, d.project_id, d.origin) for d in devs[:2]] == [
            ("atn1", ps["default"].id, "migrated"),
            ("pe1", ps["default"].id, "migrated"),
        ]
        assert s.scalar(text("SELECT COUNT(*) FROM config_versions WHERE device_id = 1")) == 2  # 没有被级联删除
        assert s.scalar(text("SELECT project_id FROM check_ignores")) == ps["default"].id
        # 检查项目各自转为项目；同名的标识自动加序号；属主为空的归第一个管理员
        assert {k for k in ps} == {"default", "oam", "orphan", "oam-2"}
        assert ps["oam"].owner_id == 3 and ps["orphan"].owner_id == 2 and ps["oam-2"].owner_id == 3
        cps = {cp.id: cp for cp in s.scalars(select(CheckProject))}
        assert cps[1].project_id == ps["oam"].id and cps[2].project_id == ps["orphan"].id
        # 基线设备复制为该项目的私有设备：固定的基线版本对应到复制出的版本；跟随最新的仍跟随
        c1 = s.get(Device, cps[1].device_id)
        assert c1 is not None and c1.project_id == ps["oam"].id and c1.origin == "copy" and c1.name == "atn1"
        v = s.get(ConfigVersion, cps[1].version_id)
        assert v is not None and v.device_id == c1.id and v.raw_text == "sysname atn1"
        assert s.scalar(text("SELECT COUNT(*) FROM nodes WHERE version_id = :v"), {"v": v.id}) == 1
        c2 = s.get(Device, cps[2].device_id)
        assert c2 is not None and c2.project_id == ps["orphan"].id and cps[2].version_id is None
        assert s.scalar(select(ConfigVersion.raw_text).where(ConfigVersion.device_id == c2.id)) == "sysname atn1\n#"
        assert cps[3].device_id is None
        # 工作空间：每个账号一个；默认项目
        ws = dict(s.execute(text("SELECT user_id, default_project_id FROM workspaces")).all())  # type: ignore[arg-type]
        assert set(ws) == {1, 2, 3} and ws[2] == ps["default"].id and ws[3] == ps["oam"].id
    # 迁移后同名设备可以在不同项目里存在；默认项目里仍按名称作为新版本导入
    with projects.use(projects.scope_by_id(db_url, ps["oam"].id)):
        assert {d["name"] for d in importer.list_devices(db_url)} == {"atn1"}


def test_fresh_database_has_no_projects(url: str) -> None:
    with store.session(url) as s:
        assert s.scalar(select(Project)) is None


# ---------------------------------------------------------------- 项目与可见性


def test_devices_are_scoped_to_projects(url: str, kb) -> None:  # type: ignore[no-untyped-def]
    users.create_user(url, "boss", PW, "admin")
    users.create_user(url, "liwei", PW, "user")
    boss, liwei = _ident(url, "boss"), _ident(url, "liwei")
    a = projects.create_project(url, liwei, {"name": "A", "slug": "pa"})
    b = projects.create_project(url, liwei, {"name": "B", "slug": "pb"})
    sa, sb = projects.resolve(url, liwei, "pa"), projects.resolve(url, liwei, "pb")
    assert a["role"] == "owner" and sa.role == "owner"
    with projects.use(sa, liwei):
        va = _imp(url, BASE)
    with projects.use(sb, liwei):
        vb = _imp(url, BASE)  # 同名设备在另一个项目里是另一台设备
        assert len(importer.list_devices(url)) == 1
        dev_b = importer.list_devices(url)[0]["id"]
    assert va != vb
    with projects.use(sa, liwei):
        dev_a = importer.list_devices(url)[0]["id"]
        assert dev_a != dev_b
        assert graphstore.latest_version(url, dev_b) is None  # 别的项目的设备看不到
        with pytest.raises(KeyError):
            graphstore.build_for_version(url, vb, kb)
        assert graphstore.latest_version(url, dev_a).id == va  # type: ignore[union-attr]
    # 不是成员：resolve 不存在；管理员：admin 角色
    with pytest.raises(projects.ProjectError) as e:
        projects.resolve(url, projects.Identity(99, "x", "user"), "pa")
    assert e.value.kind == "not_found"
    assert projects.resolve(url, boss, "pa").role == "admin"
    assert projects.resolve(url, liwei, "liwei/pa").slug == "pa"
    assert projects.resolve(url, liwei, str(b["id"])).slug == "pb"


def test_refs_pins_copy_and_delete(url: str, kb) -> None:  # type: ignore[no-untyped-def]
    users.create_user(url, "boss", PW, "admin")
    users.create_user(url, "liwei", PW, "user")
    liwei = _ident(url, "liwei")
    v1 = _imp(url, BASE, public=True)
    pub = projects.list_public(url)[0]["id"]
    projects.create_project(url, liwei, {"name": "C", "slug": "pc"})
    sc = projects.resolve(url, liwei, "pc")
    projects.add_ref(url, sc, pub, v1)
    v2 = _imp(url, V2, public=True)
    with projects.use(sc, liwei):
        row = importer.list_devices(url)[0]
        assert row["source"] == "public" and row["latest_version_id"] == v1  # 固定版本
        assert graphstore.latest_version(url, pub).id == v1  # type: ignore[union-attr]
        # 忽略项按项目
        ignores.add_ignore(url, pub, "ref.orphan", "x", "why")
        assert len(ignores.list_ignores(url)) == 1
    projects.set_ref(url, sc, pub, None)
    with projects.use(sc, liwei):
        assert importer.list_devices(url)[0]["latest_version_id"] == v2  # 跟随最新
        copied = projects.copy_device(url, sc, pub, v1)
        assert copied["renamed"] and copied["name"].endswith("-2")
        names = sorted(d["name"] for d in importer.list_devices(url))
        assert len(names) == 2
    pub_refs = projects.list_public(url)[0]["refs"]
    assert pub_refs[0]["project"] == "pc" and pub_refs[0]["policy"] == "follow"
    with pytest.raises(projects.ProjectError) as e:
        projects.delete_public(url, pub)
    assert e.value.kind == "state" and e.value.data == {"projects": ["liwei/pc"]}  # 属主/标识
    # 删除项目：私有设备（复制出的）删除，公共设备只解除引用
    res = projects.delete_project(url, sc, "pc")
    assert res["counts"]["private_devices"] == 1 and res["counts"]["refs"] == 1
    with store.session(url) as s:
        assert s.get(Device, copied["device_id"]) is None
        assert s.get(Device, pub) is not None
    assert projects.list_public(url)[0]["refs"] == []


def test_transfer_members_and_overrides(url: str, kb) -> None:  # type: ignore[no-untyped-def]
    for n, r in (("boss", "admin"), ("liwei", "user"), ("zhang", "user"), ("wang", "user")):
        users.create_user(url, n, PW, r)
    liwei, zhang, wang = _ident(url, "liwei"), _ident(url, "zhang"), _ident(url, "wang")
    projects.create_project(url, liwei, {"name": "D", "slug": "pd"})
    owner = projects.resolve(url, liwei, "pd")
    projects.set_member(url, owner, "wang", "read")
    reader = projects.resolve(url, wang, "pd")
    assert reader.role == "read" and not reader.can_write
    with pytest.raises(projects.ProjectError) as e:
        projects.update_project(url, reader, {"name": "x"})
    assert e.value.kind == "forbidden"
    with pytest.raises(projects.ProjectError):
        projects.set_member(url, reader, "zhang", "read")
    projects.remove_member(url, reader, "wang")  # 成员自己退出
    with pytest.raises(projects.ProjectError):
        projects.resolve(url, wang, "pd")
    # 规则调整：checks.check 套用当前项目的调整
    with projects.use(owner, liwei):
        _imp(url, BASE)
        dev = importer.list_devices(url)[0]
    g, _, _ = graphstore.build_for_version(url, dev["latest_version_id"], kb)
    rules = []
    base = checks.check(g, kb, rules)
    rid = base["findings"][0]["rule"] if base["findings"] else "ref.orphan"
    projects.set_override(url, owner, rid, False, None, "割接期间不查", None)
    with projects.use(projects.resolve(url, liwei, "pd"), liwei):
        after = checks.check(g, kb, rules)
    assert all(f["rule"] != rid for f in after["findings"])
    assert len(checks.check(g, kb, rules)["findings"]) == len(base["findings"])  # 项目外不受影响
    # 转交：原属主留作可编辑成员
    res = projects.transfer(url, owner, "zhang")
    assert res["owner"] == "zhang" and projects.resolve(url, liwei, "pd").role == "edit"
    assert projects.resolve(url, zhang, "pd").role == "owner"


def test_default_project_and_first_admin_adoption(url: str) -> None:
    # 还没有账号：导入落到没有属主的默认项目
    _imp(url, BASE)
    with store.session(url) as s:
        p = s.scalar(select(Project))
        assert p is not None and p.slug == "default" and p.owner_id is None
    users.create_user(url, "boss", PW, "admin")
    with store.session(url) as s:
        p = s.scalar(select(Project))
        assert p is not None and p.owner_id is not None
    boss = _ident(url, "boss")
    assert projects.default_project(url, boss)["slug"] == "default"
    users.create_user(url, "liwei", PW, "user")
    d = projects.default_project(url, _ident(url, "liwei"))
    # 标识按属主唯一：每个人的默认项目都叫 default；自己看是 default，别人看是 liwei/default
    assert d["slug"] == "default" and d["ref"] == "default"
    with store.session(url) as s:
        p = s.get(Project, d["id"])
        assert p is not None and projects.ref_of(s, p, boss) == "liwei/default"
    # 全局令牌（SYSTEM）的默认项目是第一个管理员的
    assert projects.default_project(url, projects.SYSTEM)["slug"] == "default"
    # 删除账号：空的默认项目自动删除，不要求选择
    users.delete_user(url, "liwei")
    with store.session(url) as s:
        assert s.get(Project, d["id"]) is None


def test_check_projects_belong_to_project(url: str) -> None:
    users.create_user(url, "liwei", PW, "user")
    liwei = _ident(url, "liwei")
    projects.create_project(url, liwei, {"name": "E", "slug": "pe"})
    sc = projects.resolve(url, liwei, "pe")
    me = checkproj.Actor(None, True, "t")
    with projects.use(sc, liwei):
        _imp(url, BASE)
        dev = importer.list_devices(url)[0]["id"]
        r = checkproj.create_project_script(url, me, {"name": "s1", "kind": "change", "device_id": dev, "content": "#"})
        assert r["script"]["name"] == "s1"
        rows = checkproj.list_scripts(url, me)
        assert [x["name"] for x in rows] == ["s1"] and rows[0]["baseline"]["device"]["id"] == dev
    assert projects.default_scope(url, liwei).slug == "pe"  # 第一个项目成为默认项目
    projects.create_project(url, liwei, {"name": "F", "slug": "pf"})
    with projects.use(projects.resolve(url, liwei, "pf"), liwei):
        assert checkproj.list_projects(url, me) == []
        with pytest.raises(checkproj.ProjectError):
            checkproj.get_project(url, me, r["group"]["id"])


# ---------------------------------------------------------------- 个人令牌


def test_personal_tokens(url: str) -> None:
    users.create_user(url, "liwei", PW, "user")
    t = tokens.create(url, "liwei", "ci", read_only=True)
    assert t["token"].startswith("lmp_") and len(t["token"]) == 36 and t["prefix"] == t["token"][:8]
    hit = tokens.authenticate(url, t["token"], "10.0.0.1")
    assert hit is not None and hit["username"] == "liwei" and hit["read_only"] is True
    with store.session(url) as s:
        row = s.scalar(select(ApiToken))
        assert row is not None and row.token_hash != t["token"] and row.last_used_ip == "10.0.0.1"
    assert tokens.authenticate(url, t["token"][:-1] + "x", "") is None
    # 过期
    with store.session(url) as s:
        row = s.scalar(select(ApiToken))
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert tokens.authenticate(url, t["token"], "") is None
    assert tokens.list_tokens(url, "liwei")[0]["state"] == "expired"
    # 撤销、停用账号
    t2 = tokens.create(url, "liwei", "ci2", days=None)
    assert t2["expires_at"] is None
    users.update_user(url, "liwei", disabled=True)
    assert tokens.authenticate(url, t2["token"], "") is None
    users.update_user(url, "liwei", disabled=False)
    tokens.revoke(url, "liwei", t2["id"])
    assert tokens.authenticate(url, t2["token"], "") is None
    with pytest.raises(tokens.TokenError):
        tokens.create(url, "liwei", "x", days=99999)
