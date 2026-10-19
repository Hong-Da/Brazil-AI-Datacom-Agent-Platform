"""设备命令（REQ-038）：lmesh device delete / delete-version。

设备写名称或编号；版本引用与 lmesh history 相同：纯数字是设备内的序号（#3 同义），v<编号> 是配置版本编号，另有 latest、prev、tag:<标签>。
没有 --yes 且在终端时先提示确认；删除记入日志（操作者为操作系统用户名）。"""

from __future__ import annotations

from typing import Annotated, Any, NoReturn

import typer

from lmesh.cli import output
from lmesh.cli.cmd_configs import _actor, require_db
from lmesh.cli.cmd_history import _device, _ref
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import device_delete, history

device_app = typer.Typer(no_args_is_help=True, help="设备 / devices")

ForceOpt = Annotated[bool, typer.Option("--force", help="被配置检查项目作基线时仍删除（清空基线 / 改为跟随最新版本）")]
YesOpt = Annotated[bool, typer.Option("--yes", "-y", help="跳过确认 / skip the prompt")]


def _fail(c: Ctx, e: device_delete.DeleteError) -> NoReturn:
    code = output.EXIT_NOT_FOUND if e.kind == "not_found" else output.EXIT_ERROR
    fail(c, code, c.t(e.key, **e.fmt), e.data)


def _names(projects: list[dict[str, Any]]) -> str:
    return "、".join(f"{p['name']}（{', '.join(x['name'] for x in p['scripts']) or '-'}）" for p in projects)


def _load_kb(c: Ctx) -> Any:
    """重算下一个版本的变化计数要用知识库；加载失败时不影响删除。"""
    from lmesh.cli.cmd_graph import _kb

    try:
        return _kb(c)[0]
    except Exception:
        return None


def _confirm(c: Ctx, yes: bool, text: str) -> None:
    if not (yes or c.yes) and not typer.confirm(text):
        fail(c, output.EXIT_ERROR, c.t("device.cancelled"))


@device_app.command("delete", help="删除设备与它的全部配置版本、快照、图、导入记录、检查忽略项 / delete a device")
def cmd_delete(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="设备名或编号")],
    force: ForceOpt = False,
    yes: YesOpt = False,
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    dev_id = _device(c, db, device)
    try:
        pv = device_delete.preview(db, dev_id)
        if pv["blocked"] and not force:
            fail(
                c,
                output.EXIT_ERROR,
                c.t(
                    "device_delete.baseline_in_use",
                    projects=len(pv["baseline"]["projects"]),
                    scripts=pv["baseline"]["scripts"],
                )
                + "\n"
                + c.t("device.baseline_projects", names=_names(pv["baseline"]["projects"])),
                pv,
            )
        n = pv["counts"]
        _confirm(
            c,
            yes,
            c.t(
                "device.confirm_delete",
                name=pv["device"]["name"],
                versions=n["versions"],
                imports=n["imports"],
                ignores=n["check_ignores"],
            ),
        )
        r = device_delete.delete_device(db, dev_id, force, _actor())
    except device_delete.DeleteError as e:
        _fail(c, e)
    n = r["counts"]
    lines = [
        c.t(
            "device.deleted_ok",
            name=r["device"]["name"],
            versions=n["versions"],
            imports=n["imports"],
            nodes=n["nodes"],
            unknown=n["unknown_lines"],
            ignores=n["check_ignores"],
        )
    ]
    if r["baseline_cleared"]:
        lines.append(c.t("device.baseline_cleared", n=len(r["baseline_cleared"]), names=_names(r["baseline_cleared"])))
    emit(c, r, "\n".join(lines))


@device_app.command(
    "delete-version", help="删除设备的一个配置版本（最后一个版本不能单独删除）/ delete a config version"
)
def cmd_delete_version(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="设备名或编号")],
    version: Annotated[str, typer.Argument(help="版本：序号（数字）、v<版本编号>、latest、prev、tag:<标签>")],
    force: ForceOpt = False,
    yes: YesOpt = False,
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    dev_id = _device(c, db, device)
    try:
        vid = history.resolve_snapshot(db, dev_id, _ref(version))
    except history.HistoryError as e:
        fail(c, output.EXIT_NOT_FOUND, c.t(e.key, **e.fmt))
    try:
        pv = device_delete.preview(db, dev_id)
        v = next(x for x in pv["versions"] if x["id"] == vid)
        if len(pv["versions"]) > 1:
            _confirm(c, yes, c.t("device.confirm_delete_version", name=pv["device"]["name"], version=vid, seq=v["seq"]))
        r = device_delete.delete_version(db, dev_id, vid, force, _actor(), _load_kb(c))
    except device_delete.DeleteError as e:
        _fail(c, e)
    lines = [
        c.t(
            "device.version_deleted_ok",
            name=pv["device"]["name"],
            version=vid,
            seq=r["version"]["seq"],
            left=r["versions_left"],
            latest=r["latest_version_id"],
        )
    ]
    if r["baseline_cleared"]:
        lines.append(c.t("device.baseline_follow", n=len(r["baseline_cleared"]), names=_names(r["baseline_cleared"])))
    if r["baseline_moved"]:
        lines.append(
            c.t(
                "device.baseline_moved",
                n=len(r["baseline_moved"]),
                latest=r["latest_version_id"],
                names=_names(r["baseline_moved"]),
            )
        )
    emit(c, r, "\n".join(lines))


def register(app: typer.Typer) -> None:
    app.add_typer(device_app, name="device")
