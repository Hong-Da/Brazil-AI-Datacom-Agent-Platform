"""翻译自定义规则（REQ-032）命令：lmesh naming list|show|test|match|import|delete；
lmesh translate / migrate / template generate 的 --rules 也在这里取规则集。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from lmesh.cli import output
from lmesh.cli.cmd_graph import _graph_for, _kb
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import importer, migration, naming
from lmesh.core.kb import KnowledgeBase

_SHOW = 40


def rules_fail(c: Ctx, e: naming.RulesError) -> NoReturn:
    if e.kind == "not_found":
        fail(c, output.EXIT_NOT_FOUND, c.t(e.key, **e.fmt))
    if e.kind == "invalid":
        lines = [c.t("naming.invalid", n=len(e.issues))]
        lines += [f"  {i['where']}: {c.t(i['key'], **i['args'])}" for i in e.issues]
        fail(c, output.EXIT_CONFIG, "\n".join(lines), {"issues": e.issues})
    fail(c, output.EXIT_ERROR if e.kind in ("readonly", "exists") else output.EXIT_USAGE, c.t(e.key, **e.fmt))


def load_rules(c: Ctx, ref: str | None, kb: KnowledgeBase, root: Path | None = None) -> naming.RuleSet | None:
    """--rules：规则集文件或已保存的规则集编号。"""
    if not ref:
        return None
    try:
        return naming.load(root if root is not None else _kb(c)[1], ref, kb)
    except naming.RulesError as e:
        rules_fail(c, e)


def _rule_ref(c: Ctx, r: dict[str, Any] | None) -> str:
    if not r:
        return c.t("naming.rule.none")
    return c.t(f"naming.rule.{r['section']}", n=int(r["index"]) + 1)


def report_text(c: Ctx, rep: dict[str, Any]) -> str:
    s = rep["summary"]
    lines = [c.t("naming.summary", **s)]
    if rep["renames"]:
        lines.append(f"[{c.t('naming.section.renames')}] {len(rep['renames'])}")
        for r in rep["renames"][:_SHOW]:
            mark = "" if r["applied"] else f"  ({c.t('naming.not_applied', kind=r['conflict'])})"
            fixes = f"  [{', '.join(r['fixes'])}]" if r["fixes"] else ""
            lines.append(
                f"  {r['type']}  {r['from']} → {r['to']}  {_rule_ref(c, r['rule'])}{fixes}  "
                + c.t("naming.refs", n=r["refs"])
                + mark
            )
    if rep["ports"]:
        lines.append(f"[{c.t('naming.section.ports')}] {len(rep['ports'])}")
        for p in rep["ports"][:_SHOW]:
            mark = "" if p["applied"] else f"  ({c.t('naming.not_applied', kind='conflict')})"
            lines.append(f"  {p['from']} → {p['to']}  {_rule_ref(c, p['rule'])}  +{p['subinterfaces']}{mark}")
    for title, items, fmt in (
        ("naming.section.conflicts", rep["conflicts"], lambda x: c.t(f"naming.conflict.{x['kind']}", **_cf(x))),
        ("naming.section.naming", rep["naming"], lambda x: c.t(f"naming.problem.{x['problem']}", **x)),
        ("naming.section.text_refs", rep["text_refs"], lambda x: c.t("naming.text_ref", **x)),
        ("naming.section.gaps", rep["gaps"], lambda x: c.t("naming.gap.name_limit_unknown", **x)),
    ):
        if items:
            lines.append(f"[{c.t(title)}] {len(items)}")
            lines += [f"  {fmt(x)}" for x in items[:_SHOW]]
    return "\n".join(lines)


def _cf(x: dict[str, Any]) -> dict[str, Any]:
    return {**x, "from": ", ".join(x["from"])}


def register(app: typer.Typer) -> None:
    napp = typer.Typer(
        no_args_is_help=True, help="翻译自定义规则：命名规范、名称映射、端口映射 / translation rule sets"
    )
    app.add_typer(napp, name="naming")

    @napp.command("list", help="规则集列表（内置与我的）/ list rule sets")
    def n_list(ctx: typer.Context) -> None:
        c = output.get(ctx)
        kb, root = _kb(c)
        items = naming.list_sets(root, kb)
        rows = [
            [
                i["id"],
                c.t("naming.builtin") if i["builtin"] else c.t("naming.mine"),
                f"{i.get('from') or '*'} → {i.get('to') or '*'}" if i.get("valid") else "-",
                " / ".join(str(i["counts"][k]) for k in ("names", "naming", "ports")) if i.get("valid") else "-",
                "" if i.get("valid") else c.t("naming.invalid", n=len(i["issues"])),
            ]
            for i in items
        ]
        header = [c.t("naming.col.id"), c.t("naming.col.kind"), c.t("naming.col.dir"), c.t("naming.col.counts"), ""]
        emit(c, items, output.table(rows, header) if rows else c.t("naming.none"))

    @napp.command("show", help="显示规则集的 YAML 原文 / show a rule set")
    def n_show(ctx: typer.Context, rule_set: Annotated[str, typer.Argument(help="规则集编号或文件")]) -> None:
        c = output.get(ctx)
        kb, root = _kb(c)
        rs = load_rules(c, rule_set, kb, root)
        assert rs is not None
        p = Path(rule_set)
        text = p.read_text(encoding="utf-8") if p.is_file() else naming.source(root, rs.id)[0]
        emit(c, {**rs.info(), "rules": rs.as_dict(), "source": text}, text)

    @napp.command("test", help="试运行：对一份配置按规则集改名，列出改名清单、冲突与命名规范告警 / dry run")
    def n_test(
        ctx: typer.Context,
        rule_set: Annotated[str, typer.Argument(help="规则集编号或文件")],
        target: Annotated[str, typer.Argument(help="配置文件，或已导入的设备名")],
        to: Annotated[str | None, typer.Option("--to", help="目标 Profile（取名称长度上限）")] = None,
        target_config: Annotated[
            Path | None, typer.Option("--target-config", help="目标设备现有配置（新名与其中已有的名称重名时报冲突）")
        ] = None,
        profile: Annotated[str | None, typer.Option(help="源配置的 Profile（不给时自动识别）")] = None,
    ) -> None:
        c = output.get(ctx)
        g, kb = _graph_for(c, target, profile)
        rs = load_rules(c, rule_set, kb)
        assert rs is not None
        if to and to not in kb.profiles:
            fail(c, output.EXIT_USAGE, c.t("parse.profile_unknown", profile=to))
        tg = None
        if target_config is not None:
            if not target_config.is_file() or not to:
                fail(c, output.EXIT_USAGE, c.t("naming.target_needs_to"))
            try:
                tg = migration.target_graph_from_text(importer.decode(target_config.read_bytes()), kb, to)
            except migration.MigrateError as e:
                fail(c, output.EXIT_USAGE, c.t(e.key, **e.fmt))
        _, _, rep = naming.run(g, kb, rs, to, tg)
        rep["source"] = {"device": g.graph.get("device"), "profile": g.graph.get("profile")}
        emit(c, rep, report_text(c, rep))
        if rep["conflicts"]:
            output.err_summary(c, c.t("naming.has_conflicts", n=len(rep["conflicts"])))
            raise typer.Exit(output.EXIT_ERROR)

    @napp.command("match", help="测试一个名称或接口名经过规则后的结果 / test one name or interface")
    def n_match(
        ctx: typer.Context,
        rule_set: Annotated[str, typer.Argument(help="规则集编号或文件")],
        value: Annotated[str, typer.Argument(help="名称或接口名")],
        otype: Annotated[
            str, typer.Option("--type", help="对象类型（Schema 编号，如 vrf.instance）；--port 时不用")
        ] = "*",
        port: Annotated[bool, typer.Option("--port", help="按端口映射测试接口名")] = False,
        to: Annotated[str | None, typer.Option("--to", help="目标 Profile（取名称长度上限）")] = None,
    ) -> None:
        c = output.get(ctx)
        kb, root = _kb(c)
        rs = load_rules(c, rule_set, kb, root)
        assert rs is not None
        family = kb.profiles[to].family if to and to in kb.profiles else ""
        r = naming.test_input(rs, "port" if port else "name", value, otype, kb, family)
        text = f"{r['from']} → {r['result']}  {_rule_ref(c, {'section': 'ports' if port else 'names', 'index': r['rule']} if r['rule'] is not None else None)}"
        for p in r.get("problems") or []:
            text += "\n  " + c.t(f"naming.problem.{p['problem']}", name=r["result"], **p)
        emit(c, r, text)

    @napp.command("import", help="导入规则集文件到 data/translate-rules/ / import a rule set")
    def n_import(
        ctx: typer.Context,
        file: Annotated[Path, typer.Argument(help="规则集 YAML 文件")],
        rid: Annotated[str | None, typer.Option("--id", help="保存用的编号（不给时用文件中的 id）")] = None,
        overwrite: Annotated[bool, typer.Option("--overwrite", help="同编号已存在时覆盖")] = False,
    ) -> None:
        c = output.get(ctx)
        kb, root = _kb(c)
        if not file.is_file():
            fail(c, output.EXIT_NOT_FOUND, c.t("common.not_found", path=file))
        text = file.read_text(encoding="utf-8")
        try:
            if rid:
                data = naming.parse(text, kb, rid).as_dict()
                rs = naming.save(root, rid, {**data, "id": rid}, kb, overwrite=overwrite)
            else:
                rs = naming.save(root, naming.parse(text, kb).id, text, kb, overwrite=overwrite)
        except naming.RulesError as e:
            rules_fail(c, e)
        emit(c, rs.info(), c.t("naming.saved", id=rs.id, path=str(naming.user_dir() / rs.file)))

    @napp.command("delete", help="删除我的规则集（内置的只读）/ delete a rule set")
    def n_delete(ctx: typer.Context, rid: Annotated[str, typer.Argument(help="规则集编号")]) -> None:
        c = output.get(ctx)
        _, root = _kb(c)
        try:
            naming.delete(root, rid)
        except naming.RulesError as e:
            rules_fail(c, e)
        emit(c, {"id": rid, "deleted": True}, c.t("naming.deleted", id=rid))
