"""模板制作辅助（M3-4）：从一份或几份同角色设备的配置生成模板草稿。

做法（确定性部分全部由代码在图上完成）：
    1. 每份配置解析建图、规范化；以第一份为基准，按规范编号对齐其他配置的对象与属性：编号相同直接对上；
       编号不同的对象在同一父对象、同一 Schema 下按内容相似度两两配对（例如两台设备的 Loopback 地址不同）。
       未映射的命令（ext）与功能域外的原文行（sysname 等）按所属对象与命令卡 / 首个词配对。
    2. 对上的节点所在的行逐个词比较，取值不同的词（去掉各设备共同的前缀与后缀，例如 Vbdif1584 / Vbdif1585 只取
       数字部分）是候选变量；各设备取值完全相同的位置归为同一个变量。变量名按所在节点的 Schema 建议，
       类型按取值推断（IPv4、整数 / VLAN、RD、接口名、单词、文本）。
    3. 只有一份配置时没有差异可比：设备身份（主机名、Router ID、接口地址、对等体地址等，见对比的 IDENTITY 清单）
       与描述作为候选变量。
    4. 只在部分设备上出现的对象列为可选块候选，同一父对象下结构相同的多个兄弟对象列为重复块候选（只给建议，
       不自动改写正文）。
输出模板草稿（YAML 文本，可直接保存为模板）、变量表（含每台设备的取值与依据的节点）、参数表（每份配置一行），
并用草稿校验每份源配置（应当符合、提取出的变量与参数表一致）。哪些值真正应该是变量由人确认（AI 可在此基础上建议）。
"""

from __future__ import annotations

import io
import ipaddress
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import networkx as nx
from ruamel.yaml import YAML

from lmesh.core import analysis
from lmesh.core import graph as graphmod
from lmesh.core.compare import (
    _IF_CANON,
    IDENTITY_ATTRS,
    IDENTITY_OBJECTS,
    IDENTITY_OBJECTS_IP_KEY,
    IDENTITY_RAW,
    Item,
    Multi,
    _Canon,
    _Canonicalizer,
    _Schema,
    _signature,
    _similarity,
    interface_name,
)
from lmesh.core.kb import KnowledgeBase
from lmesh.core.template import TemplateError

MAX_CONFIGS = 20
_TOKEN = re.compile(r"\S+")
_IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_RD = re.compile(r"^(\d{1,3}(\.\d{1,3}){3}|\d+(\.\d+)?):\d+$")


@dataclass
class _Cfg:
    label: str
    text: str
    lines: list[str]
    canon: _Canon
    graph: nx.MultiDiGraph
    profile: str
    family: str


@dataclass
class _Pos:
    """基准配置中一个候选变量出现的位置：行号、词的位置、词内的起止（去掉共同前后缀之后）。"""

    line: int
    start: int
    end: int
    schema: str
    node: str


@dataclass
class _Cand:
    values: tuple[str, ...]  # 各配置中的取值（按配置顺序）
    positions: list[_Pos] = field(default_factory=list)
    name: str = ""
    type: str = "word"
    reason: str = "differs"


def _load(label: str, text: str, kb: KnowledgeBase, profile: str | None) -> _Cfg:
    text = text.replace("\r\n", "\n")
    try:
        res = analysis.parse_text(text, kb, profile)
    except analysis.AnalysisError as e:
        raise TemplateError(str(e), profile=profile or "") from e
    g = graphmod.build(res.parsed, kb, res.profile, label)
    c = _Canonicalizer(g, kb, _Schema(kb)).run()
    return _Cfg(label, text, text.split("\n"), c, g, res.profile, res.family)


# ---------------------------------------------------------------- 对齐


