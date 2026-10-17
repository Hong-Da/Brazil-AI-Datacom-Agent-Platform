"""命令行入口 lmesh。只做参数解析与输出格式化，业务逻辑调用 core。"""

from __future__ import annotations

import contextlib
import os
import sys
from typing import Annotated, Any

import typer

from lmesh import __version__, paths
from lmesh.cli import output
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import config, i18n, setup, status, store
from lmesh.core import logging as lmlog

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
    help="透网 LucidMesh：多厂商路由器配置 → 统一配置图。 / LucidMesh CLI.",
)
config_app = typer.Typer(no_args_is_help=True, help="配置文件 / configuration")
db_app = typer.Typer(no_args_is_help=True, help="数据库 / database")
app.add_typer(config_app, name="config")
app.add_typer(db_app, name="db")


def _version(value: bool) -> None:
    if value:
        typer.echo(f"lmesh {__version__}")
        raise typer.Exit()


@app.callback()
def main_options(
    ctx: typer.Context,
    config_file: Annotated[str | None, typer.Option("--config", help="配置文件路径 / config file")] = None,
    lang: Annotated[str | None, typer.Option("--lang", help="zh-CN | en | pt-BR")] = None,
    output_fmt: Annotated[str, typer.Option("--output", help="text | json")] = "text",
    quiet: Annotated[bool, typer.Option("--quiet", "-q")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="跳过确认 / skip prompts")] = False,
    version: Annotated[bool, typer.Option("--version", callback=_version, is_eager=True)] = False,
) -> None:
    if output_fmt not in ("text", "json"):
        raise typer.BadParameter("--output: text | json")
    if config_file:
        os.environ["LMESH_CONFIG_FILE"] = config_file
    settings = _settings()
    c = Ctx(
        lang=i18n.normalize(lang or settings.get("ui.language")),
        output=output_fmt,
        quiet=quiet,
        verbose=verbose,
        yes=yes or not sys.stdin.isatty(),
        config_path=config_file,
    )
    ctx.obj = c
    lmlog.setup(
        level="DEBUG" if verbose else settings.get("log.level"),
        keep_days=settings.get("log.keep_days"),
        console=verbose,
    )


def _settings() -> config.Settings:
    p = os.environ.get("LMESH_CONFIG_FILE")
    from pathlib import Path

    return config.load(Path(p) if p else None)


@app.command("status", help="运行状态：版本、配置、数据库、知识库 / show status")
def cmd_status(ctx: typer.Context) -> None:
    c = output.get(ctx)
    info = status.collect(_settings())
    yes_no = {True: c.t("common.yes"), False: c.t("common.no")}
    lines = [
        f"{c.t('status.version')}: {info['version']}",
        f"{c.t('status.configured')}: {yes_no[info['configured']]}",
        f"{c.t('status.database')}: {info['database']['backend']} ({c.t('status.ok') if info['database']['ok'] else c.t('status.unavailable')})",
        f"{c.t('status.knowledge')}: {info['knowledge']['dir']} ({yes_no[info['knowledge']['exists']]})",
        f"{c.t('status.ai')}: {c.t('status.ai_on') if info['ai']['configured'] else c.t('status.ai_off')}",
    ]
    emit(c, info, "\n".join(lines))
    if not info["database"]["ok"]:
        raise typer.Exit(output.EXIT_EXTERNAL)


@app.command("serve", help="启动 Web 界面与远程 API / start the server")
def cmd_serve(
    ctx: typer.Context,
    host: Annotated[str | None, typer.Option(help="覆盖监听地址（不改配置文件）")] = None,
    port: Annotated[int | None, typer.Option(help="覆盖监听端口（不改配置文件）")] = None,
) -> None:
    import uvicorn

    from lmesh.api import create_app

    c = output.get(ctx)
    settings = _settings()
    h = host or settings.get("server.host")
    p = port or settings.get("server.port")
    if config.is_configured():
        store.upgrade(settings.database_url)
        setup.ensure_runtime_knowledge(settings)
    elif not setup.port_free(h, p):
        fail(c, output.EXIT_EXTERNAL, c.t("serve.port_busy", port=p))
    lmlog.setup(level=settings.get("log.level"), keep_days=settings.get("log.keep_days"), console=True)
    shown = "127.0.0.1" if h == "0.0.0.0" else h
    typer.echo(c.t("serve.url", url=f"http://{shown}:{p}"))
    if h == "0.0.0.0":
        others = [a for a in setup.local_addresses() if a not in ("0.0.0.0", "127.0.0.1")]
        if others:
            typer.echo(c.t("serve.lan", urls=", ".join(f"http://{a}:{p}" for a in others)))
    if not config.is_configured():
        typer.echo(c.t("serve.wizard"))
    uvicorn.run(create_app(settings, listen_host=h), host=h, port=p, log_level="warning")


