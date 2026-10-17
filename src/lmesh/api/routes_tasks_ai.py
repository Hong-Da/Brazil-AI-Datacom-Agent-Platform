"""耗时任务、文档导入、批量审核、AI 接口。都需要令牌。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from lmesh.api.common import E_EXTERNAL, E_NOT_FOUND, E_PARAM, E_STATE, ApiError, ok, require_token, settings_of
from lmesh.core import ai, kbservice, store, tasks

router = APIRouter(dependencies=[Depends(require_token)])


def _db(request: Request) -> str:
    url = settings_of(request).database_url
    store.upgrade(url)
    return url


@router.get("/tasks/{task_id}", summary="耗时任务的状态、进度与结果")
def task_get(request: Request, task_id: str) -> dict[str, Any]:
    t = tasks.get(_db(request), task_id)
    if not t:
        raise ApiError(E_NOT_FOUND, 404)
    return ok(request, t)


class IngestBody(BaseModel):
    doc_dir: str  # 服务器上的文档目录或文件
    rules: str
    domains: list[str] | None = None
    version: str = ""
    use_ai: bool = False


@router.post("/kb/ingest", summary="导入产品文档并抽取命令卡（后台任务，返回任务编号）")
def kb_ingest(request: Request, body: IngestBody) -> dict[str, Any]:
    from lmesh.core.ingest.service import find_rules, ingest

    settings = settings_of(request)
    doc = Path(body.doc_dir)
    if not doc.exists():
        raise ApiError(E_NOT_FOUND, 404, data={"doc_dir": body.doc_dir})
    root = kbservice.runtime_root(settings)
    try:
        find_rules(root, body.rules)
    except FileNotFoundError as e:
        raise ApiError(E_PARAM, 422, "ingest.rules_not_found", rules=body.rules) from e
    if body.use_ai and not ai.is_configured(settings):
        raise ApiError(E_STATE, 409, "ai.not_configured")
    db = _db(request)
    task_id = tasks.submit(
        db,
        "ingest",
        lambda progress: ingest(doc, body.rules, root, db, settings, body.domains, body.version, body.use_ai, progress),
    )
    return ok(request, {"task_id": task_id})


class BatchBody(BaseModel):
    kind: str = "card"
    contains: str | None = None
    rules: str | None = None


@router.post("/review/batch", summary="批量通过（按类型、标题关键字、抽取规则筛选）")
def review_batch(request: Request, body: BatchBody) -> dict[str, Any]:
    from lmesh.core.ingest.service import approve_matching

    return ok(
        request,
        approve_matching(
            _db(request), kbservice.runtime_root(settings_of(request)), body.kind, body.contains, body.rules
        ),
    )


@router.get("/ai/status", summary="AI 是否已配置、各任务使用的模型")
def ai_status(request: Request) -> dict[str, Any]:
    s = settings_of(request)
    return ok(
        request,
        {
            "configured": ai.is_configured(s),
            "provider": s.get("ai.provider"),
            "models": {t: ai.model_for(s, t) for t in ("default", *ai.TASK_MODEL_KEYS)},
        },
    )


@router.post("/ai/test", summary="测试 AI 接口是否可用")
def ai_test(request: Request) -> dict[str, Any]:
    s = settings_of(request)
    if not ai.is_configured(s):
        raise ApiError(E_STATE, 409, "ai.not_configured")
    _db(request)
    try:
        return ok(request, ai.test(s))
    except ai.AIError as e:
        raise ApiError(E_EXTERNAL, 502, str(e)) from e


@router.get("/ai/calls", summary="AI 调用记录")
def ai_calls(request: Request, limit: int = 100) -> dict[str, Any]:
    return ok(request, {"calls": ai.recent_calls(_db(request), min(limit, 1000))})
