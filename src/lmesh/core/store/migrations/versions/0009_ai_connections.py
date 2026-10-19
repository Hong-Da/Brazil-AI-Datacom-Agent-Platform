"""AI 接口：公共与个人（REQ-040）

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-19 22:00:00

- ai_connections：管理员接口（owner_id 为空，可多个，public 决定普通账号能否选用）与个人接口（每个账号最多一个）；
  API Key 加密保存。管理员接口名称在管理员接口之间唯一（部分唯一索引）。
- ai_choices：账号的 AI 来源选择（auto / connection / personal / none）。
- ai_calls：加发起人（user_id、actor）、接口（connection_id、connection_name）、来源与功能（skill 编号）。
- tasks：加 created_by（后台任务的发起人）。
- app_meta：系统标记。现有 [ai] 配置不在迁移里读取（迁移只拿得到数据库），由 core.ai_connections.ensure_seeded
  在第一次用到 AI 时导入为第一个管理员接口（public = true，保持升级前所有账号都能用 AI 的行为），并写入标记 ai.seeded。
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("api_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("model", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("model_extract", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("model_merge", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("model_ask", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("model_generate", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("public", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", name="uq_ai_connections_owner"),
    )
    op.create_index(
        "uq_ai_connections_admin_name",
        "ai_connections",
        ["name"],
        unique=True,
        sqlite_where=sa.text("owner_id IS NULL"),
        postgresql_where=sa.text("owner_id IS NULL"),
    )
    op.create_table(
        "ai_choices",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("choice", sa.String(length=16), nullable=False, server_default="auto"),
        sa.Column("connection_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["ai_connections.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "app_meta",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("key"),
    )
    with op.batch_alter_table("ai_calls") as b:
        b.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("actor", sa.String(length=200), nullable=False, server_default=""))
        b.add_column(sa.Column("connection_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("connection_name", sa.String(length=64), nullable=False, server_default=""))
        b.add_column(sa.Column("source", sa.String(length=16), nullable=False, server_default=""))
        b.add_column(sa.Column("feature", sa.String(length=60), nullable=False, server_default=""))
        b.create_foreign_key("fk_ai_calls_user_id", "users", ["user_id"], ["id"], ondelete="SET NULL")
        b.create_foreign_key(
            "fk_ai_calls_connection_id", "ai_connections", ["connection_id"], ["id"], ondelete="SET NULL"
        )
        b.create_index("ix_ai_calls_user_id", ["user_id"])
        b.create_index("ix_ai_calls_connection_id", ["connection_id"])
    with op.batch_alter_table("tasks") as b:
        b.add_column(sa.Column("created_by", sa.String(length=200), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("tasks") as b:
        b.drop_column("created_by")
    with op.batch_alter_table("ai_calls") as b:
        b.drop_index("ix_ai_calls_connection_id")
        b.drop_index("ix_ai_calls_user_id")
        b.drop_constraint("fk_ai_calls_connection_id", type_="foreignkey")
        b.drop_constraint("fk_ai_calls_user_id", type_="foreignkey")
        for col in ("feature", "source", "connection_name", "connection_id", "actor", "user_id"):
            b.drop_column(col)
    op.drop_table("app_meta")
    op.drop_table("ai_choices")
    op.drop_index("uq_ai_connections_admin_name", table_name="ai_connections")
    op.drop_table("ai_connections")
