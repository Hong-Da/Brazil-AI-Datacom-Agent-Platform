"""项目标识按属主唯一（M6 评审改选，2026-10-19）：迁移 0008（从 0007 样本升级）、项目引用的解析与歧义、
新建 / 改标识 / 转交时的重名检查、规范引用 ref；SQLite 与 PostgreSQL 各一次。"""

from __future__ import annotations

import pytest
from sqlalchemy import exc, select, text

from lmesh.core import projects, store, users
from lmesh.core.store.models import Project, User

pytestmark = pytest.mark.unit
PW = "Pass-word-123"


@pytest.fixture
def url(db_url: str) -> str:
    store.upgrade(db_url)
    return db_url


def _ident(url: str, name: str) -> projects.Identity:
    return projects.cli_identity(url, name)


def _upgrade_to(url: str, rev: str) -> None:
    from alembic import command

    cfg = store._alembic_config(url)
    with store.get_engine(url).connect() as conn:
        if url.startswith("sqlite"):
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()
        with conn.begin():
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, rev)


SAMPLE_0007 = [
    "INSERT INTO users (id, username, role, disabled, password_hash, failed_count, password_changed_at, created_at) "
    "VALUES (1, 'boss', 'admin', false, 'x', 0, :n, :n), (2, 'liwei', 'user', false, 'x', 0, :n, :n), "
    "(3, 'zhang', 'user', false, 'x', 0, :n, :n)",
    "INSERT INTO projects (id, slug, name, description, owner_id, created_at, updated_at) VALUES "
    "(1, 'default', '默认项目', '', 1, :n, :n), (2, 'oam-vpn', 'OAM', '', 2, :n, :n), "
    "(3, 'zhang-default', '默认项目', '', 3, :n, :n), (4, 'orphan', '没有属主', '', NULL, :n, :n)",
]


def test_migration_0008_from_0007_sample(db_url: str) -> None:
    _upgrade_to(db_url, "0007")
    with store.get_engine(db_url).begin() as c:
        for sql in SAMPLE_0007:
            c.execute(text(sql), {"n": "2026-10-19 00:00:00"})
        if db_url.startswith("postgresql"):
            for t in ("users", "projects"):
                c.execute(text(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), (SELECT MAX(id) FROM {t}))"))
    store._UPGRADED.discard(db_url)
    store.upgrade(db_url)
    with store.session(db_url) as s:
        # 数据不变；已有账号为 active / admin
        assert sorted(s.scalars(select(Project.slug))) == ["default", "oam-vpn", "orphan", "zhang-default"]
        assert {(u.status, u.origin) for u in s.scalars(select(User))} == {("active", "admin")}
        # 不同属主可以同名
        s.add(Project(slug="oam-vpn", name="张的 OAM", description="", owner_id=3, settings={}))
        s.flush()
    # 同一属主内不能同名
    with pytest.raises(exc.IntegrityError), store.session(db_url) as s:
        s.add(Project(slug="oam-vpn", name="重复", description="", owner_id=2, settings={}))
        s.flush()
    # 属主为空的项目之间也不能同名（部分唯一索引）
    with pytest.raises(exc.IntegrityError), store.session(db_url) as s:
        s.add(Project(slug="orphan", name="重复", description="", owner_id=None, settings={}))
        s.flush()
    with store.session(db_url) as s:
        assert s.scalar(text("SELECT COUNT(*) FROM projects WHERE slug = 'oam-vpn'")) == 2


@pytest.fixture
def three(url: str) -> dict[str, projects.Identity]:
    for name, role in (("boss", "admin"), ("liwei", "user"), ("zhang", "user"), ("wang", "user")):
        users.create_user(url, name, PW, role)
    return {n: _ident(url, n) for n in ("boss", "liwei", "zhang", "wang")}


def test_same_slug_for_different_owners(url: str, three: dict[str, projects.Identity]) -> None:
    liwei, zhang, wang, boss = three["liwei"], three["zhang"], three["wang"], three["boss"]
    a = projects.create_project(url, liwei, {"name": "李伟 OAM", "slug": "oam-vpn"})
    b = projects.create_project(url, zhang, {"name": "张 OAM", "slug": "oam-vpn"})
    assert a["id"] != b["id"] and a["ref"] == "oam-vpn" and a["full_ref"] == "liwei/oam-vpn"
    # 同一属主内重名
    with pytest.raises(projects.ProjectError) as e:
        projects.create_project(url, liwei, {"name": "again", "slug": "oam-vpn"})
    assert e.value.key == "projects.slug_taken" and e.value.kind == "state"
    # 只写标识：先找自己的
    assert projects.resolve(url, liwei, "oam-vpn").project_id == a["id"]
    assert projects.resolve(url, zhang, "oam-vpn").project_id == b["id"]
    # 属主/标识：精确；不是成员时不存在
    with pytest.raises(projects.ProjectError) as e:
        projects.resolve(url, liwei, "zhang/oam-vpn")
    assert e.value.kind == "not_found"
    # 成员访问别人的同名项目：自己有同名的时候只写标识仍是自己的，写全才是别人的
    projects.set_member(url, projects.resolve(url, zhang, "oam-vpn"), "liwei", "read")
    sc = projects.resolve(url, liwei, "zhang/oam-vpn")
    assert sc.project_id == b["id"] and sc.role == "read" and sc.ref == "zhang/oam-vpn"
    assert projects.resolve(url, liwei, "zhang~oam-vpn").project_id == b["id"]  # 网址里的写法
    # 自己没有同名、只在一个能访问的项目里匹配：唯一匹配就用它
    projects.set_member(url, projects.resolve(url, liwei, "oam-vpn"), "wang", "edit")
    sc = projects.resolve(url, wang, "oam-vpn")
    assert sc.project_id == a["id"] and sc.ref == "liwei/oam-vpn"
    # 能访问两个同名项目：歧义报错并列出候选，不静默挑一个
    projects.set_member(url, projects.resolve(url, zhang, "oam-vpn"), "wang", "read")
    with pytest.raises(projects.ProjectError) as e:
        projects.resolve(url, wang, "oam-vpn")
    assert e.value.kind == "ambiguous" and e.value.key == "projects.ambiguous"
    assert e.value.data == {"candidates": ["liwei/oam-vpn", "zhang/oam-vpn"]}
    # 管理员：自己没有时在全部项目里找，多个时同样歧义；全局令牌按第一个管理员
    for who in (boss, projects.SYSTEM):
        with pytest.raises(projects.ProjectError) as e:
            projects.resolve(url, who, "oam-vpn")
        assert e.value.kind == "ambiguous"
        assert projects.resolve(url, who, "liwei/oam-vpn").role == "admin"
    mine = projects.create_project(url, boss, {"name": "管理员的", "slug": "oam-vpn"})
    for who in (boss, projects.SYSTEM):
        assert projects.resolve(url, who, "oam-vpn").project_id == mine["id"]
    # 编号仍可用
    assert projects.resolve(url, boss, str(b["id"])).project_id == b["id"]
    # 列表的规范引用：自己的写标识，别人的写 属主/标识
    lists = projects.list_projects(url, wang)
    assert sorted(r["ref"] for r in lists["shared"]) == ["liwei/oam-vpn", "zhang/oam-vpn"]


