"""AI 建议命令（M8-2，REQ-041）：lmesh ai suggest run|list|show|adopt|dismiss|revert|annotations；
M8-3 加 annotate（手工标注设备角色 / 分组）、coverage（变化解读的覆盖核对）、handover（设备交接文档）。

与 API 共用 core/ai_suggest；作用于当前项目（--project，不给时默认项目）；命令行权限等同管理员。
run 同步执行：需要 AI（未配置时退出码 3）；--replay <文件> 用文件里的回复代替真实 AI（同样经过代码校验，批次标明 replay）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from lmesh.cli import output
from lmesh.cli.cmd_configs import require_db
from lmesh.cli.cmd_graph import _kb
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import ai_suggest, ai_suggest_analysis, config, importer, projects

_EXIT = {
    "param": output.EXIT_USAGE,
    "not_found": output.EXIT_NOT_FOUND,
    "state": output.EXIT_ERROR,
    "forbidden": output.EXIT_ERROR,
    "external": output.EXIT_EXTERNAL,
}


def _fail(c: Ctx, e: ai_suggest.SuggestError) -> NoReturn:
    code = output.EXIT_CONFIG if e.key == "ai.not_configured" else _EXIT.get(e.kind, output.EXIT_ERROR)
    msg = c.t(e.key, **e.fmt)
    data = e.data if isinstance(e.data, dict) else {}
    if e.key == "ai.not_configured" and data.get("reason"):
        msg += f" ({c.t('ai.reason.' + str(data['reason']))})"
    if data.get("check"):
        msg += "".join(f"\n  {_reason_text(c, r)}" for r in data["check"].get("reasons", []))
    fail(c, code, msg, e.data)


def _env(c: Ctx) -> ai_suggest.Env:
    db = require_db(c)
    settings = config.load()
    scope = projects.current()
    who = projects.identity() or projects.cli_identity(db, c.as_user)
    return ai_suggest.Env(
        settings,
        lambda: _kb(c)[0],
        project_id=scope.project_id if scope else None,
        user_id=who.user_id,
        actor=who.username or "cli",
        kb_editor=True,
        admin=True,
        lang=c.lang,
    )


def _device_id(c: Ctx, db: str, target: str) -> int:
    dev = next(
        (d for d in importer.list_devices(db) if d["name"] == target or (target.isdigit() and d["id"] == int(target))),
        None,
    )
    if dev is None:
        fail(c, output.EXIT_NOT_FOUND, c.t("ai_suggest.device_not_found", id=target))
    return int(dev["id"])


def _reason_text(c: Ctx, r: dict[str, Any]) -> str:
    text = c.t(f"ai_suggest.reason.{r['code']}")
    extra = r.get("ref") or r.get("detail")
    return f"[{r['level']}] {text}" + (f": {extra}" if extra else "")


_MARK = {"pass": "✓", "warn": "!", "reject": "✕"}


def _row_text(c: Ctx, s: dict[str, Any]) -> str:
    chk = s.get("check") or {}
    head = (
        f"#{s['id']} {_MARK.get(s['check_status'], '?')} {s['category']} [{c.t('ai_suggest.status.' + s['status'])}] "
    )
    head += s["title"] or ""
    body = chk.get("display") or ""
    if not body and isinstance(s.get("content"), dict):
        body = json.dumps(s["content"], ensure_ascii=False)[:300]
    lines = [head]
    if body:
        lines.append(f"    {body}")
    lines += [f"    {_reason_text(c, r)}" for r in chk.get("reasons", [])]
    return "\n".join(lines)


def _batch_text(c: Ctx, b: dict[str, Any], items: list[dict[str, Any]]) -> str:
    n = b["counts"]
    head = c.t(
        "ai_suggest.batch_done",
        id=b["id"],
        skill=b["skill"],
        status=b["status"],
        total=n.get("total", 0),
        passed=n.get("pass", 0),
        warn=n.get("warn", 0),
        reject=n.get("reject", 0),
    )
    if b.get("error"):
        head += (
            "\n"
            + c.t(str(b["error"].get("key") or "ai_suggest.bad_reply"))
            + (f" ({b['error']['detail']})" if b["error"].get("detail") else "")
        )
    return "\n".join([head, *(_row_text(c, s) for s in items)])


def register(ai_app: typer.Typer) -> None:
    sapp = typer.Typer(no_args_is_help=True, help="AI 建议：运行、查看、采纳、忽略、撤销 / AI suggestions")
    ai_app.add_typer(sapp, name="suggest")

    @sapp.command("run", help="运行 skill 生成建议（代码校验后入库）/ run a skill to produce suggestions")
    def s_run(
        ctx: typer.Context,
        skill: Annotated[str, typer.Argument(help="skill 编号，例如 device-summary、topology-roles")],
        device: Annotated[
            str | None, typer.Option("--device", help="设备名或编号（作用于单台设备的 skill 必填）")
        ] = None,
        devices: Annotated[
            str | None, typer.Option("--devices", help="拓扑类 skill 只取这些设备（逗号分隔的名称或编号）")
        ] = None,
        replay: Annotated[
            Path | None, typer.Option("--replay", help="用文件里的回复代替真实 AI（仍经过代码校验）")
        ] = None,
        params_json: Annotated[
            str | None,
            typer.Option(
                "--params",
                help='skill 的其他参数（JSON 对象），例如 {"source": "history", "a_version": 1, "b_version": 2}',
            ),
        ] = None,
        doc: Annotated[
            Path | None,
            typer.Option("--doc", help="规范文件（txt / md / docx），文字作为参数 text（M8-5 规范转规则）"),
        ] = None,
    ) -> None:
        c = output.get(ctx)
        env = _env(c)
        params: dict[str, Any] = {}
        if params_json:
            try:
                params = json.loads(params_json)
            except json.JSONDecodeError:
                params = None  # type: ignore[assignment]
            if not isinstance(params, dict):
                fail(c, output.EXIT_USAGE, c.t("ai_suggest.bad_params"))
        if doc is not None:
            from lmesh.core import ai_suggest_kb

            if not doc.is_file():
                fail(c, output.EXIT_NOT_FOUND, c.t("ai_kb.doc_missing", path=str(doc)))
            try:
                got = ai_suggest_kb.extract_text(doc.name, doc.read_bytes())
            except ai_suggest.SuggestError as e:
                _fail(c, e)
            params["text"], params["doc_name"] = got["text"], got["name"]
        if device:
            params["device_id"] = _device_id(c, env.db, device)
        if devices:
            params["device_ids"] = [x.strip() for x in devices.split(",") if x.strip()]
        reply = None
        if replay is not None:
            if not replay.is_file():
                fail(c, output.EXIT_NOT_FOUND, c.t("ai_suggest.replay_missing", path=str(replay)))
            reply = replay.read_text(encoding="utf-8")
        try:
            b = ai_suggest.run(env, skill, params, reply=reply)
        except ai_suggest.SuggestError as e:
            _fail(c, e)
        items = ai_suggest.list_suggestions(env, batch_id=b["id"])["items"] if b["status"] == "done" else []
        data = {"batch": b, "items": items}
        if b["status"] == "failed":
            fail(c, output.EXIT_EXTERNAL, _batch_text(c, b, []), data)
        emit(c, data, _batch_text(c, b, list(reversed(items))))

    @sapp.command("list", help="建议列表（按 skill、状态、校验结果、设备、批次过滤）/ list suggestions")
    def s_list(
        ctx: typer.Context,
        skill: Annotated[str | None, typer.Option("--skill")] = None,
        status: Annotated[str | None, typer.Option("--status", help="pending | adopted | dismissed | reverted")] = None,
        check: Annotated[str | None, typer.Option("--check", help="pass | warn | reject")] = None,
        category: Annotated[str | None, typer.Option("--category")] = None,
        device: Annotated[str | None, typer.Option("--device", help="设备名或编号")] = None,
        batch: Annotated[int | None, typer.Option("--batch", help="批次编号")] = None,
        limit: Annotated[int, typer.Option("--limit")] = 100,
    ) -> None:
        c = output.get(ctx)
        env = _env(c)
        if status and status not in ai_suggest.STATUSES:
            fail(c, output.EXIT_USAGE, c.t("ai_suggest.bad_status", allowed=", ".join(ai_suggest.STATUSES)))
        if check and check not in ai_suggest.CHECKS:
            fail(c, output.EXIT_USAGE, c.t("ai_suggest.bad_check", allowed=", ".join(ai_suggest.CHECKS)))
        did = _device_id(c, env.db, device) if device else None
        data = ai_suggest.list_suggestions(env, skill, status, check, category, did, batch, None, limit)
        text = "\n".join(_row_text(c, s) for s in data["items"]) or c.t("ai_suggest.empty")
        emit(c, data, text)

    @sapp.command("show", help="一条建议的详情 / show a suggestion")
    def s_show(ctx: typer.Context, sid: Annotated[int, typer.Argument(help="建议编号")]) -> None:
        c = output.get(ctx)
        env = _env(c)
        try:
            s = ai_suggest.get(env, sid)
        except ai_suggest.SuggestError as e:
            _fail(c, e)
        emit(c, s, _row_text(c, s))

    @sapp.command("adopt", help="采纳：给编号逐条采纳，或 --category 按类别批量采纳校验通过的 / adopt suggestions")
    def s_adopt(
        ctx: typer.Context,
        ids: Annotated[list[int] | None, typer.Argument(help="建议编号（可多个）")] = None,
        category: Annotated[
            str | None, typer.Option("--category", help="批量：只采纳该类别中校验通过（pass）的")
        ] = None,
        skill: Annotated[str | None, typer.Option("--skill", help="批量时只取该 skill")] = None,
        batch: Annotated[int | None, typer.Option("--batch", help="批量时只取该批次")] = None,
        edit: Annotated[
            Path | None, typer.Option("--edit", help="编辑后采纳：JSON 文件，内容为新的 content（只能配一个编号）")
        ] = None,
    ) -> None:
        c = output.get(ctx)
        env = _env(c)
        try:
            if category:
                r = ai_suggest.adopt_batch(env, category, skill, batch, ids or None)
                emit(c, r, c.t("ai_suggest.batch_adopted", n=len(r["adopted"]), skipped=len(r["skipped"])))
                return
            if not ids:
                fail(c, output.EXIT_USAGE, c.t("ai_suggest.need_ids"))
            content = None
            if edit is not None:
                if len(ids) != 1:
                    fail(c, output.EXIT_USAGE, c.t("ai_suggest.edit_one"))
                try:
                    content = json.loads(edit.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    fail(c, output.EXIT_USAGE, c.t("ai_suggest.bad_edit", path=str(edit)))
            done = [ai_suggest.adopt(env, i, content if edit is not None else None) for i in ids]
        except ai_suggest.SuggestError as e:
            _fail(c, e)
        emit(c, {"items": done}, "\n".join(_row_text(c, s) for s in done))

    @sapp.command("dismiss", help="忽略待处理的建议 / dismiss suggestions")
    def s_dismiss(
        ctx: typer.Context,
        ids: Annotated[list[int], typer.Argument(help="建议编号（可多个）")],
        note: Annotated[str, typer.Option("--note")] = "",
    ) -> None:
        c = output.get(ctx)
        env = _env(c)
        try:
            done = [ai_suggest.dismiss(env, i, note) for i in ids]
        except ai_suggest.SuggestError as e:
            _fail(c, e)
        emit(c, {"items": done}, "\n".join(_row_text(c, s) for s in done))

    @sapp.command("revert", help="撤销已采纳的建议 / revert adopted suggestions")
    def s_revert(
        ctx: typer.Context,
        ids: Annotated[list[int], typer.Argument(help="建议编号（可多个）")],
        note: Annotated[str, typer.Option("--note")] = "",
    ) -> None:
        c = output.get(ctx)
        env = _env(c)
        try:
            done = [ai_suggest.revert(env, i, note) for i in ids]
        except ai_suggest.SuggestError as e:
            _fail(c, e)
        emit(c, {"items": done}, "\n".join(_row_text(c, s) for s in done))

    @sapp.command("annotations", help="项目的视图标注（设备角色、分组、标签）/ project view annotations")
    def s_annotations(ctx: typer.Context) -> None:
        c = output.get(ctx)
        env = _env(c)
        items = ai_suggest.list_annotations(env.db, env.project_id or 0) if env.project_id else []
        text = "\n".join(
            f"{a['target_type']}:{a['target']} {a['key']} = {a['value']} ({a['source']})" for a in items
        ) or c.t("ai_suggest.empty")
        emit(c, {"items": items}, text)

    @sapp.command(
        "annotate", help="手工标注设备的角色、分组、标签或层次（优先于 AI 建议）/ set a manual view annotation"
    )
    def s_annotate(
        ctx: typer.Context,
        device: Annotated[str, typer.Argument(help="设备名或编号")],
        key: Annotated[str, typer.Option("--key", help="role | group | label | layer")] = "role",
        value: Annotated[str | None, typer.Option("--value", help="取值；不给或 --clear 时清除")] = None,
        clear: Annotated[bool, typer.Option("--clear", help="清除这项标注")] = False,
    ) -> None:
        c = output.get(ctx)
        env = _env(c)
        did = _device_id(c, env.db, device)
        val: Any = None if clear else value
        if key == "layer" and isinstance(val, str) and val.isdigit():
            val = int(val)
        try:
            item = ai_suggest_analysis.set_annotation(env, "device", str(did), key, val)
        except ai_suggest.SuggestError as e:
            _fail(c, e)
        text = (
            c.t("ai_suggest.annotated", target=device, item=key, value=item["value"])
            if item
            else c.t("ai_suggest.annotation_cleared", target=device, item=key)
        )
        emit(c, {"item": item}, text)

    @sapp.command("coverage", help="覆盖核对：没有被任何意图解释的差异条目（代码计算）/ coverage of difference entries")
    def s_coverage(
        ctx: typer.Context,
        scope: Annotated[str, typer.Argument(help="范围，例如 compare:3:5、history:3:5")],
        skill: Annotated[str, typer.Option("--skill")] = "diff-explain",
    ) -> None:
        c = output.get(ctx)
        env = _env(c)
        r = ai_suggest_analysis.coverage(env, skill, scope)
        if r["batch_id"] is None:
            emit(c, r, c.t("ai_suggest.coverage_none"))
            return
        lst = ", ".join(f"{u['id']} {u['label']}" for u in r["uncovered"]) or "-"
        emit(c, r, c.t("ai_suggest.coverage", covered=len(r["covered"]), total=r["total"], list=lst))

    @sapp.command("handover", help="导出设备交接文档（含采纳的 AI 设备摘要）/ export the device handover note")
    def s_handover(
        ctx: typer.Context,
        device: Annotated[str, typer.Argument(help="设备名或编号")],
        lang: Annotated[str, typer.Option("--doc-lang", help="文档语言 zh-CN | en")] = "zh-CN",
        fmt: Annotated[str, typer.Option("--format", help="html | md")] = "md",
        out: Annotated[Path | None, typer.Option("-o", "--out", help="写入文件；不给时打印到屏幕")] = None,
    ) -> None:
        c = output.get(ctx)
        env = _env(c)
        did = _device_id(c, env.db, device)
        try:
            rep = ai_suggest_analysis.handover(env, did, lang, fmt)
        except ai_suggest.SuggestError as e:
            _fail(c, e)
        if out is not None:
            out.write_text(rep.content, encoding="utf-8")
            emit(c, {"file": str(out), "name": rep.filename}, c.t("ai_suggest.handover_saved", path=str(out)))
            return
        emit(c, {"name": rep.filename, "content": rep.content}, rep.content)

    @sapp.command("redact", help="本项目的脱敏补充（采纳的脱敏复核建议，M8-5）/ the project's sanitize supplement")
    def s_redact(ctx: typer.Context) -> None:
        from lmesh.core import ai_suggest_kb

        c = output.get(ctx)
        env = _env(c)
        pats = ai_suggest_kb.project_redact(env.db, env.project_id)
        emit(c, {"patterns": pats}, "\n".join(pats) or c.t("ai_suggest.empty"))
