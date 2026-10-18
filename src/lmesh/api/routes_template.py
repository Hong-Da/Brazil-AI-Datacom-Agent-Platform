"""参数化模板接口（M3-4 / M3-5）：模板列表与编辑、按模板校验与提取变量、制作模板草稿、批量生成。都需要令牌。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from lmesh.api.common import E_NOT_FOUND, E_PARAM, E_STATE, ApiError, ok, require_token, settings_of
from lmesh.core import analysis, graphstore, importer, kbservice, store, template_draft, template_gen, template_match
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


def _template(request: Request, body: TemplateRef) -> tuple[tmod.Template, KnowledgeBase]:
    kb, root = _kb(request)
    try:
        if body.template:
            return tmod.parse(body.template, kb), kb
        if body.template_id:
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


@router.get("/templates", summary="模板列表（运行时知识库 templates/；有问题的模板附问题清单）")
def list_templates(request: Request) -> dict[str, Any]:
    kb, root = _kb(request)
    return ok(request, {"templates": tmod.list_templates(root, kb)})


@router.get("/templates/{template_id}", summary="一个模板：元数据、变量、块、正文与模板文件原文")
def get_template(request: Request, template_id: str) -> dict[str, Any]:
    kb, root = _kb(request)
    try:
        t = tmod.load(root, template_id, kb)
    except tmod.TemplateError as e:
        raise _error(e) from e
    return ok(request, t.info(kb) | {"body": t.body, "source": t.source})


class SaveBody(BaseModel):
    source: str = Field(..., max_length=MAX_TEMPLATE, description="模板文件内容（YAML），id 必须与路径中的编号一致")


@router.put("/templates/{template_id}", summary="新建或修改模板：校验（含正文解析）后写入运行时知识库并提交")
def put_template(request: Request, template_id: str, body: SaveBody) -> dict[str, Any]:
    kb, root = _kb(request)
    try:
        t = tmod.save(root, template_id, body.source, kb)
    except tmod.TemplateError as e:
        raise _error(e) from e
    return ok(request, t.info(kb) | {"body": t.body})


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


class GenerateBody(TemplateRef):
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
        r = template_gen.generate(t, rows, kb, body.engine, body.target_profile, body.verify)
    except tmod.TemplateError as e:
        raise _error(e) from e
    if not body.include_text:
        for row in r["rows"]:
            row["text"] = None
    return ok(request, r)
