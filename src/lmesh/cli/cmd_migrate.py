"""割接迁移命令：lmesh migrate <旧配置|设备> --to <Profile> [--interface-map 文件] [--target-config 文件] [-o 目录]。"""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from lmesh.cli import output
from lmesh.cli.cmd_graph import _graph_for
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import compare, importer, migration, translate

_SHOW = 30  # 文本输出每一类最多列出的条数


def _msg(c: Ctx, item: dict[str, Any]) -> str:
    try:
        return c.t(item["key"], **item["params"])
    except (KeyError, IndexError, ValueError):  # 文案缺参数时退回结构化写法
        return f"{item.get('kind') or item['key']} {item.get('node') or ''}"


def _line(c: Ctx, item: dict[str, Any]) -> str:
    at = f"  @{','.join(map(str, item['lines'][:3]))}" if item.get("lines") else ""
    return _msg(c, item) + at


def map_table(c: Ctx, r: dict[str, Any]) -> str:
    rows = [
        [
            m["source"],
            m["target"],
            m["kind"],
            c.t(f"migrate.basis.{m['basis']}"),
            f"{m['confidence']:.2f}",
            str(len(m["subinterfaces"])) if m["subinterfaces"] else "",
        ]
        for m in r["interface_map"]
    ]
    rows += [
        [u["source"], "-", u["kind"], c.t(f"migrate.reason.{u['reason']}"), "", str(len(u["subinterfaces"]) or "")]
        for u in r["unmapped"]
    ]
    head = [c.t(f"migrate.col.{k}") for k in ("source", "target", "kind", "basis", "confidence", "subs")]
    return output.table(rows, head)


def steps_text(c: Ctx, r: dict[str, Any]) -> str:
    out: list[str] = []
    for s in r["steps"]:
        dev = c.t(f"migrate.device.{s['device']}")
        out.append(f"{s['no']}. [{c.t('migrate.phase.' + s['phase'])}] [{dev}] {_msg(c, s)}")
        out += [f"    {cmd}" for cmd in s["commands"]]
    return "\n".join(out)


def text_report(c: Ctx, r: dict[str, Any]) -> str:
    st = r["stats"]
    lines = [
        c.t(
            "migrate.summary",
            src=r["source"]["profile"],
            dst=r["target"]["profile"],
            mapped=st["mapped"],
            unmapped=st["unmapped"],
            warnings=st["warnings"],
            lines=st["lines"],
        ),
        c.t(
            "migrate.inventory." + str(r["inventory"]["source"]),
            model=r["inventory"].get("model") or "-",
            ports=r["inventory"].get("ports") or 0,
        ),
    ]
    if r.get("merge"):
        lines.append(c.t("migrate.merge", **r["merge"]))
    v = r["verify"]
    if v.get("checked"):
        lines.append(
            c.t("migrate.verify_ok") if not v["unexplained"] else c.t("migrate.verify_bad", n=v["unexplained"])
        )
    if r["script"].get("available"):
        lines.append(c.t("migrate.script_ok", n=len(r["script"].get("items") or [])))
    else:
        lines.append(c.t("migrate.script_unavailable"))
    lines += ["", map_table(c, r)]
    for title, items in (
        ("migrate.section.warnings", r["warnings"]),
        ("migrate.section.unsupported", r["unsupported"]),
    ):
        if not items:
            continue
        lines.append(f"[{c.t(title)}] {len(items)}")
        lines += [f"  {_line(c, it)}" for it in items[:_SHOW]]
        if len(items) > _SHOW:
            lines.append("  " + c.t("translate.more", n=len(items) - _SHOW))
    return "\n".join(lines)


def warnings_csv(c: Ctx, r: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["category", "level", "kind", "node", "lines", "message"])
    for cat, items in (("warning", r["warnings"]), ("unsupported", r["unsupported"]), ("default", r["defaults"])):
        for it in items:
            w.writerow(
                [
                    cat,
                    it["params"].get("level") or ("info" if cat == "default" else "warning"),
                    it["kind"],
                    it.get("node") or "",
                    " ".join(map(str, it.get("lines") or [])),
                    _msg(c, it),
                ]
            )
    return buf.getvalue()


def write_outputs(c: Ctx, r: dict[str, Any], out: Path) -> list[str]:
    """输出目录：新配置、增量配置（有新设备现有配置时）、映射表 CSV、告警清单、步骤清单、完整结果 JSON。"""
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "new-config.cfg": r["text"].rstrip("\n") + "\n",
        "interface-map.csv": migration.map_csv(r),
        "warnings.csv": warnings_csv(c, r),
        "steps.txt": steps_text(c, r) + "\n",
        "migration.json": json.dumps(r, ensure_ascii=False, indent=2, default=str) + "\n",
    }
    if r["target"].get("existing"):
        files["delta.cfg"] = r["delta"].rstrip("\n") + "\n"
    if r["script"].get("available"):
        for k, name in (("script", "script.txt"), ("rollback", "rollback.txt")):
            v = r["script"].get(k)
            if v:
                files[name] = (v if isinstance(v, str) else "\n".join(map(str, v))).rstrip("\n") + "\n"
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8", newline="\n")
    return sorted(files)


