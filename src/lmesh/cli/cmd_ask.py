"""图查询、AI 自然语言查询与配置护栏命令：lmesh query、lmesh ask、lmesh guard、lmesh generate。

query 与 guard 不需要 AI；ask 与 generate 需要配置 AI（未配置时退出码 3）。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from lmesh.cli import output
from lmesh.cli.cmd_configs import require_db
from lmesh.cli.cmd_export import load_targets
from lmesh.cli.cmd_graph import _kb
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import ai, ask, config, gquery, guard, history, importer, template
from lmesh.core.kb import KnowledgeBase
from lmesh.core.objtable import display


def _ask_fail(c: Ctx, e: ask.AskError) -> NoReturn:
    code = {"state": output.EXIT_CONFIG, "not_found": output.EXIT_NOT_FOUND, "external": output.EXIT_EXTERNAL}.get(
        e.kind, output.EXIT_USAGE
    )
    fail(c, code, c.t(e.key, **e.fmt), e.data)


def _settings() -> config.Settings:
    return config.load()


def result_text(c: Ctx, r: dict[str, Any]) -> str:
    cols = [x["field"] for x in r["columns"]]
    rows = []
    for row in r["rows"]:
        cells = []
        for f in cols:
            cell = row["cells"][f]
            if cell.get("secret"):
                cells.append(c.t("export.configured") if cell.get("value") else c.t("export.not_configured"))
            elif cell["origin"] in ("none", "unsupported"):
                cells.append("—")
            else:
                cells.append(display(cell["value"]) + ("*" if cell["origin"] == "default" else ""))
        rows.append([str(row["n"]), row["device"], *cells])
    head = c.t("query.summary", count=r["count"], shown=len(r["rows"]))
    return head + "\n" + output.table(rows, ["#", c.t("export.col.device"), *cols])


def _template(c: Ctx, root: Path, kb: KnowledgeBase, ref: str | None) -> Any:
    if not ref:
        return None
    try:
        return template.load_any(root, ref, kb)
    except template.TemplateError as e:
        fail(
            c,
            output.EXIT_NOT_FOUND if getattr(e, "kind", "") == "not_found" else output.EXIT_USAGE,
            c.t(e.key, **e.fmt),
        )


def _base(c: Ctx, device: str | None) -> tuple[str | None, str, str | None]:
    """--device：已导入的设备名或编号，或配置文件（作为当前配置）。返回 (当前配置原文, 设备名, Profile)。"""
    if not device:
        return None, "device", None
    p = Path(device)
    if p.is_file():
        return importer.decode(p.read_bytes()), p.stem, None
    hit = history.latest_text(require_db(c), device)
    if hit is None:
        fail(c, output.EXIT_NOT_FOUND, c.t("graph.target_not_found", target=device))
    _, name, profile, text = hit
    return text, name, profile or None


def guard_text(c: Ctx, r: dict[str, Any]) -> str:
    mark = {"ok": "✓", "bad": "✕", "warn": "!", "ctx": " ", "skip": "-"}
    lines = [c.t(f"guard.verdict.{r['verdict']}", bad=r["summary"]["bad"], warn=r["summary"]["warn"])]
    for ln in r["lines"]:
        lines.append(f"{mark.get(ln['status'], ' ')} {ln['no']:>3}  {ln['text']}")
    for i in r["issues"]:
        lines.append(
            f"  [{i['status']}] {c.t('guard.line', n=i['line'] or '-')} {c.t(i['message']['key'], **i['message']['params'])}"
        )
    return "\n".join(lines)


def register(app: typer.Typer) -> None:
    @app.command("query", help="执行图查询（受限的只读查询语言，不需要 AI）：FIND 对象 ON 设备 WHERE 条件 RETURN 字段")
    def cmd_query(
        ctx: typer.Context,
        query: Annotated[
            str, typer.Argument(help='查询，例如 "FIND interface WHERE vrf = RAN RETURN name, ipv4.address"')
        ],
        targets: Annotated[
            list[str] | None, typer.Argument(help="配置文件、目录或设备名（不给时为全部已导入设备）")
        ] = None,
        profile: Annotated[str | None, typer.Option(help="配置文件使用的 Profile")] = None,
    ) -> None:
        c = output.get(ctx)
        kb, _ = _kb(c)
        devices = load_targets(c, kb, targets or [], not targets, profile)
        try:
            r = gquery.execute(query, devices, kb)
        except gquery.QueryError as e:
            fail(c, output.EXIT_USAGE, c.t(e.key, **e.fmt))
        emit(c, r, result_text(c, r))

    @app.command(
        "ask", help="AI 自然语言查询：AI 把问题写成图查询，代码执行，AI 组织回答，每句由代码核对（需要配置 AI）"
    )
    def cmd_ask(
        ctx: typer.Context,
        question: Annotated[str, typer.Argument(help="问题")],
        targets: Annotated[list[str] | None, typer.Argument(help="设备名或配置文件（不给时为全部已导入设备）")] = None,
        show_sent: Annotated[bool, typer.Option("--show-sent", help="同时打印发给 AI 的内容（已脱敏）")] = False,
    ) -> None:
        c = output.get(ctx)
        s = _settings()
        st = ask.status(s)
        if not st["configured"]:
            fail(c, output.EXIT_CONFIG, c.t("ai.not_configured"), ai.not_configured_data(s))
        kb, _ = _kb(c)
        devices = load_targets(c, kb, targets or [], not targets, None)
        try:
            r = ask.ask(question, devices, kb, s, c.lang)
        except ask.AskError as e:
            _ask_fail(c, e)
        lines = []
        if r["status"] != "answered":
            lines.append(c.t("ask.query_invalid"))
        else:
            lines.append(r["query_text"])
            lines.append(result_text(c, r["result"]))
            for stt in r["answer"]["statements"]:
                tag = c.t(f"ask.status.{stt['status']}")
                body = stt["corrected_text"] if stt["status"] == "corrected" else stt["text"]
                cites = "".join(f"[{n}]" for n in stt["cites"])
                lines.append(f"[{tag}] {body} {cites}".rstrip())
        if show_sent:
            for m in r["sent"]:
                lines += [f"--- {m['step']} ---", m["prompt"]]
        emit(c, r, "\n".join(lines))
        if r["status"] != "answered":
            sys.stderr.write(c.t("ask.query_invalid") + "\n")
            raise typer.Exit(output.EXIT_ERROR)

    @app.command(
        "guard", help="配置护栏（不需要 AI）：一段配置先解析、入图、依赖、模板、冲突检查，标出被拦截的行与原因"
    )
    def cmd_guard(
        ctx: typer.Context,
        file: Annotated[Path, typer.Argument(help="要校验的配置片段（AI 生成、手写或其他工具生成）")],
        device: Annotated[
            str | None, typer.Option("--device", help="目标设备：已导入的设备名 / 编号，或当前配置文件")
        ] = None,
        profile: Annotated[str | None, typer.Option(help="Profile（没有目标设备时必填）")] = None,
        tpl: Annotated[str | None, typer.Option("--template", help="按这个模板检查约束（模板编号或文件）")] = None,
        no_conflict_db: Annotated[bool, typer.Option("--no-cross-device", help="不与其他已导入设备查重")] = False,
        no_script: Annotated[bool, typer.Option("--no-script", help="通过后不生成增量变更脚本")] = False,
    ) -> None:
        c = output.get(ctx)
        if not file.is_file():
            fail(c, output.EXIT_NOT_FOUND, c.t("common.not_found", path=file))
        kb, root = _kb(c)
        base, name, dev_profile = _base(c, device)
        others = []
        if device and not Path(device).is_file() and not no_conflict_db:
            found, _ = history.devices_from_db(require_db(c), kb, None)
            others = [d for d in found if d.name != name]
        try:
            r = guard.guard(
                importer.decode(file.read_bytes()),
                kb,
                profile or dev_profile,
                base,
                name,
                others,
                _template(c, root, kb, tpl),
                c.lang,
                not no_script,
            )
        except guard.GuardError as e:
            fail(c, output.EXIT_USAGE, c.t(e.key, **e.fmt))
        r.pop("merged_text", None)
        emit(c, r, guard_text(c, r))
        if r["verdict"] != "passed":
            output.err_summary(c, c.t("guard.verdict.blocked", bad=r["summary"]["bad"], warn=r["summary"]["warn"]))
            raise typer.Exit(output.EXIT_ERROR)

    @app.command("generate", help="AI 生成配置（需要配置 AI）：生成后经护栏检查，被拦截时交回 AI 修改")
    def cmd_generate(
        ctx: typer.Context,
        request: Annotated[str, typer.Argument(help="用自然语言描述要做的配置")],
        device: Annotated[str, typer.Option("--device", help="目标设备：已导入的设备名 / 编号，或当前配置文件")],
        profile: Annotated[str | None, typer.Option(help="Profile（默认按目标设备）")] = None,
        tpl: Annotated[str | None, typer.Option("--template", help="按这个模板检查约束")] = None,
        rounds: Annotated[int, typer.Option(help="最多几轮（被拦截时交回 AI 修改）")] = 2,
        out: Annotated[Path | None, typer.Option("-o", "--out", help="通过校验后把配置写到文件")] = None,
    ) -> None:
        c = output.get(ctx)
        s = _settings()
        if not ask.status(s)["configured"]:
            fail(c, output.EXIT_CONFIG, c.t("ai.not_configured"), ai.not_configured_data(s))
        kb, root = _kb(c)
        base, name, dev_profile = _base(c, device)
        others = []
        if not Path(device).is_file():
            found, _ = history.devices_from_db(require_db(c), kb, None)
            others = [d for d in found if d.name != name]
        try:
            r = ask.generate(
                request, kb, s, base, name, profile or dev_profile, others, _template(c, root, kb, tpl), c.lang, rounds
            )
        except ask.AskError as e:
            _ask_fail(c, e)
        final = r["final"]["guard"]
        for rd in r["rounds"]:
            rd["guard"].pop("merged_text", None)
        text = guard_text(c, final) if final.get("lines") else c.t("guard.verdict.blocked", bad="-", warn="-")
        if out is not None and r["verdict"] == "passed":
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(r["final"]["text"] + "\n", encoding="utf-8")
            text += "\n" + c.t("export.written", path=out)
        emit(c, r, text)
        if r["verdict"] != "passed":
            sys.stderr.write(c.t("guard.verdict.blocked", bad="-", warn="-") + "\n")
            raise typer.Exit(output.EXIT_ERROR)
