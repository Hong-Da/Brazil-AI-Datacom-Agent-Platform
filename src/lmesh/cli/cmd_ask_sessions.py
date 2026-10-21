"""AI 查询会话命令（REQ-052～054）：lmesh ask-session list / new / show / ask / reask / update / delete /
attach / detach / report / table / ai-report。与 API 共用 core/ask_sessions、core/ask_report。
会话属于当前项目（--project / --network 选择），命令行没有账号时会话归“cli”。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from lmesh.cli import output
from lmesh.cli.cmd_ask import _ask_fail, _settings
from lmesh.cli.cmd_configs import require_db
from lmesh.cli.cmd_graph import _kb
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import ai, ask, ask_report, ask_sessions, report

_EXIT = {
    "not_found": output.EXIT_NOT_FOUND,
    "state": output.EXIT_ERROR,
    "forbidden": output.EXIT_ERROR,
    "param": output.EXIT_USAGE,
}


def _fail(c: Ctx, e: ask_sessions.SessionError) -> NoReturn:
    fail(c, _EXIT.get(e.kind, output.EXIT_ERROR), c.t(e.key, **e.fmt), getattr(e, "data", None))


def _brief_line(s: dict[str, Any]) -> str:
    flags = " ".join(x for x, on in (("[shared]", s["shared"]), ("[archived]", s["archived"])) if on)
    who = "" if s["mine"] else f" ({s['owner']})"
    return f"#{s['id']}  {s['title'] or '-'}{who}  turns={s['turns']} attachments={s['attachments']} {flags}".rstrip()


def _turn_text(c: Ctx, i: int, turn: dict[str, Any]) -> list[str]:
    v = ask_report.current_version(turn)
    res = v.get("result") or {}
    n = len(turn.get("versions") or [])
    head = f"[{i}] {v.get('question', '')}" + (f"  (v{int(turn.get('current') or 0) + 1}/{n})" if n > 1 else "")
    lines = [head]
    if res.get("query_text"):
        lines.append("    " + str(res["query_text"]).replace("\n", " "))
    for st in (res.get("answer") or {}).get("statements") or []:
        tag = c.t(f"ask.status.{st.get('status')}")
        body = st.get("corrected_text") if st.get("status") == "corrected" else st.get("text")
        lines.append(f"    [{tag}] {body}")
    return lines


def _write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8", newline="\n")


def _ai_ready(c: Ctx) -> Any:
    s = _settings()
    if not ask.status(s)["configured"]:
        fail(c, output.EXIT_CONFIG, c.t("ai.not_configured"), ai.not_configured_data(s))
    return s


def register(app: typer.Typer) -> None:
    sa = typer.Typer(no_args_is_help=True, help="AI 查询会话：保存、追问、附件、下载 / AI query sessions")
    app.add_typer(sa, name="ask-session")

    @sa.command("list", help="我的会话（--archived 已归档，--shared 别人分享给我的）")
    def s_list(
        ctx: typer.Context,
        archived: Annotated[bool, typer.Option("--archived", help="已归档的会话")] = False,
        shared: Annotated[bool, typer.Option("--shared", help="别人分享给我的会话")] = False,
        search: Annotated[str, typer.Option("--search", help="按标题搜索")] = "",
    ) -> None:
        c = output.get(ctx)
        db = require_db(c)
        which = "shared" if shared else "archived" if archived else "active"
        try:
            rows = ask_sessions.list_sessions(db, which, search)
        except ask_sessions.SessionError as e:
            _fail(c, e)
        emit(c, {"sessions": rows}, "\n".join(_brief_line(s) for s in rows) or c.t("ask_session.none"))

    @sa.command("new", help="新建会话（范围默认为当前网络全部可查询设备）")
    def s_new(
        ctx: typer.Context,
        title: Annotated[str, typer.Option("--title", help="标题；不填时用第一个问题")] = "",
        device: Annotated[list[str] | None, typer.Option("--device", help="范围中的设备（可多次）")] = None,
    ) -> None:
        c = output.get(ctx)
        try:
            s = ask_sessions.create(require_db(c), title, list(device) if device else None)
        except ask_sessions.SessionError as e:
            _fail(c, e)
        emit(c, s, _brief_line(s))

    @sa.command("show", help="显示会话：各轮的问题、图查询与回答（当前版本），附件")
    def s_show(ctx: typer.Context, session: Annotated[int, typer.Argument(help="会话编号")]) -> None:
        c = output.get(ctx)
        try:
            d = ask_sessions.get(require_db(c), session)
        except ask_sessions.SessionError as e:
            _fail(c, e)
        lines = [_brief_line(d)]
        lines += [f"  + {a['name']} ({a['kind']})" for a in d["attachment_list"]]
        for i, t in enumerate(d["turn_list"], 1):
            lines += _turn_text(c, i, t)
        emit(c, d, "\n".join(lines))

    def _ask(c: Ctx, session: int, question: str, confirm: bool, turn_no: int | None) -> None:
        s = _ai_ready(c)
        db = require_db(c)
        kb, _ = _kb(c)
        try:
            tid = before = None
            if turn_no is not None:
                turns = ask_sessions.get(db, session)["turn_list"]
                if not 1 <= turn_no <= len(turns):
                    raise ask_sessions.SessionError("ask_session.turn_not_found", "not_found", id=turn_no)
                tid = turns[turn_no - 1]["id"]
                before = ask_sessions.turn_position(db, session, tid)
            res, ctxn, atts = ask_sessions.run(db, session, question, kb, s, c.lang, None, confirm, before)
            if tid is None:
                t = ask_sessions.add_turn(db, session, question, res, ctxn, atts)
            else:
                t = ask_sessions.add_version(db, session, tid, question, res, ctxn, atts)
        except ask_sessions.SessionError as e:
            _fail(c, e)
        except ask.AskError as e:
            _ask_fail(c, e)
        emit(c, t, "\n".join(_turn_text(c, turn_no or t["position"], t)))

    @sa.command("ask", help="在会话里提问 / 追问（带前几轮上下文与附件；需要配置 AI）")
    def s_ask(
        ctx: typer.Context,
        session: Annotated[int, typer.Argument(help="会话编号")],
        question: Annotated[str, typer.Argument(help="问题")],
        confirm_images: Annotated[bool, typer.Option("--confirm-images", help="确认图片附件不经脱敏发给 AI")] = False,
    ) -> None:
        _ask(output.get(ctx), session, question, confirm_images, None)

    @sa.command("reask", help="改第 N 轮的问题重新回答（旧回答保留为历史版本）")
    def s_reask(
        ctx: typer.Context,
        session: Annotated[int, typer.Argument(help="会话编号")],
        turn: Annotated[int, typer.Argument(help="第几轮（从 1 开始）")],
        question: Annotated[str, typer.Argument(help="新的问题")],
        confirm_images: Annotated[bool, typer.Option("--confirm-images", help="确认图片附件不经脱敏发给 AI")] = False,
    ) -> None:
        _ask(output.get(ctx), session, question, confirm_images, turn)

    @sa.command("update", help="重命名、归档 / 恢复、分享 / 取消分享")
    def s_update(
        ctx: typer.Context,
        session: Annotated[int, typer.Argument(help="会话编号")],
        title: Annotated[str | None, typer.Option("--title", help="新标题")] = None,
        archive: Annotated[bool | None, typer.Option("--archive/--restore", help="归档 / 恢复到进行中")] = None,
        share: Annotated[
            bool | None, typer.Option("--share/--unshare", help="分享给项目成员只读查看 / 取消分享")
        ] = None,
    ) -> None:
        c = output.get(ctx)
        try:
            s = ask_sessions.update(require_db(c), session, {"title": title, "archived": archive, "shared": share})
        except ask_sessions.SessionError as e:
            _fail(c, e)
        emit(c, s, _brief_line(s))

    @sa.command("delete", help="删除会话（连同各轮与附件）")
    def s_delete(ctx: typer.Context, session: Annotated[int, typer.Argument(help="会话编号")]) -> None:
        c = output.get(ctx)
        try:
            ask_sessions.delete(require_db(c), session)
        except ask_sessions.SessionError as e:
            _fail(c, e)
        emit(c, {"deleted": session}, c.t("ask_session.deleted", id=session))

    @sa.command(
        "attach", help="添加附件：配置文件（临时设备）、文档 txt/md/csv/pdf/docx/xlsx、zip；图片需要 ai.ask_images"
    )
    def s_attach(
        ctx: typer.Context,
        session: Annotated[int, typer.Argument(help="会话编号")],
        files: Annotated[list[Path], typer.Argument(help="文件")],
    ) -> None:
        c = output.get(ctx)
        data = []
        for f in files:
            if not f.is_file():
                fail(c, output.EXIT_NOT_FOUND, c.t("common.not_found", path=f))
            data.append((f.name, f.read_bytes()))
        kb, _ = _kb(c)
        try:
            added = ask_sessions.add_attachments(
                require_db(c), session, data, bool(_settings().get("ai.ask_images")), kb
            )
        except ask_sessions.SessionError as e:
            _fail(c, e)
        emit(c, {"attachments": added}, "\n".join(f"#{a['id']}  {a['name']} ({a['kind']})" for a in added))

    @sa.command("detach", help="删除附件")
    def s_detach(
        ctx: typer.Context,
        session: Annotated[int, typer.Argument(help="会话编号")],
        attachment: Annotated[int, typer.Argument(help="附件编号")],
    ) -> None:
        c = output.get(ctx)
        try:
            ask_sessions.delete_attachment(require_db(c), session, attachment)
        except ask_sessions.SessionError as e:
            _fail(c, e)
        emit(c, {"deleted": attachment}, c.t("ask_session.detached", id=attachment))

    @sa.command("report", help="导出会话报告（HTML 可打印为 PDF / Markdown；中文 / English）")
    def s_report(
        ctx: typer.Context,
        session: Annotated[int, typer.Argument(help="会话编号")],
        out: Annotated[Path, typer.Option("-o", "--out", help="输出文件")],
        lang: Annotated[str | None, typer.Option("--lang", help="zh-CN / en（默认按界面语言）")] = None,
        fmt: Annotated[str, typer.Option("--format", help="html / md")] = "html",
    ) -> None:
        c = output.get(ctx)
        if fmt not in ("html", "md"):
            fail(c, output.EXIT_USAGE, c.t("report.bad_format", allowed="html, md"))
        try:
            d = ask_sessions.get(require_db(c), session)
        except ask_sessions.SessionError as e:
            _fail(c, e)
        rep = ask_report.session_report(d, report.report_lang(lang or c.lang), fmt)
        _write(out, rep.content)
        emit(c, {"path": str(out), "filename": rep.filename}, c.t("report.written", path=out))

    @sa.command("table", help="导出第 N 轮（当前版本）的结果表：CSV / Excel")
    def s_table(
        ctx: typer.Context,
        session: Annotated[int, typer.Argument(help="会话编号")],
        turn: Annotated[int, typer.Argument(help="第几轮（从 1 开始）")],
        out: Annotated[Path, typer.Option("-o", "--out", help="输出文件")],
        fmt: Annotated[str, typer.Option("--format", help="csv / xlsx")] = "csv",
    ) -> None:
        c = output.get(ctx)
        if fmt not in ("csv", "xlsx"):
            fail(c, output.EXIT_USAGE, c.t("report.bad_format", allowed="csv, xlsx"))
        try:
            turns = ask_sessions.get(require_db(c), session)["turn_list"]
        except ask_sessions.SessionError as e:
            _fail(c, e)
        if not 1 <= turn <= len(turns):
            fail(c, output.EXIT_NOT_FOUND, c.t("ask_session.turn_not_found", id=turn))
        res = ask_report.current_version(turns[turn - 1]).get("result") or {}
        _write(out, ask_report.table_xlsx(res, f"turn {turn}") if fmt == "xlsx" else ask_report.table_csv(res))
        emit(c, {"path": str(out)}, c.t("report.written", path=out))

    @sa.command("ai-report", help="AI 写会话报告（Markdown；数字与对象名由代码核对；需要配置 AI）")
    def s_ai_report(
        ctx: typer.Context,
        session: Annotated[int, typer.Argument(help="会话编号")],
        out: Annotated[Path | None, typer.Option("-o", "--out", help="写入文件（不给时打印）")] = None,
        lang: Annotated[str | None, typer.Option("--lang", help="zh-CN / en（默认按界面语言）")] = None,
    ) -> None:
        c = output.get(ctx)
        s = _ai_ready(c)
        try:
            d = ask_sessions.get(require_db(c), session)
            r = ask_report.ai_report(s, d, lang or c.lang)
        except ask_sessions.SessionError as e:
            _fail(c, e)
        except ask.AskError as e:
            _ask_fail(c, e)
        if out is not None:
            _write(out, r["markdown"])
            r["path"] = str(out)
        emit(c, r, r["markdown"] if out is None else c.t("report.written", path=out))
