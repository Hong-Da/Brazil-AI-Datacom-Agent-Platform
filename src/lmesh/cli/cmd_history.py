"""版本历史命令：lmesh history list / diff / object / tag / restore。

快照引用：数字是设备内的序号（#3 同义），v<编号> 是配置版本编号，另有 latest、prev、tag:<标签>。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from lmesh.cli import output
from lmesh.cli.cmd_configs import require_db
from lmesh.cli.cmd_graph import _kb
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import compare, config, history, report, report_change, report_history, terms


def _fail(c: Ctx, e: history.HistoryError | compare.CompareError) -> NoReturn:
    code = output.EXIT_NOT_FOUND if e.kind == "not_found" else output.EXIT_USAGE
    fail(c, code, c.t(e.key, **e.fmt))


def _device(c: Ctx, db: str, name: str) -> int:
    dev_id = compare.device_id_by_name(db, name)
    if dev_id is None and name.isdigit():
        from lmesh.core import importer

        dev_id = next((d["id"] for d in importer.list_devices(db) if d["id"] == int(name)), None)
    if dev_id is None:
        fail(c, output.EXIT_NOT_FOUND, c.t("history.device_not_found", device=name))
    return dev_id


def _ref(ref: str | None) -> str | None:
    """CLI 中的纯数字是序号。"""
    if ref is None:
        return None
    return f"#{ref}" if ref.isdigit() else ref


def _keep() -> int:
    try:
        return int(config.load().get("history.keep"))
    except Exception:
        return history.DEFAULT_KEEP


def _cnt(v: dict[str, Any] | None) -> str:
    if not v:
        return "-"
    return f"+{v['added']} ~{v['modified'] + v['renamed']} -{v['removed']}"


def timeline_text(c: Ctx, r: dict[str, Any]) -> str:
    lines = [c.t("history.header", device=r["device"]["name"], n=r["count"], imports=r["imports"], keep=r["keep"])]
    rows = []
    for s in reversed(r["snapshots"]):
        im = s["imports"][0]
        rows.append(
            [
                f"#{s['seq']}",
                f"v{s['id']}",
                (im["imported_at"] or "")[:19].replace("T", " "),
                f"{im['source_kind']}" + (f" ×{s['import_count']}" if s["import_count"] > 1 else ""),
                str(s["lines"]),
                str(s["nodes"] if s["nodes"] is not None else "-"),
                _cnt(s["vs_previous"]),
                s["kb_version"] or "-",
                s["fingerprint"][:10],
                s["tag"] or "",
            ]
        )
    head = [
        c.t(f"history.col.{k}") for k in ("seq", "id", "time", "source", "lines", "nodes", "vs", "kb", "hash", "tag")
    ]
    lines.append(output.table(rows, head))
    return "\n".join(lines)


def diff_text(c: Ctx, r: dict[str, Any]) -> str:
    s = r["summary"]
    lines = [c.t("history.diff_header", device=r["device"]["name"], a=r["a"]["seq"], b=r["b"]["seq"])]
    if r["kb"]["differs"] and not r["kb"]["rebuilt"]:
        lines.append(c.t("history.kb_differs", a=r["kb"]["a"], b=r["kb"]["b"]))
    lines.append(
        c.t("history.summary", **{k: s[k] for k in ("added", "modified", "removed", "renamed", "noneff", "fmt")})
    )
    mark = {"added": "+", "removed": "-", "modified": "~", "renamed": "»"}
    for it in r["items"]:
        if it["kind"] == "renamed":
            lines.append(f"  » {it['object']}: {it['from']} → {it['to']}")
            continue
        lines.append(f"  {mark[it['kind']]} {it['object']}")
        for ch in it["changes"][:20]:
            va = (ch.get("a") or {}).get("value")
            vb = (ch.get("b") or {}).get("value")
            lines.append(f"      {ch['field']}: {_v(va)} → {_v(vb)}")
    for n in r.get("noneff", []):
        lines.append(f"  = {n['node']} ({c.t('history.noneff.' + n['reason'])})")
    return "\n".join(lines)


def _v(v: Any) -> str:
    return "∅" if v is None else str(v)


def register(app: typer.Typer) -> None:
    hist = typer.Typer(
        no_args_is_help=True, help="版本历史：快照时间线、差异、对象历史、标签、回到某个快照 / version history"
    )
    app.add_typer(hist, name="history")

    @hist.command("list", help="设备的快照时间线（导入记录、知识库版本、指纹、标签、相对上一快照的变化）")
    def cmd_list(ctx: typer.Context, device: Annotated[str, typer.Argument(help="设备名或编号")]) -> None:
        c = output.get(ctx)
        db = require_db(c)
        kb, _ = _kb(c)
        try:
            r = history.timeline(db, _device(c, db, device), kb, _keep())
        except history.HistoryError as e:
            _fail(c, e)
        emit(c, r, timeline_text(c, r))

    @hist.command("diff", help="两个快照之间的变化：按对象归并的图差异、只是写法不同的变化、配置原文差异")
    def cmd_diff(
        ctx: typer.Context,
        device: Annotated[str, typer.Argument(help="设备名或编号")],
        a: Annotated[str | None, typer.Option("--from", help="较早的快照（默认上一个）")] = None,
        b: Annotated[str | None, typer.Option("--to", help="较晚的快照（默认最新）")] = None,
        rebuild: Annotated[bool, typer.Option("--rebuild", help="两边都按当前知识库重新解析后比较")] = False,
        noneff: Annotated[bool, typer.Option("--show-noneff", help="同时列出只是写法不同、有效值相同的变化")] = False,
        domain: Annotated[str | None, typer.Option(help="只看一个功能域")] = None,
        no_text: Annotated[bool, typer.Option("--no-text", help="不附配置原文差异")] = False,
        report_file: Annotated[Path | None, typer.Option("--report", help="同时导出差异报告（.html 或 .md）")] = None,
        report_lang: Annotated[str | None, typer.Option("--report-lang", help="报告语言 zh-CN | en")] = None,
    ) -> None:
        c = output.get(ctx)
        db = require_db(c)
        kb, root = _kb(c)
        try:
            r = history.diff(
                db,
                _device(c, db, device),
                kb,
                _ref(a),
                _ref(b),
                rebuild,
                noneff,
                domain,
                with_text=not no_text or bool(report_file),
            )
        except (history.HistoryError, compare.CompareError) as e:
            _fail(c, e)
        if report_file:
            fmt = "md" if report_file.suffix.lower() == ".md" else "html"
            try:
                rep = report_history.history_report(
                    r, report.report_lang(report_lang or c.lang), fmt, namer=terms.namer(root, kb, "huawei")
                )
            except report.ReportError as e:
                fail(c, output.EXIT_USAGE, c.t(e.key, **e.fmt))
            report_file.parent.mkdir(parents=True, exist_ok=True)
            report_file.write_text(rep.content, encoding="utf-8")
        if no_text:
            r.pop("text", None)
        text = diff_text(c, r)
        if report_file:
            text += "\n" + c.t("report.written", path=report_file)
        emit(c, r, text)

    @hist.command("object", help="一个对象（规范编号）在每个快照中的取值与变化")
    def cmd_object(
        ctx: typer.Context,
        device: Annotated[str, typer.Argument(help="设备名或编号")],
        node: Annotated[str, typer.Argument(help="对象的规范编号，例如 interface[GigabitEthernet0/0/0]")],
        rebuild: Annotated[bool, typer.Option("--rebuild", help="按当前知识库重新解析每个快照")] = False,
    ) -> None:
        c = output.get(ctx)
        db = require_db(c)
        kb, _ = _kb(c)
        try:
            r = history.object_history(db, _device(c, db, device), node, kb, rebuild)
        except history.HistoryError as e:
            _fail(c, e)
        lines = [c.t("history.object_header", node=node, n=len(r["snapshots"]), changes=r["changes"])]
        for s in r["snapshots"]:
            if not s["present"]:
                lines.append(f"  #{s['seq']}  {c.t('history.absent')}")
                continue
            ch = ", ".join(f"{f}={_v(s['values'].get(f, {}).get('value'))}" for f in s["changed"] if f != "@presence")
            lines.append(f"  #{s['seq']}  {ch or '—'}")
        emit(c, r, "\n".join(lines))

    @hist.command("tag", help="给快照贴标签（贴了标签的快照永久保留）；--remove 去掉标签")
    def cmd_tag(
        ctx: typer.Context,
        device: Annotated[str, typer.Argument(help="设备名或编号")],
        snapshot: Annotated[str, typer.Argument(help="快照（序号、v<编号>、latest）")],
        tag: Annotated[str | None, typer.Argument(help="标签文字")] = None,
        remove: Annotated[bool, typer.Option("--remove", help="去掉标签")] = False,
    ) -> None:
        c = output.get(ctx)
        if not remove and not (tag or "").strip():
            fail(c, output.EXIT_USAGE, c.t("history.tag_required"))
        db = require_db(c)
        dev_id = _device(c, db, device)
        try:
            vid = history.resolve_snapshot(db, dev_id, _ref(snapshot))
            r = history.set_tag(db, dev_id, vid, None if remove else tag)
        except history.HistoryError as e:
            _fail(c, e)
        emit(c, r, c.t("history.tagged" if r["tag"] else "history.untagged", id=vid, tag=r["tag"] or ""))

    @hist.command("restore", help="回到某个快照：生成当前（默认最新）→ 目标快照的增量变更脚本，附回滚脚本与模拟验证")
    def cmd_restore(
        ctx: typer.Context,
        device: Annotated[str, typer.Argument(help="设备名或编号")],
        to: Annotated[str, typer.Option("--to", help="要回到的快照")],
        current: Annotated[str | None, typer.Option("--from", help="当前快照（默认最新）")] = None,
        out: Annotated[Path | None, typer.Option("-o", "--out", help="把下发脚本写到文件")] = None,
        rollback: Annotated[Path | None, typer.Option("--rollback", help="把回滚脚本写到文件")] = None,
        plain: Annotated[bool, typer.Option("--plain", help="脚本不带说明行")] = False,
        report_file: Annotated[Path | None, typer.Option("--report", help="同时导出变更报告（.html 或 .md）")] = None,
    ) -> None:
        c = output.get(ctx)
        db = require_db(c)
        kb, root = _kb(c)
        try:
            r = history.restore(db, _device(c, db, device), kb, _ref(to), _ref(current), lang=c.lang)
        except history.HistoryError as e:
            _fail(c, e)
        ch = r["change"]
        script = ch["script_plain"] if plain else ch["script"]
        msgs = [c.t("history.restore", a=r["from"]["seq"], b=r["to"]["seq"], ops=ch["summary"]["ops"])]
        if out:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(script, encoding="utf-8")
            msgs.append(c.t("change.written", path=out))
        if rollback and ch.get("rollback"):
            rollback.parent.mkdir(parents=True, exist_ok=True)
            rb = ch["rollback"]
            rollback.write_text(rb["script_plain"] if plain else rb["script"], encoding="utf-8")
            msgs.append(c.t("change.rollback_written", path=rollback))
        if report_file:
            fmt = "md" if report_file.suffix.lower() == ".md" else "html"
            rep = report_change.change_report(
                ch, report.report_lang(c.lang), fmt, namer=terms.namer(root, kb, "huawei")
            )
            report_file.parent.mkdir(parents=True, exist_ok=True)
            report_file.write_text(rep.content, encoding="utf-8")
            msgs.append(c.t("report.written", path=report_file))
        text = "\n".join(msgs) if out else script.rstrip("\n") + "\n" + "\n".join(msgs)
        emit(c, r, text)
