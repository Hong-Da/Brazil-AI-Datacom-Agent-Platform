"""审计表格导出（M5-3）：按设备 / 对象类型 / 字段 / 筛选从配置图生成表格，输出 JSON、CSV（UTF-8 BOM）或 XLSX。

预置模板在知识库 `export/tables.yaml`（运行时知识库没有时用程序自带的）；每个格子都带来源（显式 / 默认 / 派生 /
未配置 / 不支持）、图节点与配置行号。表头三语（中文、English、Português）；格子里的配置取值保持原文。
敏感字段只输出“已配置 / 未配置”。XLSX 用批注标出默认值与不支持的格子，CSV 另加一列“来源”说明哪些格子来自默认值。
"""

from __future__ import annotations

import csv
import io
import ipaddress
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import networkx as nx

from lmesh.core import compare, gquery
from lmesh.core.kb import KnowledgeBase, SchemaNode, read_yaml
from lmesh.core.objtable import Cell, Extractor, TableError, display, field_schema, resolve_type

LANGS = ("zh-CN", "en", "pt-BR")
FORMATS = ("json", "csv", "xlsx")
SHEETS = ("per-device", "single")
TABLES_FILE = Path("export") / "tables.yaml"

# 固定文案（表头之外）：三种语言
TEXTS: dict[str, dict[str, str]] = {
    "zh-CN": {
        "device": "设备",
        "node": "节点",
        "lines": "行号",
        "source": "来源",
        "default": "默认值",
        "unsupported": "Profile 不支持",
        "derived": "派生",
        "configured": "已配置",
        "not_configured": "未配置",
        "yes": "是",
        "no": "否",
        "about": "说明",
        "generated": "生成时间",
        "kb_version": "知识库版本",
        "object": "对象类型",
        "filters": "筛选条件",
        "columns": "列",
        "field": "Schema 路径",
        "version": "配置版本",
        "profile": "Profile",
        "rows": "行数",
        "notes": "说明",
        "note_config": "只含配置，不含运行状态（BGP 会话是否建立、接口 up / down 不在表里）。",
        "note_secret": "密码、团体字等敏感字段只写“已配置 / 未配置”，从不导出取值。",
        "note_default": "斜体灰字并带批注的格子来自 Profile 默认值（配置里没有写）。",
        "note_default_csv": "“来源”列列出这一行中来自 Profile 默认值、或 Profile 不支持的格子。",
        "comment_default": "默认值（Profile {profile}），配置中没有这一行",
        "comment_unsupported": "Profile {profile} 不支持这个字段",
        "table": "表格",
    },
    "en": {
        "device": "Device",
        "node": "Node",
        "lines": "Lines",
        "source": "Source",
        "default": "default",
        "unsupported": "not supported by the Profile",
        "derived": "derived",
        "configured": "Configured",
        "not_configured": "Not configured",
        "yes": "Yes",
        "no": "No",
        "about": "About",
        "generated": "Generated",
        "kb_version": "KB version",
        "object": "Object type",
        "filters": "Filters",
        "columns": "Columns",
        "field": "Schema path",
        "version": "Config version",
        "profile": "Profile",
        "rows": "Rows",
        "notes": "Notes",
        "note_config": "Configuration only, no runtime state (BGP session state, interface up / down are not included).",
        "note_secret": "Passwords, communities and other secrets export only as “Configured / Not configured”, never the value.",
        "note_default": "Grey italic cells with a comment come from the Profile default (not written in the config).",
        "note_default_csv": "The “Source” column lists the cells of the row that come from a Profile default or are not supported by the Profile.",
        "comment_default": "Default value (Profile {profile}); not written in the config",
        "comment_unsupported": "Profile {profile} does not support this field",
        "table": "Table",
    },
    "pt-BR": {
        "device": "Dispositivo",
        "node": "Nó",
        "lines": "Linhas",
        "source": "Origem",
        "default": "padrão",
        "unsupported": "não suportado pelo Profile",
        "derived": "derivado",
        "configured": "Configurada",
        "not_configured": "Não configurada",
        "yes": "Sim",
        "no": "Não",
        "about": "Sobre",
        "generated": "Gerado em",
        "kb_version": "Versão da base",
        "object": "Tipo de objeto",
        "filters": "Filtros",
        "columns": "Colunas",
        "field": "Caminho no Schema",
        "version": "Versão da configuração",
        "profile": "Profile",
        "rows": "Linhas",
        "notes": "Observações",
        "note_config": "Só configuração, sem estado operacional (estado de sessão BGP e up / down de interfaces não entram).",
        "note_secret": "Senhas, comunidades e outros segredos saem só como “Configurada / Não configurada”, nunca o valor.",
        "note_default": "Células em cinza itálico com comentário vêm do padrão do Profile (não escritas na configuração).",
        "note_default_csv": "A coluna “Origem” lista as células da linha que vêm do padrão do Profile ou que o Profile não suporta.",
        "comment_default": "Valor padrão (Profile {profile}); não escrito na configuração",
        "comment_unsupported": "O Profile {profile} não suporta este campo",
        "table": "Tabela",
    },
}


