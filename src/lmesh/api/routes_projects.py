"""用户工作空间与项目（REQ-035）、权限（REQ-036）的接口。

- router（需要登录）：我的项目列表与新建、工作空间（默认项目）、公共设备库（查看）、知识库建议。
- project（只挂在 /api/v1/projects/{project}/… 下）：项目详情与设置、删除、成员、转交、复制、引用公共设备、
  复制设备到本项目、项目级规则调整、脚本一览。
- admin（管理员）：所有项目、访问审计、公共设备库的导入 / 删除 / 重新解析。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
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
    project_error,
    require_admin,
    require_token,
    settings_of,
)
from lmesh.core import analysis, checkproj, checks, i18n, importer, kbservice, projects, review, tasks, workbench
from lmesh.core import rules as rulesmod

router = APIRouter(dependencies=[Depends(require_token)])
project = APIRouter(dependencies=[Depends(require_token)])
admin = APIRouter(dependencies=[Depends(require_admin)])


def _scope(request: Request) -> projects.Scope:
    return request.state.scope  # type: ignore[no-any-return]


def _ident(request: Request) -> projects.Identity:
    return principal_of(request).identity()


# ---------------------------------------------------------------- 我的项目与工作空间


@router.get("/projects", summary="我的项目（属主）与共享给我的（成员）；管理员 all=true 时另列出其他人的项目")
def list_projects(
    request: Request,
    all: bool = Query(False, description="管理员：同时列出不是自己参与的项目（others）"),  # noqa: A002
    owner: str | None = Query(None, description="只看某个属主的项目"),
) -> dict[str, Any]:
    p = principal_of(request)
    try:
        data = projects.list_projects(db_of(request), p.identity(), include_all=all and p.is_admin, owner=owner)
    except projects.ProjectError as e:
        raise project_error(e) from e
    return ok(request, data)


class ProjectBody(BaseModel):
    name: str = Field(..., max_length=200)
    slug: str | None = Field(
        None,
        max_length=64,
        description="项目标识（在自己的项目里唯一，小写字母、数字、短横线；别人可以有同名项目）；不给时由名称生成",
    )
    description: str | None = Field(None, max_length=4000)
    settings: dict[str, Any] | None = Field(None, description="style 显示风格、rule_set 翻译规则集、baseline 安全基线")


@router.post(
    "/projects",
    summary="新建项目（属主是自己）；还没有默认项目时它成为默认项目；没有创建权限时 403（projects.create_forbidden，M9-8）",
)
def create_project(request: Request, body: ProjectBody) -> dict[str, Any]:
    try:
        return ok(request, projects.create_project(db_of(request), _ident(request), body.model_dump()))
    except projects.ProjectError as e:
        raise project_error(e) from e


@router.get(
    "/workspace",
    summary="我的工作空间：默认项目（没有项目也不能创建时为 null）、项目数、私有模板与规则集数、有效的个人令牌数、能否新建项目",
)
def workspace(request: Request) -> dict[str, Any]:
    from lmesh.core import assets, tokens

    p = principal_of(request)
    db = db_of(request)
    from lmesh.core import joining

    default = projects.default_project_or_none(db, p.identity())
    lists = projects.list_projects(db, p.identity())
    mine = {"template": 0, "ruleset": 0}
    for kind in mine:
        mine[kind] = sum(1 for _, (uid, _n) in assets.owners(db, kind).items() if uid == p.user_id)
    toks = tokens.list_tokens(db, p.username) if p.user_id is not None else []
    return ok(
        request,
        {
            "user": {"username": p.username, "role": p.role, "via": p.via, "read_only": p.read_only},
            "default_project": default["ref"] if default else None,
            "can_create": joining.creation_status(db, p.identity())["can_create"],
            "projects": {"mine": len(lists["mine"]), "shared": len(lists["shared"])},
            "templates": mine["template"],
            "rule_sets": mine["ruleset"],
            "tokens": sum(1 for t in toks if t["state"] == "active"),
        },
    )


class DefaultBody(BaseModel):
    project: str = Field(..., max_length=200)


@router.put("/workspace/default-project", summary="设置我的默认项目（命令行不带 --project 与旧的无项目接口都用它）")
def set_default(request: Request, body: DefaultBody) -> dict[str, Any]:
    try:
        return ok(request, projects.set_default(db_of(request), _ident(request), body.project))
    except projects.ProjectError as e:
        raise project_error(e) from e


# ---------------------------------------------------------------- 项目详情、设置、删除


@project.get("", summary="项目详情：属主、我的角色、成员、设置、规则调整、设备与脚本计数、最近活动")
def get_project(request: Request) -> dict[str, Any]:
    return ok(request, projects.get_project(db_of(request), _scope(request)))


class ProjectPatch(BaseModel):
    name: str | None = Field(None, max_length=200)
    slug: str | None = Field(None, max_length=64, description="改标识只限属主与管理员")
    description: str | None = Field(None, max_length=4000)
    settings: dict[str, Any] | None = None
    discoverable: bool | None = Field(None, description="可被搜索（M9-8）：属主、管理成员与管理员可以改")


@project.put(
    "",
    summary="修改项目名称、说明、设置（属主、管理与可编辑成员）；改标识只限属主与管理员；可被搜索限属主、管理成员与管理员",
)
def update_project(request: Request, body: ProjectPatch) -> dict[str, Any]:
    try:
        return ok(
            request, projects.update_project(db_of(request), _scope(request), body.model_dump(exclude_unset=True))
        )
    except projects.ProjectError as e:
        raise project_error(e) from e


@project.get("/delete-preview", summary="删除项目的影响：私有设备与版本、脚本、忽略项、引用（只解除）、成员")
def delete_preview(request: Request) -> dict[str, Any]:
    return ok(request, projects.delete_preview(db_of(request), _scope(request)))


@project.delete(
    "", summary="删除项目（属主与管理员）：私有设备一起删除，引用的公共设备只解除引用；confirm 必须是项目标识"
)
def delete_project(request: Request, confirm: str = Query(..., description="项目标识（确认用）")) -> dict[str, Any]:
    sc = _scope(request)
    try:
        res = projects.delete_project(db_of(request), sc, confirm)
    except projects.ProjectError as e:
        raise project_error(e) from e
    if sc.role == "admin":
        projects.audit(db_of(request), sc.identity, None, sc.slug, "delete", {"project_id": sc.project_id})
    return ok(request, res)


# ---------------------------------------------------------------- 成员与转交


@project.get("/members", summary="成员：属主、可编辑、只读，加入时间")
def members(request: Request) -> dict[str, Any]:
    return ok(request, {"members": projects.list_members(db_of(request), _scope(request))})


class MemberBody(BaseModel):
    role: Literal["manage", "edit", "read"]


@project.put("/members/{username}", summary="添加成员或改成员角色（属主、管理成员与管理员）")
def set_member(request: Request, username: str, body: MemberBody) -> dict[str, Any]:
    try:
        return ok(request, projects.set_member(db_of(request), _scope(request), username, body.role))
    except projects.ProjectError as e:
        raise project_error(e) from e


@project.delete("/members/{username}", summary="移除成员（属主、管理成员与管理员）；成员移除自己即退出项目")
def remove_member(request: Request, username: str) -> dict[str, Any]:
    try:
        return ok(request, projects.remove_member(db_of(request), _scope(request), username))
    except projects.ProjectError as e:
        raise project_error(e) from e


class TransferBody(BaseModel):
    to: str = Field(..., max_length=64, description="新属主账号")
    keep_as: Literal["manage", "edit", "read"] | None = Field("edit", description="原属主留作成员的角色；null 表示退出")
    slug: str | None = Field(
        None, max_length=64, description="同时改标识：新属主已有同名项目时必须给（409 的 data.suggested 是可用的标识）"
    )


@project.post(
    "/transfer",
    summary="转交项目（属主与管理员）；项目用到的原属主私有规则集复制一份给新属主；新属主已有同名标识时 409，可用 slug 改名",
)
def transfer(request: Request, body: TransferBody) -> dict[str, Any]:
    try:
        return ok(request, projects.transfer(db_of(request), _scope(request), body.to, body.keep_as, body.slug))
    except projects.ProjectError as e:
        raise project_error(e) from e


class CopyBody(BaseModel):
    name: str = Field(..., max_length=200)
    slug: str | None = Field(None, max_length=64)
    description: str | None = Field(None, max_length=4000)
    devices: bool = Field(True, description="复制私有设备（各复制当前版本）与引用")
    scripts: bool = Field(True, description="复制脚本（当前内容）")


@project.post(
    "/copy", summary="复制为我的新项目（能查看即可，只读成员也可以）：设置、规则调整、设备、引用、脚本；不复制成员"
)
def copy_project(request: Request, body: CopyBody) -> dict[str, Any]:
    try:
        return ok(request, projects.copy_project(db_of(request), _scope(request), _ident(request), body.model_dump()))
    except projects.ProjectError as e:
        raise project_error(e) from e


# ---------------------------------------------------------------- 引用公共设备、复制设备到本项目


class RefBody(BaseModel):
    device_id: int
    version_id: int | None = Field(None, description="固定的版本；不给时跟随公共库最新版本")


@project.get("/refs", summary="本项目引用的公共设备：跟随最新 / 固定的版本、公共库是否有更新的版本")
def list_refs(request: Request) -> dict[str, Any]:
    from lmesh.core import kbservice as kbs

    kb = analysis.load_kb(kbs.runtime_root(settings_of(request)))
    rows = [d for d in workbench.device_rows(db_of(request), kb.version) if d.get("source") == "public"]
    return ok(request, {"refs": rows})


@project.post("/refs", summary="引用公共设备（跟随最新或固定版本）；项目里已有同名设备时 409")
def add_ref(request: Request, body: RefBody) -> dict[str, Any]:
    try:
        return ok(request, projects.add_ref(db_of(request), _scope(request), body.device_id, body.version_id))
    except projects.ProjectError as e:
        raise project_error(e) from e


class PinBody(BaseModel):
    version_id: int | None = Field(None, description="固定的版本；null 表示改为跟随最新")


@project.put("/refs/{device_id}", summary="改引用的版本：固定到某个版本或跟随最新")
def set_ref(request: Request, device_id: int, body: PinBody) -> dict[str, Any]:
    try:
        return ok(request, projects.set_ref(db_of(request), _scope(request), device_id, body.version_id))
    except projects.ProjectError as e:
        raise project_error(e) from e


@project.delete("/refs/{device_id}", summary="解除引用（本项目对它的忽略项一并删除，以它为基线的脚本基线置空）")
def remove_ref(request: Request, device_id: int) -> dict[str, Any]:
    try:
        return ok(request, projects.remove_ref(db_of(request), _scope(request), device_id))
    except projects.ProjectError as e:
        raise project_error(e) from e


class CopyInBody(BaseModel):
    device_id: int = Field(..., description="来源设备：公共设备，或自己能查看的其他项目里的设备")
    version_id: int | None = Field(None, description="复制哪个版本；不给时为来源中的当前版本")
    name: str | None = Field(None, max_length=200, description="新设备名；不给时沿用（同名时自动加 -2、-3…）")


@project.post("/devices/copy-in", summary="把公共设备或其他项目的设备复制为本项目的私有设备（只复制一个版本）")
def copy_in(request: Request, body: CopyInBody) -> dict[str, Any]:
    sc = _scope(request)
    db = db_of(request)
    from lmesh.core import store
    from lmesh.core.store.models import Device, Project

    with store.session(db) as s:
        dev = s.get(Device, body.device_id)
        src = s.get(Project, dev.project_id) if dev is not None and dev.project_id else None
        src_ref = src.id if src is not None else None
    if dev is None:
        raise ApiError(E_NOT_FOUND, 404, "projects.device_not_found", device=body.device_id)
    label = "public"
    if src_ref is not None:
        try:
            src_scope = projects.resolve(db, sc.identity, src_ref)  # 来源项目必须能查看
        except projects.ProjectError as e:
            raise ApiError(E_NOT_FOUND, 404, "projects.device_not_found", device=body.device_id) from e
        label = src_scope.label
        if body.version_id is None:
            with projects.use(src_scope, sc.identity), store.session(db) as s:
                body.version_id = projects.current_version_id(s, body.device_id)
    try:
        res = projects.copy_device(db, sc, body.device_id, body.version_id, body.name, label)
    except projects.ProjectError as e:
        raise project_error(e) from e
    return ok(request, res)


# ---------------------------------------------------------------- 项目级规则调整


def _rule_rows(request: Request) -> list[dict[str, Any]]:
    root = kbservice.runtime_root(settings_of(request))
    kb = analysis.load_kb(root)
    try:
        rows = checks.list_rules(kb, checks.rules_dir(root))["rules"]
    except rulesmod.RuleError as e:
        raise ApiError(E_STATE, 409, "rules.invalid", data={"issues": e.issues}, n=len(e.issues)) from e
    keys = ("id", "builtin", "title", "severity", "enabled", "domain", "tags", "ai")
    return [{k: r.get(k) for k in keys} for r in rows]


@project.get("/rules", summary="检查规则在本项目中的设置：共享级别与开关、本项目的调整（关闭 / 改级别 / 原因）")
def project_rules(request: Request) -> dict[str, Any]:
    ov = {o["rule"]: o for o in projects.list_overrides(db_of(request), _scope(request))}
    rows = []
    for r in _rule_rows(request):
        o = ov.get(r["id"])
        rows.append(
            {
                **r,
                "override": o,
                "effective": {
                    "enabled": bool(r["enabled"]) and (o is None or o["enabled"]),
                    "severity": (o or {}).get("severity") or r["severity"],
                },
            }
        )
    return ok(request, {"rules": rows, "adjusted": len(ov)})


class OverrideBody(BaseModel):
    enabled: bool | None = Field(None, description="false：本项目关闭这条规则")
    severity: Literal["error", "warning", "info"] | None = Field(None, description="本项目使用的级别")
    reason: str = Field(..., max_length=2000, description="原因（必填）")


@project.put("/rules/{rule_id}", summary="本项目关闭某条规则或改级别（属主与可编辑成员，只影响本项目）")
def set_override(request: Request, rule_id: str, body: OverrideBody) -> dict[str, Any]:
    known = {r["id"] for r in _rule_rows(request)}
    try:
        return ok(
            request,
            projects.set_override(
                db_of(request), _scope(request), rule_id, body.enabled, body.severity, body.reason, known
            ),
        )
    except projects.ProjectError as e:
        raise project_error(e) from e


@project.delete("/rules/{rule_id}", summary="恢复为共享规则的设置")
def delete_override(request: Request, rule_id: str) -> dict[str, Any]:
    try:
        return ok(request, projects.delete_override(db_of(request), _scope(request), rule_id))
    except projects.ProjectError as e:
        raise project_error(e) from e


# ---------------------------------------------------------------- 脚本一览


def _actor(request: Request) -> checkproj.Actor:
    p = principal_of(request)
    return checkproj.Actor(p.user_id, p.is_admin, p.username)


@project.get(
    "/scripts", summary="本项目全部脚本（平铺）：类型、基线设备与版本策略、检查结果、顺序核查、AI、修订数、最后修改"
)
def list_scripts(
    request: Request, kind: Literal["change", "full"] | None = None, device_id: int | None = None
) -> dict[str, Any]:
    return ok(request, {"scripts": checkproj.list_scripts(db_of(request), _actor(request), kind, device_id)})


class NewScriptBody(BaseModel):
    name: str = Field(..., max_length=200)
    kind: Literal["change", "full"] = "change"
    device_id: int | None = Field(None, description="基线设备（本项目的设备）")
    version_id: int | None = Field(None, description="基线版本；不给时跟随设备在项目中的当前版本")
    content: str = Field("", max_length=checkproj.MAX_TEXT)
    order_check: bool = True
    ai_check: bool = False


@project.post("/scripts", summary="新建脚本（同时建一个检查项目保存基线与检查设置），返回 group 与 script")
def create_script(request: Request, body: NewScriptBody) -> dict[str, Any]:
    try:
        return ok(request, checkproj.create_project_script(db_of(request), _actor(request), body.model_dump()))
    except checkproj.ProjectError as e:
        status = {"not_found": (E_NOT_FOUND, 404)}.get(e.kind, (E_PARAM, 422))
        raise ApiError(status[0], status[1], e.key, **e.fmt) from e


# ---------------------------------------------------------------- 公共设备库（查看：所有人；导入 / 删除：管理员）


@router.get("/public-devices", summary="公共设备库：版本数、最新版本、引用它的项目（跟随最新 / 固定版本）")
def public_devices(request: Request) -> dict[str, Any]:
    rows = projects.list_public(db_of(request))
    if not principal_of(request).is_admin:  # 普通账号只看到自己能访问的引用项目
        ident = _ident(request)
        visible = {p["slug"] for k in ("mine", "shared") for p in projects.list_projects(db_of(request), ident)[k]}
        for r in rows:
            r["refs"] = [x for x in r["refs"] if x["project"] in visible]
    return ok(request, {"devices": rows})


@router.get("/public-devices/{device_id}/versions", summary="公共设备的版本（新的在前）")
def public_versions(request: Request, device_id: int) -> dict[str, Any]:
    from lmesh.core import compare

    with projects.use(None, _ident(request)):
        if not any(d["id"] == device_id for d in projects.list_public(db_of(request))):
            raise ApiError(E_NOT_FOUND, 404, "projects.public_not_found", device=device_id)
        vers = compare.versions(db_of(request), device_id)
    return ok(request, {"device_id": device_id, "versions": vers or []})


@admin.post("/public-devices", summary="导入到公共设备库（管理员）：同名设备作为新版本，引用它并跟随最新的项目随之更新")
async def public_import(
    request: Request, files: list[UploadFile] = File(...), level: Literal["basic", "strict"] = Form("basic")
) -> dict[str, Any]:
    if not files:
        raise ApiError(E_PARAM, 422)
    sources: list[tuple[str, bytes]] = []
    for f in files:
        sources.extend(importer.iter_bytes(f.filename or "upload.txt", await f.read()))
    settings = settings_of(request)
    db = db_of(request)
    lang = lang_of(request)
    results = []
    with projects.use(None, _ident(request)):
        for r in importer.import_sources(
            sources,
            db,
            level,
            kbservice.runtime_root(settings),
            source_kind="api",
            actor=principal_of(request).username,
            keep=int(settings.get("history.keep")),
            public=True,
        ):
            d = r.as_dict()
            if not r.ok:
                d["error"] = i18n.t(r.error, lang)
            results.append(d)
    return ok(request, {"files": results})


@admin.delete(
    "/public-devices/{device_id}",
    summary="删除公共设备（管理员）：还有项目引用时 409（data.projects），force=true 时一并解除引用",
)
def public_delete(request: Request, device_id: int, force: bool = False) -> dict[str, Any]:
    try:
        return ok(request, projects.delete_public(db_of(request), device_id, force, principal_of(request).username))
    except projects.ProjectError as e:
        raise project_error(e) from e


@admin.delete(
    "/public-devices/{device_id}/versions/{version_id}",
    summary="删除公共设备的一个版本（管理员）；固定在该版本的引用改为跟随最新",
)
def public_delete_version(request: Request, device_id: int, version_id: int, force: bool = False) -> dict[str, Any]:
    from lmesh.core import device_delete

    with projects.use(None, _ident(request)):
        try:
            return ok(
                request,
                device_delete.delete_version(
                    db_of(request), device_id, version_id, force, principal_of(request).username
                ),
            )
        except device_delete.DeleteError as e:
            code = (E_NOT_FOUND, 404) if e.kind == "not_found" else (E_STATE, 409)
            raise ApiError(code[0], code[1], e.key, data=e.data, **e.fmt) from e


@admin.post("/public-devices/rebuild", summary="按当前知识库重新解析公共设备库（后台任务，管理员）")
def public_rebuild(request: Request) -> dict[str, Any]:
    db, root = db_of(request), kbservice.runtime_root(settings_of(request))
    ids = [d["id"] for d in projects.list_public(db)]
    return ok(request, {"task_id": tasks.submit(db, "rebuild", lambda p: workbench.rebuild_all(db, root, p, ids))})


# ---------------------------------------------------------------- 管理员：所有项目与审计


@admin.get("/admin/projects", summary="所有项目（管理员）：属主（含已停用）、成员、设备与脚本计数、最近活动")
def all_projects(request: Request) -> dict[str, Any]:
    data = projects.list_projects(db_of(request), _ident(request), include_all=True)
    rows = data["mine"] + data["shared"] + data["others"]
    return ok(
        request,
        {
            "projects": rows,
            "owners": len({r["owner"] for r in rows if r["owner"]}),
            "with_members": sum(1 for r in rows if r["members"] > 1),
            "owner_disabled": sum(1 for r in rows if r["owner_disabled"]),
        },
    )


@admin.get("/admin/audit", summary="访问审计（管理员）：管理员进入或修改他人项目、转交、删除；不含请求内容")
def audit(request: Request, project: str | None = None, limit: int = Query(200, ge=1, le=2000)) -> dict[str, Any]:
    return ok(request, {"events": projects.list_audit(db_of(request), project, limit)})


# ---------------------------------------------------------------- 知识库建议（普通用户提交，维护员在审核队列处理）


class SuggestionBody(BaseModel):
    target: str = Field(..., max_length=400, description="Schema 节点、属性或命令卡编号")
    kind: Literal["default", "syntax", "description", "other"] = Field(
        ..., description="修改默认值 / 补充命令写法 / 修改说明 / 其他"
    )
    current: str = Field("", max_length=2000)
    proposed: str = Field("", max_length=4000)
    reason: str = Field(..., min_length=1, max_length=4000)
    project: str | None = Field(None, max_length=64, description="提出建议时所在的项目（只作参考）")


@router.post("/kb/suggestions", summary="对知识库提建议（所有账号）：进入审核队列（类型 suggestion），由维护员处理")
def suggest(request: Request, body: SuggestionBody) -> dict[str, Any]:
    p = principal_of(request)
    title = f"{body.target} · {body.kind}"
    payload = body.model_dump()
    rid = review.add(
        db_of(request),
        "suggestion",
        title,
        body.target,
        payload,
        {"method": "user", "user": p.username, "project": body.project},
    )
    return ok(request, {"id": rid, "status": "pending"})


@router.get("/kb/suggestions", summary="建议列表：mine=true 只看自己提的（含处理结果与驳回原因）")
def suggestions(request: Request, mine: bool = True, status: str = "all") -> dict[str, Any]:
    p = principal_of(request)
    if not mine and not p.is_kb_editor:
        raise ApiError(E_FORBIDDEN, 403, "api.error.kb_editor_only")
    db = db_of(request)
    data = review.list_items(db, None if status == "all" else status, "suggestion", 1000, 0)
    items = data.get("items", [])
    if mine:
        items = [i for i in items if (i.get("source") or {}).get("user") == p.username]
    return ok(request, {"items": [review.get(db, int(i["id"])) for i in items]})
