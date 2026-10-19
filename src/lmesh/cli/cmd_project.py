"""项目、个人令牌、公共设备库命令（M6，REQ-035 / REQ-036）。

- lmesh project list|show|create|delete|members|transfer|copy|default|ref
- lmesh token create|list|revoke
- lmesh public-device list|import|delete（管理员维护的公共设备库）
命令行直接操作本机数据库，权限等同管理员；--as <账号> 决定以谁的身份（默认项目、新建项目与令牌的属主），
不给时为第一个管理员（决策记录）。项目写法：标识、属主/标识或编号。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from lmesh.cli import output
from lmesh.cli.cmd_configs import _actor, _level, require_db
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import config, importer, projects, tokens

project_app = typer.Typer(no_args_is_help=True, help="项目 / projects")
token_app = typer.Typer(no_args_is_help=True, help="个人 API 令牌 / personal API tokens")
public_app = typer.Typer(no_args_is_help=True, help="公共设备库（管理员）/ public device library")


def _fail(c: Ctx, e: Exception) -> NoReturn:
    kind = getattr(e, "kind", "param")
    code = {"param": output.EXIT_USAGE, "ambiguous": output.EXIT_USAGE, "not_found": output.EXIT_NOT_FOUND}.get(
        kind, output.EXIT_ERROR
    )
    fail(c, code, c.t(getattr(e, "key", str(e)), **getattr(e, "fmt", {})), getattr(e, "data", None))


def _who(c: Ctx, db: str) -> projects.Identity:
    try:
        return projects.cli_identity(db, c.as_user)
    except projects.ProjectError as e:
        _fail(c, e)


def _scope(c: Ctx, db: str, ref: str | None) -> projects.Scope:
    who = _who(c, db)
    try:
        return projects.resolve(db, who, ref) if ref else projects.default_scope(db, who)
    except projects.ProjectError as e:
        _fail(c, e)


def _role(c: Ctx, role: str | None) -> str:
    return c.t(f"project.role.{role}") if role else "-"


def _rows_text(c: Ctx, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return c.t("project.empty")
    head = [c.t(f"project.col.{k}") for k in ("slug", "name", "owner", "role", "devices", "scripts", "members")]
    body = [
        [
            r["ref"] + (" *" if r.get("default") else ""),
            r["name"],
            r["owner"] or "-",
            _role(c, r["role"]),
            f"{r['counts']['devices']} ({r['counts']['private']}/{r['counts']['refs']})",
            str(r["counts"]["scripts"]),
            str(r["members"]),
        ]
        for r in rows
    ]
    return output.table(body, head) + "\n" + c.t("project.count", n=len(rows))


@project_app.command("list", help="我的项目与共享给我的；--all 列出全部（管理员）/ list projects")
def cmd_list(
    ctx: typer.Context,
    all_: Annotated[bool, typer.Option("--all", help="同时列出不是自己参与的项目")] = False,
    owner: Annotated[str | None, typer.Option("--owner", help="只看某个属主的项目")] = None,
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    who = _who(c, db)
    try:
        data = projects.list_projects(db, who, include_all=all_ and who.is_admin, owner=owner)
    except projects.ProjectError as e:
        _fail(c, e)
    rows = data["mine"] + data["shared"] + data["others"]
    emit(c, data, _rows_text(c, rows))


@project_app.command("show", help="项目详情（不给项目时为当前项目）/ show a project")
def cmd_show(ctx: typer.Context, project: Annotated[str | None, typer.Argument(help="项目")] = None) -> None:
    c = output.get(ctx)
    db = require_db(c)
    sc = _scope(c, db, project or c.project)
    d = projects.get_project(db, sc)
    lines = [
        f"{d['name']} ({d['full_ref']})",
        f"{c.t('project.col.owner')}: {d['owner'] or '-'}  {c.t('project.col.role')}: {_role(c, d['role'])}",
        c.t(
            "project.counts",
            devices=d["counts"]["devices"],
            private=d["counts"]["private"],
            refs=d["counts"]["refs"],
            scripts=d["counts"]["scripts"],
        ),
    ]
    lines += [f"  {m['username']}  {_role(c, m['role'])}" for m in d["member_list"]]
    emit(c, d, "\n".join(lines))


@project_app.command("create", help="新建项目（属主为 --as 账号，默认第一个管理员）/ create a project")
def cmd_create(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="项目名称")],
    slug: Annotated[
        str | None, typer.Option("--slug", help="项目标识（在属主自己的项目里唯一）；不给时由名称生成")
    ] = None,
    description: Annotated[str | None, typer.Option("--description", help="说明")] = None,
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    try:
        d = projects.create_project(db, _who(c, db), {"name": name, "slug": slug, "description": description})
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, d, c.t("project.created", slug=d["ref"]))


@project_app.command("delete", help="删除项目：私有设备一起删除，引用只解除（需要确认，--yes 跳过）/ delete a project")
def cmd_delete(ctx: typer.Context, project: Annotated[str, typer.Argument(help="项目")]) -> None:
    c = output.get(ctx)
    db = require_db(c)
    sc = _scope(c, db, project)
    pre = projects.delete_preview(db, sc)
    if not c.yes:
        n = pre["counts"]
        typer.echo(
            c.t(
                "project.delete_impact",
                devices=n["private_devices"],
                versions=n["versions"],
                scripts=n["scripts"],
                refs=n["refs"],
            )
        )
        if typer.prompt(c.t("project.confirm_delete", slug=sc.slug)) != sc.slug:
            fail(c, output.EXIT_ERROR, c.t("project.cancelled"))
    try:
        d = projects.delete_project(db, sc, sc.slug)
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, d, c.t("project.deleted", slug=sc.label))


@project_app.command("members", help="成员列表；--add 邀请或改角色、--remove 移除 / project members")
def cmd_members(
    ctx: typer.Context,
    project: Annotated[str, typer.Argument(help="项目")],
    add: Annotated[str | None, typer.Option("--add", help="邀请的账号（已是成员时改角色）")] = None,
    role: Annotated[str, typer.Option("--role", help="edit | read")] = "read",
    remove: Annotated[str | None, typer.Option("--remove", help="移除的账号")] = None,
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    sc = _scope(c, db, project)
    try:
        if add:
            projects.set_member(db, sc, add, role)
        if remove:
            projects.remove_member(db, sc, remove)
    except projects.ProjectError as e:
        _fail(c, e)
    rows = projects.list_members(db, sc)
    text = output.table(
        [[m["username"], _role(c, m["role"]), (m["since"] or "")[:10]] for m in rows],
        [c.t("project.col.user"), c.t("project.col.role"), c.t("project.col.since")],
    )
    emit(c, {"project": sc.label, "members": rows}, text)


@project_app.command("transfer", help="转交项目给其他账号；原属主默认留作可编辑成员 / transfer a project")
def cmd_transfer(
    ctx: typer.Context,
    project: Annotated[str, typer.Argument(help="项目")],
    to: Annotated[str, typer.Argument(help="新属主账号")],
    keep_as: Annotated[str, typer.Option("--keep-as", help="原属主留作成员的角色：edit | read | none")] = "edit",
    slug: Annotated[str | None, typer.Option("--slug", help="同时改标识（新属主已有同名项目时必须给）")] = None,
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    sc = _scope(c, db, project)
    try:
        d = projects.transfer(db, sc, to, None if keep_as == "none" else keep_as, slug)
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, d, c.t("project.transferred", slug=d["full_ref"], owner=to))


@project_app.command("copy", help="复制为新项目（属主为 --as 账号）/ copy a project")
def cmd_copy(
    ctx: typer.Context,
    project: Annotated[str, typer.Argument(help="来源项目")],
    name: Annotated[str, typer.Argument(help="新项目名称")],
    slug: Annotated[str | None, typer.Option("--slug", help="新项目标识")] = None,
    no_devices: Annotated[bool, typer.Option("--no-devices", help="不复制设备与引用")] = False,
    no_scripts: Annotated[bool, typer.Option("--no-scripts", help="不复制脚本")] = False,
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    sc = _scope(c, db, project)
    try:
        d = projects.copy_project(
            db, sc, _who(c, db), {"name": name, "slug": slug, "devices": not no_devices, "scripts": not no_scripts}
        )
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, d, c.t("project.copied", slug=d["ref"], devices=d["copied"]["devices"], scripts=d["copied"]["scripts"]))


@project_app.command("default", help="设置 --as 账号的默认项目 / set the default project")
def cmd_default(ctx: typer.Context, project: Annotated[str, typer.Argument(help="项目")]) -> None:
    c = output.get(ctx)
    db = require_db(c)
    try:
        d = projects.set_default(db, _who(c, db), project)
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, d, c.t("project.default_set", slug=d["default_project"]))


@project_app.command(
    "ref", help="在当前项目（--project）引用公共设备；--pin 固定版本、--remove 解除引用 / reference a public device"
)
def cmd_ref(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="公共设备名称或编号")],
    pin: Annotated[int | None, typer.Option("--pin", help="固定的版本编号；不给时跟随最新")] = None,
    remove: Annotated[bool, typer.Option("--remove", help="解除引用")] = False,
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    sc = _scope(c, db, c.project)
    dev = _public(c, db, device)
    try:
        d = projects.remove_ref(db, sc, dev["id"]) if remove else projects.add_ref(db, sc, dev["id"], pin)
    except projects.ProjectError as e:
        _fail(c, e)
    key = "project.unreferenced" if remove else "project.referenced"
    emit(c, d, c.t(key, device=dev["name"], slug=sc.label))


# ---------------------------------------------------------------- 个人令牌


def _need_account(c: Ctx, who: projects.Identity) -> None:
    if who.user_id is None:
        fail(c, output.EXIT_ERROR, c.t("tokens.need_account"))


@token_app.command("create", help="生成个人令牌（属于 --as 账号）；令牌只显示这一次 / create a token")
def cmd_token_create(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="用途说明")],
    read_only: Annotated[bool, typer.Option("--read-only", help="只读：只能读取与计算")] = False,
    days: Annotated[int, typer.Option("--days", help="有效天数；0 表示不过期")] = tokens.DEFAULT_DAYS,
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    who = _who(c, db)
    _need_account(c, who)
    try:
        d = tokens.create(db, who.username, name, read_only, days)
    except tokens.TokenError as e:
        _fail(c, e)
    emit(c, d, c.t("token.created", token=d["token"], prefix=d["prefix"]))


@token_app.command("list", help="--as 账号的个人令牌 / list tokens")
def cmd_token_list(ctx: typer.Context) -> None:
    c = output.get(ctx)
    db = require_db(c)
    who = _who(c, db)
    _need_account(c, who)
    rows = tokens.list_tokens(db, who.username)
    text = output.table(
        [
            [
                str(t["id"]),
                t["name"],
                t["prefix"] + "…",
                c.t("token.ro") if t["read_only"] else c.t("token.rw"),
                (t["expires_at"] or "-")[:10],
                (t["last_used_at"] or "-")[:16].replace("T", " "),
                c.t(f"token.state.{t['state']}"),
            ]
            for t in rows
        ],
        [c.t(f"token.col.{k}") for k in ("id", "name", "prefix", "scope", "expires", "last_used", "state")],
    )
    emit(c, {"tokens": rows}, text if rows else c.t("token.empty"))


@token_app.command("revoke", help="撤销个人令牌 / revoke a token")
def cmd_token_revoke(
    ctx: typer.Context, token_id: Annotated[int, typer.Argument(help="令牌编号（token list）")]
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    who = _who(c, db)
    _need_account(c, who)
    try:
        d = tokens.revoke(db, who.username, token_id)
    except tokens.TokenError as e:
        _fail(c, e)
    emit(c, d, c.t("token.revoked", prefix=d["prefix"]))


# ---------------------------------------------------------------- 公共设备库


def _public(c: Ctx, db: str, ref: str) -> dict[str, Any]:
    rows = projects.list_public(db)
    hit = next((d for d in rows if d["name"] == ref or (ref.isdigit() and d["id"] == int(ref))), None)
    if hit is None:
        fail(c, output.EXIT_NOT_FOUND, c.t("projects.public_not_found", device=ref))
    return hit


@public_app.command("list", help="公共设备与引用它的项目 / list public devices")
def cmd_public_list(ctx: typer.Context) -> None:
    c = output.get(ctx)
    db = require_db(c)
    rows = projects.list_public(db)
    text = output.table(
        [
            [str(d["id"]), d["name"], d["profile"] or "-", str(d["versions"]), f"{d['follow']}/{d['pinned']}"]
            for d in rows
        ],
        [c.t(f"public.col.{k}") for k in ("id", "name", "profile", "versions", "refs")],
    )
    emit(c, {"devices": rows}, text if rows else c.t("public.empty"))


@public_app.command("import", help="导入到公共设备库（同名设备作为新版本）/ import into the public library")
def cmd_public_import(
    ctx: typer.Context,
    source: Annotated[Path, typer.Argument(help="配置文件、目录或 zip")],
    level: Annotated[str, typer.Option(help="脱敏强度：basic / strict")] = "basic",
) -> None:
    c = output.get(ctx)
    if not source.exists():
        fail(c, output.EXIT_NOT_FOUND, c.t("common.not_found", path=source))
    url = require_db(c)
    from lmesh.core import kbservice

    settings = config.load()
    kind = "dir" if source.is_dir() else ("zip" if source.suffix.lower() == ".zip" else "file")
    results = [
        r.as_dict()
        for r in importer.import_sources(
            list(importer.iter_sources(source)),
            url,
            _level(c, level),
            kbservice.runtime_root(settings),
            source_kind=kind,
            actor=_actor(),
            keep=int(settings.get("history.keep")),
            public=True,
        )
    ]
    rows = [
        [r["source"], r["device"] or "-", str(r["version_id"] or "-"), c.t(r["error"]) if r["error"] else ""]
        for r in results
    ]
    emit(
        c,
        {"files": results},
        output.table(rows, [c.t("import.file"), c.t("public.col.name"), c.t("public.col.version"), ""]),
    )
    if not any(r["ok"] for r in results):
        raise typer.Exit(output.EXIT_ERROR)


@public_app.command("delete", help="删除公共设备；还有项目引用时拒绝（--force 一并解除引用）/ delete a public device")
def cmd_public_delete(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="公共设备名称或编号")],
    force: Annotated[bool, typer.Option("--force", help="还有项目引用时一并解除引用")] = False,
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    dev = _public(c, db, device)
    if not c.yes and not typer.confirm(c.t("public.confirm_delete", name=dev["name"])):
        fail(c, output.EXIT_ERROR, c.t("project.cancelled"))
    try:
        d = projects.delete_public(db, dev["id"], force, _actor())
    except projects.ProjectError as e:
        _fail(c, e)
    emit(c, d, c.t("public.deleted", name=dev["name"]))


def register(app: typer.Typer) -> None:
    app.add_typer(project_app, name="project")
    app.add_typer(token_app, name="token")
    app.add_typer(public_app, name="public-device")
