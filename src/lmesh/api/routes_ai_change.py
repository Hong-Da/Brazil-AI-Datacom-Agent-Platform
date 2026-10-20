"""变更与割接组的 AI 结果（M8-4，REQ-041）：只挂在项目路径 /api/v1/projects/{project}/… 下，所有成员可查看。

建议的运行、采纳、撤销用通用接口（routes_ai_suggest）；这里只给由代码在采纳结果上计算的内容：
变更意图转脚本合并后的变更（脚本逐行标出 AI 改动、回滚、影响、模拟）、割接方案文档（中英双语，可导出）、
翻译结果中采纳的 AI 写法。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from lmesh.api.common import ok, require_token
from lmesh.api.routes_ai_suggest import _env, _err
from lmesh.core import ai_suggest, ai_suggest_change

router = APIRouter(dependencies=[Depends(require_token)])


@router.get(
    "/ai/change/plan",
    summary="变更意图转脚本：一次运行中已采纳的改动合并后由代码生成的脚本（逐行标出来自 AI 改动的行）、回滚、影响分析与模拟执行",
)
def change_plan(request: Request, batch_id: int = Query(..., description="intent-script 的运行编号")) -> dict[str, Any]:
    try:
        return ok(request, ai_suggest_change.intent_plan(_env(request), batch_id))
    except ai_suggest.SuggestError as e:
        raise _err(e) from e


@router.get(
    "/ai/cutover-plan/{batch_id}",
    summary="割接方案文档（预览）：代码给出的标题、步骤与命令，加上各节的 AI 文字（含待采纳的，标明状态）",
)
def cutover_doc(
    request: Request,
    batch_id: int,
    lang: Literal["zh-CN", "en"] = Query("zh-CN", description="文档语言（中英双语分别查看与导出）"),
) -> dict[str, Any]:
    try:
        return ok(request, ai_suggest_change.plan_doc(_env(request), batch_id, lang)["doc"])
    except ai_suggest.SuggestError as e:
        raise _err(e) from e


@router.get(
    "/ai/cutover-plan/{batch_id}/export",
    summary="导出割接方案（Markdown，只含已采纳的 AI 文字；命令来自代码生成的步骤）：中文版与英文版分别下载",
    response_class=Response,
)
def cutover_export(request: Request, batch_id: int, lang: Literal["zh-CN", "en"] = Query("zh-CN")) -> Response:
    try:
        md = ai_suggest_change.plan_doc(_env(request), batch_id, lang, adopted_only=True)["markdown"]
    except ai_suggest.SuggestError as e:
        raise _err(e) from e
    name = f"cutover-plan-{batch_id}-{lang}.md"
    return Response(
        content=md.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get(
    "/ai/translate-patches",
    summary="翻译未支持项：项目中已采纳的 AI 写法（同一设备、同一目标 Profile），翻译接口会把它们写进译文并标为 AI 来源",
)
def translate_patches(
    request: Request,
    device_id: int = Query(...),
    to: str = Query(..., max_length=120, description="目标 Profile"),
) -> dict[str, Any]:
    env = _env(request)
    return ok(request, {"items": ai_suggest_change.translate_patches(env.db, env.project_id, device_id, to)})
