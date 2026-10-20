"""规范与合规、知识库构建两组 AI skill 的辅助接口（M8-5，REQ-041）：只挂在项目路径 /api/v1/projects/{project}/… 下。

- GET  /ai/kb/gate?skill=…      skill 能否在当前生效的 AI 接口上运行（脱敏复核只允许本地模型：provider 不是 local 时
                                allowed=false、reason=local_only）；界面据此在运行前就拦住。
- POST /ai/kb/extract-text      上传的规范文件（txt / md / docx）→ 文字，供“规范转规则”作为参数 text 运行。
- GET  /ai/kb/sanitize-redact   本项目的脱敏补充（采纳的脱敏复核建议，正则列表）。
运行、采纳、撤销等仍走 /ai/suggestions/…（routes_ai_suggest.py）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile

from lmesh.api.common import E_PARAM, E_STATE, ApiError, db_of, ok, require_token
from lmesh.api.routes_ai_suggest import _env, _err
from lmesh.core import ai_suggest, ai_suggest_kb

router = APIRouter(dependencies=[Depends(require_token)])
MAX_UPLOAD = 5 * 1024 * 1024


@router.get(
    "/ai/kb/gate",
    summary="skill 能否在当前生效的 AI 接口上运行：脱敏复核只允许本地模型（provider 不是 local 时 allowed 为 false）",
)
def kb_gate(request: Request, skill: str = Query(..., max_length=60)) -> dict[str, Any]:
    try:
        ai_suggest.spec_of(skill)
    except ai_suggest.SuggestError as e:
        raise _err(e) from e
    return ok(request, ai_suggest_kb.local_gate(_env(request), skill))


@router.post(
    "/ai/kb/extract-text",
    summary="上传的规范文件（txt / md / docx，5 MB 以内）→ 文字（前 60000 字），给“规范转规则”作为参数 text",
)
async def kb_extract_text(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise ApiError(E_PARAM, 422, "ai_kb.doc_too_large", n=MAX_UPLOAD // 1024 // 1024)
    try:
        return ok(request, ai_suggest_kb.extract_text(file.filename or "upload.txt", data))
    except ai_suggest.SuggestError as e:
        raise _err(e) from e


@router.get(
    "/ai/kb/sanitize-redact", summary="本项目的脱敏补充：采纳的脱敏复核建议（正则列表），导入与发给 AI 前一并替换"
)
def kb_sanitize_redact(request: Request) -> dict[str, Any]:
    env = _env(request)
    db_of(request)
    if env.project_id is None:
        raise ApiError(E_STATE, 409, "ai_suggest.need_project")
    return ok(request, {"patterns": ai_suggest_kb.project_redact(env.db, env.project_id)})
