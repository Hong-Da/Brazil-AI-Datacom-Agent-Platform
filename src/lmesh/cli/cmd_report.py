"""报告导出命令：lmesh report compare A B、lmesh report check 目标（中文 / English，HTML / Markdown）。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from lmesh.cli import output
from lmesh.cli.cmd_check import device_ignores, load_overrides, load_rules
from lmesh.cli.cmd_compare import _fail, _side
from lmesh.cli.cmd_graph import _graph_for, _kb
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import checks, compare, config, graphstore, report
from lmesh.core import rules as rulesmod

LangOpt = Annotated[str | None, typer.Option("--lang", help="报告语言 zh-CN | en（默认跟随界面语言，pt-BR 用 en）")]
FormatOpt = Annotated[str, typer.Option("--format", help="html（自包含、可打印）| md（贴进工单）")]
OutOpt = Annotated[Path | None, typer.Option("-o", "--out", help="写到文件；不给时把报告写到 stdout")]
StyleOpt = Annotated[
    str | None, typer.Option("--style", help="节点的显示风格 huawei | cisco（默认取配置 ui.term_style）")
]


def _namer(c: Ctx, kb: Any, root: Path, style: str | None) -> Any:
    from lmesh.core import terms

    use = style or (str(config.load().get("ui.term_style")) if config.is_configured() else "huawei")
    if use not in terms.STYLES:
        fail(c, output.EXIT_USAGE, c.t("report.bad_style", allowed=", ".join(terms.STYLES)))
    return terms.namer(root, kb, use)


def _args(c: Ctx, lang: str | None, fmt: str) -> str:
    use = lang or report.report_lang(c.lang)
    if use not in report.LANGS:
        fail(c, output.EXIT_USAGE, c.t("report.bad_lang", allowed=", ".join(report.LANGS)))
    if fmt not in report.FORMATS:
        fail(c, output.EXIT_USAGE, c.t("report.bad_format", allowed=", ".join(report.FORMATS)))
    return use


def _deliver(c: Ctx, rep: report.Report, out: Path | None, lang: str, fmt: str) -> None:
    data: dict[str, Any] = {"filename": rep.filename, "lang": lang, "format": fmt, "bytes": len(rep.content.encode())}
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rep.content, encoding="utf-8", newline="\n")
        emit(c, {**data, "path": str(out)}, c.t("report.written", path=out))
    elif c.output == "json":
        emit(c, {**data, "content": rep.content})
    else:
        sys.stdout.write(rep.content)


def _meta(target: str) -> dict[str, Any]:
    """目标是已导入的设备名时取最新配置版本的信息（报告头用）。"""
    if Path(target).exists() or not config.is_configured():
        return {}
    db = config.load().database_url
    dev_id = compare.device_id_by_name(db, target)
    ver = graphstore.latest_version(db, dev_id) if dev_id is not None else None
    return report.version_meta(db, ver.id if ver else None)


def register(app: typer.Typer) -> None:
    report_app = typer.Typer(no_args_is_help=True, help="报告导出 / export reports")
    app.add_typer(report_app, name="report")

    @report_app.command("compare", help="配置对比报告 / comparison report")
    def report_compare(
        ctx: typer.Context,
        a: Annotated[str, typer.Argument(help="A：配置文件，或设备名（设备名@版本编号）")],
        b: Annotated[str, typer.Argument(help="B：配置文件，或设备名（设备名@版本编号）")],
        lang: LangOpt = None,
        fmt: FormatOpt = "html",
        out: OutOpt = None,
        domain: Annotated[str | None, typer.Option(help="只看一个功能域")] = None,
        raw: Annotated[bool, typer.Option("--raw", help="同时比较功能域外的原文行")] = False,
        hide_identity: Annotated[bool, typer.Option("--hide-identity", help="隐藏设备身份差异")] = False,
        interface_map: Annotated[Path | None, typer.Option("--interface-map", help="接口映射表")] = None,
        profile_a: Annotated[str | None, typer.Option("--profile-a")] = None,
        profile_b: Annotated[str | None, typer.Option("--profile-b")] = None,
        rename_threshold: Annotated[float, typer.Option("--rename-threshold")] = 1.0,
        style: StyleOpt = None,
    ) -> None:
        c = output.get(ctx)
        use = _args(c, lang, fmt)
        kb, kb_root = _kb(c)
        namer = _namer(c, kb, kb_root, style)
        try:
            ifmap = compare.load_interface_map(interface_map) if interface_map else None
            sa = _side(c, kb, a, profile_a)
            sb = _side(c, kb, b, profile_b)
            r = compare.compare(
                sa,
                sb,
                kb,
                domain=domain,
                include_raw=raw,
                interface_map=ifmap,
                rename_threshold=rename_threshold,
                hide_identity=hide_identity,
            )
        except compare.CompareError as e:
            _fail(c, e)
        meta: dict[str, dict[str, Any]] = {}
        if config.is_configured():
            db = config.load().database_url
            meta = {k: report.version_meta(db, s.version_id) for k, s in (("a", sa), ("b", sb))}
        _deliver(c, report.compare_report(r, use, fmt, meta, namer=namer), out, use, fmt)

    @report_app.command("check", help="配置检查报告（有孤儿时附清理脚本）/ check report")
    def report_check(
        ctx: typer.Context,
        target: Annotated[str, typer.Argument(help="配置文件，或已导入的设备名")],
        lang: LangOpt = None,
        fmt: FormatOpt = "html",
        out: OutOpt = None,
        severity: Annotated[str, typer.Option(help="最低级别：error | warning | info")] = "info",
        domain: Annotated[str | None, typer.Option(help="只看一个功能域")] = None,
        rules: Annotated[Path | None, typer.Option("--rules", help="规则目录（默认知识库的 rules/）")] = None,
        profile: Annotated[str | None, typer.Option()] = None,
        style: StyleOpt = None,
    ) -> None:
        c = output.get(ctx)
        use = _args(c, lang, fmt)
        if severity not in rulesmod.SEVERITIES:
            fail(c, output.EXIT_USAGE, c.t("check.bad_severity"))
        kb, root = _kb(c)
        rule_list = load_rules(c, kb, root, rules)
        overrides = load_overrides(c, root, rules)
        g, kb = _graph_for(c, target, profile)
        res = checks.check(g, kb, rule_list, severity, domain, overrides, device_ignores(target))
        namer = _namer(c, kb, root, style)
        _deliver(c, report.build_check_report(g, kb, res, use, fmt, _meta(target), namer=namer), out, use, fmt)
