"""参数化模板命令：lmesh template list|show|check|extract|draft|generate|save。

<模板> 是模板编号（knowledge/templates/ 中的）或模板文件路径；<配置> 是配置文件或已导入的设备名。
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from lmesh.cli import output
from lmesh.cli.cmd_graph import _graph_for, _kb
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import importer, template_draft, template_gen, template_match
from lmesh.core import template as tmod
from lmesh.core.kb import KnowledgeBase


def issue_text(c: Ctx, i: dict[str, Any]) -> str:
    args = {k: v for k, v in (i.get("args") or {}).items()}
    return f"{i.get('where') or '-'}: {c.t(i['key'], **args)}"


def template_fail(c: Ctx, e: tmod.TemplateError) -> NoReturn:
    if e.kind == "invalid":
        lines = [c.t("template.invalid", n=len(e.issues))] + ["  " + issue_text(c, i) for i in e.issues]
        fail(c, output.EXIT_CONFIG, "\n".join(lines), {"issues": e.issues})
    code = output.EXIT_NOT_FOUND if e.kind == "not_found" else output.EXIT_USAGE
    fail(c, code, c.t(e.key, **e.fmt))


def _load(c: Ctx, ref: str) -> tuple[tmod.Template, KnowledgeBase, Path]:
    kb, root = _kb(c)
    try:
        return tmod.load_any(root, ref, kb), kb, root
    except tmod.TemplateError as e:
        template_fail(c, e)


def _fmt(v: Any) -> str:
    if v is None:
        return "∅"
    if isinstance(v, dict | list):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def finding_text(c: Ctx, f: dict[str, Any]) -> str:
    where = f["node"] or f["actual_node"] or f["var"] or ""
    scope = f" [{f['block']}#{f['instance'] + 1}]" if f.get("block") and f.get("instance") is not None else ""
    if f.get("block") and f.get("instance") is None:
        scope = f" [{f['block']}]"
    msg = c.t(
        f"template.finding.{f['kind']}",
        expected=_fmt(f.get("expected")),
        actual=_fmt(f.get("actual")),
        var=f.get("var") or "",
        count=f.get("count") if f.get("count") is not None else "",
        problem=c.t(f["problem"]) if f.get("problem") else "",
    )
    at = []
    if f["kind"] == "missing" and f.get("parent"):
        at.append(c.t("template.under", parent=f["parent"]))
    if f.get("lines"):
        at.append(c.t("template.at_lines", lines=",".join(map(str, f["lines"][:6]))))
    if f.get("template_lines"):
        at.append(c.t("template.at_template", lines=",".join(map(str, f["template_lines"][:6]))))
    tail = f"  ({'; '.join(at)})" if at else ""
    return f"  {f['severity'][0].upper()} {where}{scope}: {msg}{tail}"


def check_text(c: Ctx, r: dict[str, Any]) -> str:
    s = r["summary"]
    lines = [c.t("template.check_header", template=r["template"]["id"], device=r["device"], profile=r["profile"])]
    lines.append(
        c.t("template.compliant") if r["compliant"] else c.t("template.not_compliant", n=s["by_severity"]["error"])
    )
    for n in r["notes"]:
        lines.append("  " + c.t(n["key"], **n["args"]))
    lines.append(c.t("template.vars_header"))
    for k, v in r["variables"].items():
        lines.append(f"  {k} = {_fmt(v)}")
    for b, v in r["blocks"].items():
        if isinstance(v, list):
            lines.append(c.t("template.block_instances", block=b, n=len(v)))
            for i, inst in enumerate(v):
                vals = ", ".join(f"{k}={_fmt(x)}" for k, x in inst.items() if not k.startswith("_"))
                lines.append(f"  #{i + 1} {vals}")
        else:
            lines.append(f"  {b} = {_fmt(v)}")
    if r["findings"]:
        lines.append(c.t("template.findings_header", n=len(r["findings"])))
        lines += [finding_text(c, f) for f in r["findings"]]
    return "\n".join(lines)


def _graph(c: Ctx, target: str, profile: str | None):  # type: ignore[no-untyped-def]
    g, _ = _graph_for(c, target, profile)
    return g


def rows_csv(t: tmod.Template, rows: list[dict[str, Any]]) -> str:
    """参数行 → CSV（与 generate 的输入格式相同：块变量“块名.变量”，重复块的取值用分号连接）。"""
    cols = ["device"] + [v.name for v in t.input_vars(None)]
    for b in t.blocks.values():
        if b.kind == "optional":
            cols.append(b.name)
        cols += [v.name for v in t.input_vars(b.name)]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for r in rows:
        out = []
        for col in cols:
            if "." in col:
                bname, k = col.split(".", 1)
                val = r.get(bname)
                if isinstance(val, list):
                    out.append(";".join("" if x.get(k) is None else str(x.get(k)) for x in val))
                elif isinstance(val, dict):
                    out.append("" if val.get(k) is None else str(val.get(k)))
                else:
                    out.append("")
            elif col in t.blocks:
                out.append("true" if r.get(col) else "false")
            else:
                out.append("" if r.get(col) is None else str(r.get(col)))
        w.writerow(out)
    return buf.getvalue()


def register(app: typer.Typer) -> None:
    tapp = typer.Typer(no_args_is_help=True, help="参数化配置模板 / parameterized configuration templates")
    app.add_typer(tapp, name="template")

    @tapp.command("list", help="列出模板 / list templates")
    def t_list(ctx: typer.Context) -> None:
        c = output.get(ctx)
        kb, root = _kb(c)
        items = tmod.list_templates(root, kb)
        rows = [
            [
                i["id"],
                (i.get("title") or {}).get(c.lang, (i.get("title") or {}).get("en", "")) if i["valid"] else "✗",
                i.get("profile", "") or "",
                str(i.get("vars", "")),
                str(i.get("blocks", "")),
            ]
            for i in items
        ]
        emit(c, {"templates": items}, output.table(rows, c.t("template.list_header").split("|")))

    @tapp.command("show", help="显示模板：变量、块、正文 / show a template")
    def t_show(ctx: typer.Context, template: Annotated[str, typer.Argument(help="模板编号或模板文件")]) -> None:
        c = output.get(ctx)
        t, kb, _ = _load(c, template)
        info = t.info(kb) | {"body": t.body}
        lines = [f"{t.id}  {t.title.get(c.lang, '')}  ({t.profile})"]
        for v in t.vars.values():
            extra = f" = {v.expr}" if v.expr else ""
            lines.append(f"  {v.name}: {v.type}{extra}")
        lines += ["", t.body]
        emit(c, info, "\n".join(lines))

    @tapp.command("check", help="按模板校验配置并提取变量 / check a configuration against a template")
    def t_check(
        ctx: typer.Context,
        template: Annotated[str, typer.Argument(help="模板编号或模板文件")],
        target: Annotated[str, typer.Argument(help="配置文件，或已导入的设备名")],
        profile: Annotated[str | None, typer.Option(help="配置使用的 Profile（默认自动识别）")] = None,
        extra: Annotated[str | None, typer.Option(help="模板外的配置：allow 只列出 / deny 算不符合")] = None,
        extra_scope: Annotated[
            str | None, typer.Option("--extra-scope", help="模板外配置的范围：none / matched / domains")
        ] = None,
    ) -> None:
        c = output.get(ctx)
        t, kb, _ = _load(c, template)
        g = _graph(c, target, profile)
        try:
            r = template_match.check(
                t, g, kb, Path(target).stem if Path(target).exists() else target, extra, extra_scope
            )
        except tmod.TemplateError as e:
            template_fail(c, e)
        emit(c, r, check_text(c, r))
        if not r["compliant"]:  # 退出码 1，摘要同时写 stderr
            typer.echo(c.t("template.not_compliant", n=r["summary"]["by_severity"]["error"]), err=True)
            raise typer.Exit(output.EXIT_ERROR)

    @tapp.command("extract", help="按模板提取变量（可直接作为 generate 的参数表）/ extract variables")
    def t_extract(
        ctx: typer.Context,
        template: Annotated[str, typer.Argument(help="模板编号或模板文件")],
        targets: Annotated[list[str], typer.Argument(help="配置文件或已导入的设备名（可多个）")],
        fmt: Annotated[str, typer.Option("--format", help="参数表格式：json / csv")] = "json",
        out: Annotated[Path | None, typer.Option("-o", "--out", help="把参数表写到文件")] = None,
        profile: Annotated[str | None, typer.Option(help="配置使用的 Profile")] = None,
    ) -> None:
        c = output.get(ctx)
        if fmt not in ("json", "csv"):
            fail(c, output.EXIT_USAGE, c.t("template.params_format", format=fmt))
        t, kb, _ = _load(c, template)
        results = []
        for target in targets:
            g = _graph(c, target, profile)
            label = Path(target).stem if Path(target).exists() else target
            results.append(template_match.extract_view(template_match.check(t, g, kb, label)))
        rows = [r["row"] for r in results]
        content = rows_csv(t, rows) if fmt == "csv" else json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
        if out:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(content, encoding="utf-8", newline="\n")
        lines = []
        for r in results:
            state = c.t("template.compliant") if r["compliant"] else c.t("template.not_compliant", n=len(r["findings"]))
            lines.append(f"{r['device']}: {state}")
        lines.append(c.t("template.params_written", path=out) if out else content.rstrip("\n"))
        emit(c, {"results": results, "rows": rows, "format": fmt, "file": str(out) if out else None}, "\n".join(lines))

    @tapp.command("draft", help="从同角色设备的配置生成模板草稿 / draft a template from configurations")
    def t_draft(
        ctx: typer.Context,
        configs: Annotated[list[Path], typer.Argument(help="配置文件（一份或几份同角色设备的配置，第一份为基准）")],
        template_id: Annotated[str, typer.Option("--id", help="模板编号")] = "draft",
        out: Annotated[Path | None, typer.Option("-o", "--out", help="把模板草稿写到文件")] = None,
        params_out: Annotated[
            Path | None, typer.Option("--params-out", help="把参数表（每份配置一行，CSV）写到文件")
        ] = None,
        profile: Annotated[str | None, typer.Option(help="配置使用的 Profile")] = None,
    ) -> None:
        c = output.get(ctx)
        kb, _ = _kb(c)
        missing = [str(p) for p in configs if not p.is_file()]
        if missing:
            fail(c, output.EXIT_NOT_FOUND, c.t("common.not_found", path=", ".join(missing)))
        texts = [(p.stem, importer.decode(p.read_bytes())) for p in configs]
        try:
            d = template_draft.draft(texts, kb, profile, template_id)
        except tmod.TemplateError as e:
            template_fail(c, e)
        if out:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(d["source"], encoding="utf-8", newline="\n")
        if params_out and d["valid"]:
            t = tmod.parse(d["source"], kb)
            params_out.parent.mkdir(parents=True, exist_ok=True)
            params_out.write_text(rows_csv(t, d["params"]), encoding="utf-8", newline="\n")
        lines = [c.t("template.draft_header", n=len(d["vars"]), configs=len(d["configs"]))]
        for v in d["vars"]:
            lines.append(f"  {v['name']}: {v['type']}  {' | '.join(v['values'][:4])}")
        for o in d["optional_candidates"]:
            lines.append("  " + c.t("template.draft_optional", node=o["node"], devices=", ".join(o["missing_in"])))
        for rp in d["repeat_candidates"]:
            lines.append("  " + c.t("template.draft_repeat", schema=rp["schema"], n=rp["count"]))
        for v in d["verify"]:
            ok = v["compliant"] and not v["mismatched"]
            lines.append(
                "  " + c.t("template.draft_verify_ok" if ok else "template.draft_verify_bad", device=v["device"])
            )
        if not d["valid"]:
            lines.append(c.t("template.invalid", n=len(d["issues"])))
            lines += ["  " + issue_text(c, i) for i in d["issues"]]
        lines.append(c.t("template.draft_written", path=out) if out else d["source"].rstrip("\n"))
        emit(c, d, "\n".join(lines))

    @tapp.command("generate", help="模板 + 参数表批量生成配置并验证 / generate configurations")
    def t_generate(
        ctx: typer.Context,
        template: Annotated[str, typer.Argument(help="模板编号或模板文件")],
        params: Annotated[Path, typer.Argument(help="参数表：CSV 或 JSON")],
        fmt: Annotated[str | None, typer.Option("--format", help="参数表格式：csv / json（默认按内容判断）")] = None,
        out_dir: Annotated[
            Path | None, typer.Option("--out-dir", help="把生成的配置写到这个目录（每行一个文件）")
        ] = None,
        engine: Annotated[str, typer.Option(help="生成方式：text（正文替换）/ canon（规范渲染器）")] = "text",
        target_profile: Annotated[
            str | None, typer.Option("--target-profile", help="生成到另一个 Profile（需要 --engine canon）")
        ] = None,
        verify: Annotated[bool, typer.Option("--verify/--no-verify", help="生成后解析、往返、按模板校验")] = True,
        rules: Annotated[
            str | None, typer.Option("--rules", help="翻译规则集（编号或 YAML 文件），需要 --engine canon")
        ] = None,
    ) -> None:
        from lmesh.cli.cmd_naming import load_rules

        c = output.get(ctx)
        t, kb, _ = _load(c, template)
        rs = load_rules(c, rules, kb)
        if not params.is_file():
            fail(c, output.EXIT_NOT_FOUND, c.t("common.not_found", path=params))
        try:
            rows = template_gen.parse_params(importer.decode(params.read_bytes()), fmt)
            r = template_gen.generate(t, rows, kb, engine, target_profile, verify, rs)
        except tmod.TemplateError as e:
            template_fail(c, e)
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
            for row in r["rows"]:
                if row["ok"] and row["text"]:
                    (out_dir / row["file"]).write_text(row["text"], encoding="utf-8", newline="\n")
        s = r["summary"]
        lines = [c.t("template.gen_summary", total=s["total"], ok=s["ok"], failed=s["failed"])]
        for row in r["rows"]:
            mark = "✓" if row["ok"] else "✗"
            lines.append(f"  {mark} {row['device']}  {row['file']}")
            for err in row["errors"]:
                detail = c.t(err["problem"], **{k: v for k, v in err.items() if k not in ("problem", "stage")})
                where = (
                    f"{err['var']}" + (f"#{err['instance'] + 1}" if err.get("instance") is not None else "")
                    if err.get("var")
                    else err["stage"]
                )
                lines.append(f"      {where}: {detail}")
        if out_dir:
            lines.append(c.t("template.gen_written", path=out_dir, n=s["ok"]))
        data = r if out_dir is None else {**r, "out_dir": str(out_dir)}
        emit(c, data, "\n".join(lines))
        if s["failed"]:
            typer.echo(lines[0], err=True)
            raise typer.Exit(output.EXIT_ERROR)

    @tapp.command("save", help="校验并保存模板到运行时知识库 / save a template into the knowledge base")
    def t_save(ctx: typer.Context, file: Annotated[Path, typer.Argument(help="模板文件（YAML）")]) -> None:
        c = output.get(ctx)
        kb, root = _kb(c)
        if not file.is_file():
            fail(c, output.EXIT_NOT_FOUND, c.t("common.not_found", path=file))
        source = file.read_text(encoding="utf-8")
        try:
            t = tmod.parse(source, kb, file.name)
            saved = tmod.save(root, t.id, source, kb)
        except tmod.TemplateError as e:
            template_fail(c, e)
        emit(c, saved.info(kb), c.t("template.saved", id=saved.id, file=saved.file))
