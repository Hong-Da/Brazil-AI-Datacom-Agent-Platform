"""未支持型号的处理（M8-7，REQ-044）：导入前识别、设备更换 Profile、型号规则、申请支持、派生 Profile 与改指向。

- POST /configs/inspect：导入前识别（不入库）：匹配程度、会用的 Profile、候选的试解析结果、“记住”预填的规则
- GET /devices/{id}/profile-candidates；PUT /devices/{id}/profile：更换 Profile 并重新解析（profile 为空改回自动）
- POST /devices/{id}/support-request：申请支持此型号（进审核队列，类型 suggestion，payload.kind = model）
- GET|POST /model-rules、POST /model-rules/test、PUT|DELETE /model-rules/{id}：型号规则（本项目与全局；全局只限维护员与管理员）
- GET /kb/model-support/{item}、POST …/derive、POST …/retarget：维护员处理型号支持申请
"""

from __future__ import annotations

from typing import Any, Literal, NoReturn

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, Field

from lmesh.api.common import (
    E_FORBIDDEN,
    E_NOT_FOUND,
    E_PARAM,
    E_STATE,
    ApiError,
    db_of,
    lang_of,
    ok,
    principal_of,
    require_token,
    settings_of,
)
from lmesh.core import analysis, i18n, importer, kbservice, model_support, projects

router = APIRouter(dependencies=[Depends(require_token)])


def _raise(e: model_support.ModelError) -> NoReturn:
    code = {"not_found": (E_NOT_FOUND, 404), "forbidden": (E_FORBIDDEN, 403), "state": (E_STATE, 409)}.get(
        e.kind, (E_PARAM, 422)
    )
    raise ApiError(code[0], code[1], e.key, data=e.data, **e.fmt) from e


def _root(request: Request) -> Any:
    return kbservice.runtime_root(settings_of(request))


def _kb(request: Request) -> Any:
    return analysis.load_kb(_root(request))


def _project_id(request: Request) -> int:
    return projects.target_project_id(db_of(request))


# ---------------------------------------------------------------- 导入前识别


@router.post(
    "/configs/inspect",
    summary="导入前识别（不入库）：每个文件的匹配程度、会用的 Profile、候选 Profile 的试解析结果、“记住”预填的规则",
)
async def inspect(
    request: Request, files: list[UploadFile] = File(...), level: Literal["basic", "strict"] = Form("basic")
) -> dict[str, Any]:
    sources: list[tuple[str, bytes]] = []
    for f in files:
        sources.extend(importer.iter_bytes(f.filename or "upload.txt", await f.read()))
    rows = importer.inspect_sources(sources, db_of(request), level, _root(request))
    lang = lang_of(request)
    for r in rows:
        if not r["ok"]:
            r["error"] = i18n.t(r["error"], lang)
    return ok(request, {"files": rows, "can_global": principal_of(request).is_kb_editor})


# ---------------------------------------------------------------- 设备


@router.get("/devices/{device_id}/profile-candidates", summary="更换 Profile 的候选：当前选择与试解析结果（不修改）")
def device_candidates(request: Request, device_id: int) -> dict[str, Any]:
    try:
        return ok(request, model_support.device_candidates(db_of(request), _kb(request), device_id))
    except model_support.ModelError as e:
        _raise(e)


class RememberBody(BaseModel):
    scope: Literal["project", "global"] = "project"
    name_pattern: str = Field("", max_length=200)
    version: str = Field("", max_length=200)
    feature: str = Field("", max_length=400)
    note: str = Field("", max_length=2000)


class ProfileBody(BaseModel):
    profile: str | None = Field(None, description="Profile 编号；为空（null 或空串）时改回自动选择")
    remember: RememberBody | None = Field(None, description="同时记住为型号规则")


