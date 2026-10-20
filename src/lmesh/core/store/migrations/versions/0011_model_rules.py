"""未支持型号的处理（M8-7，REQ-044）

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-20 09:00:00

- model_rules：型号规则（设备名模式、软件版本、特征命令 → Profile），project_id 为空是全局规则。
- devices 加 profile_source（auto / fallback / rule / manual / none）与 profile_rule_id（按哪条型号规则选的）。
  已有设备：Profile 为空的记 none，其余记 auto（升级后第一次重新解析时按新的选择顺序重新判断）。
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("vendor", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("name_pattern", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("version", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("feature", sa.String(length=400), nullable=False, server_default=""),
        sa.Column("profile", sa.String(length=120), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_rules_project_id", "model_rules", ["project_id"])
    with op.batch_alter_table("devices") as b:
        b.add_column(sa.Column("profile_source", sa.String(length=10), nullable=False, server_default="auto"))
        b.add_column(sa.Column("profile_rule_id", sa.Integer(), nullable=True))
        b.create_foreign_key(
            "fk_devices_profile_rule_id", "model_rules", ["profile_rule_id"], ["id"], ondelete="SET NULL"
        )
    op.execute("UPDATE devices SET profile_source = 'none' WHERE profile IS NULL OR profile = ''")


def downgrade() -> None:
    with op.batch_alter_table("devices") as b:
        b.drop_constraint("fk_devices_profile_rule_id", type_="foreignkey")
        b.drop_column("profile_rule_id")
        b.drop_column("profile_source")
    op.drop_index("ix_model_rules_project_id", table_name="model_rules")
    op.drop_table("model_rules")
