"""用户工作空间与项目（REQ-035）、项目权限（REQ-036）。CLI 与 API 共用。

三层：系统（知识库、公共设备库，管理员维护）→ 用户工作空间（每个账号一个：默认项目、我的模板、我的规则集）→ 项目
（私有设备与对公共设备的引用、脚本、检查忽略项、规则调整、项目设置）。

项目角色：owner 属主 / edit 可编辑成员 / read 只读成员 / admin（管理员访问不是自己参与的项目，完全权限，写审计）。
属主与可编辑成员可以修改项目内的数据与项目设置（D-0176）；成员管理、转交、删除只限属主与管理员。不是成员的普通账号
看不到项目（返回“不存在”，不暴露项目是否存在）。

当前项目（Scope）放在上下文变量里：API 的项目路径依赖、旧的无项目接口（落到调用者的默认项目）与命令行（--project，
不带时默认项目）设置它；设备列表、最新版本、版本访问、忽略项、检查规则调整等按它过滤。没有设置时（单元测试直接调用
core、管理员的全局操作）不过滤，行为与 M6 之前相同。
"""

from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, or_, select, update

from lmesh.core import store
from lmesh.core.store.models import (
    AuditEvent,
    CheckIgnore,
    CheckProject,
    CheckRevision,
    CheckScript,
    ConfigImport,
    ConfigVersion,
    Device,
    Edge,
    Node,
    Project,
    ProjectDeviceRef,
    ProjectMember,
    ProjectRuleOverride,
    UnknownLine,
    User,
    Workspace,
    iso,
)

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
MEMBER_ROLES = ("edit", "read")
SEVERITIES = ("error", "warning", "info")
STYLES = ("huawei", "cisco", "nokia")
# 项目设置的默认值：style 显示风格（空 = 按设备自动）、rule_set 翻译规则集（空 = 不用）、baseline 安全基线（空 = 不用）
SETTINGS_DEFAULTS: dict[str, Any] = {"style": "", "rule_set": "", "baseline": ""}
DEFAULT_NAME = "默认项目"

_log = logging.getLogger("lmesh.projects")
_audit_log = logging.getLogger("lmesh.audit")