@router.put(
    "/devices/{device_id}/profile",
    summary="更换 Profile 并重新解析最新版本（只允许同厂商 / 同平台族；之后的导入与重新解析沿用手工选择）",
)
def device_profile(request: Request, device_id: int, body: ProfileBody) -> dict[str, Any]:
    p = principal_of(request)
    try:
        return ok(
            request,
            model_support.set_device_profile(
                db_of(request),
                _root(request),
                _kb(request),
                device_id,
                body.profile or None,
                p.username,
                body.remember.model_dump() if body.remember else None,
                can_global=p.is_kb_editor,
                is_admin=p.is_admin,
            ),
        )
    except model_support.ModelError as e:
        _raise(e)


class SupportBody(BaseModel):
    model: str = Field(..., min_length=1, max_length=200, description="型号，例如 NE8000 X8")
    reason: str = Field("", max_length=4000)


@router.post(
    "/devices/{device_id}/support-request",
    summary="申请支持此型号：附设备信息与未识别行写法，进审核队列（建议），由维护员处理",
)
def support_request(request: Request, device_id: int, body: SupportBody) -> dict[str, Any]:
    sc = projects.current()
    try:
        return ok(
            request,
            model_support.request_support(
                db_of(request),
                device_id,
                principal_of(request).username,
                body.model,
                body.reason,
                sc.label if sc else None,
            ),
        )
    except model_support.ModelError as e:
        _raise(e)


# ---------------------------------------------------------------- 型号规则


class RuleBody(BaseModel):
    scope: Literal["project", "global"] = "project"
    vendor: str = Field("", max_length=40)
    name_pattern: str = Field("", max_length=200)
    version: str = Field("", max_length=200)
    feature: str = Field("", max_length=400)
    profile: str = Field(..., max_length=120)
    note: str = Field("", max_length=2000)
    enabled: bool = True
    reparse: bool = Field(False, description="保存后重新解析本项目里命中的设备（手工选择的不动）")


class RuleUpdate(BaseModel):
    vendor: str | None = Field(None, max_length=40)
    name_pattern: str | None = Field(None, max_length=200)
    version: str | None = Field(None, max_length=200)
    feature: str | None = Field(None, max_length=400)
    profile: str | None = Field(None, max_length=120)
    note: str | None = Field(None, max_length=2000)
    enabled: bool | None = None
    reparse: bool = False


class RuleTest(BaseModel):
    id: int | None = Field(None, description="正在编辑的规则（试匹配时不算作“被更早的规则抢先”）")
    vendor: str = ""
    name_pattern: str = ""
    version: str = ""
    feature: str = ""
    profile: str


@router.get("/model-rules", summary="型号规则：本项目与全局，按生效顺序（停用的排在后面），带命中设备数")
def rules_list(request: Request) -> dict[str, Any]:
    data = model_support.list_rules(db_of(request), _project_id(request))
    data["can_global"] = principal_of(request).is_kb_editor
    return ok(request, data)


def _reparse(request: Request, rule_body: dict[str, Any], rule_id: int | None) -> int:
    from lmesh.core import workbench

    db, kb = db_of(request), _kb(request)
    hits = model_support.test_rules(db, kb, _project_id(request), {**rule_body, "id": rule_id})["devices"]
    n = 0
    for h in hits:
        if h["source"] == "manual":
            continue
        from lmesh.core import graphstore

        ver = graphstore.latest_version(db, h["id"])
        if ver is not None:
            workbench.analyse_version(db, ver.id, _root(request), kb=kb)
            n += 1
    return n


@router.post(
    "/model-rules", summary="新建型号规则（scope=global 只限维护员与管理员）；reparse=true 时重新解析命中的设备"
)
def rules_create(request: Request, body: RuleBody) -> dict[str, Any]:
    p = principal_of(request)
    if body.scope == "global" and not p.is_kb_editor:
        raise ApiError(E_FORBIDDEN, 403, "api.error.kb_editor_only")
    pid = None if body.scope == "global" else _project_id(request)
    data = body.model_dump(exclude={"scope", "reparse"})
    try:
        r = model_support.create_rule(db_of(request), _kb(request), pid, data, p.username)
    except model_support.ModelError as e:
        _raise(e)
    if body.reparse:
        r["reparsed"] = _reparse(request, data, r["id"])
    return ok(request, r)


