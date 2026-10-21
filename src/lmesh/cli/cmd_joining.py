"""创建项目的权限与加入项目（M9-8，REQ-050）的命令，挂在 lmesh project 与 lmesh user 下。

- lmesh project discover [搜索词]：可被搜索的项目（只有名称、简介、属主、设备数）
- lmesh project join <项目> [--role read|edit] [--reason]：申请加入（项目写编号或 属主/标识）
- lmesh project my-requests、lmesh project cancel-request <编号>
- lmesh project requests <项目>、approve <项目> <编号> [--role]、decline <项目> <编号> [--note]
- lmesh project discoverable <项目> on|off
- lmesh project invite <项目> [--role --days --approval --note]、invites <项目>、revoke-invite <项目> <编号>
- lmesh project accept-invite <令牌或链接> [--reason]
- lmesh project can-create、request-create [--reason]
- lmesh user grant-create <账号> [--revoke]、create-requests、approve-create <编号>、decline-create <编号> [--note]
以 --as 账号的身份（默认第一个管理员）。
"""

from __future__ import annotations

from typing import Annotated, Any

import typer

from lmesh.cli import output
from lmesh.cli.cmd_configs import require_db
from lmesh.cli.cmd_project import _fail, _role, _scope, _who, project_app
from lmesh.cli.cmd_user import user_app
from lmesh.cli.output import Ctx, emit
from lmesh.core import joining, projects


def _t16(v: str | None) -> str:
    return (v or "-")[:16].replace("T", " ")


def _st(c: Ctx, status: str) -> str:
    return c.t(f"join.status.{status}")


def _requests_text(c: Ctx, rows: list[dict[str, Any]], mine: bool) -> str:
    if not rows:
        return c.t("join.empty")
    head = [c.t(f"join.col.{k}") for k in ("id", "project" if mine else "user", "role", "status", "created", "reason")]
    body = [
        [
            str(r["id"]),
            r["project"]["ref"] if mine else r["username"],
            _role(c, r["decided_role"] or r["role"]),
            _st(c, r["status"]),
            _t16(r["created_at"]),
            (r["reason"] or "")[:40],
        ]
        for r in rows
    ]
    return output.table(body, head)


@project_app.command("discover", help="可被搜索的项目：名称、简介、属主、设备数 / discoverable projects")
def cmd_discover(ctx: typer.Context, query: Annotated[str, typer.Argument(help="搜索词（可选）")] = "") -> None:
    c = output.get(ctx)
    db = require_db(c)
    d = joining.discover(db, _who(c, db), query)
    rows = [
        [str(p["id"]), p["ref"], p["name"], p["owner"] or "-", str(p["devices"]), c.t(f"join.mine.{p['my_status']}")]
        for p in d["projects"]
    ]
    head = [c.t(f"join.col.{k}") for k in ("id", "project", "name", "owner", "devices", "status")]
    emit(c, d, output.table(rows, head) if rows else c.t("join.discover_empty"))


@project_app.command("join", help="申请加入可被搜索的项目（编号或 属主/标识）/ ask to join a project")
def cmd_join(
    ctx: typer.Context,
    project: Annotated[str, typer.Argument(help="项目编号或 属主/标识")],
    role: Annotated[str, typer.Option("--role", help="read | edit")] = "read",
    reason: Annotated[str, typer.Option("--reason", help="申请理由")] = "",
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    try:
        d = joining.request_join(db, _who(c, db), project, role, reason)
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, d, c.t("join.requested", project=d["project"]["ref"], id=d["id"]))


@project_app.command("my-requests", help="我提交的加入申请 / my join requests")
def cmd_my_requests(ctx: typer.Context) -> None:
    c = output.get(ctx)
    db = require_db(c)
    try:
        rows = joining.my_requests(db, _who(c, db))
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, {"requests": rows}, _requests_text(c, rows, True))


@project_app.command("cancel-request", help="撤回我待审批的加入申请 / cancel my join request")
def cmd_cancel_request(ctx: typer.Context, request_id: Annotated[int, typer.Argument(help="申请编号")]) -> None:
    c = output.get(ctx)
    db = require_db(c)
    try:
        d = joining.cancel_request(db, _who(c, db), request_id)
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, d, c.t("join.cancelled", id=request_id))