class ExportError(ValueError):
    def __init__(self, key: str, kind: str = "param", **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.fmt = key, kind, fmt


# ---------------------------------------------------------------- 模板


def tables_file(kb_root: Path) -> Path:
    f = Path(kb_root) / TABLES_FILE
    if not f.exists():
        from lmesh import paths

        f = paths.builtin_knowledge_dir() / TABLES_FILE
    return f


def load_spec(kb_root: Path) -> dict[str, Any]:
    f = tables_file(kb_root)
    data = (read_yaml(f) or {}) if f.exists() else {}
    if not isinstance(data, dict):
        raise ExportError("export.bad_tables_file", "config", file=str(f))
    return data


def _label(spec: Any, style: str) -> dict[str, str]:
    """{zh-CN, en, pt-BR} 或 {huawei: {…}, cisco: {…}} → 三语文案。"""
    if isinstance(spec, dict) and ("huawei" in spec or "cisco" in spec):
        spec = spec.get(style) or spec.get("huawei") or spec.get("cisco")
    if isinstance(spec, str):
        return dict.fromkeys(LANGS, spec)
    if isinstance(spec, dict):
        base = str(spec.get("en") or spec.get("zh-CN") or next(iter(spec.values()), ""))
        return {lg: str(spec.get(lg) or base) for lg in LANGS}
    return {}


def presets(kb_root: Path, kb: KnowledgeBase, style: str = "huawei") -> list[dict[str, Any]]:
    """预置模板列表（列、筛选条件都已展开成三语文案）。"""
    spec = load_spec(kb_root)
    out = []
    for pid, p in (spec.get("presets") or {}).items():
        obj = str(p.get("object") or "")
        filters = _filters(spec, obj, style)
        out.append(
            {
                "id": pid,
                "aliases": list(p.get("aliases") or []),
                "object": obj,
                "title": _label(p.get("title"), style),
                "description": _label(p.get("description"), style),
                "columns": [_column(kb, obj, c, style, spec) for c in p.get("columns") or [] if obj in kb.nodes],
                "where": list(p.get("where") or []),
                "filters": [{"id": k, "label": v["label"], **v["cond"].as_dict()} for k, v in filters.items()],
                "available": obj in kb.nodes,
            }
        )
    return out


def _filters(spec: dict[str, Any], obj: str, style: str) -> dict[str, dict[str, Any]]:
    out = {}
    for fid, f in ((spec.get("filters") or {}).get(obj) or {}).items():
        op = str(f.get("op") or "=")
        out[str(fid)] = {
            "cond": gquery.Cond(str(f["field"]), op, f.get("value")),
            "label": _label(f.get("label"), style),
        }
    return out


def find_preset(spec: dict[str, Any], name: str) -> tuple[str, dict[str, Any]]:
    ps = spec.get("presets") or {}
    for pid, p in ps.items():
        if name == pid or name in (p.get("aliases") or []):
            return str(pid), p
    raise ExportError("export.bad_preset", "not_found", preset=name, presets=", ".join(ps))


# ---------------------------------------------------------------- 派生列


@dataclass
class Ctx:
    g: nx.MultiDiGraph
    kb: KnowledgeBase
    ex: Extractor
    node: str
    obj: SchemaNode
    canonical: bool = False


def _mask(c: Ctx) -> Cell:
    cell = c.ex.cell(c.node, c.obj, "ipv4.prefix_length")
    if cell.origin in ("none", "unsupported"):
        return Cell(None, cell.origin)
    vals = cell.value if isinstance(cell.value, list) else [cell.value]
    masks = []
    for v in vals:
        try:
            masks.append(str(ipaddress.IPv4Network(f"0.0.0.0/{int(v)}").netmask))
        except (TypeError, ValueError):
            masks.append("")
    return Cell(masks[0] if len(masks) == 1 else masks, "derived", cell.nodes, cell.lines)


def _instance(c: Ctx) -> str | None:
    p = c.ex.ix.parent.get(c.node)
    while p is not None and c.g.nodes[p].get("schema") != "bgp.instance":
        p = c.ex.ix.parent.get(p)
    return p


def _peer_group_node(c: Ctx) -> str | None:
    grp = c.ex.cell(c.node, c.obj, "group")
    inst = _instance(c)
    if grp.origin == "none" or inst is None:
        return None
    for n in c.ex.ix.child(inst, "bgp.peer_group"):
        if str(c.g.nodes[n].get("key")) == str(grp.value):
            return n
    return None


def _peer_remote_as(c: Ctx) -> Cell:
    own = c.ex.cell(c.node, c.obj, "remote_as")
    if own.origin not in ("none", "unsupported"):
        return own
    gn = _peer_group_node(c)
    if gn is not None and "bgp.peer_group" in c.kb.nodes:
        gc = c.ex.cell(gn, c.kb.nodes["bgp.peer_group"], "remote_as")
        if gc.origin not in ("none", "unsupported"):
            return Cell(gc.value, "derived", gc.nodes, gc.lines)
        gt = c.ex.cell(gn, c.kb.nodes["bgp.peer_group"], "type") if "bgp.peer_group.type" in c.kb.nodes else Cell()
        inst = _instance(c)
        if str(gt.value).lower() in ("ibgp", "internal") and inst is not None:
            return Cell(c.g.nodes[inst].get("key"), "derived", [inst, *gt.nodes], gt.lines)
    return own


def _peer_type(c: Ctx) -> Cell:
    ras = _peer_remote_as(c)
    inst = _instance(c)
    if ras.origin in ("none", "unsupported") or inst is None:
        return Cell(None, "none")
    local = str(c.g.nodes[inst].get("key"))
    return Cell("iBGP" if str(ras.value) == local else "eBGP", "derived", [*ras.nodes, inst], ras.lines)


def _af_peers(c: Ctx) -> list[tuple[str, str]]:
    """同一 BGP 实例下、键等于该对等体地址的地址族对等体：(地址族节点, 地址族对等体节点)。"""
    inst = _instance(c)
    if inst is None:
        return []
    addr = str(c.g.nodes[c.node].get("key"))
    out = []
    for af in c.ex.ix.child(inst, "bgp.af"):
        for ap in c.ex.ix.child(af, "bgp.af.peer"):
            if str(c.g.nodes[ap].get("key")) == addr:
                out.append((af, ap))
    return out


def _af_name(c: Ctx, af: str) -> str:
    key = c.g.nodes[af].get("key")
    if isinstance(key, dict):
        afi, vrf = str(key.get("afi") or ""), str(key.get("vrf") or "")
        return f"{afi} vrf {vrf}" if vrf else afi
    return display(key)


def _peer_afs(c: Ctx) -> Cell:
    pairs = _af_peers(c)
    if not pairs:
        return Cell(None, "none")
    names: list[str] = []
    nodes: list[str] = []
    lines: set[int] = set()
    for af, ap in pairs:
        en = c.ex.cell(ap, c.kb.nodes["bgp.af.peer"], "enabled") if "bgp.af.peer.enabled" in c.kb.nodes else Cell()
        if en.origin != "none" and en.value is False:
            continue
        names.append(_af_name(c, af))
        nodes.append(ap)
        lines.update(c.g.nodes[ap].get("lines") or [])
    if not names:
        return Cell(None, "none")
    return Cell(names[0] if len(names) == 1 else names, "derived", nodes, sorted(lines))


def _peer_policy(attr: str) -> Callable[[Ctx], Cell]:
    def run(c: Ctx) -> Cell:
        vals: list[str] = []
        nodes: list[str] = []
        lines: set[int] = set()
        pairs = _af_peers(c)
        for af, ap in pairs:
            if f"bgp.af.peer.{attr}" not in c.kb.nodes:
                continue
            cell = c.ex.cell(ap, c.kb.nodes["bgp.af.peer"], attr, with_defaults=False)
            if cell.origin in ("none", "unsupported"):
                continue
            vals.append(display(cell.value) if len(pairs) == 1 else f"{_af_name(c, af)}: {display(cell.value)}")
            nodes += cell.nodes
            lines.update(cell.lines)
        if not vals:
            return Cell(None, "none")
        return Cell(vals[0] if len(vals) == 1 else vals, "explicit", nodes, sorted(lines))

    return run


def _vrf_rt(direction: str) -> Callable[[Ctx], Cell]:
    def run(c: Ctx) -> Cell:
        vals: list[str] = []
        nodes: list[str] = []
        lines: set[int] = set()
        for af in c.ex.ix.child(c.node, "vrf.instance.af"):
            for rt in c.ex.ix.child(af, "vrf.instance.af.rt"):
                key = c.g.nodes[rt].get("key") or {}
                d = str(key.get("direction") or "") if isinstance(key, dict) else ""
                if d in (direction, "both"):
                    v = str(key.get("value") or "")
                    if v not in vals:
                        vals.append(v)
                    nodes.append(rt)
                    lines.update(c.g.nodes[rt].get("lines") or [])
        if not vals:
            return Cell(None, "none")
        return Cell(vals[0] if len(vals) == 1 else vals, "explicit", nodes, sorted(lines))

    return run


def _vrf_interfaces(c: Ctx) -> Cell:
    name = str(c.g.nodes[c.node].get("key"))
    nodes = []
    for itf in c.ex.ix.objects("interface"):
        for v in c.ex.ix.child(itf, "interface.vrf"):
            if str(c.g.nodes[v].get("value")) == name:
                nodes.append(itf)
    return Cell(len(nodes), "derived", nodes, [])


def _bd_members(c: Ctx) -> Cell:
    bd = str(c.g.nodes[c.node].get("key"))
    vals: list[str] = []
    nodes: list[str] = []
    lines: set[int] = set()
    for m in c.ex.ix.child(c.node, "bridge_domain.member"):
        key = c.g.nodes[m].get("key") or {}
        itf = key.get("interface") if isinstance(key, dict) else key
        inst = key.get("instance") if isinstance(key, dict) else ""
        vals.append(f"{_ifname(c, itf)} · {inst}" if inst else _ifname(c, itf))
        nodes.append(m)
        lines.update(c.g.nodes[m].get("lines") or [])
    for itf in c.ex.ix.objects("interface"):
        for acc in c.ex.ix.child(itf, "interface.access"):
            for b in c.ex.ix.child(acc, "interface.access.bridge_domain"):
                if str(c.g.nodes[b].get("value")) != bd:
                    continue
                acc_key = str(c.g.nodes[acc].get("key") or "")
                vlan = c.ex.cell(acc, c.kb.nodes["interface.access"], "vlan", with_defaults=False)
                text = _ifname(c, c.g.nodes[itf].get("key"))
                if acc_key and acc_key != "_":
                    text += f" · {acc_key}"
                if vlan.origin not in ("none", "unsupported"):
                    text += f" (dot1q {display(vlan.value)})"
                if text not in vals:
                    vals.append(text)
                nodes.append(acc)
                lines.update(c.g.nodes[acc].get("lines") or [])
    if not vals:
        return Cell(None, "none")
    return Cell(vals[0] if len(vals) == 1 else vals, "derived", nodes, sorted(lines))


def _bd_l3(c: Ctx) -> Cell:
    bd = str(c.g.nodes[c.node].get("key"))
    for itf in c.ex.ix.objects("interface"):
        name = str(c.g.nodes[itf].get("key") or "")
        low = name.lower()
        if low in (f"vbdif{bd}", f"bdi{bd}"):
            return Cell(_ifname(c, name), "derived", [itf], list(c.g.nodes[itf].get("lines") or []))
    return Cell(None, "none")


def _ifname(c: Ctx, name: Any) -> str:
    s = str(name or "")
    return compare.interface_name(s) if c.canonical else s


DERIVES: dict[str, tuple[str, Callable[[Ctx], Cell]]] = {
    "mask": ("interface", _mask),
    "peer_remote_as": ("bgp.peer", _peer_remote_as),
    "peer_type": ("bgp.peer", _peer_type),
    "peer_afs": ("bgp.peer", _peer_afs),
    "peer_import": ("bgp.peer", _peer_policy("import_policy")),
    "peer_export": ("bgp.peer", _peer_policy("export_policy")),
    "vrf_rt_import": ("vrf.instance", _vrf_rt("import")),
    "vrf_rt_export": ("vrf.instance", _vrf_rt("export")),
    "vrf_interfaces": ("vrf.instance", _vrf_interfaces),
    "bd_members": ("bridge_domain", _bd_members),
    "bd_l3_interface": ("bridge_domain", _bd_l3),
}


# ---------------------------------------------------------------- 列


def _column(kb: KnowledgeBase, obj: str, c: Any, style: str, spec: dict[str, Any]) -> dict[str, Any]:
    """列定义 → {key, field, derive, label, schema, type, secret, empty, off}。c 可以是路径字符串或字典。"""
    if isinstance(c, str):
        c = {"derive": c[7:]} if c.startswith("derive:") else {"field": c}
    if not isinstance(c, dict):
        raise ExportError("export.bad_column", column=str(c))
    sn = resolve_type(kb, obj)
    fld, der = c.get("field"), c.get("derive")
    out: dict[str, Any] = {"field": fld, "derive": der, "schema": None, "type": "derived", "secret": False}
    if der:
        if der not in DERIVES or DERIVES[der][0] != sn.id:
            raise ExportError("export.bad_derive", derive=str(der), object=sn.id)
        out["key"] = f"derive:{der}"
    elif fld:
        try:
            fs = field_schema(kb, sn, str(fld))
        except TableError as e:
            raise ExportError("export.bad_field", field=str(fld), object=sn.id) from e
        out.update(
            key=str(fld), schema=fs.id if fs else None, type=fs.type if fs else "key", secret=bool(fs and fs.secret)
        )
    else:
        raise ExportError("export.bad_column", column=str(c))
    label = _label(c.get("label"), style)
    if not label:
        fs = kb.nodes.get(out["schema"] or "")
        sem = dict(fs.semantic) if fs else {}
        base = str(fld or der)
        label = {lg: str(sem.get(lg) or (sem.get("en") if lg != "zh-CN" else "") or base) for lg in LANGS}
    out["label"] = label
    empty = c.get("empty")
    if isinstance(empty, str) and empty in (spec.get("labels") or {}):
        empty = (spec.get("labels") or {})[empty]
    out["empty"] = _label(empty, style) if empty else None
    out["off"] = bool(c.get("off"))
    return out


# ---------------------------------------------------------------- 生成表格


def build(
    devices: list[Any],
    kb: KnowledgeBase,
    kb_root: Path,
    preset: str | None = None,
    obj: str | None = None,
    columns: list[Any] | None = None,
    where: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    defaults: bool = True,
    canonical_names: bool = False,
    style: str = "huawei",
) -> dict[str, Any]:
    """devices：topology.Device 列表。preset 与 obj 至少给一个；columns 不给时用模板的列（模板中 off 的列不选）。"""
    spec = load_spec(kb_root)
    pid: str | None = None
    p: dict[str, Any] = {}
    if preset:
        pid, p = find_preset(spec, preset)
    obj_id = obj or str(p.get("object") or "")
    if not obj_id:
        raise ExportError("export.need_object")
    try:
        sn = resolve_type(kb, obj_id)
    except TableError as e:
        raise ExportError("export.bad_object", object=obj_id) from e
    if pid and sn.id != p.get("object"):
        raise ExportError("export.preset_object", preset=pid, object=sn.id)
    if columns:
        preset_cols = {(c.get("field") or f"derive:{c.get('derive')}"): c for c in p.get("columns") or []}
        cols = []
        for c in columns:
            if isinstance(c, str) and c in preset_cols:
                c = {k: v for k, v in preset_cols[c].items() if k != "off"}
            cols.append(_column(kb, sn.id, c, style, spec))
    elif p:
        cols = [x for x in (_column(kb, sn.id, c, style, spec) for c in p.get("columns") or []) if not x["off"]]
    else:
        cols = [_column(kb, sn.id, k, style, spec) for k in (sn.key or [])]
        cols += [
            _column(kb, sn.id, ch.id[len(sn.id) + 1 :], style, spec)
            for ch in sorted(kb.children(sn.id), key=lambda n: n.id)
            if ch.type != "object" and ch.id[len(sn.id) + 1 :] not in sn.key and not ch.secret
        ]
    if not cols:
        raise ExportError("export.no_columns")
    named = _filters(spec, sn.id, style)
    where_ids = list(where if where is not None else (p.get("where") or []))
    conds: list[tuple[str, gquery.Cond]] = []
    for w in where_ids:
        if w not in named:
            raise ExportError("export.bad_filter", filter=w, filters=", ".join(named) or "-")
        conds.append((w, named[w]["cond"]))
    for f in filters or []:
        q = gquery.from_dict({"find": sn.id, "where": [f]})
        conds.append(("", q.where[0]))
    vq = gquery.Query(find=sn.id, where=[c for _, c in conds])
    try:
        gquery.validate(vq, kb)
    except gquery.QueryError as e:
        raise ExportError(e.key, **e.fmt) from e

    ctypes = {c.field: gquery.value_type(kb, sn, c.field) for _, c in conds}
    rows: list[dict[str, Any]] = []
    dev_info = []
    counts = {"default": 0, "unsupported": 0, "secret": 0}
    for dev in devices:
        ex = Extractor(dev.g, kb)
        n_dev = 0
        for nid in ex.ix.objects(sn.id):
            ok = True
            for _, cond in conds:
                cell = Cell(dev.name, "explicit") if cond.field == "device" else ex.cell(nid, sn, cond.field)
                if not gquery._match(cond.op, cell, cond.value, ctypes[cond.field]):
                    ok = False
                    break
            if not ok:
                continue
            ctx = Ctx(dev.g, kb, ex, nid, sn, canonical_names)
            cells = []
            for col in cols:
                if col["derive"]:
                    cell = DERIVES[col["derive"]][1](ctx)
                else:
                    cell = ex.cell(nid, sn, col["field"], with_defaults=defaults)
                    if canonical_names and (
                        col["type"] == "interface" or (sn.id == "interface" and col["field"] == "name")
                    ):
                        cell.value = (
                            [compare.interface_name(str(v)) for v in cell.value]
                            if isinstance(cell.value, list)
                            else compare.interface_name(str(cell.value))
                            if cell.value is not None
                            else None
                        )
                if cell.origin == "default":
                    counts["default"] += 1
                elif cell.origin == "unsupported":
                    counts["unsupported"] += 1
                if cell.secret:
                    counts["secret"] += 1
                cells.append(cell.as_dict())
            n_dev += 1
            key = dev.g.nodes[nid].get("key")
            rows.append(
                {
                    "device": dev.name,
                    "device_id": getattr(dev, "device_id", None),
                    "version_id": getattr(dev, "version_id", None),
                    "profile": dev.g.graph.get("profile"),
                    "node": nid,
                    "key": key,
                    "lines": ex.ix.subtree_lines(nid),
                    "cells": cells,
                }
            )
        dev_info.append(
            {
                "name": dev.name,
                "device_id": getattr(dev, "device_id", None),
                "version_id": getattr(dev, "version_id", None),
                "collected_at": getattr(dev, "collected_at", None),
                "profile": dev.g.graph.get("profile"),
                "family": dev.g.graph.get("family"),
                "rows": n_dev,
            }
        )
    title = _label(p.get("title"), style) if p else {lg: sn.id for lg in LANGS}
    return {
        "preset": pid,
        "object": sn.id,
        "title": title,
        "style": style,
        "columns": cols,
        "filters": [
            {"id": fid, "label": named[fid]["label"] if fid in named else {}, **cond.as_dict()} for fid, cond in conds
        ],
        "options": {"defaults": defaults, "canonical_names": canonical_names},
        "devices": dev_info,
        "rows": rows,
        "kb_version": kb.version,
        "summary": {
            "rows": len(rows),
            "devices": sum(1 for d in dev_info if d["rows"]),
            "columns": len(cols),
            "default_cells": counts["default"],
            "unsupported_cells": counts["unsupported"],
            "secret_columns": sum(1 for c in cols if c["secret"]),
        },
    }


# ---------------------------------------------------------------- 文件


def cell_text(cell: dict[str, Any], col: dict[str, Any], lang: str) -> str:
    t = TEXTS[lang]
    if cell.get("secret"):
        return t["configured"] if cell.get("value") else t["not_configured"]
    if cell.get("origin") == "unsupported":
        return "—"
    v = cell.get("value")
    if v is None or v == []:
        return (col.get("empty") or {}).get(lang, "") if cell.get("origin") == "none" else ""
    if isinstance(v, bool):
        return t["yes"] if v else t["no"]
    return display(v)


def _filename(table: dict[str, Any], lang: str, ext: str) -> str:
    base = table.get("preset") or str(table.get("object") or "table").replace(".", "-")
    return f"lmesh-{base}-{lang}.{ext}"


def _source_text(row: dict[str, Any], cols: list[dict[str, Any]], lang: str) -> str:
    t = TEXTS[lang]
    defaults = [c["label"][lang] for c, cell in zip(cols, row["cells"], strict=True) if cell["origin"] == "default"]
    unsup = [c["label"][lang] for c, cell in zip(cols, row["cells"], strict=True) if cell["origin"] == "unsupported"]
    parts = []
    if defaults:
        parts.append(f"{t['default']}: " + ", ".join(defaults))
    if unsup:
        parts.append(f"{t['unsupported']}: " + ", ".join(unsup))
    return "; ".join(parts)


def to_csv(table: dict[str, Any], lang: str) -> tuple[str, bytes]:
    """一张表：第一列设备，最后是来源、节点、行号；UTF-8 带 BOM（Excel 直接打开中文不乱码），CRLF 换行。"""
    _check_lang(lang)
    t = TEXTS[lang]
    cols = table["columns"]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([t["device"], *(c["label"][lang] for c in cols), t["source"], t["node"], t["lines"]])
    for r in table["rows"]:
        w.writerow(
            [
                r["device"],
                *(cell_text(cell, c, lang) for c, cell in zip(cols, r["cells"], strict=True)),
                _source_text(r, cols, lang),
                r["node"],
                _lines(r["lines"]),
            ]
        )
    return _filename(table, lang, "csv"), ("﻿" + buf.getvalue()).encode("utf-8")


def _lines(lines: list[int]) -> str:
    if not lines:
        return ""
    out, start, prev = [], lines[0], lines[0]
    for n in [*lines[1:], None]:
        if n is not None and n == prev + 1:
            prev = n
            continue
        out.append(str(start) if start == prev else f"{start}-{prev}")
        if n is not None:
            start = prev = n
    return ",".join(out)


def _check_lang(lang: str) -> None:
    if lang not in LANGS:
        raise ExportError("export.bad_lang", allowed=", ".join(LANGS))


def _sheet_name(name: str, used: set[str]) -> str:
    bad = "[]:*?/\\"
    s = "".join("_" if ch in bad else ch for ch in name)[:31] or "Sheet"
    base, i = s, 2
    while s.lower() in used:
        suffix = f"~{i}"
        s = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(s.lower())
    return s


def to_xlsx(
    table: dict[str, Any], lang: str, sheets: str = "per-device", now: datetime | None = None
) -> tuple[str, bytes]:
    """XLSX：“说明”工作表 + 每台设备一个工作表（或全部一张表）；默认值格子斜体灰字并加批注，不支持的格子加批注。"""
    _check_lang(lang)
    if sheets not in SHEETS:
        raise ExportError("export.bad_sheets", allowed=", ".join(SHEETS))
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    t = TEXTS[lang]
    cols = table["columns"]
    wb = Workbook()
    used: set[str] = set()
    about = wb.active
    assert about is not None
    about.title = _sheet_name(t["about"], used)
    bold = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="E8EEF5")
    def_font = Font(italic=True, color="808080")
    stamp = (now or datetime.now().astimezone()).strftime("%Y-%m-%d %H:%M:%S %z")
    info = [
        (t["table"], table["title"].get(lang, "")),
        (t["generated"], stamp),
        (t["kb_version"], table.get("kb_version", "")),
        (t["object"], table["object"]),
        (t["rows"], table["summary"]["rows"]),
        (
            t["filters"],
            "; ".join(
                f.get("label", {}).get(lang) or f"{f['field']} {f['op']} {f.get('value', '')}".strip()
                for f in table["filters"]
            )
            or "—",
        ),
    ]
    for k, v in info:
        about.append([k, v])
        about.cell(about.max_row, 1).font = bold
    about.append([])
    about.append([t["device"], t["version"], t["profile"], t["rows"]])
    for c in about[about.max_row]:
        c.font, c.fill = bold, head_fill
    for d in table["devices"]:
        ver = f"v{d['version_id']}" if d.get("version_id") else ""
        if d.get("collected_at"):
            ver = f"{ver} · {d['collected_at']}".strip(" ·")
        about.append([d["name"], ver, d.get("profile") or "", d["rows"]])
    about.append([])
    about.append([t["columns"], t["field"]])
    for c in about[about.max_row]:
        c.font, c.fill = bold, head_fill
    for c in cols:
        about.append([c["label"][lang], c["field"] or f"derive:{c['derive']}"])
    about.append([])
    about.append([t["notes"]])
    about.cell(about.max_row, 1).font = bold
    for k in ("note_config", "note_secret", "note_default"):
        about.append([t[k]])
    about.column_dimensions["A"].width = 28
    about.column_dimensions["B"].width = 60

    groups: list[tuple[str, list[dict[str, Any]]]]
    if sheets == "single":
        groups = [(table["title"].get(lang) or t["table"], table["rows"])]
    else:
        groups = [
            (d["name"], [r for r in table["rows"] if r["device"] == d["name"]]) for d in table["devices"] if d["rows"]
        ]
        if not groups:
            groups = [(table["title"].get(lang) or t["table"], [])]
    header = ([t["device"]] if sheets == "single" else []) + [c["label"][lang] for c in cols] + [t["node"], t["lines"]]
    for name, rows in groups:
        ws = wb.create_sheet(_sheet_name(name, used))
        ws.append(header)
        for c in ws[1]:
            c.font, c.fill = bold, head_fill
            c.alignment = Alignment(vertical="top", wrap_text=True)
        widths = [len(h) + 2 for h in header]
        for r in rows:
            vals = (
                ([r["device"]] if sheets == "single" else [])
                + [cell_text(cell, c, lang) for c, cell in zip(cols, r["cells"], strict=True)]
                + [r["node"], _lines(r["lines"])]
            )
            ws.append(vals)
            off = 1 if sheets == "single" else 0
            for i, (_c, cell) in enumerate(zip(cols, r["cells"], strict=True)):
                xc = ws.cell(ws.max_row, off + i + 1)
                if cell["origin"] == "default":
                    xc.font = def_font
                    xc.comment = Comment(t["comment_default"].format(profile=r.get("profile") or ""), "LucidMesh")
                elif cell["origin"] == "unsupported":
                    xc.comment = Comment(t["comment_unsupported"].format(profile=r.get("profile") or ""), "LucidMesh")
            for i, v in enumerate(vals):
                widths[i] = max(widths[i], min(60, len(str(v)) + 2))
        for i, wdt in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = wdt
        ws.freeze_panes = "A2"
        if rows:
            ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    return _filename(table, lang, "xlsx"), buf.getvalue()


MEDIA = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