class ProjectError(ValueError):
    """kind：param 参数不合格（422 / 退出码 2）、not_found 不存在或无权查看（404 / 4）、
    state 状态不允许（409 / 1）、forbidden 没有权限（403 / 1）。"""

    def __init__(self, key: str, kind: str = "param", data: Any = None, **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.data, self.fmt = key, kind, data, fmt


@dataclass(frozen=True)
class Identity:
    """调用者：账号（user_id）或全局 API 令牌 / 没有账号时的命令行（user_id 为空，按管理员）。"""

    user_id: int | None
    username: str
    role: str = "admin"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_kb_editor(self) -> bool:
        return self.role in ("admin", "maintainer")


SYSTEM = Identity(None, "api-token", "admin")


@dataclass(frozen=True)
class Scope:
    """当前项目与调用者在其中的角色。overrides：项目级规则调整 {规则: {enabled, severity, reason}}。"""

    project_id: int
    slug: str
    role: str
    identity: Identity = SYSTEM
    overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def can_write(self) -> bool:
        return self.role in ("owner", "edit", "admin")

    @property
    def can_manage(self) -> bool:
        return self.role in ("owner", "admin")


_SCOPE: ContextVar[Scope | None] = ContextVar("lmesh_project_scope", default=None)
_LAZY: ContextVar[Callable[[], Scope] | None] = ContextVar("lmesh_project_lazy", default=None)
_IDENT: ContextVar[Identity | None] = ContextVar("lmesh_identity", default=None)


def current() -> Scope | None:
    """当前项目；命令行设置的是延迟解析（第一次用到时才连接数据库），解析后缓存。"""
    sc = _SCOPE.get()
    if sc is None:
        lazy = _LAZY.get()
        if lazy is not None:
            sc = lazy()
            _SCOPE.set(sc)
    return sc


def identity() -> Identity | None:
    return _IDENT.get()


def set_identity(ident: Identity | None) -> None:
    _IDENT.set(ident)


def set_scope(scope: Scope | None) -> None:
    _SCOPE.set(scope)


def set_lazy(resolver: Callable[[], Scope] | None) -> None:
    _SCOPE.set(None)
    _LAZY.set(resolver)


@contextlib.contextmanager
def use(scope: Scope | None, ident: Identity | None = None) -> Iterator[Scope | None]:
    t1, t2, t3 = _SCOPE.set(scope), _LAZY.set(None), _IDENT.set(ident if ident is not None else _IDENT.get())
    try:
        yield scope
    finally:
        _SCOPE.reset(t1)
        _LAZY.reset(t2)
        _IDENT.reset(t3)


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------- 设备可见性（其他模块调用）


def device_clause(scope: Scope) -> Any:
    """项目能看到的设备：私有设备 + 引用的公共设备。"""
    refs = select(ProjectDeviceRef.device_id).where(ProjectDeviceRef.project_id == scope.project_id)
    return or_(Device.project_id == scope.project_id, Device.id.in_(refs))


def scoped_devices(stmt: Any) -> Any:
    """给设备查询加上当前项目的过滤（没有当前项目时原样返回）。"""
    sc = current()
    return stmt if sc is None else stmt.where(device_clause(sc))


def visible(s: Any, device_id: int) -> bool:
    sc = current()
    if sc is None:
        return True
    dev = s.get(Device, device_id)
    if dev is None:
        return False
    if dev.project_id == sc.project_id:
        return True
    return _ref(s, sc.project_id, device_id) is not None


def visible_version(s: Any, version_id: int) -> bool:
    sc = current()
    if sc is None:
        return True
    ver = s.get(ConfigVersion, version_id)
    return ver is not None and visible(s, ver.device_id)


def check_device(db_url: str, device_id: int) -> bool:
    if current() is None:
        return True
    with store.session(db_url) as s:
        return visible(s, device_id)


def check_version(db_url: str, version_id: int) -> bool:
    if current() is None:
        return True
    with store.session(db_url) as s:
        return visible_version(s, version_id)


def _ref(s: Any, project_id: int, device_id: int) -> ProjectDeviceRef | None:
    return s.scalar(
        select(ProjectDeviceRef).where(
            ProjectDeviceRef.project_id == project_id, ProjectDeviceRef.device_id == device_id
        )
    )


def pins(s: Any) -> dict[int, int | None]:
    """当前项目引用的公共设备：{设备: 固定的版本（None 表示跟随最新）}。"""
    sc = current()
    if sc is None:
        return {}
    rows = s.execute(
        select(ProjectDeviceRef.device_id, ProjectDeviceRef.version_id).where(
            ProjectDeviceRef.project_id == sc.project_id
        )
    ).all()
    return {int(d): (int(v) if v is not None else None) for d, v in rows}


def current_version_id(s: Any, device_id: int) -> int | None:
    """设备在当前项目中的“当前版本”：引用并固定了版本时是该版本，否则是最新版本。"""
    sc = current()
    if sc is not None:
        ref = _ref(s, sc.project_id, device_id)
        if ref is not None and ref.version_id is not None:
            return int(ref.version_id)
    return s.scalar(
        select(ConfigVersion.id).where(ConfigVersion.device_id == device_id).order_by(ConfigVersion.id.desc()).limit(1)
    )


def source_info(s: Any, dev: Device, latest_id: int | None) -> dict[str, Any]:
    """设备在当前项目中的来源：private 私有 / public 引用的公共设备（policy follow|pin、固定的版本、是否有更新的版本）。"""
    if dev.project_id is not None:
        return {"source": "private", "origin": dev.origin, "origin_note": dev.origin_note}
    sc = current()
    ref = _ref(s, sc.project_id, dev.id) if sc is not None else None
    pinned = ref.version_id if ref is not None else None
    return {
        "source": "public",
        "origin": dev.origin,
        "origin_note": dev.origin_note,
        "policy": "pin" if pinned else "follow",
        "pinned_version_id": pinned,
        "public_latest_version_id": latest_id,
        "newer_available": bool(pinned and latest_id and latest_id != pinned),
    }


def target_project_id(db_url: str) -> int:
    """导入新设备时放到哪个项目：当前项目；没有当前项目时放默认项目（与命令行、旧接口一致）。"""
    sc = current()
    if sc is not None:
        return sc.project_id
    return default_project(db_url, identity() or SYSTEM)["id"]


def rule_overrides() -> dict[str, dict[str, Any]]:
    sc = current()
    return dict(sc.overrides) if sc is not None else {}


# ---------------------------------------------------------------- 项目查找与角色


def _user(s: Any, username: str) -> User:
    u = s.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if u is None:
        raise ProjectError("projects.user_not_found", "not_found", name=username)
    return u


def role_of(s: Any, p: Project, ident: Identity) -> str | None:
    if ident.user_id is not None and p.owner_id == ident.user_id:
        return "owner"
    if ident.user_id is not None:
        m = s.scalar(
            select(ProjectMember.role).where(ProjectMember.project_id == p.id, ProjectMember.user_id == ident.user_id)
        )
        if m:
            return str(m)
    if ident.is_admin:
        return "admin"
    return None


def _find(s: Any, ref: str | int) -> Project | None:
    text = str(ref).strip()
    if "/" in text:  # 属主/标识
        owner, _, slug = text.partition("/")
        p = s.scalar(select(Project).where(Project.slug == slug.lower()))
        if p is None:
            return None
        o = s.get(User, p.owner_id) if p.owner_id else None
        return p if o is not None and o.username.lower() == owner.lower() else None
    p = s.scalar(select(Project).where(Project.slug == text.lower()))
    if p is None and text.isdigit():
        p = s.get(Project, int(text))
    return p


def _load_overrides(s: Any, project_id: int) -> dict[str, dict[str, Any]]:
    rows = s.scalars(select(ProjectRuleOverride).where(ProjectRuleOverride.project_id == project_id))
    return {r.rule: {"enabled": r.enabled, "severity": r.severity, "reason": r.reason} for r in rows}


def _scope(s: Any, p: Project, ident: Identity, role: str) -> Scope:
    return Scope(p.id, p.slug, role, ident, _load_overrides(s, p.id))


def resolve(db_url: str, ident: Identity, ref: str | int) -> Scope:
    """项目引用（标识、属主/标识或编号）→ Scope；不存在或没有权限查看时 not_found。"""
    with store.session(db_url) as s:
        p = _find(s, ref)
        role = role_of(s, p, ident) if p is not None else None
        if p is None or role is None:
            raise ProjectError("projects.not_found", "not_found", project=str(ref))
        return _scope(s, p, ident, role)


def scope_by_id(db_url: str, project_id: int, ident: Identity = SYSTEM) -> Scope:
    with store.session(db_url) as s:
        p = s.get(Project, project_id)
        if p is None:
            raise ProjectError("projects.not_found", "not_found", project=str(project_id))
        return _scope(s, p, ident, role_of(s, p, ident) or "admin")


def require_write(scope: Scope) -> None:
    if not scope.can_write:
        raise ProjectError("projects.read_only", "forbidden", project=scope.slug)


def require_manage(scope: Scope) -> None:
    if not scope.can_manage:
        raise ProjectError("projects.owner_only", "forbidden", project=scope.slug)


# ---------------------------------------------------------------- 默认项目与工作空间


def _first_admin(s: Any) -> User | None:
    q = select(User).where(User.role == "admin").order_by(User.disabled, User.id).limit(1)
    return s.scalar(q)


def _workspace(s: Any, user_id: int) -> Workspace:
    ws = s.scalar(select(Workspace).where(Workspace.user_id == user_id))
    if ws is None:
        ws = Workspace(user_id=user_id)
        s.add(ws)
        s.flush()
    return ws


def _free_slug(s: Any, base: str) -> str:
    b = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")[:56]
    if len(b) < 2 or not b[0].isalnum():
        b = "project"
    cand, n = b, 2
    while s.scalar(select(Project.id).where(Project.slug == cand)) is not None:
        cand, n = f"{b}-{n}", n + 1
    return cand


def _ensure_default(s: Any, ident: Identity) -> Project:
    if ident.user_id is None:
        admin = _first_admin(s)
        if admin is not None:
            return _ensure_default(s, Identity(admin.id, admin.username, "admin"))
        p = s.scalar(select(Project).where(Project.owner_id.is_(None), Project.slug == "default"))
        if p is None:
            p = Project(slug=_free_slug(s, "default"), name=DEFAULT_NAME, description="", owner_id=None, settings={})
            s.add(p)
            s.flush()
        return p
    ws = _workspace(s, ident.user_id)
    p = s.get(Project, ws.default_project_id) if ws.default_project_id else None
    if p is not None and role_of(s, p, ident) not in (None, "admin"):
        return p
    adopt = None
    if ident.is_admin:
        first = _first_admin(s)
        if first is not None and first.id == ident.user_id:  # 第一个管理员接管没有属主的默认项目
            adopt = s.scalar(select(Project).where(Project.owner_id.is_(None), Project.slug == "default"))
    if adopt is not None:
        adopt.owner_id = ident.user_id
        p = adopt
    else:
        p = s.scalar(
            select(Project).where(Project.owner_id == ident.user_id).order_by(Project.created_at, Project.id).limit(1)
        )
        if p is None:
            p = Project(
                slug=_free_slug(s, f"{ident.username}-default"),
                name=DEFAULT_NAME,
                description="",
                owner_id=ident.user_id,
                settings={},
            )
            s.add(p)
            s.flush()
    ws.default_project_id = p.id
    return p


def cli_identity(db_url: str, username: str | None = None) -> Identity:
    """命令行以哪个账号的身份：--as 给出的账号；不给时第一个管理员；还没有账号时为 SYSTEM（与全局令牌相同）。"""
    with store.session(db_url) as s:
        u = _user(s, username) if username else _first_admin(s)
        if u is None:
            return SYSTEM
        return Identity(u.id, u.username, u.role)


def default_project(db_url: str, ident: Identity) -> dict[str, Any]:
    """调用者的默认项目（不存在时自动创建）：命令行不带 --project、旧的无项目接口都用它。"""
    with store.session(db_url) as s:
        p = _ensure_default(s, ident)
        return {"id": p.id, "slug": p.slug}


def default_scope(db_url: str, ident: Identity) -> Scope:
    with store.session(db_url) as s:
        p = _ensure_default(s, ident)
        return _scope(s, p, ident, role_of(s, p, ident) or "admin")


def set_default(db_url: str, ident: Identity, ref: str | int) -> dict[str, Any]:
    if ident.user_id is None:
        raise ProjectError("projects.need_account", "state")
    sc = resolve(db_url, ident, ref)
    with store.session(db_url) as s:
        _workspace(s, ident.user_id).default_project_id = sc.project_id
    return {"default_project": sc.slug}


def on_user_created(db_url: str, user_id: int) -> None:
    """新账号：建工作空间；第一个管理员接管没有属主的默认项目（旧安装没有账号时导入的数据）。"""
    with store.session(db_url) as s:
        u = s.get(User, user_id)
        if u is None:
            return
        _workspace(s, u.id)
        if u.role == "admin":
            first = _first_admin(s)
            orphan = s.scalar(select(Project).where(Project.owner_id.is_(None), Project.slug == "default"))
            if first is not None and first.id == u.id:
                if orphan is not None:
                    _workspace(s, u.id).default_project_id = orphan.id
                s.execute(update(Project).where(Project.owner_id.is_(None)).values(owner_id=u.id))


# ---------------------------------------------------------------- 项目信息


def _settings(p: Project) -> dict[str, Any]:
    return {**SETTINGS_DEFAULTS, **(p.settings or {})}


def _counts(s: Any, p: Project) -> dict[str, Any]:
    private = int(s.scalar(select(func.count()).select_from(Device).where(Device.project_id == p.id)) or 0)
    refs = int(
        s.scalar(select(func.count()).select_from(ProjectDeviceRef).where(ProjectDeviceRef.project_id == p.id)) or 0
    )
    cps = list(s.scalars(select(CheckProject.id).where(CheckProject.project_id == p.id)))
    scripts = 0
    errors = 0
    if cps:
        rows = list(s.scalars(select(CheckScript).where(CheckScript.project_id.in_(cps))))
        scripts = len(rows)
        errors = sum(1 for x in rows if int((x.last_check or {}).get("errors") or 0) > 0)
    return {
        "devices": private + refs,
        "private": private,
        "refs": refs,
        "scripts": scripts,
        "scripts_with_errors": errors,
        "check_projects": len(cps),
    }


def _member_rows(s: Any, p: Project) -> list[dict[str, Any]]:
    out = []
    owner = s.get(User, p.owner_id) if p.owner_id else None
    if owner is not None:
        out.append(
            {"username": owner.username, "role": "owner", "disabled": owner.disabled, "since": iso(p.created_at)}
        )
    rows = s.execute(
        select(ProjectMember, User).join(User, User.id == ProjectMember.user_id).where(ProjectMember.project_id == p.id)
    ).all()
    for m, u in sorted(rows, key=lambda r: r[1].username.lower()):
        out.append({"username": u.username, "role": m.role, "disabled": u.disabled, "since": iso(m.created_at)})
    return out


def project_dict(s: Any, p: Project, role: str | None, full: bool = False) -> dict[str, Any]:
    owner = s.get(User, p.owner_id) if p.owner_id else None
    members = _member_rows(s, p)
    out: dict[str, Any] = {
        "id": p.id,
        "slug": p.slug,
        "name": p.name,
        "description": p.description,
        "owner": owner.username if owner else None,
        "owner_disabled": bool(owner.disabled) if owner else False,
        "role": role,
        "members": len(members),
        "member_names": [m["username"] for m in members],
        "settings": _settings(p),
        "migrated_from": p.migrated_from,
        "last_activity": p.last_activity,
        "counts": _counts(s, p),
        "created_at": iso(p.created_at),
        "updated_at": iso(p.updated_at),
    }
    if full:
        out["member_list"] = members
        out["overrides"] = [{"rule": k, **v} for k, v in sorted(_load_overrides(s, p.id).items())]
    return out


def list_projects(
    db_url: str, ident: Identity, *, include_all: bool = False, owner: str | None = None
) -> dict[str, Any]:
    """我的项目（属主）与共享给我的（成员）；include_all（管理员）时列出全部项目。owner 只看某个属主的项目。"""
    with store.session(db_url) as s:
        default_id = None
        if ident.user_id is not None:
            ws = s.scalar(select(Workspace).where(Workspace.user_id == ident.user_id))
            default_id = ws.default_project_id if ws else None
        q = select(Project).order_by(Project.updated_at.desc(), Project.id.desc())
        if owner:
            q = q.where(Project.owner_id == _user(s, owner).id)
        rows = []
        for p in s.scalars(q):
            role = role_of(s, p, ident)
            if role is None or (role == "admin" and not include_all):
                continue
            d = project_dict(s, p, role)
            d["default"] = p.id == default_id
            rows.append(d)
        return {
            "mine": [r for r in rows if r["role"] == "owner"],
            "shared": [r for r in rows if r["role"] in MEMBER_ROLES],
            "others": [r for r in rows if r["role"] == "admin"],
            "default_project": next((r["slug"] for r in rows if r["default"]), None),
        }


def get_project(db_url: str, scope: Scope) -> dict[str, Any]:
    with store.session(db_url) as s:
        p = s.get(Project, scope.project_id)
        if p is None:
            raise ProjectError("projects.not_found", "not_found", project=scope.slug)
        return project_dict(s, p, scope.role, full=True)


def _validate_slug(slug: str) -> str:
    v = (slug or "").strip().lower()
    if not SLUG_RE.match(v):
        raise ProjectError("projects.bad_slug", slug=slug)
    return v


def _validate_name(name: str | None) -> str:
    n = (name or "").strip()
    if not n or len(n) > 200:
        raise ProjectError("projects.bad_name")
    return n


def _validate_settings(data: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (data or {}).items():
        if k not in SETTINGS_DEFAULTS:
            raise ProjectError("projects.bad_setting", setting=k)
        v = "" if v is None else str(v)
        if k == "style" and v and v not in STYLES:
            raise ProjectError("projects.bad_setting", setting=k)
        if len(v) > 120:
            raise ProjectError("projects.bad_setting", setting=k)
        out[k] = v
    return out


def create_project(db_url: str, ident: Identity, data: dict[str, Any]) -> dict[str, Any]:
    """新建项目：标识全站唯一；属主是调用者（全局令牌与没有账号的命令行建的项目属于第一个管理员）。"""
    name = _validate_name(data.get("name"))
    with store.session(db_url) as s:
        slug = _validate_slug(data["slug"]) if data.get("slug") else _free_slug(s, name)
        if s.scalar(select(Project.id).where(Project.slug == slug)) is not None:
            raise ProjectError("projects.slug_taken", "state", slug=slug)
        owner_id = ident.user_id
        if owner_id is None:
            admin = _first_admin(s)
            owner_id = admin.id if admin is not None else None
        p = Project(
            slug=slug,
            name=name,
            description=str(data.get("description") or "")[:4000],
            owner_id=owner_id,
            settings=_validate_settings(data.get("settings")),
            last_activity={"actor": ident.username, "action": "create", "at": iso(_now())},
        )
        s.add(p)
        s.flush()
        if ident.user_id is not None:
            ws = _workspace(s, ident.user_id)
            if ws.default_project_id is None:
                ws.default_project_id = p.id
        _log.info("项目已创建：%s（%s，属主 %s）", p.slug, p.id, ident.username)
        return project_dict(s, p, role_of(s, p, ident))


def update_project(db_url: str, scope: Scope, data: dict[str, Any]) -> dict[str, Any]:
    """改名称、说明、设置（属主与可编辑成员）；改标识只限属主与管理员。"""
    require_write(scope)
    with store.session(db_url) as s:
        p = s.get(Project, scope.project_id)
        assert p is not None
        if "slug" in data and data["slug"] and data["slug"] != p.slug:
            require_manage(scope)
            slug = _validate_slug(data["slug"])
            if s.scalar(select(Project.id).where(Project.slug == slug)) is not None:
                raise ProjectError("projects.slug_taken", "state", slug=slug)
            p.slug = slug
        if "name" in data and data["name"] is not None:
            p.name = _validate_name(data["name"])
        if "description" in data and data["description"] is not None:
            p.description = str(data["description"])[:4000]
        if data.get("settings") is not None:
            p.settings = {**(p.settings or {}), **_validate_settings(data["settings"])}
        p.updated_at = _now()
        s.flush()
        return project_dict(s, p, scope.role, full=True)


# ---------------------------------------------------------------- 删除项目


def _delete_device_rows(s: Any, device_id: int) -> int:
    vids = list(s.scalars(select(ConfigVersion.id).where(ConfigVersion.device_id == device_id)))
    if vids:
        s.execute(delete(Edge).where(Edge.version_id.in_(vids)))
        s.execute(delete(Node).where(Node.version_id.in_(vids)))
        s.execute(delete(UnknownLine).where(UnknownLine.version_id.in_(vids)))
        s.execute(delete(ConfigImport).where(ConfigImport.version_id.in_(vids)))
        s.execute(update(ProjectDeviceRef).where(ProjectDeviceRef.version_id.in_(vids)).values(version_id=None))
        s.execute(update(CheckProject).where(CheckProject.version_id.in_(vids)).values(version_id=None))
        s.execute(delete(ConfigVersion).where(ConfigVersion.id.in_(vids)))
    s.execute(update(CheckProject).where(CheckProject.device_id == device_id).values(device_id=None))
    s.execute(delete(CheckIgnore).where(CheckIgnore.device_id == device_id))
    s.execute(delete(ProjectDeviceRef).where(ProjectDeviceRef.device_id == device_id))
    s.execute(delete(Device).where(Device.id == device_id))
    return len(vids)


def delete_preview(db_url: str, scope: Scope) -> dict[str, Any]:
    with store.session(db_url) as s:
        p = s.get(Project, scope.project_id)
        assert p is not None
        c = _counts(s, p)
        devices = list(s.scalars(select(Device.id).where(Device.project_id == p.id)))
        versions = (
            int(
                s.scalar(select(func.count()).select_from(ConfigVersion).where(ConfigVersion.device_id.in_(devices)))
                or 0
            )
            if devices
            else 0
        )
        ignores = int(
            s.scalar(select(func.count()).select_from(CheckIgnore).where(CheckIgnore.project_id == p.id)) or 0
        )
        return {
            "project": {"id": p.id, "slug": p.slug, "name": p.name},
            "counts": {
                "private_devices": c["private"],
                "versions": versions,
                "refs": c["refs"],
                "check_projects": c["check_projects"],
                "scripts": c["scripts"],
                "check_ignores": ignores,
                "members": len(_member_rows(s, p)) - (1 if p.owner_id else 0),
            },
        }


def delete_project(db_url: str, scope: Scope, confirm: str | None = None) -> dict[str, Any]:
    """删除项目：私有设备与它们的全部版本一起删除（D-0173），引用的公共设备只解除引用；confirm 必须等于项目标识。"""
    require_manage(scope)
    if confirm is not None and confirm != scope.slug:
        raise ProjectError("projects.confirm_mismatch", slug=scope.slug)
    info = delete_preview(db_url, scope)
    with store.session(db_url) as s:
        for dev_id in list(s.scalars(select(Device.id).where(Device.project_id == scope.project_id))):
            _delete_device_rows(s, dev_id)
        cps = list(s.scalars(select(CheckProject.id).where(CheckProject.project_id == scope.project_id)))
        if cps:
            sids = list(s.scalars(select(CheckScript.id).where(CheckScript.project_id.in_(cps))))
            if sids:
                s.execute(delete(CheckRevision).where(CheckRevision.script_id.in_(sids)))
                s.execute(delete(CheckScript).where(CheckScript.id.in_(sids)))
            s.execute(delete(CheckProject).where(CheckProject.id.in_(cps)))
        for model in (ProjectDeviceRef, ProjectMember, ProjectRuleOverride, CheckIgnore):
            s.execute(delete(model).where(model.project_id == scope.project_id))  # type: ignore[attr-defined]
        s.execute(
            update(Workspace).where(Workspace.default_project_id == scope.project_id).values(default_project_id=None)
        )
        s.execute(update(AuditEvent).where(AuditEvent.project_id == scope.project_id).values(project_id=None))
        s.execute(delete(Project).where(Project.id == scope.project_id))
    from lmesh.core import script_check

    script_check.clear_cache()
    _log.info("项目已删除：%s（编号 %d，操作者 %s）", scope.slug, scope.project_id, scope.identity.username)
    return {"deleted": True, **info}


# ---------------------------------------------------------------- 成员与转交


def list_members(db_url: str, scope: Scope) -> list[dict[str, Any]]:
    with store.session(db_url) as s:
        p = s.get(Project, scope.project_id)
        assert p is not None
        return _member_rows(s, p)


def set_member(db_url: str, scope: Scope, username: str, role: str) -> dict[str, Any]:
    """邀请成员或改成员角色（属主与管理员）。"""
    require_manage(scope)
    if role not in MEMBER_ROLES:
        raise ProjectError("projects.bad_member_role", role=role)
    with store.session(db_url) as s:
        u = _user(s, username)
        p = s.get(Project, scope.project_id)
        assert p is not None
        if u.id == p.owner_id:
            raise ProjectError("projects.member_is_owner", "state", name=u.username)
        if u.disabled:
            raise ProjectError("projects.user_disabled", "state", name=u.username)
        m = s.scalar(select(ProjectMember).where(ProjectMember.project_id == p.id, ProjectMember.user_id == u.id))
        if m is None:
            s.add(ProjectMember(project_id=p.id, user_id=u.id, role=role))
        else:
            m.role = role
        _workspace(s, u.id)
        s.flush()
        _log.info("项目成员：%s %s → %s（操作者 %s）", scope.slug, u.username, role, scope.identity.username)
        return {"members": _member_rows(s, p)}


def remove_member(db_url: str, scope: Scope, username: str) -> dict[str, Any]:
    """移除成员（属主与管理员）；成员自己退出项目也走这里。"""
    self_leave = scope.identity.username.lower() == username.lower() and scope.role in MEMBER_ROLES
    if not self_leave:
        require_manage(scope)
    with store.session(db_url) as s:
        u = _user(s, username)
        p = s.get(Project, scope.project_id)
        assert p is not None
        m = s.scalar(select(ProjectMember).where(ProjectMember.project_id == p.id, ProjectMember.user_id == u.id))
        if m is None:
            raise ProjectError("projects.member_not_found", "not_found", name=username)
        s.delete(m)
        s.execute(
            update(Workspace)
            .where(Workspace.user_id == u.id, Workspace.default_project_id == p.id)
            .values(default_project_id=None)
        )
        s.flush()
        return {"members": _member_rows(s, p)}


def transfer(db_url: str, scope: Scope, username: str, keep_as: str | None = "edit") -> dict[str, Any]:
    """把项目转交给其他账号（属主与管理员）。原属主默认留作可编辑成员（keep_as 为空时退出）；
    项目设置里用到的、原属主私有的翻译规则集复制一份给新属主（D-0179）。"""
    require_manage(scope)
    if keep_as is not None and keep_as not in MEMBER_ROLES:
        raise ProjectError("projects.bad_member_role", role=keep_as)
    with store.session(db_url) as s:
        u = _user(s, username)
        if u.disabled:
            raise ProjectError("projects.user_disabled", "state", name=u.username)
        p = s.get(Project, scope.project_id)
        assert p is not None
        old = p.owner_id
        if old == u.id:
            raise ProjectError("projects.already_owner", "state", name=u.username)
        s.execute(delete(ProjectMember).where(ProjectMember.project_id == p.id, ProjectMember.user_id == u.id))
        if old is not None and keep_as:
            s.add(ProjectMember(project_id=p.id, user_id=old, role=keep_as))
        if old is not None:
            s.execute(
                update(Workspace)
                .where(Workspace.user_id == old, Workspace.default_project_id == p.id)
                .values(default_project_id=None if not keep_as else p.id)
            )
        p.owner_id = u.id
        p.updated_at = _now()
        _workspace(s, u.id)
        settings = _settings(p)
        old_user = s.get(User, old) if old is not None else None
        old_name = old_user.username if old_user is not None else ""
        s.flush()
        new_owner = u.username
        new_id = u.id
    copied = None
    if settings.get("rule_set") and old is not None:
        from lmesh.core import assets

        copied = assets.copy_ruleset_for(db_url, str(settings["rule_set"]), old, new_id, new_owner)
        if copied:
            with store.session(db_url) as s:
                p = s.get(Project, scope.project_id)
                assert p is not None
                p.settings = {**(p.settings or {}), "rule_set": copied}
    audit(db_url, scope.identity, scope.project_id, scope.slug, "transfer", {"from": old_name, "to": new_owner})
    return {
        "project": scope.slug,
        "owner": new_owner,
        "previous_owner": old_name,
        "kept_as": keep_as,
        "rule_set_copied": copied,
    }


# ---------------------------------------------------------------- 引用公共设备、复制设备


def _public_device(s: Any, device_id: int) -> Device:
    dev = s.get(Device, device_id)
    if dev is None or dev.project_id is not None:
        raise ProjectError("projects.public_not_found", "not_found", device=device_id)
    return dev


def _name_taken(s: Any, project_id: int, name: str, ignore: int | None = None) -> bool:
    q = select(Device.id).where(Device.project_id == project_id, Device.name == name)
    if s.scalar(q) not in (None, ignore):
        return True
    refs = select(ProjectDeviceRef.device_id).where(ProjectDeviceRef.project_id == project_id)
    hit = s.scalar(select(Device.id).where(Device.id.in_(refs), Device.name == name))
    return hit is not None and hit != ignore


def add_ref(db_url: str, scope: Scope, device_id: int, version_id: int | None = None) -> dict[str, Any]:
    """引用公共设备：version_id 为空时跟随最新版本，否则固定在该版本。项目里已有同名设备时 409。"""
    require_write(scope)
    with store.session(db_url) as s:
        dev = _public_device(s, device_id)
        if version_id is not None:
            v = s.get(ConfigVersion, version_id)
            if v is None or v.device_id != device_id:
                raise ProjectError("projects.version_not_found", "not_found", version=version_id)
        ref = _ref(s, scope.project_id, device_id)
        if ref is None:
            if _name_taken(s, scope.project_id, dev.name):
                raise ProjectError("projects.name_taken", "state", name=dev.name)
            ref = ProjectDeviceRef(project_id=scope.project_id, device_id=device_id, version_id=version_id)
            s.add(ref)
        else:
            ref.version_id = version_id
        s.flush()
        return {
            "device_id": device_id,
            "name": dev.name,
            "policy": "pin" if version_id else "follow",
            "version_id": version_id,
        }


def set_ref(db_url: str, scope: Scope, device_id: int, version_id: int | None) -> dict[str, Any]:
    """改引用的版本策略：固定到某个版本，或跟随最新（version_id 为空）。"""
    require_write(scope)
    with store.session(db_url) as s:
        if _ref(s, scope.project_id, device_id) is None:
            raise ProjectError("projects.ref_not_found", "not_found", device=device_id)
    return add_ref(db_url, scope, device_id, version_id)


def remove_ref(db_url: str, scope: Scope, device_id: int) -> dict[str, Any]:
    """解除引用（项目中“删除”引用的公共设备）：本项目对它的忽略项一并删除，以它为基线的检查项目基线置空。"""
    require_write(scope)
    with store.session(db_url) as s:
        ref = _ref(s, scope.project_id, device_id)
        if ref is None:
            raise ProjectError("projects.ref_not_found", "not_found", device=device_id)
        s.delete(ref)
        s.execute(
            delete(CheckIgnore).where(CheckIgnore.project_id == scope.project_id, CheckIgnore.device_id == device_id)
        )
        cleared = s.execute(
            update(CheckProject)
            .where(CheckProject.project_id == scope.project_id, CheckProject.device_id == device_id)
            .values(device_id=None, version_id=None)
        ).rowcount  # type: ignore[attr-defined]
    from lmesh.core import script_check

    script_check.clear_cache()
    return {"unreferenced": True, "device_id": device_id, "baseline_cleared": int(cleared or 0)}


def copy_device(
    db_url: str,
    target: Scope,
    device_id: int,
    version_id: int | None = None,
    name: str | None = None,
    source_label: str = "",
) -> dict[str, Any]:
    """把设备（公共设备或其他项目的设备）的一个版本复制为目标项目的私有设备（默认复制来源中的当前版本）。
    调用方负责检查来源可读；目标项目要可写。同名时自动改名（-2、-3…）。"""
    require_write(target)
    with store.session(db_url) as s:
        src = s.get(Device, device_id)
        if src is None:
            raise ProjectError("projects.device_not_found", "not_found", device=device_id)
        if version_id is None:
            version_id = current_version_id(s, device_id)
        ver = s.get(ConfigVersion, version_id) if version_id else None
        if ver is None or ver.device_id != device_id:
            raise ProjectError("projects.version_not_found", "not_found", version=version_id)
        seq = int(
            s.scalar(
                select(func.count())
                .select_from(ConfigVersion)
                .where(ConfigVersion.device_id == device_id, ConfigVersion.id <= ver.id)
            )
            or 0
        )
        base = (name or src.name).strip()[:190] or src.name
        new_name, n = base, 2
        while _name_taken(s, target.project_id, new_name):
            new_name, n = f"{base}-{n}", n + 1
        src_proj = s.get(Project, src.project_id) if src.project_id else None
        note = {
            "type": "copy",
            "project": src_proj.slug if src_proj else None,
            "public": src.project_id is None,
            "device": src.name,
            "device_id": src.id,
            "seq": seq,
            "label": source_label,
        }
        dev = Device(
            name=new_name,
            vendor=src.vendor,
            platform=src.platform,
            sw_version=src.sw_version,
            profile=src.profile,
            project_id=target.project_id,
            origin="copy",
            origin_note=note,
        )
        s.add(dev)
        s.flush()
        nv = ConfigVersion(
            device_id=dev.id,
            source_name=ver.source_name,
            raw_text=ver.raw_text,
            structured=ver.structured,
            sanitized=ver.sanitized,
            kb_version=ver.kb_version,
            collected_at=ver.collected_at,
            content_hash=ver.content_hash,
            graph_gz=ver.graph_gz,
            tag=None,
            change_summary=None,
        )
        s.add(nv)
        s.flush()
        for n_ in s.scalars(select(Node).where(Node.version_id == ver.id)):
            s.add(
                Node(
                    version_id=nv.id,
                    node_key=n_.node_key,
                    schema_type=n_.schema_type,
                    value=n_.value,
                    origin=n_.origin,
                    line_start=n_.line_start,
                    line_end=n_.line_end,
                    parent_key=n_.parent_key,
                )
            )
        for e in s.scalars(select(Edge).where(Edge.version_id == ver.id)):
            s.add(Edge(version_id=nv.id, src_key=e.src_key, dst_key=e.dst_key, kind=e.kind, attrs=e.attrs))
        for u in s.scalars(select(UnknownLine).where(UnknownLine.version_id == ver.id)):
            s.add(UnknownLine(version_id=nv.id, line_no=u.line_no, text=u.text, view=u.view, pattern=u.pattern))
        s.add(
            ConfigImport(
                device_id=dev.id,
                version_id=nv.id,
                source_kind="other",
                source_name=f"copy:{src.name}#{seq}"[:400],
                actor=target.identity.username,
                duplicate=False,
            )
        )
        s.flush()
        return {
            "device_id": dev.id,
            "name": dev.name,
            "renamed": dev.name != base,
            "version_id": nv.id,
            "from": note,
        }


# ---------------------------------------------------------------- 复制项目


def copy_project(db_url: str, scope: Scope, ident: Identity, data: dict[str, Any]) -> dict[str, Any]:
    """复制为调用者的新项目：设置、规则调整、私有设备（当前版本）、引用（同样的版本策略）、脚本（当前内容）；
    不复制成员。只读成员也可以复制（D-0179）。"""
    created = create_project(
        db_url,
        ident,
        {
            "name": data.get("name") or "",
            "slug": data.get("slug"),
            "description": data.get("description"),
        },
    )
    target = resolve(db_url, ident, created["slug"])
    if ident.user_id is None:
        target = Scope(target.project_id, target.slug, "admin", ident, {})
    id_map: dict[int, int] = {}
    with store.session(db_url) as s:
        src = s.get(Project, scope.project_id)
        dst = s.get(Project, target.project_id)
        assert src is not None and dst is not None
        dst.settings = dict(src.settings or {})
        for o in s.scalars(select(ProjectRuleOverride).where(ProjectRuleOverride.project_id == src.id)):
            s.add(
                ProjectRuleOverride(
                    project_id=dst.id,
                    rule=o.rule,
                    enabled=o.enabled,
                    severity=o.severity,
                    reason=o.reason,
                    updated_by=ident.username,
                )
            )
        for r in s.scalars(select(ProjectDeviceRef).where(ProjectDeviceRef.project_id == src.id)):
            s.add(ProjectDeviceRef(project_id=dst.id, device_id=r.device_id, version_id=r.version_id))
            id_map[r.device_id] = r.device_id
        private = list(s.scalars(select(Device.id).where(Device.project_id == src.id).order_by(Device.id)))
    if data.get("devices", True):
        for dev_id in private:
            res = copy_device(db_url, target, dev_id, _version_of(db_url, dev_id), source_label=scope.slug)
            id_map[dev_id] = res["device_id"]
    scripts = 0
    if data.get("scripts", True):
        scripts = _copy_scripts(db_url, scope.project_id, target.project_id, id_map, ident)
    out = get_project(db_url, target)
    out["copied"] = {"devices": len(private) if data.get("devices", True) else 0, "scripts": scripts}
    return out


def _version_of(db_url: str, device_id: int) -> int | None:
    with store.session(db_url) as s:
        return s.scalar(
            select(ConfigVersion.id)
            .where(ConfigVersion.device_id == device_id)
            .order_by(ConfigVersion.id.desc())
            .limit(1)
        )


def _copy_scripts(db_url: str, src_pid: int, dst_pid: int, id_map: dict[int, int], ident: Identity) -> int:
    n = 0
    with store.session(db_url) as s:
        for cp in s.scalars(select(CheckProject).where(CheckProject.project_id == src_pid).order_by(CheckProject.id)):
            new_dev = id_map.get(cp.device_id) if cp.device_id else None
            ncp = CheckProject(
                name=cp.name,
                description=cp.description,
                device_id=new_dev,
                version_id=cp.version_id if new_dev == cp.device_id else None,
                profile=cp.profile,
                default_kind=cp.default_kind,
                order_check=cp.order_check,
                ai_check=cp.ai_check,
                ai_rules=cp.ai_rules,
                user_id=ident.user_id,
                project_id=dst_pid,
            )
            s.add(ncp)
            s.flush()
            for sc in s.scalars(select(CheckScript).where(CheckScript.project_id == cp.id).order_by(CheckScript.id)):
                ns = CheckScript(
                    project_id=ncp.id, name=sc.name, kind=sc.kind, content=sc.content, position=sc.position
                )
                s.add(ns)
                s.flush()
                s.add(
                    CheckRevision(
                        script_id=ns.id,
                        seq=1,
                        content=sc.content,
                        source="create",
                        note={"copied_from": sc.id},
                        user_id=ident.user_id,
                        author=ident.username,
                    )
                )
                n += 1
    return n


# ---------------------------------------------------------------- 公共设备库（管理员）


def list_public(db_url: str) -> list[dict[str, Any]]:
    """公共设备：版本数、最新版本、引用它的项目（跟随最新 / 固定的版本）。"""
    with store.session(db_url) as s:
        out = []
        for d in s.scalars(select(Device).where(Device.project_id.is_(None)).order_by(Device.name)):
            vers = list(
                s.execute(
                    select(ConfigVersion.id, ConfigVersion.collected_at)
                    .where(ConfigVersion.device_id == d.id)
                    .order_by(ConfigVersion.id)
                ).all()
            )
            latest = vers[-1] if vers else None
            refs = []
            for r, p in s.execute(
                select(ProjectDeviceRef, Project)
                .join(Project, Project.id == ProjectDeviceRef.project_id)
                .where(ProjectDeviceRef.device_id == d.id)
                .order_by(Project.slug)
            ).all():
                owner = s.get(User, p.owner_id) if p.owner_id else None
                refs.append(
                    {
                        "project": p.slug,
                        "name": p.name,
                        "owner": owner.username if owner else None,
                        "policy": "pin" if r.version_id else "follow",
                        "version_id": r.version_id,
                        "seq": next((i + 1 for i, v in enumerate(vers) if v[0] == r.version_id), None),
                    }
                )
            out.append(
                {
                    "id": d.id,
                    "name": d.name,
                    "vendor": d.vendor,
                    "sw_version": d.sw_version,
                    "profile": d.profile,
                    "versions": len(vers),
                    "latest_version_id": latest[0] if latest else None,
                    "collected_at": iso(latest[1]) if latest else None,
                    "refs": refs,
                    "follow": sum(1 for r in refs if r["policy"] == "follow"),
                    "pinned": sum(1 for r in refs if r["policy"] == "pin"),
                }
            )
        return out


def delete_public(db_url: str, device_id: int, force: bool = False, actor: str = "") -> dict[str, Any]:
    """删除公共设备：还有项目引用时拒绝（data 列出项目）；force 时一并解除引用。"""
    with store.session(db_url) as s:
        dev = _public_device(s, device_id)
        refs = [
            p.slug
            for p in s.scalars(
                select(Project)
                .join(ProjectDeviceRef, ProjectDeviceRef.project_id == Project.id)
                .where(ProjectDeviceRef.device_id == device_id)
            )
        ]
        if refs and not force:
            raise ProjectError("projects.public_referenced", "state", data={"projects": refs}, n=len(refs))
        name = dev.name
        versions = _delete_device_rows(s, device_id)
    from lmesh.core import script_check

    script_check.clear_cache()
    _log.info(
        "公共设备已删除：%s（编号 %d，版本 %d 个，解除引用 %d 个，操作者 %s）",
        name,
        device_id,
        versions,
        len(refs),
        actor or "-",
    )
    return {"deleted": True, "device": {"id": device_id, "name": name}, "versions": versions, "unreferenced": refs}


# ---------------------------------------------------------------- 项目级规则调整


def list_overrides(db_url: str, scope: Scope) -> list[dict[str, Any]]:
    with store.session(db_url) as s:
        rows = s.scalars(
            select(ProjectRuleOverride)
            .where(ProjectRuleOverride.project_id == scope.project_id)
            .order_by(ProjectRuleOverride.rule)
        )
        return [
            {
                "rule": r.rule,
                "enabled": r.enabled,
                "severity": r.severity,
                "reason": r.reason,
                "updated_by": r.updated_by,
                "updated_at": iso(r.updated_at),
            }
            for r in rows
        ]


def set_override(
    db_url: str,
    scope: Scope,
    rule: str,
    enabled: bool | None,
    severity: str | None,
    reason: str,
    known: set[str] | None,
) -> dict[str, Any]:
    """本项目关闭某条规则或改级别（属主与可编辑成员，D-0176）；原因必填。known 为已知规则编号（校验用）。"""
    require_write(scope)
    rule = (rule or "").strip()
    if not rule or len(rule) > 120 or (known is not None and rule not in known):
        raise ProjectError("projects.rule_not_found", "not_found", rule=rule)
    if severity is not None and severity not in SEVERITIES:
        raise ProjectError("projects.bad_severity", severity=severity)
    reason = (reason or "").strip()
    if not reason:
        raise ProjectError("projects.reason_required")
    with store.session(db_url) as s:
        o = s.scalar(
            select(ProjectRuleOverride).where(
                ProjectRuleOverride.project_id == scope.project_id, ProjectRuleOverride.rule == rule
            )
        )
        if o is None:
            o = ProjectRuleOverride(project_id=scope.project_id, rule=rule)
            s.add(o)
        if enabled is not None:
            o.enabled = enabled
        elif o.id is None:
            o.enabled = True
        o.severity = severity
        o.reason = reason[:2000]
        o.updated_by = scope.identity.username
        o.updated_at = _now()
        s.flush()
    return {"rule": rule, "enabled": o.enabled, "severity": o.severity, "reason": o.reason}


def delete_override(db_url: str, scope: Scope, rule: str) -> dict[str, Any]:
    """恢复为共享规则的设置。"""
    require_write(scope)
    with store.session(db_url) as s:
        n = s.execute(
            delete(ProjectRuleOverride).where(
                ProjectRuleOverride.project_id == scope.project_id, ProjectRuleOverride.rule == rule
            )
        ).rowcount  # type: ignore[attr-defined]
    if not n:
        raise ProjectError("projects.override_not_found", "not_found", rule=rule)
    return {"rule": rule, "restored": True}


def apply_overrides(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """检查发现套用当前项目的规则调整：关闭的规则去掉，改了级别的换级别并标出 project_override。"""
    ov = rule_overrides()
    if not ov:
        return findings
    out = []
    for f in findings:
        o = ov.get(f.get("rule", ""))
        if o is None:
            out.append(f)
            continue
        if not o.get("enabled", True):
            continue
        if o.get("severity"):
            f = {**f, "severity": o["severity"], "shared_severity": f.get("severity")}
        f["project_override"] = {"severity": o.get("severity"), "reason": o.get("reason")}
        out.append(f)
    return out


# ---------------------------------------------------------------- 审计与最近活动


_ENTER_SEEN: dict[tuple[str, int], float] = {}
ENTER_EVERY_S = 1800.0


def audit(
    db_url: str, ident: Identity, project_id: int | None, slug: str, action: str, detail: dict[str, Any] | None = None
) -> None:
    """写审计：数据库 audit_events（界面查看）与 lmesh.audit 日志（logs/）；不记录请求内容。"""
    with store.session(db_url) as s:
        s.add(
            AuditEvent(
                actor=ident.username,
                user_id=ident.user_id,
                project_id=project_id,
                project_slug=slug,
                action=action,
                detail=detail,
            )
        )
    _audit_log.info("%s %s %s %s", ident.username, action, slug or "-", detail or "")


def admin_access(db_url: str, scope: Scope, method: str, path: str, write: bool) -> None:
    """管理员访问他人项目：写操作每次记录；只读访问同一项目 30 分钟内只记一次“进入项目”。"""
    if scope.role != "admin":
        return
    import time

    key = (scope.identity.username, scope.project_id)
    now = time.monotonic()
    if not write:
        last = _ENTER_SEEN.get(key)
        if last is not None and now - last < ENTER_EVERY_S:
            return
        _ENTER_SEEN[key] = now
    audit(
        db_url,
        scope.identity,
        scope.project_id,
        scope.slug,
        "write" if write else "enter",
        {"method": method, "path": path},
    )


def list_audit(db_url: str, project: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    with store.session(db_url) as s:
        q = select(AuditEvent).order_by(AuditEvent.at.desc(), AuditEvent.id.desc()).limit(max(1, min(limit, 2000)))
        if project:
            q = q.where(AuditEvent.project_slug == project)
        return [
            {
                "id": e.id,
                "at": iso(e.at),
                "actor": e.actor,
                "project": e.project_slug,
                "project_id": e.project_id,
                "action": e.action,
                "detail": e.detail,
            }
            for e in s.scalars(q)
        ]


def touch(db_url: str, scope: Scope, action: str) -> None:
    """记录项目的最近活动（写操作）。"""
    with store.session(db_url) as s:
        p = s.get(Project, scope.project_id)
        if p is not None:
            p.last_activity = {"actor": scope.identity.username, "action": action, "at": iso(_now())}
            p.updated_at = _now()


# ---------------------------------------------------------------- 删除账号时的项目


def owned_projects(db_url: str, username: str, non_empty_only: bool = False) -> list[dict[str, Any]]:
    """账号拥有的项目；non_empty_only 时不含空项目（没有设备、引用、脚本与成员，例如自动建的默认项目）。"""
    with store.session(db_url) as s:
        u = _user(s, username)
        out = []
        for p in s.scalars(select(Project).where(Project.owner_id == u.id).order_by(Project.slug)):
            c = _counts(s, p)
            empty = not (c["devices"] or c["check_projects"]) and len(_member_rows(s, p)) <= 1
            if non_empty_only and empty:
                continue
            out.append({"id": p.id, "slug": p.slug, "name": p.name, "empty": empty, **c})
        return out


def dispose_user_projects(db_url: str, username: str, transfer_to: str | None, actor: Identity) -> dict[str, Any]:
    """删除账号前处理他的项目：transfer_to 给出时全部转交给该账号，否则一并删除。"""
    owned = owned_projects(db_url, username)
    done = []
    for p in owned:
        sc = scope_by_id(db_url, p["id"], actor)
        sc = Scope(sc.project_id, sc.slug, "admin", actor, sc.overrides)
        if transfer_to and not p["empty"]:
            transfer(db_url, sc, transfer_to, keep_as=None)
        else:
            delete_project(db_url, sc)
            audit(db_url, actor, None, sc.slug, "delete", {"reason": "account_deleted", "owner": username})
        done.append(p["slug"])
    return {"projects": done, "action": "transfer" if transfer_to else "delete", "to": transfer_to}
