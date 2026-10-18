"""配置检查项目、脚本与修订记录（REQ-031）

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18 23:00:00
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "check_projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("version_id", sa.Integer(), nullable=True),
        sa.Column("profile", sa.String(length=120), nullable=False),
        sa.Column("default_kind", sa.String(length=20), nullable=False),
        sa.Column("order_check", sa.Boolean(), nullable=False),
        sa.Column("ai_check", sa.Boolean(), nullable=False),
        sa.Column("ai_rules", JSONType, nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["version_id"], ["config_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_check_projects_user_id"), "check_projects", ["user_id"], unique=False)
    op.create_table(
        "check_scripts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("last_check", JSONType, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["check_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_check_scripts_project_id"), "check_scripts", ["project_id"], unique=False)
    op.create_table(
        "check_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("script_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("note", JSONType, nullable=True),
        sa.Column("summary", JSONType, nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("author", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["script_id"], ["check_scripts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("script_id", "seq", name="uq_check_revisions_script_seq"),
    )
    op.create_index(op.f("ix_check_revisions_script_id"), "check_revisions", ["script_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_check_revisions_script_id"), table_name="check_revisions")
    op.drop_table("check_revisions")
    op.drop_index(op.f("ix_check_scripts_project_id"), table_name="check_scripts")
    op.drop_table("check_scripts")
    op.drop_index(op.f("ix_check_projects_user_id"), table_name="check_projects")
    op.drop_table("check_projects")
