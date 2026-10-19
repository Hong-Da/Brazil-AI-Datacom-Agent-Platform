"""数据库访问：引擎、会话、迁移。"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from lmesh import paths

MIGRATIONS = Path(__file__).resolve().parent / "migrations"

_engines: dict[str, Engine] = {}


def get_engine(url: str) -> Engine:
    if url not in _engines:
        if url.startswith("sqlite"):
            paths.data_dir().mkdir(parents=True, exist_ok=True)
            eng = create_engine(url, connect_args={"check_same_thread": False})

            @event.listens_for(eng, "connect")
            def _fk_on(dbapi_conn, _rec):  # type: ignore[no-untyped-def]
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA journal_mode=WAL")
                cur.close()
        else:
            eng = create_engine(url, pool_pre_ping=True)
        _engines[url] = eng
    return _engines[url]


def dispose_all() -> None:
    for e in _engines.values():
        e.dispose()
    _engines.clear()
    _UPGRADED.clear()


def _alembic_config(url: str):  # type: ignore[no-untyped-def]
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


_UPGRADED: set[str] = set()
_UPGRADE_LOCK = threading.Lock()


def upgrade(url: str) -> None:
    """把数据库升级到最新结构（幂等）；同一进程内每个地址只做一次，并发请求时串行。"""
    from alembic import command

    with _UPGRADE_LOCK:
        if url in _UPGRADED:
            return
        cfg = _alembic_config(url)
        sqlite = url.startswith("sqlite")
        with get_engine(url).connect() as conn:
            if sqlite:
                # 迁移中重建表（batch）时必须关闭外键：SQLite 删除被引用的旧表会按 ON DELETE CASCADE 删掉子表数据。
                # PRAGMA 在事务内无效，所以在开始事务前设置，结束后恢复。
                conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
                conn.commit()
            try:
                with conn.begin():
                    cfg.attributes["connection"] = conn
                    command.upgrade(cfg, "head")
            finally:
                if sqlite:
                    conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                    conn.commit()
        _UPGRADED.add(url)


def table_names(url: str) -> list[str]:
    return sorted(inspect(get_engine(url)).get_table_names())


@contextmanager
def session(url: str) -> Iterator[Session]:
    factory = sessionmaker(bind=get_engine(url), expire_on_commit=False)
    s = factory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def backend_name(url: str) -> str:
    return "postgresql" if url.startswith("postgresql") else "sqlite"
