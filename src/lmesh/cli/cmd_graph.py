"""配置图命令：lmesh graph show、lmesh render、lmesh roundtrip。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from lmesh.cli import output
from lmesh.cli.cmd_configs import require_db
from lmesh.cli.cmd_kb import _root
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import analysis, config, graphstore, importer, roundtrip
from lmesh.core import graph as graphmod
from lmesh.core.kb import KnowledgeBase
from lmesh.core.renderer import render_roundtrip


def _kb(c: Ctx) -> tuple[KnowledgeBase, Path]:
    from lmesh import paths

    root = _root(c) if config.is_configured() else paths.builtin_knowledge_dir()
    return analysis.load_kb(root), root


def _graph_for(c: Ctx, target: str, profile: str | None):  # type: ignore[no-untyped-def]
    """target 是配置文件路径，或已导入的设备名。"""
    kb, _ = _kb(c)
    p = Path(target)
    if p.exists():
        try:
            res = analysis.parse_text(importer.decode(p.read_bytes()), kb, profile)
        except analysis.AnalysisError as e:
            fail(c, output.EXIT_USAGE, c.t(str(e), profile=profile or ""))
        return graphmod.build(res.parsed, kb, res.profile, p.stem), kb
    db = require_db(c)
    dev = next((d for d in importer.list_devices(db) if d["name"] == target), None)
    if dev is None or not dev["latest_version_id"]:
        fail(c, output.EXIT_NOT_FOUND, c.t("graph.target_not_found", target=target))
    g, _, _ = graphstore.build_for_version(db, dev["latest_version_id"], kb)
    return g, kb


def register(app: typer.Typer) -> None:
    graph_app = typer.Typer(no_args_is_help=True, help="配置图 / configuration graph")
    app.add_typer(graph_app, name="graph")

    @graph_app.command("show", help="显示设备配置图：节点、依赖边、隐藏的默认节点 / show the graph")
    def graph_show(
        ctx: typer.Context,
        target: Annotated[str, typer.Argument(help="配置文件，或已导入的设备名")],
        domain: Annotated[str | None, typer.Option(help="只看一个功能域（Schema 前缀，如 bgp、interface）")] = None,
        profile: Annotated[str | None, typer.Option()] = None,
    ) -> None:
        c = output.get(ctx)
        g, kb = _graph_for(c, target, profile)
        roots = [n.id for n in kb.nodes.values() if domain and n.domain == domain and not n.parent]
        data = graphmod.to_json(g, domain, include_raw=False, roots=roots or None)
        s = data["summary"]
        lines = [
            c.t(
                "graph.summary",
                device=data["device"],
                profile=data["profile"],
                nodes=s["nodes"],
                edges=s["edges"],
                defaults=s["attr_origins"].get("default", 0),
                dangling=s["dangling"],
            )
        ]
        shown = 0
        for n in data["nodes"]:
            if n["kind"] in ("object", "attr", "ext") and shown < 60:
                mark = {"default": "·", "derived": "~"}.get(n.get("origin", ""), " ")
                val = "" if n.get("value") is None else f" = {n['value']}"
                lines.append(f" {mark} {n['id']}{val}")
                shown += 1
        for d in data["dangling"][:20]:
            lines.append("  ! " + c.t("graph.dangling", node=d["node"], value=d["value"]))
        emit(c, data, "\n".join(lines))

    @app.command("render", help="把配置图渲染回配置文本（往返模式）/ render the graph back to text")
    def cmd_render(
        ctx: typer.Context,
        target: Annotated[str, typer.Argument(help="配置文件，或已导入的设备名")],
        profile: Annotated[str | None, typer.Option()] = None,
    ) -> None:
        c = output.get(ctx)
        g, kb = _graph_for(c, target, profile)
        text = render_roundtrip(g, kb)
        emit(c, {"text": text, "profile": g.graph.get("profile")}, text)

    @app.command("roundtrip", help="往返测试：配置 → 图 → 配置逐字比较；--samples 跑全部样本 / round-trip test")
    def cmd_roundtrip(
        ctx: typer.Context,
        file: Annotated[Path | None, typer.Argument(help="配置文件；省略时用 --samples")] = None,
        samples: Annotated[
            bool, typer.Option("--samples", help="知识库中的全部样本（门槛：逐字一致且没有未识别行）")
        ] = False,
        profile: Annotated[str | None, typer.Option()] = None,
    ) -> None:
        c = output.get(ctx)
        kb, root = _kb(c)
        if samples or file is None:
            res = roundtrip.regression(root, kb=kb)
            rows = [
                [
                    r["file"],
                    "gate" if r["gate"] else "-",
                    c.t("roundtrip.ok") if r.get("ok") else c.t("roundtrip.diff"),
                    str(r.get("unknown", "-")),
                    str(r.get("graph", {}).get("nodes", "-")),
                ]
                for r in res["results"]
            ]
            emit(
                c,
                res,
                output.table(
                    rows,
                    [
                        c.t("roundtrip.sample"),
                        c.t("roundtrip.gate"),
                        c.t("roundtrip.result"),
                        c.t("roundtrip.unknown"),
                        c.t("roundtrip.nodes"),
                    ],
                )
                + "\n"
                + c.t("roundtrip.summary", n=res["samples"], failed=res["failed"]),
            )
            if res["failed"]:
                raise typer.Exit(output.EXIT_ERROR)
            return
        if not file.exists():
            fail(c, output.EXIT_NOT_FOUND, c.t("common.not_found", path=file))
        try:
            r = roundtrip.run(importer.decode(file.read_bytes()), kb, profile, file.stem)
        except analysis.AnalysisError as e:
            fail(c, output.EXIT_USAGE, c.t(str(e), profile=profile or ""))
        text = c.t(
            "roundtrip.one",
            result=c.t("roundtrip.ok") if r["ok"] else c.t("roundtrip.diff"),
            lines=r["lines"],
            unknown=r["unknown"],
            nodes=r["graph"]["nodes"],
        )
        for d in r["diffs"][:10]:
            text += (
                f"\n  @{d['line']}\n    - "
                + "\n    - ".join(d["original"])
                + "\n    + "
                + "\n    + ".join(d["rendered"])
            )
        emit(c, r, text)
        if not r["ok"]:
            raise typer.Exit(output.EXIT_ERROR)