def test_rename_and_transfer_conflicts(url: str, three: dict[str, projects.Identity]) -> None:
    liwei, zhang, boss = three["liwei"], three["zhang"], three["boss"]
    projects.create_project(url, liwei, {"name": "A", "slug": "alpha"})
    projects.create_project(url, liwei, {"name": "B", "slug": "beta"})
    projects.create_project(url, zhang, {"name": "Z", "slug": "beta"})
    sc = projects.resolve(url, liwei, "alpha")
    # 改标识：只在属主自己的项目里查重
    with pytest.raises(projects.ProjectError) as e:
        projects.update_project(url, sc, {"slug": "beta"})
    assert e.value.key == "projects.slug_taken"
    # 管理员给别人的项目改标识撞名：提示属主已有并给出建议
    with pytest.raises(projects.ProjectError) as e:
        projects.update_project(url, projects.resolve(url, boss, "liwei/alpha"), {"slug": "beta"})
    assert e.value.key == "projects.slug_taken_owner" and e.value.data == {"suggested": "beta-2"}
    # 转交：新属主已有同名标识时拒绝，并给出可用的标识；带新标识时成功
    sc = projects.resolve(url, liwei, "beta")
    with pytest.raises(projects.ProjectError) as e:
        projects.transfer(url, sc, "zhang")
    assert e.value.key == "projects.slug_taken_owner" and e.value.data == {"suggested": "beta-2"}
    res = projects.transfer(url, sc, "zhang", new_slug="beta-li")
    assert res["full_ref"] == "zhang/beta-li"
    assert projects.resolve(url, liwei, "zhang/beta-li").role == "edit"
    # 复制为自己的项目：重名检查在新属主（调用者）范围内
    projects.set_member(url, projects.resolve(url, zhang, "beta"), "liwei", "read")
    copied = projects.copy_project(url, projects.resolve(url, liwei, "zhang/beta"), liwei, {"name": "copy"})
    assert copied["slug"] == "copy" and copied["owner"] == "liwei"
    again = projects.copy_project(url, projects.resolve(url, liwei, "zhang/beta"), liwei, {"name": "x", "slug": "beta"})
    assert again["full_ref"] == "liwei/beta"


def test_delete_account_transfer_renames_on_conflict(url: str, three: dict[str, projects.Identity]) -> None:
    liwei, zhang = three["liwei"], three["zhang"]
    users.create_user(url, "tmp", PW, "user")
    tmp = _ident(url, "tmp")
    projects.create_project(url, zhang, {"name": "Z", "slug": "shared-name"})
    projects.create_project(url, tmp, {"name": "T", "slug": "shared-name", "description": "x"})
    projects.set_member(url, projects.resolve(url, tmp, "shared-name"), "liwei", "read")  # 非空项目
    users.delete_user(url, "tmp", transfer_to="zhang")
    lists = projects.list_projects(url, zhang)
    assert sorted(r["slug"] for r in lists["mine"]) == ["shared-name", "shared-name-2"]
    assert projects.resolve(url, liwei, "zhang/shared-name-2").role == "read"


def test_ownerless_projects_and_adoption(url: str) -> None:
    # 没有账号时建的项目属主为空，它们之间标识唯一；第一个管理员接管时与他已有的重名会加编号
    projects.create_project(url, projects.SYSTEM, {"name": "X", "slug": "xx"})
    with pytest.raises(projects.ProjectError):
        projects.create_project(url, projects.SYSTEM, {"name": "X2", "slug": "xx"})
    assert projects.resolve(url, projects.SYSTEM, "xx").ref == "xx"
    users.create_user(url, "boss", PW, "admin")
    boss = _ident(url, "boss")
    sc = projects.resolve(url, boss, "xx")
    assert sc.role == "owner" and sc.ref == "xx"


def test_split_ref() -> None:
    assert projects.split_ref("liwei/OAM-vpn") == ("liwei", "oam-vpn")
    assert projects.split_ref("liwei~oam") == ("liwei", "oam")
    assert projects.split_ref(" oam ") == (None, "oam")