def _align(base: _Cfg, other: _Cfg) -> dict[int, int]:
    """基准配置的行号 → 另一份配置中对应的行号（由对齐的节点得到）。"""
    a_items, b_items = base.canon.items, other.canon.items
    amap: dict[str, str] = {"": ""}  # 基准对象编号 → 另一份配置的对象编号
    taken: set[str] = set()
    pending: dict[tuple[str, str], list[Item]] = defaultdict(list)
    for cid, it in a_items.items():
        if it.kind != "object" or it.origin != "explicit":
            continue
        if cid in b_items and b_items[cid].kind == "object":
            amap[cid] = cid
            taken.add(cid)
        else:
            pending[(it.parent, it.schema)].append(it)
    # 编号不同的对象：父对象已对上时，在同一父对象、同一 Schema 下按内容相似度配对（逐层进行）
    for _ in range(8):
        progressed = False
        for (parent, schema), its in list(pending.items()):
            if parent not in amap:
                continue
            bparent = amap[parent]
            cands = [
                b
                for b in b_items.values()
                if b.kind == "object" and b.schema == schema and b.parent == bparent and b.cid not in taken
            ]
            scored = []
            for it in its:
                sa = _signature(base.canon, it.cid)
                for b in cands:
                    sb = _signature(other.canon, b.cid)
                    scored.append((_similarity(sa, sb), -min(it.lines or [0]), -min(b.lines or [0]), it, b))
            scored.sort(key=lambda x: (-x[0], -x[1], -x[2]))
            used_a: set[str] = set()
            for _s, _x, _y, it, b in scored:
                if it.cid in used_a or b.cid in taken:
                    continue
                amap[it.cid] = b.cid
                taken.add(b.cid)
                used_a.add(it.cid)
            del pending[(parent, schema)]
            progressed = True
        if not progressed:
            break
    pairs: dict[int, int] = {}

    def pair(la: list[int], lb: list[int]) -> None:
        if len(la) != len(lb):
            return
        for x, y in zip(sorted(la), sorted(lb), strict=True):
            pairs.setdefault(x, y)

    for cid, it in a_items.items():
        if it.origin != "explicit":
            continue
        if it.kind == "object":
            if cid in amap:
                pair(it.lines, b_items[amap[cid]].lines)
            continue
        if it.parent not in amap:
            continue
        rel = cid[len(it.parent) + 1 :] if it.parent else cid
        bcid = f"{amap[it.parent]}/{rel}" if amap[it.parent] else rel
        hit = b_items.get(bcid)
        if hit is not None and hit.origin == "explicit":
            pair(it.lines, hit.lines)
    # 未映射命令与原文行：同一所属对象下按命令卡（原文行按首个词）唯一配对
    for kind in ("ext", "raw"):
        la: list[Multi] = base.canon.ext if kind == "ext" else base.canon.raw
        lb: list[Multi] = other.canon.ext if kind == "ext" else other.canon.raw
        groups_b: dict[tuple[str, str], list[Multi]] = defaultdict(list)
        for m in lb:
            groups_b[(m.owner, _group(m))].append(m)
        groups_a: dict[tuple[str, str], list[Multi]] = defaultdict(list)
        for m in la:
            if m.owner in amap:
                groups_a[(amap[m.owner], _group(m))].append(m)
        for key, ms in groups_a.items():
            mb = groups_b.get(key, [])
            if len(ms) == len(mb):
                for x, y in zip(ms, mb, strict=True):
                    pair(x.lines, y.lines)
    return pairs


def _group(m: Multi) -> str:
    if m.group != "raw":
        return m.group
    words = str(m.value).split()
    return "raw:" + (words[0] if words else "")


# ---------------------------------------------------------------- 候选变量


def _trim(values: list[str]) -> tuple[int, int]:
    """各取值共同的前缀与后缀长度（不切开数字串或字母串的中间）。"""
    if len(values) < 2:
        return 0, 0
    pre = 0
    shortest = min(len(v) for v in values)
    while pre < shortest and all(v[pre] == values[0][pre] for v in values):
        pre += 1
    while pre > 0 and any(
        pre < len(v) and v[pre - 1].isalnum() and v[pre].isalnum() and v[pre - 1].isdigit() == v[pre].isdigit()
        for v in values
    ):
        pre -= 1
    suf = 0
    while suf < shortest - pre and all(v[len(v) - 1 - suf] == values[0][len(values[0]) - 1 - suf] for v in values):
        suf += 1
    while suf > 0 and any(
        len(v) - suf - 1 >= 0
        and v[len(v) - suf - 1].isalnum()
        and v[len(v) - suf].isalnum()
        and v[len(v) - suf - 1].isdigit() == v[len(v) - suf].isdigit()
        for v in values
    ):
        suf -= 1
    return pre, suf


