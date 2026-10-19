"""安全基线审计命令：lmesh baseline [设备…|--all|文件…] [--profile basic|strict]。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from lmesh.cli import output
from lmesh.cli.cmd_check import rule_error
from lmesh.cli.cmd_configs import require_db
from lmesh.cli.cmd_graph import _graph_for, _kb
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import baseline as blmod
from lmesh.core import graphstore, importer
from lmesh.core import rules as rulesmod
from lmesh.core.kb import KnowledgeBase


def _bad_profile(c: Ctx, e: blmod.BaselineError) -> NoReturn:
    fail(c, output.EXIT_USAGE, c.t(e.key, **e.fmt))


def load_baseline(c: Ctx, kb: KnowledgeBase, kb_root: Path, rules_dir: Path | None) -> blmod.Baseline:
    if rules_dir is not None and not rules_dir.exists():
        fail(c, output.EXIT_NOT_FOUND, c.t("common.not_found", path=rules_dir))
    try:
        return blmod.load(kb, rules_dir or blmod.baseline_dir(kb_root))
    except rulesmod.RuleError as e:
        rule_error(c, e)


def _all_graphs(c: Ctx, kb: KnowledgeBase) -> list[Any]:
    db = require_db(c)
    devs = [d for d in importer.list_devices(db) if d["latest_version_id"]]
    if not devs:
        fail(c, output.EXIT_NOT_FOUND, c.t("baseline.no_devices"))
    return [graphstore.build_for_version(db, d["latest_version_id"], kb)[0] for d in devs]


def _text(c: Ctx, res: dict[str, Any]) -> str:
    s = res["summary"]
    score = "—" if s["score"] is None else s["score"]
    lines = [
        c.t(
            "baseline.summary",
            baseline=res["baseline"],
            devices=s["devices"],
            rules=s["rules"],
            score=score,
            passed=s["pass"],
            failed=s["fail"],
            na=s["na"],
        )
    ]
    mark = {"pass": "✓", "fail": "✗", "na": "—"}
    if len(res["devices"]) > 1:
        header = [c.t("baseline.rule")] + [str(d["device"]) for d in res["devices"]]
        rows = [
            [rid] + [mark[v] for v in cells]
            for rid, cells in zip(res["matrix"]["rules"], res["matrix"]["cells"], strict=True)
        ]
        rows.append([c.t("baseline.score")] + ["—" if d["score"] is None else str(d["score"]) for d in res["devices"]])
        lines += ["", output.table(rows, header)]
    for d in res["devices"]:
        sm = d["summary"]
        lines += [
            "",
            c.t(
                "baseline.device",
                device=d["device"],
                family=d["family"],
                score="—" if d["score"] is None else d["score"],
                passed=sm["pass"],
                failed=sm["fail"],
                na=sm["na"],
            ),
        ]
        if not d["failures"]:
            lines.append("  " + c.t("baseline.all_pass"))
        for f in d["failures"]:
            where = f"{c.t('check.line')} {','.join(map(str, f['lines']))}" if f["lines"] else ""
            lines.append(f"  [{c.t('check.severity.' + f['severity'])}] {f['rule']}  {f['node']}  {where}".rstrip())
            lines.append("      " + blmod.render_text(f["message"], c.lang, res["texts"]))
            lines.append("      " + c.t("check.fix") + blmod.render_text(f["suggestion"], c.lang, res["texts"]))
            if f["remedy"]:
                lines.append("      " + c.t("baseline.remedy") + " | ".join(x.strip() for x in f["remedy"]))
    return "\n".join(lines)


def register(app: typer.Typer) -> None:
    @app.command(
        "baseline",
        help="安全基线审计：设备 × 规则矩阵、不符合项、分数；有 error 级规则不通过时退出码 1 / security baseline audit",
    )
    def cmd_baseline(
        ctx: typer.Context,
        targets: Annotated[list[str] | None, typer.Argument(help="配置文件或已导入的设备名（可多个）")] = None,
        all_devices: Annotated[bool, typer.Option("--all", help="全部已导入设备的最新配置版本")] = False,
        profile: Annotated[str, typer.Option("--profile", help="基线：basic | strict（见 --list-rules）")] = "basic",
        rules: Annotated[Path | None, typer.Option("--rules", help="规则目录（默认知识库的 rules/）")] = None,
        parse_profile: Annotated[
            str | None, typer.Option("--parse-profile", help="配置文件的知识库 Profile（默认自动识别）")
        ] = None,
        list_rules: Annotated[bool, typer.Option("--list-rules", help="只列出基线与规则")] = False,
        report_out: Annotated[
            Path | None, typer.Option("--report", help="同时导出基线报告（.html 或 .md，按扩展名）")
        ] = None,
        report_lang: Annotated[
            str | None, typer.Option("--report-lang", help="报告语言 zh-CN | en（默认跟随界面语言，pt-BR 用 en）")
        ] = None,
        style: Annotated[
            str | None,
            typer.Option("--style", help="报告中节点的显示风格 huawei | cisco | nokia（默认取配置 ui.term_style）"),
        ] = None,
    ) -> None:
        c = output.get(ctx)
        kb, root = _kb(c)
        bl = load_baseline(c, kb, root, rules)
        if profile not in bl.profiles:
            allowed = ", ".join(bl.profiles) or "-"
            _bad_profile(c, blmod.BaselineError("baseline.unknown_profile", profile=profile, allowed=allowed))
        if list_rules:
            data = blmod.list_rules(bl, profile)
            listing = [c.t("baseline.list", n=data["total"])]
            listing += [f"  {p['id']}: {p['rules']}  ({', '.join(p['chain'])})" for p in data["profiles"]]
            listing += [f"  [{r['severity']}] {r['id']}  {r['title'].get(c.lang, r['id'])}" for r in data["rules"]]
            emit(c, data, "\n".join(listing))
            return
        if not targets and not all_devices:
            fail(c, output.EXIT_USAGE, c.t("baseline.no_target"))
        graphs = _all_graphs(c, kb) if all_devices else []
        for t in targets or []:
            graphs.append(_graph_for(c, t, parse_profile)[0])
        res = blmod.audit(graphs, bl, profile)
        if report_out is not None:
            from lmesh.cli.cmd_report import _args, _namer
            from lmesh.core.report_baseline import baseline_report

            fmt = "md" if report_out.suffix.lower() == ".md" else "html"
            use = _args(c, report_lang, fmt)
            rep = baseline_report(
                res, use, fmt, namer=_namer(c, kb, root, style), kb_version=graphs[0].graph.get("kb_version")
            )
            report_out.parent.mkdir(parents=True, exist_ok=True)
            report_out.write_text(rep.content, encoding="utf-8", newline="\n")
            res["report"] = {"path": str(report_out), "lang": use, "format": fmt, "filename": rep.filename}
        text = _text(c, res)
        if report_out is not None:
            text += "\n\n" + c.t("report.written", path=report_out)
        emit(c, res, text)
        if res["summary"]["has_errors"]:  # 与 lmesh check 一致：error 级规则不通过时退出码 1，摘要同时写 stderr
            typer.echo(text.splitlines()[0], err=True)
            raise typer.Exit(output.EXIT_ERROR)
