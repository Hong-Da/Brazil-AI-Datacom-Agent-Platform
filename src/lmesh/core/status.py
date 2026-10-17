"""运行状态：版本、是否已配置、数据库、知识库。CLI 的 status 与 API 的 health 共用。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from lmesh import __version__
from lmesh.core import config, store


def collect(settings: config.Settings | None = None) -> dict[str, Any]:
    settings = settings or config.load()
    url = settings.database_url
    db: dict[str, Any] = {"backend": store.backend_name(url), "ok": False}
    try:
        with store.get_engine(url).connect() as conn:
            conn.execute(text("SELECT 1"))
        db["ok"] = True
    except Exception as e:  # 数据库不可用时状态里说明，不抛出
        db["error"] = type(e).__name__
    kb_dir = settings.knowledge_dir
    return {
        "version": __version__,
        "configured": config.is_configured(),
        "database": db,
        "knowledge": {"dir": str(kb_dir), "exists": kb_dir.exists()},
        "ai": {"configured": bool(settings.get("ai.provider"))},
    }
