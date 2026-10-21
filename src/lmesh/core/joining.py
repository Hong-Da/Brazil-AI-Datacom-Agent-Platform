"""创建项目的权限与加入项目（M9-8，REQ-050）。CLI 与 API 共用。

- 创建权限：管理员始终可以；普通账号看系统设置“普通用户可以创建项目”（总开关，默认关）或管理员单独授权
  （users.can_create_projects）。没有项目也不能创建的账号可以一键申请，管理员在账号管理里授权或拒绝。
- 加入项目的三种方式：属主按用户名添加（projects.set_member）；搜索“可被搜索”的项目并申请（审批后加入）；
  邀请链接（有效期、角色、可选仍需审批，可撤销；链接里的令牌只存 SHA-256）。
- 审批人：属主、管理成员（manage）、系统管理员（Scope.can_manage）。通过时可以改角色。
- 可被搜索的项目对外只显示名称、简介、属主、设备数，不显示设备名、配置与成员。
- 申请、通过、拒绝、撤回、授权、邀请链接的建立 / 撤销 / 使用都写审计（projects.audit）。
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select

from lmesh.core import projects, store
from lmesh.core.projects import Identity, ProjectError, Scope
from lmesh.core.store.models import (
    Project,
    ProjectCreateRequest,
    ProjectInvite,
    ProjectJoinRequest,
    ProjectMember,
    User,
    iso,
)

REQUEST_ROLES = ("read", "edit")  # 申请时能选的角色；“管理”只能由审批人给
REASON_MAX = 500
NOTE_MAX = 500
INVITE_DAYS_DEFAULT = 7
INVITE_DAYS_MAX = 90
INVITE_PREFIX = "lmi_"
STATUSES = ("pending", "approved", "declined", "cancelled")

_log = logging.getLogger("lmesh.projects")


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _text(v: Any, limit: int) -> str:
    t = str(v or "").strip()
    if len(t) > limit:
        raise ProjectError("joining.too_long", n=limit)
    return t


def _account(s: Any, ident: Identity) -> User:
    """需要账号的操作（全局令牌与没有账号的命令行不行）。"""
    u = s.get(User, ident.user_id) if ident.user_id is not None else None
    if u is None:
        raise ProjectError("joining.need_account", "state")
    return u


def _devices(s: Any, p: Project) -> int:
    return int(projects._counts(s, p)["devices"])


def _owner_name(s: Any, p: Project) -> str | None:
    u = s.get(User, p.owner_id) if p.owner_id else None
    return u.username if u is not None else None


def _member_role(s: Any, p: Project, user_id: int) -> str | None:
    if p.owner_id == user_id:
        return "owner"
    r = s.scalar(select(ProjectMember.role).where(ProjectMember.project_id == p.id, ProjectMember.user_id == user_id))
    return str(r) if r else None


def _pending(s: Any, project_id: int, user_id: int) -> ProjectJoinRequest | None:
    q = select(ProjectJoinRequest).where(
        ProjectJoinRequest.project_id == project_id,
        ProjectJoinRequest.user_id == user_id,
        ProjectJoinRequest.status == "pending",
    )
    return s.scalar(q.order_by(ProjectJoinRequest.id.desc()).limit(1))  # type: ignore[no-any-return]


def _add_member(s: Any, p: Project, u: User, role: str) -> None:
    """加入或改角色（属主不变）；还没有默认项目时它成为默认项目。"""
    if p.owner_id == u.id:
        return
    m = s.scalar(select(ProjectMember).where(ProjectMember.project_id == p.id, ProjectMember.user_id == u.id))
    if m is None:
        s.add(ProjectMember(project_id=p.id, user_id=u.id, role=role))
    else:
        m.role = role
    ws = projects._workspace(s, u.id)
    if ws.default_project_id is None:
        ws.default_project_id = p.id
    s.flush()


# ---------------------------------------------------------------- 创建项目的权限


def creation_status(db_url: str, ident: Identity) -> dict[str, Any]:
    """我能不能新建项目、为什么，以及我的创建权限申请（最近一条）。"""
    with store.session(db_url) as s:
        u = s.get(User, ident.user_id) if ident.user_id is not None else None
        req = None
        if u is not None:
            r = s.scalar(
                select(ProjectCreateRequest)
                .where(ProjectCreateRequest.user_id == u.id)
                .order_by(ProjectCreateRequest.id.desc())
                .limit(1)
            )
            req = _create_req_dict(r, u.username) if r is not None else None
        return {
            "can_create": projects.can_create(s, ident),
            "open": projects.create_open(),
            "admin": ident.is_admin,
            "granted": bool(u is not None and u.can_create_projects),
            "request": req,
        }


def _create_req_dict(r: ProjectCreateRequest, username: str) -> dict[str, Any]:
    return {
        "id": r.id,
        "username": username,
        "reason": r.reason,
        "status": r.status,
        "decided_by": r.decided_by or None,
        "note": r.note or "",
        "created_at": iso(r.created_at),
        "decided_at": iso(r.decided_at),
    }


def request_create(db_url: str, ident: Identity, reason: str = "") -> dict[str, Any]:
    """申请创建项目的权限：已经能创建时 409（create_request.not_needed），已有待处理的申请时 409。"""
    text = _text(reason, REASON_MAX)
    with store.session(db_url) as s:
        u = _account(s, ident)
        if projects.can_create(s, ident):
            raise ProjectError("create_request.not_needed", "state")
        q = select(ProjectCreateRequest.id).where(
            ProjectCreateRequest.user_id == u.id, ProjectCreateRequest.status == "pending"
        )
        if s.scalar(q) is not None:
            raise ProjectError("create_request.pending", "state")
        r = ProjectCreateRequest(user_id=u.id, reason=text, status="pending")
        s.add(r)
        s.flush()
        out = _create_req_dict(r, u.username)
    projects.audit(db_url, ident, None, "", "create.request", {"request_id": out["id"]})
    return out


def cancel_create_request(db_url: str, ident: Identity) -> dict[str, Any]:
    with store.session(db_url) as s:
        u = _account(s, ident)
        r = s.scalar(
            select(ProjectCreateRequest).where(
                ProjectCreateRequest.user_id == u.id, ProjectCreateRequest.status == "pending"
            )
        )
        if r is None:
            raise ProjectError("create_request.not_found", "not_found")
        r.status, r.decided_at, r.decided_by = "cancelled", _now(), u.username
        s.flush()
        out = _create_req_dict(r, u.username)
    projects.audit(db_url, ident, None, "", "create.cancel", {"request_id": out["id"]})
    return out


def list_create_requests(db_url: str, status: str | None = "pending") -> list[dict[str, Any]]:
    """创建权限的申请（管理员）；status 为空时全部。"""
    with store.session(db_url) as s:
        q = select(ProjectCreateRequest, User).join(User, User.id == ProjectCreateRequest.user_id)
        if status:
            q = q.where(ProjectCreateRequest.status == status)
        rows = s.execute(q.order_by(ProjectCreateRequest.created_at.desc(), ProjectCreateRequest.id.desc())).all()
        return [_create_req_dict(r, u.username) for r, u in rows]


def decide_create(db_url: str, actor: Identity, request_id: int, approve: bool, note: str = "") -> dict[str, Any]:
    """管理员处理创建权限的申请：通过即给该账号单独授权；拒绝可以写说明。"""
    text = _text(note, NOTE_MAX)
    with store.session(db_url) as s:
        r = s.get(ProjectCreateRequest, request_id)
        if r is None:
            raise ProjectError("create_request.not_found", "not_found")
        if r.status != "pending":
            raise ProjectError("create_request.decided", "state")
        u = s.get(User, r.user_id)
        assert u is not None
        r.status = "approved" if approve else "declined"
        r.decided_by, r.decided_at, r.note = actor.username, _now(), text
        if approve:
            u.can_create_projects = True
        s.flush()
        out = _create_req_dict(r, u.username)
    projects.audit(
        db_url,
        actor,
        None,
        "",
        "create.grant" if approve else "create.decline",
        {"username": out["username"], "request_id": request_id},
    )
    return out


def set_create_permission(db_url: str, actor: Identity, username: str, allowed: bool) -> dict[str, Any]:
    """管理员给个别账号单独授权（或收回）创建项目；授权时把他待处理的申请一并标为通过。"""
    with store.session(db_url) as s:
        u = projects._user(s, username)
        changed = bool(u.can_create_projects) != bool(allowed)
        u.can_create_projects = bool(allowed)
        if allowed:
            for r in s.scalars(
                select(ProjectCreateRequest).where(
                    ProjectCreateRequest.user_id == u.id, ProjectCreateRequest.status == "pending"
                )
            ):
                r.status, r.decided_by, r.decided_at = "approved", actor.username, _now()
        name = u.username
    if changed:
        projects.audit(db_url, actor, None, "", "create.grant" if allowed else "create.revoke", {"username": name})
    return {"username": name, "can_create_projects": bool(allowed)}


# ---------------------------------------------------------------- 发现项目与加入申请


def _my_status(s: Any, p: Project, user_id: int | None) -> tuple[str, str | None, int | None]:
    """（状态，角色，申请编号）：owner / member / pending / declined / none。"""
    if user_id is None:
        return "none", None, None
    role = _member_role(s, p, user_id)
    if role == "owner":
        return "owner", "owner", None
    if role:
        return "member", role, None
    r = s.scalar(
        select(ProjectJoinRequest)
        .where(ProjectJoinRequest.project_id == p.id, ProjectJoinRequest.user_id == user_id)
        .order_by(ProjectJoinRequest.id.desc())
        .limit(1)
    )
    if r is not None and r.status in ("pending", "declined"):
        return str(r.status), str(r.role), int(r.id)
    return "none", None, None


def _public_card(s: Any, p: Project, user_id: int | None) -> dict[str, Any]:
    """对外显示的项目信息：只有名称、简介、属主、设备数（不含设备名、配置与成员）。"""
    st, role, rid = _my_status(s, p, user_id)
    return {
        "id": p.id,
        "ref": projects.full_ref(s, p),
        "name": p.name,
        "description": p.description or "",
        "owner": _owner_name(s, p),
        "devices": _devices(s, p),
        "my_status": st,
        "my_role": role,
        "request_id": rid,
    }


def discover(db_url: str, ident: Identity, q: str = "", limit: int = 100) -> dict[str, Any]:
    """可被搜索的项目（按名称、简介、属主、标识搜索，不区分大小写）。"""
    needle = (q or "").strip().lower()
    with store.session(db_url) as s:
        rows = []
        for p in s.scalars(select(Project).where(Project.discoverable.is_(True)).order_by(Project.name, Project.id)):
            card = _public_card(s, p, ident.user_id)
            hay = " ".join([card["name"], card["description"], card["owner"] or "", card["ref"]]).lower()
            if needle and needle not in hay:
                continue
            rows.append(card)
            if len(rows) >= max(1, min(limit, 500)):
                break
        return {"projects": rows, "count": len(rows)}


def _find_discoverable(s: Any, project: str | int) -> Project:
    """申请加入时找项目：编号或“属主/标识”；不可被搜索的项目一律当作不存在（不暴露是否存在）。"""
    p = None
    text = str(project).strip()
    if isinstance(project, int) or text.isdigit():
        p = s.get(Project, int(text))
    else:
        owner, slug = projects.split_ref(text)
        if owner is not None:
            u = s.scalar(select(User).where(func.lower(User.username) == owner.lower()))
            if u is not None:
                p = s.scalar(select(Project).where(Project.owner_id == u.id, Project.slug == slug))
    if p is None or not p.discoverable:
        raise ProjectError("projects.not_found", "not_found", project=text)
    return p  # type: ignore[no-any-return]


def _new_request(
    s: Any, p: Project, u: User, role: str, reason: str, via: str, invite_id: int | None = None
) -> ProjectJoinRequest:
    if _member_role(s, p, u.id):
        raise ProjectError("joining.already_member", "state", project=p.name)
    if _pending(s, p.id, u.id) is not None:
        raise ProjectError("joining.already_pending", "state", project=p.name)
    r = ProjectJoinRequest(
        project_id=p.id, user_id=u.id, role=role, reason=reason, via=via, invite_id=invite_id, status="pending"
    )
    s.add(r)
    s.flush()
    return r


def request_join(
    db_url: str, ident: Identity, project: str | int, role: str = "read", reason: str = ""
) -> dict[str, Any]:
    """申请加入可被搜索的项目（role：read / edit；“管理”只能由审批人给）。"""
    if role not in REQUEST_ROLES:
        raise ProjectError("joining.bad_role", role=role)
    text = _text(reason, REASON_MAX)
    with store.session(db_url) as s:
        u = _account(s, ident)
        p = _find_discoverable(s, project)
        r = _new_request(s, p, u, role, text, "search")
        out = _request_dict(s, r, p, u)
        pid, slug = p.id, p.slug
    projects.audit(db_url, ident, pid, slug, "join.request", {"request_id": out["id"], "role": role, "via": "search"})
    return out


def _request_dict(s: Any, r: ProjectJoinRequest, p: Project, u: User) -> dict[str, Any]:
    inv = s.get(ProjectInvite, r.invite_id) if r.invite_id else None
    return {
        "id": r.id,
        "project": {"id": p.id, "ref": projects.full_ref(s, p), "name": p.name, "owner": _owner_name(s, p)},
        "username": u.username,
        "role": r.role,
        "reason": r.reason or "",
        "via": r.via,
        "invite_prefix": inv.prefix if inv is not None else None,
        "status": r.status,
        "decided_by": r.decided_by or None,
        "decided_role": r.decided_role or None,
        "note": r.note or "",
        "created_at": iso(r.created_at),
        "decided_at": iso(r.decided_at),
    }


def my_requests(db_url: str, ident: Identity, status: str | None = None) -> list[dict[str, Any]]:
    """我提交的加入申请（新的在前）。"""
    with store.session(db_url) as s:
        u = _account(s, ident)
        q = select(ProjectJoinRequest, Project).join(Project, Project.id == ProjectJoinRequest.project_id)
        q = q.where(ProjectJoinRequest.user_id == u.id)
        if status:
            q = q.where(ProjectJoinRequest.status == status)
        rows = s.execute(q.order_by(ProjectJoinRequest.created_at.desc(), ProjectJoinRequest.id.desc())).all()
        return [_request_dict(s, r, p, u) for r, p in rows]


def cancel_request(db_url: str, ident: Identity, request_id: int) -> dict[str, Any]:
    """撤回自己待审批的申请。"""
    with store.session(db_url) as s:
        u = _account(s, ident)
        r = s.get(ProjectJoinRequest, request_id)
        if r is None or r.user_id != u.id:
            raise ProjectError("joining.request_not_found", "not_found", id=request_id)
        if r.status != "pending":
            raise ProjectError("joining.request_decided", "state", id=request_id)
        r.status, r.decided_at, r.decided_by = "cancelled", _now(), u.username
        p = s.get(Project, r.project_id)
        assert p is not None
        s.flush()
        out = _request_dict(s, r, p, u)
        pid, slug = p.id, p.slug
    projects.audit(db_url, ident, pid, slug, "join.cancel", {"request_id": request_id})
    return out


def list_requests(db_url: str, scope: Scope, status: str | None = "pending") -> list[dict[str, Any]]:
    """项目的加入申请（属主、管理成员、管理员）。"""
    projects.require_manage(scope)
    with store.session(db_url) as s:
        p = s.get(Project, scope.project_id)
        assert p is not None
        q = select(ProjectJoinRequest, User).join(User, User.id == ProjectJoinRequest.user_id)
        q = q.where(ProjectJoinRequest.project_id == p.id)
        if status:
            q = q.where(ProjectJoinRequest.status == status)
        rows = s.execute(q.order_by(ProjectJoinRequest.created_at.desc(), ProjectJoinRequest.id.desc())).all()
        return [_request_dict(s, r, p, u) for r, u in rows]


def decide(
    db_url: str, scope: Scope, request_id: int, approve: bool, role: str | None = None, note: str = ""
) -> dict[str, Any]:
    """审批加入申请（属主、管理成员、管理员）：通过时可以改角色（可给“管理”）；拒绝可以写说明。"""
    projects.require_manage(scope)
    text = _text(note, NOTE_MAX)
    with store.session(db_url) as s:
        r = s.get(ProjectJoinRequest, request_id)
        if r is None or r.project_id != scope.project_id:
            raise ProjectError("joining.request_not_found", "not_found", id=request_id)
        if r.status != "pending":
            raise ProjectError("joining.request_decided", "state", id=request_id)
        p = s.get(Project, r.project_id)
        u = s.get(User, r.user_id)
        assert p is not None and u is not None
        given = role or r.role
        if approve:
            if given not in projects.MEMBER_ROLES:
                raise ProjectError("projects.bad_member_role", role=given)
            if u.disabled:
                raise ProjectError("projects.user_disabled", "state", name=u.username)
            _add_member(s, p, u, given)
            r.decided_role = given
        r.status = "approved" if approve else "declined"
        r.decided_by, r.decided_at, r.note = scope.identity.username, _now(), text
        s.flush()
        out = _request_dict(s, r, p, u)
    detail: dict[str, Any] = {"request_id": request_id, "username": out["username"]}
    if approve:
        detail["role"] = given
    projects.audit(
        db_url, scope.identity, scope.project_id, scope.slug, "join.approve" if approve else "join.decline", detail
    )
    return out


# ---------------------------------------------------------------- 邀请链接


def _hash(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def _invite_state(inv: ProjectInvite, now: datetime | None = None) -> str:
    if inv.revoked_at is not None:
        return "revoked"
    exp = _aware(inv.expires_at)
    if exp is not None and exp <= (now or _now()):
        return "expired"
    return "active"


def _invite_dict(inv: ProjectInvite) -> dict[str, Any]:
    return {
        "id": inv.id,
        "prefix": inv.prefix,
        "role": inv.role,
        "requires_approval": bool(inv.requires_approval),
        "note": inv.note or "",
        "created_by": inv.created_by,
        "uses": int(inv.uses or 0),
        "expires_at": iso(inv.expires_at),
        "revoked_at": iso(inv.revoked_at),
        "created_at": iso(inv.created_at),
        "state": _invite_state(inv),
    }


def create_invite(
    db_url: str,
    scope: Scope,
    role: str = "read",
    days: int = INVITE_DAYS_DEFAULT,
    requires_approval: bool = False,
    note: str = "",
) -> dict[str, Any]:
    """新建邀请链接（属主、管理成员、管理员）。返回的 token 只出现这一次；数据库只存它的 SHA-256。"""
    projects.require_manage(scope)
    if role not in projects.MEMBER_ROLES:
        raise ProjectError("projects.bad_member_role", role=role)
    if not 1 <= int(days) <= INVITE_DAYS_MAX:
        raise ProjectError("invites.bad_days", max=INVITE_DAYS_MAX)
    text = _text(note, 200)
    token = INVITE_PREFIX + secrets.token_urlsafe(24)
    with store.session(db_url) as s:
        inv = ProjectInvite(
            project_id=scope.project_id,
            token_hash=_hash(token),
            prefix=token[len(INVITE_PREFIX) : len(INVITE_PREFIX) + 6],
            role=role,
            requires_approval=bool(requires_approval),
            note=text,
            created_by=scope.identity.username,
            uses=0,
            expires_at=_now() + timedelta(days=int(days)),
        )
        s.add(inv)
        s.flush()
        out = _invite_dict(inv)
    projects.audit(
        db_url,
        scope.identity,
        scope.project_id,
        scope.slug,
        "invite.create",
        {"invite_id": out["id"], "role": role, "days": int(days), "approval": bool(requires_approval)},
    )
    return {**out, "token": token, "path": f"/invite/{token}"}


def list_invites(db_url: str, scope: Scope) -> list[dict[str, Any]]:
    projects.require_manage(scope)
    with store.session(db_url) as s:
        q = select(ProjectInvite).where(ProjectInvite.project_id == scope.project_id)
        return [
            _invite_dict(i) for i in s.scalars(q.order_by(ProjectInvite.created_at.desc(), ProjectInvite.id.desc()))
        ]


def revoke_invite(db_url: str, scope: Scope, invite_id: int) -> dict[str, Any]:
    projects.require_manage(scope)
    with store.session(db_url) as s:
        inv = s.get(ProjectInvite, invite_id)
        if inv is None or inv.project_id != scope.project_id:
            raise ProjectError("invites.not_found", "not_found")
        if inv.revoked_at is None:
            inv.revoked_at = _now()
        s.flush()
        out = _invite_dict(inv)
    projects.audit(db_url, scope.identity, scope.project_id, scope.slug, "invite.revoke", {"invite_id": invite_id})
    return out


def _find_invite(s: Any, token: str) -> ProjectInvite:
    inv = s.scalar(select(ProjectInvite).where(ProjectInvite.token_hash == _hash(token or "")))
    if inv is None:
        raise ProjectError("invites.not_found", "not_found")
    return inv  # type: ignore[no-any-return]


def invite_info(db_url: str, ident: Identity, token: str) -> dict[str, Any]:
    """打开邀请链接时看到的：项目名称、简介、属主、设备数、加入后的角色、是否需审批、有效期、链接状态、我的状态。"""
    with store.session(db_url) as s:
        inv = _find_invite(s, token)
        p = s.get(Project, inv.project_id)
        assert p is not None
        card = _public_card(s, p, ident.user_id)
        return {
            "project": {k: card[k] for k in ("id", "ref", "name", "description", "owner", "devices")},
            "my_status": card["my_status"],
            "my_role": card["my_role"],
            "role": inv.role,
            "requires_approval": bool(inv.requires_approval),
            "expires_at": iso(inv.expires_at),
            "state": _invite_state(inv),
            "invited_by": inv.created_by,
        }


def accept_invite(db_url: str, ident: Identity, token: str, reason: str = "") -> dict[str, Any]:
    """登录用户打开邀请链接后加入：直接成为成员，或（链接要求审批时）提交加入申请。
    已是成员时不变（status=member）；已有待审批的申请时返回它（status=pending）。"""
    text = _text(reason, REASON_MAX)
    with store.session(db_url) as s:
        u = _account(s, ident)
        inv = _find_invite(s, token)
        state = _invite_state(inv)
        if state != "active":
            raise ProjectError(f"invites.{state}", "state")
        p = s.get(Project, inv.project_id)
        assert p is not None
        ref = projects.ref_of(s, p, ident)
        role = _member_role(s, p, u.id)
        if role:
            return {"status": "member", "project": ref, "role": role}
        if inv.requires_approval:
            old = _pending(s, p.id, u.id)
            if old is not None:
                return {"status": "pending", "project": ref, "request_id": old.id, "role": old.role}
            r = _new_request(s, p, u, inv.role, text, "invite", inv.id)
            inv.uses = int(inv.uses or 0) + 1
            rid, action = r.id, "join.request"
        else:
            _add_member(s, p, u, inv.role)
            inv.uses = int(inv.uses or 0) + 1
            rid, action = None, "invite.join"
        pid, slug, inv_id, inv_role = p.id, p.slug, inv.id, inv.role
    detail: dict[str, Any] = {"invite_id": inv_id, "role": inv_role, "via": "invite"}
    if rid is not None:
        detail["request_id"] = rid
    projects.audit(db_url, ident, pid, slug, action, detail)
    _log.info("邀请链接：%s %s 项目 %s", ident.username, "申请加入" if rid else "加入", slug)
    if rid is not None:
        return {"status": "pending", "project": ref, "request_id": rid, "role": inv_role}
    return {"status": "joined", "project": ref, "role": inv_role}


# ---------------------------------------------------------------- 通知（导航上的数字）


def notifications(db_url: str, ident: Identity) -> dict[str, Any]:
    """等我处理的：我是属主或管理成员的项目里待审批的加入申请（按项目）；管理员另有创建权限的申请。
    管理员能审批所有项目，但这里只数他自己参与管理的项目，避免全站的申请都提醒到每个管理员（决策记录）。"""
    with store.session(db_url) as s:
        by_project: list[dict[str, Any]] = []
        if ident.user_id is not None:
            managed = select(ProjectMember.project_id).where(
                ProjectMember.user_id == ident.user_id, ProjectMember.role == "manage"
            )
            q = (
                select(Project, func.count(ProjectJoinRequest.id))
                .join(ProjectJoinRequest, ProjectJoinRequest.project_id == Project.id)
                .where(
                    ProjectJoinRequest.status == "pending",
                    or_(Project.owner_id == ident.user_id, Project.id.in_(managed)),
                )
                .group_by(Project.id)
                .order_by(Project.name)
            )
            for p, n in s.execute(q).all():
                by_project.append({"id": p.id, "ref": projects.ref_of(s, p, ident), "name": p.name, "count": int(n)})
        create = 0
        if ident.is_admin:
            create = int(
                s.scalar(
                    select(func.count())
                    .select_from(ProjectCreateRequest)
                    .where(ProjectCreateRequest.status == "pending")
                )
                or 0
            )
        joins = sum(r["count"] for r in by_project)
        return {"join_requests": joins, "by_project": by_project, "create_requests": create, "total": joins + create}
