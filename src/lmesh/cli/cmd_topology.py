"""拓扑还原与跨设备一致性命令：lmesh topology、lmesh consistency。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from lmesh.cli import output
from lmesh.cli.cmd_check import rule_error
from lmesh.cli.cmd_configs import require_db
from lmesh.cli.cmd_graph import _kb
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import analysis, checks, consistency, importer, topology
from lmesh.core import rules as rulesmod
from lmesh.core.kb import KnowledgeBase

_SUFFIXES = (".cfg", ".txt", ".conf", ".config", ".log")
TARGETS_HELP = "配置文件、目录或已导入的设备名 / 编号（可多个）"


def _bad_config(c: Ctx, e: analysis.AnalysisError) -> NoReturn:
    fail(
        c, output.EXIT_USAGE, c.t("topology.bad_config", source=getattr(e, "source", ""), error=c.t(str(e), profile=""))
    )


def load_devices(
    c: Ctx, kb: KnowledgeBase, targets: list[str], all_devices: bool, profile: str | None
) -> list[topology.Device]:
    """目标：配置文件、目录（其中的 .cfg / .txt 等文件）或已导入的设备名 / 编号；--all 表示全部已导入设备。"""
    if not targets and not all_devices:
        fail(c, output.EXIT_USAGE, c.t("topology.no_targets"))
    items: list[dict[str, str | None]] = []
    names: list[str] = []
    for t in targets:
        p = Path(t)
        if p.is_dir():
            files = sorted(f for f in p.iterdir() if f.is_file() and f.suffix.lower() in _SUFFIXES)
            items += [{"name": f.name, "text": importer.decode(f.read_bytes()), "profile": profile} for f in files]
        elif p.is_file():
            items.append({"name": p.name, "text": importer.decode(p.read_bytes()), "profile": profile})
        else:
            names.append(t)
    try:
        devices = topology.from_texts(items, kb)
    except analysis.AnalysisError as e:
        _bad_config(c, e)
    if names or all_devices:
        db = require_db(c)
        found, missing = topology.from_db(db, kb, names) if names else ([], [])
        if missing:
            fail(c, output.EXIT_NOT_FOUND, c.t("graph.target_not_found", target=", ".join(missing)))
        if all_devices:
            rest, _ = topology.from_db(db, kb, None)
            found += [d for d in rest if d.device_id not in {x.device_id for x in found}]
        devices += found
    if not devices:
        fail(c, output.EXIT_NOT_FOUND, c.t("topology.no_devices"))
    taken = topology.unique_names([d.name for d in devices])
    for d, n in zip(devices, taken, strict=True):
        d.name = n
    return devices


def _link_lines(c: Ctx, links: list[dict]) -> list[str]:  # type: ignore[type-arg]
    out = []
    for lk in links:
        a, b = lk["a"], lk["b"]
        mark = f"  [{c.t('check.severity.' + lk['severity'])} ×{len(lk['issues'])}]" if lk.get("issues") else ""
        out.append(
            f"  {lk['type']:<10} {a['device']} {a.get('interface') or a.get('address') or '-'}"
            f"  ~  {b['device']} {b.get('interface') or b.get('address') or '-'}"
            f"  ({c.t('topology.confidence.' + lk['confidence'])}, {lk['basis']['rule']}){mark}"
        )
    return out


def register(app: typer.Typer) -> None:
    @app.command(
        "topology", help="拓扑还原：同网段接口、BGP 邻居、IGP 邻接、伪线、BFD 推导三层拓扑 / rebuild the topology"
    )
    def cmd_topology(
        ctx: typer.Context,
        targets: Annotated[list[str] | None, typer.Argument(help=TARGETS_HELP)] = None,
        all_devices: Annotated[bool, typer.Option("--all", help="全部已导入的设备（最新配置版本）")] = False,
        profile: Annotated[str | None, typer.Option(help="配置文件统一使用的 Profile（默认自动识别）")] = None,
    ) -> None:
        c = output.get(ctx)
        kb, _ = _kb(c)
        devices = load_devices(c, kb, targets or [], all_devices, profile)
        data = topology.to_json(topology.build(devices, kb))
        s = data["summary"]
        lines = [c.t("topology.summary", devices=s["devices"], links=s["links"], unresolved=s["unresolved"])]
        lines += _link_lines(c, data["links"])
        for u in data["unresolved"]:
            lines.append("  ? " + c.t("topology.unresolved", type=u["type"], device=u["device"], address=u["address"]))
        emit(c, data, "\n".join(lines))

    @app.command(
        "consistency",
        help="跨设备一致性检查：链路两端 MTU / 网段、IGP 参数、BGP 对等、LDP、伪线、BFD；有 error 级发现时退出码 1"
        " / cross-device consistency",
    )
    def cmd_consistency(
        ctx: typer.Context,
        targets: Annotated[list[str] | None, typer.Argument(help=TARGETS_HELP)] = None,
        all_devices: Annotated[bool, typer.Option("--all", help="全部已导入的设备（最新配置版本）")] = False,
        severity: Annotated[str, typer.Option(help="最低级别：error | warning | info")] = "info",
        rules: Annotated[
            Path | None, typer.Option("--rules", help="跨设备规则文件（默认知识库的 rules/cross-device.yaml）")
        ] = None,
        profile: Annotated[str | None, typer.Option(help="配置文件统一使用的 Profile（默认自动识别）")] = None,
    ) -> None:
        c = output.get(ctx)
        if severity not in rulesmod.SEVERITIES:
            fail(c, output.EXIT_USAGE, c.t("check.bad_severity"))
        kb, root = _kb(c)
        if rules is not None and not rules.is_file():
            fail(c, output.EXIT_NOT_FOUND, c.t("common.not_found", path=rules))
        try:
            ruleset = consistency.load(kb, rules or consistency.rules_file(root))
        except rulesmod.RuleError as e:
            rule_error(c, e)
        devices = load_devices(c, kb, targets or [], all_devices, profile)
        res = consistency.check(topology.build(devices, kb), kb, ruleset, severity)
        s = res["summary"]
        lines = [
            c.t(
                "consistency.summary",
                devices=s["topology"]["devices"],
                links=s["topology"]["links"],
                total=s["total"],
                **s["by_severity"],
            )
        ]
        lines += _link_lines(c, [lk for lk in res["links"] if lk["issues"]])
        if not res["findings"]:
            lines.append(c.t("consistency.none"))
        for f in res["findings"]:
            where = " ~ ".join(f"{e['device']} {e['end']}" for e in f["ends"])
            lines.append(f"[{c.t('check.severity.' + f['severity'])}] {f['rule']}  {where}")
            lines.append("    " + checks.render_text(f["message"], c.lang, res["texts"]))
            lines.append("    " + c.t("check.fix") + checks.render_text(f["suggestion"], c.lang, res["texts"]))
        emit(c, res, "\n".join(lines))
        if s["has_errors"]:
            output.err_summary(c, lines[0])
            raise typer.Exit(output.EXIT_ERROR)
