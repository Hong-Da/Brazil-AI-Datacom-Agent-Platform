"""创建项目的权限与加入项目（M9-8，REQ-050）

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-20 20:00:00

- users 加 can_create_projects（单独授权创建项目，默认否）。
- projects 加 discoverable（可被搜索，默认否）。
- project_invites：邀请链接（只存令牌的 SHA-256 与前 6 个字符、角色、是否仍需审批、有效期、撤销时间、使用次数）。
- project_join_requests：加入申请（来自搜索或需要审批的邀请链接；待审批 / 已通过 / 已拒绝 / 已撤回）。
- project_create_requests：申请创建项目的权限。
- 成员角色新增 manage（管理），列长度不变，不需要改表。
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("can_create_projects", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("projects") as b:
        b.add_column(sa.Column("discoverable", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "project_invites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=12), nullable=False, server_default=""),
        sa.Column("role", sa.String(length=10), nullable=False, server_default="read"),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("note", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_project_invites_project_id", "project_invites", ["project_id"])
    op.create_table(
        "project_join_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False, server_default="read"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("via", sa.String(length=10), nullable=False, server_default="search"),
        sa.Column("invite_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("decided_role", sa.String(length=10), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invite_id"], ["project_invites.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_join_requests_project_id", "project_join_requests", ["project_id"])
    op.create_index("ix_project_join_requests_user_id", "project_join_requests", ["user_id"])
    op.create_index("ix_project_join_requests_status", "project_join_requests", ["status"])
    op.create_table(
        "project_create_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_create_requests_user_id", "project_create_requests", ["user_id"])
    op.create_index("ix_project_create_requests_status", "project_create_requests", ["status"])


def downgrade() -> None:
    op.drop_table("project_create_requests")
    op.drop_table("project_join_requests")
    op.drop_table("project_invites")
    with op.batch_alter_table("projects") as b:
        b.drop_column("discoverable")
    with op.batch_alter_table("users") as b:
        b.drop_column("can_create_projects")
