"""检查规则与忽略记录命令：lmesh rules list|set、lmesh ignore list|add|remove（与 API 共用 core）。"""

from __future__ import annotations

from typing import Annotated, NoReturn

import typer

from lmesh.cli import output
from lmesh.cli.cmd_check import rule_error
from lmesh.cli.cmd_configs import require_db
from lmesh.cli.cmd_graph import _kb
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import checks, compare, config, ignores, rule_edit
from lmesh.core import rules as rulesmod


def _ignore_fail(c: Ctx, e: ignores.IgnoreError) -> NoReturn:
    fail(c, output.EXIT_NOT_FOUND if e.kind == "not_found" else output.EXIT_USAGE, c.t(e.key, **e.fmt))


def _device(c: Ctx, db: str, name: str) -> int:
    dev_id = compare.device_id_by_name(db, name)
    if dev_id is None:
        fail(c, output.EXIT_NOT_FOUND, c.t("compare.device_not_found", target=name))
    return dev_id


def register(app: typer.Typer) -> None:
    rules_app = typer.Typer(no_args_is_help=True, help="检查规则 / check rules")
    ignore_app = typer.Typer(no_args_is_help=True, help="忽略的检查发现 / ignored findings")
    app.add_typer(rules_app, name="rules")
    app.add_typer(ignore_app, name="ignore")

    @rules_app.command("list", help="内置检查与知识库规则：开关、级别、来源 / list rules")
    def rules_list(ctx: typer.Context) -> None:
        c = output.get(ctx)
        kb, root = _kb(c)
        try:
            data = checks.list_rules(kb, checks.rules_dir(root))
        except rulesmod.RuleError as e:
            rule_error(c, e)
        rows = [
            [r["id"], r["severity"], c.t("common.yes") if r["enabled"] else c.t("common.no"), r["source"]]
            for r in data["rules"]
        ]
        emit(
            c,
            data,
            output.table(
                rows,
                [c.t("rules.col.id"), c.t("rules.col.severity"), c.t("rules.col.enabled"), c.t("rules.col.source")],
            ),
        )

    @rules_app.command("set", help="修改规则的开关与级别，写回运行时知识库并提交 / enable, disable or re-grade a rule")
    def rules_set(
        ctx: typer.Context,
        rule_id: Annotated[str, typer.Argument(help="规则编号，如 ref.orphan、vrf.rd_without_rt")],
        enable: Annotated[bool | None, typer.Option("--enable/--disable", help="启用 / 停用")] = None,
        severity: Annotated[str | None, typer.Option(help="error | warning | info")] = None,
    ) -> None:
        c = output.get(ctx)
        if not config.is_configured():
            fail(c, output.EXIT_CONFIG, c.t("config.not_configured"))
        kb, root = _kb(c)
        try:
            view = rule_edit.set_rule(root, kb, rule_id, enable, severity)
        except rule_edit.RuleEditError as e:
            fail(c, output.EXIT_NOT_FOUND if e.kind == "not_found" else output.EXIT_USAGE, c.t(e.key, **e.fmt))
        except rulesmod.RuleError as e:
            rule_error(c, e)
        state = c.t("common.yes") if view["enabled"] else c.t("common.no")
        emit(c, view, c.t("rules.updated", rule=rule_id, severity=view["severity"], enabled=state))

    @ignore_app.command("list", help="忽略的检查发现 / list ignored findings")
    def ignore_list(
        ctx: typer.Context,
        device: Annotated[str | None, typer.Option(help="只看一台设备（设备名）")] = None,
    ) -> None:
        c = output.get(ctx)
        db = require_db(c)
        dev_id = _device(c, db, device) if device else None
        try:
            rows = ignores.list_ignores(db, dev_id)
        except ignores.IgnoreError as e:
            _ignore_fail(c, e)
        table = [[str(r["id"]), str(r["device_id"]), r["rule"], r["node"], r["reason"]] for r in rows]
        header = ["id", c.t("ignore.col.device"), c.t("rules.col.id"), c.t("ignore.col.node"), c.t("ignore.col.reason")]
        emit(c, {"ignores": rows}, output.table(table, header) if rows else c.t("ignore.none"))

    @ignore_app.command("add", help="忽略一条检查发现（必须写原因）/ ignore a finding")
    def ignore_add(
        ctx: typer.Context,
        device: Annotated[str, typer.Argument(help="设备名")],
        rule: Annotated[str, typer.Argument(help="规则编号")],
        node: Annotated[str, typer.Argument(help="发现的节点（检查结果中的 node）")],
        reason: Annotated[str, typer.Option("--reason", help="忽略原因（必填）")] = "",
    ) -> None:
        c = output.get(ctx)
        db = require_db(c)
        dev_id = _device(c, db, device)
        kb, root = _kb(c)
        try:
            known = set(checks.BUILTIN) | {r.id for r in rulesmod.load_dir(kb, checks.rules_dir(root))}
        except rulesmod.RuleError as e:
            rule_error(c, e)
        try:
            row = ignores.add_ignore(db, dev_id, rule, node, reason, known)
        except ignores.IgnoreError as e:
            _ignore_fail(c, e)
        emit(c, row, c.t("ignore.added", id=row["id"], rule=row["rule"], node=row["node"]))

    @ignore_app.command("remove", help="取消忽略 / remove an ignore")
    def ignore_remove(ctx: typer.Context, ignore_id: Annotated[int, typer.Argument(help="忽略记录编号")]) -> None:
        c = output.get(ctx)
        db = require_db(c)
        try:
            row = ignores.remove_ignore(db, ignore_id)
        except ignores.IgnoreError as e:
            _ignore_fail(c, e)
        emit(c, row, c.t("ignore.removed", id=ignore_id))