@project_app.command("requests", help="项目的加入申请（属主、管理成员、管理员）/ join requests of a project")
def cmd_requests(
    ctx: typer.Context,
    project: Annotated[str, typer.Argument(help="项目")],
    all_: Annotated[bool, typer.Option("--all", help="包括已处理的")] = False,
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    sc = _scope(c, db, project)
    try:
        rows = joining.list_requests(db, sc, None if all_ else "pending")
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, {"project": sc.label, "requests": rows}, _requests_text(c, rows, False))


@project_app.command("approve", help="通过加入申请（可用 --role 改角色）/ approve a join request")
def cmd_approve(
    ctx: typer.Context,
    project: Annotated[str, typer.Argument(help="项目")],
    request_id: Annotated[int, typer.Argument(help="申请编号")],
    role: Annotated[str | None, typer.Option("--role", help="manage | edit | read；不给时按申请的角色")] = None,
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    sc = _scope(c, db, project)
    try:
        d = joining.decide(db, sc, request_id, True, role)
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, d, c.t("join.approved", user=d["username"], role=_role(c, d["decided_role"])))


@project_app.command("decline", help="拒绝加入申请 / decline a join request")
def cmd_decline(
    ctx: typer.Context,
    project: Annotated[str, typer.Argument(help="项目")],
    request_id: Annotated[int, typer.Argument(help="申请编号")],
    note: Annotated[str, typer.Option("--note", help="说明（申请人能看到）")] = "",
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    sc = _scope(c, db, project)
    try:
        d = joining.decide(db, sc, request_id, False, note=note)
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, d, c.t("join.declined", user=d["username"]))


@project_app.command("discoverable", help="设置项目是否可被搜索（on / off）/ make a project discoverable")
def cmd_discoverable(
    ctx: typer.Context,
    project: Annotated[str, typer.Argument(help="项目")],
    state: Annotated[str, typer.Argument(help="on | off")],
) -> None:
    c = output.get(ctx)
    if state not in ("on", "off"):
        output.fail(c, output.EXIT_USAGE, c.t("join.on_off"))
    db = require_db(c)
    sc = _scope(c, db, project)
    try:
        d = projects.update_project(db, sc, {"discoverable": state == "on"})
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, d, c.t("join.discoverable_on" if d["discoverable"] else "join.discoverable_off", project=sc.label))


@project_app.command("invite", help="新建邀请链接（令牌只显示这一次）/ create an invite link")
def cmd_invite(
    ctx: typer.Context,
    project: Annotated[str, typer.Argument(help="项目")],
    role: Annotated[str, typer.Option("--role", help="manage | edit | read")] = "read",
    days: Annotated[int, typer.Option("--days", help="有效天数（1–90）")] = joining.INVITE_DAYS_DEFAULT,
    approval: Annotated[bool, typer.Option("--approval", help="打开链接后仍需审批")] = False,
    note: Annotated[str, typer.Option("--note", help="备注")] = "",
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    sc = _scope(c, db, project)
    try:
        d = joining.create_invite(db, sc, role, days, approval, note)
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, d, c.t("invite.created", path=d["path"], expires=_t16(d["expires_at"])))


@project_app.command("invites", help="项目的邀请链接 / invite links of a project")
def cmd_invites(ctx: typer.Context, project: Annotated[str, typer.Argument(help="项目")]) -> None:
    c = output.get(ctx)
    db = require_db(c)
    sc = _scope(c, db, project)
    try:
        rows = joining.list_invites(db, sc)
    except projects.ProjectError as e:
        _fail(c, e)
    body = [
        [
            str(v["id"]),
            v["prefix"] + "…",
            _role(c, v["role"]),
            c.t("invite.approval_yes") if v["requires_approval"] else c.t("invite.approval_no"),
            _t16(v["expires_at"]),
            str(v["uses"]),
            c.t(f"invite.state.{v['state']}"),
        ]
        for v in rows
    ]
    head = [c.t(f"invite.col.{k}") for k in ("id", "prefix", "role", "approval", "expires", "uses", "state")]
    emit(c, {"project": sc.label, "invites": rows}, output.table(body, head) if rows else c.t("invite.empty"))


