"""日常分析组的 AI skill（M8-3，REQ-041 / REQ-042）：拓扑整理、变化解读、问题解读与修复、影响说明、能力对比说明，
以及拓扑的手工标注、变化解读的覆盖核对、设备交接文档（含 AI 设备摘要）。设备摘要的上下文在 ai_suggest_skills.py。

所有事实由代码在图上算出并编号（d 设备、u 未解析对端、c 差异条目、f 问题、n 对象、k 命令卡、p Profile），AI 只能引用编号；
每个 skill 除类别校验器外还有自己的额外校验（SkillSpec.check）：
    topology-roles   view_hint（角色 / 分组 / 层次）+ peer_link（推测对端：代码核对两端接口地址同网段才连线）
    diff-explain     refs_exist：每个意图至少挂上一个差异条目 c*；风险等级合法；覆盖核对列出没被任何意图解释的差异
    finding-fix      refs_exist（原因、优先级、更可能出错的一端）+ script_valid（修复脚本；{"finding": "f3"} 要求在模拟图上复检后
                     问题消失：单台设备的检查问题看脚本检查的 findings_fixed，跨设备问题换上模拟后的图重新做一致性检查）
    impact-explain   text_only：影响范围由代码计算（impact.analyze），AI 只改写成运维语言
    feature-compare  text_only：commands 里的每条命令必须能被所引命令卡的语法（或取消语法）解析
"""

from __future__ import annotations

import ipaddress
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from lmesh.core import ai_suggest as A
from lmesh.core import store
from lmesh.core.ai_suggest import (
    Context,
    Env,
    SkillSpec,
    SuggestError,
    Validator,
    reason,
    register_category,
    register_skill,
)
from lmesh.core.ai_suggest_skills import (
    LANG_NAMES,
    MAX_DEVICES,
    MAX_NAMES,
    _device_row,
    _prepare_device,
    _short,
    node_label,
)
from lmesh.core.store.models import AISuggestion, AISuggestionBatch, ConfigVersion, ViewAnnotation, iso

MAX_ITEMS = 300  # 每次发给 AI 的差异条目、问题、受影响对象的上限
LEVELS = ("high", "medium", "low")
SNIPPET = 2  # 问题所在行前后各带几行配置


def _lang(env: Env) -> str:
    return LANG_NAMES.get(env.lang, "English")


def _ids_of(draft: dict[str, Any], prefix: str) -> set[str]:
    """建议引用的编号（refs 与正文中的 [[编号]]），只取某一前缀（c、f……）。"""
    out = {str(r.get("id")) for r in A._ref_ids(draft.get("refs")) if str(r.get("id") or "").startswith(prefix)}
    c: dict[str, Any] = draft["content"] if isinstance(draft.get("content"), dict) else {}
    for k in ("text", "explain", "reason"):
        if isinstance(c.get(k), str):
            out |= {m for m in A._MENTION.findall(c[k]) if m.startswith(prefix)}
    return {x for x in out if re.fullmatch(rf"{prefix}\d+", x)}


def _text_check(text: Any, facts: dict[str, Any], env: Env, required: bool = True) -> list[dict[str, Any]]:
    """说明文字：对象与数字核对 + 给界面的片段（AI 文字紫色虚线、代码填入的实线）。"""
    if not isinstance(text, str) or not text.strip():
        return [reason("no_text")] if required else []
    if len(text) > A.MAX_TEXT:
        return [reason("too_large")]
    env.out["display"] = A.render_text(text, facts)
    env.out["segments"] = A.text_segments(text, facts)
    return A.check_text(text, facts)


def _level(v: Any, code: str) -> list[dict[str, Any]]:
    return [] if str(v or "").lower() in LEVELS else [reason(code, ref=str(v))]


def _add_names(names: set[str], v: Any) -> None:
    if isinstance(v, str) and v.strip():
        names.add(v.strip())
    elif isinstance(v, dict):
        for x in v.values():
            _add_names(names, x)
    elif isinstance(v, list | tuple):
        for x in v:
            _add_names(names, x)


def _graph_names(g: Any) -> set[str]:
    """图里可以在正文中直接出现的名称：对象键与非默认的属性取值。"""
    names: set[str] = set()
    for _, d in g.nodes(data=True):
        if d.get("kind") == "object" and d.get("key") is not None:
            _add_names(names, d["key"])
        elif d.get("kind") == "attr" and d.get("origin") != "default":
            _add_names(names, d.get("value"))
    return names


def _finish_names(names: set[str]) -> list[str]:
    return sorted(n for n in names if len(n) <= 200)[:MAX_NAMES]


# ================================================================ 拓扑整理（view_hint + peer_link）


def _iface_rows(f: Any) -> list[list[Any]]:
    """设备的接口地址：[[接口, "10.0.0.1/30", vrf, 是否环回]]（代码核对推测对端用）。"""
    rows = []
    for itf in f.ifaces.values():
        if itf.shutdown:
            continue
        for addr, _node, _sec in itf.addrs:
            rows.append([itf.name, str(addr), itf.vrf or "", bool(itf.loopback)])
    return rows


