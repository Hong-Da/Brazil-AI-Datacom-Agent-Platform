"""参数化模板接口（M3-4 / M3-5）：模板列表与编辑、按模板校验与提取变量、制作模板草稿、批量生成。都需要令牌。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from lmesh.api.common import (
    E_FORBIDDEN,
    E_NOT_FOUND,
    E_PARAM,
    E_STATE,
    ApiError,
    db_of,
    ok,
    project_error,
    require_token,
    settings_of,
)
from lmesh.api.routes_translate_rules import RulesRef, resolve_rules
from lmesh.core import (
    analysis,
    assets,
    graphstore,
    importer,
    kbservice,
    projects,
    store,
    template_draft,
    template_gen,
    template_match,
)
from lmesh.core import graph as graphmod
from lmesh.core import template as tmod
from lmesh.core.kb import KnowledgeBase

router = APIRouter(dependencies=[Depends(require_token)])
MAX_TEMPLATE = 512 * 1024


def _kb(request: Request) -> tuple[KnowledgeBase, Any]:
    root = kbservice.runtime_root(settings_of(request))
    return analysis.load_kb(root), root


def _error(e: tmod.TemplateError) -> ApiError:
    if e.kind == "not_found":
        return ApiError(E_NOT_FOUND, 404, e.key, **e.fmt)
    if e.kind == "invalid":
        return ApiError(E_STATE, 409, "template.invalid", data={"issues": e.issues}, n=len(e.issues))
    return ApiError(E_PARAM, 422, e.key, **e.fmt)


class TemplateRef(BaseModel):
    """模板：template_id（知识库中的模板）或 template（模板文件内容，YAML）二选一。"""

    template_id: str | None = Field(None, max_length=80)
    template: str | None = Field(None, max_length=MAX_TEMPLATE, description="模板文件内容（YAML），不保存")


def _ident(request: Request) -> projects.Identity:
    return request.state.principal.identity()  # type: ignore[no-any-return]


def _access(request: Request, root: Any, template_id: str, write: bool = False) -> str:
    """模板的归属：shared 共享（知识库）/ mine 我的 / user 别人的私有模板（管理员）；无权查看时 404，无权修改时 403。"""
    f = tmod.find_file(root, template_id)
    if f is None:
        raise ApiError(E_NOT_FOUND, 404, "template.not_found", id=template_id)
    db = db_of(request)
    ident = _ident(request)
    try:
        if not tmod.is_private_file(f):
            if write and not ident.is_kb_editor:
                raise ApiError(E_FORBIDDEN, 403, "assets.shared_readonly", id=template_id)
            return "shared"
        if write:
            return assets.ensure_writable(db, "template", template_id, False, ident)
        return assets.ensure_readable(db, "template", template_id, False, ident)
    except projects.ProjectError as e:
        raise project_error(e) from e


def _template(request: Request, body: TemplateRef) -> tuple[tmod.Template, KnowledgeBase]:
    kb, root = _kb(request)
    try:
        if body.template:
            return tmod.parse(body.template, kb), kb
        if body.template_id:
            _access(request, root, body.template_id)
            return tmod.load(root, body.template_id, kb), kb
    except tmod.TemplateError as e:
        raise _error(e) from e
    raise ApiError(E_PARAM, 422, "template.need_template")


class TargetBody(TemplateRef):
    """配置来源：text（配置文本）、version_id（配置版本）或 device_id（设备的最新版本）之一。"""

    text: str | None = Field(None, max_length=importer.MAX_BYTES)
    device_id: int | None = None
    version_id: int | None = None
    profile: str | None = None
    label: str | None = Field(None, max_length=120, description="结果中的设备名（配置文本时使用）")
    extra: Literal["allow", "deny"] | None = Field(None, description="覆盖模板的 match.extra")
    extra_scope: Literal["none", "matched", "domains"] | None = Field(None, description="覆盖模板的 match.extra_scope")


def _target_graph(request: Request, kb: KnowledgeBase, body: TargetBody) -> tuple[Any, str]:
    if body.text:
        try:
            res = analysis.parse_text(body.text, kb, body.profile)
        except analysis.AnalysisError as e:
            raise ApiError(E_PARAM, 422, str(e), profile=body.profile or "") from e
        label = body.label or "config"
        return graphmod.build(res.parsed, kb, res.profile, label), label
    db = settings_of(request).database_url
    store.upgrade(db)
    version_id = body.version_id
    if version_id is None and body.device_id is not None:
        ver = graphstore.latest_version(db, body.device_id)
        if ver is None:
            raise ApiError(E_NOT_FOUND, 404, "compare.device_not_found", target=str(body.device_id))
        version_id = ver.id
    if version_id is None:
        raise ApiError(E_PARAM, 422, "template.need_source")
    try:
        g, ver, _ = graphstore.build_for_version(db, version_id, kb)
    except KeyError as e:
        raise ApiError(E_NOT_FOUND, 404, "compare.version_not_found", version=version_id) from e
    return g, str(g.graph.get("device") or version_id)


@router.get(
    "/templates",
    summary="模板列表：共享模板（运行时知识库 templates/）与我的模板（scope：shared / mine / user）；有问题的模板附问题清单",
)
def list_templates(request: Request) -> dict[str, Any]:
    kb, root = _kb(request)
    db, ident = db_of(request), _ident(request)
    owners = assets.owners(db, "template")
    out = []
    for row in tmod.list_templates(root, kb):
        if row.get("private"):
            sc = assets.scope_of(db, "template", str(row["id"]), False, ident)
            if sc == "hidden":
                continue
            own = owners.get(str(row["id"]))
            row.update(scope=sc, owner=own[1] if own else None, editable=True)
        else:
            row.update(scope="shared", owner=None, editable=ident.is_kb_editor)
        out.append(row)
    return ok(request, {"templates": out})


@router.get("/templates/{template_id}", summary="一个模板：元数据、变量、块、正文与模板文件原文、归属")
def get_template(request: Request, template_id: str) -> dict[str, Any]:
    kb, root = _kb(request)
    sc = _access(request, root, template_id)
    try:
        t = tmod.load(root, template_id, kb)
    except tmod.TemplateError as e:
        raise _error(e) from e
    editable = sc in ("mine", "user") or _ident(request).is_kb_editor
    return ok(request, t.info(kb) | {"body": t.body, "source": t.source, "scope": sc, "editable": editable})


class SaveBody(BaseModel):
    source: str = Field(..., max_length=MAX_TEMPLATE, description="模板文件内容（YAML），id 必须与路径中的编号一致")
    shared: bool = Field(
        False, description="新建为共享模板（只限管理员与知识库维护员）；默认新建为我的模板（data/user-templates/）"
    )


@router.put(
    "/templates/{template_id}",
    summary="新建或修改模板：共享模板写入运行时知识库并提交（管理员与维护员）；我的模板写入 data/user-templates/",
)
def put_template(request: Request, template_id: str, body: SaveBody) -> dict[str, Any]:
    kb, root = _kb(request)
    ident = _ident(request)
    exists = tmod.find_file(root, template_id) is not None
    sc = _access(request, root, template_id, write=True) if exists else None
    private = sc in ("mine", "user") or (sc is None and not body.shared and ident.user_id is not None)
    if sc is None and not private and not ident.is_kb_editor:
        raise ApiError(E_FORBIDDEN, 403, "assets.shared_readonly", id=template_id)
    try:
        if private:
            t = tmod.save_private(template_id, body.source, kb)
            if sc is None and ident.user_id is not None:
                assets.claim(db_of(request), "template", template_id, ident.user_id)
        else:
            t = tmod.save(root, template_id, body.source, kb)
    except tmod.TemplateError as e:
        raise _error(e) from e
    return ok(request, t.info(kb) | {"body": t.body, "scope": (sc or "mine") if private else "shared"})


@router.delete("/templates/{template_id}", summary="删除我的模板（共享模板不能在这里删除，403）")
def delete_template(request: Request, template_id: str) -> dict[str, Any]:
    _, root = _kb(request)
    sc = _access(request, root, template_id, write=True)
    if sc not in ("mine", "user"):
        raise ApiError(E_FORBIDDEN, 403, "assets.shared_readonly", id=template_id)
    tmod.delete_private(template_id)
    assets.release(db_of(request), "template", template_id)
    return ok(request, {"id": template_id, "deleted": True})


class CopyBody(BaseModel):
    new_id: str = Field(..., max_length=80, description="新模板编号（全站唯一）")


@router.post("/templates/{template_id}/copy", summary="复制为我的模板（共享模板或自己能看到的模板）")
def copy_template(request: Request, template_id: str, body: CopyBody) -> dict[str, Any]:
    kb, root = _kb(request)
    ident = _ident(request)
    if ident.user_id is None:
        raise ApiError(E_STATE, 409, "tokens.need_account")
    _access(request, root, template_id)
    if tmod.find_file(root, body.new_id) is not None:
        raise ApiError(E_STATE, 409, "template.exists", id=body.new_id)
    try:
        t = tmod.copy_private(root, template_id, body.new_id, kb)
    except tmod.TemplateError as e:
        raise _error(e) from e
    assets.claim(db_of(request), "template", body.new_id, ident.user_id)
    return ok(request, t.info(kb) | {"scope": "mine"})


@router.post(
    "/templates/check", summary="按模板校验配置：符合 / 逐项原因（缺少、取值不符、违反约束、模板外的配置）与变量"
)
def check(request: Request, body: TargetBody) -> dict[str, Any]:
    t, kb = _template(request, body)
    g, label = _target_graph(request, kb, body)
    try:
        return ok(request, template_match.check(t, g, kb, label, body.extra, body.extra_scope))
    except tmod.TemplateError as e:
        raise _error(e) from e


@router.post("/templates/extract", summary="按模板提取变量：变量表、块实例、可直接用于生成的一行参数")
def extract(request: Request, body: TargetBody) -> dict[str, Any]:
    t, kb = _template(request, body)
    g, label = _target_graph(request, kb, body)
    try:
        return ok(request, template_match.extract_view(template_match.check(t, g, kb, label)))
    except tmod.TemplateError as e:
        raise _error(e) from e


class DraftConfig(BaseModel):
    label: str = Field(..., max_length=120)
    text: str = Field(..., max_length=importer.MAX_BYTES)


class DraftBody(BaseModel):
    configs: list[DraftConfig] = Field(..., min_length=1, max_length=template_draft.MAX_CONFIGS)
    template_id: str = Field("draft", max_length=80)
    title: str | None = Field(None, max_length=200)
    profile: str | None = None


@router.post("/templates/draft", summary="从一份或几份同角色设备的配置生成模板草稿（候选变量、类型、参数表、自检）")
def draft(request: Request, body: DraftBody) -> dict[str, Any]:
    kb, _ = _kb(request)
    try:
        d = template_draft.draft(
            [(c.label, c.text) for c in body.configs], kb, body.profile, body.template_id, body.title
        )
    except tmod.TemplateError as e:
        raise _error(e) from e
    return ok(request, d)


class GenerateBody(TemplateRef, RulesRef):
    """rule_set / rules：翻译自定义规则（REQ-032），只用于 engine=canon。"""

    rows: list[dict[str, Any]] | None = Field(None, max_length=2000, description="参数行（JSON）")
    csv: str | None = Field(None, max_length=importer.MAX_BYTES, description="参数表（CSV 文本）")
    engine: Literal["text", "canon"] = "text"
    target_profile: str | None = None
    verify: bool = True
    include_text: bool = Field(True, description="结果中带生成的配置文本")


@router.post("/templates/generate", summary="模板 + 参数表批量生成配置；每行解析、往返并按模板校验，失败的行给出原因")
def generate(request: Request, body: GenerateBody) -> dict[str, Any]:
    t, kb = _template(request, body)
    try:
        if body.rows is not None:
            rows = body.rows
        elif body.csv is not None:
            rows = template_gen.parse_params(body.csv, "csv")
        else:
            raise tmod.TemplateError("template.params_empty")
        rules = resolve_rules(request, body, kb)
        r = template_gen.generate(t, rows, kb, body.engine, body.target_profile, body.verify, rules)
    except tmod.TemplateError as e:
        raise _error(e) from e
    if not body.include_text:
        for row in r["rows"]:
            row["text"] = None
    return ok(request, r)
