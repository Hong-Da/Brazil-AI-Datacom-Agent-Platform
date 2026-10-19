"""解析与知识库映射命令：lmesh parse、lmesh unknown list、lmesh kb map。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from lmesh.cli import output
from lmesh.cli.cmd_configs import require_db
from lmesh.cli.cmd_kb import _root
from lmesh.cli.output import emit, fail
from lmesh.core import analysis, importer


def register(app: typer.Typer) -> None:
    kb_app = next(g.typer_instance for g in app.registered_groups if g.name == "kb")
    unknown_app = typer.Typer(no_args_is_help=True, help="未识别的配置行 / unknown lines")
    app.add_typer(unknown_app, name="unknown")
    assert kb_app is not None

    @app.command("parse", help="解析配置为带行号的结构化 JSON / parse a config")
    def cmd_parse(
        ctx: typer.Context,
        file: Annotated[Path, typer.Argument(help="配置文件")],
        profile: Annotated[str | None, typer.Option(help="Profile；不填时按厂商与版本自动选择")] = None,
        lines: Annotated[bool, typer.Option("--lines/--summary", help="输出每一行的结果（JSON 时默认输出）")] = False,
    ) -> None:
        c = output.get(ctx)
        if not file.exists():
            fail(c, output.EXIT_NOT_FOUND, c.t("common.not_found", path=file))
        # 只读操作：未配置时使用程序自带的知识库
        from lmesh import paths
        from lmesh.core import config

        kb = analysis.load_kb(_root(c) if config.is_configured() else paths.builtin_knowledge_dir())
        text = importer.decode(file.read_bytes())
        try:
            res = analysis.parse_text(text, kb, profile)
        except analysis.AnalysisError as e:
            fail(c, output.EXIT_USAGE, c.t(str(e), profile=profile or ""))
        data = (
            res.as_dict() if (lines or c.output == "json") else {k: v for k, v in res.as_dict().items() if k != "lines"}
        )
        cnt = res.parsed.counts()
        text_out = c.t(
            "parse.summary",
            profile=res.profile,
            command=cnt.get("command", 0),
            unknown=cnt.get("unknown", 0),
            raw=cnt.get("raw", 0),
            coverage=f"{res.parsed.coverage():.1%}",
        )
        for ln in res.parsed.unknown()[:20]:
            text_out += f"\n  ? {ln.no:5}  {ln.view:<14} {ln.text}"
        emit(c, data, text_out)

    @unknown_app.command("list", help="已导入配置中的未识别行，按出现次数汇总 / list unknown lines")
    def unknown_list(ctx: typer.Context, limit: Annotated[int, typer.Option()] = 50) -> None:
        c = output.get(ctx)
        rows = analysis.unknown_summary(require_db(c), limit)
        emit(
            c,
            {"patterns": rows},
            output.table(
                [[str(r["count"]), r["view"], r["pattern"], r["example"]] for r in rows],
                [c.t("unknown.count"), c.t("unknown.view"), c.t("unknown.pattern"), c.t("unknown.example")],
            )
            if rows
            else c.t("unknown.none"),
        )

    @kb_app.command("map", help="把映射规则写进命令卡，并重新汇总 Profile / apply mapping rules")
    def kb_map(
        ctx: typer.Context,
        family: Annotated[
            list[str] | None, typer.Option("--family", help="只处理这些平台族 / only these platform families")
        ] = None,
    ) -> None:
        c = output.get(ctx)
        res = analysis.apply_mappings(_root(c), family or None)
        emit(
            c,
            res,
            c.t(
                "kb.mapped",
                cards=sum(v["mapped"] + v["unchanged"] for v in res["families"].values()),
                profiles=len(res["profiles"]),
            ),
        )