def _roles_build(env: Env, params: dict[str, Any]) -> Context:
    from lmesh.core import topology

    targets = [str(x) for x in params.get("device_ids") or []] or None
    devices, missing = topology.from_db(env.db, env.kb, targets)
    if missing:
        raise SuggestError("ai_suggest.device_not_found", "not_found", id=", ".join(missing))
    if not devices:
        raise SuggestError("ai_suggest.no_devices", "state")
    devices = devices[:MAX_DEVICES]
    topo = topology.build(devices, env.kb)
    tj = topology.to_json(topo)
    annos = A.list_annotations(env.db, env.project_id, "device", env.network_id) if env.project_id is not None else []
    anno_of: dict[str, dict[str, Any]] = {}
    for a in annos:
        anno_of.setdefault(str(a["target"]), {})[a["key"]] = (a["value"], a["source"])
    ref_of: dict[str, str] = {}
    objects: dict[str, dict[str, Any]] = {}
    names: set[str] = set()
    numbers: dict[str, Any] = {"devices": len(devices), "links": tj["summary"]["links"]}
    rows, cur = [], []
    for i, (d, node) in enumerate(zip(devices, tj["nodes"], strict=True), 1):
        ref = f"d{i}"
        ref_of[d.name] = ref
        f = topo.facts[d.name]
        ifs = _iface_rows(f)
        objects[ref] = {
            "type": "device",
            "label": d.name,
            "device_id": d.device_id,
            "version_id": d.version_id,
            "ifaces": ifs,
        }
        names.add(d.name)
        descs = []
        for _, nd in d.g.nodes(data=True):
            if nd.get("schema") == "interface.description" and isinstance(nd.get("value"), str):
                descs.append(_short(nd["value"], 40))
                names.add(nd["value"])
            if len(descs) >= 8:
                break
        for r in ifs:
            names.update({r[0], r[1], r[1].split("/")[0]})
        names.update(node.get("loopbacks") or [])
        numbers[f"links.{ref}"] = node["links"]
        rows.append(
            f"{ref} | {d.name} | family={node.get('family') or '-'} | profile={node.get('profile') or '-'} | "
            f"links={node['links']} | interfaces={node['interfaces']} | asn={node.get('asn') or '-'} | "
            f"loopbacks={', '.join(node.get('loopbacks') or []) or '-'} | descriptions: {'; '.join(descs) or '-'}"
        )
        for k, (v, src) in sorted(anno_of.get(str(d.device_id), {}).items()):
            cur.append(f"{ref} {k}={v} ({'set by hand' if src == 'user' else 'adopted AI suggestion'})")
    linked: list[list[str]] = []
    links = []
    for lk in tj["links"][:400]:
        a, b = lk["a"], lk["b"]
        ra, rb = ref_of.get(a["device"], "?"), ref_of.get(b["device"], "?")
        if lk["type"] == "subnet":
            linked.append([ra, a.get("interface") or "", rb, b.get("interface") or ""])
        links.append(f"{ra}:{a.get('interface') or '-'} <-> {rb}:{b.get('interface') or '-'} ({lk['type']})")
    unres = []
    for j, u in enumerate(tj.get("unresolved") or [], 1):
        if j > 100:
            break
        ref = f"u{j}"
        src = ref_of.get(u.get("device") or "")
        addr = str(u.get("address") or "")
        objects[ref] = {
            "type": "peer",
            "label": addr or u.get("node"),
            "device": src,
            "address": addr,
            "node": u.get("node"),
        }
        if addr:
            names.add(addr)
        unres.append(f"{ref} | {u.get('type')} peer {addr or '-'} referenced by {src or '?'} ({u.get('node')})")
    vars_ = {
        "devices": "\n".join(rows),
        "links": "\n".join(links) or "(none)",
        "unresolved": "\n".join(unres) or "(none)",
        "annotations": "\n".join(cur) or "(none)",
        "roles": ", ".join(A.ROLES),
        "lang": _lang(env),
    }
    facts = {
        "objects": objects,
        "numbers": numbers,
        "lines": {},
        "names": _finish_names(names),
        "linked": linked,
    }
    return Context(vars_, facts, "topology", None)


def _ip(s: str) -> ipaddress.IPv4Interface | None:
    try:
        return ipaddress.IPv4Interface(s)
    except ValueError:
        return None


