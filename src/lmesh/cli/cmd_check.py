"""配置检查与冗余清理命令：lmesh check、lmesh cleanup。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from lmesh.cli import output
from lmesh.cli.cmd_graph import _graph_for, _kb
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import checks, cleanup
from lmesh.core import rules as rulesmod
from lmesh.core.kb import KnowledgeBase


def rule_error(c: Ctx, e: rulesmod.RuleError) -> NoReturn:
    lines = [c.t("rules.invalid", n=len(e.issues))]
    for i in e.issues:
        lines.append(
            "  "
            + c.t(
                "rules.issue",
                file=i["file"],
                rule=i["rule"] or "-",
                field=i["field"] or "-",
                message=c.t(i["code"], **i["params"]),
            )
        )
    fail(c, output.EXIT_CONFIG, "\n".join(lines), {"issues": e.issues})


def load_rules(c: Ctx, kb: KnowledgeBase, kb_root: Path, rules_dir: Path | None) -> list[rulesmod.Rule]:
    directory = rules_dir or checks.rules_dir(kb_root)
    if rules_dir is not None and not rules_dir.exists():
        fail(c, output.EXIT_NOT_FOUND, c.t("common.not_found", path=rules_dir))
    try:
        return rulesmod.load_dir(kb, directory)
    except rulesmod.RuleError as e:
        rule_error(c, e)


def register(app: typer.Typer) -> None:
    @app.command(
        "check", help="配置检查：悬空引用、孤儿对象、互斥冲突、规则约束；有 error 级发现时退出码 1 / check a config"
    )
    def cmd_check(
        ctx: typer.Context,
        target: Annotated[str, typer.Argument(help="配置文件，或已导入的设备名")],
        rules: Annotated[Path | None, typer.Option("--rules", help="规则目录（默认知识库的 rules/）")] = None,
        severity: Annotated[str, typer.Option(help="最低级别：error | warning | info")] = "info",
        domain: Annotated[str | None, typer.Option(help="只看一个功能域，如 bgp、vrf")] = None,
        profile: Annotated[str | None, typer.Option()] = None,
    ) -> None:
        c = output.get(ctx)
        if severity not in rulesmod.SEVERITIES:
            fail(c, output.EXIT_USAGE, c.t("check.bad_severity"))
        kb, root = _kb(c)
        rule_list = load_rules(c, kb, root, rules)
        g, kb = _graph_for(c, target, profile)
        res = checks.check(g, kb, rule_list, severity, domain)
        s = res["summary"]
        lines = [
            c.t(
                "check.summary",
                device=res["device"],
                profile=res["profile"],
                total=s["total"],
                **s["by_severity"],
            )
        ]
        if not res["findings"]:
            lines.append(c.t("check.none"))
        for f in res["findings"]:
            where = f"{c.t('check.line')} {','.join(map(str, f['lines']))}" if f["lines"] else ""
            lines.append(f"[{c.t('check.severity.' + f['severity'])}] {f['rule']}  {f['node']}  {where}".rstrip())
            lines.append("    " + checks.render_text(f["message"], c.lang, res["texts"]))
            lines.append("    " + c.t("check.fix") + checks.render_text(f["suggestion"], c.lang, res["texts"]))
        emit(c, res, "\n".join(lines))
        if s["has_errors"]:  # 退出码 1，摘要同时写 stderr（脚本里只看 stderr 也能知道原因）
            typer.echo(lines[0], err=True)
            raise typer.Exit(output.EXIT_ERROR)

    @app.command("cleanup", help="冗余清理：为孤儿对象（含级联孤儿）生成删除脚本 / generate a cleanup script")
    def cmd_cleanup(
        ctx: typer.Context,
        target: Annotated[str, typer.Argument(help="配置文件，或已导入的设备名")],
        out: Annotated[Path | None, typer.Option("-o", "--out", help="把删除脚本写到文件")] = None,
        profile: Annotated[str | None, typer.Option()] = None,
    ) -> None:
        c = output.get(ctx)
        g, kb = _graph_for(c, target, profile)
        res = cleanup.cleanup(g, kb)
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(res["script"], encoding="utf-8", newline="\n")
            res["written"] = str(out)
        lines = [
            c.t(
                "cleanup.summary",
                device=res["device"],
                objects=len(res["objects"]),
                commands=len(res["commands"]),
                fallbacks=res["fallbacks"],
            )
        ]
        if not res["commands"]:
            lines.append(c.t("cleanup.none"))
        elif out is None:
            lines.append(res["script"].rstrip("\n"))
        else:
            lines.append(c.t("cleanup.written", path=out))
        for s in res["skipped"]:
            lines.append(c.t("cleanup.skipped", node=s["node"], lines=",".join(map(str, s["lines"]))))
        ok = res["verify"]["ok"]
        lines.append(c.t("cleanup.verify_ok") if ok else c.t("cleanup.verify_failed"))
        emit(c, res, "\n".join(lines))
        if not ok:
            typer.echo(c.t("cleanup.verify_failed"), err=True)
            raise typer.Exit(output.EXIT_ERROR)
