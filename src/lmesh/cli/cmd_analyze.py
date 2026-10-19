"""设备配置分析命令（REQ-034）：lmesh analyze <配置文件 | 设备名>，输出分析摘要与 TCP/IP 分层（--part 选择）。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from lmesh.cli import output
from lmesh.cli.cmd_check import device_ignores, load_overrides, load_rules
from lmesh.cli.cmd_graph import _graph_for, _kb
from lmesh.cli.output import emit, fail
from lmesh.core import compare, config, config_analysis, layers, store

PARTS = ("summary", "layers", "script")


def register(app: typer.Typer) -> None:
    @app.command(
        "analyze",
        help="设备配置分析：功能域对象数、检查发现、未识别行、依赖默认值的关键配置、基线得分、TCP/IP 分层 / analyze a config",
    )
    def cmd_analyze(
        ctx: typer.Context,
        target: Annotated[str, typer.Argument(help="配置文件，或已导入的设备名")],
        part: Annotated[
            list[str] | None, typer.Option("--part", help="summary | layers | script（可多次；默认 summary 与 layers）")
        ] = None,
        profile: Annotated[str | None, typer.Option()] = None,
    ) -> None:
        c = output.get(ctx)
        parts = list(dict.fromkeys(part or ["summary", "layers"]))
        bad = [p for p in parts if p not in PARTS]
        if bad:
            fail(c, output.EXIT_USAGE, c.t("analysis.bad_part", part=", ".join(bad), allowed=", ".join(PARTS)))
        kb, root = _kb(c)
        g, kb = _graph_for(c, target, profile)
        lay = layers.load(root)
        data: dict[str, Any] = {
            "device": g.graph.get("device"),
            "profile": g.graph.get("profile"),
            "kb_version": g.graph.get("kb_version"),
            "parts": parts,
        }
        lines: list[str] = []
        if "summary" in parts:
            rules = load_rules(c, kb, root, None)
            chk = config_analysis.run_check(g, kb, rules, load_overrides(c, root, None), device_ignores(target))
            data["summary"] = s = config_analysis.summary(
                g, kb, lay, check=chk, baseline=config_analysis.run_baseline(g, kb, root), history=_history(target, kb)
            )
            lines += _summary_text(c, s)
        if "layers" in parts:
            data["layers"] = cls = layers.classify(g, kb, lay)
            lines.append(c.t("analysis.layers_head", cross=len(cls["cross"])))
            names = {x["id"]: x.get("name") or {} for x in lay.layers}
            for r in cls["layers"]:
                name = (names.get(r["id"]) or {}).get(c.lang) or r["id"]
                lines.append(f"  {name:<16} {c.t('analysis.layer_row', objects=r['objects'], attrs=r['attrs'])}")
        if "script" in parts:
            data["script"] = config_analysis.script(g, kb, lay)
            lines.append(
                c.t("analysis.script_head", lines=len(data["script"]["lines"]), refs=len(data["script"]["refs"]))
            )
        emit(c, data, "\n".join(lines))


def _history(target: str, kb: Any) -> dict[str, Any] | None:
    """目标是已导入的设备名时，与上一版本比较。"""
    if Path(target).exists() or not config.is_configured():
        return None
    db = config.load().database_url
    store.upgrade(db)
    dev_id = compare.device_id_by_name(db, target)
    if dev_id is None:
        return None
    from lmesh.core import graphstore

    ver = graphstore.latest_version(db, dev_id)
    return config_analysis.history_brief(db, dev_id, ver.id, kb) if ver else None


def _summary_text(c: output.Ctx, s: dict[str, Any]) -> list[str]:
    ln = s["lines"]
    out = [
        c.t("analysis.head", device=s["device"], profile=s["profile"]),
        "  "
        + c.t(
            "analysis.lines",
            total=ln["total"],
            command=ln["command"],
            raw=ln["raw"],
            unknown=ln["unknown"],
            coverage=round(ln["coverage"] * 100, 1),
        ),
        "  " + c.t("analysis.domains") + ", ".join(f"{d['domain']} {d['objects']}" for d in s["domains"]),
    ]
    chk = s.get("check")
    if chk:
        out.append("  " + c.t("analysis.check", total=chk["summary"]["total"], **chk["summary"]["by_severity"]))
    bl = s.get("baseline")
    out.append(
        "  "
        + (
            c.t("analysis.baseline", score="-" if bl["score"] is None else bl["score"], fail=bl["failure_count"])
            if bl
            else c.t("analysis.baseline_na")
        )
    )
    d = s["defaults"]
    out.append("  " + c.t("analysis.defaults", total=d["total"], important=d["key"]))
    for it in d["items"][:10]:
        others = ", ".join(f"{o['profile']}={o['value']}" for o in it["others"])
        out.append(f"    · {it['node']} = {it['value']}  ({others})")
    h = s.get("history")
    if h and h.get("previous"):
        sm = h.get("summary") or {}
        out.append(
            "  "
            + c.t(
                "analysis.history",
                prev=h["previous"]["seq"],
                cur=h["current"]["seq"],
                added=sm.get("added", 0),
                modified=sm.get("modified", 0),
                removed=sm.get("removed", 0),
            )
        )
    elif h:
        out.append("  " + c.t("analysis.history_first"))
    return out
