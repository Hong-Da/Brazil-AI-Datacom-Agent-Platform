"""配置检查项目的命令（REQ-031）：
lmesh script-check <脚本> --device <设备|配置文件> [--version N] [--kind change|full] [--order/--no-order] [--reorder [-o 文件]]；
lmesh script-diff <a> <b> [--ignore-order] [--device <设备|配置文件>] [--kind change|full] [--format text|unified|html] [-o 文件]。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from lmesh.cli import output
from lmesh.cli.cmd_configs import require_db
from lmesh.cli.cmd_graph import _kb
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import compare, importer, script_check, terms, textdiff
from lmesh.core.kb import KnowledgeBase

_SHOW = 80


def _read(c: Ctx, path: Path) -> str:
    if not path.is_file():
        fail(c, output.EXIT_NOT_FOUND, c.t("common.not_found", path=path))
    return importer.decode(path.read_bytes())


def _baseline(
    c: Ctx, kb: KnowledgeBase, device: str | None, version: int | None, profile: str | None
) -> script_check.Baseline | None:
    if not device:
        return None
    p = Path(device)
    try:
        if p.is_file():
            return script_check.baseline_from_text(_read(c, p), kb, profile, p.stem)
        db = require_db(c)
        name = device
        if "@" in device and version is None:
            head, _, tail = device.rpartition("@")
            if tail.isdigit():
                name, version = head, int(tail)
        dev_id = compare.device_id_by_name(db, name)
        if dev_id is None:
            fail(c, output.EXIT_NOT_FOUND, c.t("script_check.device_not_found", device=name))
        return script_check.baseline_from_db(db, kb, dev_id, version, profile)
    except script_check.ScriptCheckError as e:
        _fail(c, e)


def _fail(c: Ctx, e: script_check.ScriptCheckError) -> NoReturn:
    code = output.EXIT_NOT_FOUND if e.kind == "not_found" else output.EXIT_USAGE
    fail(c, code, c.t(e.key, **e.fmt))


def text_report(c: Ctx, r: dict[str, Any]) -> str:
    s = r["summary"]
    base = r.get("baseline") or {}
    lines = [
        c.t(
            "script_check.cli.header",
            kind=c.t(f"script_check.kind.{r['kind']}"),
            baseline=base.get("label") or "-",
            errors=s["errors"],
            warnings=s["warnings"],
            infos=s["infos"],
            ms=r["ms"],
        )
    ]
    if r["order"]["applicable"]:
        lines.append(
            c.t("script_check.cli.order_on", n=r["order"]["violations"])
            if r["order"]["enabled"]
            else c.t("script_check.cli.order_off")
        )
    if not r["issues"]:
        lines.append(c.t("script_check.cli.none"))
    for it in r["issues"][:_SHOW]:
        where = f"{c.t('script_check.cli.line')} {it['line']}" if it["line"] else "-"
        src = " [AI]" if it.get("source") == "ai" else ""
        lines.append(f"  [{c.t('check.severity.' + it['severity'])}] {where} {it['category']}{src}: {it['text']}")
    if len(r["issues"]) > _SHOW:
        lines.append("  … " + c.t("script_check.cli.more", n=len(r["issues"]) - _SHOW))
    res = r["result"]
    if r["kind"] == "change":
        lines.append(
            c.t(
                "script_check.cli.result",
                added=res["lines_added"],
                removed=res["lines_removed"],
                overridden=res["lines_overridden"],
                side=res["side_effect_removed"],
                new=len(res["findings_new"]),
                fixed=len(res["findings_fixed"]),
            )
        )
    elif res.get("compare"):
        lines.append(c.t("script_check.cli.compare", total=res["compare"]["summary"]["total"]))
    return "\n".join(lines)


def register(app: typer.Typer) -> None:
    @app.command(
        "script-check",
        help="检查变更脚本 / 完整配置：在基线上模拟执行、顺序核查、配置检查规则；有 error 时退出码 1 / check a script",
    )
    def cmd_script_check(
        ctx: typer.Context,
        script: Annotated[Path, typer.Argument(help="脚本文件")],
        device: Annotated[
            str | None, typer.Option("--device", help="基线：已导入的设备名（可写 名称@版本），或配置文件")
        ] = None,
        version: Annotated[int | None, typer.Option("--version", help="基线设备的配置版本编号（默认最新）")] = None,
        kind: Annotated[str, typer.Option("--kind", help="change（变更脚本）| full（完整配置）")] = "change",
        order: Annotated[bool, typer.Option("--order/--no-order", help="顺序核查（默认开启）")] = True,
        do_reorder: Annotated[bool, typer.Option("--reorder", help="按依赖重排，输出重排后的脚本与移动原因")] = False,
        out: Annotated[Path | None, typer.Option("-o", "--out", help="--reorder 时把重排后的脚本写到文件")] = None,
        profile: Annotated[str | None, typer.Option()] = None,
        rules: Annotated[Path | None, typer.Option("--rules", help="规则目录（默认知识库的 rules/）")] = None,
    ) -> None:
        c = output.get(ctx)
        if kind not in script_check.KINDS:
            fail(c, output.EXIT_USAGE, c.t("script_check.bad_kind", allowed=", ".join(script_check.KINDS)))
        text = _read(c, script)
        kb, root = _kb(c)
        base = _baseline(c, kb, device, version, profile)
        namer = terms.namer(root, kb, "huawei" if base is None or base.family.startswith("huawei") else "cisco")
        if do_reorder:
            if base is None or kind != "change":
                fail(c, output.EXIT_USAGE, c.t("script_check.need_baseline"))
            try:
                r = script_check.reorder_text(text, kb, base, namer=namer, lang=c.lang, rules_dir=rules)
            except script_check.ScriptCheckError as e:
                _fail(c, e)
            if out is not None:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(r["script"], encoding="utf-8", newline="\n")
                r["written"] = str(out)
            lines = [
                c.t(
                    "script_check.cli.reorder",
                    moves=len(r["moves"]),
                    before=r["before"]["order_violations"],
                    after=r["after"]["order_violations"],
                )
            ]
            for m in r["moves"]:
                lines.append(f"  {m['line']} → {m['new_line']}  {m['text']}")
                for why in m["reasons"]:
                    lines.append(f"      {why['text']}")
            lines.append(c.t("script_check.cli.written", path=out) if out else r["script"].rstrip("\n"))
            emit(c, r, "\n".join(lines))
            return
        try:
            r = script_check.check_text(
                text, kb, base, kind, order, profile=profile, rules_dir=rules, namer=namer, lang=c.lang
            )
        except script_check.ScriptCheckError as e:
            _fail(c, e)
        res = script_check.public(r)
        emit(c, res, text_report(c, res))
        if res["summary"]["errors"]:
            output.err_summary(c, text_report(c, res).split("\n")[0])
            raise typer.Exit(output.EXIT_ERROR)

    @app.command(
        "script-diff",
        help="脚本 / 配置的文本差异：移动识别、行内字符标记、忽略顺序、语义差异；可输出统一 diff 或 HTML 报告 / diff two scripts",
    )
    def cmd_script_diff(
        ctx: typer.Context,
        a: Annotated[Path, typer.Argument(help="A（旧）")],
        b: Annotated[Path, typer.Argument(help="B（新）")],
        ignore_order: Annotated[bool, typer.Option("--ignore-order", help="忽略顺序，只看内容差异")] = False,
        device: Annotated[
            str | None, typer.Option("--device", help="基线（语义差异：变更脚本在基线上执行后比较）")
        ] = None,
        kind: Annotated[str, typer.Option("--kind", help="两侧的类型：full（完整配置）| change（变更脚本）")] = "full",
        fmt: Annotated[str, typer.Option("--format", help="text | unified | html")] = "text",
        report_lang: Annotated[str, typer.Option("--report-lang", help="html 报告语言：zh-CN | en")] = "zh-CN",
        out: Annotated[Path | None, typer.Option("-o", "--out", help="把 unified / html 写到文件")] = None,
        semantic: Annotated[bool, typer.Option("--semantic/--no-semantic", help="同时给出语义差异")] = True,
        profile: Annotated[str | None, typer.Option()] = None,
    ) -> None:
        c = output.get(ctx)
        if (
            fmt not in ("text", "unified", "html")
            or kind not in script_check.KINDS
            or report_lang not in ("zh-CN", "en")
        ):
            fail(c, output.EXIT_USAGE, c.t("script_check.cli.bad_diff_args"))
        ta, tb = _read(c, a), _read(c, b)
        r = textdiff.diff(ta, tb, ignore_order)
        r["unified"] = textdiff.unified(ta, tb, str(a), str(b))
        r["a"], r["b"] = {"label": str(a), "kind": kind}, {"label": str(b), "kind": kind}
        r["semantic"] = None
        if semantic:
            kb, _ = _kb(c)
            base = _baseline(c, kb, device, None, profile)
            try:
                from lmesh.core import checkproj

                ga = checkproj._graph_of(kb, ta, kind, base, profile)
                gb = checkproj._graph_of(kb, tb, kind, base, profile)
            except Exception as e:  # 解析失败时只给文本差异
                r["semantic_error"] = getattr(e, "key", type(e).__name__)
                ga = gb = None
            if ga is not None and gb is not None:
                cr = compare.compare(compare.Side(ga, str(a)), compare.Side(gb, str(b)), kb)
                r["semantic"] = {
                    "equal": cr["equal"],
                    "summary": cr["summary"],
                    "diffs": [
                        {"kind": d["kind"], "node": d["node"], "label": d["node"], "a": d.get("a"), "b": d.get("b")}
                        for d in cr["diffs"][:300]
                    ],
                }
        st = r["stats"]
        if fmt in ("unified", "html"):
            rep = textdiff.report(r, str(a), str(b), report_lang, fmt, r.get("semantic"))
            if out is not None:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(rep.content, encoding="utf-8", newline="\n")
                emit(c, {"written": str(out), "stats": st}, c.t("script_check.cli.written", path=out))
            else:
                emit(c, {"content": rep.content, "stats": st}, rep.content)
            return
        lines = [c.t("script_check.cli.diff", **{k: st[k] for k in ("add", "del", "change", "move", "equal")})]
        for row in r["rows"]:
            if row["t"] == "equal":
                continue
            mark = {"add": "+", "del": "-", "change": "~", "move_from": "<", "move_to": ">"}[row["t"]]
            if row["t"] == "change":
                lines.append(f"~ {row['a']}→{row['b']}  {row['at']}  ⇒  {row['bt']}")
            elif row["t"] == "move_from":
                lines.append(f"{mark} {row['a']}→{row['to']}  {row['at']}")
            elif row["t"] in ("del",):
                lines.append(f"{mark} {row['a']}  {row['at']}")
            elif row["t"] == "add":
                lines.append(f"{mark} {row['b']}  {row['bt']}")
        if r.get("semantic") is not None:
            sem = r["semantic"]
            lines.append(
                c.t("script_check.cli.semantic_equal")
                if sem["equal"]
                else c.t("script_check.cli.semantic", total=sem["summary"]["total"])
            )
        emit(c, r, "\n".join(lines))
