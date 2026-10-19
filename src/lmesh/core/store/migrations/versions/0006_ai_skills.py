"""AI skill 的调用记录、案例（回归集与候选示例）与进化（REQ-033）

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-19 02:00:00
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "skill_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("skill", sa.String(length=60), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("task", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("input", JSONType, nullable=True),
        sa.Column("reply", sa.Text(), nullable=False),
        sa.Column("detail", JSONType, nullable=True),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("ms", sa.Integer(), nullable=False),
        sa.Column("rating", sa.String(length=10), nullable=True),
        sa.Column("correction", sa.Text(), nullable=False),
        sa.Column("feedback_by", sa.String(length=200), nullable=False),
        sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_skill_runs_skill"), "skill_runs", ["skill"], unique=False)
    op.create_index(op.f("ix_skill_runs_created_at"), "skill_runs", ["created_at"], unique=False)
    op.create_table(
        "skill_cases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("skill", sa.String(length=60), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("input", JSONType, nullable=True),
        sa.Column("reply", sa.Text(), nullable=False),
        sa.Column("detail", JSONType, nullable=True),
        sa.Column("expect", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["skill_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill", "kind", "input_hash", name="uq_skill_cases_skill_kind_hash"),
    )
    op.create_index(op.f("ix_skill_cases_skill"), "skill_cases", ["skill"], unique=False)
    op.create_table(
        "skill_evolutions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("skill", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("base_version", sa.String(length=20), nullable=False),
        sa.Column("candidate", JSONType, nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("scores", JSONType, nullable=True),
        sa.Column("error", JSONType, nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.String(length=200), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_version", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_skill_evolutions_skill"), "skill_evolutions", ["skill"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_skill_evolutions_skill"), table_name="skill_evolutions")
    op.drop_table("skill_evolutions")
    op.drop_index(op.f("ix_skill_cases_skill"), table_name="skill_cases")
    op.drop_table("skill_cases")
    op.drop_index(op.f("ix_skill_runs_created_at"), table_name="skill_runs")
    op.drop_index(op.f("ix_skill_runs_skill"), table_name="skill_runs")
    op.drop_table("skill_runs")
