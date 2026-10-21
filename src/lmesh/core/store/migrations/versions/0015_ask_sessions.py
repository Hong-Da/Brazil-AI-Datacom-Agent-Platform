"""AI 查询会话、附件（REQ-052、REQ-053）

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-21 20:00:00

- ask_sessions：会话（项目、本人、标题、网络与设备范围、归档、分享）。
- ask_turns：会话中的一轮（各版本的问题与结果、当前版本、带了几轮上下文）。
- ask_attachments：会话附件（配置文件作为临时设备、文档文字、图片）。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "ask_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("owner", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("network_id", sa.Integer(), nullable=True),
        sa.Column("network_slug", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("devices", JSONType, nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["network_id"], ["networks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ask_sessions_project_id", "ask_sessions", ["project_id"])
    op.create_index("ix_ask_sessions_user_id", "ask_sessions", ["user_id"])
    op.create_table(
        "ask_turns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("versions", JSONType, nullable=True),
        sa.Column("current", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["ask_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ask_turns_session_id", "ask_turns", ["session_id"])
    op.create_table(
        "ask_attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("data", sa.LargeBinary(), nullable=True),
        sa.Column("meta", JSONType, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["ask_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ask_attachments_session_id", "ask_attachments", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_ask_attachments_session_id", table_name="ask_attachments")
    op.drop_table("ask_attachments")
    op.drop_index("ix_ask_turns_session_id", table_name="ask_turns")
    op.drop_table("ask_turns")
    op.drop_index("ix_ask_sessions_user_id", table_name="ask_sessions")
    op.drop_index("ix_ask_sessions_project_id", table_name="ask_sessions")
    op.drop_table("ask_sessions")
