"""特性能力查询命令：lmesh feature [关键词]、lmesh feature-diff <A> <B>。"""

from __future__ import annotations

from typing import Annotated, Any, NoReturn

import typer

from lmesh.cli import output
from lmesh.cli.cmd_graph import _kb
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import features, terms


def _fail(c: Ctx, e: features.FeatureError) -> NoReturn:
    fail(c, output.EXIT_NOT_FOUND if e.kind == "not_found" else output.EXIT_USAGE, c.t(e.key, **e.fmt))


def _cell(c: Ctx, cell: dict[str, Any]) -> str:
    st = cell["state"]
    if st != "supported":
        return c.t(f"feature.state.{st}")
    d = cell.get("default")
    mark = "↑" if cell.get("inherited") else ""
    return f"{mark}{'—' if d is None else d}"


def register(app: typer.Typer) -> None:
    @app.command(
        "feature", help="特性能力查询：哪些 Profile 支持、命令写法、默认值、来源（由知识库计算）/ feature lookup"
    )
    def cmd_feature(
        ctx: typer.Context,
        q: Annotated[str, typer.Argument(help="关键词：节点编号、叫法或命令关键字（空字符串列出全部）")] = "",
        profile: Annotated[list[str] | None, typer.Option("--profile", help="只看这些 Profile（可多次）")] = None,
        family: Annotated[str | None, typer.Option(help="只看一个平台族")] = None,
        domain: Annotated[str | None, typer.Option(help="只看一个功能域")] = None,
        state: Annotated[
            str | None, typer.Option(help="supported | unsupported | unfilled（任一 Profile 符合）")
        ] = None,
        include_same: Annotated[
            bool, typer.Option("--include-same", help="不带关键词时也列出各 Profile 完全相同的特性")
        ] = False,
        detail: Annotated[
            str | None, typer.Option("--detail", help="一个 Schema 节点的完整信息（命令卡、来源、依赖）")
        ] = None,
        limit: Annotated[int, typer.Option(help="最多列出几项")] = 200,
    ) -> None:
        c = output.get(ctx)
        kb, root = _kb(c)
        try:
            if detail:
                r = features.detail(kb, detail, profile)
                lines = [f"{r['node']} ({r['type']}, {r['domain']})"]
                for pid, cell in r["profiles"].items():
                    lines.append(f"  {pid}: {_cell(c, cell)}  {' | '.join(cell.get('syntax', []))}")
                emit(c, r, "\n".join(lines))
                return
            r = features.search(
                kb, q, profile, family, domain, state, include_same, terms=terms.load(root, kb), limit=limit
            )
        except features.FeatureError as e:
            _fail(c, e)
        pids = [p["id"] for p in r["profiles"]]
        rows = [[it["node"], *(_cell(c, it["profiles"][p]) for p in pids)] for it in r["items"]]
        text = (
            c.t("feature.summary", n=r["total"], hidden=r["hidden_same"])
            + "\n"
            + output.table(rows, [c.t("feature.col.node"), *pids])
        )
        emit(c, r, text)

    @app.command(
        "feature-diff", help="两个 Profile 对比：默认值不同的排在前面，其次支持情况不同、未填写 / profile diff"
    )
    def cmd_feature_diff(
        ctx: typer.Context,
        a: Annotated[str, typer.Argument(help="Profile A")],
        b: Annotated[str, typer.Argument(help="Profile B")],
        domain: Annotated[str | None, typer.Option(help="只看一个功能域")] = None,
        include_same: Annotated[
            bool, typer.Option("--include-same", help="同时列出两边相同（只是写法不同）的特性")
        ] = False,
    ) -> None:
        c = output.get(ctx)
        kb, _ = _kb(c)
        try:
            r = features.diff(kb, a, b, domain, include_same)
        except features.FeatureError as e:
            _fail(c, e)
        rows = [[c.t(f"feature.kind.{x['kind']}"), x["node"], _cell(c, x["a"]), _cell(c, x["b"])] for x in r["rows"]]
        text = (
            c.t("feature.diff_summary", a=a, b=b, **r["counts"])
            + "\n"
            + output.table(rows, [c.t("feature.col.kind"), c.t("feature.col.node"), a, b])
        )
        emit(c, r, text)