@app.command("setup", help="首次运行向导（命令行）/ setup wizard")
def cmd_setup(
    ctx: typer.Context,
    defaults: Annotated[bool, typer.Option("--defaults", help="全部采用默认值与环境变量，不提问")] = False,
    force: Annotated[bool, typer.Option("--force", help="已有配置时覆盖")] = False,
) -> None:
    c = output.get(ctx)
    if config.is_configured() and not force:
        fail(c, output.EXIT_CONFIG, c.t("setup.already"))
    current = config.load()  # 默认值 + 环境变量（非交互场景从环境变量读取）
    answers: dict[str, Any] = {k: current.get(k) for k in current.values}
    if current.sources.get("ui.language") == "default":
        answers["ui.language"] = c.lang  # 没有环境变量指定时，跟随 --lang
    if not defaults and not c.yes:
        lang = typer.prompt("Language / 语言 / Idioma [zh-CN / en / pt-BR]", default=c.lang)
        c.lang = i18n.normalize(lang)
        answers["ui.language"] = c.lang
        for group in setup.wizard_schema(c.lang):
            typer.echo(f"\n== {group['title']} ==")
            for f in group["fields"]:
                if f["key"] == "ui.language":
                    continue
                while True:
                    typer.echo(f"  {f['desc']}")
                    choices = f" ({' / '.join(x or '-' for x in f['choices'])})" if f["choices"] else ""
                    v = typer.prompt(
                        f"  {f['key']}{choices}",
                        default=str(answers.get(f["key"]) or ""),
                        hide_input=f["kind"] in ("secret", "token"),
                        show_default=f["kind"] not in ("secret", "token"),
                    )
                    v = "" if v == "-" else v
                    errs = setup.validate_answers({**answers, f["key"]: v})
                    if f["key"] in errs:
                        typer.echo("  ! " + c.t(errs[f["key"]]), err=True)
                        continue
                    answers[f["key"]] = v
                    break
        if not typer.confirm(c.t("setup.confirm"), default=True):
            raise typer.Exit(output.EXIT_ERROR)
    try:
        result = setup.apply(answers, c.lang)
    except setup.SetupError as e:
        fail(c, output.EXIT_CONFIG, c.t("setup.invalid"), {k: c.t(v) for k, v in e.errors.items()})
    text = "\n".join(
        [c.t("setup.done", path=result["config_path"]), c.t("setup.url", url=result["url"])]
        + ([c.t("setup.token", token=result["api_token"])] if result["token_generated"] else [])
    )
    emit(c, result, text)


@config_app.command("example", help="生成 config/config.example.toml / write the example config")
def cmd_config_example(
    ctx: typer.Context,
    check: Annotated[bool, typer.Option("--check", help="只检查是否最新，不写入")] = False,
) -> None:
    c = output.get(ctx)
    target = paths.config_dir() / "config.example.toml"
    text = config.example_text()
    if check:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current != text:
            fail(c, output.EXIT_ERROR, c.t("config.example_outdated"))
        emit(c, {"path": str(target), "up_to_date": True}, c.t("config.example_ok"))
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    emit(c, {"path": str(target)}, c.t("config.example_written", path=target))


@config_app.command("show", help="显示当前生效的配置（敏感值只显示是否已设置）/ show effective config")
def cmd_config_show(ctx: typer.Context) -> None:
    c = output.get(ctx)
    s = _settings()
    data = {"values": s.public_dict(), "sources": s.sources}
    rows = [[k, str(v), s.sources[k]] for k, v in data["values"].items()]
    emit(c, data, output.table(rows, [c.t("config.key"), c.t("config.value"), c.t("config.source")]))


@db_app.command("upgrade", help="把数据库升级到最新结构 / migrate the database")
def cmd_db_upgrade(ctx: typer.Context) -> None:
    c = output.get(ctx)
    s = _settings()
    try:
        store.upgrade(s.database_url)
    except Exception as e:
        fail(c, output.EXIT_EXTERNAL, c.t("db.failed", error=type(e).__name__))
    emit(
        c,
        {"backend": store.backend_name(s.database_url), "tables": store.table_names(s.database_url)},
        c.t("db.upgraded", backend=store.backend_name(s.database_url)),
    )


from lmesh.cli import cmd_configs  # noqa: E402

cmd_configs.register(app, config_app)

from lmesh.cli import cmd_kb  # noqa: E402

cmd_kb.register(app)


def main() -> None:
    if os.name == "nt":  # Windows 控制台输出中文与葡语
        for stream in (sys.stdout, sys.stderr):
            with contextlib.suppress(AttributeError, ValueError):
                stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    app()
