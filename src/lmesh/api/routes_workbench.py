"""Web 界面用的接口：首页概况、设备状态与重建、Schema 与 Profile 编辑、草稿区、未识别行送审、AI 设置。都需要令牌。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from lmesh.api.common import (
    E_FORBIDDEN,
    E_NOT_FOUND,
    E_PARAM,
    E_STATE,
    ApiError,
    lang_of,
    ok,
    require_admin,
    require_token,
    settings_of,
)
from lmesh.core import analysis, config, kbservice, store, tasks, workbench
from lmesh.core.kb import edit, read_yaml, repo

router = APIRouter(dependencies=[Depends(require_token)])


def _root(request: Request):  # type: ignore[no-untyped-def]
    return kbservice.runtime_root(settings_of(request))


def _db(request: Request) -> str:
    url = settings_of(request).database_url
    store.upgrade(url)
    return url


def _edit_error(e: edit.EditError) -> ApiError:
    if e.key in ("kb.profile_unknown", "kb.node_unknown"):
        return ApiError(E_NOT_FOUND, 404, e.key, data=e.data, **e.fmt)
    if e.key == "kb.node_in_use":
        return ApiError(E_STATE, 409, e.key, data=e.data, **e.fmt)
    return ApiError(E_PARAM, 422, e.key, data=e.data, **e.fmt)


# ---------- 首页与设备 ----------


@router.get("/summary", summary="首页概况：知识库、审核队列、未识别行、设备、最近一次样本回归、AI")
def summary(request: Request) -> dict[str, Any]:
    _db(request)
    return ok(request, workbench.summary(settings_of(request)))


@router.post(
    "/devices/rebuild",
    summary="按当前知识库重新解析设备（后台任务）：项目路径下为本项目的设备（属主与可编辑成员）；旧路径为全部设备（只限管理员）",
)
def devices_rebuild(request: Request) -> dict[str, Any]:
    from lmesh.core import importer

    db, root = _db(request), _root(request)
    if getattr(request.state, "project_via", "path") == "legacy":
        if not request.state.principal.is_admin:
            raise ApiError(E_FORBIDDEN, 403)
        return ok(request, {"task_id": tasks.submit(db, "rebuild", lambda p: workbench.rebuild_all(db, root, p))})
    ids = [d["id"] for d in importer.list_devices(db)]
    return ok(request, {"task_id": tasks.submit(db, "rebuild", lambda p: workbench.rebuild_all(db, root, p, ids))})


@router.post("/devices/{device_id}/rebuild", summary="按当前知识库重新解析一台设备")
def device_rebuild(request: Request, device_id: int) -> dict[str, Any]:
    from lmesh.core import graphstore

    db = _db(request)
    ver = graphstore.latest_version(db, device_id)
    if ver is None:
        raise ApiError(E_NOT_FOUND, 404)
    return ok(request, workbench.analyse_version(db, ver.id, _root(request)))


@router.get("/regression/last", summary="最近一次样本往返回归的结果（没有跑过时为 null）")
def regression_last(request: Request) -> dict[str, Any]:
    return ok(request, workbench.last_regression())


@router.get("/tasks", summary="最近的后台任务")
def tasks_recent(request: Request, kind: str | None = None, limit: int = Query(20, le=200)) -> dict[str, Any]:
    return ok(request, {"tasks": tasks.recent(_db(request), kind, limit)})


# ---------- Schema ----------


@router.get("/kb/schema", summary="Schema：各功能域的节点与依赖规则")
def kb_schema(request: Request) -> dict[str, Any]:
    return ok(request, edit.schema_tree(analysis.load_kb(_root(request))))


class NodeBody(BaseModel):
    parent: str | None = None
    type: str
    key: list[str] | None = None
    semantic: dict[str, str] = Field(default_factory=dict)
    range: list[int] | None = None
    choices: list[str] | None = None
    ordered: bool = False
    ref: str | None = None
    deprecated: bool = False
    replaced_by: str | None = None
    status: str | None = None


@router.put("/kb/schema/nodes/{node_id}", summary="新增或修改 Schema 节点（写入后校验，出错自动撤销）")
def kb_node_put(request: Request, node_id: str, body: NodeBody) -> dict[str, Any]:
    try:
        return ok(request, edit.upsert_node(_root(request), node_id, body.model_dump()))
    except edit.EditError as e:
        raise _edit_error(e) from e


@router.get("/kb/schema/nodes/{node_id}/usage", summary="删除前检查：子节点、引用、依赖、Profile 条目、命令卡")
def kb_node_usage(request: Request, node_id: str) -> dict[str, Any]:
    kb = analysis.load_kb(_root(request))
    if node_id not in kb.nodes:
        raise ApiError(E_NOT_FOUND, 404, "kb.node_unknown", node=node_id)
    return ok(request, edit.node_usage(kb, node_id))


@router.delete("/kb/schema/nodes/{node_id}", summary="删除 Schema 节点（仍被使用时 409，data 中给出使用情况）")
def kb_node_delete(request: Request, node_id: str) -> dict[str, Any]:
    try:
        return ok(request, edit.delete_node(_root(request), node_id))
    except edit.EditError as e:
        raise _edit_error(e) from e


# ---------- Profile ----------


def _device_counts(db: str) -> dict[str, int]:
    from sqlalchemy import func, select

    from lmesh.core.store.models import Device

    with store.session(db) as s:
        rows = s.execute(select(Device.profile, func.count(Device.id)).group_by(Device.profile))
        return {str(p): int(n) for p, n in rows}


@router.get("/kb/profiles", summary="Profile 列表：继承、条目数、覆盖率、可信度分布、设备数")
def kb_profiles(request: Request) -> dict[str, Any]:
    kb = analysis.load_kb(_root(request))
    rows = edit.profile_rows(kb, _device_counts(_db(request)))
    return ok(request, {"profiles": rows, "families": sorted(kb.families)})


class ProfileBody(BaseModel):
    id: str
    title: str = ""
    family: str = ""
    vendor: str = ""
    platform: str = ""
    software: str = ""
    inherits: str | None = None
    version: str = ""


@router.post("/kb/profiles", summary="新建 Profile（可继承已有 Profile，只写差异）")
def kb_profile_create(request: Request, body: ProfileBody) -> dict[str, Any]:
    try:
        return ok(request, edit.create_profile(_root(request), body.model_dump()))
    except edit.EditError as e:
        raise _edit_error(e) from e


@router.get("/kb/profiles/{profile_id}", summary="Profile 详情：继承展开后的全部条目")
def kb_profile(request: Request, profile_id: str) -> dict[str, Any]:
    try:
        return ok(request, edit.profile_detail(analysis.load_kb(_root(request)), profile_id))
    except edit.EditError as e:
        raise _edit_error(e) from e


class EntryBody(BaseModel):
    supported: bool | None = None
    default: Any = None
    show_rule: str | None = None
    source: str | None = None
    verified: str | None = None
    note: str | None = None


@router.put(
    "/kb/profiles/{profile_id}/entries/{node_id}", summary="人工修改 Profile 条目（标记 manual，重新汇总时保留）"
)
def kb_entry_put(request: Request, profile_id: str, node_id: str, body: EntryBody) -> dict[str, Any]:
    try:
        data = body.model_dump(exclude_unset=True)
        return ok(request, edit.set_entry(_root(request), profile_id, node_id, data))
    except edit.EditError as e:
        raise _edit_error(e) from e


@router.delete("/kb/profiles/{profile_id}/entries/{node_id}", summary="删除 Profile 自己的条目")
def kb_entry_delete(request: Request, profile_id: str, node_id: str) -> dict[str, Any]:
    try:
        return ok(request, edit.clear_entry(_root(request), profile_id, node_id))
    except edit.EditError as e:
        raise _edit_error(e) from e


@router.get("/kb/profile-compare", summary="对比两个 Profile：支持情况与默认值差异")
def kb_profile_compare(request: Request, a: str, b: str) -> dict[str, Any]:
    try:
        return ok(request, edit.profile_compare(analysis.load_kb(_root(request)), a, b))
    except edit.EditError as e:
        raise _edit_error(e) from e


# ---------- 草稿区与抽取规则 ----------


@router.get("/kb/draft", summary="草稿区：上次发布以来的修改与提交")
def kb_draft(request: Request) -> dict[str, Any]:
    root = _root(request)
    has_repo = (root / ".git").exists()
    rels = repo.releases(root) if has_repo else []
    history = repo.history(root, 100) if has_repo else []
    if rels:
        base = rels[0]
        cut = next((i for i, h in enumerate(history) if base.commit.startswith(str(h.get("commit", "")))), None)
        history = history[:cut] if cut is not None else history
        changes = kbservice.diff(root, base.tag)
    else:
        changes = None
    return ok(request, {"base": rels[0].version if rels else None, "changes": changes, "commits": history})


@router.get("/kb/terms", summary="显示风格的术语表：对象的叫法与命令写法模板、属性的命令关键字（华为 / Cisco）")
def kb_terms(request: Request) -> dict[str, Any]:
    from lmesh.core import terms

    root = _root(request)
    data = terms.load(root, analysis.load_kb(root)).as_dict()
    data["default"] = str(settings_of(request).get("ui.term_style") or data["default"])
    return ok(request, data)


@router.get("/kb/extractors", summary="可用的命令卡抽取规则")
def kb_extractors(request: Request) -> dict[str, Any]:
    root = _root(request)
    out = []
    for f in sorted((root / "extractors").glob("*.yaml")):
        if f.name.endswith(".patches.yaml"):
            continue
        d = read_yaml(f) or {}
        out.append(
            {
                "name": f.stem,
                "family": d.get("family", ""),
                "title": d.get("title", ""),
                "patches": (f.parent / f"{f.stem}.patches.yaml").exists(),
            }
        )
    return ok(request, {"extractors": out})


# ---------- 未识别行 ----------


@router.get("/unknown-lines/states", summary="未识别行模式的送审状态")
def unknown_states(request: Request) -> dict[str, Any]:
    return ok(request, {"states": workbench.unknown_states(_db(request))})


class PatternsBody(BaseModel):
    patterns: list[str] = Field(..., min_length=1, max_length=500)


@router.post("/unknown-lines/review", summary="把选中的未识别行模式送入审核队列")
def unknown_review(request: Request, body: PatternsBody) -> dict[str, Any]:
    return ok(request, workbench.unknown_to_review(_db(request), body.patterns))


# ---------- AI 设置 ----------


@router.get(
    "/ai/settings", summary="AI 接口设置（API Key 只显示是否已设置；管理员）", dependencies=[Depends(require_admin)]
)
def ai_settings(request: Request) -> dict[str, Any]:
    return ok(request, workbench.ai_settings(settings_of(request)))


class AISettingsBody(BaseModel):
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False
    model: str | None = None
    model_extract: str | None = None
    model_merge: str | None = None
    timeout: int | None = None
    max_tokens: int | None = None


@router.put(
    "/ai/settings",
    summary="保存 AI 接口设置（写入配置文件，API Key 加密保存；管理员）",
    dependencies=[Depends(require_admin)],
)
def ai_settings_put(request: Request, body: AISettingsBody) -> dict[str, Any]:
    try:
        new = workbench.save_ai_settings(body.model_dump(), lang_of(request))
    except config.ConfigError as e:
        raise ApiError(E_PARAM, 422, data={"error": str(e)}) from e
    request.app.state.settings = new
    return ok(request, workbench.ai_settings(new))
