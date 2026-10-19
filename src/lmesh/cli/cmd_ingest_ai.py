"""文档导入、批量审核、AI 命令：lmesh kb ingest、lmesh review approve-all、lmesh ai …。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from lmesh.cli import cmd_ai, output
from lmesh.cli.cmd_configs import require_db
from lmesh.cli.cmd_kb import _root
from lmesh.cli.output import emit, fail
from lmesh.core import ai, config


def register(app: typer.Typer) -> None:
    kb_app = next(g.typer_instance for g in app.registered_groups if g.name == "kb")
    review_app = next(g.typer_instance for g in app.registered_groups if g.name == "review")
    ai_app = typer.Typer(no_args_is_help=True, help="AI 接口 / AI")
    app.add_typer(ai_app, name="ai")
    assert kb_app is not None and review_app is not None

    @kb_app.command("ingest", help="导入产品文档并按抽取规则生成命令卡（draft），送审核队列 / ingest product docs")
    def kb_ingest(
        ctx: typer.Context,
        doc: Annotated[Path, typer.Argument(help="文档目录或文件（Markdown / HTML / PDF / CHM）")],
        rules: Annotated[
            str, typer.Option(help="抽取规则：knowledge/extractors/ 下的名称（如 huawei-vrp8-md）或文件路径")
        ],
        domain: Annotated[list[str] | None, typer.Option(help="只抽取这些功能域（可多次）")] = None,
        version: Annotated[str, typer.Option(help="文档对应的软件版本，记入命令卡来源")] = "",
        use_ai: Annotated[bool, typer.Option("--ai", help="规则抽取失败的命令交给 AI 修正（需要已配置 AI）")] = False,
    ) -> None:
        c = output.get(ctx)
        if not doc.exists():
            fail(c, output.EXIT_NOT_FOUND, c.t("common.not_found", path=doc))
        from lmesh.core.ingest.convert import ConvertError
        from lmesh.core.ingest.service import ingest

        settings = config.load()
        root = _root(c)
        if use_ai and not ai.is_configured(settings):
            fail(c, output.EXIT_CONFIG, c.t("ai.not_configured"), ai.not_configured_data(settings))

        def progress(pct: int, msg: str) -> None:
            if not c.quiet and c.output == "text" and c.verbose:
                typer.echo(f"[{pct:3d}%] {msg}", err=True)

        try:
            res = ingest(doc, rules, root, require_db(c), settings, domain, version, use_ai, progress)
        except FileNotFoundError:
            fail(c, output.EXIT_NOT_FOUND, c.t("ingest.rules_not_found", rules=rules))
        except ConvertError as e:
            fail(c, output.EXIT_EXTERNAL, c.t(str(e)))
        m = res["merge"]
        text = c.t(
            "ingest.summary",
            files=res["files"],
            commands=res["commands"],
            cards=res["cards"],
            new=m.get("new", 0),
            updated=m.get("updated_draft", 0),
            changed=m.get("changed_reviewed", 0),
            unchanged=m.get("unchanged", 0),
            reviews=res["review_items"],
        )
        if res["skipped"]:
            text += "\n" + c.t("ingest.skipped", detail=", ".join(f"{k} {v}" for k, v in res["skipped"].items()))
        emit(c, res, text)

    @review_app.command("approve-all", help="批量通过：按类型、标题关键字、抽取规则筛选 / batch approve")
    def review_approve_all(
        ctx: typer.Context,
        kind: Annotated[str, typer.Option(help="条目类型")] = "card",
        contains: Annotated[str | None, typer.Option(help="标题包含的文字")] = None,
        rules: Annotated[str | None, typer.Option(help="只通过这个抽取规则产生的条目")] = None,
    ) -> None:
        c = output.get(ctx)
        from lmesh.core.ingest.service import approve_matching

        if not c.yes and not typer.confirm(c.t("review.approve_all_confirm"), default=False):
            raise typer.Exit(output.EXIT_ERROR)
        res = approve_matching(require_db(c), _root(c), kind, contains, rules)
        emit(c, res, c.t("review.approved_n", n=res["approved"], failed=res["failed"]))

    cmd_ai.register(ai_app)

    @ai_app.command("test", help="测试当前生效的 AI 接口（按 --as 账号的选择）/ test the effective AI connection")
    def ai_test(ctx: typer.Context) -> None:
        c = output.get(ctx)
        settings = config.load()
        require_db(c)
        if not ai.is_configured(settings):
            fail(c, output.EXIT_CONFIG, c.t("ai.not_configured"), ai.not_configured_data(settings))
        try:
            res = ai.test(settings)
        except ai.AIError as e:
            fail(c, output.EXIT_EXTERNAL, c.t(str(e)))
        emit(c, res, c.t("ai.test_ok", model=res["model"], reply=res["reply"]))

    @ai_app.command("calls", help="最近的 AI 调用记录（发起人、接口）/ recent AI calls")
    def ai_calls(
        ctx: typer.Context,
        limit: Annotated[int, typer.Option()] = 20,
        user: Annotated[str | None, typer.Option("--user", help="只看这个账号的")] = None,
    ) -> None:
        c = output.get(ctx)
        calls = ai.recent_calls(require_db(c), limit, actor=user)
        rows = [
            [
                str(x["id"]),
                str(x["user"] or "—"),
                str(x["connection"] or "—"),
                str(x["feature"]),
                str(x["model"]),
                f"{x['tokens_in']}/{x['tokens_out']}",
                str(x["status"]),
            ]
            for x in calls
        ]
        head = [
            "#",
            c.t("ai.col.user"),
            c.t("ai.col.connection"),
            c.t("ai.task"),
            c.t("ai.model"),
            "tokens",
            c.t("review.status"),
        ]
        emit(
            c,
            {"calls": calls},
            output.table(rows, head) if rows else c.t("ai.no_calls"),
        )