def register(app: typer.Typer) -> None:
    @app.command(
        "migrate",
        help="割接迁移：翻译 + 接口映射（自动建议），生成新设备配置、告警、校验与割接步骤 / migrate a device",
    )
    def cmd_migrate(
        ctx: typer.Context,
        target: Annotated[str, typer.Argument(help="旧设备的配置文件，或已导入的设备名")],
        to: Annotated[str, typer.Option("--to", help="新设备的目标 Profile，例如 cisco-iosxe-asr920-17.15")],
        interface_map: Annotated[
            Path | None,
            typer.Option(
                "--interface-map",
                help="接口映射表（可以只给部分，其余自动建议；CSV / JSON / YAML / 两列文本；- 表示不迁移）",
            ),
        ] = None,
        target_config: Annotated[
            Path | None,
            typer.Option("--target-config", help="新设备现有配置（出厂 / 已配置的管理口）：只生成需要新增的部分"),
        ] = None,
        model: Annotated[str | None, typer.Option("--model", help="新设备型号（按知识库的端口清单分配接口）")] = None,
        on_conflict: Annotated[
            str, typer.Option("--on-conflict", help="现有配置与迁移内容冲突时：migrate 以旧设备为准，keep 保留现有")
        ] = "migrate",
        out: Annotated[
            Path | None, typer.Option("-o", "--out", help="输出目录：新配置、映射表 CSV、告警清单、步骤清单")
        ] = None,
        profile: Annotated[str | None, typer.Option(help="旧配置的 Profile（不给时自动识别）")] = None,
        suggest_only: Annotated[bool, typer.Option("--suggest-only", help="只给接口映射建议")] = False,
        no_verify: Annotated[bool, typer.Option("--no-verify", help="不做新配置的再解析校验")] = False,
        rules: Annotated[
            str | None, typer.Option("--rules", help="翻译规则集（编号或 YAML 文件）：名称映射、命名规范、端口映射")
        ] = None,
    ) -> None:
        from lmesh.cli.cmd_naming import load_rules, report_text
        from lmesh.core import naming

        c = output.get(ctx)
        g, kb = _graph_for(c, target, profile)
        rs = load_rules(c, rules, kb)
        src = str(g.graph.get("profile"))
        try:
            ifmap = migration.load_map_file(interface_map) if interface_map else None
            tg = None
            if target_config is not None:
                if not target_config.exists():
                    fail(c, output.EXIT_NOT_FOUND, c.t("migrate.target_missing", path=str(target_config)))
                tg = migration.target_graph_from_text(importer.decode(target_config.read_bytes()), kb, to)
            if suggest_only:
                if rs is not None:  # 端口映射规则：用户给出的映射优先
                    ifmap = {**naming.port_map(g, rs), **(ifmap or {})}
                s = migration.suggest_map(g, kb, src, to, ifmap, tg, model)
                emit(
                    c,
                    s,
                    map_table(c, {**s, "interface_map": s["map"]})
                    + "".join(f"\n  {_line(c, w)}" for w in s["warnings"]),
                )
                return
            r = migration.migrate(g, kb, src, to, ifmap, tg, model, on_conflict, verify=not no_verify, rules=rs)
        except compare.CompareError as e:
            fail(c, output.EXIT_NOT_FOUND if e.kind == "not_found" else output.EXIT_USAGE, c.t(e.key, **e.fmt))
        except (migration.MigrateError, translate.TranslateError) as e:
            fail(c, output.EXIT_USAGE, c.t(e.key, **e.fmt))
        report = text_report(c, r)
        if r.get("naming") is not None:
            report += "\n" + report_text(c, r["naming"])
        if out is not None:
            files = write_outputs(c, r, out)
            emit(
                c,
                {**r, "out": str(out), "files": files},
                report + "\n\n" + steps_text(c, r) + "\n" + c.t("migrate.written", path=out, files=", ".join(files)),
            )
        else:
            emit(c, r, r["text"])
            if c.output == "text" and not c.quiet:
                sys.stderr.write(report + "\n\n" + steps_text(c, r) + "\n")  # 新配置单独占 stdout，便于重定向
        if r["verify"].get("checked") and r["verify"]["unexplained"]:
            raise typer.Exit(output.EXIT_ERROR)
