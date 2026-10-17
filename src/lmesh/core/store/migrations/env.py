"""Alembic 环境：连接由 lmesh.core.store.upgrade 传入，也支持命令行（sqlalchemy.url）。"""

from alembic import context
from sqlalchemy import engine_from_config, pool

from lmesh.core.store.models import Base

config = context.config
target_metadata = Base.metadata


def run() -> None:
    conn = config.attributes.get("connection")
    if conn is not None:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = engine_from_config(
        config.get_section(config.config_ini_section) or {}, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


run()
