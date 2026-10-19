"""项目标识按属主唯一（M6 评审改选）、用户自助注册（REQ-039）

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-19 20:00:00

- projects：唯一约束从 slug 改为 (owner_id, slug)（用户 2026-10-19 评审改选“每个属主内唯一”）；属主为空的项目
  （没有账号时迁移出的默认项目）另有部分唯一索引：属主为空的项目之间标识也不能重复。数据不用改：0007 生成的标识
  全站唯一，自然也按属主唯一。
- users：增加 status（active 正常 / pending 待审核）与 origin（admin 管理员建 / register 自助注册），已有账号为
  active / admin。
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    with op.batch_alter_table("projects", recreate="always" if sqlite else "auto") as b:
        b.drop_constraint("uq_projects_slug", type_="unique")
        b.create_unique_constraint("uq_projects_owner_slug", ["owner_id", "slug"])
    op.create_index(
        "uq_projects_ownerless_slug",
        "projects",
        ["slug"],
        unique=True,
        sqlite_where=sa.text("owner_id IS NULL"),
        postgresql_where=sa.text("owner_id IS NULL"),
    )
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("status", sa.String(length=16), nullable=False, server_default="active"))
        b.add_column(sa.Column("origin", sa.String(length=16), nullable=False, server_default="admin"))


def downgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    op.execute("DELETE FROM users WHERE status = 'pending'")
    with op.batch_alter_table("users") as b:
        b.drop_column("origin")
        b.drop_column("status")
    op.drop_index("uq_projects_ownerless_slug", table_name="projects")
    # 降级回全站唯一：不同属主的同名项目改名（加编号）后才能建回原约束
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, slug FROM projects ORDER BY id")).all()
    taken = {r[1] for r in rows}
    seen: set[str] = set()
    for pid, slug in rows:
        cand, n = slug, 2
        while cand in seen or (cand != slug and cand in taken):
            cand, n = f"{slug}-{n}", n + 1
        seen.add(cand)
        if cand != slug:
            bind.execute(sa.text("UPDATE projects SET slug = :s WHERE id = :i"), {"s": cand, "i": pid})
    with op.batch_alter_table("projects", recreate="always" if sqlite else "auto") as b:
        b.drop_constraint("uq_projects_owner_slug", type_="unique")
        b.create_unique_constraint("uq_projects_slug", ["slug"])
