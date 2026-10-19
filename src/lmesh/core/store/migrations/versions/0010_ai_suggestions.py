"""AI 建议框架（M8-2，REQ-041）

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-19 23:30:00

- ai_suggestion_batches：一次运行（项目、设备 / 范围、skill 与版本、AI 接口与调用记录、发起人、状态、计数、代码给出的事实）。
- ai_suggestions：一条建议（类别、内容、依据与引用、代码校验结果、状态 pending / adopted / dismissed / reverted、
  采纳与撤销信息）。
- view_annotations：项目级视图标注（设备角色、分组、标签……；手工或采纳的 AI 建议），可撤销。
- ai_choices 加 no_token_warn：个人偏好“不提示大请求”（优先于全局 ai.warn_tokens）。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None
JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "ai_suggestion_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("scope_key", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("skill", sa.String(length=60), nullable=False),
        sa.Column("skill_version", sa.String(length=20), nullable=False, server_default="builtin"),
        sa.Column("mode", sa.String(length=10), nullable=False, server_default="ai"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("task_id", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("skill_run_id", sa.Integer(), nullable=True),
        sa.Column("ai_call_ids", JSONType, nullable=True),
        sa.Column("connection_name", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("ai_source", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("model", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("params", JSONType, nullable=True),
        sa.Column("context", JSONType, nullable=True),
        sa.Column("counts", JSONType, nullable=True),
        sa.Column("error", JSONType, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["skill_run_id"], ["skill_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_suggestion_batches_project_id", "ai_suggestion_batches", ["project_id"])
    op.create_index("ix_ai_suggestion_batches_skill", "ai_suggestion_batches", ["skill"])
    op.create_index("ix_ai_suggestion_batches_created_at", "ai_suggestion_batches", ["created_at"])
    op.create_table(
        "ai_suggestions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("scope_key", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("skill", sa.String(length=60), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=400), nullable=False, server_default=""),
        sa.Column("content", JSONType, nullable=True),
        sa.Column("original", JSONType, nullable=True),
        sa.Column("refs", JSONType, nullable=True),
        sa.Column("check", JSONType, nullable=True),
        sa.Column("check_status", sa.String(length=10), nullable=False, server_default="reject"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("ai_call_id", sa.Integer(), nullable=True),
        sa.Column("connection_name", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("decided_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("adopt_info", JSONType, nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("reverted_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revert_info", JSONType, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["ai_suggestion_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ai_call_id"], ["ai_calls.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("batch_id", "project_id", "skill", "check_status", "status", "created_at"):
        op.create_index(f"ix_ai_suggestions_{col}", "ai_suggestions", [col])
    op.create_table(
        "view_annotations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target", sa.String(length=200), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("value", JSONType, nullable=True),
        sa.Column("source", sa.String(length=10), nullable=False, server_default="user"),
        sa.Column("suggestion_id", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["suggestion_id"], ["ai_suggestions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "target_type", "target", "key", name="uq_view_annotations_target_key"),
    )
    op.create_index("ix_view_annotations_project_id", "view_annotations", ["project_id"])
    with op.batch_alter_table("ai_choices") as b:
        b.add_column(sa.Column("no_token_warn", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("ai_choices") as b:
        b.drop_column("no_token_warn")
    op.drop_index("ix_view_annotations_project_id", table_name="view_annotations")
    op.drop_table("view_annotations")
    for col in ("batch_id", "project_id", "skill", "check_status", "status", "created_at"):
        op.drop_index(f"ix_ai_suggestions_{col}", table_name="ai_suggestions")
    op.drop_table("ai_suggestions")
    for col in ("created_at", "skill", "project_id"):
        op.drop_index(f"ix_ai_suggestion_batches_{col}", table_name="ai_suggestion_batches")
    op.drop_table("ai_suggestion_batches")
