"""审计表格导出命令：lmesh export table、lmesh export presets。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from lmesh.cli import output
from lmesh.cli.cmd_configs import require_db
from lmesh.cli.cmd_graph import _kb
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import analysis, export_tables, gquery, history, importer, topology
from lmesh.core.kb import KnowledgeBase

_SUFFIXES = (".cfg", ".txt", ".conf", ".config", ".log")


def load_targets(
    c: Ctx, kb: KnowledgeBase, targets: list[str], all_devices: bool, profile: str | None, need: bool = True
) -> list[topology.Device]:
    """目标：配置文件、目录或已导入的设备名 / 编号（最新快照）；--all 表示全部已导入设备。"""
    if not targets and not all_devices:
        if not need:
            return []
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
        fail(
            c,
            output.EXIT_USAGE,
            c.t("topology.bad_config", source=getattr(e, "source", ""), error=c.t(str(e), profile="")),
        )
    if names or all_devices:
        db = require_db(c)
        found, missing = history.devices_from_db(db, kb, names) if names else ([], [])
        if missing:
            fail(c, output.EXIT_NOT_FOUND, c.t("graph.target_not_found", target=", ".join(missing)))
        if all_devices:
            rest, _ = history.devices_from_db(db, kb, None)
            found += [d for d in rest if d.device_id not in {x.device_id for x in found}]
        devices += found
    if not devices and need:
        fail(c, output.EXIT_NOT_FOUND, c.t("topology.no_devices"))
    for d, n in zip(devices, topology.unique_names([d.name for d in devices]), strict=True):
        d.name = n
    return devices


def _fail(c: Ctx, e: export_tables.ExportError | gquery.QueryError) -> NoReturn:
    kind = getattr(e, "kind", "param")
    code = {"not_found": output.EXIT_NOT_FOUND, "config": output.EXIT_CONFIG}.get(kind, output.EXIT_USAGE)
    fail(c, code, c.t(e.key, **e.fmt))


def _split(v: str | None) -> list[str] | None:
    return [x.strip() for x in v.split(",") if x.strip()] if v else None


def _filters(c: Ctx, items: list[str] | None) -> list[dict[str, str]]:
    """--filter 'description ~ ^TO-'：字段、运算符、取值（EXISTS / NOT EXISTS 不要取值）。"""
    out = []
    for f in items or []:
        try:
            q = gquery.parse(f"FIND x WHERE {f}")
        except gquery.QueryError as e:
            _fail(c, e)
        out += [cond.as_dict() for cond in q.where]
    return out


def register(app: typer.Typer) -> None:
    exp = typer.Typer(no_args_is_help=True, help="审计表格导出：IP 地址表、VLAN / 桥域表、BGP 邻居表等 / audit tables")
    app.add_typer(exp, name="export")

    @exp.command("presets", help="预置模板：编号、对象类型、列与筛选条件")
    def cmd_presets(
        ctx: typer.Context, style: Annotated[str, typer.Option(help="显示风格 huawei | cisco（表头叫法）")] = "huawei"
    ) -> None:
        c = output.get(ctx)
        kb, root = _kb(c)
        ps = export_tables.presets(root, kb, style)
        rows = [
            [p["id"], ", ".join(p["aliases"]), p["object"], p["title"].get(c.lang, ""), str(len(p["columns"]))]
            for p in ps
        ]
        head = [
            c.t("export.col.preset"),
            c.t("export.col.aliases"),
            c.t("export.col.object"),
            c.t("export.col.title"),
            c.t("export.col.columns"),
        ]
        emit(c, {"presets": ps}, output.table(rows, head))

    @exp.command("table", help="按模板或对象类型导出表格：CSV（UTF-8 BOM）/ XLSX / JSON；敏感字段只写已配置 / 未配置")
    def cmd_table(
        ctx: typer.Context,
        targets: Annotated[
            list[str] | None, typer.Argument(help="配置文件、目录或已导入的设备名 / 编号（可多个）")
        ] = None,
        all_devices: Annotated[bool, typer.Option("--all", help="全部已导入设备")] = False,
        preset: Annotated[
            str | None,
            typer.Option(
                "--preset",
                help="预置模板：ip-address / bridge-domain / bgp-peer / interface-description / vrf / static-route（或别名 ip、vlan、bgp、desc、static）",
            ),
        ] = None,
        obj: Annotated[str | None, typer.Option("--object", help="对象类型（Schema 编号，自定义表格时用）")] = None,
        fields: Annotated[
            str | None, typer.Option("--fields", help="列：逗号分隔的 Schema 路径，派生列写 derive:名称")
        ] = None,
        where: Annotated[
            str | None, typer.Option("--where", help="命名筛选条件（逗号分隔）；不给时用模板自带的")
        ] = None,
        flt: Annotated[
            list[str] | None, typer.Option("--filter", help="临时筛选条件，例如 'description ~ ^TO-'（可多次）")
        ] = None,
        no_defaults: Annotated[
            bool, typer.Option("--no-defaults", help="不填 Profile 默认值（只写配置里写了的）")
        ] = False,
        canonical: Annotated[bool, typer.Option("--canonical-names", help="接口名统一写成全称")] = False,
        fmt: Annotated[str, typer.Option("--format", help="csv | xlsx | json")] = "csv",
        sheets: Annotated[
            str, typer.Option("--sheets", help="XLSX：per-device 每台设备一个工作表 | single 全部一张表")
        ] = "per-device",
        table_lang: Annotated[
            str | None, typer.Option("--table-lang", help="表头语言 zh-CN | en | pt-BR（默认跟随 --lang）")
        ] = None,
        style: Annotated[str, typer.Option(help="显示风格 huawei | cisco（表头叫法）")] = "huawei",
        out: Annotated[
            Path | None, typer.Option("-o", "--out", help="输出文件（CSV / XLSX 必填，JSON 不给时写到标准输出）")
        ] = None,
        profile: Annotated[str | None, typer.Option(help="配置文件使用的 Profile（默认自动识别）")] = None,
    ) -> None:
        c = output.get(ctx)
        if fmt not in export_tables.FORMATS:
            fail(c, output.EXIT_USAGE, c.t("export.bad_format", allowed=", ".join(export_tables.FORMATS)))
        if style not in ("huawei", "cisco"):
            fail(c, output.EXIT_USAGE, c.t("change.bad_style"))
        if not preset and not obj:
            fail(c, output.EXIT_USAGE, c.t("export.need_object"))
        if fmt != "json" and out is None:
            fail(c, output.EXIT_USAGE, c.t("export.need_out"))
        lang = table_lang or c.lang
        kb, root = _kb(c)
        devices = load_targets(c, kb, targets or [], all_devices, profile)
        try:
            t = export_tables.build(
                devices,
                kb,
                root,
                preset=preset,
                obj=obj,
                columns=_split(fields),  # type: ignore[arg-type]
                where=_split(where),
                filters=_filters(c, flt),
                defaults=not no_defaults,
                canonical_names=canonical,
                style=style,
            )
            if fmt == "csv":
                _, data = export_tables.to_csv(t, lang)
            elif fmt == "xlsx":
                _, data = export_tables.to_xlsx(t, lang, sheets)
            else:
                data = json.dumps(t, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        except (export_tables.ExportError, gquery.QueryError) as e:
            _fail(c, e)
        s = t["summary"]
        msg = c.t(
            "export.summary", rows=s["rows"], devices=s["devices"], columns=s["columns"], defaults=s["default_cells"]
        )
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            msg += "\n" + c.t("export.written", path=out)
            emit(
                c,
                {**t, "output": str(out)}
                if fmt == "json"
                else {
                    "summary": s,
                    "output": str(out),
                    "format": fmt,
                    "columns": t["columns"],
                    "preset": t["preset"],
                    "object": t["object"],
                },
                msg,
            )
            return
        emit(c, t, data.decode("utf-8"))
