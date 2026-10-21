"""创建项目的权限与加入项目（M9-8，REQ-050）的接口。

- router（需要登录）：发现项目、申请加入、我的申请、我的创建权限与申请、通知数、邀请链接的查看与使用。
- project（只挂在 /api/v1/projects/{project}/… 下）：加入申请的审批、邀请链接（属主、管理成员、管理员；由 core 判断）。
- admin（管理员）：创建权限的申请与处理；单独授权在 PUT /users/{username}（can_create_projects）。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from lmesh.api.common import db_of as _db
from lmesh.api.common import ok, principal_of, project_error, require_admin, require_token
from lmesh.core import joining, projects

router = APIRouter(dependencies=[Depends(require_token)])
project = APIRouter(dependencies=[Depends(require_token)])
admin = APIRouter(dependencies=[Depends(require_admin)])

Status = Literal["pending", "approved", "declined", "cancelled", "all"]


def _ident(request: Request) -> projects.Identity:
    return principal_of(request).identity()


def _scope(request: Request) -> projects.Scope:
    return request.state.scope  # type: ignore[no-any-return]


def _st(status: str) -> str | None:
    return None if status == "all" else status


# ---------------------------------------------------------------- 发现项目与我的申请


@router.get(
    "/discover",
    summary="发现项目：可被搜索的项目（只有名称、简介、属主、设备数）与我在其中的状态（owner / member / pending / declined / none）",
)
def discover(
    request: Request, q: str = Query("", max_length=200, description="按名称、简介、属主、标识搜索")
) -> dict[str, Any]:
    return ok(request, joining.discover(_db(request), _ident(request), q))


class JoinBody(BaseModel):
    role: Literal["read", "edit"] = Field("read", description="希望的角色；“管理”只能由审批人给")
    reason: str = Field("", max_length=joining.REASON_MAX, description="申请理由（可选）")


@router.post(
    "/discover/{project_ref}/join-requests",
    summary="申请加入可被搜索的项目（project_ref：编号或 属主~标识）；已是成员或已有待审批的申请时 409",
)
def request_join(request: Request, project_ref: str, body: JoinBody) -> dict[str, Any]:
    try:
        return ok(request, joining.request_join(_db(request), _ident(request), project_ref, body.role, body.reason))
    except projects.ProjectError as e:
        raise project_error(e) from e


@router.get("/me/join-requests", summary="我提交的加入申请（新的在前）")
def my_requests(request: Request, status: Status = "all") -> dict[str, Any]:
    try:
        return ok(request, {"requests": joining.my_requests(_db(request), _ident(request), _st(status))})
    except projects.ProjectError as e:
        raise project_error(e) from e


@router.delete("/me/join-requests/{request_id}", summary="撤回我待审批的加入申请")
def cancel_request(request: Request, request_id: int) -> dict[str, Any]:
    try:
        return ok(request, joining.cancel_request(_db(request), _ident(request), request_id))
    except projects.ProjectError as e:
        raise project_error(e) from e


@router.get(
    "/me/create-permission",
    summary="我能否新建项目（can_create）、总开关（open）、是否单独授权（granted）与我最近的创建权限申请",
)
def create_permission(request: Request) -> dict[str, Any]:
    return ok(request, joining.creation_status(_db(request), _ident(request)))


class ReasonBody(BaseModel):
    reason: str = Field("", max_length=joining.REASON_MAX)


@router.post(
    "/me/create-permission/request",
    summary="申请创建项目的权限（通知管理员）；已经能创建或已有待处理的申请时 409",
)
def request_create(request: Request, body: ReasonBody) -> dict[str, Any]:
    try:
        return ok(request, joining.request_create(_db(request), _ident(request), body.reason))
    except projects.ProjectError as e:
        raise project_error(e) from e


@router.delete("/me/create-permission/request", summary="撤回我待处理的创建权限申请")
def cancel_create(request: Request) -> dict[str, Any]:
    try:
        return ok(request, joining.cancel_create_request(_db(request), _ident(request)))
    except projects.ProjectError as e:
        raise project_error(e) from e


@router.get(
    "/me/notifications",
    summary="等我处理的：我是属主或管理成员的项目里待审批的加入申请（按项目）；管理员另有创建权限的申请",
)
def notifications(request: Request) -> dict[str, Any]:
    return ok(request, joining.notifications(_db(request), _ident(request)))


# ---------------------------------------------------------------- 邀请链接（使用）


@router.get(
    "/invites/{token}",
    summary="打开邀请链接：项目名称、简介、属主、设备数、加入后的角色、是否需审批、有效期、链接状态（active / expired / revoked）",
)
def invite_info(request: Request, token: str) -> dict[str, Any]:
    try:
        return ok(request, joining.invite_info(_db(request), _ident(request), token))
    except projects.ProjectError as e:
        raise project_error(e) from e


@router.post(
    "/invites/{token}/accept",
    summary="用邀请链接加入：status=joined 已加入 / pending 已提交申请（链接要求审批）/ member 已是成员；失效时 409",
)
def invite_accept(request: Request, token: str, body: ReasonBody) -> dict[str, Any]:
    try:
        return ok(request, joining.accept_invite(_db(request), _ident(request), token, body.reason))
    except projects.ProjectError as e:
        raise project_error(e) from e


# ---------------------------------------------------------------- 项目内：审批与邀请链接


@project.get("/join-requests", summary="项目的加入申请（属主、管理成员、管理员）；status 默认 pending")
def list_requests(request: Request, status: Status = "pending") -> dict[str, Any]:
    try:
        return ok(request, {"requests": joining.list_requests(_db(request), _scope(request), _st(status))})
    except projects.ProjectError as e:
        raise project_error(e) from e


class ApproveBody(BaseModel):
    role: Literal["manage", "edit", "read"] | None = Field(None, description="给的角色；不给时按申请的角色")


@project.post("/join-requests/{request_id}/approve", summary="通过加入申请（可改角色，可给“管理”）")
def approve(request: Request, request_id: int, body: ApproveBody) -> dict[str, Any]:
    try:
        return ok(request, joining.decide(_db(request), _scope(request), request_id, True, body.role))
    except projects.ProjectError as e:
        raise project_error(e) from e


class NoteBody(BaseModel):
    note: str = Field("", max_length=joining.NOTE_MAX, description="说明（可选，申请人能看到）")


@project.post("/join-requests/{request_id}/decline", summary="拒绝加入申请")
def decline(request: Request, request_id: int, body: NoteBody) -> dict[str, Any]:
    try:
        return ok(request, joining.decide(_db(request), _scope(request), request_id, False, note=body.note))
    except projects.ProjectError as e:
        raise project_error(e) from e


@project.get("/invites", summary="邀请链接（属主、管理成员、管理员）：角色、是否需审批、有效期、使用次数、状态")
def list_invites(request: Request) -> dict[str, Any]:
    try:
        return ok(request, {"invites": joining.list_invites(_db(request), _scope(request))})
    except projects.ProjectError as e:
        raise project_error(e) from e


class InviteBody(BaseModel):
    role: Literal["manage", "edit", "read"] = "read"
    days: int = Field(joining.INVITE_DAYS_DEFAULT, ge=1, le=joining.INVITE_DAYS_MAX, description="有效天数")
    requires_approval: bool = Field(False, description="打开链接后仍需审批")
    note: str = Field("", max_length=200)


@project.post("/invites", summary="新建邀请链接：返回的 token / path 只出现这一次（服务器只存它的 SHA-256）")
def create_invite(request: Request, body: InviteBody) -> dict[str, Any]:
    try:
        return ok(
            request,
            joining.create_invite(
                _db(request), _scope(request), body.role, body.days, body.requires_approval, body.note
            ),
        )
    except projects.ProjectError as e:
        raise project_error(e) from e


@project.delete("/invites/{invite_id}", summary="撤销邀请链接")
def revoke_invite(request: Request, invite_id: int) -> dict[str, Any]:
    try:
        return ok(request, joining.revoke_invite(_db(request), _scope(request), invite_id))
    except projects.ProjectError as e:
        raise project_error(e) from e


# ---------------------------------------------------------------- 管理员：创建权限的申请


@admin.get("/admin/create-requests", summary="创建项目权限的申请（管理员）；status 默认 pending")
def create_requests(request: Request, status: Status = "pending") -> dict[str, Any]:
    rows = joining.list_create_requests(_db(request), _st(status))
    return ok(request, {"requests": rows, "count": len(rows)})


@admin.post("/admin/create-requests/{request_id}/approve", summary="通过创建权限的申请：给该账号单独授权")
def create_approve(request: Request, request_id: int) -> dict[str, Any]:
    try:
        return ok(request, joining.decide_create(_db(request), _ident(request), request_id, True))
    except projects.ProjectError as e:
        raise project_error(e) from e


@admin.post("/admin/create-requests/{request_id}/decline", summary="拒绝创建权限的申请")
def create_decline(request: Request, request_id: int, body: NoteBody) -> dict[str, Any]:
    try:
        return ok(request, joining.decide_create(_db(request), _ident(request), request_id, False, body.note))
    except projects.ProjectError as e:
        raise project_error(e) from e
