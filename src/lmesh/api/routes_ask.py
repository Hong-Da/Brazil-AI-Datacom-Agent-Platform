"""图查询、AI 自然语言查询与配置护栏接口（M5-5）。都需要令牌。

不需要 AI：GET /ask/status、POST /query（执行受限的图查询）、POST /guard（配置护栏）。
需要 AI：POST /ask、POST /generate；未配置 AI 时返回 409，data.status 为 not_configured（核心功能不受影响）。
发给 AI 的内容一律先脱敏，实际发送的内容在 data.sent 中返回。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from lmesh.api.common import (
    E_EXTERNAL,
    E_NOT_FOUND,
    E_PARAM,
    E_STATE,
    ApiError,
    lang_of,
    ok,
    require_token,
    settings_of,
)
from lmesh.api.routes_export import load_devices, targets_of
from lmesh.api.routes_topology import ConfigText
from lmesh.core import analysis, ask, gquery, guard, history, importer, kbservice, store, template
from lmesh.core.kb import KnowledgeBase

router = APIRouter(dependencies=[Depends(require_token)])


def _kb(request: Request) -> tuple[KnowledgeBase, Any]:
    root = kbservice.runtime_root(settings_of(request))
    return analysis.load_kb(root), root


def _ask_error(e: ask.AskError) -> ApiError:
    if e.kind == "state":
        return ApiError(E_STATE, 409, e.key, data=e.data, **e.fmt)
    if e.kind == "not_found":
        return ApiError(E_NOT_FOUND, 404, e.key, data=e.data, **e.fmt)
    if e.kind == "external":
        return ApiError(E_EXTERNAL, 502, e.key, data=e.data, **e.fmt)
    return ApiError(E_PARAM, 422, e.key, data=e.data, **e.fmt)


@router.get("/ask/status", summary="AI 查询与生成是否可用（未配置 AI 时界面隐藏入口）；配置护栏与图查询不需要 AI")
def get_status(request: Request) -> dict[str, Any]:
    return ok(request, {**ask.status(settings_of(request)), "grammar": gquery.grammar()})


class QueryBody(BaseModel):
    query: str | dict[str, Any] = Field(..., description="查询文本（FIND … ON … WHERE … RETURN …）或等价的 JSON")
    devices: list[str | int] | str | None = Field(
        None, description='设备名或编号，"all" 为全部；configs 为空且不给时取全部'
    )
    configs: list[ConfigText] = Field(default_factory=list, max_length=200)


@router.post("/query", summary="执行图查询（受限的只读查询语言，不需要 AI）：每行带设备、节点与配置行号，每格带来源")
def post_query(request: Request, body: QueryBody) -> dict[str, Any]:
    kb, _ = _kb(request)
    devices = load_devices(request, kb, body.configs, targets_of(body.configs, body.devices))
    try:
        return ok(request, gquery.execute(body.query, devices, kb))
    except gquery.QueryError as e:
        raise ApiError(E_PARAM, 422, e.key, **e.fmt) from e


class AskBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    devices: list[str | int] | str | None = Field(None, description="查询范围（设备名或编号）；不给时为全部已导入设备")
    lang: Literal["zh-CN", "en", "pt-BR"] | None = Field(None, description="回答语言；不填时按请求的语言")


@router.post(
    "/ask",
    summary="AI 自然语言查询：AI 写图查询 → 代码执行 → AI 组织回答 → 代码逐句核对（通过 / 被更正 / 无法校验）；需要配置 AI",
)
def post_ask(request: Request, body: AskBody) -> dict[str, Any]:
    settings = settings_of(request)
    if not ask.status(settings)["configured"]:
        raise ApiError(E_STATE, 409, "ai.not_configured", data={"status": "not_configured", "configured": False})
    kb, _ = _kb(request)
    devices = load_devices(request, kb, [], targets_of([], body.devices))
    try:
        return ok(request, ask.ask(body.question, devices, kb, settings, body.lang or lang_of(request)))
    except ask.AskError as e:
        raise _ask_error(e) from e


class GuardBody(BaseModel):
    """目标：device（已导入设备的名称或编号，取最新快照为当前配置）或 base_text（当前配置）；都不给时按空配置校验，需要 profile。"""

    text: str = Field(..., min_length=1, max_length=importer.MAX_BYTES, description="要校验的配置片段")
    device: str | int | None = Field(None, description="目标设备（名称或编号）")
    base_text: str | None = Field(None, max_length=importer.MAX_BYTES, description="当前配置（不用已导入设备时）")
    profile: str | None = Field(None, description="Profile（默认按目标设备）")
    template: str | None = Field(None, description="按这个模板检查约束（模板编号）")
    cross_device: bool = Field(True, description="与其他已导入设备查重（地址、RD）")
    script: bool = Field(True, description="通过后附上增量变更脚本")
    merged: bool = Field(False, description="同时返回合并后的完整配置 merged_text（界面交给增量变更时用）")
    lang: Literal["zh-CN", "en", "pt-BR"] | None = None


def _target(request: Request, kb: KnowledgeBase, device: str | int | None, base_text: str | None, cross: bool):
    """(当前配置原文, 设备名, Profile, 其他设备)。"""
    if device is None:
        return base_text, "device", None, []
    db = settings_of(request).database_url
    store.upgrade(db)
    hit = history.latest_text(db, str(device))
    if hit is None:
        raise ApiError(E_NOT_FOUND, 404, "graph.target_not_found", target=str(device))
    _, name, profile, text = hit
    others = []
    if cross:
        found, _ = history.devices_from_db(db, kb, None)
        others = [d for d in found if d.name != name]
    return text, name, profile or None, others


def _template(root: Any, kb: KnowledgeBase, ref: str | None) -> Any:
    if not ref:
        return None
    try:
        return template.load(root, ref, kb)
    except template.TemplateError as e:
        code = E_NOT_FOUND if e.kind == "not_found" else E_PARAM
        raise ApiError(code, 404 if e.kind == "not_found" else 422, e.key, **e.fmt) from e


@router.post(
    "/guard",
    summary="配置护栏（不需要 AI）：解析、入图（合并到目标设备当前配置）、依赖、模板、冲突检查，逐行标出通过 / 拦截 / 注意与原因",
)
def post_guard(request: Request, body: GuardBody) -> dict[str, Any]:
    kb, root = _kb(request)
    base, name, profile, others = _target(request, kb, body.device, body.base_text, body.cross_device)
    try:
        r = guard.guard(
            body.text,
            kb,
            body.profile or profile,
            base,
            name,
            others,
            _template(root, kb, body.template),
            body.lang or lang_of(request),
            body.script,
        )
    except guard.GuardError as e:
        raise ApiError(E_PARAM, 422, e.key, **e.fmt) from e
    if not body.merged:
        r.pop("merged_text", None)
    return ok(request, r)


class GenerateBody(BaseModel):
    request: str = Field(..., min_length=1, max_length=4000, description="用自然语言描述要做的配置")
    device: str | int = Field(..., description="目标设备（名称或编号）")
    profile: str | None = None
    template: str | None = Field(None, description="按这个模板检查约束（模板编号）")
    rounds: int = Field(2, ge=1, le=5, description="最多几轮（被拦截时把问题交回 AI 修改）")
    merged: bool = Field(False, description="最后一轮附上合并后的完整配置 merged_text（界面交给增量变更时用）")
    lang: Literal["zh-CN", "en", "pt-BR"] | None = None


@router.post(
    "/generate",
    summary="AI 生成配置：生成后经护栏检查（解析、入图、依赖、模板、冲突），被拦截时交回 AI 修改；需要配置 AI",
)
def post_generate(request: Request, body: GenerateBody) -> dict[str, Any]:
    settings = settings_of(request)
    if not ask.status(settings)["configured"]:
        raise ApiError(E_STATE, 409, "ai.not_configured", data={"status": "not_configured", "configured": False})
    kb, root = _kb(request)
    base, name, profile, others = _target(request, kb, body.device, None, True)
    try:
        r = ask.generate(
            body.request,
            kb,
            settings,
            base,
            name,
            body.profile or profile,
            others,
            _template(root, kb, body.template),
            body.lang or lang_of(request),
            body.rounds,
        )
    except ask.AskError as e:
        raise _ask_error(e) from e
    for rd in r["rounds"]:
        if not (body.merged and rd is r["final"]):
            rd["guard"].pop("merged_text", None)
    return ok(request, r)
