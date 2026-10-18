"""配置对比命令：lmesh compare A B。A、B 是配置文件，或已导入的设备名（设备名@配置版本编号 取指定版本）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from lmesh.cli import output
from lmesh.cli.cmd_configs import require_db
from lmesh.cli.cmd_graph import _kb
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import compare, importer
from lmesh.core.kb import KnowledgeBase

_MARK = {"added": "+", "removed": "-", "changed": "~", "renamed": "»"}


def _fail(c: Ctx, e: compare.CompareError) -> None:
    code = output.EXIT_NOT_FOUND if e.kind == "not_found" else output.EXIT_USAGE
    fail(c, code, c.t(e.key, **e.fmt))


def _side(c: Ctx, kb: KnowledgeBase, target: str, profile: str | None) -> compare.Side:
    p = Path(target)
    if p.is_file():
        return compare.side_from_text(importer.decode(p.read_bytes()), kb, profile, p.stem)
    db = require_db(c)
    name, version = target, None
    if "@" in target:
        head, _, tail = target.rpartition("@")
        if tail.isdigit():
            name, version = head, int(tail)
    dev_id = compare.device_id_by_name(db, name)
    if dev_id is None:
        raise compare.CompareError("compare.device_not_found", "not_found", target=name)
    if version is not None:
        return compare.side_from_version(db, kb, version, profile, dev_id)
    return compare.side_from_device(db, kb, dev_id, profile)


def _fmt(v: Any) -> str:
    if v is None:
        return "∅"
    if isinstance(v, dict | list):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def text_report(c: Ctx, r: dict[str, Any]) -> str:
    s = r["summary"]
    lines = [
        c.t(
            "compare.header",
            a=r["a"]["label"],
            pa=r["a"]["profile"],
            b=r["b"]["label"],
            pb=r["b"]["profile"],
        )
    ]
    if r["equal"]:
        lines.append(c.t("compare.equal"))
    else:
        lines.append(c.t("compare.summary", total=s["total"], **s["by_kind"]))
    current = None
    for d in r["diffs"]:
        if d["domain"] != current:
            current = d["domain"]
            lines.append(f"[{current}] {s['by_domain'][current]['total']}")
        va = (d["a"] or {}).get("value")
        vb = (d["b"] or {}).get("value")
        if d["kind"] == "changed":
            detail = f": {_fmt(va)} → {_fmt(vb)}"
        elif d["kind"] == "renamed":
            detail = f": {d['from']} → {d['to']}"
        elif d["node_kind"] in ("attr", "ext"):
            detail = f" = {_fmt(va if d['kind'] == 'removed' else vb)}"
        else:
            detail = ""
        side = d["a"] if d["kind"] == "removed" else d["b"]
        at = f"  @{','.join(map(str, side['lines'][:3]))}" if side and side.get("lines") else ""
        lines.append(f"  {_MARK[d['kind']]} {d['node']}{detail}{at}")
    if s.get("default_only"):
        lines.append(c.t("compare.default_only", n=s["default_only"]))
    lines.append(c.t("compare.unknown", a=s["unknown"]["a"], b=s["unknown"]["b"]))
    return "\n".join(lines)


def register(app: typer.Typer) -> None:
    @app.command("compare", help="配置对比：按有效值、改名与语义等价比较两份配置 / compare two configurations")
    def cmd_compare(
        ctx: typer.Context,
        a: Annotated[str, typer.Argument(help="A：配置文件，或设备名（设备名@版本编号）")],
        b: Annotated[str, typer.Argument(help="B：配置文件，或设备名（设备名@版本编号）")],
        domain: Annotated[str | None, typer.Option(help="只看一个功能域，如 bgp、interface")] = None,
        raw: Annotated[bool, typer.Option("--raw", help="同时比较功能域外的原文行（按所属对象）")] = False,
        interface_map: Annotated[
            Path | None, typer.Option("--interface-map", help="接口映射表（A 接口 → B 接口；JSON / YAML / 两列文本）")
        ] = None,
        profile_a: Annotated[str | None, typer.Option("--profile-a", help="A 使用的 Profile")] = None,
        profile_b: Annotated[str | None, typer.Option("--profile-b", help="B 使用的 Profile")] = None,
        rename_threshold: Annotated[
            float, typer.Option("--rename-threshold", help="改名识别的相似度阈值（0–1，默认 1 只认内容完全相同）")
        ] = 1.0,
    ) -> None:
        c = output.get(ctx)
        kb, _ = _kb(c)
        try:
            ifmap = compare.load_interface_map(interface_map) if interface_map else None
            sa = _side(c, kb, a, profile_a)
            sb = _side(c, kb, b, profile_b)
            r = compare.compare(
                sa,
                sb,
                kb,
                domain=domain,
                include_raw=raw,
                interface_map=ifmap,
                rename_threshold=rename_threshold,
            )
        except compare.CompareError as e:
            _fail(c, e)
        emit(c, r, text_report(c, r))
