"""用户工作空间与项目、权限、个人 API 令牌（M6，REQ-035 / REQ-036）

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-19 12:00:00

结构：projects、project_members、workspaces、project_device_refs、project_rule_overrides、api_tokens、audit_events、
user_assets；devices 增加 project_id / origin / origin_note，名称改为项目内唯一；check_ignores 按项目；
check_projects 增加 project_id。

现有数据（用户确认的做法）：
- 每个账号建一个工作空间；
- 有账号或有设备时建“默认项目”（slug default），属于第一个管理员（没有账号时属主为空，第一个管理员创建后接管），
  现有设备、配置版本、导入记录、检查忽略项都移入其中（私有设备，origin = migrated）；
- 已有的配置检查项目各自转为一个项目（属主为空的归第一个管理员），基线设备复制为该项目的私有设备（D-0175），
  固定的基线版本对应到复制出的版本。

SQLite 上重建 devices / check_ignores 表时外键必须关闭（store.upgrade 负责），否则删除旧表会级联删除配置版本。
"""

import re
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
_SLUG_BAD = re.compile(r"[^a-z0-9]+")


def _now() -> datetime:
    return datetime.now(UTC)


def _create_tables() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("settings", JSONType, nullable=True),
        sa.Column("migrated_from", JSONType, nullable=True),
        sa.Column("last_activity", JSONType, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_projects_slug"),
    )
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])
    op.create_table(
        "project_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
    )
    op.create_index("ix_project_members_project_id", "project_members", ["project_id"])
    op.create_index("ix_project_members_user_id", "project_members", ["user_id"])
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("default_project_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["default_project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_workspaces_user_id"),
    )
    op.create_table(
        "project_device_refs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["config_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "device_id", name="uq_project_device_refs_project_device"),
    )
    op.create_index("ix_project_device_refs_project_id", "project_device_refs", ["project_id"])
    op.create_index("ix_project_device_refs_device_id", "project_device_refs", ["device_id"])
    op.create_table(
        "project_rule_overrides",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("rule", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "rule", name="uq_project_rule_overrides_project_rule"),
    )
    op.create_index("ix_project_rule_overrides_project_id", "project_rule_overrides", ["project_id"])
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("read_only", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_ip", sa.String(length=64), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_api_tokens_token_hash"),
    )
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("project_slug", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("detail", JSONType, nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_at", "audit_events", ["at"])
    op.create_index("ix_audit_events_project_id", "audit_events", ["project_id"])
    op.create_table(
        "user_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("asset_id", sa.String(length=120), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "asset_id", name="uq_user_assets_kind_asset"),
    )
    op.create_index("ix_user_assets_user_id", "user_assets", ["user_id"])


def _alter_tables() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    # devices：名称从全局唯一改为项目内唯一。SQLite 上 0001 建的是匿名唯一约束，用命名规则让 batch 能找到并删除它
    with op.batch_alter_table(
        "devices",
        naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"},
        recreate="always" if sqlite else "auto",
    ) as b:
        b.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("origin", sa.String(length=20), nullable=False, server_default="import"))
        b.add_column(sa.Column("origin_note", JSONType, nullable=True))
        b.drop_constraint("uq_devices_name" if sqlite else "devices_name_key", type_="unique")
        b.create_foreign_key("fk_devices_project_id", "projects", ["project_id"], ["id"], ondelete="CASCADE")
        b.create_unique_constraint("uq_devices_project_name", ["project_id", "name"])
        b.create_index("ix_devices_project_id", ["project_id"])
    with op.batch_alter_table("check_ignores") as b:
        b.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        b.drop_constraint("uq_check_ignores_device_rule_node", type_="unique")
        b.create_foreign_key("fk_check_ignores_project_id", "projects", ["project_id"], ["id"], ondelete="CASCADE")
        b.create_unique_constraint(
            "uq_check_ignores_project_device_rule_node", ["project_id", "device_id", "rule", "node"]
        )
        b.create_index("ix_check_ignores_project_id", ["project_id"])
    with op.batch_alter_table("check_projects") as b:
        b.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_check_projects_project_id", "projects", ["project_id"], ["id"], ondelete="CASCADE")
        b.create_index("ix_check_projects_project_id", ["project_id"])


# ---------------------------------------------------------------- 现有数据


_MD = sa.MetaData()
_projects = sa.Table(
    "projects",
    _MD,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("slug", sa.String),
    sa.Column("name", sa.String),
    sa.Column("description", sa.Text),
    sa.Column("owner_id", sa.Integer),
    sa.Column("settings", JSONType),
    sa.Column("migrated_from", JSONType),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
)
_devices = sa.Table(
    "devices",
    _MD,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("name", sa.String),
    sa.Column("vendor", sa.String),
    sa.Column("platform", sa.String),
    sa.Column("sw_version", sa.String),
    sa.Column("profile", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("project_id", sa.Integer),
    sa.Column("origin", sa.String),
    sa.Column("origin_note", JSONType),
)
_versions = sa.Table(
    "config_versions",
    _MD,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("device_id", sa.Integer),
    sa.Column("source_name", sa.String),
    sa.Column("raw_text", sa.Text),
    sa.Column("structured", JSONType),
    sa.Column("sanitized", sa.Boolean),
    sa.Column("kb_version", sa.String),
    sa.Column("collected_at", sa.DateTime(timezone=True)),
    sa.Column("content_hash", sa.String),
    sa.Column("graph_gz", sa.LargeBinary),
    sa.Column("tag", sa.String),
    sa.Column("change_summary", JSONType),
)
_imports = sa.Table(
    "config_imports",
    _MD,
    sa.Column("device_id", sa.Integer),
    sa.Column("version_id", sa.Integer),
    sa.Column("imported_at", sa.DateTime(timezone=True)),
    sa.Column("source_kind", sa.String),
    sa.Column("source_name", sa.String),
    sa.Column("actor", sa.String),
    sa.Column("duplicate", sa.Boolean),
)
_workspaces = sa.Table(
    "workspaces",
    _MD,
    sa.Column("user_id", sa.Integer),
    sa.Column("default_project_id", sa.Integer),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)


def _slug(conn: sa.Connection, base: str, fallback: str) -> str:
    s = _SLUG_BAD.sub("-", base.lower()).strip("-")[:56]
    if len(s) < 2 or not s[0].isalnum():
        s = fallback
    cand, n = s, 2
    while conn.execute(sa.text("SELECT 1 FROM projects WHERE slug = :s"), {"s": cand}).first():
        cand, n = f"{s}-{n}", n + 1
    return cand


def _new_project(
    conn: sa.Connection, slug: str, name: str, description: str, owner: int | None, origin: dict[str, object]
) -> int:
    now = _now()
    res = conn.execute(
        _projects.insert().values(
            slug=slug,
            name=name,
            description=description,
            owner_id=owner,
            settings={},
            migrated_from=origin,
            created_at=now,
            updated_at=now,
        )
    )
    return int(res.inserted_primary_key[0])  # type: ignore[index]


def _copy_device(
    conn: sa.Connection, device_id: int, version_id: int | None, project_id: int, cp_name: str
) -> int | None:
    """把检查项目的基线设备复制为新项目的私有设备（只复制作为基线的那一个版本），返回复制出的版本编号。"""
    dev = conn.execute(sa.select(_devices).where(_devices.c.id == device_id)).mappings().first()
    if dev is None:
        return None
    vq = sa.select(_versions).where(_versions.c.device_id == device_id)
    ver = (
        conn.execute(
            vq.where(_versions.c.id == version_id) if version_id else vq.order_by(_versions.c.id.desc()).limit(1)
        )
        .mappings()
        .first()
    )
    seq = None
    if ver is not None:
        seq = conn.execute(
            sa.text("SELECT COUNT(*) FROM config_versions WHERE device_id = :d AND id <= :v"),
            {"d": device_id, "v": ver["id"]},
        ).scalar()
    note = {"type": "check_project", "check_project": cp_name, "project": "default", "device": dev["name"], "seq": seq}
    new_dev = conn.execute(
        _devices.insert().values(
            name=dev["name"],
            vendor=dev["vendor"],
            platform=dev["platform"],
            sw_version=dev["sw_version"],
            profile=dev["profile"],
            created_at=_now(),
            project_id=project_id,
            origin="copy",
            origin_note=note,
        )
    ).inserted_primary_key[0]  # type: ignore[index]
    if ver is None:
        return None
    cols = {k: ver[k] for k in ver.keys() if k not in ("id", "device_id")}  # noqa: SIM118
    new_ver = conn.execute(_versions.insert().values(device_id=new_dev, **cols)).inserted_primary_key[0]  # type: ignore[index]
    for table, columns in (
        ("nodes", "node_key, schema_type, value, origin, line_start, line_end, parent_key"),
        ("edges", "src_key, dst_key, kind, attrs"),
        ("unknown_lines", "line_no, text, view, pattern"),
    ):
        conn.execute(
            sa.text(
                f"INSERT INTO {table} (version_id, {columns}) SELECT :new, {columns} FROM {table} WHERE version_id = :old"
            ),
            {"new": new_ver, "old": ver["id"]},
        )
    conn.execute(
        _imports.insert().values(
            device_id=new_dev,
            version_id=new_ver,
            imported_at=_now(),
            source_kind="copy",
            source_name=ver["source_name"] or "",
            actor="upgrade-0.6.0",
            duplicate=False,
        )
    )
    return int(new_ver)


def _migrate_data() -> None:
    conn = op.get_bind()
    users = conn.execute(sa.text("SELECT id, role, disabled FROM users ORDER BY id")).all()
    admins = [u for u in users if u[1] == "admin"]
    enabled_admins = [u for u in admins if not u[2]]
    pick = enabled_admins or admins
    admin_id = int(pick[0][0]) if pick else None
    now = _now()
    for u in users:
        conn.execute(_workspaces.insert().values(user_id=u[0], default_project_id=None, created_at=now))
    has_devices = conn.execute(sa.text("SELECT 1 FROM devices")).first() is not None
    if not users and not has_devices:
        return  # 新库：默认项目在第一次用到时再建
    default_id = _new_project(conn, "default", "默认项目", "", admin_id, {"type": "upgrade", "version": "0.6.0"})
    conn.execute(sa.text("UPDATE devices SET project_id = :p, origin = 'migrated'"), {"p": default_id})
    conn.execute(
        sa.text(
            "UPDATE check_ignores SET project_id = (SELECT d.project_id FROM devices d WHERE d.id = check_ignores.device_id)"
        )
    )
    if admin_id is not None:
        conn.execute(
            sa.text("UPDATE workspaces SET default_project_id = :p WHERE user_id = :u"),
            {"p": default_id, "u": admin_id},
        )
    rows = conn.execute(
        sa.text("SELECT id, name, description, device_id, version_id, user_id FROM check_projects ORDER BY id")
    ).all()
    for cp_id, name, desc, dev_id, ver_id, user_id in rows:
        owner = user_id if user_id is not None else admin_id
        pid = _new_project(
            conn,
            _slug(conn, str(name or ""), f"check-{cp_id}"),
            str(name or f"check-{cp_id}"),
            str(desc or ""),
            owner,
            {"type": "check_project", "id": cp_id, "name": name},
        )
        new_ver = _copy_device(conn, dev_id, ver_id, pid, str(name or "")) if dev_id is not None else None
        new_dev = None
        if new_ver is not None:
            new_dev = conn.execute(
                sa.text("SELECT device_id FROM config_versions WHERE id = :v"), {"v": new_ver}
            ).scalar()
        elif dev_id is not None:
            new_dev = conn.execute(
                sa.text("SELECT id FROM devices WHERE project_id = :p ORDER BY id LIMIT 1"), {"p": pid}
            ).scalar()
        conn.execute(
            sa.text("UPDATE check_projects SET project_id = :p, device_id = :d, version_id = :v WHERE id = :id"),
            {"p": pid, "d": new_dev, "v": new_ver if ver_id is not None else None, "id": cp_id},
        )
        if owner is not None and owner != admin_id:
            conn.execute(
                sa.text(
                    "UPDATE workspaces SET default_project_id = :p WHERE user_id = :u AND default_project_id IS NULL"
                ),
                {"p": pid, "u": owner},
            )


def upgrade() -> None:
    _create_tables()
    _alter_tables()
    _migrate_data()


def downgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    with op.batch_alter_table("check_projects") as b:
        b.drop_index("ix_check_projects_project_id")
        b.drop_constraint("fk_check_projects_project_id", type_="foreignkey")
        b.drop_column("project_id")
    with op.batch_alter_table("check_ignores") as b:
        b.drop_index("ix_check_ignores_project_id")
        b.drop_constraint("uq_check_ignores_project_device_rule_node", type_="unique")
        b.drop_constraint("fk_check_ignores_project_id", type_="foreignkey")
        b.drop_column("project_id")
        b.create_unique_constraint("uq_check_ignores_device_rule_node", ["device_id", "rule", "node"])
    # 复制出的设备在降级时删除（名称会与原设备重复）
    op.execute("DELETE FROM devices WHERE origin = 'copy'")
    with op.batch_alter_table("devices", recreate="always" if sqlite else "auto") as b:
        b.drop_index("ix_devices_project_id")
        b.drop_constraint("uq_devices_project_name", type_="unique")
        b.drop_constraint("fk_devices_project_id", type_="foreignkey")
        b.drop_column("origin_note")
        b.drop_column("origin")
        b.drop_column("project_id")
        b.create_unique_constraint("uq_devices_name", ["name"])
    for t in (
        "user_assets",
        "audit_events",
        "api_tokens",
        "project_rule_overrides",
        "project_device_refs",
        "workspaces",
        "project_members",
        "projects",
    ):
        op.drop_table(t)
