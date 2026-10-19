"""账号命令（REQ-030）：lmesh user list / add / disable / enable / reset-password / set-role / delete；
自助注册（REQ-039）：lmesh user list --pending、lmesh user approve / reject。

直接操作本机数据库。密码从提示（不回显、输入两次）或 --password-stdin 读取，不接受命令行明文参数。
"""

from __future__ import annotations

import sys
from typing import Annotated, Any, NoReturn

import typer

from lmesh.cli import output
from lmesh.cli.cmd_configs import require_db
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import users

user_app = typer.Typer(no_args_is_help=True, help="网页登录账号 / user accounts")

StdinOpt = Annotated[bool, typer.Option("--password-stdin", help="从标准输入读取密码（第一行）")]


def _fail(c: Ctx, e: users.UserError) -> NoReturn:
    code = {"param": output.EXIT_USAGE, "not_found": output.EXIT_NOT_FOUND}.get(e.kind, output.EXIT_ERROR)
    fail(c, code, c.t(e.key, **e.fmt))


def _password(c: Ctx, from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    if not sys.stdin.isatty():
        fail(c, output.EXIT_USAGE, c.t("user.need_stdin"))
    first = typer.prompt(c.t("user.password_prompt"), hide_input=True)
    if typer.prompt(c.t("user.password_repeat"), hide_input=True) != first:
        fail(c, output.EXIT_USAGE, c.t("user.password_mismatch"))
    return str(first)


def _status(c: Ctx, u: dict[str, Any]) -> str:
    if u["disabled"]:
        return c.t("user.status.disabled")
    if u.get("status") == "pending":
        return c.t("user.status.pending")
    if u["locked"]:
        return c.t("user.status.locked", until=(u["locked_until"] or "")[:16].replace("T", " "))
    return c.t("user.status.enabled")


def list_text(c: Ctx, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return c.t("user.empty")
    head = [c.t(f"user.col.{k}") for k in ("name", "role", "status", "last_login", "created")]
    body = [
        [
            u["username"],
            c.t(f"user.role.{u['role']}"),
            _status(c, u),
            (u["last_login_at"] or "-")[:16].replace("T", " "),
            (u["created_at"] or "")[:10],
        ]
        for u in rows
    ]
    return output.table(body, head) + "\n" + c.t("user.count", n=len(rows))


@user_app.command("list", help="账号列表；--pending 只看待审核的自助注册账号 / list accounts")
def cmd_list(
    ctx: typer.Context,
    pending: Annotated[bool, typer.Option("--pending", help="只看待审核的自助注册账号（REQ-039）")] = False,
) -> None:
    c = output.get(ctx)
    rows = users.list_users(require_db(c), "pending" if pending else None)
    emit(c, {"users": rows, "count": len(rows)}, list_text(c, rows))


@user_app.command("add", help="新建账号 / add an account")
def cmd_add(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="用户名")],
    role: Annotated[str, typer.Option("--role", help="admin | maintainer | user")] = "user",
    password_stdin: StdinOpt = False,
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    try:
        users.validate_username(name)
        users.validate_role(role)
        u = users.create_user(db, name, _password(c, password_stdin), role)
    except users.UserError as e:
        _fail(c, e)
    emit(c, {"user": u}, c.t("user.added", name=u["username"], role=c.t(f"user.role.{u['role']}")))


@user_app.command("disable", help="停用账号（会话立即失效）/ disable an account")
def cmd_disable(ctx: typer.Context, name: Annotated[str, typer.Argument(help="用户名")]) -> None:
    c = output.get(ctx)
    try:
        u = users.update_user(require_db(c), name, disabled=True)
    except users.UserError as e:
        _fail(c, e)
    emit(c, {"user": u}, c.t("user.disabled_ok", name=name))


@user_app.command("enable", help="启用账号（同时解除锁定）/ enable an account")
def cmd_enable(ctx: typer.Context, name: Annotated[str, typer.Argument(help="用户名")]) -> None:
    c = output.get(ctx)
    try:
        u = users.update_user(require_db(c), name, disabled=False, unlock=True)
    except users.UserError as e:
        _fail(c, e)
    emit(c, {"user": u}, c.t("user.enabled_ok", name=name))


@user_app.command("reset-password", help="重置密码（解除锁定，会话失效）/ reset a password")
def cmd_reset(
    ctx: typer.Context, name: Annotated[str, typer.Argument(help="用户名")], password_stdin: StdinOpt = False
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    try:
        users.get_user(db, name)
        r = users.reset_password(db, name, _password(c, password_stdin))
    except users.UserError as e:
        _fail(c, e)
    closed = r.pop("sessions_closed")
    emit(c, {"user": r, "sessions_closed": closed}, c.t("user.reset_ok", name=name, n=closed))


@user_app.command("set-role", help="改角色 / change role")
def cmd_set_role(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="用户名")],
    role: Annotated[str, typer.Argument(help="admin | maintainer | user")],
) -> None:
    c = output.get(ctx)
    try:
        u = users.update_user(require_db(c), name, role=role)
    except users.UserError as e:
        _fail(c, e)
    emit(c, {"user": u}, c.t("user.role_ok", name=name, role=c.t(f"user.role.{role}")))


@user_app.command(
    "delete", help="删除账号（需要确认，--yes 跳过）；拥有项目时 --transfer-to 或 --delete-projects / delete an account"
)
def cmd_delete(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="用户名")],
    transfer_to: Annotated[
        str | None, typer.Option("--transfer-to", help="把他的项目、私有模板与规则集转交给这个账号")
    ] = None,
    delete_projects: Annotated[
        bool, typer.Option("--delete-projects", help="一并删除他的项目、私有模板与规则集")
    ] = False,
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    try:
        users.get_user(db, name)
        if not c.yes and not typer.confirm(c.t("user.confirm_delete", name=name)):
            fail(c, output.EXIT_ERROR, c.t("user.cancelled"))
        r = users.delete_user(db, name, transfer_to, delete_projects)
    except users.UserError as e:
        _fail(c, e)
    emit(c, r, c.t("user.deleted_ok", name=name))


def register(app: typer.Typer) -> None:
    app.add_typer(user_app, name="user")


def _audit(c: Ctx, db: str, action: str, name: str) -> None:
    from lmesh.core import projects

    projects.audit(db, projects.cli_identity(db, c.as_user), None, "", action, {"username": name, "via": "cli"})


@user_app.command("approve", help="批准自助注册的待审核账号（建好默认项目）/ approve a pending sign-up")
def cmd_approve(ctx: typer.Context, name: Annotated[str, typer.Argument(help="用户名")]) -> None:
    c = output.get(ctx)
    db = require_db(c)
    try:
        u = users.approve(db, name)
    except users.UserError as e:
        _fail(c, e)
    _audit(c, db, "user.approve", u["username"])
    emit(c, {"user": u}, c.t("user.approved", name=u["username"]))


@user_app.command("reject", help="拒绝自助注册的待审核账号（删除，用户名可再注册）/ reject a pending sign-up")
def cmd_reject(ctx: typer.Context, name: Annotated[str, typer.Argument(help="用户名")]) -> None:
    c = output.get(ctx)
    db = require_db(c)
    try:
        r = users.reject(db, name)
    except users.UserError as e:
        _fail(c, e)
    _audit(c, db, "user.reject", name)
    emit(c, r, c.t("user.rejected", name=name))