@project_app.command("revoke-invite", help="撤销邀请链接 / revoke an invite link")
def cmd_revoke_invite(
    ctx: typer.Context,
    project: Annotated[str, typer.Argument(help="项目")],
    invite_id: Annotated[int, typer.Argument(help="链接编号（invites）")],
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    sc = _scope(c, db, project)
    try:
        d = joining.revoke_invite(db, sc, invite_id)
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, d, c.t("invite.revoked", prefix=d["prefix"]))


@project_app.command("accept-invite", help="用邀请链接加入（令牌或整个链接）/ join with an invite link")
def cmd_accept_invite(
    ctx: typer.Context,
    token: Annotated[str, typer.Argument(help="邀请令牌，或包含 /invite/<令牌> 的链接")],
    reason: Annotated[str, typer.Option("--reason", help="留言（链接需要审批时）")] = "",
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    tok = token.rsplit("/invite/", 1)[-1].strip().strip("/")
    try:
        d = joining.accept_invite(db, _who(c, db), tok, reason)
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, d, c.t(f"invite.accept.{d['status']}", project=d["project"], role=_role(c, d.get("role"))))


@project_app.command("can-create", help="--as 账号能否新建项目，以及创建权限申请 / can this account create projects")
def cmd_can_create(ctx: typer.Context) -> None:
    c = output.get(ctx)
    db = require_db(c)
    d = joining.creation_status(db, _who(c, db))
    if d["can_create"]:
        why = "admin" if d["admin"] else "open" if d["open"] else "granted"
        text = c.t(f"create.yes.{why}")
    else:
        req = d["request"]
        text = c.t("create.no") + (
            "\n" + c.t("create.request_state", status=_st(c, req["status"])) if req is not None else ""
        )
    emit(c, d, text)


@project_app.command("request-create", help="向管理员申请创建项目的权限 / ask for permission to create projects")
def cmd_request_create(ctx: typer.Context, reason: Annotated[str, typer.Option("--reason", help="用途")] = "") -> None:
    c = output.get(ctx)
    db = require_db(c)
    try:
        d = joining.request_create(db, _who(c, db), reason)
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, d, c.t("create.requested", id=d["id"]))


# ---------------------------------------------------------------- lmesh user：单独授权与申请


@user_app.command("grant-create", help="单独授权账号创建项目（--revoke 收回）/ let an account create projects")
def cmd_grant_create(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="用户名")],
    revoke: Annotated[bool, typer.Option("--revoke", help="收回授权")] = False,
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    try:
        d = joining.set_create_permission(db, _who(c, db), name, not revoke)
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, d, c.t("create.revoked_ok" if revoke else "create.granted_ok", name=d["username"]))


@user_app.command("create-requests", help="创建项目权限的申请（--all 包括已处理的）/ requests to create projects")
def cmd_create_requests(
    ctx: typer.Context, all_: Annotated[bool, typer.Option("--all", help="包括已处理的")] = False
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    rows = joining.list_create_requests(db, None if all_ else "pending")
    body = [[str(r["id"]), r["username"], _st(c, r["status"]), _t16(r["created_at"]), r["reason"][:40]] for r in rows]
    head = [c.t(f"join.col.{k}") for k in ("id", "user", "status", "created", "reason")]
    emit(c, {"requests": rows}, output.table(body, head) if rows else c.t("join.empty"))


@user_app.command("approve-create", help="通过创建权限的申请（给该账号单独授权）/ approve a create request")
def cmd_approve_create(ctx: typer.Context, request_id: Annotated[int, typer.Argument(help="申请编号")]) -> None:
    c = output.get(ctx)
    db = require_db(c)
    try:
        d = joining.decide_create(db, _who(c, db), request_id, True)
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, d, c.t("create.granted_ok", name=d["username"]))


@user_app.command("decline-create", help="拒绝创建权限的申请 / decline a create request")
def cmd_decline_create(
    ctx: typer.Context,
    request_id: Annotated[int, typer.Argument(help="申请编号")],
    note: Annotated[str, typer.Option("--note", help="说明")] = "",
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    try:
        d = joining.decide_create(db, _who(c, db), request_id, False, note)
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, d, c.t("create.declined_ok", name=d["username"]))


def register(app: typer.Typer) -> None:
    """命令在导入本模块时已挂到 lmesh project 与 lmesh user 下（M9-8），这里不用再添加。"""
    del app