def _line_items(cfg: _Cfg) -> dict[int, list[tuple[str, str, str]]]:
    """行号 → [（Schema，节点编号，取值文字）]，用于判断一个词属于哪个节点、给变量起名。"""
    out: dict[int, list[tuple[str, str, str]]] = defaultdict(list)
    for cid, it in cfg.canon.items.items():
        if it.origin != "explicit":
            continue
        val = it.key if it.kind == "object" else it.value
        if isinstance(val, dict):
            val = " ".join(str(v) for v in val.values())
        for ln in it.lines:
            out[ln].append((it.schema, cid, "" if val is None or isinstance(val, bool) else str(val)))
    for m in [*cfg.canon.ext, *cfg.canon.raw]:
        for ln in m.lines:
            out[ln].append((_group(m), m.owner, str(m.value)))
    return out


def _owner_of(items: list[tuple[str, str, str]], value: str) -> tuple[str, str]:
    """一个词（取值）属于这一行的哪个节点：取值相等的优先，其次包含它的，最后取这一行的第一个节点。"""
    if not items:
        return "", ""
    low = value.lower()
    for sch, cid, v in items:
        if v.lower() == low or interface_name(v) == interface_name(value):
            return sch, cid
    for sch, cid, v in items:
        if low and low in v.lower():
            return sch, cid
    return items[0][0], items[0][1]


_IF_TYPES = {k for k in _IF_CANON} | {v.lower() for v in _IF_CANON.values()}
_IF_LIKE = re.compile(r"^[A-Za-z][A-Za-z-]*\d")


def _trim_ok(word: str, pre: int, suf: int) -> bool:
    """只在接口名上去掉共同前缀：前缀是接口类型（Vbdif1584 → 1584）或到子接口的点为止（GE0/2/0.1584 → 1584）。"""
    if pre == 0 or suf != 0 or not _IF_LIKE.match(word):
        return False
    prefix = word[:pre]
    kind = re.match(r"[A-Za-z-]+", word)
    known = bool(kind) and kind.group().lower() in _IF_TYPES  # type: ignore[union-attr]
    return known and (prefix.isalpha() or prefix.endswith("."))


def _diff_candidates(cfgs: list[_Cfg]) -> tuple[dict[tuple[str, ...], _Cand], list[dict[str, Any]]]:
    base = cfgs[0]
    aligns = [_align(base, c) for c in cfgs[1:]]
    owners = _line_items(base)
    cands: dict[tuple[str, ...], _Cand] = {}
    notes: list[dict[str, Any]] = []
    for ln in sorted(set.intersection(*(set(a) for a in aligns)) if aligns else set()):
        texts = [base.lines[ln - 1]] + [c.lines[a[ln] - 1] for c, a in zip(cfgs[1:], aligns, strict=True)]
        toks = [[(m.start(), m.end(), m.group()) for m in _TOKEN.finditer(t)] for t in texts]
        if len({len(t) for t in toks}) != 1:
            if len({t.strip() for t in texts}) > 1:
                notes.append({"key": "template.draft.line_shape", "line": ln, "text": texts[0].strip()})
            continue
        for i, (s0, _e0, w0) in enumerate(toks[0]):
            words = [t[i][2] for t in toks]
            if len(set(words)) == 1:
                continue
            pre, suf = _trim(words)
            if not _trim_ok(w0, pre, suf):
                pre, suf = 0, 0
            vals = tuple(w[pre : len(w) - suf] for w in words)
            if any(v == "" for v in vals):
                vals, pre, suf = tuple(words), 0, 0
            schema, node = _owner_of(owners.get(ln, []), w0 if not pre else w0[pre:])
            c = cands.setdefault(vals, _Cand(vals))
            c.positions.append(_Pos(ln, s0 + pre, s0 + len(w0) - suf, schema, node))
    return cands, notes


