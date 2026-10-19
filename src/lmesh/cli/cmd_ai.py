"""AI 接口命令（REQ-040）：lmesh ai connections …（管理员接口）、lmesh ai use、lmesh ai personal …、lmesh ai status、
lmesh ai usage。命令行直接操作本机数据库，权限等同管理员；use / personal 作用于 --as 账号（不给时第一个管理员）。
API Key 不写在命令行参数里也可以：--api-key-stdin 从标准输入读取（不进 shell 历史）。"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Annotated, Any

import typer

from lmesh.cli import output
from lmesh.cli.cmd_configs import require_db
from lmesh.cli.output import emit, fail
from lmesh.core import ai, ai_connections, config, projects

_EXIT = {"not_found": output.EXIT_NOT_FOUND, "state": output.EXIT_ERROR, "param": output.EXIT_USAGE}


def _settings(c: output.Ctx) -> config.Settings:
    require_db(c)
    return config.load()


def _conn_err(c: output.Ctx, e: ai_connections.ConnError) -> None:
    detail = (e.data or {}).get("error") if isinstance(e.data, dict) else None
    msg = c.t(e.key, **e.fmt) + (f"（{detail}）" if detail and c.lang == "zh-CN" else f" ({detail})" if detail else "")
    fail(c, _EXIT.get(e.kind, output.EXIT_ERROR), msg, e.data)


def _key(api_key: str | None, from_stdin: bool) -> str | None:
    if from_stdin:
        return sys.stdin.readline().strip() or None
    return api_key


def _fields(
    provider: str | None,
    base_url: str | None,
    api_key: str | None,
    model: str | None,
    model_extract: str | None,
    model_merge: str | None,
    model_ask: str | None,
    model_generate: str | None,
    clear_api_key: bool = False,
) -> dict[str, Any]:
    d = {
        "provider": provider,
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "model_extract": model_extract,
        "model_merge": model_merge,
        "model_ask": model_ask,
        "model_generate": model_generate,
        "clear_api_key": clear_api_key,
    }
    return {k: v for k, v in d.items() if v not in (None, False)}


def _who(c: output.Ctx) -> projects.Identity:
    """use / personal 作用的账号：--as，不给时第一个管理员；还没有账号时退出码 1。"""
    db = require_db(c)
    try:
        ident = projects.cli_identity(db, c.as_user)
    except projects.ProjectError as e:
        fail(c, output.EXIT_NOT_FOUND, c.t(e.key, **e.fmt))
    if ident.user_id is None:
        fail(c, output.EXIT_ERROR, c.t("ai.need_account"))
    return ident


def _effective_text(c: output.Ctx, eff: dict[str, Any]) -> str:
    if eff["configured"]:
        if eff["source"] == "personal":
            src = c.t("ai.src.personal")
        else:
            src = c.t("ai.src.connection", name=(eff.get("connection") or {}).get("name", ""))
        return c.t("ai.effective", src=src, model=eff.get("model") or "")
    return c.t("ai.effective_off", reason=c.t(f"ai.reason.{eff.get('reason') or 'no_connection'}"))


# 各选项（多个命令共用）
ProviderOpt = Annotated[str | None, typer.Option("--provider", help="anthropic | openai | local")]
UrlOpt = Annotated[str | None, typer.Option("--base-url", help="接口地址（OpenAI 兼容 / 本地模型必填）")]
KeyOpt = Annotated[str | None, typer.Option("--api-key", help="API Key（加密保存）；更安全的做法是 --api-key-stdin")]
KeyStdinOpt = Annotated[bool, typer.Option("--api-key-stdin", help="从标准输入读取 API Key")]
ModelOpt = Annotated[str | None, typer.Option("--model", help="默认模型")]
MExtract = Annotated[str | None, typer.Option("--model-extract", help="命令卡抽取用的模型")]
MMerge = Annotated[str | None, typer.Option("--model-merge", help="语义归并用的模型")]
MAsk = Annotated[str | None, typer.Option("--model-ask", help="自然语言查询用的模型")]
MGen = Annotated[str | None, typer.Option("--model-generate", help="生成配置用的模型")]


def register(ai_app: typer.Typer) -> None:
    conn_app = typer.Typer(no_args_is_help=True, help="管理员 AI 接口 / admin AI connections")
    personal_app = typer.Typer(no_args_is_help=True, help="个人 AI 接口 / personal AI connection")
    ai_app.add_typer(conn_app, name="connections")
    ai_app.add_typer(personal_app, name="personal")

    @conn_app.command("list", help="管理员 AI 接口列表 / list admin AI connections")
    def conn_list(ctx: typer.Context) -> None:
        c = output.get(ctx)
        data = ai_connections.list_connections(_settings(c))
        yes, no = c.t("common.yes"), c.t("common.no")
        rows = [
            [
                str(x["id"]) + (" *" if x["is_default"] else ""),
                x["name"],
                x["provider"],
                x["model"],
                yes if x["public"] else no,
                yes if x["enabled"] else no,
                str(x["chosen_by"]),
                f"{x['usage']['tokens_in']}/{x['usage']['tokens_out']}",
            ]
            for x in data["connections"]
        ]
        head = [
            "#",
            c.t("ai.col.name"),
            c.t("ai.col.provider"),
            c.t("ai.model"),
            c.t("ai.col.public"),
            c.t("ai.col.enabled"),
            c.t("ai.col.chosen"),
            "tokens",
        ]
        emit(c, data, output.table(rows, head) + "\n" + c.t("ai.default_mark") if rows else c.t("ai.conn.none"))

    @conn_app.command("add", help="新建管理员 AI 接口 / add an admin AI connection")
    def conn_add(
        ctx: typer.Context,
        name: Annotated[str, typer.Argument(help="名称（唯一）")],
        provider: ProviderOpt = None,
        base_url: UrlOpt = None,
        api_key: KeyOpt = None,
        api_key_stdin: KeyStdinOpt = False,
        model: ModelOpt = None,
        model_extract: MExtract = None,
        model_merge: MMerge = None,
        model_ask: MAsk = None,
        model_generate: MGen = None,
        public: Annotated[bool, typer.Option("--public/--private", help="允许公共使用（普通账号可以选用）")] = False,
        enabled: Annotated[bool, typer.Option("--enabled/--disabled")] = True,
    ) -> None:
        c = output.get(ctx)
        f = _fields(
            provider,
            base_url,
            _key(api_key, api_key_stdin),
            model,
            model_extract,
            model_merge,
            model_ask,
            model_generate,
        )
        try:
            r = ai_connections.create_connection(
                _settings(c), {"name": name, "public": public, "enabled": enabled, **f}
            )
        except ai_connections.ConnError as e:
            _conn_err(c, e)
        emit(c, r, c.t("ai.conn.created", name=r["name"], id=r["id"]))

    @conn_app.command("set", help="修改管理员 AI 接口（名称或编号）/ change an admin AI connection")
    def conn_set(
        ctx: typer.Context,
        ref: Annotated[str, typer.Argument(help="接口名称或编号")],
        name: Annotated[str | None, typer.Option("--name", help="改名")] = None,
        provider: ProviderOpt = None,
        base_url: UrlOpt = None,
        api_key: KeyOpt = None,
        api_key_stdin: KeyStdinOpt = False,
        clear_api_key: Annotated[bool, typer.Option("--clear-api-key", help="清除 API Key")] = False,
        model: ModelOpt = None,
        model_extract: MExtract = None,
        model_merge: MMerge = None,
        model_ask: MAsk = None,
        model_generate: MGen = None,
        public: Annotated[bool | None, typer.Option("--public/--private", help="允许公共使用")] = None,
        enabled: Annotated[bool | None, typer.Option("--enabled/--disabled")] = None,
    ) -> None:
        c = output.get(ctx)
        s = _settings(c)
        f = _fields(
            provider,
            base_url,
            _key(api_key, api_key_stdin),
            model,
            model_extract,
            model_merge,
            model_ask,
            model_generate,
            clear_api_key,
        )
        try:
            cid = ai_connections.find_admin(s, ref)
            r = ai_connections.update_connection(s, cid, {**f, "name": name, "public": public, "enabled": enabled})
        except ai_connections.ConnError as e:
            _conn_err(c, e)
        emit(c, r, c.t("ai.conn.updated", name=r["name"], id=r["id"]))

    @conn_app.command("remove", help="删除管理员 AI 接口 / remove an admin AI connection")
    def conn_remove(ctx: typer.Context, ref: Annotated[str, typer.Argument(help="接口名称或编号")]) -> None:
        c = output.get(ctx)
        s = _settings(c)
        try:
            cid = ai_connections.find_admin(s, ref)
        except ai_connections.ConnError as e:
            _conn_err(c, e)
        if not c.yes and not typer.confirm(c.t("ai.conn.remove_confirm", name=ref), default=False):
            raise typer.Exit(output.EXIT_ERROR)
        r = ai_connections.delete_connection(s, cid)
        emit(c, r, c.t("ai.conn.removed", name=ref, n=r["affected_users"]))

    @conn_app.command("test", help="测试管理员 AI 接口 / test an admin AI connection")
    def conn_test(ctx: typer.Context, ref: Annotated[str, typer.Argument(help="接口名称或编号")]) -> None:
        c = output.get(ctx)
        s = _settings(c)
        try:
            conn = ai_connections.admin_conn(s, ai_connections.find_admin(s, ref))
        except ai_connections.ConnError as e:
            _conn_err(c, e)
        _run_test(c, s, conn)

    @ai_app.command("use", help="选择 AI 来源：personal | <公共接口名> | none | auto / choose the AI source")
    def ai_use(
        ctx: typer.Context, target: Annotated[str, typer.Argument(help="personal | 接口名称或编号 | none | auto")]
    ) -> None:
        c = output.get(ctx)
        s = _settings(c)
        who = _who(c)
        data: dict[str, Any]
        if target in ("personal", "none", "auto"):
            data = {"choice": target}
        else:
            try:
                data = {"choice": "connection", "connection_id": ai_connections.find_admin(s, target)}
            except ai_connections.ConnError as e:
                _conn_err(c, e)
        try:
            r = ai_connections.save_mine(s, who, data)
        except ai_connections.ConnError as e:
            _conn_err(c, e)
        emit(c, r, c.t("ai.use_ok", user=who.username) + "\n" + _effective_text(c, r["effective"]))

    @ai_app.command("status", help="当前账号的 AI 选择与生效来源 / effective AI source")
    def ai_status(ctx: typer.Context) -> None:
        c = output.get(ctx)
        s = _settings(c)
        db = require_db(c)
        who = projects.cli_identity(db, c.as_user)
        r = ai_connections.mine(s, who if who.user_id is not None else None)
        lines = [f"{who.username}: {r['choice']}", _effective_text(c, r["effective"])]
        emit(c, r, "\n".join(lines))

    @personal_app.command("show", help="查看个人 AI 接口（不显示 Key）/ show the personal connection")
    def personal_show(ctx: typer.Context) -> None:
        c = output.get(ctx)
        r = ai_connections.mine(_settings(c), _who(c))
        p = r["personal"]
        if p is None:
            emit(c, r, c.t("ai.personal_none"))
            return
        key = c.t("ai.key_set") if p["api_key_set"] else c.t("ai.key_unset")
        emit(c, r, f"{p['provider']}  {p['base_url'] or '—'}  {p['model']}  ({key})")

    @personal_app.command("set", help="新建或修改个人 AI 接口 / set the personal connection")
    def personal_set(
        ctx: typer.Context,
        provider: ProviderOpt = None,
        base_url: UrlOpt = None,
        api_key: KeyOpt = None,
        api_key_stdin: KeyStdinOpt = False,
        clear_api_key: Annotated[bool, typer.Option("--clear-api-key")] = False,
        model: ModelOpt = None,
        model_extract: MExtract = None,
        model_merge: MMerge = None,
        model_ask: MAsk = None,
        model_generate: MGen = None,
        use: Annotated[bool, typer.Option("--use", help="同时改为使用个人接口")] = False,
    ) -> None:
        c = output.get(ctx)
        f = _fields(
            provider,
            base_url,
            _key(api_key, api_key_stdin),
            model,
            model_extract,
            model_merge,
            model_ask,
            model_generate,
            clear_api_key,
        )
        data: dict[str, Any] = {"personal": f}
        if use:
            data["choice"] = "personal"
        try:
            r = ai_connections.save_mine(_settings(c), _who(c), data)
        except ai_connections.ConnError as e:
            _conn_err(c, e)
        emit(c, r, c.t("ai.personal_saved") + "\n" + _effective_text(c, r["effective"]))

    @personal_app.command("remove", help="删除个人 AI 接口 / remove the personal connection")
    def personal_remove(ctx: typer.Context) -> None:
        c = output.get(ctx)
        r = ai_connections.save_mine(_settings(c), _who(c), {"remove_personal": True})
        emit(c, r, c.t("ai.personal_removed"))

    @personal_app.command("test", help="测试个人 AI 接口 / test the personal connection")
    def personal_test(ctx: typer.Context) -> None:
        c = output.get(ctx)
        s = _settings(c)
        conn = ai_connections.personal_conn(s, _who(c))
        if conn is None:
            fail(c, output.EXIT_CONFIG, c.t("ai.personal_missing"))
        _run_test(c, s, conn)

    @ai_app.command("usage", help="AI 用量统计 / AI token usage")
    def ai_usage(
        ctx: typer.Context,
        start: Annotated[
            str | None, typer.Option("--from", help="起始日期 YYYY-MM-DD（UTC，含）；默认结束前 29 天")
        ] = None,
        end: Annotated[str | None, typer.Option("--to", help="结束日期 YYYY-MM-DD（UTC，含）；默认今天")] = None,
        group: Annotated[str, typer.Option("--group", help="day | user | connection | feature | model")] = "day",
        user: Annotated[str | None, typer.Option("--user", help="只统计这个账号")] = None,
        csv: Annotated[Path | None, typer.Option("--csv", help="把这一组导出为 CSV 文件")] = None,
    ) -> None:
        c = output.get(ctx)
        if group not in ai.USAGE_GROUPS:
            fail(c, output.EXIT_USAGE, c.t("ai.usage.bad_group", groups=" / ".join(ai.USAGE_GROUPS)))
        try:
            d0 = date.fromisoformat(start) if start else None
            d1 = date.fromisoformat(end) if end else None
        except ValueError:
            fail(c, output.EXIT_USAGE, c.t("ai.usage.bad_date"))
        data = ai.usage(require_db(c), d0, d1, actor=user)
        if csv is not None:
            csv.parent.mkdir(parents=True, exist_ok=True)
            csv.write_text(ai.usage_csv(data, group), encoding="utf-8", newline="")
        t = data["totals"]
        rows = [
            [str(r["key"]), str(r["calls"]), str(r["errors"]), str(r["tokens_in"]), str(r["tokens_out"])]
            for r in data[f"by_{group}"]
        ]
        head = [c.t(f"ai.usage.g_{group}"), c.t("ai.usage.calls"), c.t("ai.usage.errors"), "tokens in", "tokens out"]
        text = c.t(
            "ai.usage.summary",
            start=data["from"],
            end=data["to"],
            calls=t["calls"],
            errors=t["errors"],
            tin=t["tokens_in"],
            tout=t["tokens_out"],
        )
        if rows:
            text += "\n" + output.table(rows, head)
        if csv is not None:
            text += "\n" + c.t("ai.usage.csv_written", path=csv)
        emit(c, data, text)


def _run_test(c: output.Ctx, s: config.Settings, conn: ai_connections.Conn) -> None:
    try:
        res = ai.test(s, conn)
    except ai.AIError as e:
        fail(c, output.EXIT_EXTERNAL, c.t(str(e)))
    emit(c, res, c.t("ai.test_ok", model=res["model"], reply=res["reply"]))
