"""项目内的网络命令（M9，REQ-045）。

- lmesh network list|show|create|update|delete|copy
- lmesh network members|add|remove|pin|follow
- lmesh network rules|rule-add|rule-delete|rule-preview
- lmesh network folder-add|folder-delete
- lmesh network suggest|adopt
项目用全局 --project（不给时默认项目）；网络写在参数里（标识或编号）。按网络的其他命令（topology、check……）用全局
--network 选网络，不给时为默认网络。命令行权限等同管理员。
"""

from __future__ import annotations

from typing import Annotated, Any, NoReturn

import typer

from lmesh.cli import output
from lmesh.cli.cmd_configs import require_db
from lmesh.cli.cmd_graph import _kb
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import networks, projects

network_app = typer.Typer(no_args_is_help=True, help="项目里的网络 / networks in a project")


def _fail(c: Ctx, e: Exception) -> NoReturn:
    kind = getattr(e, "kind", "param")
    code = {"param": output.EXIT_USAGE, "ambiguous": output.EXIT_USAGE, "not_found": output.EXIT_NOT_FOUND}.get(
        kind, output.EXIT_ERROR
    )
    fail(c, code, c.t(getattr(e, "key", str(e)), **getattr(e, "fmt", {})), getattr(e, "data", None))


def _ctx(ctx: typer.Context) -> tuple[Ctx, str, projects.Scope]:
    c = output.get(ctx)
    db = require_db(c)
    sc = projects.current()
    if sc is None:
        try:
            sc = projects.default_scope(db, projects.cli_identity(db, c.as_user))
        except projects.ProjectError as e:
            _fail(c, e)
    return c, db, sc


def _kb_or_none(c: Ctx) -> Any:
    try:
        return _kb(c)[0]
    except (Exception, SystemExit):  # noqa: BLE001 - 没有知识库时管理地址与按图计算的建议不可用
        return None


def _run(c: Ctx, fn: Any, *args: Any, **kw: Any) -> Any:
    try:
        return fn(*args, **kw)
    except projects.ProjectError as e:
        _fail(c, e)


def _ids(text: str) -> list[int]:
    return [int(x) for x in text.replace(" ", "").split(",") if x.strip().isdigit()]


@network_app.command("list", help="本项目的网络与汇总 / list networks")
def cmd_list(ctx: typer.Context) -> None:
    c, db, sc = _ctx(ctx)
    data = _run(c, networks.list_networks, db, sc)
    head = [c.t(f"network.col.{k}") for k in ("slug", "name", "devices", "shared", "scripts", "findings")]
    body = [
        [
            n["slug"] + (" *" if n["default"] else ""),
            n["name"],
            str(n["counts"]["devices"]),
            str(n["counts"]["shared"]),
            str(n["counts"]["scripts"]),
            f"{n['counts']['findings']['error']}/{n['counts']['findings']['warning']}",
        ]
        for n in data["networks"]
    ]
    emit(c, data, output.table(body, head) + "\n" + c.t("network.count", n=len(body)))


@network_app.command("show", help="网络详情 / show a network")
def cmd_show(ctx: typer.Context, network: Annotated[str, typer.Argument(help="网络标识或编号")]) -> None:
    c, db, sc = _ctx(ctx)
    d = _run(c, networks.get_network, db, sc, network)
    emit(c, d, f"{d['name']} ({d['slug']})  {c.t('network.col.devices')}: {d['counts']['devices']}")