def _identity_candidates(cfg: _Cfg) -> dict[tuple[str, ...], _Cand]:
    """只有一份配置时：设备身份与描述作为候选变量（在所在行中找到取值对应的词）。"""
    cands: dict[tuple[str, ...], _Cand] = {}

    def add(ln: int, value: str, schema: str, node: str, reason: str) -> None:
        if not value or ln < 1:
            return
        text = cfg.lines[ln - 1]
        for m in _TOKEN.finditer(text):
            w = m.group()
            hit = w == value or (schema.endswith("interface") and interface_name(w) == interface_name(value))
            if hit:
                c = cands.setdefault((w,), _Cand((w,), reason=reason))
                if not any(p.line == ln and p.start == m.start() for p in c.positions):
                    c.positions.append(_Pos(ln, m.start(), m.end(), schema, node))
                return
        if schema.endswith("description"):  # 描述可以含空格：取命令之后的全部文字
            idx = text.find(value)
            if idx >= 0:
                c = cands.setdefault((value,), _Cand((value,), reason=reason, type="text"))
                c.positions.append(_Pos(ln, idx, idx + len(value), schema, node))

    for cid, it in cfg.canon.items.items():
        if it.origin != "explicit":
            continue
        if it.kind == "attr" and (it.schema in IDENTITY_ATTRS or it.schema.endswith(".description")):
            for ln in it.lines:
                add(ln, str(it.value), it.schema, cid, "identity" if it.schema in IDENTITY_ATTRS else "description")
        elif it.kind == "object" and (it.schema in IDENTITY_OBJECTS or it.schema in IDENTITY_OBJECTS_IP_KEY):
            key = it.key if not isinstance(it.key, dict) else next(iter(it.key.values()), "")
            if it.schema in IDENTITY_OBJECTS_IP_KEY and not _IPV4.match(str(key)):
                continue
            for ln in it.lines:
                add(ln, str(key), it.schema, cid, "identity")
    for m in cfg.canon.raw:
        if IDENTITY_RAW.match(str(m.value)):
            words = str(m.value).split()
            if len(words) >= 2:
                for ln in m.lines:
                    add(ln, words[1], "raw:" + words[0], m.owner, "identity")
    return cands


_NAME_HINTS = {
    "interface.ipv4": "ip",
    "interface.ipv4.address": "ip",
    "interface.ipv4.prefix_length": "mask",
    "interface.description": "desc",
    "interface.vrf": "vrf",
    "vrf.instance": "vrf",
    "bgp.instance": "asn",
    "bgp.instance.router_id": "router_id",
    "bgp.peer": "peer",
    "bgp.af.peer": "peer",
    "interface": "port",
    "interface.access": "vlan",
    "interface.access.vlan": "vlan",
    "interface.dot1q_termination": "vlan",
    "bridge_domain": "bd",
    "isis.process.net": "net",
}


def _suggest_name(c: _Cand, used: set[str]) -> str:
    hint = ""
    for p in c.positions:
        sch = p.schema
        if sch.startswith("raw:"):
            hint = {"sysname": "hostname", "hostname": "hostname"}.get(sch[4:], sch[4:])
        elif sch in _NAME_HINTS:
            hint = _NAME_HINTS[sch]
        elif sch.endswith(".rd") or sch.endswith(".rt") or sch.endswith(".value"):
            hint = "rd" if sch.endswith(".rd") else "rt"
        elif sch and not sch.startswith(("huawei", "cisco")):
            hint = sch.rsplit(".", 1)[-1]
        if hint:
            break
    hint = re.sub(r"[^A-Za-z0-9_]", "_", hint or "var").strip("_").lower() or "var"
    if hint[0].isdigit():
        hint = "v_" + hint
    name, n = hint[:32], 2
    while name in used:
        name = f"{hint[:28]}_{n}"
        n += 1
    used.add(name)
    return name


