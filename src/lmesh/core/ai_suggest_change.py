"""变更与割接组的 AI skill（M8-4，REQ-041）：变更意图转脚本、割接方案文档、翻译未支持项、命名映射建议、模板提取。

原则同 M8-2 框架（core/ai_suggest.py）：AI 只给建议，确定性结论由代码在图上计算，校验不通过的拒绝；采纳可撤销。

    skill               类别            AI 给出                          代码校验                                       采纳
    intent-script       graph_edit      目标图上的增、删、改（Schema 节点  节点在 Schema 中且 Profile 支持、取值类型与范围、  生成项目脚本（下发 + 回滚），
                                        + 图中对象编号）                  引用存在；增量变更逻辑生成脚本，影响分析，模拟执行  同一次运行的采纳合并成一份
    cutover-plan        plan_section    割接方案的一节（中英双语）        两种语言都有；提到的对象与数字在事实里；命令只能   写入方案（导出时按代码给出的
                                                                          引用代码生成的步骤 [[s3]]，写出命令的拒绝          步骤填入命令）
    translate-gap       translate_eq    不支持 / 原文保留行的目标写法     用目标 Profile 的命令卡解析：不能识别的拒绝，要     写入翻译结果（标为 AI 来源）
                                                                          映射到预期的 Schema 节点
    naming-map          naming_rules    名称、端口映射规则（REQ-032）     规则集语法；在源图上试运行列出完整映射表，冲突拒绝、 保存为我的规则集
                                                                          遗漏与没用上的规则提醒
    template-extract    template_draft  公共模板与变量                    模板语法；用每台设备自己的取值渲染，结果须与原配置  保存为我的模板
                                                                          等价（模板覆盖的部分逐节点相同）
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections import defaultdict
from typing import Any

import networkx as nx

from lmesh.core import ai_suggest as base
from lmesh.core import graph as graphmod
from lmesh.core.ai_suggest import (
    Context,
    Env,
    SkillSpec,
    SuggestError,
    Validator,
    check_text,
    reason,
    register_category,
    register_skill,
)
from lmesh.core.ai_suggest_skills import LANG_NAMES, MAX_NAMES, _prepare_device, _short
from lmesh.core.store.models import AISuggestion

MAX_EDITS = 60
MAX_OBJECTS = 400
MAX_INTENT = 2000
MAX_GAPS = 60
MAX_TEMPLATE_DEVICES = 10
MAX_CONFIG_LINES = 80
PLAN_SECTIONS = ("overview", "window", "steps", "checks", "rollback", "risks")
EDIT_OPS = ("set", "unset", "add", "delete")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _actor(env: Env) -> Any:
    from lmesh.core import checkproj

    return checkproj.Actor(env.user_id, env.admin, env.actor)


def _texts(title: str) -> dict[str, str]:
    t = title[:80] or "AI"
    return {"zh-CN": t, "en": t, "pt-BR": t}


# ================================================================ 1. 变更意图转脚本（graph_edit）


def _prepare_intent(env: Env, params: dict[str, Any]) -> None:
    _prepare_device(env, params)
    intent = str(params.get("intent") or "").strip()
    if not intent:
        raise SuggestError("ai_suggest.need_intent", "param")
    if len(intent) > MAX_INTENT:
        raise SuggestError("ai_suggest.intent_too_long", "param", max=MAX_INTENT)
    params["intent"] = intent


def _owner_schema(kb: Any, sid: str | None) -> str | None:
    """Schema 节点最近的对象祖先（不含自己）；没有时 None（挂在设备下）。"""
    sn = kb.nodes.get(sid) if sid else None
    cur = kb.nodes.get(sn.parent) if sn is not None and sn.parent else None
    while cur is not None and cur.type != "object":
        cur = kb.nodes.get(cur.parent) if cur.parent else None
    return cur.id if cur is not None else None


def _children(g: nx.MultiDiGraph, n: str) -> list[str]:
    return [b for _, b, d in g.out_edges(n, data=True) if d.get("kind") == "contains"]


def _subtree(g: nx.MultiDiGraph, n: str) -> list[str]:
    out, stack = [], [n]
    while stack:
        x = stack.pop()
        out.append(x)
        stack.extend(_children(g, x))
    return out


def _supported(kb: Any, profile: str) -> dict[str, bool]:
    if profile not in kb.profiles:
        return {}
    return {k: bool(e.supported) for k, e in kb.resolve_profile(profile).entries.items()}


def _intent_objects(g: nx.MultiDiGraph, intent: str) -> list[str]:
    """给 AI 看的对象：显式对象，与描述有关的（键或属性取值出现在描述里）优先，其次按配置行号。"""
    low = intent.lower()
    words = {w for w in re.split(r"[\s,，。;；:：()（）\"'“”]+", low) if len(w) >= 2}
    objs = [n for n, d in g.nodes(data=True) if d.get("kind") == "object" and d.get("origin") != "default"]

    def related(n: str) -> bool:
        d = g.nodes[n]
        vals = [graphmod._key_text(d.get("key"))]
        vals += [str(g.nodes[c].get("value")) for c in _children(g, n) if g.nodes[c].get("kind") == "attr"]
        return any(v and v.lower() in words or (len(v) >= 3 and v.lower() in low) for v in vals)

    def first_line(n: str) -> int:
        return (g.nodes[n].get("lines") or [10**9])[0]

    rel = [n for n in objs if related(n)]
    # 相关对象的祖先也给出（编号路径要完整）
    keep: set[str] = set()
    for n in rel:
        x = n
        while x and x != graphmod.DEVICE:
            keep.add(x)
            preds = [a for a, _, d in g.in_edges(x, data=True) if d.get("kind") == "contains"]
            x = preds[0] if preds else ""
    rest = sorted((n for n in objs if n not in keep), key=lambda n: (n.count("/"), first_line(n)))
    chosen = sorted(keep, key=first_line) + rest
    return chosen[:MAX_OBJECTS]


def _schema_rows(kb: Any, profile: str, domains: set[str]) -> list[str]:
    sup = _supported(kb, profile)
    rows = []
    for sid, sn in kb.nodes.items():
        if sn.deprecated or (sup and not sup.get(sid, False)) or (domains and sn.domain not in domains):
            continue
        spec = sn.type
        if sn.type == "object":
            spec += f" key({','.join(sn.key) or 'name'})"
        if sn.range:
            spec += f" {sn.range[0]}..{sn.range[1]}"
        if sn.choices:
            spec += " " + "/".join(sn.choices)
        if sn.ref:
            spec += f" -> {sn.ref}"
        rows.append(f"{sid} | {spec} | parent {_owner_schema(kb, sid) or '-'}")
    return rows


def _intent_build(env: Env, params: dict[str, Any]) -> Context:
    from lmesh.core.ai_suggest_skills import _device_row

    g, ver, dev = _device_row(env, int(params["device_id"]))
    intent = str(params.get("intent") or "")
    objects: dict[str, dict[str, Any]] = {
        "d1": {"type": "device", "label": dev.name, "device_id": dev.id, "version_id": ver.id}
    }
    names: set[str] = {dev.name}
    ref_of: dict[str, str] = {graphmod.DEVICE: "d1"}
    rows = []
    for i, nid in enumerate(_intent_objects(g, intent), 1):
        d = g.nodes[nid]
        ref = f"n{i}"
        ref_of[nid] = ref
        lines = d.get("lines") or []
        label = graphmod._key_text(d.get("key")) or nid
        objects[ref] = {
            "type": d.get("schema"),
            "label": label,
            "device": "d1",
            "node": nid,
            "line": lines[0] if lines else None,
        }
        names.add(label)
        attrs = []
        for c in _children(g, nid):
            cd = g.nodes[c]
            if cd.get("kind") != "attr" or cd.get("origin") == "default":
                continue
            if isinstance(cd.get("value"), str):
                names.add(cd["value"])
            attrs.append(f"{cd.get('schema')}={_short(cd.get('value'), 40)}")
        preds = [a for a, _, e in g.in_edges(nid, data=True) if e.get("kind") == "contains"]
        parent = ref_of.get(preds[0], "?") if preds else "d1"
        rows.append(f"{ref} | {d.get('schema')} | {_short(label)} | parent {parent} | {'; '.join(attrs[:12])}")
    profile = str(g.graph.get("profile") or dev.profile or "")
    domains = {str(n.domain) for s in {g.nodes[x].get("schema") for x in g} if s and (n := env.kb.nodes.get(s))}
    domains |= {"interface", "vrf", "static-route", "bgp", "routing-policy"}
    numbers = {
        "lines": len(ver.raw_text.splitlines()),
        "objects": sum(1 for _, d in g.nodes(data=True) if d.get("kind") == "object"),
    }
    vars_ = {
        "device": f"d1 | {dev.name} | vendor={dev.vendor} | profile={profile or '-'}",
        "intent": intent,
        "objects": "\n".join(rows) or "(none)",
        "schema": "\n".join(_schema_rows(env.kb, profile, domains)),
        "lang": LANG_NAMES.get(env.lang, "English"),
    }
    facts = {
        "objects": objects,
        "numbers": numbers,
        "lines": {"d1": numbers["lines"]},
        "names": sorted(names)[:MAX_NAMES],
        "intent": intent,
        "profile": profile,
    }
    return Context(vars_, facts, f"change:{dev.id}", dev.id)


# ---------------------------------------------------------------- 取值检查


_IFNAME_RX = re.compile(r"^[A-Za-z][\w\-/.:]*$")
_COMMUNITY_RX = re.compile(r"^(\d+:\d+|[a-z][a-z-]*)$")


def check_value(sn: Any, value: Any) -> tuple[Any, str | None]:
    """按 Schema 节点类型检查一个取值（AI 给出的属性值或键）：返回 (规范化后的取值, 问题说明或 None)。"""
    from lmesh.core.kb import mapping

    t = sn.type
    if value is None or (isinstance(value, str) and not value.strip()):
        return value, "empty"
    if isinstance(value, dict | list):
        return value, "not_scalar"
    s = str(value).strip()
    try:
        if t == "integer":
            if isinstance(value, bool) or not re.fullmatch(r"-?\d+", s):
                return value, "not_integer"
            n = int(s)
            if sn.range and not sn.range[0] <= n <= sn.range[1]:
                return n, f"out_of_range {sn.range[0]}..{sn.range[1]}"
            return n, None
        if t in ("boolean", "flag"):
            if isinstance(value, bool):
                return value, None
            if s.lower() in ("true", "false"):
                return s.lower() == "true", None
            return value, "not_boolean"
        if t == "enum":
            hit = next((c for c in sn.choices or [] if c.lower() == s.lower()), None)
            return (hit, None) if hit is not None else (s, f"not_choice {'/'.join(sn.choices or [])}")
        if t == "ipv4":
            return str(ipaddress.IPv4Address(s)), None
        if t == "mask":
            if s.isdigit() and 0 <= int(s) <= 32:
                return s, None
            ipaddress.IPv4Network(f"0.0.0.0/{s}")
            return s, None
        if t == "prefix":
            ipaddress.IPv4Interface(s)
            return mapping.normalize("prefix", sn.id, s), None
        if t == "rd":
            left, sep, right = s.rpartition(":")
            if not sep or not right.isdigit() or not left:
                return s, "bad_rd"
            if left.count(".") == 3:
                ipaddress.IPv4Address(left)
            elif not re.fullmatch(r"\d+(\.\d+)?", left):
                return s, "bad_rd"
            return s, None
        if t == "asn":
            return (s, None) if re.fullmatch(r"\d+(\.\d+)?", s) else (s, "bad_asn")
        if t == "community":
            return (s, None) if _COMMUNITY_RX.match(s) else (s, "bad_community")
        if t == "interface":
            return (s, None) if _IFNAME_RX.match(s) else (s, "bad_interface")
        if t == "string":
            return (s, None) if "\n" not in s and len(s) <= 255 else (s, "bad_string")
        if t == "text":
            return (s, None) if "\n" not in s and len(s) <= 1000 else (s, "bad_text")
        if t == "ref":
            return (s, None) if "\n" not in s and len(s) <= 255 else (s, "bad_ref")
    except ValueError:
        return s, f"bad_{t}"
    return s, None


# ---------------------------------------------------------------- 把改动应用到目标图


class EditError(ValueError):
    def __init__(self, code: str, ref: str = "", detail: str = ""):
        super().__init__(code)
        self.code, self.ref, self.detail = code, ref, detail

    def reason(self) -> dict[str, Any]:
        return reason(self.code, ref=self.ref or None, detail=self.detail or None)


def apply_edits(
    g: nx.MultiDiGraph, kb: Any, edits: list[Any], facts: dict[str, Any]
) -> tuple[nx.MultiDiGraph, set[str], list[str]]:
    """AI 的改动 → 目标图（副本）。返回 (目标图, 改动涉及的节点, 改动里出现的新名称)；不合法时抛出 EditError。

    改动：{"op": "set", "target": "n3", "attr": "interface.mtu", "value": 9000}；{"op": "unset", "target": "n3",
    "attr": "interface.description"}；{"op": "add", "id": "+1", "parent": "n2" | "d1" | "+k", "schema": "interface",
    "key": "GE0/2/6.2458" | {字段: 值}, "attrs": {"interface.vrf": "RAN"}}；{"op": "delete", "target": "n5"}。"""
    if not isinstance(edits, list) or not edits:
        raise EditError("no_edits")
    if len(edits) > MAX_EDITS:
        raise EditError("too_large")
    objs = facts.get("objects") or {}
    profile = str(facts.get("profile") or g.graph.get("profile") or "")
    sup = _supported(kb, profile)
    present = {str(d.get("schema")) for _, d in g.nodes(data=True) if d.get("schema")}
    h = g.copy()
    h.graph = dict(g.graph)
    touched: set[str] = set()
    new_names: list[str] = []
    alias: dict[str, str] = {}

    def node_of(ref: Any, allow_device: bool = False) -> str:
        r = str(ref or "")
        if r in alias:
            return alias[r]
        o = objs.get(r)
        if o is None or (o.get("type") == "device" and not allow_device):
            raise EditError("ref_not_found", r)
        nid = graphmod.DEVICE if o.get("type") == "device" else str(o.get("node") or "")
        if nid not in h:
            raise EditError("ref_not_found", r, "deleted")
        return nid

    def schema_ok(sid: str) -> Any:
        sn = kb.nodes.get(sid)
        if sn is None:
            raise EditError("schema_unknown", sid)
        if sup and not sup.get(sid, False) and sid not in present:
            raise EditError("profile_unsupported", sid, profile)
        return sn

    def set_attr(owner: str, sid: str, value: Any) -> None:
        sn = schema_ok(sid)
        if sn.type == "object":
            raise EditError("schema_mismatch", sid, "object")
        osch = h.nodes[owner].get("schema")
        if _owner_schema(kb, sid) != osch:
            raise EditError("schema_mismatch", sid, str(osch))
        norm, bad = check_value(sn, value)
        if bad:
            raise EditError("bad_value", f"{sid}={value}", bad)
        from lmesh.core.kb import mapping

        norm = mapping.normalize(sn.type, sn.id, norm)
        nid = f"{owner}/{graphmod._short(sid, osch)}"
        if nid not in h:
            h.add_node(nid, kind="attr", schema=sid, origin="explicit", lines=[], cards=[])
            h.add_edge(owner, nid, kind="contains")
        raw = ("true" if norm else "false") if isinstance(norm, bool) else str(value)
        # 新取值不再对应原配置的行：清掉行号与命令卡，脚本按新值由规范渲染生成
        h.nodes[nid].update(value=norm, raw=raw, origin="explicit", negated=False, lines=[], cards=[])
        touched.add(nid)
        if isinstance(norm, str):
            new_names.append(norm)

    for i, e in enumerate(edits, 1):
        if not isinstance(e, dict):
            raise EditError("bad_edit", f"#{i}")
        op = str(e.get("op") or "")
        if op not in EDIT_OPS:
            raise EditError("bad_edit", f"#{i}", op)
        if op in ("set", "unset"):
            owner = node_of(e.get("target"))
            if h.nodes[owner].get("kind") != "object":
                raise EditError("schema_mismatch", str(e.get("target")), "not an object")
            sid = str(e.get("attr") or "")
            if op == "set":
                set_attr(owner, sid, e.get("value"))
            else:
                schema_ok(sid)
                nid = f"{owner}/{graphmod._short(sid, h.nodes[owner].get('schema'))}"
                if nid not in h or h.nodes[nid].get("origin") == "default":
                    raise EditError("attr_not_set", f"{e.get('target')}:{sid}")
                h.remove_node(nid)
                touched.add(nid)
        elif op == "delete":
            nid = node_of(e.get("target"))
            sub = _subtree(h, nid)
            touched.update(sub)
            h.remove_nodes_from(sub)
        else:  # add
            sid = str(e.get("schema") or "")
            sn = schema_ok(sid)
            if sn.type != "object":
                raise EditError("schema_mismatch", sid, "not an object")
            want = _owner_schema(kb, sid)
            parent = node_of(e.get("parent") or "d1", allow_device=True)
            if (h.nodes[parent].get("schema") if parent != graphmod.DEVICE else None) != want:
                raise EditError("schema_mismatch", f"{e.get('parent') or 'd1'}→{sid}", str(want or "device"))
            key = e.get("key")
            fields = list(sn.key) or ["name"]
            from lmesh.core import compare as cmp

            sch = cmp._Schema(kb)
            if len(fields) > 1:
                if not isinstance(key, dict) or not any(key.get(f) not in (None, "") for f in fields):
                    raise EditError("bad_key", sid, ",".join(fields))
                unknown = set(key) - set(fields)
                if unknown:
                    raise EditError("bad_key", sid, ",".join(sorted(unknown)))
                kv: Any = {f: (None if key.get(f) in (None, "") else str(key.get(f))) for f in fields}
                for f, v in kv.items():
                    ft = kb.nodes.get(f"{sid}.{f}")
                    if v is not None and ft is not None and ft.type != "object":
                        _, bad = check_value(ft, v)
                        if bad:
                            raise EditError("bad_value", f"{sid}.{f}={v}", bad)
            else:
                if isinstance(key, dict):
                    key = next(iter(key.values()), None)
                if key in (None, "") or isinstance(key, list | dict):
                    raise EditError("bad_key", sid, fields[0])
                ft_type, _ = sch.field_type(sn, fields[0])
                fake = type("N", (), {"type": ft_type, "range": None, "choices": None, "id": sid})()
                _, bad = check_value(fake, key)
                if bad:
                    raise EditError("bad_value", f"{sid}={key}", bad)
                kv = str(key).strip()
            seg = f"{graphmod._short(sid, h.nodes[parent].get('schema'))}[{graphmod._key_text(kv)}]"
            nid = seg if parent == graphmod.DEVICE else f"{parent}/{seg}"
            if nid in h:
                raise EditError("already_exists", graphmod._key_text(kv))
            h.add_node(nid, kind="object", schema=sid, origin="explicit", lines=[], cards=[], key=kv, raw=kv)
            h.add_edge(parent, nid, kind="contains")
            touched.add(nid)
            new_names += [str(v) for v in (kv.values() if isinstance(kv, dict) else [kv]) if v]
            attrs = e.get("attrs") or {}
            if not isinstance(attrs, dict):
                raise EditError("bad_edit", f"#{i}", "attrs")
            for f in fields:  # 键字段同时是属性（interface.ipv4.address）时自动写上
                fv = kv.get(f) if isinstance(kv, dict) else kv
                fsn = kb.nodes.get(f"{sid}.{f}")
                if fv not in (None, "") and fsn is not None and fsn.type != "object" and fsn.id not in attrs:
                    attrs = {**attrs, fsn.id: fv}
            for asid, av in attrs.items():
                set_attr(nid, str(asid), av)
            if e.get("id"):
                alias[str(e["id"])] = nid
    return h, touched, new_names


# ---------------------------------------------------------------- 生成脚本、影响分析与模拟执行


def plan_edits(cur: nx.MultiDiGraph, edited: nx.MultiDiGraph, touched: set[str], kb: Any, lang: str) -> dict[str, Any]:
    """目标图 → 增量变更（现有 core/change.py）：先在当前配置上模拟执行得到目标配置文本、重新解析建图，确认每个改动都
    落到了图上；再用重新解析的目标图生成下发与回滚脚本、影响分析与模拟执行的验证。返回 {ok, reasons, change, ...}。"""
    from lmesh.core import analysis, change, checks, compare

    reasons: list[dict[str, Any]] = []
    try:
        p = change._Planner(cur, edited, kb)
        ops = p.run()
    except change.ChangeError as e:
        return {"ok": False, "reasons": [reason("plan_failed", detail=e.key)]}
    if p.unsupported:
        for u in p.unsupported[:5]:
            reasons.append(reason("cannot_render", ref=str(u.get("node") or u.get("schema") or "")))
        return {"ok": False, "reasons": reasons}
    sim = change._Sim(p)
    for op in ops:
        sim.apply(op)
    after_text = sim.text()
    profile = str(cur.graph.get("profile"))
    res = analysis.parse_text(after_text, kb, profile)
    after = graphmod.build(res.parsed, kb, res.profile, str(cur.graph.get("device") or "device"))
    # 每个改动都要落到图上：目标图里有、重新解析的图里没有或取值不同的，说明这条改动写不出来
    diff = compare.compare(compare.Side(after, "after"), compare.Side(edited, "edited"), kb)
    for d in diff["diffs"]:
        if d["kind"] in ("added", "changed", "renamed"):
            reasons.append(reason("edit_not_realized", ref=str(d["node"])))
    if reasons:
        return {"ok": False, "reasons": reasons[:10]}
    # 引用必须存在：重新解析后新出现的悬空引用（引用了不存在的对象、删掉了还被引用的对象）
    old = {(x["referrer"], str(x["target_type"]), str(x["value"])) for x in checks.dangling(cur, kb)}
    for x in checks.dangling(after, kb):
        if (x["referrer"], str(x["target_type"]), str(x["value"])) not in old:
            reasons.append(reason("ref_missing", ref=f"{x['target_type']}:{x['value']}"))
    if reasons:
        return {"ok": False, "reasons": reasons[:10]}
    r = change.change(compare.Side(cur, "current"), compare.Side(after, "target"), kb, lang=lang)
    if r["equal"]:
        return {"ok": False, "reasons": [reason("no_change")], "change": r}
    if not (r.get("verify") or {}).get("ok"):
        reasons.append(reason("simulation_failed", detail=_verify_text(r.get("verify"))))
    if not ((r.get("rollback") or {}).get("verify") or {}).get("ok", True):
        reasons.append(reason("rollback_failed", detail=_verify_text(r["rollback"].get("verify"))))
    for op in r["ops"]:
        if op["action"] in ("side_effect", "mutex"):
            reasons.append(reason("side_effect", "warn", ref=str(op.get("label") or op["text"])))
    if r["risk"]["level"] == "high" and not any(x["code"] == "side_effect" for x in reasons):
        reasons.append(reason("high_risk", "warn"))
    return {
        "ok": not any(x["level"] == "reject" for x in reasons),
        "reasons": reasons,
        "change": r,
        "after": after_text,
    }


def _verify_text(v: dict[str, Any] | None) -> str:
    if not v:
        return ""
    parts = []
    if v.get("diff_count"):
        parts.append(f"diffs={v['diff_count']}")
    if v.get("new_dangling"):
        parts.append(f"dangling={len(v['new_dangling'])}")
    if v.get("order_violations"):
        parts.append(f"order={len(v['order_violations'])}")
    if v.get("issues"):
        parts.append(f"issues={len(v['issues'])}")
    return ", ".join(parts)


def _ai_rows(r: dict[str, Any], touched: set[str]) -> list[dict[str, Any]]:
    """脚本逐行：ai=True 表示这一行来自 AI 的改动（命令涉及的节点在改动范围内）；code=True 是代码补发的
    （副作用、互斥）；其余是视图进出等结构行。"""

    def under(n: str) -> bool:
        return n in touched or any(n.startswith(t + "/") for t in touched)

    by_seq = {op["seq"]: op for op in r["ops"]}
    out = []
    for row in r["script_rows"]:
        op = by_seq.get(row["seq"]) if row["seq"] is not None else None
        kind = "frame"
        if op is not None:
            if op["action"] in ("side_effect", "mutex"):
                kind = "code"
            elif any(under(n) for n in op["target_nodes"] + op["current_nodes"]):
                kind = "ai"
            else:
                kind = "code"
        out.append({"text": "  " * int(row["depth"]) + row["text"], "k": kind, "seq": row["seq"]})
    return out


def _edit_lines(edits: list[Any], facts: dict[str, Any]) -> list[str]:
    """改动的显示（代码从改动生成，对象名由代码填入）。"""
    objs = facts.get("objects") or {}

    def name(ref: Any) -> str:
        o = objs.get(str(ref or ""))
        return f"{o.get('type')} {o.get('label')}" if o else str(ref or "")

    out = []
    for e in edits[:MAX_EDITS]:
        if not isinstance(e, dict):
            continue
        op = e.get("op")
        if op == "set":
            out.append(f"~ {name(e.get('target'))}: {e.get('attr')} = {e.get('value')}")
        elif op == "unset":
            out.append(f"- {name(e.get('target'))}: {e.get('attr')}")
        elif op == "delete":
            out.append(f"- {name(e.get('target'))}")
        elif op == "add":
            key = e.get("key")
            kt = graphmod._key_text(key) if isinstance(key, dict) else str(key)
            out.append(f"+ {e.get('schema')} {kt}  ({name(e.get('parent') or 'd1')})")
            for k, v in (e.get("attrs") or {}).items() if isinstance(e.get("attrs"), dict) else []:
                out.append(f"    {k} = {v}")
    return out


def _edits_of(content: dict[str, Any]) -> list[Any]:
    e = content.get("edits")
    return e if isinstance(e, list) else []


def graph_of(env: Env, facts: dict[str, Any], ref: str = "d1") -> nx.MultiDiGraph:
    """事实里设备 ref 的配置图：按记下的配置版本重新建图（运行时），或用事实里给出的配置文本（skill 管理页的样例回放）。"""
    from lmesh.core import analysis, graphstore

    o = (facts.get("objects") or {}).get(ref) or {}
    text = (facts.get("configs") or {}).get(ref)
    if o.get("version_id") is not None:
        try:
            g, _, _ = graphstore.build_for_version(env.db, int(o["version_id"]), env.kb)
            return g
        except KeyError as e:
            if text is None:
                raise SuggestError("ai_suggest.device_not_found", "not_found", id=o.get("device_id")) from e
    if text is None:
        raise SuggestError("ai_suggest.device_not_found", "not_found", id=ref)
    prof = o.get("profile") or facts.get("profile")
    res = analysis.parse_text(str(text), env.kb, prof if prof in env.kb.profiles else None)
    return graphmod.build(res.parsed, env.kb, res.profile, str(o.get("label") or ref))


def evaluate_edits(env: Env, edits: list[Any], facts: dict[str, Any]) -> dict[str, Any]:
    """一组改动的完整校验：应用到目标图 → 生成脚本 → 模拟执行。返回 {reasons, change?, rows?, touched, names}。"""
    cur = graph_of(env, facts)
    try:
        edited, touched, names = apply_edits(cur, env.kb, edits, facts)
    except EditError as e:
        return {"reasons": [e.reason()], "touched": set(), "names": []}
    res = plan_edits(cur, edited, touched, env.kb, env.lang)
    out: dict[str, Any] = {"reasons": res["reasons"], "touched": touched, "names": names}
    if res.get("change") is not None:
        out["change"] = res["change"]
        out["rows"] = _ai_rows(res["change"], touched)
    return out


def _summary_of(r: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    by = r["summary"]["by_action"]
    imp = (r.get("impact") or {}).get("summary") or {}
    return {
        "summary": {
            "ops": r["summary"]["ops"],
            "risk": r["risk"]["level"],
            "impact_objects": imp.get("objects", 0),
            "impact_business": imp.get("business", 0),
            "verify": bool((r.get("verify") or {}).get("ok")),
            "rollback_verify": bool(((r.get("rollback") or {}).get("verify") or {}).get("ok")),
            "ai_lines": sum(1 for x in rows if x["k"] == "ai"),
        },
        "result": {
            "lines_added": by.get("add", 0),
            "lines_removed": by.get("delete", 0),
            "lines_overridden": by.get("modify", 0) + by.get("side_effect", 0) + by.get("mutex", 0),
        },
    }


def _check_graph_edit(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    c = d["content"]
    edits = _edits_of(c)
    if not edits:
        return [reason("no_edits")]
    ev = evaluate_edits(env, edits, facts)
    out: list[dict[str, Any]] = list(ev["reasons"])
    lines = [{"text": t, "k": "ai"} for t in _edit_lines(edits, facts)]
    if ev.get("change") is not None:
        r = ev["change"]
        rows = ev["rows"]
        lines += [{"text": "", "k": "frame"}] + [{"text": x["text"], "k": x["k"]} for x in rows]
        env.out["result"] = {**_summary_of(r, rows), "lines": lines}
    else:
        env.out["result"] = {"lines": lines}
    if c.get("explain"):  # 说明文字：图中没有的对象拒绝（改动里新建的名称可以出现）
        f2 = {**facts, "names": list(facts.get("names") or []) + ev.get("names", [])}
        out += [x for x in check_text(str(c["explain"]), f2) if x["level"] == "reject"]
        env.out["segments"] = base.text_segments(str(c["explain"]), facts)
    return out


def _batch_rows(env: Env, row: AISuggestion, include: bool) -> list[AISuggestion]:
    """同一次运行中已采纳的改动（按编号），include 时加上这一条。"""
    from sqlalchemy import select

    from lmesh.core import store

    with store.session(env.db) as s:
        rows = list(
            s.scalars(
                select(AISuggestion)
                .where(
                    AISuggestion.batch_id == row.batch_id,
                    AISuggestion.category == "graph_edit",
                    AISuggestion.status == "adopted",
                    AISuggestion.id != row.id,
                )
                .order_by(AISuggestion.id)
            )
        )
        for r in rows:
            s.expunge(r)
    if include:
        rows = sorted([*rows, row], key=lambda r: r.id)
    return rows


def combined(env: Env, rows: list[AISuggestion], facts: dict[str, Any]) -> dict[str, Any] | None:
    """几条采纳的改动合并后的变更（脚本、回滚、影响、模拟）；没有改动时 None。"""
    edits: list[Any] = []
    for r in rows:
        edits += _edits_of(r.content or {})
    if not edits:
        return None
    return evaluate_edits(env, edits, facts)


def _script_texts(r: dict[str, Any], facts: dict[str, Any]) -> tuple[str, str]:
    head = f"intent: {_short(facts.get('intent') or '', 200)}"
    fam_comment = "#"
    return (
        f"{fam_comment} {head}\n{r['script']}",
        f"{fam_comment} rollback · {head}\n{(r.get('rollback') or {}).get('script', '')}",
    )


def _script_content(env: Env, info: dict[str, Any]) -> str | None:
    """代码生成的项目脚本的当前内容；脚本已被删除时 None。"""
    from lmesh.core import checkproj

    try:
        sc = checkproj.get_script(env.db, _actor(env), int(info["group_id"]), int(info["script_id"]))
    except (checkproj.ProjectError, KeyError, TypeError, ValueError):
        return None
    return str(sc.get("content") or "")


def _latest_info(rows: list[AISuggestion]) -> dict[str, Any] | None:
    for r in sorted(rows, key=lambda x: x.decided_at or x.created_at, reverse=True):
        info = r.adopt_info or {}
        if info.get("action") == "script" and info.get("group_id"):
            return info
    return None


def _same_scripts(env: Env, info: dict[str, Any], want: tuple[str, str] | None) -> bool:
    """项目脚本还是代码上次写入的内容（没有被人改过）。"""
    got = _script_content(env, info)
    return got is not None and want is not None and got == want[0].replace(chr(13) + chr(10), chr(10))


def _adopt_graph_edit(env: Env, row: AISuggestion, facts: dict[str, Any]) -> dict[str, Any]:
    """采纳：这一次运行里已采纳的改动加上这一条，合并后重新校验（不通过 409），生成项目脚本（下发 + 回滚）。
    同一次运行之前采纳生成的脚本没被人改过时更新它，否则另建一份。"""
    from lmesh.core import checkproj, graphstore

    d1 = (facts.get("objects") or {}).get("d1") or {}
    ver = graphstore.latest_version(env.db, int(d1.get("device_id") or 0))
    if ver is None or ver.id != d1.get("version_id"):
        raise SuggestError("ai_suggest.device_changed", "state", id=d1.get("device_id"))
    prev = _batch_rows(env, row, False)
    ev = combined(env, [*prev, row], facts)
    if ev is None or ev.get("change") is None or any(x["level"] == "reject" for x in ev["reasons"]):
        raise SuggestError(
            "ai_suggest.check_failed", "state", data={"check": {"reasons": (ev or {}).get("reasons")}}, id=row.id
        )
    fwd, rb = _script_texts(ev["change"], facts)
    actor = _actor(env)
    info = _latest_info(prev)
    if info is not None:
        old = combined(env, prev, facts)
        old_txt = _script_texts(old["change"], facts) if old and old.get("change") else None
        if _same_scripts(env, info, old_txt):
            checkproj.update_script(env.db, actor, int(info["group_id"]), int(info["script_id"]), {"content": fwd})
            if info.get("rollback_id"):
                checkproj.update_script(env.db, actor, int(info["group_id"]), int(info["rollback_id"]), {"content": rb})
            return {**info, "updated": True, "ops": ev["change"]["summary"]["ops"]}
    name = f"AI · {_short(facts.get('intent') or row.title or row.id, 60)}"
    r = checkproj.create_project_script(
        env.db, actor, {"name": name[:200], "kind": "change", "device_id": d1.get("device_id"), "content": fwd}
    )
    gid = r["group"]["id"]
    rbs = checkproj.create_script(
        env.db, actor, gid, {"name": f"{name} · rollback"[:200], "kind": "change", "content": rb}
    )
    return {
        "action": "script",
        "group_id": gid,
        "script_id": r["script"]["id"],
        "rollback_id": rbs["id"],
        "device_id": d1.get("device_id"),
        "ops": ev["change"]["summary"]["ops"],
    }


def _revert_graph_edit(env: Env, row: AISuggestion) -> dict[str, Any]:
    """撤销：项目脚本还是代码写入的内容时，去掉这一条改动重新生成（没有剩下的改动时删除脚本）；被人改过时 409。"""
    from lmesh.core import checkproj, store
    from lmesh.core.store.models import AISuggestionBatch

    info = row.adopt_info or {}
    with store.session(env.db) as s:
        b = s.get(AISuggestionBatch, row.batch_id)
        facts = dict(b.context or {}) if b is not None else {}
    others = _batch_rows(env, row, False)
    mine = [r for r in others if (r.adopt_info or {}).get("group_id") == info.get("group_id")]
    before = combined(env, sorted([*mine, row], key=lambda r: r.id), facts)
    want = _script_texts(before["change"], facts) if before and before.get("change") else None
    if _script_content(env, info) is None:
        return {"action": "none"}
    if not _same_scripts(env, info, want):
        raise SuggestError("ai_suggest.script_modified", "state", id=info.get("script_id"))
    actor = _actor(env)
    if not mine:
        checkproj.delete_project(env.db, actor, int(info["group_id"]))
        return {"action": "script_deleted", "script_id": info.get("script_id")}
    after = combined(env, mine, facts)
    if after is None or after.get("change") is None:
        raise SuggestError("ai_suggest.check_failed", "state", id=row.id)
    fwd, rb = _script_texts(after["change"], facts)
    checkproj.update_script(env.db, actor, int(info["group_id"]), int(info["script_id"]), {"content": fwd})
    if info.get("rollback_id"):
        checkproj.update_script(env.db, actor, int(info["group_id"]), int(info["rollback_id"]), {"content": rb})
    return {"action": "script_updated", "script_id": info.get("script_id")}


register_category("graph_edit", Validator(_check_graph_edit, _adopt_graph_edit, _revert_graph_edit, batch=False))
register_skill(
    SkillSpec(
        id="intent-script",
        build=_intent_build,
        categories=("graph_edit",),
        default_category="graph_edit",
        scope="device",
        prepare=_prepare_intent,
    )
)


def intent_plan(env: Env, batch_id: int) -> dict[str, Any]:
    """一次运行中已采纳的全部改动合并后的变更：脚本逐行（标出来自 AI 改动的行）、回滚脚本、影响分析、模拟执行
    与生成的项目脚本（界面“变更脚本”区）。没有采纳的改动时 adopted=0。"""
    from sqlalchemy import select

    from lmesh.core import store
    from lmesh.core.store.models import AISuggestionBatch

    with store.session(env.db) as s:
        b = base._batch(s, env, batch_id)
        if b.skill != "intent-script":
            raise SuggestError("ai_suggest.batch_not_found", "not_found", id=batch_id)
        facts = dict(b.context or {})
        rows = list(
            s.scalars(
                select(AISuggestion)
                .where(
                    AISuggestion.batch_id == batch_id,
                    AISuggestion.category == "graph_edit",
                    AISuggestion.status == "adopted",
                )
                .order_by(AISuggestion.id)
            )
        )
        for r in rows:
            s.expunge(r)
        _ = AISuggestionBatch
    out: dict[str, Any] = {"batch_id": batch_id, "adopted": [r.id for r in rows], "intent": facts.get("intent")}
    if not rows:
        return out
    ev = combined(env, rows, facts)
    if ev is None or ev.get("change") is None:
        out["reasons"] = (ev or {}).get("reasons") or []
        return out
    r = ev["change"]
    out.update(
        rows=ev["rows"],
        rollback=(r.get("rollback") or {}).get("script_plain", ""),
        script=r["script_plain"],
        impact=(r.get("impact") or {}).get("summary") or {},
        risk=r["risk"],
        verify=bool((r.get("verify") or {}).get("ok")),
        rollback_verify=bool(((r.get("rollback") or {}).get("verify") or {}).get("ok")),
        summary=r["summary"],
        reasons=ev["reasons"],
        script_info=_latest_info(rows),
    )
    return out


# ================================================================ 2. 割接方案文档（plan_section）

_CLI_VERBS = re.compile(
    r"\b(undo\s+\S+|no\s+(?:shutdown|ip|ipv6|interface|bgp|router|neighbor|peer|vlan|description|mpls|route|vrf)\b"
    r"|reset\s+(?:bgp|ospf|isis|mpls|counters|arp|ip|lldp|interface|saved-configuration|ldp)\b"
    r"|display\s+(?:current|interface|ip|bgp|ospf|isis|mpls|vlan|lldp|arp|version|device|alarm|this|saved|bfd|vrrp)\b"
    r"|show\s+(?:run|running|ip|ipv6|interface|interfaces|bgp|ospf|isis|mpls|vlan|lldp|arp|version|bfd|vrrp|router"
    r"|service|port|log|configuration)\b"
    r"|system-view|configure\s+terminal|commit\b|copy\s+running|write\s+memory|save\s+force"
    r"|clear\s+(?:ip|bgp|counters|arp)\b|admin\s+(?:save|display-config|show)|reboot\b|reload\b)",
)
_MENTION_ANY = re.compile(r"\[\[[^\]]{1,40}\]\]|<<[^>]{1,80}>>")
_ASCII_RUN = re.compile(r"[A-Za-z][\x20-\x7e]*[A-Za-z0-9]")


def command_hits(text: str, kb: Any, families: list[str]) -> list[str]:
    """文字里直接写出的设备命令（割接方案等说明文字不允许）：代码格式、常见的运维命令，以及能被平台族命令卡
    在根视图识别为命令的片段。返回命中的片段。"""
    from lmesh.core import parser as parsemod

    if "`" in text:
        i = text.index("`")
        return [text[i : i + 40]]
    plain = _MENTION_ANY.sub(" X ", text)
    hits = [m.group(0) for m in _CLI_VERBS.finditer(plain)]
    if hits:
        return hits[:5]
    cands: list[str] = []
    for run in _ASCII_RUN.findall(plain):
        toks = run.split()
        for i in range(len(toks)):
            if toks[i].lower() in ("no", "undo", "not"):  # 取消形式由上面的写法识别；英文的 no / not 不当命令
                continue
            for k in range(2, 7):
                if i + k <= len(toks):
                    cands.append(" ".join(toks[i : i + k]))
    if not cands:
        return []
    out: list[str] = []
    for fam in families:
        if fam not in kb.families:
            continue
        parsed = parsemod.parse("\n".join(cands[:400]), kb, fam)
        out += [ln.raw for ln in parsed.lines if ln.kind == "command" and ln.raw.strip()]
    return out[:5]


def _prepare_cutover(env: Env, params: dict[str, Any]) -> None:
    _prepare_device(env, params)
    to = str(params.get("to") or "")
    if to not in env.kb.profiles:
        raise SuggestError("ai_suggest.need_target_profile", "param", profile=to)
    params["to"] = to
    tid = params.get("target_device_id")
    if tid not in (None, ""):
        p2: dict[str, Any] = {"device_id": tid}
        _prepare_device(env, p2)
        params["target_device_id"] = p2["device_id"]
    else:
        params.pop("target_device_id", None)


def _rules(env: Env, rid: Any) -> Any:
    if not rid:
        return None
    from lmesh.core import kbservice, naming

    try:
        return naming.load(kbservice.runtime_root(env.settings), str(rid), env.kb)
    except naming.RulesError as e:
        raise SuggestError("ai_suggest.rules_not_found", "not_found", id=rid) from e


def _step_label(st: dict[str, Any], lang: str) -> str:
    from lmesh.core import i18n

    return i18n.t(st["key"], lang, **dict(st.get("params") or {}))


def _imap(params: dict[str, Any]) -> dict[str, str] | None:
    m = params.get("interface_map")
    return {str(k): str(v) for k, v in m.items()} or None if isinstance(m, dict) else None


def _cutover_build(env: Env, params: dict[str, Any]) -> Context:
    from lmesh.core import migration
    from lmesh.core.ai_suggest_skills import _device_row

    g, ver, dev = _device_row(env, int(params["device_id"]))
    to = str(params["to"])
    tg = tdev = None
    if params.get("target_device_id") is not None:
        tg, _, tdev = _device_row(env, int(params["target_device_id"]))
    try:
        res = migration.migrate(
            g,
            env.kb,
            str(g.graph.get("profile")),
            to,
            _imap(params),
            tg,
            params.get("model") or None,
            str(params.get("on_conflict") or "migrate"),
            verify=True,
            rules=_rules(env, params.get("rule_set")),
        )
    except migration.MigrateError as e:
        raise SuggestError(e.key, "param", **dict(getattr(e, "fmt", {}) or {})) from e
    target_label = (tdev.name if tdev else "") or str(params.get("model") or to)
    objects: dict[str, dict[str, Any]] = {
        "d1": {"type": "device", "label": dev.name, "device_id": dev.id, "version_id": ver.id},
        "d2": {"type": "new_device", "label": target_label, "profile": to},
    }
    if tdev is not None:
        objects["d2"].update(device_id=tdev.id, type="device")
    names: set[str] = {dev.name, target_label, to}
    numbers: dict[str, Any] = {}
    rows = []
    steps = []
    for st in res.get("steps") or []:
        ref = f"s{st['no']}"
        labels = {lg: _step_label(st, lg) for lg in ("zh-CN", "en", "pt-BR")}
        objects[ref] = {
            "type": "step",
            "label": labels.get(env.lang, labels["en"]),
            "labels": labels,
            "phase": st["phase"],
            "side": st["device"],
            "commands": len(st.get("commands") or []),
        }
        for k, v in (st.get("params") or {}).items():
            if isinstance(v, int) and not isinstance(v, bool):
                numbers[f"{ref}.{k}"] = v
        steps.append({"ref": ref, **st, "labels": labels})
        n_cmd = len(st.get("commands") or [])
        rows.append(f"{ref} | {st['phase']} | {st['device']} | {labels['en']} | {n_cmd} command lines")
    imap_rows = res.get("interface_map") or []
    for r in imap_rows:
        names.update(str(r.get(k)) for k in ("source", "target") if r.get(k))
    numbers.update(
        {
            "steps": len(steps),
            "interfaces": len([r for r in imap_rows if r.get("target")]),
            "unmapped": len(res.get("unmapped") or []),
            "warnings": len(res.get("warnings") or []),
            "unsupported": len(res.get("unsupported") or []),
            "config_lines": len(str(res.get("text") or "").splitlines()),
        }
    )
    for k, v in (res.get("stats") or {}).items():
        if isinstance(v, int) and not isinstance(v, bool):
            numbers.setdefault(f"stats.{k}", v)
    script = res.get("script") or {}
    vars_ = {
        "devices": f"d1 | old device {dev.name} | profile={g.graph.get('profile')}\n"
        f"d2 | new device {target_label} | profile={to}",
        "steps": "\n".join(rows) or "(none)",
        "facts": "\n".join(f"{k} = {v}" for k, v in numbers.items()),
        "lang": LANG_NAMES.get(env.lang, "English"),
    }
    facts = {
        "objects": objects,
        "numbers": numbers,
        "lines": {"d1": len(ver.raw_text.splitlines())},
        "names": sorted(names)[:MAX_NAMES],
        "steps": steps,
        "families": sorted({str(g.graph.get("family") or ""), env.kb.profiles[to].family} - {""}),
        "meta": {
            "device": dev.name,
            "target": target_label,
            "merge": tdev is not None,  # 并入新设备的现有配置（REQ-056-07：标题写“并入”）
            "from": str(g.graph.get("profile") or ""),
            "to": to,
            "kb_version": str(g.graph.get("kb_version") or ""),
            "script_available": bool(script.get("available")),
        },
    }
    return Context(vars_, facts, f"cutover:{dev.id}:{to}", dev.id)


def _plan_texts(c: dict[str, Any]) -> list[tuple[str, str]]:
    out = [("zh", str(c.get("zh") or "")), ("en", str(c.get("en") or ""))]
    for i, st in enumerate(c.get("steps") or [], 1):
        if isinstance(st, dict):
            for k in ("zh", "en", "check_zh", "check_en"):
                if st.get(k):
                    out.append((f"steps[{i}].{k}", str(st[k])))
    return out


def _lang_facts(facts: dict[str, Any], lang: str) -> dict[str, Any]:
    """事实的一个语言版本：步骤的显示名换成该语言（导出中文版 / 英文版时用）。"""
    objs = {}
    for k, o in (facts.get("objects") or {}).items():
        labels = o.get("labels")
        objs[k] = {**o, "label": labels.get(lang) or labels.get("en")} if isinstance(labels, dict) else o
    return {**facts, "objects": objs}


def _check_plan_section(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    c = d["content"]
    sec = str(c.get("section") or "")
    if sec not in PLAN_SECTIONS:
        return [reason("bad_section", ref=sec)]
    if not str(c.get("zh") or "").strip() or not str(c.get("en") or "").strip():
        return [reason("need_bilingual")]
    steps = c.get("steps") or []
    if not isinstance(steps, list):
        return [reason("bad_content")]
    out: list[dict[str, Any]] = []
    objs = facts.get("objects") or {}
    if sec in ("steps", "rollback") and not steps:
        out.append(reason("no_steps", "warn"))
    for st in steps:
        ref = str(st.get("step") or "") if isinstance(st, dict) else ""
        if (objs.get(ref) or {}).get("type") != "step":
            out.append(reason("ref_not_found", ref=ref))
    for where, text in _plan_texts(c):
        if len(text) > base.MAX_TEXT:
            return [reason("too_large")]
        out += check_text(text, facts)
        hits = command_hits(text, env.kb, list(facts.get("families") or []))
        if hits:
            out.append(reason("command_in_text", ref=hits[0], detail=where))
    lang = "zh-CN" if env.lang == "zh-CN" else "en"
    key = "zh" if lang == "zh-CN" else "en"
    f2 = _lang_facts(facts, lang)
    lines = [{"text": base.render_text(str(c.get(key) or ""), f2), "k": "ai"}]
    by_ref = {s.get("ref"): s for s in facts.get("steps") or []}
    for st in steps:
        if not isinstance(st, dict):
            continue
        code = by_ref.get(str(st.get("step") or ""))
        lines.append({"text": f"[{st.get('step')}] {base.render_text(str(st.get(key) or ''), f2)}", "k": "ai"})
        if code:
            lines += [{"text": f"    {x}", "k": "code"} for x in (code.get("commands") or [])[:12]]
        chk = st.get(f"check_{key}")
        if chk:
            lines.append({"text": f"    ✓ {base.render_text(str(chk), f2)}", "k": "ai"})
    env.out["result"] = {"lines": lines}
    env.out["segments"] = base.text_segments(str(c.get(key) or ""), f2)
    env.out["display"] = base.render_text(str(c.get(key) or ""), f2)
    return out


register_category("plan_section", Validator(_check_plan_section, base._adopt_record, base._revert_record))
register_skill(
    SkillSpec(
        id="cutover-plan",
        build=_cutover_build,
        categories=("plan_section",),
        default_category="plan_section",
        scope="device",
        prepare=_prepare_cutover,
    )
)

_DOC_T: dict[str, dict[str, Any]] = {
    "zh-CN": {
        "title": "割接方案：{device} 替换为 {target}",
        "title_merge": "割接方案：{device} 并入 {target}",
        "meta": "源 Profile {src} → 目标 Profile {to} · 知识库 {kb} · 生成 {date}",
        "note": "命令全部来自代码生成的割接步骤，AI 只撰写说明文字（只含已采纳的部分）。",
        "missing": "（这一节没有采纳的内容，需要人工填写）",
        "steps": "步骤清单（代码生成）",
        "action": "操作",
        "commands": "命令",
        "check": "检查点",
        "ai": "AI 撰写",
        "sec": {
            "overview": "概述与范围",
            "window": "时间窗口",
            "steps": "割接步骤",
            "checks": "检查点",
            "rollback": "回退条件与步骤",
            "risks": "风险与注意事项",
        },
    },
    "en": {
        "title": "Cutover plan: replace {device} with {target}",
        "title_merge": "Cutover plan: merge {device} into {target}",
        "meta": "Source profile {src} → target profile {to} · KB {kb} · generated {date}",
        "note": "Every command comes from the cutover steps generated by code; the AI only wrote the prose "
        "(adopted parts only).",
        "missing": "(Nothing adopted for this section; write it by hand.)",
        "steps": "Step list (generated by code)",
        "action": "Action",
        "commands": "Commands",
        "check": "Checkpoint",
        "ai": "AI-written",
        "sec": {
            "overview": "Overview and scope",
            "window": "Maintenance window",
            "steps": "Cutover steps",
            "checks": "Checkpoints",
            "rollback": "Rollback criteria and steps",
            "risks": "Risks and notes",
        },
    },
}


def plan_doc(env: Env, batch_id: int, lang: str = "zh-CN", adopted_only: bool = False) -> dict[str, Any]:
    """割接方案文档：标题与元数据（代码）、各节（采纳的 AI 文字；adopted_only=False 时也带上待处理的，供页面预览）、
    步骤清单（代码生成的命令按引用填入）。lang：zh-CN 或 en（中英双语，分别导出）。返回 {doc, markdown}；
    markdown 只含已采纳的部分。"""
    from datetime import UTC, datetime

    from sqlalchemy import select

    from lmesh.core import store

    lang = "zh-CN" if lang.lower().startswith("zh") else "en"
    T = _DOC_T[lang]
    key = "zh" if lang == "zh-CN" else "en"
    with store.session(env.db) as s:
        b = base._batch(s, env, batch_id)
        if b.skill != "cutover-plan":
            raise SuggestError("ai_suggest.batch_not_found", "not_found", id=batch_id)
        facts = _lang_facts(dict(b.context or {}), lang)
        created = b.created_at
        rows = list(s.scalars(select(AISuggestion).where(AISuggestion.batch_id == batch_id).order_by(AISuggestion.id)))
        items: list[dict[str, Any]] = [
            {"id": r.id, "status": r.status, "check": r.check_status, "content": dict(r.content or {})} for r in rows
        ]
    meta = facts.get("meta") or {}
    date = (created or datetime.now(UTC)).strftime("%Y-%m-%d")
    by_ref = {st.get("ref"): st for st in facts.get("steps") or []}
    sections = []
    for sec in PLAN_SECTIONS:
        parts = []
        for it in items:
            c = it["content"]
            if c.get("section") != sec or it["check"] == "reject":
                continue
            if it["status"] in ("dismissed", "reverted") or (adopted_only and it["status"] != "adopted"):
                continue
            steps = []
            for st in c.get("steps") or []:
                if not isinstance(st, dict):
                    continue
                code = by_ref.get(str(st.get("step") or "")) or {}
                steps.append(
                    {
                        "step": st.get("step"),
                        "label": (code.get("labels") or {}).get(lang, ""),
                        "action": base.render_text(str(st.get(key) or ""), facts),
                        "commands": list(code.get("commands") or []),
                        "check": base.render_text(str(st.get(f"check_{key}") or ""), facts),
                    }
                )
            parts.append(
                {
                    "suggestion_id": it["id"],
                    "status": it["status"],
                    "text": base.render_text(str(c.get(key) or ""), facts),
                    "segments": base.text_segments(str(c.get(key) or ""), facts),
                    "steps": steps,
                }
            )
        sections.append({"section": sec, "title": T["sec"][sec], "parts": parts})
    doc = {
        "lang": lang,
        "batch_id": batch_id,
        "title": T["title_merge" if meta.get("merge") else "title"].format(
            device=meta.get("device", ""), target=meta.get("target", "")
        ),
        "meta": T["meta"].format(
            src=meta.get("from", ""), to=meta.get("to", ""), kb=meta.get("kb_version", ""), date=date
        ),
        "note": T["note"],
        "sections": sections,
        "steps": [
            {
                "ref": st.get("ref"),
                "no": st.get("no"),
                "phase": st.get("phase"),
                "side": st.get("device"),
                "label": (st.get("labels") or {}).get(lang, ""),
                "commands": list(st.get("commands") or []),
            }
            for st in facts.get("steps") or []
        ],
    }
    return {"doc": doc, "markdown": _plan_markdown(doc, T)}


def _plan_markdown(doc: dict[str, Any], T: dict[str, Any]) -> str:
    out = [f"# {doc['title']}", "", doc["meta"], "", f"> {doc['note']}", ""]
    for i, sec in enumerate(doc["sections"], 1):
        out += [f"## {i}. {sec['title']}", ""]
        adopted = [p for p in sec["parts"] if p["status"] == "adopted"]
        if not adopted:
            out += [T["missing"], ""]
            continue
        for p in adopted:
            out += [f"<!-- {T['ai']} #{p['suggestion_id']} -->", p["text"], ""]
            if p["steps"]:
                out += [f"| # | {T['action']} | {T['commands']} | {T['check']} |", "|---|---|---|---|"]
                for st in p["steps"]:
                    cmds = "<br>".join(f"`{x}`" for x in st["commands"]) or "—"
                    out.append(f"| {st['step']} | {st['action'] or st['label']} | {cmds} | {st['check'] or '—'} |")
                out.append("")
    out += [f"## {T['steps']}", ""]
    for st in doc["steps"]:
        out.append(f"{st['no']}. {st['label']}")
        if st["commands"]:
            out += ["", "   ```", *[f"   {x}" for x in st["commands"]], "   ```", ""]
    return "\n".join(out).rstrip() + "\n"


# ================================================================ 3. 翻译未支持项（translate_eq）


def _gap_lines(raw_lines: list[str], nos: list[int]) -> list[tuple[int, str]]:
    """未支持项的原文：给出的行，以及它下面缩进更深的行（块），每项最多 12 行。"""
    out: list[tuple[int, str]] = []
    for no in sorted(set(nos))[:4]:
        if not 1 <= no <= len(raw_lines):
            continue
        head = raw_lines[no - 1]
        ind = len(head) - len(head.lstrip())
        out.append((no, head))
        for j in range(no, min(len(raw_lines), no + 11)):
            ln = raw_lines[j]
            if not ln.strip() or len(ln) - len(ln.lstrip()) <= ind:
                break
            out.append((j + 1, ln))
    return out[:12]


def _graph_names(g: nx.MultiDiGraph) -> set[str]:
    out: set[str] = set()
    for _, d in g.nodes(data=True):
        if d.get("kind") == "object" and d.get("key") is not None and not isinstance(d.get("key"), dict):
            out.add(str(d["key"]))
        elif d.get("kind") == "attr" and isinstance(d.get("value"), str) and d.get("origin") != "default":
            out.add(d["value"])
    return out


def _translate_build(env: Env, params: dict[str, Any]) -> Context:
    from lmesh.core import translate
    from lmesh.core.ai_suggest_skills import _device_row

    g, ver, dev = _device_row(env, int(params["device_id"]))
    to = str(params["to"])
    try:
        res = translate.translate(
            g,
            env.kb,
            str(g.graph.get("profile")),
            to,
            _imap(params),
            verify=False,
            rules=_rules(env, params.get("rule_set")),
        )
    except translate.TranslateError as e:
        raise SuggestError(e.key, "param", **dict(getattr(e, "fmt", {}) or {})) from e
    raw_lines = ver.raw_text.splitlines()
    objects: dict[str, dict[str, Any]] = {
        "d1": {"type": "device", "label": dev.name, "device_id": dev.id, "version_id": ver.id}
    }
    names = {dev.name} | _graph_names(g)
    rows = []
    seen: set[tuple[int, ...]] = set()
    for u in res.get("unsupported") or []:
        nos = [int(x) for x in u.get("lines") or [] if isinstance(x, int)]
        if not nos or tuple(nos) in seen or (u.get("params") or {}).get("reason") == "secret":
            continue  # 密码类不交给 AI（人工重新设置）
        if len(seen) >= MAX_GAPS:
            break
        seen.add(tuple(nos))
        ref = f"u{len(seen)}"
        block = _gap_lines(raw_lines, nos)
        text = "\n".join(t for _, t in block)
        why = str((u.get("params") or {}).get("reason") or u.get("kind") or "")
        objects[ref] = {
            "type": "gap",
            "label": f"L{nos[0]}",
            "kind": u.get("kind"),
            "reason": why,
            "schema": u.get("schema"),
            "node": u.get("node"),
            "device": "d1",
            "line": nos[0],
            "lines": [no for no, _ in block],
            "text": text,
        }
        rows.append(f"{ref} | line {nos[0]} | {u.get('kind')} | {why} | schema={u.get('schema') or '-'}\n{text}")
    sp = str(g.graph.get("profile") or "")
    vars_ = {
        "source": f"d1 | {dev.name} | profile={sp}",
        "target": f"{to} ({env.kb.profiles[to].family})",
        "items": "\n\n".join(rows) or "(none)",
        "lang": LANG_NAMES.get(env.lang, "English"),
    }
    facts = {
        "objects": objects,
        "numbers": {"gaps": len(seen), "unsupported": len(res.get("unsupported") or [])},
        "lines": {"d1": len(raw_lines)},
        "names": sorted(names)[:MAX_NAMES],
        "to": to,
        "from": sp,
    }
    return Context(vars_, facts, f"translate:{dev.id}:{to}", dev.id)


def _check_translate_eq(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    from lmesh.core import analysis

    c = d["content"]
    item = (facts.get("objects") or {}).get(str(c.get("item") or ""))
    if not item or item.get("type") != "gap":
        return [reason("ref_not_found", ref=str(c.get("item") or ""))]
    to = str(facts.get("to") or "")
    if to not in env.kb.profiles:
        return [reason("bad_content", ref=to)]
    out: list[dict[str, Any]] = []
    config = str(c.get("config") or "").strip("\n")
    lines: list[dict[str, Any]] = [{"text": ln, "k": "frame"} for ln in str(item.get("text") or "").splitlines()]
    lines.append({"text": "→", "k": "frame"})
    if (d.get("kind") or "equivalent") == "none":
        if config.strip():
            out.append(reason("config_with_none"))
        sch = item.get("schema")
        if sch and _supported(env.kb, to).get(str(sch), False):
            out.append(reason("target_supports_node", "warn", ref=str(sch)))
        lines.append({"text": "(—)", "k": "ai"})
    else:
        if not config.strip():
            return [reason("no_config")]
        if "`" in config or len(config.splitlines()) > MAX_CONFIG_LINES:
            return [reason("bad_config")]
        try:
            res = analysis.parse_text(config, env.kb, to)
        except analysis.AnalysisError as e:
            return [reason("target_parse_failed", detail=str(e))]
        g = graphmod.build(res.parsed, env.kb, res.profile, "ai")
        for ln in res.parsed.lines:
            lines.append(
                {"text": ln.raw, "k": {"command": "ai", "unknown": "bad", "raw": "warn"}.get(ln.kind, "frame")}
            )
        bad = [ln.raw.strip() for ln in res.parsed.lines if ln.kind == "unknown"]
        if bad:
            out.append(reason("target_parse_failed", ref=bad[0], detail=str(len(bad))))
        rawl = [ln.raw.strip() for ln in res.parsed.lines if ln.kind == "raw"]
        cmds = [ln for ln in res.parsed.lines if ln.kind == "command"]
        if not cmds and not bad:  # 一行也没有被目标命令卡识别：无法确认是目标平台的写法
            out.append(reason("target_not_recognized", ref=(rawl or [""])[0]))
        elif rawl and not bad:  # 部分行是功能域外的原文：代码无法确认这些行
            out.append(reason("target_unverifiable", "warn", ref=rawl[0], detail=str(len(rawl))))
        got = {str(x.get("schema")) for _, x in g.nodes(data=True) if x.get("schema")}
        expect = c.get("expect")
        want = [str(x) for x in expect] if isinstance(expect, list) and expect else []
        if not want and item.get("schema"):
            want = [str(item["schema"])]
        for w in want:
            if w not in env.kb.nodes:
                out.append(reason("schema_unknown", ref=w))
            elif w not in got:
                out.append(reason("node_not_mapped", ref=w))
        if item.get("schema") and want and str(item["schema"]) not in want:
            out.append(reason("different_node", "warn", ref=", ".join(want)))
    if c.get("reason"):
        f2 = {**facts, "names": list(facts.get("names") or []) + config.split()}
        out += [x for x in check_text(str(c["reason"]), f2) if x["level"] == "reject"]
        env.out["segments"] = base.text_segments(str(c["reason"]), facts)
        env.out["display"] = base.render_text(str(c["reason"]), facts)
    env.out["result"] = {"lines": lines}
    return out


def _adopt_translate(env: Env, row: AISuggestion, facts: dict[str, Any]) -> dict[str, Any]:
    c = row.content or {}
    item = (facts.get("objects") or {}).get(str(c.get("item") or "")) or {}
    return {
        "action": "translate",
        "item": c.get("item"),
        "line": item.get("line"),
        "lines": item.get("lines"),
        "kind": row.kind or "equivalent",
        "to": facts.get("to"),
    }


register_category("translate_eq", Validator(_check_translate_eq, _adopt_translate, base._revert_record))
register_skill(
    SkillSpec(
        id="translate-gap",
        build=_translate_build,
        categories=("translate_eq",),
        default_category="translate_eq",
        scope="device",
        prepare=_prepare_cutover,
    )
)


def translate_patches(db_url: str, project_id: int | None, device_id: int, to: str) -> list[dict[str, Any]]:
    """项目里采纳的“翻译未支持项”建议（同一设备、同一目标 Profile），按源配置行号排序；同一行取最后采纳的一条。"""
    from sqlalchemy import select

    from lmesh.core import store

    with store.session(db_url) as s:
        q = select(AISuggestion).where(
            AISuggestion.scope_key == f"translate:{device_id}:{to}",
            AISuggestion.category == "translate_eq",
            AISuggestion.status == "adopted",
        )
        if project_id is not None:
            q = q.where(AISuggestion.project_id == project_id)
            from lmesh.core import projects

            sc = projects.current()
            if sc is not None and sc.network_id is not None and sc.project_id == project_id:
                q = q.where(AISuggestion.network_id == sc.network_id)  # M9：按网络
        last: dict[Any, dict[str, Any]] = {}
        for r in s.scalars(q.order_by(AISuggestion.decided_at, AISuggestion.id)):
            info = r.adopt_info or {}
            kind = str(info.get("kind") or r.kind or "equivalent")
            c = r.content or {}
            last[info.get("line")] = {
                "suggestion_id": r.id,
                "line": info.get("line"),
                "lines": list(info.get("lines") or []),
                "kind": kind,
                "config": str(c.get("config") or "").strip("\n") if kind != "none" else "",
                "title": r.title,
                "decided_by": r.decided_by,
            }
    return sorted(last.values(), key=lambda p: int(p["line"] or 0))


def apply_translate_patches(result: dict[str, Any], patches: list[dict[str, Any]], kb: Any, to: str) -> dict[str, Any]:
    """把采纳的等价写法写进翻译结果（标为 AI 来源）：插在结尾标记（return / end）之前；ai_lines 是译文中来自 AI 的
    行号，unsupported 中对应的项带上 ai（建议编号、类型与写法）。"""
    if not patches:
        return result
    fam = kb.families.get(kb.profiles[to].family) if to in kb.profiles else None
    end = str(getattr(fam, "end", "") or "").strip()
    lines = str(result.get("text") or "").split("\n")
    tail: list[str] = []
    while lines and not lines[-1].strip():
        tail.insert(0, lines.pop())
    last = lines.pop() if lines and end and lines[-1].strip() == end else None
    ai_lines: list[int] = []
    for p in patches:
        for ln in p["config"].split("\n") if p["config"] else []:
            lines.append(ln)
            ai_lines.append(len(lines))
    if last is not None:
        lines.append(last)
    by_line = {p["line"]: p for p in patches}
    for u in result.get("unsupported") or []:
        nos = u.get("lines") or []
        hit = by_line.get(nos[0]) if nos else None
        if hit is not None:
            u["ai"] = {"suggestion_id": hit["suggestion_id"], "kind": hit["kind"], "config": hit["config"]}
    result["text"] = "\n".join(lines + tail)
    result["ai_lines"] = ai_lines
    result["ai_patches"] = patches
    return result


# ================================================================ 4. 命名映射建议（naming_rules，REQ-032）


def _naming_build(env: Env, params: dict[str, Any]) -> Context:
    from lmesh.core import naming
    from lmesh.core.ai_suggest_skills import _device_row

    g, ver, dev = _device_row(env, int(params["device_id"]))
    to = str(params["to"])
    types = naming.rename_types(env.kb)
    objects: dict[str, dict[str, Any]] = {
        "d1": {"type": "device", "label": dev.name, "device_id": dev.id, "version_id": ver.id}
    }
    names: set[str] = {dev.name}

    def listing(gr: nx.MultiDiGraph) -> list[str]:
        by: dict[str, list[str]] = defaultdict(list)
        for _, d in gr.nodes(data=True):
            if d.get("kind") != "object" or isinstance(d.get("key"), dict) or d.get("key") in (None, "", "_"):
                continue
            sch = str(d.get("schema"))
            if sch in types or sch == "interface":
                by[sch].append(str(d["key"]))
                names.add(str(d["key"]))
        return [f"{t}: {', '.join(sorted(set(v))[:40])}" for t, v in sorted(by.items())]

    src_rows = listing(g)
    tgt_rows: list[str] = []
    if params.get("target_device_id") is not None:
        tg, tver, tdev = _device_row(env, int(params["target_device_id"]))
        objects["d2"] = {"type": "device", "label": tdev.name, "device_id": tdev.id, "version_id": tver.id}
        names.add(tdev.name)
        tgt_rows = listing(tg)
    limits = naming.name_limits(env.kb, env.kb.profiles[to].family)
    target = f"d2 | {objects['d2']['label']}\n" + "\n".join(tgt_rows) if tgt_rows else f"(no device; profile {to})"
    vars_ = {
        "source": f"d1 | {dev.name} | profile={g.graph.get('profile')}\n" + "\n".join(src_rows),
        "target": target,
        "types": ", ".join(types),
        "limits": ", ".join(f"{k}<={v}" for k, v in sorted(limits.items())) or "-",
        "lang": LANG_NAMES.get(env.lang, "English"),
    }
    facts = {
        "objects": objects,
        "numbers": {"types": len(types)},
        "lines": {"d1": len(ver.raw_text.splitlines())},
        "names": sorted(names)[:MAX_NAMES],
        "to": to,
    }
    return Context(vars_, facts, f"naming:{dev.id}:{to}", dev.id)


def _rule_data(c: dict[str, Any], rid: str = "ai-draft") -> dict[str, Any]:
    return {"id": rid, **{k: c.get(k) or [] for k in ("names", "ports", "naming")}}


_NOT_PORT = ("loop", "null", "nul", "vlanif", "tunnel", "vbdif", "bdi", "eth-trunk", "port-channel", "lag")


def _check_naming(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    from lmesh.core import i18n, naming

    c = d["content"]
    if not any(c.get(k) for k in ("names", "ports", "naming")):
        return [reason("no_rules")]
    try:
        rs = naming.parse(_rule_data(c), env.kb, "ai-draft")
    except naming.RulesError as e:
        return [reason("bad_rules", detail=i18n.t(e.key, env.lang, **dict(getattr(e, "fmt", {}) or {})))]
    g = graph_of(env, facts, "d1")
    tg = graph_of(env, facts, "d2") if "d2" in (facts.get("objects") or {}) else None
    _, pmap, rep = naming.run(g, env.kb, rs, str(facts.get("to") or "") or None, tg)
    out: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    for r in rep["renames"]:
        extra = f"  ({r['conflict']})" if r.get("conflict") else ""
        lines.append({"text": f"{r['type']}  {r['from']} → {r['to']}{extra}", "k": "ai" if r["applied"] else "bad"})
    for p in rep["ports"]:
        lines.append({"text": f"port  {p['from']} → {p['to']}", "k": "ai" if p.get("applied") else "bad"})
    for cf in rep["conflicts"]:
        out.append(
            reason("naming_conflict", ref=f"{cf.get('type', 'port')}:{cf.get('to')}", detail=f"{cf.get('kind')}")
        )
    for gp in rep["gaps"][:5]:
        out.append(reason("naming_gap", "warn", ref=str(gp.get("type") or gp.get("name") or "")))
    for w in rep["naming"][:5]:
        out.append(reason("naming_warn", "warn", ref=str(w.get("name") or w.get("from") or "")))
    used = {(r["rule"]["section"], r["rule"]["index"]) for r in rep["renames"] + rep["ports"] if r.get("rule")}
    pairs: list[tuple[str, Any]] = [("names", r) for r in rs.names] + [("ports", r) for r in rs.ports]
    idx: dict[str, int] = defaultdict(int)
    for sec, rule in pairs:
        i = idx[sec]
        idx[sec] += 1
        if (sec, i) not in used:
            out.append(reason("rule_unused", "warn", ref=f"{sec}[{i}] {rule.as_dict().get('from', '')}"))
    if rs.ports:
        phys = {
            str(x.get("key"))
            for _, x in g.nodes(data=True)
            if x.get("schema") == "interface" and x.get("kind") == "object" and "." not in str(x.get("key"))
        }
        missed = sorted(p for p in phys if p not in pmap and not p.lower().startswith(_NOT_PORT))
        if missed:
            out.append(reason("port_unmapped", "warn", ref=", ".join(missed[:5]), detail=str(len(missed))))
    if not rep["renames"] and not rep["ports"]:
        out.append(reason("nothing_mapped"))
    if c.get("explain"):
        out += [x for x in check_text(str(c["explain"]), facts) if x["level"] == "reject"]
        env.out["segments"] = base.text_segments(str(c["explain"]), facts)
        env.out["display"] = base.render_text(str(c["explain"]), facts)
    env.out["result"] = {"lines": lines, "summary": rep["summary"]}
    return out


def _file_sha(path: Any) -> str | None:
    try:
        return _sha(path.read_text(encoding="utf-8"))
    except OSError:
        return None


def _adopt_naming(env: Env, row: AISuggestion, facts: dict[str, Any]) -> dict[str, Any]:
    from lmesh.core import assets, kbservice, naming

    rid = f"ai-naming-{row.id}"
    data: dict[str, Any] = _rule_data(row.content or {}, rid)
    data["title"] = _texts(base.render_title(row.title or rid, facts))
    to = str(facts.get("to") or "")
    if to in env.kb.profiles:
        data["to"] = env.kb.profiles[to].family
    try:
        rs = naming.save(kbservice.runtime_root(env.settings), rid, data, env.kb, overwrite=False)
    except naming.RulesError as e:
        raise SuggestError(e.key, "state", **dict(getattr(e, "fmt", {}) or {})) from e
    if env.user_id is not None:
        assets.claim(env.db, "ruleset", rid, env.user_id)
    return {"action": "ruleset", "id": rid, "sha": _file_sha(naming.user_dir() / rs.file)}


def _revert_naming(env: Env, row: AISuggestion) -> dict[str, Any]:
    from lmesh.core import assets, naming

    info = row.adopt_info or {}
    path = naming.user_dir() / f"{info.get('id')}.yaml"
    if not path.is_file():
        return {"action": "none"}
    if _file_sha(path) != info.get("sha"):
        raise SuggestError("ai_suggest.asset_modified", "state", id=info.get("id"))
    path.unlink()
    assets.release(env.db, "ruleset", str(info.get("id")))
    return {"action": "ruleset_deleted", "id": info.get("id")}


register_category("naming_rules", Validator(_check_naming, _adopt_naming, _revert_naming))
register_skill(
    SkillSpec(
        id="naming-map",
        build=_naming_build,
        categories=("naming_rules",),
        default_category="naming_rules",
        scope="device",
        prepare=_prepare_cutover,
    )
)


# ================================================================ 5. 模板提取（template_draft）


def _prepare_template(env: Env, params: dict[str, Any]) -> None:
    from lmesh.core import compare, graphstore

    raw = params.get("device_ids")
    ids: list[int] = []
    for x in raw if isinstance(raw, list) else []:
        s = str(x).strip()
        did = int(s) if s.isdigit() else compare.device_id_by_name(env.db, s)  # 命令行可以给设备名
        if did is None:
            raise SuggestError("ai_suggest.device_not_found", "not_found", id=s)
        if did not in ids:
            ids.append(did)
    if not ids or len(ids) > MAX_TEMPLATE_DEVICES:
        raise SuggestError("ai_suggest.need_devices", "param", max=MAX_TEMPLATE_DEVICES)
    for i in ids:
        if graphstore.latest_version(env.db, i) is None:
            raise SuggestError("ai_suggest.device_not_found", "not_found", id=i)
    params["device_ids"] = ids


def _template_build(env: Env, params: dict[str, Any]) -> Context:
    from lmesh.core import template_draft
    from lmesh.core.ai_suggest_skills import _device_row
    from lmesh.core.template import TemplateError

    objects: dict[str, dict[str, Any]] = {}
    configs = []
    names: set[str] = set()
    fams = set()
    for i, did in enumerate(params["device_ids"], 1):
        g, ver, dev = _device_row(env, int(did))
        objects[f"d{i}"] = {"type": "device", "label": dev.name, "device_id": dev.id, "version_id": ver.id}
        configs.append((dev.name, ver.raw_text))
        names.add(dev.name)
        fams.add(str(g.graph.get("family") or ""))
    if len(fams) > 1:
        raise SuggestError("ai_suggest.template_family", "param", families=", ".join(sorted(fams)))
    try:
        dr = template_draft.draft(configs, env.kb, None, "ai-draft")
    except TemplateError as e:
        raise SuggestError(e.key, "param", **dict(getattr(e, "fmt", {}) or {})) from e
    var_rows = []
    labels = [o["label"] for o in objects.values()]
    for v in dr.get("vars") or []:
        vals = [str(x) for x in v.get("values") or []]
        names.update(vals)
        shown = "; ".join(f"{k}={x}" for k, x in list(zip(labels, vals, strict=False))[:10])
        var_rows.append(f"{v.get('name')} | {v.get('type')} | {shown}")
    vars_ = {
        "devices": "\n".join(f"{k} | {o['label']}" for k, o in objects.items()),
        "draft": str(dr.get("source") or ""),
        "variables": "\n".join(var_rows) or "(none)",
        "lang": LANG_NAMES.get(env.lang, "English"),
    }
    facts = {
        "objects": objects,
        "numbers": {"devices": len(configs), "variables": len(dr.get("vars") or [])},
        "lines": {k: len(t.splitlines()) for k, (_, t) in zip(objects, configs, strict=True)},
        "names": sorted(names)[:MAX_NAMES],
    }
    key = ",".join(str(x) for x in sorted(params["device_ids"]))
    return Context(vars_, facts, f"template:{key}", None)


_TPL_ID = re.compile(r"(?m)^id:\s*.*$")


def _check_template(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    from lmesh.core import analysis, compare, i18n, template_match
    from lmesh.core import template as tmod

    c = d["content"]
    src = str(c.get("template") or "")
    if not src.strip():
        return [reason("no_template")]
    if not _TPL_ID.search(src):
        src = "id: ai-draft\n" + src
    try:
        t = tmod.parse(src, env.kb)
        template_match.compile_template(t, env.kb)
    except tmod.TemplateError as e:
        det = i18n.t(e.key, env.lang, **dict(getattr(e, "fmt", {}) or {}))
        if e.issues:
            det += "; " + "; ".join(str(x.get("key") or x) for x in e.issues[:3])
        return [reason("template_invalid", detail=det)]
    out: list[dict[str, Any]] = []
    if not t.vars:
        out.append(reason("no_variables", "warn"))
    lines: list[dict[str, Any]] = [{"text": ln, "k": "ai"} for ln in t.body.splitlines()[:60]]
    cover: dict[str, int] = {}
    for ref, o in (facts.get("objects") or {}).items():
        if o.get("type") != "device":
            continue
        label = str(o.get("label"))
        g = graph_of(env, facts, ref)
        r = template_match.check(t, g, env.kb, label)
        if not r["compliant"]:
            errs = [f for f in r["findings"] if f.get("severity") == "error"]
            first = errs[0] if errs else {}
            out.append(reason("template_mismatch", ref=label, detail=str(first.get("key") or first.get("kind") or "")))
            lines.append({"text": f"✗ {label}", "k": "bad"})
            continue
        text = tmod.render_text(t, r["row"])
        try:
            res = analysis.parse_text(text, env.kb, str(g.graph.get("profile") or "") or None)
        except analysis.AnalysisError as e:
            out.append(reason("render_mismatch", ref=label, detail=str(e)))
            continue
        rg = graphmod.build(res.parsed, env.kb, res.profile, label)
        diff = compare.compare(compare.Side(rg, "rendered"), compare.Side(g, "device"), env.kb)
        bad = [x for x in diff["diffs"] if x["kind"] in ("removed", "changed", "renamed")]
        if bad:
            out.append(reason("render_mismatch", ref=label, detail=f"{bad[0]['kind']} {bad[0]['node']}"))
            lines.append({"text": f"✗ {label}: {len(bad)}", "k": "bad"})
            continue

        def explicit(gr: nx.MultiDiGraph) -> int:
            return sum(
                1
                for _, x in gr.nodes(data=True)
                if x.get("kind") in ("object", "attr") and x.get("origin") == "explicit"
            )

        cover[label] = round(100 * explicit(rg) / max(1, explicit(g)))
        lines.append({"text": f"✓ {label}: {cover[label]}%", "k": "code"})
    if c.get("explain"):
        out += [x for x in check_text(str(c["explain"]), facts) if x["level"] == "reject"]
        env.out["segments"] = base.text_segments(str(c["explain"]), facts)
        env.out["display"] = base.render_text(str(c["explain"]), facts)
    env.out["result"] = {"lines": lines, "coverage": cover, "variables": list(t.vars)}
    return out


def _adopt_template(env: Env, row: AISuggestion, facts: dict[str, Any]) -> dict[str, Any]:
    from lmesh.core import assets
    from lmesh.core import template as tmod

    tid = f"ai-template-{row.id}"
    src = str((row.content or {}).get("template") or "")
    src = _TPL_ID.sub(f"id: {tid}", src, count=1) if _TPL_ID.search(src) else f"id: {tid}\n{src}"
    try:
        t = tmod.save_private(tid, src, env.kb)
    except tmod.TemplateError as e:
        raise SuggestError(e.key, "state", **dict(getattr(e, "fmt", {}) or {})) from e
    if env.user_id is not None:
        assets.claim(env.db, "template", tid, env.user_id)
    return {"action": "template", "id": tid, "sha": _file_sha(tmod.private_dir() / (t.file or f"{tid}.yaml"))}


def _revert_template(env: Env, row: AISuggestion) -> dict[str, Any]:
    from lmesh.core import assets
    from lmesh.core import template as tmod

    info = row.adopt_info or {}
    path = tmod.private_dir() / f"{info.get('id')}.yaml"
    if not path.is_file():
        return {"action": "none"}
    if _file_sha(path) != info.get("sha"):
        raise SuggestError("ai_suggest.asset_modified", "state", id=info.get("id"))
    tmod.delete_private(str(info.get("id")))
    assets.release(env.db, "template", str(info.get("id")))
    return {"action": "template_deleted", "id": info.get("id")}


register_category("template_draft", Validator(_check_template, _adopt_template, _revert_template))
register_skill(
    SkillSpec(
        id="template-extract",
        build=_template_build,
        categories=("template_draft",),
        default_category="template_draft",
        scope="project",
        prepare=_prepare_template,
    )
)
