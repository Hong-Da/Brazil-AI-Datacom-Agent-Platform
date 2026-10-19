"""耗时任务：在后台线程中运行，进度与结果写入 tasks 表，API 通过 GET /tasks/{id} 轮询。"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from typing import Any

from lmesh.core import store
from lmesh.core.store.models import Task, iso

_log = logging.getLogger("lmesh.tasks")
Progress = Callable[[int, str], None]


def _update(db_url: str, task_id: str, **fields: Any) -> None:
    with store.session(db_url) as s:
        t = s.get(Task, task_id)
        if t is not None:
            for k, v in fields.items():
                setattr(t, k, v)


def submit(
    db_url: str, kind: str, fn: Callable[[Progress], dict[str, Any]], wait: bool = False, created_by: str | None = None
) -> str:
    """提交任务；wait=True 时在当前线程执行（测试与 CLI 用）。created_by：发起人，不给时取当前请求的调用者
    （REQ-040：任务里调用 AI 时按发起人的选择——由提交时绑定了发起人的 settings 决定，这里只做记录）。"""
    task_id = uuid.uuid4().hex[:16]
    if created_by is None:
        from lmesh.core import projects

        who = projects.identity()
        created_by = who.username if who is not None else ""
    with store.session(db_url) as s:
        s.add(Task(id=task_id, kind=kind, status="queued", progress=0, created_by=created_by))

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
            "created_by": t.created_by,
            "created_at": iso(t.created_at),
            "updated_at": iso(t.updated_at),
        }


def recent(db_url: str, kind: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    from sqlalchemy import select

    with store.session(db_url) as s:
        q = select(Task.id).order_by(Task.created_at.desc()).limit(limit)
        if kind:
            q = q.where(Task.kind == kind)
        ids = list(s.scalars(q))
    return [t for t in (get(db_url, i) for i in ids) if t]