def _infer_type(c: _Cand) -> tuple[str, dict[str, Any]]:
    vals = list(c.values)
    extra: dict[str, Any] = {}
    if c.type == "text" or any(p.schema.endswith("description") for p in c.positions):
        return "text", extra
    if all(v.isdigit() for v in vals):
        nums = [int(v) for v in vals]
        vlanish = any(
            p.schema.endswith(("vlan", "dot1q_termination", "access", "bridge_domain")) or "vlan" in p.schema
            for p in c.positions
        )
        if vlanish and all(1 <= n <= 4094 for n in nums):
            return "vlan", extra
        if any(p.schema == "bgp.instance" or p.schema.endswith("remote_as") for p in c.positions):
            return "asn", extra
        return "integer", extra
    if all(_IPV4.match(v) for v in vals):
        try:
            for v in vals:
                ipaddress.IPv4Address(v)
            return "ipv4", extra
        except ValueError:
            pass
    if all(_RD.match(v) for v in vals):
        return "rd", extra
    if all(interface_name(v) != v or re.match(r"^[A-Za-z][A-Za-z-]*\d+([/:.]\d+)*$", v) for v in vals) and any(
        p.schema == "interface" or p.schema.endswith(("interface", "update_source")) for p in c.positions
    ):
        return "interface", extra
    if any(re.search(r"\s", v) for v in vals):
        return "text", extra
    return "word", extra


# ---------------------------------------------------------------- 候选块


