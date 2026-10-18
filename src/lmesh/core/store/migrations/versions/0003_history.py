"""版本历史：快照指纹、图、标签、变化计数与导入记录（M5-2）

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-18 20:00:00
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("config_versions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("content_hash", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("graph_gz", sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column("tag", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("change_summary", JSONType, nullable=True))
        batch_op.create_index(batch_op.f("ix_config_versions_content_hash"), ["content_hash"], unique=False)
    op.create_table(
        "config_imports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_kind", sa.String(length=20), nullable=False),
        sa.Column("source_name", sa.String(length=400), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("duplicate", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["config_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("config_imports", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_config_imports_device_id"), ["device_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_config_imports_version_id"), ["version_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("config_imports", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_config_imports_version_id"))
        batch_op.drop_index(batch_op.f("ix_config_imports_device_id"))
    op.drop_table("config_imports")
    with op.batch_alter_table("config_versions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_config_versions_content_hash"))
        batch_op.drop_column("change_summary")
        batch_op.drop_column("tag")
        batch_op.drop_column("graph_gz")
        batch_op.drop_column("content_hash")
