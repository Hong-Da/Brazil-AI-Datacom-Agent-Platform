"""配置相关命令：sanitize、config import、config list。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from lmesh.cli import output
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import config, importer, store
from lmesh.core.sanitize import Level, SanitizeLeak, Sanitizer, local_key


def require_db(c: Ctx) -> str:
    """需要数据库的命令：未配置时提示先完成首次配置。"""
    if not config.is_configured():
        fail(c, output.EXIT_CONFIG, c.t("config.not_configured"))
    url = config.load().database_url
    try:
        store.upgrade(url)
    except Exception as e:
        fail(c, output.EXIT_EXTERNAL, c.t("db.failed", error=type(e).__name__))
    return url


def _actor() -> str:
    """导入人：操作系统用户名（版本历史的导入记录用）。"""
    import getpass

    try:
        return getpass.getuser()
    except Exception:
        return ""


def _level(c: Ctx, level: str) -> Level:
    if level not in ("basic", "strict"):
        fail(c, output.EXIT_USAGE, c.t("sanitize.bad_level"))
    return level  # type: ignore[return-value]


def register(app: typer.Typer, config_app: typer.Typer) -> None:
    @app.command(
        "sanitize", help="配置脱敏：替换密码、密文、团体字、密钥、IP 等，保持引用关系与行号 / sanitize configs"
    )
    def cmd_sanitize(
        ctx: typer.Context,
        source: Annotated[Path, typer.Argument(help="配置文件、目录或 zip")],
        out: Annotated[Path, typer.Option("--out", "-o", help="输出文件（单个输入时）或目录")],
        level: Annotated[
            str, typer.Option(help="basic：秘密与公网 IP；strict：另外替换全部 IP、主机名、描述、用户名")
        ] = "basic",
        map_out: Annotated[
            Path | None, typer.Option("--map-out", help="把“原值 → 替换值”写到这个文件（敏感，只在本机保存）")
        ] = None,
        redact: Annotated[
            list[str] | None, typer.Option("--redact", help="额外替换的词或正则（客户名、站点编码等），可多次使用")
        ] = None,
    ) -> None:
        c = output.get(ctx)
        if not source.exists():
            fail(c, output.EXIT_NOT_FOUND, c.t("common.not_found", path=source))
        sanitizer = Sanitizer(_level(c, level), local_key(), redact=redact)
        items = list(importer.iter_sources(source))
        single = source.is_file() and not source.name.lower().endswith(".zip") and len(items) == 1
        results = []
        for name, raw in items:
            try:
                res, text = importer.sanitize_one(name, raw, sanitizer)
            except SanitizeLeak as e:
                fail(c, output.EXIT_ERROR, str(e))
            if res.ok:
                target = out if single else out / name.replace("/", "_")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(text.encode("utf-8"))  # 统一 LF 换行，不随系统转换
                results.append({**res.as_dict(), "output": str(target)})
            else:
                results.append({**res.as_dict(), "error": c.t(res.error)})
        if map_out:
            map_out.parent.mkdir(parents=True, exist_ok=True)
            map_out.write_text(json.dumps(sanitizer.mapping(), ensure_ascii=False, indent=2), encoding="utf-8")
        rows = [
            [
                r["source"],
                r["vendor"] or "-",
                str(sum(r["sanitized"].values())) if r["ok"] else "-",
                r.get("output", "") if r["ok"] else r["error"],
            ]
            for r in results
        ]
        emit(
            c,
            {"files": results},
            output.table(
                rows, [c.t("import.file"), c.t("import.vendor"), c.t("sanitize.count"), c.t("sanitize.output")]
            ),
        )
        if not any(r["ok"] for r in results):
            raise typer.Exit(output.EXIT_ERROR)

    @config_app.command("import", help="导入配置：识别厂商 → 脱敏 → 入库 / import configs")
    def cmd_import(
        ctx: typer.Context,
        source: Annotated[Path, typer.Argument(help="配置文件、目录或 zip")],
        level: Annotated[str, typer.Option(help="脱敏强度：basic / strict")] = "basic",
        profile: Annotated[
            str | None,
            typer.Option("--profile", help="手工指定 Profile（所有文件；只允许同厂商 / 同平台族，认不出厂商时任意）"),
        ] = None,
        keep_unsupported: Annotated[
            bool, typer.Option("--keep-unsupported", help="认不出厂商的文件只存原文（默认不导入）")
        ] = False,
        remember: Annotated[
            str | None, typer.Option("--remember", help="把 --profile 记住为型号规则：project / global")
        ] = None,
        match_name: Annotated[
            str | None, typer.Option("--match-name", help="规则的设备名模式（默认按设备名预填）")
        ] = None,
        match_version: Annotated[str | None, typer.Option("--match-version", help="规则的软件版本正则")] = None,
        match_feature: Annotated[str | None, typer.Option("--match-feature", help="规则的特征命令正则")] = None,
    ) -> None:
        c = output.get(ctx)
        if not source.exists():
            fail(c, output.EXIT_NOT_FOUND, c.t("common.not_found", path=source))
        if remember and (remember not in ("project", "global") or not profile):
            fail(c, output.EXIT_USAGE, c.t("model.remember_needs_profile"))
        url = require_db(c)
        from lmesh.core import kbservice

        kb_root = kbservice.runtime_root(config.load())
        kind = "dir" if source.is_dir() else ("zip" if source.suffix.lower() == ".zip" else "file")
        settings = config.load()
        items = list(importer.iter_sources(source))
        choices = None
        if remember and profile:
            rem = {"scope": remember}
            rem.update(
                {
                    k: v
                    for k, v in (("name_pattern", match_name), ("version", match_version), ("feature", match_feature))
                    if v
                }
            )
            choices = {name: {"profile": profile, "remember": rem} for name, _ in items}
        results = [
            r.as_dict()
            for r in importer.import_sources(
                items,
                url,
                _level(c, level),
                kb_root,
                source_kind=kind,
                actor=_actor(),
                keep=int(settings.get("history.keep")),
                choices=choices,
                profile=profile,
                keep_unsupported=keep_unsupported,
            )
        ]
        for r in results:
            if not r["ok"]:
                r["error"] = c.t(r["error"])
        rows = [
            [
                r["source"],
                r["device"] or "-",
                r["vendor"] or "-",
                r["version"] or "-",
                (r["profile"] or "-")
                + (f" ({r['profile_source']})" if r.get("profile_source") not in (None, "", "auto") else ""),
                str(r["version_id"] or "") if r["ok"] else r["error"],
            ]
            for r in results
        ]
        emit(
            c,
            {"files": results},
            output.table(
                rows,
                [
                    c.t("import.file"),
                    c.t("import.device"),
                    c.t("import.vendor"),
                    c.t("import.version"),
                    c.t("import.profile"),
                    c.t("import.version_id"),
                ],
            ),
        )
        if not any(r["ok"] for r in results):
            raise typer.Exit(output.EXIT_ERROR)

    @config_app.command("list", help="已导入的设备与配置版本 / list devices")
    def cmd_list(ctx: typer.Context) -> None:
        c = output.get(ctx)
        devices = importer.list_devices(require_db(c))
        rows = [
            [d["name"], d["vendor"], d["sw_version"] or "-", d["profile"] or "-", str(d["versions"])] for d in devices
        ]
        text = (
            output.table(
                rows,
                [
                    c.t("import.device"),
                    c.t("import.vendor"),
                    c.t("import.version"),
                    c.t("import.profile"),
                    c.t("import.versions"),
                ],
            )
            if devices
            else c.t("import.empty")
        )
        emit(c, {"devices": devices}, text)