def _block_hints(cfgs: list[_Cfg]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    base = cfgs[0]
    optional: list[dict[str, Any]] = []
    if len(cfgs) > 1:
        aligns = [_align(base, c) for c in cfgs[1:]]
        for cid, it in base.canon.items.items():
            if it.kind != "object" or it.origin != "explicit" or (it.parent and it.parent not in base.canon.items):
                continue
            up = base.canon.items.get(it.parent)
            if up is not None and up.kind == "object" and not _all_aligned(up, aligns):
                continue  # 只报最上层
            missing = [c.label for c, a in zip(cfgs[1:], aligns, strict=True) if not all(ln in a for ln in it.lines)]
            if missing and it.lines:
                optional.append(
                    {
                        "node": cid,
                        "schema": it.schema,
                        "lines": base.canon.subtree_lines.get(cid, it.lines),
                        "missing_in": missing,
                    }
                )
    # 重复块：同一父对象下同一 Schema 的多个兄弟对象，内容（去掉键之后）相同
    repeat: list[dict[str, Any]] = []
    groups: dict[tuple[str, str], list[Item]] = defaultdict(list)
    for it in base.canon.items.values():
        if it.kind == "object" and it.origin == "explicit":
            groups[(it.parent, it.schema)].append(it)
    for (parent, schema), its in groups.items():
        if len(its) < 2:
            continue
        sigs = [frozenset(_signature(base.canon, it.cid)) for it in its]
        if sigs[0] and all(_similarity(set(sigs[0]), set(s)) >= 0.6 for s in sigs[1:]):
            repeat.append({"parent": parent, "schema": schema, "nodes": [it.cid for it in its], "count": len(its)})
    return optional, repeat


def _all_aligned(it: Item, aligns: list[dict[int, int]]) -> bool:
    return all(all(ln in a for ln in it.lines) for a in aligns)


# ---------------------------------------------------------------- 草稿


def _dump_yaml(data: dict[str, Any]) -> str:
    y = YAML()
    y.default_flow_style = None
    y.width = 4096
    y.allow_unicode = True
    buf = io.StringIO()
    y.dump(data, buf)
    return buf.getvalue()


def draft(
    configs: list[tuple[str, str]],
    kb: KnowledgeBase,
    profile: str | None = None,
    template_id: str = "draft",
    title: str | None = None,
) -> dict[str, Any]:
    """configs：[(设备名, 配置文本)]，第一份是基准。"""
    from lmesh.core import template as tmod
    from lmesh.core import template_match

    if not configs:
        raise TemplateError("template.draft_empty")
    if len(configs) > MAX_CONFIGS:
        raise TemplateError("template.draft_too_many", max=MAX_CONFIGS)
    if not tmod.ID_RE.match(template_id):
        raise TemplateError("template.bad_id", id=template_id)
    cfgs = [_load(label, text, kb, profile) for label, text in configs]
    fams = {c.family for c in cfgs}
    if len(fams) > 1:
        raise TemplateError("template.draft_family", families=", ".join(sorted(fams)))
    base = cfgs[0]
    notes: list[dict[str, Any]] = []
    if len(cfgs) > 1:
        cands, notes = _diff_candidates(cfgs)
    else:
        cands = _identity_candidates(base)
    # 同一行中位置重叠的候选只留第一个
    taken: dict[int, list[tuple[int, int]]] = defaultdict(list)
    ordered = sorted(cands.values(), key=lambda c: min((p.line, p.start) for p in c.positions))
    final: list[_Cand] = []
    used_names: set[str] = set()
    for c in ordered:
        keep = []
        for p in c.positions:
            if any(not (p.end <= s or p.start >= e) for s, e in taken[p.line]):
                continue
            keep.append(p)
            taken[p.line].append((p.start, p.end))
        if not keep:
            continue
        c.positions = keep
        c.type, _ = _infer_type(c)
        c.name = _suggest_name(c, used_names)
        final.append(c)
    # 正文：基准配置中候选位置换成占位符
    body_lines = list(base.lines)
    by_line: dict[int, list[tuple[int, int, str]]] = defaultdict(list)
    for c in final:
        for p in c.positions:
            by_line[p.line].append((p.start, p.end, c.name))
    for ln, spans in by_line.items():
        text = body_lines[ln - 1]
        for s, e, name in sorted(spans, reverse=True):
            text = text[:s] + "{{" + name + "}}" + text[e:]
        body_lines[ln - 1] = text
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()
    vars_doc: dict[str, Any] = {}
    for c in final:
        spec: dict[str, Any] = {"type": c.type, "example": _example(c)}
        vars_doc[c.name] = spec
    ttl = title or f"{template_id}"
    meta = {
        "id": template_id,
        "version": 1,
        "title": {"zh-CN": ttl, "en": ttl, "pt-BR": ttl},
        "profile": base.profile,
        "match": {"extra": "allow", "extra_scope": "matched"},
        "vars": vars_doc,
    }
    header = (
        "# 模板草稿：由 lmesh template draft 从 "
        + ", ".join(c.label for c in cfgs)
        + " 生成；请确认变量、类型与约束后保存。\n"
    )
    source = header + _dump_yaml(meta) + "body: |2\n" + "".join(f"  {ln}\n" if ln else "\n" for ln in body_lines)
    params = []
    for i, cfg in enumerate(cfgs):
        row: dict[str, Any] = {"device": cfg.label}
        for c in final:
            v = c.values[i] if i < len(c.values) else c.values[0]
            row[c.name] = int(v) if c.type in ("integer", "vlan", "asn") and v.isdigit() else v
        params.append(row)
    optional, repeat = _block_hints(cfgs)
    result: dict[str, Any] = {
        "template_id": template_id,
        "profile": base.profile,
        "family": base.family,
        "configs": [c.label for c in cfgs],
        "source": source,
        "vars": [
            {
                "name": c.name,
                "type": c.type,
                "values": list(c.values),
                "reason": c.reason,
                "positions": [
                    {"line": p.line, "schema": p.schema or None, "node": p.node or None} for p in c.positions
                ],
            }
            for c in final
        ],
        "params": params,
        "optional_candidates": optional,
        "repeat_candidates": repeat,
        "notes": notes,
        "verify": [],
        "valid": True,
        "issues": [],
    }
    try:
        t = tmod.parse(source, kb, f"{template_id}.yaml")
        template_match.compile_template(t, kb)
    except TemplateError as e:
        result["valid"], result["issues"] = False, e.issues or [{"where": "", "key": e.key, "args": e.fmt}]
        return result
    from lmesh.core.template_gen import _mismatch, prepare_row

    for cfg, row in zip(cfgs, params, strict=True):
        chk = template_match.check(t, cfg.graph, kb, cfg.label)
        want, errs = prepare_row(t, row)
        mism = _mismatch(t, want, chk["row"]) if not errs else []
        result["verify"].append(
            {
                "device": cfg.label,
                "compliant": chk["compliant"],
                "errors": chk["summary"]["by_severity"]["error"],
                "mismatched": mism,
            }
        )
    return result


def _example(c: _Cand) -> Any:
    v = c.values[0]
    if c.type in ("integer", "vlan", "asn") and v.isdigit():
        return int(v)
    return v
