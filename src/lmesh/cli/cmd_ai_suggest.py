"""AI 建议命令（M8-2，REQ-041）：lmesh ai suggest run|list|show|adopt|dismiss|revert|annotations。

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
from lmesh.core import ai_suggest, config, importer, projects

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
    ) -> None:
        c = output.get(ctx)
        env = _env(c)
        params: dict[str, Any] = {}
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