def _pair(c: dict[str, Any], facts: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """推测对端的代码核对：返回 (连线信息, 原因)。

    设备 ↔ 设备：两端（给出接口时只看该接口）有一对接口地址同网段（一端的网段包含另一端的地址），且这对接口还没有链路；
    设备 ↔ 未解析对端 u*：设备有一个接口的网段包含该对端地址（直连），才把对端当作外部设备连上。"""
    objs = facts.get("objects") or {}
    a_id, b_id = str(c.get("a") or ""), str(c.get("b") or "")
    oa, ob = objs.get(a_id), objs.get(b_id)
    if oa is None or oa.get("type") != "device":
        return None, [reason("ref_not_found", ref=a_id)]
    if ob is None:
        return None, [reason("ref_not_found", ref=b_id)]
    if a_id == b_id or ob.get("type") not in ("device", "peer"):
        return None, [reason("bad_peer", ref=b_id)]
    want_a, want_b = str(c.get("a_interface") or ""), str(c.get("b_interface") or "")
    ifs_a = [r for r in oa.get("ifaces") or [] if not want_a or r[0].lower() == want_a.lower()]
    if ob["type"] == "peer":
        peer = _ip(f"{ob.get('address') or ''}/32")
        if peer is None:
            return None, [reason("bad_peer", ref=b_id)]
        for r in ifs_a:
            ia = _ip(r[1])
            if ia is not None and not r[3] and peer.ip in ia.network and peer.ip != ia.ip:
                return {
                    "a": {"device_id": oa.get("device_id"), "name": oa["label"], "interface": r[0], "address": r[1]},
                    "b": {
                        "device_id": None,
                        "name": ob.get("address"),
                        "interface": None,
                        "address": ob.get("address"),
                    },
                    "external": True,
                    "label": _short(c.get("label") or "", 60),
                }, []
        return None, [reason("no_shared_subnet", ref=f"{oa['label']} ~ {ob.get('address')}")]
    ifs_b = [r for r in ob.get("ifaces") or [] if not want_b or r[0].lower() == want_b.lower()]
    linked = {(x[0], x[1].lower(), x[2], x[3].lower()) for x in facts.get("linked") or []}
    seen_link = False
    for ra in ifs_a:
        ia = _ip(ra[1])
        for rb in ifs_b:
            ib = _ip(rb[1])
            if ia is None or ib is None or ra[3] or rb[3] or ia.ip == ib.ip or ra[2] != rb[2]:
                continue
            if ib.ip in ia.network or ia.ip in ib.network:
                if (a_id, ra[0].lower(), b_id, rb[0].lower()) in linked or (
                    b_id,
                    rb[0].lower(),
                    a_id,
                    ra[0].lower(),
                ) in linked:
                    seen_link = True
                    continue
                return {
                    "a": {"device_id": oa.get("device_id"), "name": oa["label"], "interface": ra[0], "address": ra[1]},
                    "b": {"device_id": ob.get("device_id"), "name": ob["label"], "interface": rb[0], "address": rb[1]},
                    "external": False,
                    "label": _short(c.get("label") or "", 60),
                }, []
    if seen_link:
        return None, [reason("already_linked", ref=f"{oa['label']} ~ {ob['label']}")]
    return None, [reason("no_shared_subnet", ref=f"{oa['label']} ~ {ob['label']}")]


def _check_peer(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    c = d["content"]
    out: list[dict[str, Any]] = []
    if c.get("reason"):
        out += [r for r in _text_check(c["reason"], facts, env) if r["level"] == "reject"]
    info, why = _pair(c, facts)
    if info is not None:
        env.out["result"] = {"link": info}
    return out + why


def _link_target(info: dict[str, Any]) -> str:
    a, b = info["a"], info["b"]
    if info.get("external"):
        return f"{a['device_id']}|{b['address']}"
    x, y = sorted([str(a["device_id"]), str(b["device_id"])])
    return f"{x}|{y}"


def _adopt_peer(env: Env, row: AISuggestion, facts: dict[str, Any]) -> dict[str, Any]:
    if env.project_id is None:
        raise SuggestError("ai_suggest.need_project", "state")
    info, why = _pair(row.content or {}, facts)
    if info is None:
        raise SuggestError("ai_suggest.check_failed", "state", data={"check": {"status": "reject", "reasons": why}})
    target = _link_target(info)
    with store.session(env.db) as s:
        cur = A._annotation(s, env.project_id, "link", target, "peer", env.network_id)
        prior = None
        if cur is None:
            cur = ViewAnnotation(
                project_id=env.project_id, network_id=env.network_id, target_type="link", target=target, key="peer"
            )
            s.add(cur)
        else:
            prior = {"value": cur.value, "source": cur.source, "suggestion_id": cur.suggestion_id}
        cur.value, cur.source, cur.suggestion_id = info, "ai", row.id
        cur.updated_by, cur.updated_at = env.actor, datetime.now(UTC)
        s.flush()
        return {
            "action": "annotate",
            "annotation_id": cur.id,
            "target_type": "link",
            "target": target,
            "key": "peer",
            "value": info,
            "prior": prior,
        }


register_category("peer_link", Validator(_check_peer, _adopt_peer, A._revert_view_hint))


def _roles_extra(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    """分组只能是简短的名称（不能在名称里写出图中没有的设备、地址）。"""
    c = d.get("content") or {}
    if d.get("category") == "view_hint" and c.get("key") == "group" and isinstance(c.get("value"), str):
        return [r for r in A.check_text(c["value"], facts) if r["level"] == "reject"]
    return []


register_skill(
    SkillSpec(
        id="topology-roles",
        build=_roles_build,
        categories=("view_hint", "peer_link"),
        default_category="view_hint",
        scope="project",
        check=_roles_extra,
    )
)


# ---------------------------------------------------------------- 手工标注（来源 user，优先于 AI）


def set_annotation(env: Env, target_type: str, target: str, key: str, value: Any) -> dict[str, Any] | None:
    """手工设置或清除设备的视图标注（角色、分组、标签、层次）；value 为 None 时删除。返回标注（删除时 None）。"""
    from lmesh.core import graphstore

    if env.project_id is None:
        raise SuggestError("ai_suggest.need_project", "state")
    if target_type != "device":
        raise SuggestError("ai_suggest.bad_target_type", "param", ref=target_type)
    if key not in A.HINT_KEYS:
        raise SuggestError("ai_suggest.bad_hint_key", "param", ref=key)
    try:
        did = int(target)
    except (TypeError, ValueError) as e:
        raise SuggestError("ai_suggest.need_device", "param") from e
    if graphstore.latest_version(env.db, did) is None:
        raise SuggestError("ai_suggest.device_not_found", "not_found", id=did)
    norm = None if value is None or value == "" else A._hint_value(key, value)
    if value not in (None, "") and norm is None:
        raise SuggestError("ai_suggest.bad_hint_value", "param", ref=str(value))
    with store.session(env.db) as s:
        cur = A._annotation(s, env.project_id, "device", str(did), key, env.network_id)
        if norm is None:
            if cur is not None:
                s.delete(cur)
            return None
        if cur is None:
            cur = ViewAnnotation(
                project_id=env.project_id, network_id=env.network_id, target_type="device", target=str(did), key=key
            )
            s.add(cur)
        cur.value, cur.source, cur.suggestion_id = norm, "user", None
        cur.updated_by, cur.updated_at = env.actor[:200], datetime.now(UTC)
        s.flush()
        return {
            "id": cur.id,
            "target_type": cur.target_type,
            "target": cur.target,
            "key": cur.key,
            "value": cur.value,
            "source": cur.source,
            "suggestion_id": None,
            "updated_by": cur.updated_by,
            "updated_at": iso(cur.updated_at),
        }


# ================================================================ 变化解读（refs_exist：意图挂差异条目）


def _version_ok(env: Env, vid: Any) -> int:
    try:
        v = int(vid)
    except (TypeError, ValueError) as e:
        raise SuggestError("ai_suggest.need_versions", "param") from e
    with store.session(env.db) as s:
        ver = s.get(ConfigVersion, v)
        if ver is None:
            raise SuggestError("ai_suggest.version_not_found", "not_found", id=v)
        dev_id = ver.device_id
    from lmesh.core import graphstore

    if graphstore.latest_version(env.db, dev_id) is None:  # 设备不在当前项目可见范围内
        raise SuggestError("ai_suggest.version_not_found", "not_found", id=v)
    return v


def _diff_prepare(env: Env, params: dict[str, Any]) -> None:
    src = params.get("source") or "compare"
    if src not in ("compare", "history"):
        raise SuggestError("ai_suggest.bad_source", "param", ref=str(src))
    params["source"] = src
    params["a_version"] = _version_ok(env, params.get("a_version"))
    params["b_version"] = _version_ok(env, params.get("b_version"))
    if src == "history":
        _prepare_device(env, params)


def _val_text(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, dict) and "value" in v:
        v = v["value"]
    if isinstance(v, dict):
        return ", ".join(f"{k}={x}" for k, x in v.items())
    return str(v)


def _diff_build(env: Env, params: dict[str, Any]) -> Context:
    from lmesh.core import compare, graphstore, history

    src, va, vb = params["source"], int(params["a_version"]), int(params["b_version"])
    ga, ver_a, dev_a = graphstore.build_for_version(env.db, va, env.kb)
    gb, ver_b, dev_b = graphstore.build_for_version(env.db, vb, env.kb)
    objects: dict[str, dict[str, Any]] = {
        "d1": {"type": "device", "label": dev_b.name, "device_id": dev_b.id, "version_id": vb}
    }
    if dev_a.id != dev_b.id:
        objects["d2"] = {"type": "device", "label": dev_a.name, "device_id": dev_a.id, "version_id": va}
    names = _graph_names(ga) | _graph_names(gb) | {dev_a.name, dev_b.name}
    rows: list[str] = []
    kinds: Counter[str] = Counter()
    if src == "history":
        r = history.diff(env.db, dev_b.id, env.kb, va, vb, with_text=False)
        entries = r["items"]
        for i, it in enumerate(entries[:MAX_ITEMS], 1):
            ref = f"c{i}"
            kinds[it["kind"]] += 1
            ch = "; ".join(
                f"{x.get('field') or x.get('node')}: {_short(_val_text(x.get('a')), 40)} -> {_short(_val_text(x.get('b')), 40)}"
                for x in (it.get("changes") or [])[:6]
            )
            lines = it.get("lines_b") or it.get("lines_a") or []
            objects[ref] = {
                "type": "diff",
                "label": it["object"],
                "op": it["kind"],
                "schema": it.get("schema"),
                "node": it["object"],
                "device": "d1",
                "line": lines[0] if lines else None,
            }
            names.add(it["object"])
            rows.append(f"{ref} | {it['kind']} | {it.get('domain') or '-'} | {it['object']} | {ch or '-'}")
    else:
        res = compare.compare(compare.Side(ga, "a"), compare.Side(gb, "b"), env.kb)
        entries = res["diffs"]
        for i, it in enumerate(entries[:MAX_ITEMS], 1):
            ref = f"c{i}"
            kinds[it["kind"]] += 1
            lines = (it.get("b") or {}).get("lines") or (it.get("a") or {}).get("lines") or []
            objects[ref] = {
                "type": "diff",
                "label": it["node"],
                "op": it["kind"],
                "schema": it.get("schema"),
                "node": it["node"],
                "device": "d1",
                "line": lines[0] if lines else None,
            }
            names.add(it["node"])
            rows.append(
                f"{ref} | {it['kind']} | {it.get('domain') or '-'} | {it['node']} | "
                f"{_short(_val_text(it.get('a')), 50)} -> {_short(_val_text(it.get('b')), 50)}"
            )
    numbers: dict[str, Any] = {"diffs": len(entries)}
    numbers.update({f"diffs.{k}": v for k, v in sorted(kinds.items())})
    vars_ = {
        "versions": f"A = {dev_a.name} version {va} ({iso(ver_a.collected_at) or '-'}); "
        f"B = {dev_b.name} version {vb} ({iso(ver_b.collected_at) or '-'})",
        "diffs": "\n".join(rows) or "(none)",
        "facts": "\n".join(f"{k} = {v}" for k, v in numbers.items()),
        "lang": _lang(env),
    }
    facts = {"objects": objects, "numbers": numbers, "lines": {}, "names": _finish_names(names)}
    return Context(vars_, facts, f"{src}:{va}:{vb}"[:200], dev_b.id)


def _diff_extra(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    c = d["content"]
    out = _text_check(c.get("text"), facts, env)
    out += _level(c.get("risk"), "bad_risk")
    objs = facts.get("objects") or {}
    if not any(i in objs for i in _ids_of(d, "c")):
        out.append(reason("no_diff_refs"))
    return out


register_skill(
    SkillSpec(
        id="diff-explain",
        build=_diff_build,
        categories=("refs_exist",),
        default_category="refs_exist",
        scope="project",
        prepare=_diff_prepare,
        check=_diff_extra,
    )
)


def coverage(env: Env, skill: str, scope_key: str, prefix: str = "c") -> dict[str, Any]:
    """覆盖核对（代码计算）：范围内最近一次完成的运行里，未被拒绝、未忽略的建议引用到的条目，与没有被任何建议解释到的条目。"""
    with store.session(env.db) as s:
        q = select(AISuggestionBatch).where(
            AISuggestionBatch.skill == skill,
            AISuggestionBatch.scope_key == scope_key,
            AISuggestionBatch.status == "done",
        )
        q = q.where(*A.scope_conds(env, AISuggestionBatch))
        b = s.scalar(q.order_by(AISuggestionBatch.id.desc()).limit(1))
        if b is None:
            return {"batch_id": None, "prefix": prefix, "total": 0, "covered": [], "uncovered": [], "by_suggestion": {}}
        facts = b.context or {}
        rows = list(s.scalars(select(AISuggestion).where(AISuggestion.batch_id == b.id)))
        by: dict[str, list[str]] = {}
        for r in rows:
            if r.check_status == "reject" or r.status in ("dismissed", "reverted"):
                continue
            ids = sorted(_ids_of({"refs": r.refs, "content": r.content}, prefix), key=lambda x: int(x[len(prefix) :]))
            by[str(r.id)] = ids
        objs = facts.get("objects") or {}
        universe = sorted((k for k in objs if re.fullmatch(rf"{prefix}\d+", k)), key=lambda x: int(x[len(prefix) :]))
        covered = {i for ids in by.values() for i in ids if i in objs}
        return {
            "batch_id": b.id,
            "prefix": prefix,
            "total": len(universe),
            "covered": [k for k in universe if k in covered],
            "uncovered": [
                {
                    "id": k,
                    "label": objs[k].get("label"),
                    "op": objs[k].get("op"),
                    "node": objs[k].get("node"),
                    "type": objs[k].get("schema") or objs[k].get("type"),
                }
                for k in universe
                if k not in covered
            ],
            "by_suggestion": by,
        }


# ================================================================ 问题解读与修复（refs_exist + script_valid）


def _fix_prepare(env: Env, params: dict[str, Any]) -> None:
    src = params.get("source") or "check"
    if src not in ("check", "consistency"):
        raise SuggestError("ai_suggest.bad_source", "param", ref=str(src))
    params["source"] = src
    if src == "check":
        _prepare_device(env, params)
    else:
        ids = params.get("device_ids") or []
        if not isinstance(ids, list):
            raise SuggestError("ai_suggest.need_device", "param")
        params["device_ids"] = [int(x) for x in ids if str(x).isdigit()]


def _snippet(text: str, lines: list[int], width: int = SNIPPET) -> list[str]:
    all_ = text.splitlines()
    keep: set[int] = set()
    for n in lines[:6]:
        keep.update(range(max(1, n - width), min(len(all_), n + width) + 1))
    return [f"{n:>5}  {all_[n - 1]}" for n in sorted(keep)]


def _fmt(tpl: str, params: dict[str, Any]) -> str:
    try:
        return tpl.format(**params)
    except (KeyError, IndexError, ValueError):
        return tpl


def _key_text(ref: dict[str, Any], lang: str, texts: dict[str, dict[str, str]]) -> str:
    from lmesh.core import i18n

    key, params = ref.get("key") or "", ref.get("params") or {}
    t = (texts.get(key) or {}).get(lang) or (texts.get(key) or {}).get("en")
    return _fmt(t, params) if t else i18n.t(key, lang, **params)


def _fix_build_check(env: Env, params: dict[str, Any]) -> Context:
    from lmesh.core import checks, ignores, kbservice
    from lmesh.core import rules as rulesmod

    g, ver, dev = _device_row(env, int(params["device_id"]))
    root = kbservice.runtime_root(env.settings)
    try:
        rules = rulesmod.load_cached(env.kb, checks.rules_dir(root))
        overrides = checks.load_overrides(checks.rules_dir(root))
    except rulesmod.RuleError as e:
        raise SuggestError("rules.invalid", "state", n=len(e.issues)) from e
    res = checks.check(g, env.kb, rules, None, None, overrides, ignores.index(env.db, dev.id))
    objects: dict[str, dict[str, Any]] = {
        "d1": {"type": "device", "label": dev.name, "device_id": dev.id, "version_id": ver.id}
    }
    rows = []
    found = [f for f in res["findings"] if not f.get("ignored")]
    for i, f in enumerate(found[:MAX_ITEMS], 1):
        ref = f"f{i}"
        lines = list(f.get("lines") or [])
        msg = checks.render_text(f["message"], env.lang, res["texts"]) if f.get("message") else ""
        objects[ref] = {
            "type": "finding",
            "label": f"{f['rule']} @ {f.get('node') or '-'}",
            "rule": f["rule"],
            "node": f.get("node"),
            "severity": f.get("severity"),
            "device": "d1",
            "devices": ["d1"],
            "line": lines[0] if lines else None,
        }
        snip = "\n".join(_snippet(ver.raw_text, lines))
        rows.append(f"{ref} | {f.get('severity')} | {f['rule']} | node={f.get('node') or '-'} | {msg}\n{snip}")
    numbers = {
        "findings": len(found),
        **{f"findings.{k}": v for k, v in sorted(Counter(f.get("severity") for f in found).items()) if k},
    }
    names = _graph_names(g) | {dev.name}
    vars_ = {
        "devices": f"d1 | {dev.name} | vendor={dev.vendor} | profile={g.graph.get('profile') or dev.profile or '-'}",
        "findings": "\n\n".join(rows) or "(none)",
        "facts": "\n".join(f"{k} = {v}" for k, v in numbers.items()),
        "lang": _lang(env),
    }
    facts = {
        "objects": objects,
        "numbers": numbers,
        "lines": {"d1": len(ver.raw_text.splitlines())},
        "names": _finish_names(names),
        "source": "check",
    }
    return Context(vars_, facts, f"check:{dev.id}", dev.id)


def _consistency_inputs(env: Env, device_ids: list[int] | None) -> tuple[Any, Any, Any]:
    from lmesh.core import consistency, kbservice, topology

    targets = [str(x) for x in device_ids] if device_ids else None
    devices, missing = topology.from_db(env.db, env.kb, targets)
    if missing:
        raise SuggestError("ai_suggest.device_not_found", "not_found", id=", ".join(missing))
    if not devices:
        raise SuggestError("ai_suggest.no_devices", "state")
    ruleset = consistency.load_cached(env.kb, consistency.rules_file(kbservice.runtime_root(env.settings)))
    return devices[:MAX_DEVICES], ruleset, topology


def _fix_build_consistency(env: Env, params: dict[str, Any]) -> Context:
    from lmesh.core import consistency

    devices, ruleset, topology = _consistency_inputs(env, params.get("device_ids") or None)
    topo = topology.build(devices, env.kb)
    res = consistency.check(topo, env.kb, ruleset)
    objects: dict[str, dict[str, Any]] = {}
    ref_of: dict[str, str] = {}
    texts_of: dict[str, str] = {}
    names: set[str] = set()
    for i, d in enumerate(devices, 1):
        ref = f"d{i}"
        ref_of[d.name] = ref
        objects[ref] = {"type": "device", "label": d.name, "device_id": d.device_id, "version_id": d.version_id}
        names |= _graph_names(d.g) | {d.name}
        with store.session(env.db) as s:
            v = s.get(ConfigVersion, d.version_id)
            texts_of[d.name] = v.raw_text if v is not None else ""
    rows = []
    found = [f for f in res["findings"] if not f.get("ignored")]
    for i, f in enumerate(found[:MAX_ITEMS], 1):
        ref = f"f{i}"
        ends = f.get("ends") or []
        devs = [ref_of[e["device"]] for e in ends if e.get("device") in ref_of]
        first = ends[0] if ends else {}
        objects[ref] = {
            "type": "finding",
            "label": f"{f['rule']} @ {f.get('link')}",
            "rule": f["rule"],
            "finding": f["id"],
            "link": f.get("link"),
            "node": f.get("node"),
            "severity": f.get("severity"),
            "device": ref_of.get(first.get("device") or ""),
            "devices": devs,
            "line": (first.get("lines") or [None])[0],
        }
        msg = _key_text(f.get("message") or {}, env.lang, res.get("texts") or {})
        parts = [f"{ref} | {f.get('severity')} | {f['rule']} | {msg}"]
        for e in ends:
            dref = ref_of.get(e.get("device") or "", "?")
            parts.append(f"  end {dref} {e.get('end')}: value={e.get('value')}")
            parts += ["  " + x for x in _snippet(texts_of.get(e.get("device") or "", ""), list(e.get("lines") or []))]
        rows.append("\n".join(parts))
    numbers = {
        "findings": len(found),
        "devices": len(devices),
        **{f"findings.{k}": v for k, v in sorted(Counter(f.get("severity") for f in found).items()) if k},
    }
    vars_ = {
        "devices": "\n".join(
            f"{ref_of[d.name]} | {d.name} | profile={d.g.graph.get('profile') or '-'}" for d in devices
        ),
        "findings": "\n\n".join(rows) or "(none)",
        "facts": "\n".join(f"{k} = {v}" for k, v in numbers.items()),
        "lang": _lang(env),
    }
    facts = {
        "objects": objects,
        "numbers": numbers,
        "lines": {ref_of[d.name]: len(texts_of[d.name].splitlines()) for d in devices},
        "names": _finish_names(names),
        "source": "consistency",
        "device_ids": [d.device_id for d in devices],
    }
    return Context(vars_, facts, "consistency", None)


def _fix_build(env: Env, params: dict[str, Any]) -> Context:
    return _fix_build_check(env, params) if params.get("source") == "check" else _fix_build_consistency(env, params)


def _recheck_consistency(
    env: Env, facts: dict[str, Any], dev_id: int, final_graph: Any, finding_ids: list[str]
) -> list[str]:
    """把一台设备换成脚本执行后的模拟图，重新做跨设备一致性检查；返回仍然存在的问题编号。"""
    from lmesh.core import consistency

    devices, ruleset, topology = _consistency_inputs(env, facts.get("device_ids") or None)
    swapped = [
        topology.Device(d.name, final_graph, device_id=d.device_id, version_id=d.version_id, source=d.source)
        if d.device_id == dev_id
        else d
        for d in devices
    ]
    res = consistency.check(topology.build(swapped, env.kb), env.kb, ruleset)
    alive = {f["id"] for f in res["findings"]}
    return [x for x in finding_ids if x in alive]


def _fix_extra(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    from lmesh.core import script_check

    c = d["content"]
    objs = facts.get("objects") or {}
    fids = sorted(i for i in _ids_of(d, "f") if i in objs)
    fixes = [x for x in c.get("fixes") or [] if isinstance(x, dict) and x.get("finding")]
    fids = sorted(set(fids) | {str(x["finding"]) for x in fixes if str(x["finding"]) in objs})
    out: list[dict[str, Any]] = []
    if not fids:
        out.append(reason("no_finding_refs"))
    ends = {e for f in fids for e in objs[f].get("devices") or []}
    if d.get("category") == "refs_exist":
        out += _text_check(c.get("text"), facts, env)
        out += _level(c.get("priority"), "bad_priority")
        if c.get("suspect") is not None and str(c.get("suspect")) not in ends:
            out.append(reason("suspect_not_end", ref=str(c.get("suspect"))))
        return out
    # script_valid：脚本所在设备必须是问题涉及的设备；{"finding": "f3"} 要求模拟后问题消失
    dev_ref = str(c.get("device") or "")
    if fids and dev_ref not in ends:
        out.append(reason("fix_wrong_device", ref=dev_ref))
        return out
    if c.get("priority") is not None:
        out += _level(c.get("priority"), "bad_priority")
    for x in fixes:
        if str(x["finding"]) not in objs:
            out.append(reason("ref_not_found", ref=str(x["finding"])))
    want = [str(x["finding"]) for x in fixes if str(x["finding"]) in objs]
    if not want or not isinstance(c.get("script"), str) or not c["script"].strip():
        return out
    dev_id = A._script_device(c, facts)
    if dev_id is None:
        return out
    try:
        base = script_check.baseline_from_db(env.db, env.kb, dev_id)
        res = script_check.check_text(c["script"], env.kb, base, "change", True, lang=env.lang, with_reorder=False)
    except script_check.ScriptCheckError:
        return out  # 脚本本身的错误由 script_valid 报出
    if facts.get("source") == "consistency":
        alive = _recheck_consistency(env, facts, dev_id, res["_final_graph"], [objs[f]["finding"] for f in want])
        out += [reason("finding_not_fixed", ref=f) for f in want if objs[f]["finding"] in alive]
    else:
        fixed = {(f.get("rule"), f.get("node")) for f in res["result"].get("findings_fixed") or []}
        out += [reason("finding_not_fixed", ref=f) for f in want if (objs[f]["rule"], objs[f]["node"]) not in fixed]
    return out


register_skill(
    SkillSpec(
        id="finding-fix",
        build=_fix_build,
        categories=("refs_exist", "script_valid"),
        default_category="refs_exist",
        scope="project",
        prepare=_fix_prepare,
        check=_fix_extra,
    )
)


# ================================================================ 影响说明（text_only；影响范围由代码计算）

DIRECTIONS = ("up", "down", "both")


def impact_scope(device_id: int, direction: str, nodes: list[str]) -> str:
    return f"impact:{device_id}:{direction}:{','.join(sorted(nodes))}"[:200]


def _impact_prepare(env: Env, params: dict[str, Any]) -> None:
    _prepare_device(env, params)
    nodes = params.get("nodes")
    if not isinstance(nodes, list) or not nodes or not all(isinstance(x, str) and x for x in nodes):
        raise SuggestError("ai_suggest.need_nodes", "param")
    params["nodes"] = nodes[:50]
    if params.get("direction", "up") not in DIRECTIONS:
        raise SuggestError("ai_suggest.bad_direction", "param", ref=str(params.get("direction")))
    params["direction"] = params.get("direction") or "up"


def _impact_build(env: Env, params: dict[str, Any]) -> Context:
    from lmesh.core import impact

    g, ver, dev = _device_row(env, int(params["device_id"]))
    try:
        r = impact.analyze(g, env.kb, list(params["nodes"]), params.get("direction") or "up")
    except impact.ImpactError as e:
        raise SuggestError("ai_suggest.bad_nodes", "param", ref=str(e)) from e
    objects: dict[str, dict[str, Any]] = {
        "d1": {"type": "device", "label": dev.name, "device_id": dev.id, "version_id": ver.id}
    }
    ref_of: dict[str, str] = {}

    def obj(node: str, kind: str) -> str:
        if node in ref_of:
            return ref_of[node]
        ref = f"n{len(ref_of) + 1}"
        nd = g.nodes[node] if node in g else {}
        lines = nd.get("lines") or []
        ref_of[node] = ref
        objects[ref] = {
            "type": nd.get("schema") or kind,
            "label": node_label(nd, node),
            "node": node,
            "device": "d1",
            "line": lines[0] if lines else None,
            "role": kind,
        }
        return ref

    seeds = [f"{obj(s['node'], 'seed')} | {s['schema']} | {s['node']}" for s in r["seeds"]]
    objs = [
        f"{obj(o['node'], 'object')} | {o['schema']} | {o['domain']} | depth={o['depth']} | via {o['edge']}"
        for o in r["objects"][:MAX_ITEMS]
    ]
    biz = []
    for b in r["business"][:MAX_ITEMS]:
        path = " -> ".join(obj(p, "path") if p in g else p for p in b.get("path") or [])
        biz.append(f"{obj(b['node'], 'business')} | {b['type']} | {b['node']} | path: {path}")
    numbers = {f"impact.{k}": v for k, v in r["summary"].items()}
    numbers.update({f"impact.domain.{k}": v["objects"] for k, v in r["by_domain"].items()})
    names = _graph_names(g) | {dev.name}
    names |= {str(o["label"]) for o in objects.values()} | set(ref_of)
    vars_ = {
        "device": f"d1 | {dev.name} | profile={r.get('profile') or '-'} | direction={r['direction']}",
        "seeds": "\n".join(seeds) or "(none)",
        "objects": "\n".join(objs) or "(none)",
        "business": "\n".join(biz) or "(none)",
        "facts": "\n".join(f"{k} = {v}" for k, v in numbers.items()),
        "lang": _lang(env),
    }
    facts = {
        "objects": objects,
        "numbers": numbers,
        "lines": {"d1": len(ver.raw_text.splitlines())},
        "names": _finish_names(names),
    }
    return Context(vars_, facts, impact_scope(dev.id, r["direction"], list(params["nodes"])), dev.id)


def _impact_extra(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    """说明里至少要提到一个代码算出的受影响对象（[[n*]]），否则就不是对这次影响范围的说明。"""
    text = (d.get("content") or {}).get("text")
    objs = facts.get("objects") or {}
    if isinstance(text, str) and not any(m in objs and m.startswith("n") for m in A._MENTION.findall(text)):
        return [reason("no_impact_refs")]
    return []


register_skill(
    SkillSpec(
        id="impact-explain",
        build=_impact_build,
        categories=("text_only",),
        default_category="text_only",
        scope="device",
        prepare=_impact_prepare,
        check=_impact_extra,
    )
)


# ================================================================ 能力对比说明（text_only；写法来自命令卡）


def _feature_prepare(env: Env, params: dict[str, Any]) -> None:
    kb = env.kb
    node = str(params.get("node") or "")
    if node not in kb.nodes:
        raise SuggestError("ai_suggest.bad_feature", "not_found", ref=node)
    for k in ("a", "b"):
        p = str(params.get(k) or "")
        if p not in kb.profiles:
            raise SuggestError("ai_suggest.bad_profile", "not_found", ref=p)
    if params["a"] == params["b"]:
        raise SuggestError("ai_suggest.same_profile", "param")


def _feature_build(env: Env, params: dict[str, Any]) -> Context:
    from lmesh.core import features

    kb = env.kb
    node, pa, pb = str(params["node"]), str(params["a"]), str(params["b"])
    det = features.detail(kb, node, [pa, pb])
    n = kb.nodes[node]
    objects: dict[str, dict[str, Any]] = {}
    names: set[str] = {node, pa, pb}
    rows = []
    k = 0
    for pref, pid in (("p1", pa), ("p2", pb)):
        cell = det["profiles"].get(pid) or {}
        fam = kb.profiles[pid].family
        objects[pref] = {"type": "profile", "label": pid, "family": fam}
        rows.append(
            f"{pref} | {pid} | family={fam} | state={cell.get('state')} | default={cell.get('default')} | "
            f"inherited={cell.get('inherited', False)}"
        )
        for cid in cell.get("cards") or []:
            card = kb.cards.get(cid)
            if card is None:
                continue
            k += 1
            ref = f"k{k}"
            objects[ref] = {
                "type": "card",
                "label": cid,
                "profile": pref,
                "family": card.family,
                "syntax": card.syntax,
                "undo": card.undo,
                "view": card.view,
            }
            names.add(cid)
            rows.append(
                f"  {ref} | card {cid} | view={card.view} | syntax: {card.syntax}"
                + (f" | undo: {card.undo}" if card.undo else "")
            )
    deps = [f"{x['kind']}: {x['src']} -> {x['dst']}" for x in det["deps"][:20]]
    title = (
        n.semantic
        if isinstance(n.semantic, str)
        else (n.semantic or {}).get("en", "")
        if isinstance(n.semantic, dict)
        else ""
    )
    vars_ = {
        "feature": f"{node} | type={n.type} | domain={n.domain} | {title}",
        "profiles": "\n".join(rows),
        "deps": "\n".join(deps) or "(none)",
        "lang": _lang(env),
    }
    facts = {"objects": objects, "numbers": {"cards": k}, "lines": {}, "names": _finish_names(names)}
    return Context(vars_, facts, f"feature:{node}:{pa}:{pb}"[:200], None)


def syntax_matches(kb: Any, card_id: str, text: str, fallback: dict[str, Any] | None = None) -> bool:
    """命令写法能否被命令卡的语法（或取消语法）解析。知识库里没有这张卡时（例如回放记下的事实）用事实里记下的语法。"""
    from lmesh.core.kb import syntax as syn

    text = text.strip()
    card = kb.cards.get(card_id)
    if not text:
        return False
    if card is not None:
        params: dict[str, Any] = card.params
        quotes = bool(kb.families[card.family].quotes) if card.family in kb.families else False
        forms = [card.syntax, card.undo]
    else:
        fb = fallback or {}
        params, quotes, forms = {}, False, [fb.get("syntax"), fb.get("undo")]
    for form in forms:
        if not form:
            continue
        try:
            if syn.match(syn.parse(form), text, params, quotes) is not None:
                return True
        except (syn.SyntaxErrorKB, ValueError):
            continue
    return False


def _feature_extra(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    c = d["content"]
    objs = facts.get("objects") or {}
    out: list[dict[str, Any]] = []
    cmds = c.get("commands")
    if cmds is None:
        return out
    if not isinstance(cmds, list):
        return [reason("bad_content")]
    for x in cmds[:30]:
        if not isinstance(x, dict):
            out.append(reason("bad_content"))
            continue
        ref, text = str(x.get("card") or ""), str(x.get("text") or "")
        o = objs.get(ref)
        if o is None or o.get("type") != "card":
            out.append(reason("card_not_found", ref=ref))
        elif not syntax_matches(env.kb, str(o["label"]), text, o):
            out.append(reason("syntax_mismatch", ref=f"{o['label']}: {_short(text, 80)}"))
    return out


register_skill(
    SkillSpec(
        id="feature-compare",
        build=_feature_build,
        categories=("text_only",),
        default_category="text_only",
        scope="project",
        prepare=_feature_prepare,
        check=_feature_extra,
    )
)


# ================================================================ 设备交接文档（含采纳的 AI 设备摘要，中文 / English）

_HT = {
    "zh-CN": {
        "title": "设备交接说明",
        "device": "设备",
        "vendor": "厂商",
        "profile": "Profile",
        "version": "配置版本",
        "collected": "采集时间",
        "lines": "配置行数",
        "role": "角色",
        "group": "分组",
        "counts": "对象统计（代码计算）",
        "type": "类型",
        "count": "数量",
        "summary": "设备摘要",
        "ai_note": "以下摘要由 AI 生成，经代码校验（对象与数字都在配置图中），由 {who} 于 {at} 采纳。",
        "no_summary": "还没有采纳的设备摘要。可在设备配置分析页用 AI 生成并采纳后再导出。",
        "other_lang": "（摘要原文为 {lang}，没有本语言的版本）",
        "src.user": "手工标注",
        "src.ai": "AI 建议（已采纳）",
        "none": "未设置",
    },
    "en": {
        "title": "Device handover note",
        "device": "Device",
        "vendor": "Vendor",
        "profile": "Profile",
        "version": "Config version",
        "collected": "Collected at",
        "lines": "Config lines",
        "role": "Role",
        "group": "Group",
        "counts": "Object counts (computed by code)",
        "type": "Type",
        "count": "Count",
        "summary": "Device summary",
        "ai_note": "The summary below was written by AI, checked by code (every object and number is in the config graph) "
        "and adopted by {who} at {at}.",
        "no_summary": "No device summary has been adopted yet. Generate and adopt one on the device analysis page, then export again.",
        "other_lang": "(the summary was written in {lang}; there is no version in this language)",
        "src.user": "set by hand",
        "src.ai": "AI suggestion (adopted)",
        "none": "not set",
    },
}


def _adopted_summary(env: Env, device_id: int, lang: str) -> tuple[dict[str, Any] | None, str | None]:
    """最近采纳的设备摘要：优先同语言的（批次事实里记下了语言），没有时取任一语言的。返回 (建议, 原文语言)。"""
    with store.session(env.db) as s:
        q = select(AISuggestion).where(
            AISuggestion.skill == "device-summary",
            AISuggestion.device_id == device_id,
            AISuggestion.status == "adopted",
        )
        q = q.where(*A.scope_conds(env, AISuggestion))
        rows = list(s.scalars(q.order_by(AISuggestion.decided_at.desc())))
        if not rows:
            return None, None
        facts = A._facts_of(s, {r.batch_id for r in rows})
        pick = next((r for r in rows if (facts.get(r.batch_id) or {}).get("lang") == lang), None)
        r = pick or rows[0]
        f = facts.get(r.batch_id) or {}
        text = str((r.content or {}).get("text") or "")
        return {
            "id": r.id,
            "text": A.render_text(text, f),
            "decided_by": r.decided_by,
            "decided_at": iso(r.decided_at),
        }, f.get("lang")


def handover(env: Env, device_id: int, lang: str = "zh-CN", fmt: str = "html") -> Any:
    """设备交接文档：设备信息、视图标注（角色、分组）、代码算出的对象统计，以及最近采纳的 AI 设备摘要。"""
    from lmesh.core import report

    lang = report.report_lang(lang)
    if fmt not in ("html", "md"):
        raise SuggestError("report.bad_format", "param", format=fmt)
    g, ver, dev = _device_row(env, device_id)
    T = _HT[lang]
    doc = report._Doc(fmt, lang)
    doc.h(1, f"{T['title']} · {dev.name}")
    annos = {}
    if env.project_id is not None:
        for a in A.list_annotations(env.db, env.project_id, "device", env.network_id):
            if a["target"] == str(dev.id):
                annos[a["key"]] = a

    def anno(k: str) -> str:
        a = annos.get(k)
        if not a:
            return doc.esc(T["none"])
        return doc.esc(
            f"{a['value']}（{T['src.' + a['source']]}）"
            if lang == "zh-CN"
            else f"{a['value']} ({T['src.' + a['source']]})"
        )

    rows = [
        [doc.esc(T["device"]), doc.code(dev.name)],
        [doc.esc(T["vendor"]), doc.esc(dev.vendor)],
        [doc.esc(T["profile"]), doc.code(g.graph.get("profile") or dev.profile or "-")],
        [doc.esc(T["version"]), doc.esc(str(ver.id))],
        [doc.esc(T["collected"]), doc.esc(iso(ver.collected_at) or "-")],
        [doc.esc(T["lines"]), doc.esc(str(len(ver.raw_text.splitlines())))],
        [doc.esc(T["role"]), anno("role")],
        [doc.esc(T["group"]), anno("group")],
    ]
    doc.table(["", ""], rows)
    doc.h(2, T["summary"])
    sm, src_lang = _adopted_summary(env, dev.id, lang)
    if sm is None:
        doc.p(T["no_summary"], "note")
    else:
        doc.p(T["ai_note"].format(who=sm["decided_by"] or "-", at=sm["decided_at"] or "-"), "note")
        if src_lang and src_lang != lang:
            doc.p(T["other_lang"].format(lang=src_lang), "note")
        doc.p(sm["text"])
    doc.h(2, T["counts"])
    top: Counter[str] = Counter()
    for _a, b, d in g.edges(data=True):
        if d.get("kind") == "contains" and g.nodes[b].get("kind") == "object":
            top[str(g.nodes[b].get("schema") or "")] += 1
    doc.table([T["type"], T["count"]], [[doc.code(k), doc.esc(str(v))] for k, v in sorted(top.items()) if k])
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    ext = "html" if fmt == "html" else "md"
    safe = re.sub(r"[^\w.-]+", "_", dev.name)
    return report.Report(
        f"handover-{safe}-{lang}-{stamp}.{ext}",
        doc.render(f"{T['title']} · {dev.name}"),
        "text/html; charset=utf-8" if fmt == "html" else "text/markdown; charset=utf-8",
    )