@network_app.command("create", help="新建网络 / create a network")
def cmd_create(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="名称")],
    slug: Annotated[str | None, typer.Option("--slug", help="标识；不给时由名称生成")] = None,
    color: Annotated[str | None, typer.Option("--color", help="识别色（8 色之一）")] = None,
    devices: Annotated[str, typer.Option("--devices", help="同时加入的设备编号，逗号分隔")] = "",
    name_rule: Annotated[list[str] | None, typer.Option("--name-rule", help="自动加入规则：设备名通配")] = None,
    subnet_rule: Annotated[list[str] | None, typer.Option("--subnet-rule", help="自动加入规则：管理网段")] = None,
) -> None:
    c, db, sc = _ctx(ctx)
    rules = [{"kind": "name", "pattern": p, "apply_existing": True} for p in name_rule or []]
    rules += [{"kind": "subnet", "pattern": p, "apply_existing": True} for p in subnet_rule or []]
    data = {"name": name, "slug": slug, "color": color, "device_ids": _ids(devices), "rules": rules}
    d = _run(c, networks.create_network, db, sc, data, _kb_or_none(c) if subnet_rule else None)
    emit(c, d, c.t("network.created", slug=d["slug"], n=d["counts"]["devices"]))


@network_app.command("update", help="改名、标识、颜色 / rename or recolor a network")
def cmd_update(
    ctx: typer.Context,
    network: Annotated[str, typer.Argument(help="网络")],
    name: Annotated[str | None, typer.Option("--name")] = None,
    slug: Annotated[str | None, typer.Option("--slug")] = None,
    color: Annotated[str | None, typer.Option("--color")] = None,
) -> None:
    c, db, sc = _ctx(ctx)
    d = _run(c, networks.update_network, db, sc, network, {"name": name, "slug": slug, "color": color})
    emit(c, d, c.t("network.updated", slug=d["slug"]))


@network_app.command("delete", help="删除网络与它的工作数据（不删设备）；--confirm 写网络名称 / delete a network")
def cmd_delete(
    ctx: typer.Context,
    network: Annotated[str, typer.Argument(help="网络")],
    confirm: Annotated[str | None, typer.Option("--confirm", help="网络名称（确认）")] = None,
    preview: Annotated[bool, typer.Option("--preview", help="只列出会删除的内容")] = False,
) -> None:
    c, db, sc = _ctx(ctx)
    if preview:
        d = _run(c, networks.delete_preview, db, sc, network)
        emit(c, d, "\n".join(f"{k}: {v}" for k, v in d["counts"].items()))
        return
    d = _run(c, networks.delete_network, db, sc, network, confirm)
    emit(c, d, c.t("network.deleted", slug=d["network"]["slug"]))


@network_app.command("copy", help="复制网络（连同工作数据）/ copy a network")
def cmd_copy(
    ctx: typer.Context,
    network: Annotated[str, typer.Argument(help="网络")],
    name: Annotated[str, typer.Option("--name", help="新网络名称")],
    slug: Annotated[str | None, typer.Option("--slug")] = None,
) -> None:
    c, db, sc = _ctx(ctx)
    d = _run(c, networks.copy_network, db, sc, network, {"name": name, "slug": slug})
    emit(c, d, c.t("network.created", slug=d["slug"], n=d["counts"]["devices"]))


@network_app.command("members", help="网络成员与本网络用的版本 / members of a network")
def cmd_members(ctx: typer.Context, network: Annotated[str, typer.Argument(help="网络")]) -> None:
    c, db, sc = _ctx(ctx)
    d = _run(c, networks.list_members, db, sc, network, None)
    head = [c.t(f"network.col.{k}") for k in ("device", "version", "also_in", "joined")]
    body = [
        [
            f"{m['name']} ({m['device_id']})",
            (f"v{m['seq']}" if m["seq"] else "-") + (" pin" if m["policy"] == "pin" else ""),
            ", ".join(x["slug"] for x in m["also_in"]) or "-",
            m["join_source"],
        ]
        for m in d["members"]
    ]
    emit(c, d, output.table(body, head) + "\n" + c.t("network.count_members", n=len(body)))


@network_app.command("add", help="从项目设备池加入设备 / add devices")
def cmd_add(
    ctx: typer.Context,
    network: Annotated[str, typer.Argument(help="网络")],
    devices: Annotated[str, typer.Argument(help="设备编号，逗号分隔")],
    pin: Annotated[bool, typer.Option("--pin", help="固定在当前最新版本")] = False,
) -> None:
    c, db, sc = _ctx(ctx)
    d = _run(c, networks.add_members, db, sc, network, _ids(devices), "pin" if pin else "follow")
    emit(c, d, c.t("network.added", n=len(d["added"])))


