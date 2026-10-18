"""配置翻译命令：lmesh translate <配置|设备> --to <Profile> [--interface-map 文件] [-o 文件]。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from lmesh.cli import output
from lmesh.cli.cmd_graph import _graph_for
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import compare, translate

_SHOW = 30  # 文本输出每一类最多列出的条数


def _line(c: Ctx, item: dict[str, Any]) -> str:
    at = f"  @{','.join(map(str, item['lines'][:3]))}" if item.get("lines") else ""
    try:
        return c.t(item["key"], **item["params"]) + at
    except (KeyError, IndexError, ValueError):  # 文案缺参数时退回结构化写法
        return f"{item['kind']} {item.get('node') or ''}{at}"


def text_report(c: Ctx, r: dict[str, Any]) -> str:
    st = r["stats"]
    lines = [
        c.t(
            "translate.summary",
            src=r["source"]["profile"],
            dst=r["target"]["profile"],
            **{
                k: st[k]
                for k in (
                    "facts",
                    "rendered",
                    "unsupported",
                    "not_translated",
                    "default_differs",
                    "defaults_omitted",
                    "warnings",
                )
            },
        )
    ]
    v = r["verify"]
    if v.get("checked"):
        lines.append(
            c.t("translate.verify_ok") if not v["unexplained"] else c.t("translate.verify_bad", n=v["unexplained"])
        )
    for title, items in (
        ("translate.section.warnings", r["warnings"]),
        ("translate.section.unsupported", [u for u in r["unsupported"] if u["kind"] == "node"]),
        ("translate.section.not_translated", [u for u in r["unsupported"] if u["kind"] != "node"]),
        ("translate.section.defaults", r["defaults"]),
    ):
        if not items:
            continue
        lines.append(f"[{c.t(title)}] {len(items)}")
        lines += [f"  {_line(c, it)}" for it in items[:_SHOW]]
        if len(items) > _SHOW:
            lines.append("  " + c.t("translate.more", n=len(items) - _SHOW))
    return "\n".join(lines)


def register(app: typer.Typer) -> None:
    @app.command(
        "translate",
        help="配置翻译：按有效值翻译到另一个 Profile，列出默认值差异与不支持的项 / translate a configuration",
    )
    def cmd_translate(
        ctx: typer.Context,
        target: Annotated[str, typer.Argument(help="配置文件，或已导入的设备名")],
        to: Annotated[str, typer.Option("--to", help="目标 Profile，例如 cisco-iosxe-asr920-17.15")],
        interface_map: Annotated[
            Path | None, typer.Option("--interface-map", help="接口映射表（源接口 → 目标接口；JSON / YAML / 两列文本）")
        ] = None,
        out: Annotated[
            Path | None, typer.Option("-o", "--out", help="把译文写到文件（不给时译文写到标准输出）")
        ] = None,
        profile: Annotated[str | None, typer.Option(help="源配置的 Profile（不给时自动识别）")] = None,
        no_verify: Annotated[bool, typer.Option("--no-verify", help="不做译文的再解析校验")] = False,
    ) -> None:
        c = output.get(ctx)
        g, kb = _graph_for(c, target, profile)
        try:
            ifmap = compare.load_interface_map(interface_map) if interface_map else None
            r = translate.translate(g, kb, str(g.graph.get("profile")), to, ifmap, verify=not no_verify)
        except compare.CompareError as e:
            fail(c, output.EXIT_NOT_FOUND if e.kind == "not_found" else output.EXIT_USAGE, c.t(e.key, **e.fmt))
        except translate.TranslateError as e:
            fail(c, output.EXIT_USAGE, c.t(e.key, **e.fmt))
        report = text_report(c, r)
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(r["text"].rstrip("\n") + "\n", encoding="utf-8")
            emit(c, {**r, "out": str(out)}, report + "\n" + c.t("translate.written", path=out))
        else:
            emit(c, r, r["text"])
            if c.output == "text" and not c.quiet:
                sys.stderr.write(report + "\n")  # 译文单独占 stdout，便于重定向
        if r["verify"].get("checked") and r["verify"]["unexplained"]:
            raise typer.Exit(output.EXIT_ERROR)
