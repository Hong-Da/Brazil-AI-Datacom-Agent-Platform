"""忽略的检查发现（M2-5）

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18 10:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "check_ignores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("rule", sa.String(length=120), nullable=False),
        sa.Column("node", sa.String(length=600), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "rule", "node", name="uq_check_ignores_device_rule_node"),
    )
    with op.batch_alter_table("check_ignores", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_check_ignores_device_id"), ["device_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("check_ignores", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_check_ignores_device_id"))
    op.drop_table("check_ignores")
