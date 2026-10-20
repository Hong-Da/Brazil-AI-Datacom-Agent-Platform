"""个人偏好按账号保存（M9-7，REQ-047）

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-20 18:00:00

- users 加 prefs（JSON，可为空）：语言、明暗主题、显示风格、设备图标风格。为空表示账号还没保存过偏好
  （登录后网页把浏览器本地的值写入账号）。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None
JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("prefs", JSONType, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.drop_column("prefs")
