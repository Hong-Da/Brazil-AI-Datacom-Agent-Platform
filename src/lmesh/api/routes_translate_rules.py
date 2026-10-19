"""翻译自定义规则（REQ-032）：规则集的列表、读取、保存、删除、导入导出、编辑器即时匹配与试运行。都需要登录。

归属（M6，REQ-035）：账号新建的规则集是“我的规则集”，只有自己（与管理员）能看到和修改；M6 之前保存的、全局令牌
或命令行保存的没有属主，作为共享规则集，所有人可用，管理员与知识库维护员可以修改；内置规则集只读（D-0135）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from lmesh.api.common import (
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
from lmesh.core import analysis, assets, compare, importer, kbservice, migration, naming, projects, store
from lmesh.core.kb import KnowledgeBase

router = APIRouter(dependencies=[Depends(require_token)])
MAX_RULES = 256 * 1024


def _kb(request: Request) -> tuple[KnowledgeBase, Path]:
    root = kbservice.runtime_root(settings_of(request))
    return analysis.load_kb(root), root


def rules_error(e: naming.RulesError) -> ApiError:
    if e.kind == "not_found":
        return ApiError(E_NOT_FOUND, 404, e.key, **e.fmt)
    if e.kind == "invalid":
        return ApiError(E_PARAM, 422, "naming.invalid", data={"issues": e.issues}, n=len(e.issues))
    if e.kind in ("readonly", "exists"):
        return ApiError(E_STATE, 409, e.key, **e.fmt)
    return ApiError(E_PARAM, 422, e.key, **e.fmt)


class RulesRef(BaseModel):
    """规则集：rule_set（已保存的规则集编号）或 rules（规则集内容，编辑中未保存的）二选一；都不给时不用规则集。"""

    rule_set: str | None = Field(None, max_length=80, description="规则集编号（内置或我的）")
    rules: dict[str, Any] | None = Field(None, description="规则集内容（与 YAML 文件结构相同），不保存")


def _ident(request: Request) -> projects.Identity:
    return request.state.principal.identity()  # type: ignore[no-any-return]


def _access(request: Request, root: Path, rid: str, write: bool = False) -> str:
    """规则集归属：builtin / shared / mine / user（管理员看到的别人的）；无权查看 404、无权修改 403。"""
    hit = naming.find_file(root, rid)
    if hit is None:
        raise ApiError(E_NOT_FOUND, 404, "naming.not_found", id=rid)
    try:
        if write:
            return assets.ensure_writable(db_of(request), "ruleset", rid, hit[1], _ident(request))
        return assets.ensure_readable(db_of(request), "ruleset", rid, hit[1], _ident(request))
    except projects.ProjectError as e:
        if e.key == "assets.ruleset_not_found":
            raise ApiError(E_NOT_FOUND, 404, "naming.not_found", id=rid) from e
        raise project_error(e) from e


def resolve_rules(request: Request, ref: RulesRef, kb: KnowledgeBase) -> naming.RuleSet | None:
    """翻译、割接迁移、批量生成共用：取请求里的规则集（别人的私有规则集按不存在处理）。"""
    try:
        if ref.rules is not None:
            return naming.parse({"id": "unsaved", **ref.rules}, kb)
        if ref.rule_set:
            root = kbservice.runtime_root(settings_of(request))
            if naming.find_file(root, ref.rule_set) is not None:
                _access(request, root, ref.rule_set)
            return naming.load(root, ref.rule_set, kb)
    except naming.RulesError as e:
        raise rules_error(e) from e
    return None


@router.get("/translate-rules", summary="规则集列表（内置与我的）与可改名的对象类型")
def list_rules(request: Request) -> dict[str, Any]:
    kb, root = _kb(request)
    db, ident = db_of(request), _ident(request)
    owners = assets.owners(db, "ruleset")
    items = []
    for it in naming.list_sets(root, kb):
        sc = assets.scope_of(db, "ruleset", str(it["id"]), bool(it.get("builtin")), ident)
        if sc == "hidden":
            continue
        own = owners.get(str(it["id"]))
        it.update(scope=sc, owner=own[1] if own else None, editable=assets.can_write(sc, ident))
        items.append(it)
    return ok(request, {"items": items, "types": naming.type_infos(kb)})


@router.get("/translate-rules/{rid}", summary="读取规则集：结构化内容与 YAML 原文")
def get_rules(request: Request, rid: str) -> dict[str, Any]:
    kb, root = _kb(request)
    _access(request, root, rid)
    try:
        rs = naming.load(root, rid, kb)
        text, _ = naming.source(root, rid)
    except naming.RulesError as e:
        raise rules_error(e) from e
    return ok(request, {**rs.info(), "rules": rs.as_dict(), "source": text})


class SaveBody(BaseModel):
    """rules（结构化，合并进已有文件、保留注释）或 source（YAML 原文，原样写入）二选一。"""

    rules: dict[str, Any] | None = None
    source: str | None = Field(None, max_length=MAX_RULES)


@router.put("/translate-rules/{rid}", summary="保存规则集到 data/translate-rules/（内置规则集只读，409）")
def save_rules(request: Request, rid: str, body: SaveBody) -> dict[str, Any]:
    kb, root = _kb(request)
    data: dict[str, Any] | str | None = body.source if body.source else body.rules
    if data is None:
        raise ApiError(E_PARAM, 422, "naming.need_rules")
    hit = naming.find_file(root, rid)
    if hit is not None and not hit[1]:
        _access(request, root, rid, write=True)
    try:
        rs = naming.save(root, rid, data, kb)
        text, _ = naming.source(root, rid)
    except naming.RulesError as e:
        raise rules_error(e) from e
    _claim_new(request, rid, hit is None)
    return ok(request, {**rs.info(), "rules": rs.as_dict(), "source": text})


def _claim_new(request: Request, rid: str, new: bool) -> None:
    """账号新建的规则集记为“我的规则集”（全局令牌新建的没有属主，作为共享规则集）。"""
    ident = _ident(request)
    if new and ident.user_id is not None:
        assets.claim(db_of(request), "ruleset", rid, ident.user_id)


@router.delete("/translate-rules/{rid}", summary="删除我的规则集（内置规则集只读，409）")
def delete_rules(request: Request, rid: str) -> dict[str, Any]:
    _, root = _kb(request)
    hit = naming.find_file(root, rid)
    if hit is not None and not hit[1]:
        _access(request, root, rid, write=True)
    try:
        naming.delete(root, rid)
    except naming.RulesError as e:
        raise rules_error(e) from e
    assets.release(db_of(request), "ruleset", rid)
    return ok(request, {"id": rid, "deleted": True})


@router.get("/translate-rules/{rid}/export", summary="导出规则集（YAML 文件）", response_class=Response)
def export_rules(request: Request, rid: str) -> Response:
    _, root = _kb(request)
    _access(request, root, rid)
    try:
        text, _ = naming.source(root, rid)
    except naming.RulesError as e:
        raise rules_error(e) from e
    return Response(
        text.encode("utf-8"),
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{rid}.yaml"'},
    )


class ImportBody(BaseModel):
    source: str = Field(..., max_length=MAX_RULES, description="规则集文件内容（YAML）")
    id: str | None = Field(None, max_length=80, description="保存用的编号（不给时用文件中的 id）")
    overwrite: bool = Field(False, description="同编号的规则集已存在时覆盖")


@router.post("/translate-rules/import", summary="导入规则集（YAML 原文）；编号已存在时 409，overwrite=true 覆盖")
def import_rules(request: Request, body: ImportBody) -> dict[str, Any]:
    kb, root = _kb(request)
    try:
        rid = body.id or naming.parse(body.source, kb).id
        hit = naming.find_file(root, rid)
        if hit is not None and not hit[1] and body.overwrite:
            _access(request, root, rid, write=True)
        source = body.source
        if body.id:  # 换编号导入：内容里的 id 跟着改
            data = naming.parse(body.source, kb, body.id).as_dict()
            rs = naming.save(root, rid, {**data, "id": rid}, kb, overwrite=body.overwrite)
        else:
            rs = naming.save(root, rid, source, kb, overwrite=body.overwrite)
    except naming.RulesError as e:
        raise rules_error(e) from e
    _claim_new(request, rid, hit is None)
    return ok(request, rs.info())


class MatchBody(RulesRef):
    kind: Literal["name", "port"] = "name"
    type: str = Field(naming.ANY, max_length=80, description="对象类型（kind=name 时）")
    value: str = Field(..., max_length=200, description="要测试的名称或接口名")
    to: str | None = Field(None, description="目标 Profile（取名称长度上限；不给时按规则集的 to 平台族）")


@router.post(
    "/translate-rules/match", summary="编辑器测试框：一个名称或接口名经过规则后的结果（命中的规则、整理动作、告警）"
)
def match_rules(request: Request, body: MatchBody) -> dict[str, Any]:
    kb, _ = _kb(request)
    rs = resolve_rules(request, body, kb)
    if rs is None:
        raise ApiError(E_PARAM, 422, "naming.need_rules")
    family = kb.profiles[body.to].family if body.to and body.to in kb.profiles else ""
    return ok(request, naming.test_input(rs, body.kind, body.value, body.type, kb, family))


class TestBody(RulesRef):
    """配置来源：text（配置文本）、version_id（配置版本）或 device_id（设备的最新版本）之一。"""

    text: str | None = Field(None, max_length=importer.MAX_BYTES)
    device_id: int | None = None
    version_id: int | None = None
    profile: str | None = Field(None, description="源配置的 Profile（不给时自动识别）")
    to: str | None = Field(None, description="目标 Profile（取名称长度上限）")
    target_text: str | None = Field(
        None, max_length=importer.MAX_BYTES, description="目标设备现有配置（新名与其中已有的名称重名时报冲突）"
    )


@router.post(
    "/translate-rules/test", summary="试运行：对一份配置按规则集改名，返回改名清单、端口映射、冲突、命名规范告警"
)
def test_rules(request: Request, body: TestBody) -> dict[str, Any]:
    kb, _ = _kb(request)
    rs = resolve_rules(request, body, kb)
    if rs is None:
        raise ApiError(E_PARAM, 422, "naming.need_rules")
    if body.to and body.to not in kb.profiles:
        raise ApiError(E_PARAM, 422, "parse.profile_unknown", profile=body.to)
    try:
        if body.text:
            side = compare.side_from_text(body.text, kb, body.profile, "source")
        elif body.version_id is not None or body.device_id is not None:
            db = settings_of(request).database_url
            store.upgrade(db)
            side = (
                compare.side_from_version(db, kb, body.version_id, body.profile, body.device_id)
                if body.version_id is not None
                else compare.side_from_device(db, kb, body.device_id or 0, body.profile)
            )
        else:
            raise ApiError(E_PARAM, 422, "translate.need_source")
        tg = migration.target_graph_from_text(body.target_text, kb, body.to) if body.target_text and body.to else None
    except compare.CompareError as e:
        if e.kind == "not_found":
            raise ApiError(E_NOT_FOUND, 404, e.key, **e.fmt) from e
        raise ApiError(E_PARAM, 422, e.key, **e.fmt) from e
    except migration.MigrateError as e:
        raise ApiError(E_PARAM, 422, e.key, **e.fmt) from e
    _, _, report = naming.run(side.graph, kb, rs, body.to, tg)
    report["source"] = {"device": side.graph.graph.get("device"), "profile": side.graph.graph.get("profile")}
    return ok(request, report)
