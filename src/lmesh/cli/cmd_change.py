"""增量变更与影响分析命令：
lmesh change <当前> <目标> [-o 脚本] [--rollback 文件] [--style huawei|cisco] [--plain] [--report 文件]；
lmesh impact <配置|设备> --node <节点>... [--direction up|down|both]。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from lmesh.cli import output
from lmesh.cli.cmd_compare import _side
from lmesh.cli.cmd_graph import _graph_for, _kb
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import change, compare, impact, report, report_change, terms

_SHOW = 40


def _namer(c: Ctx, style: str | None) -> Any:
    if style is None:
        return None
    if style not in terms.STYLES:
        fail(c, output.EXIT_USAGE, c.t("change.bad_style"))
    kb, root = _kb(c)
    return terms.namer(root, kb, style)


def text_report(c: Ctx, r: dict[str, Any]) -> str:
    s = r["summary"]
    lines = [c.t("change.header", a=r["current"]["label"], b=r["target"]["label"], family=r["family"])]
    if r["equal"]:
        lines.append(c.t("change.equal"))
        return "\n".join(lines)
    lines.append(
        c.t(
            "change.summary",
            ops=s["ops"],
            risk=c.t(f"change.risk.{r['risk']['level']}"),
            fallbacks=s["fallbacks"],
            **s["by_action"],
        )
    )
    for title, part in (("", r), ("rollback", r.get("rollback"))):
        if not part or part.get("verify") is None:
            continue
        v = part["verify"]
        msg = (
            c.t("change.verify_ok")
            if v["ok"]
            else c.t(
                "change.verify_bad",
                diffs=v["diff_count"],
                dangling=len(v["new_dangling"]),
                order=len(v["order_violations"]),
                issues=len(v["issues"]),
            )
        )
        lines.append((c.t("change.rollback", ops=len(part["ops"])) + "：" if title else "") + msg)
    imp = r.get("impact") or {}
    if imp.get("business"):
        types = ", ".join(f"{k} {len(v)}" for k, v in imp["by_business"].items())
        lines.append(c.t("change.impact", n=len(imp["business"]), types=types))
    for d in r["ops"][:_SHOW]:
        lines.append("  " + change.note_text(d, c.lang))
    return "\n".join(lines)


def impact_text(c: Ctx, r: dict[str, Any]) -> str:
    s = r["summary"]
    lines = [
        c.t(
            "impact.summary", direction=r["direction"], **{k: s[k] for k in ("seeds", "objects", "business", "domains")}
        )
    ]
    if r["business"]:
        lines.append(f"[{c.t('impact.section.business')}]")
        for b in r["business"][:_SHOW]:
            lines.append(f"  {b['type']:<9} {b['node']}")
            lines.append(f"            {' → '.join(b['path'])}")
    if r["by_domain"]:
        lines.append(f"[{c.t('impact.section.domains')}]")
        for dm, v in r["by_domain"].items():
            lines.append(f"  {dm}: {v['objects']}")
    return "\n".join(lines)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def register(app: typer.Typer) -> None:
    @app.command(
        "change",
        help="增量变更脚本：当前 → 目标（同一平台族），按依赖排序、补发副作用，附回滚脚本与模拟验证 / change script",
    )
    def cmd_change(
        ctx: typer.Context,
        current: Annotated[str, typer.Argument(help="当前配置：配置文件，或设备名（设备名@版本编号）")],
        target: Annotated[str, typer.Argument(help="目标配置：配置文件，或设备名（设备名@版本编号）")],
        out: Annotated[
            Path | None, typer.Option("-o", "--out", help="把下发脚本写到文件（不给时写到标准输出）")
        ] = None,
        rollback: Annotated[Path | None, typer.Option("--rollback", help="把回滚脚本写到文件")] = None,
        style: Annotated[
            str | None, typer.Option("--style", help="说明文字中对象的显示风格：huawei | cisco | nokia（不影响命令）")
        ] = None,
        plain: Annotated[bool, typer.Option("--plain", help="脚本不带说明行（直接粘贴到设备）")] = False,
        profile: Annotated[str | None, typer.Option(help="两份配置使用的 Profile（不给时自动识别）")] = None,
        no_verify: Annotated[bool, typer.Option("--no-verify", help="不做模拟执行验证")] = False,
        report_file: Annotated[
            Path | None, typer.Option("--report", help="同时导出变更报告（.html 或 .md，按扩展名）")
        ] = None,
        report_lang: Annotated[
            str | None, typer.Option("--report-lang", help="报告语言 zh-CN | en（默认跟随界面语言，pt-BR 用英文）")
        ] = None,
    ) -> None:
        c = output.get(ctx)
        kb, _ = _kb(c)
        namer = _namer(c, style)
        try:
            a = _side(c, kb, current, profile)
            b = _side(c, kb, target, profile)
            r = change.change(a, b, kb, verify_scripts=not no_verify, namer=namer, lang=c.lang)
        except compare.CompareError as e:
            fail(c, output.EXIT_NOT_FOUND if e.kind == "not_found" else output.EXIT_USAGE, c.t(e.key, **e.fmt))
        except change.ChangeError as e:
            fail(c, output.EXIT_USAGE, c.t(e.key, **e.fmt))
        key = "script_plain" if plain else "script"
        summary = text_report(c, r)
        notes: list[str] = []
        data: dict[str, Any] = dict(r)
        if out is not None:
            _write(out, r[key])
            notes.append(c.t("change.written", path=out))
            data["out"] = str(out)
        if rollback is not None:
            _write(rollback, r["rollback"][key])
            notes.append(c.t("change.rollback_written", path=rollback))
            data["rollback_out"] = str(rollback)
        if report_file is not None:
            fmt = "md" if report_file.suffix.lower() == ".md" else "html"
            try:
                rep = report_change.change_report(r, report.report_lang(report_lang or c.lang), fmt, namer=namer)
            except report.ReportError as e:
                fail(c, output.EXIT_USAGE, c.t(e.key, **e.fmt))
            _write(report_file, rep.content)
            notes.append(c.t("change.report_written", path=report_file))
            data["report_out"] = str(report_file)
        if out is not None:
            emit(c, data, "\n".join([summary, *notes]))
        else:
            emit(c, data, r[key])
            if c.output == "text" and not c.quiet:
                sys.stderr.write("\n".join([summary, *notes]) + "\n")  # 脚本单独占 stdout，便于重定向
        bad = [p for p in (r, r.get("rollback")) if p and p.get("verify") and not p["verify"]["ok"]]
        if bad:
            raise typer.Exit(output.EXIT_ERROR)

    @app.command("impact", help="变更影响分析：沿依赖边求一组节点的影响范围与受影响的业务对象 / impact analysis")
    def cmd_impact(
        ctx: typer.Context,
        target: Annotated[str, typer.Argument(help="配置文件，或已导入的设备名")],
        node: Annotated[list[str], typer.Option("--node", help="节点编号（可重复；也可以写对象编号中唯一的一段）")],
        direction: Annotated[
            str, typer.Option("--direction", help="up：谁受影响（默认）；down：依赖谁；both：两个方向")
        ] = "up",
        profile: Annotated[str | None, typer.Option(help="配置的 Profile（不给时自动识别）")] = None,
    ) -> None:
        c = output.get(ctx)
        g, kb = _graph_for(c, target, profile)
        try:
            r = impact.analyze(g, kb, node, direction)
        except impact.ImpactError as e:
            fail(c, output.EXIT_NOT_FOUND if e.kind == "not_found" else output.EXIT_USAGE, c.t(e.key, **e.fmt))
        emit(c, r, impact_text(c, r))
