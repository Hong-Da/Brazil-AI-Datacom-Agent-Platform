"""项目内的网络（M9，REQ-045）

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-20 12:00:00

- network_folders：网络列表的文件夹（只整理列表）。
- networks：项目内的网络（标识在项目内唯一、识别色、文件夹、是否默认、复制来源、检查结果汇总、最近活动）。
- network_rules：自动加入规则（设备名 / 管理网段）。
- network_members：网络成员（设备、固定的版本或跟随最新、加入方式、手工移出的排除标记）。
- check_ignores、check_projects、project_rule_overrides、ai_suggestion_batches、ai_suggestions、view_annotations
  加 network_id；忽略项、规则调整、视图标注的唯一约束从按项目改为按网络。
- 现有数据：每个项目建“默认网络”（标识 default，颜色 slate），项目的私有设备与引用的公共设备都成为成员（升级时移入，
  跟随最新），项目里的工作数据都移进默认网络。
"""

from datetime import UTC, datetime
from typing import Literal

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None
JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

WORK_TABLES = (
    "check_ignores",
    "check_projects",
    "project_rule_overrides",
    "ai_suggestion_batches",
    "ai_suggestions",
    "view_annotations",
)


def upgrade() -> None:
    op.create_table(
        "network_folders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_network_folders_project_id", "network_folders", ["project_id"])
    op.create_table(
        "networks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("color", sa.String(length=16), nullable=False, server_default="slate"),
        sa.Column("folder_id", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("copied_from", JSONType, nullable=True),
        sa.Column("stats", JSONType, nullable=True),
        sa.Column("last_activity", JSONType, nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["folder_id"], ["network_folders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "slug", name="uq_networks_project_slug"),
    )
    op.create_index("ix_networks_project_id", "networks", ["project_id"])
    op.create_table(
        "network_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("network_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("pattern", sa.String(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["network_id"], ["networks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_network_rules_network_id", "network_rules", ["network_id"])
    op.create_table(
        "network_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("network_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=True),
        sa.Column("join_source", sa.String(length=16), nullable=False, server_default="manual"),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("excluded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("joined_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["network_id"], ["networks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["config_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rule_id"], ["network_rules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("network_id", "device_id", name="uq_network_members_network_device"),
    )
    op.create_index("ix_network_members_network_id", "network_members", ["network_id"])
    op.create_index("ix_network_members_device_id", "network_members", ["device_id"])
    _alter_tables()
    _move_data()


def _alter_tables() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    mode: Literal["always", "auto"] = "always" if sqlite else "auto"
    replace = {
        "check_ignores": (
            "uq_check_ignores_project_device_rule_node",
            "uq_check_ignores_network_device_rule_node",
            ["network_id", "device_id", "rule", "node"],
        ),
        "project_rule_overrides": (
            "uq_project_rule_overrides_project_rule",
            "uq_project_rule_overrides_network_rule",
            ["network_id", "rule"],
        ),
        "view_annotations": (
            "uq_view_annotations_target_key",
            "uq_view_annotations_network_target_key",
            ["network_id", "target_type", "target", "key"],
        ),
    }
    for table in WORK_TABLES:
        with op.batch_alter_table(table, recreate=mode) as b:
            b.add_column(sa.Column("network_id", sa.Integer(), nullable=True))
            b.create_foreign_key(f"fk_{table}_network_id", "networks", ["network_id"], ["id"], ondelete="CASCADE")
            b.create_index(f"ix_{table}_network_id", ["network_id"])
            if table in replace:
                old, new, cols = replace[table]
                b.drop_constraint(old, type_="unique")
                b.create_unique_constraint(new, cols)


def _move_data() -> None:
    conn = op.get_bind()
    now = datetime.now(UTC)
    projects = [int(r[0]) for r in conn.execute(sa.text("SELECT id FROM projects ORDER BY id"))]
    for pid in projects:
        conn.execute(
            sa.text(
                "INSERT INTO networks (project_id, slug, name, description, color, position, is_default, created_by, "
                "created_at, updated_at, last_activity) VALUES (:p, 'default', :n, '', 'slate', 0, :t, '', :now, :now, "
                "NULL)"
            ),
            {"p": pid, "n": "默认网络", "t": True, "now": now},
        )
        nid = int(
            conn.execute(
                sa.text("SELECT id FROM networks WHERE project_id = :p AND slug = 'default'"), {"p": pid}
            ).scalar_one()
        )
        devices = [
            int(r[0])
            for r in conn.execute(
                sa.text(
                    "SELECT id FROM devices WHERE project_id = :p UNION "
                    "SELECT device_id FROM project_device_refs WHERE project_id = :p"
                ),
                {"p": pid},
            )
        ]
        for did in sorted(set(devices)):
            conn.execute(
                sa.text(
                    "INSERT INTO network_members (network_id, device_id, version_id, join_source, excluded, joined_by, "
                    "joined_at) VALUES (:n, :d, NULL, 'upgrade', :f, '', :now)"
                ),
                {"n": nid, "d": did, "f": False, "now": now},
            )
        for table in WORK_TABLES:
            conn.execute(sa.text(f"UPDATE {table} SET network_id = :n WHERE project_id = :p"), {"n": nid, "p": pid})
    # 检查项目里的脚本组没有项目时（升级前直接调用 core 建的）保持为空


def downgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    mode: Literal["always", "auto"] = "always" if sqlite else "auto"
    restore = {
        "check_ignores": (
            "uq_check_ignores_network_device_rule_node",
            "uq_check_ignores_project_device_rule_node",
            ["project_id", "device_id", "rule", "node"],
        ),
        "project_rule_overrides": (
            "uq_project_rule_overrides_network_rule",
            "uq_project_rule_overrides_project_rule",
            ["project_id", "rule"],
        ),
        "view_annotations": (
            "uq_view_annotations_network_target_key",
            "uq_view_annotations_target_key",
            ["project_id", "target_type", "target", "key"],
        ),
    }
    for table in WORK_TABLES:
        with op.batch_alter_table(table, recreate=mode) as b:
            if table in restore:
                old, new, cols = restore[table]
                b.drop_constraint(old, type_="unique")
                b.create_unique_constraint(new, cols)
            b.drop_index(f"ix_{table}_network_id")
            b.drop_constraint(f"fk_{table}_network_id", type_="foreignkey")
            b.drop_column("network_id")
    for idx, table in (
        ("ix_network_members_device_id", "network_members"),
        ("ix_network_members_network_id", "network_members"),
        ("ix_network_rules_network_id", "network_rules"),
        ("ix_networks_project_id", "networks"),
        ("ix_network_folders_project_id", "network_folders"),
    ):
        op.drop_index(idx, table_name=table)
    for table in ("network_members", "network_rules", "networks", "network_folders"):
        op.drop_table(table)
