"""耗时任务：在后台线程中运行，进度与结果写入 tasks 表，API 通过 GET /tasks/{id} 轮询。"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from typing import Any

from lmesh.core import store
from lmesh.core.store.models import Task

_log = logging.getLogger("lmesh.tasks")
Progress = Callable[[int, str], None]


def _update(db_url: str, task_id: str, **fields: Any) -> None:
    with store.session(db_url) as s:
        t = s.get(Task, task_id)
        if t is not None:
            for k, v in fields.items():
                setattr(t, k, v)


def submit(db_url: str, kind: str, fn: Callable[[Progress], dict[str, Any]], wait: bool = False) -> str:
    """提交任务；wait=True 时在当前线程执行（测试与 CLI 用）。"""
    task_id = uuid.uuid4().hex[:16]
    with store.session(db_url) as s:
        s.add(Task(id=task_id, kind=kind, status="queued", progress=0))

    def progress(pct: int, message: str) -> None:
        _update(db_url, task_id, progress=max(0, min(100, pct)), message=message)

    def run() -> None:
        _update(db_url, task_id, status="running")
        try:
            result = fn(progress)
            _update(db_url, task_id, status="done", progress=100, result=result)
        except Exception as e:  # 任务失败写进结果，不让线程静默退出
            _log.exception("任务 %s（%s）失败", task_id, kind)
            _update(db_url, task_id, status="failed", message=f"{type(e).__name__}: {e}")

    if wait:
        run()
    else:
        threading.Thread(target=run, name=f"task-{kind}-{task_id}", daemon=True).start()
    return task_id


def get(db_url: str, task_id: str) -> dict[str, Any] | None:
    with store.session(db_url) as s:
        t = s.get(Task, task_id)
        if t is None:
            return None
        return {
            "id": t.id,
            "kind": t.kind,
            "status": t.status,
            "progress": t.progress,
            "message": t.message,
            "result": t.result,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
