"""变更与割接组的 AI 结果命令（M8-4，REQ-041）：lmesh ai change-plan、lmesh ai cutover-doc。

建议的运行、采纳与撤销用 lmesh ai suggest（run intent-script / cutover-plan / translate-gap / naming-map /
template-extract，参数用 --params）；这里查看由代码在采纳结果上计算的内容。与 API 共用 core/ai_suggest_change。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from lmesh.cli import output
from lmesh.cli.cmd_ai_suggest import _env, _fail, _reason_text
from lmesh.cli.output import emit
from lmesh.core import ai_suggest, ai_suggest_change

_KIND = {"ai": "+", "code": "*", "frame": " "}


def _plan_text(c: output.Ctx, p: dict[str, Any]) -> str:
    if not p.get("adopted"):
        return c.t("ai_change.no_adopted", id=p["batch_id"])
    lines = [
        c.t(
            "ai_change.plan_head",
            id=p["batch_id"],
            n=len(p["adopted"]),
            ops=(p.get("summary") or {}).get("ops", 0),
            risk=(p.get("risk") or {}).get("level", "-"),
            verify="ok" if p.get("verify") and p.get("rollback_verify") else "fail",
        )
    ]
    lines += [f"{_KIND.get(r['k'], ' ')} {r['text']}" for r in p.get("rows") or []]
    lines += [f"  {_reason_text(c, r)}" for r in p.get("reasons") or []]
    return "\n".join(lines)


def register(ai_app: typer.Typer) -> None:
    @ai_app.command(
        "change-plan",
        help="变更意图转脚本：已采纳的改动合并后由代码生成的脚本（+ 来自 AI 改动，* 代码补发）/ merged change of adopted edits",
    )
    def change_plan(ctx: typer.Context, batch: Annotated[int, typer.Argument(help="intent-script 的运行编号")]) -> None:
        c = output.get(ctx)
        try:
            p = ai_suggest_change.intent_plan(_env(c), batch)
        except ai_suggest.SuggestError as e:
            _fail(c, e)
        emit(c, p, _plan_text(c, p))

    @ai_app.command(
        "cutover-doc",
        help="割接方案文档（Markdown，只含已采纳的 AI 文字，命令来自代码生成的步骤）/ export the cutover plan",
    )
    def cutover_doc(
        ctx: typer.Context,
        batch: Annotated[int, typer.Argument(help="cutover-plan 的运行编号")],
        lang: Annotated[str, typer.Option("--lang", help="zh-CN 或 en（中英双语分别导出）")] = "zh-CN",
        out: Annotated[Path | None, typer.Option("--out", help="写入文件；不给时打印")] = None,
    ) -> None:
        c = output.get(ctx)
        if lang not in ("zh-CN", "en"):
            output.fail(c, output.EXIT_USAGE, c.t("ai_change.bad_lang", lang=lang))
        try:
            r = ai_suggest_change.plan_doc(_env(c), batch, lang, adopted_only=True)
        except ai_suggest.SuggestError as e:
            _fail(c, e)
        if out is not None:
            out.write_text(r["markdown"], encoding="utf-8", newline="\n")
            emit(c, {"file": str(out), "doc": r["doc"]}, c.t("ai_change.written", path=str(out)))
        else:
            emit(c, {"markdown": r["markdown"], "doc": r["doc"]}, r["markdown"].rstrip("\n"))
