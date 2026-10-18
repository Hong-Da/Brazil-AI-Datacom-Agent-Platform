"""批量生成（M3-5）：模板 + 参数表（CSV / JSON）→ 每行一份配置，生成后解析、建图、往返，并按模板做一次约束匹配。

参数表：
    JSON：[{"device": "PE-07", "hostname": "PE-07", "svc": [{"vlan": 101, …}, …], "bfd": true}, …]，或 {"rows": [...]}。
    CSV：表头是 device、基础变量名、可选块名（true / false）、块变量“块名.变量”；重复块的取值用分号分隔，
         各列的个数相同，个数就是实例数（全部为空时 0 个实例）。

生成方式（engine）：
    text   模板正文按参数直接替换（默认）；
    canon  先按 text 方式生成并建图，再交给规范渲染器 core/canon.py 的 render(图, 知识库, Profile) 输出
           （可指定 target_profile 生成另一平台族的配置；渲染器尚未提供时报错 template.canon_unavailable）。
验证：未识别行为 0、往返逐字一致、按模板校验符合且提取出的变量与输入一致；任何一项不通过，这一行算失败并给出原因。
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from lmesh.core import analysis
from lmesh.core import graph as graphmod
from lmesh.core.kb import KnowledgeBase
from lmesh.core.renderer import render_roundtrip
from lmesh.core.template import RESERVED, Template, TemplateError, check_value, render_text, same_value

TRUE = {"true", "1", "yes", "y", "on", "是"}
FALSE = {"false", "0", "no", "n", "off", "否", ""}
ENGINES = ("text", "canon")


# ---------------------------------------------------------------- 参数表


def parse_params(text: str, fmt: str | None = None) -> list[dict[str, Any]]:
    """参数表文本 → 行（未经检查）。fmt：csv / json；不给时按内容判断。"""
    s = text.lstrip("﻿")
    kind = fmt or ("json" if s.lstrip().startswith(("[", "{")) else "csv")
    if kind == "json":
        try:
            data = json.loads(s)
        except json.JSONDecodeError as e:
            raise TemplateError("template.params_invalid", error=str(e)) from e
        if isinstance(data, dict):
            data = data.get("rows", [data] if "rows" not in data else [])
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise TemplateError("template.params_invalid", error="rows")
        return [dict(r) for r in data]
    if kind != "csv":
        raise TemplateError("template.params_format", format=kind)
    reader = csv.DictReader(io.StringIO(s))
    rows = []
    for r in reader:
        if not any((v or "").strip() for v in r.values() if isinstance(v, str)):
            continue
        rows.append({str(k).strip(): (v or "").strip() for k, v in r.items() if k is not None})
    return rows


def _from_columns(t: Template, raw: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """CSV 风格的扁平列（块名.变量、分号分隔）→ 结构化的一行；JSON 的结构化写法原样保留。"""
    errors: list[dict[str, Any]] = []
    row: dict[str, Any] = {}
    flat: dict[str, dict[str, Any]] = {}
    known = set(RESERVED) | {v.name for v in t.vars.values() if v.block is None} | set(t.blocks)
    for k, v in raw.items():
        if "." in k and k.split(".", 1)[0] in t.blocks:
            b, name = k.split(".", 1)
            if f"{b}.{name}" not in t.vars or t.vars[f"{b}.{name}"].derived:
                errors.append({"var": k, "value": v, "problem": "template.param.unknown_column"})
                continue
            flat.setdefault(b, {})[name] = v
        elif k in known:
            if k in t.vars and t.vars[k].derived:
                errors.append({"var": k, "value": v, "problem": "template.param.derived"})
                continue
            row[k] = v
        else:
            errors.append({"var": k, "value": v, "problem": "template.param.unknown_column"})
    for b, cols in flat.items():
        blk = t.blocks[b]
        if blk.kind == "optional":
            present = row.get(b)
            if isinstance(present, str):
                present = present.strip().lower() in TRUE
            if present is None:
                present = any(str(v).strip() for v in cols.values())
            row[b] = dict(cols) if present else False
            continue
        if isinstance(row.get(b), list):
            continue  # JSON 已给出结构化的列表
        split = {k: [x.strip() for x in str(v).split(";")] if str(v).strip() else [] for k, v in cols.items()}
        counts = {len(v) for v in split.values()}
        if len(counts) > 1:
            errors.append({"var": b, "value": None, "problem": "template.param.count_mismatch"})
            continue
        n = counts.pop() if counts else 0
        row[b] = [{k: v[i] for k, v in split.items()} for i in range(n)]
    return row, errors


def prepare_row(t: Template, raw: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """检查一行参数：补默认值、按类型规范化、检查约束。返回 (规范化的一行, 问题清单)。"""
    row_in, errors = _from_columns(t, raw)
    out: dict[str, Any] = {}
    if row_in.get("device") not in (None, ""):
        out["device"] = str(row_in["device"])
    for v in t.input_vars(None):
        val = row_in.get(v.name)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            val = v.default
        norm, problem = check_value(v, val)
        out[v.name] = norm
        if problem:
            errors.append({"var": v.name, "value": val, "problem": problem})
    for blk in t.blocks.values():
        val = row_in.get(blk.name)
        if blk.kind == "optional":
            if isinstance(val, str):
                if val.strip().lower() not in TRUE | FALSE:
                    errors.append({"var": blk.name, "value": val, "problem": "template.param.not_bool"})
                val = val.strip().lower() in TRUE
            if not val:
                out[blk.name] = False
                continue
            inst = val if isinstance(val, dict) else {}
            norm_inst, errs = _instance(t, blk.name, inst, None)
            errors += errs
            out[blk.name] = norm_inst or True
            continue
        items = val if isinstance(val, list) else []
        if val is not None and not isinstance(val, list):
            errors.append({"var": blk.name, "value": val, "problem": "template.param.not_list"})
        insts = []
        for i, inst in enumerate(items):
            if not isinstance(inst, dict):
                errors.append({"var": blk.name, "value": inst, "problem": "template.param.not_object", "instance": i})
                continue
            norm_inst, errs = _instance(t, blk.name, inst, i)
            errors += errs
            insts.append(norm_inst)
        if len(insts) < blk.min or (blk.max is not None and len(insts) > blk.max):
            errors.append(
                {
                    "var": blk.name,
                    "value": len(insts),
                    "problem": "template.param.count",
                    "min": blk.min,
                    "max": blk.max,
                }
            )
        for v in t.input_vars(blk.name):
            if v.unique:
                seen: set[str] = set()
                for i, inst in enumerate(insts):
                    k = str(inst.get(v.short)).lower()
                    if inst.get(v.short) is not None and k in seen:
                        errors.append(
                            {
                                "var": v.name,
                                "value": inst[v.short],
                                "problem": "template.value.not_unique",
                                "instance": i,
                            }
                        )
                    seen.add(k)
        out[blk.name] = insts
    return out, errors


def _instance(
    t: Template, block: str, inst: dict[str, Any], idx: int | None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    out: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []
    names = {v.short for v in t.input_vars(block)}
    for k in inst:
        if k not in names:
            errors.append(
                {"var": f"{block}.{k}", "value": inst[k], "problem": "template.param.unknown_column", "instance": idx}
            )
    for v in t.input_vars(block):
        val = inst.get(v.short)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            val = v.default
        norm, problem = check_value(v, val)
        out[v.short] = norm
        if problem:
            errors.append({"var": v.name, "value": val, "problem": problem, "instance": idx})
    return out, errors


# ---------------------------------------------------------------- 生成


def _canon_render(g: Any, kb: KnowledgeBase, profile: str) -> tuple[str, list[str], list[str]]:
    """规范渲染器：返回 (文本, 没能生成命令的节点, 没写出的原文行与未映射命令)。"""
    try:
        from lmesh.core import canon
    except ImportError as e:
        raise TemplateError("template.canon_unavailable") from e
    try:
        if hasattr(canon, "render_full"):
            r = canon.render_full(g, kb, profile)
            return r.text, list(r.uncovered), list(r.skipped_extras)
        return str(canon.render(g, kb, profile)), [], []
    except ValueError as e:  # canon.CanonError
        raise TemplateError("template.canon_failed", error=str(e)) from e


def _mismatch(t: Template, want: dict[str, Any], got: dict[str, Any]) -> list[dict[str, Any]]:
    """输入参数与从生成结果中提取出的变量逐个比较。"""
    bad: list[dict[str, Any]] = []
    for v in t.input_vars(None):
        if not same_value(v, want.get(v.name), got.get(v.name)):
            bad.append({"var": v.name, "want": want.get(v.name), "got": got.get(v.name)})
    for blk in t.blocks.values():
        w, g = want.get(blk.name), got.get(blk.name)
        if blk.kind == "optional":
            if bool(w) != bool(g):
                bad.append({"var": blk.name, "want": bool(w), "got": bool(g)})
            continue
        wl, gl = list(w or []), list(g or [])
        if len(wl) != len(gl):
            bad.append({"var": blk.name, "want": len(wl), "got": len(gl)})
            continue
        key = next((v for v in t.input_vars(blk.name) if v.unique), None)
        if key is not None:
            gl_by = {str(x.get(key.short)).lower(): x for x in gl}
            gl = [gl_by.get(str(x.get(key.short)).lower(), {}) for x in wl]
        for i, (a, b) in enumerate(zip(wl, gl, strict=True)):
            for v in t.input_vars(blk.name):
                if not same_value(v, a.get(v.short), b.get(v.short)):
                    bad.append({"var": v.name, "instance": i, "want": a.get(v.short), "got": b.get(v.short)})
    return bad


def generate_row(
    t: Template,
    raw: dict[str, Any],
    kb: KnowledgeBase,
    index: int = 0,
    engine: str = "text",
    target_profile: str | None = None,
    verify: bool = True,
) -> dict[str, Any]:
    from lmesh.core import template_match

    row, errors = prepare_row(t, raw)
    device = str(row.get("device") or raw.get("device") or f"row-{index + 1}")
    result: dict[str, Any] = {
        "index": index,
        "device": device,
        "ok": False,
        "text": None,
        "params": row,
        "errors": [{"stage": "params", **e} for e in errors],
        "checks": {},
    }
    if errors:
        return result
    try:
        text = render_text(t, row)
    except TemplateError as e:
        result["errors"].append({"stage": "render", "problem": e.key, **e.fmt})
        return result
    profile = target_profile or t.profile
    if engine == "canon":
        res = analysis.parse_text(text, kb, t.profile)
        g0 = graphmod.build(res.parsed, kb, res.profile, device)
        try:
            text, uncovered, skipped = _canon_render(g0, kb, profile)
        except TemplateError as e:
            result["errors"].append({"stage": "render", "problem": e.key, **e.fmt})
            return result
        if not text.endswith("\n"):
            text += "\n"
        result["checks"]["canon"] = {"uncovered": uncovered, "skipped_extras": skipped}
        if uncovered:
            result["errors"].append({"stage": "render", "problem": "template.gen.uncovered", "count": len(uncovered)})
    result["text"] = text
    if not verify:
        result["ok"] = not result["errors"]
        return result
    res = analysis.parse_text(text, kb, profile)
    unknown = [{"line": ln.no, "text": ln.text} for ln in res.parsed.unknown()]
    result["checks"]["parse"] = {"profile": res.profile, "unknown": len(unknown), "unknown_lines": unknown[:20]}
    if unknown:
        result["errors"].append({"stage": "parse", "problem": "template.gen.unknown_lines", "count": len(unknown)})
    g = graphmod.build(res.parsed, kb, res.profile, device)
    rt = render_roundtrip(g, kb) == text.replace("\r\n", "\n")
    result["checks"]["roundtrip"] = rt
    if not rt:
        result["errors"].append({"stage": "roundtrip", "problem": "template.gen.roundtrip"})
    if kb.profiles[res.profile].family == kb.profiles[t.profile].family:
        chk = template_match.check(t, g, kb, device)
        mism = _mismatch(t, row, chk["row"])
        errs = [f for f in chk["findings"] if f["severity"] == "error"]
        result["checks"]["template"] = {
            "compliant": chk["compliant"],
            "errors": len(errs),
            "findings": errs[:20],
            "mismatched": mism,
        }
        if not chk["compliant"]:
            result["errors"].append({"stage": "template", "problem": "template.gen.not_compliant", "count": len(errs)})
        if mism:
            result["errors"].append(
                {"stage": "template", "problem": "template.gen.extract_mismatch", "count": len(mism)}
            )
    else:
        result["checks"]["template"] = None  # 生成到另一平台族时不按模板校验（模板的命令写法属于原平台族）
    result["ok"] = not result["errors"]
    return result


def generate(
    t: Template,
    rows: list[dict[str, Any]],
    kb: KnowledgeBase,
    engine: str = "text",
    target_profile: str | None = None,
    verify: bool = True,
) -> dict[str, Any]:
    if engine not in ENGINES:
        raise TemplateError("template.bad_engine", engine=engine)
    if target_profile and target_profile not in kb.profiles:
        raise TemplateError("parse.profile_unknown", profile=target_profile)
    if target_profile and engine != "canon" and target_profile != t.profile:
        raise TemplateError("template.target_needs_canon")
    if not rows:
        raise TemplateError("template.params_empty")
    out = [generate_row(t, r, kb, i, engine, target_profile, verify) for i, r in enumerate(rows)]
    names: dict[str, int] = {}
    for r in out:  # 设备名重复时文件名加序号
        n = names.get(r["device"], 0)
        names[r["device"]] = n + 1
        r["file"] = f"{_safe(r['device'])}{'' if n == 0 else f'-{n + 1}'}.cfg"
    ok = sum(1 for r in out if r["ok"])
    return {
        "template": {k: v for k, v in t.info(kb).items() if k in ("id", "version", "title", "profile", "digest")},
        "engine": engine,
        "profile": target_profile or t.profile,
        "verify": verify,
        "rows": out,
        "summary": {"total": len(out), "ok": ok, "failed": len(out) - ok},
    }


def _safe(name: str) -> str:
    keep = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name).strip("._")
    return keep[:80] or "device"