@network_app.command("remove", help="移出网络（记为排除）/ remove devices")
def cmd_remove(
    ctx: typer.Context,
    network: Annotated[str, typer.Argument(help="网络")],
    devices: Annotated[str, typer.Argument(help="设备编号，逗号分隔")],
) -> None:
    c, db, sc = _ctx(ctx)
    d = _run(c, networks.remove_members, db, sc, network, _ids(devices))
    emit(c, d, c.t("network.removed", n=len(d["removed"])))


@network_app.command("pin", help="在本网络固定版本（不给 --version 时固定在当前最新）/ pin versions")
def cmd_pin(
    ctx: typer.Context,
    network: Annotated[str, typer.Argument(help="网络")],
    devices: Annotated[str, typer.Argument(help="设备编号，逗号分隔")],
    version: Annotated[int | None, typer.Option("--version", help="版本编号（只能一台设备）")] = None,
) -> None:
    c, db, sc = _ctx(ctx)
    d = _run(c, networks.set_policy, db, sc, network, _ids(devices), "pin", version)
    emit(c, d, c.t("network.policy_set", n=len(d["updated"])))


@network_app.command("follow", help="在本网络改为跟随最新 / follow the latest version")
def cmd_follow(
    ctx: typer.Context,
    network: Annotated[str, typer.Argument(help="网络")],
    devices: Annotated[str, typer.Argument(help="设备编号，逗号分隔")],
) -> None:
    c, db, sc = _ctx(ctx)
    d = _run(c, networks.set_policy, db, sc, network, _ids(devices), "follow", None)
    emit(c, d, c.t("network.policy_set", n=len(d["updated"])))


@network_app.command("rules", help="自动加入规则 / auto-join rules")
def cmd_rules(ctx: typer.Context, network: Annotated[str, typer.Argument(help="网络")]) -> None:
    c, db, sc = _ctx(ctx)
    d = _run(c, networks.list_rules, db, sc, network)
    lines = [f"#{r['id']} {r['kind']} {r['pattern']}" for r in d["rules"]] or [c.t("network.no_rules")]
    emit(c, d, "\n".join(lines))


@network_app.command("rule-add", help="添加自动加入规则 / add an auto-join rule")
def cmd_rule_add(
    ctx: typer.Context,
    network: Annotated[str, typer.Argument(help="网络")],
    kind: Annotated[str, typer.Argument(help="name | subnet")],
    pattern: Annotated[str, typer.Argument(help="设备名通配或 CIDR")],
    apply_existing: Annotated[bool, typer.Option("--apply", help="同时加入现在命中的设备")] = False,
) -> None:
    c, db, sc = _ctx(ctx)
    kb = _kb_or_none(c) if kind == "subnet" else None
    d = _run(c, networks.add_rule, db, sc, network, kind, pattern, apply_existing, kb)
    emit(c, d, c.t("network.rule_added", id=d["id"], n=len(d["added"])))


@network_app.command("rule-preview", help="规则命中预览 / preview a rule")
def cmd_rule_preview(
    ctx: typer.Context,
    network: Annotated[str, typer.Argument(help="网络")],
    kind: Annotated[str, typer.Argument(help="name | subnet")],
    pattern: Annotated[str, typer.Argument(help="设备名通配或 CIDR")],
) -> None:
    c, db, sc = _ctx(ctx)
    kb = _kb_or_none(c) if kind == "subnet" else None
    d = _run(c, networks.preview_rule, db, sc, network, kind, pattern, kb)
    emit(c, d, c.t("network.rule_preview", n=d["matches"], out=d["not_in_network"]))