@router.post("/model-rules/test", summary="试匹配：规则条件（未保存）在本项目设备上的命中情况")
def rules_test(request: Request, body: RuleTest) -> dict[str, Any]:
    try:
        return ok(
            request, model_support.test_rules(db_of(request), _kb(request), _project_id(request), body.model_dump())
        )
    except model_support.ModelError as e:
        _raise(e)


@router.put("/model-rules/{rule_id}", summary="修改型号规则（全局规则只限维护员与管理员）")
def rules_update(request: Request, rule_id: int, body: RuleUpdate) -> dict[str, Any]:
    p = principal_of(request)
    data = body.model_dump(exclude={"reparse"}, exclude_unset=True)
    try:
        r = model_support.update_rule(db_of(request), _kb(request), rule_id, _project_id(request), data, p.is_kb_editor)
    except model_support.ModelError as e:
        _raise(e)
    if body.reparse:
        r["reparsed"] = _reparse(request, r, rule_id)
    return ok(request, r)


@router.delete(
    "/model-rules/{rule_id}", summary="删除型号规则（全局规则只限维护员与管理员）；按它选的设备下次重新解析时重新选择"
)
def rules_delete(request: Request, rule_id: int) -> dict[str, Any]:
    p = principal_of(request)
    try:
        return ok(request, model_support.delete_rule(db_of(request), rule_id, _project_id(request), p.is_kb_editor))
    except model_support.ModelError as e:
        _raise(e)


# ---------------------------------------------------------------- 维护员：型号支持申请


def _kb_editor(request: Request) -> None:
    if not principal_of(request).is_kb_editor:
        raise ApiError(E_FORBIDDEN, 403, "api.error.kb_editor_only")


@router.get(
    "/kb/model-support/{item_id}",
    summary="型号支持申请的处理状态：派生的 Profile、是否已发布、改指向的预演、基础 Profile 的试解析（维护员）",
)
def support_get(request: Request, item_id: int) -> dict[str, Any]:
    _kb_editor(request)
    try:
        return ok(request, model_support.support_status(db_of(request), _root(request), _kb(request), item_id))
    except model_support.ModelError as e:
        _raise(e)


class DeriveBody(BaseModel):
    id: str = Field(..., max_length=120, description="新 Profile 编号")
    base: str = Field(..., max_length=120, description="基础 Profile（继承它，只写差异）")
    title: str = Field("", max_length=200)
    platform: str = Field("", max_length=200)
    software: str = Field("", max_length=120)
    version: str = Field("", max_length=200, description="版本规则（正则）")


@router.post(
    "/kb/model-support/{item_id}/derive", summary="从现有 Profile 派生（继承，只写差异），记在申请上（维护员）"
)
def support_derive(request: Request, item_id: int, body: DeriveBody) -> dict[str, Any]:
    try:
        return ok(
            request,
            model_support.derive(
                db_of(request), _root(request), item_id, body.model_dump(), principal_of(request).username
            ),
        )
    except model_support.ModelError as e:
        _raise(e)


class RetargetBody(BaseModel):
    note: str = Field("", max_length=2000)


@router.post(
    "/kb/model-support/{item_id}/retarget",
    summary="型号规则改指向派生的 Profile（没有规则时新建全局规则），相关设备重新解析，申请标为通过（维护员）",
)
def support_retarget(request: Request, item_id: int, body: RetargetBody | None = None) -> dict[str, Any]:
    try:
        return ok(
            request,
            model_support.retarget(
                db_of(request),
                _root(request),
                _kb(request),
                item_id,
                principal_of(request).username,
                body.note if body else "",
            ),
        )
    except model_support.ModelError as e:
        _raise(e)