@network_app.command("rule-delete", help="删除自动加入规则 / delete a rule")
def cmd_rule_delete(
    ctx: typer.Context,
    network: Annotated[str, typer.Argument(help="网络")],
    rule_id: Annotated[int, typer.Argument(help="规则编号")],
) -> None:
    c, db, sc = _ctx(ctx)
    d = _run(c, networks.delete_rule, db, sc, network, rule_id)
    emit(c, d, c.t("network.rule_deleted", id=rule_id))


@network_app.command("folder-add", help="新建文件夹 / create a folder")
def cmd_folder_add(ctx: typer.Context, name: Annotated[str, typer.Argument(help="名称")]) -> None:
    c, db, sc = _ctx(ctx)
    d = _run(c, networks.create_folder, db, sc, name)
    emit(c, d, f"#{d['id']} {d['name']}")


@network_app.command("folder-delete", help="删除文件夹（网络移到最外层）/ delete a folder")
def cmd_folder_delete(ctx: typer.Context, folder_id: Annotated[int, typer.Argument(help="文件夹编号")]) -> None:
    c, db, sc = _ctx(ctx)
    d = _run(c, networks.delete_folder, db, sc, folder_id)
    emit(c, d, f"#{folder_id}")


def _params(regex: str | None, prefix: int, protocol: str, all_links: bool) -> dict[str, Any]:
    return {"regex": regex, "prefix": prefix, "protocol": protocol, "ignore_mgmt": not all_links}


@network_app.command("suggest", help="建网建议（预览）/ suggest networks")
def cmd_suggest(
    ctx: typer.Context,
    basis: Annotated[str, typer.Argument(help="components | igp | bgp | name | subnet | ai")],
    regex: Annotated[str | None, typer.Option("--regex", help="设备名规则：正则，第一个括号")] = None,
    prefix: Annotated[int, typer.Option("--prefix", help="管理网段的前缀长度")] = 24,
    protocol: Annotated[str, typer.Option("--protocol", help="IGP：all | isis | ospf")] = "all",
    all_links: Annotated[bool, typer.Option("--all-links", help="连通分量：管理口链路也算")] = False,
) -> None:
    c, db, sc = _ctx(ctx)
    kb = None if basis == "name" else _kb_or_none(c)
    d = _run(c, networks.suggest, db, sc, basis, _params(regex, prefix, protocol, all_links), kb)
    head = [c.t(f"network.col.{k}") for k in ("key", "name", "devices", "same_as")]
    body = [
        [g["key"], g["name"], str(g["count"]), (g["same_as"] or {}).get("slug") or ("✗" if not g["adoptable"] else "")]
        for g in d["suggestions"]
    ]
    emit(c, d, output.table(body, head) + "\n" + c.t("network.count", n=len(body)))


@network_app.command("adopt", help="采纳建网建议（不给 --key 时采纳全部可采纳的）/ adopt suggestions")
def cmd_adopt(
    ctx: typer.Context,
    basis: Annotated[str, typer.Argument(help="components | igp | bgp | name | subnet | ai")],
    key: Annotated[list[str] | None, typer.Option("--key", help="建议的 key，可多次")] = None,
    with_rules: Annotated[bool, typer.Option("--with-rules", help="同时设为自动加入规则")] = False,
    regex: Annotated[str | None, typer.Option("--regex")] = None,
    prefix: Annotated[int, typer.Option("--prefix")] = 24,
    protocol: Annotated[str, typer.Option("--protocol")] = "all",
    all_links: Annotated[bool, typer.Option("--all-links")] = False,
) -> None:
    c, db, sc = _ctx(ctx)
    kb = None if basis == "name" else _kb_or_none(c)
    params = _params(regex, prefix, protocol, all_links)
    d = _run(c, networks.adopt, db, sc, basis, params, key or [], kb, with_rules)
    emit(c, d, c.t("network.adopted", n=len(d["created"]), skipped=len(d["skipped"])))


def register(app: typer.Typer) -> None:
    app.add_typer(network_app, name="network")
