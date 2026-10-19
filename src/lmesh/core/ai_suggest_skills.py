"""AI 建议 skill 的上下文构造（M8-2 示范；M8-3～M8-5 的 skill 也注册在这里或各自的模块里）。

每个 skill：build(env, params) → Context（提示词变量 + 代码给出的事实），以及允许的建议类别。
事实里的对象一律用短编号（d1 设备、n1 对象），AI 只能引用这些编号；编号到图节点、行号、设备编号的对应由代码保存，
界面据此跳转。数字（接口数、链路数……）由代码算好放进 numbers，AI 用 <<键>> 引用、由代码填入。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from lmesh.core import graph as graphmod
from lmesh.core.ai_suggest import Context, Env, SkillSpec, SuggestError, register_skill

MAX_OBJECTS = 200
MAX_NAMES = 3000
MAX_DEVICES = 200
LANG_NAMES = {"zh-CN": "Simplified Chinese", "en": "English", "pt-BR": "Brazilian Portuguese"}


def _device_row(env: Env, device_id: int) -> tuple[Any, Any, Any]:
    from lmesh.core import graphstore

    ver = graphstore.latest_version(env.db, int(device_id))
    if ver is None:
        raise SuggestError("ai_suggest.device_not_found", "not_found", id=device_id)
    try:
        return graphstore.build_for_version(env.db, ver.id, env.kb)
    except KeyError as e:
        raise SuggestError("ai_suggest.device_not_found", "not_found", id=device_id) from e


def _prepare_device(env: Env, params: dict[str, Any]) -> None:
    from lmesh.core import graphstore

    try:
        did = int(params["device_id"])
    except (TypeError, ValueError, KeyError) as e:
        raise SuggestError("ai_suggest.need_device", "param") from e
    params["device_id"] = did
    if graphstore.latest_version(env.db, did) is None:
        raise SuggestError("ai_suggest.device_not_found", "not_found", id=did)


def _short(v: Any, n: int = 80) -> str:
    t = " ".join(str(v).split())
    return t if len(t) <= n else t[: n - 1] + "…"


# ---------------------------------------------------------------- 设备摘要（text_only）


def _summary_build(env: Env, params: dict[str, Any]) -> Context:
    g, ver, dev = _device_row(env, int(params["device_id"]))
    objects: dict[str, dict[str, Any]] = {
        "d1": {"type": "device", "label": dev.name, "device_id": dev.id, "version_id": ver.id}
    }
    names: set[str] = {dev.name}
    children: dict[str, list[str]] = {}
    top: list[str] = []
    for a, b, d in g.edges(data=True):
        if d.get("kind") != "contains":
            continue
        children.setdefault(a, []).append(b)
        if a == graphmod.DEVICE and g.nodes[b].get("kind") == "object":
            top.append(b)
    for _, d in g.nodes(data=True):
        if d.get("kind") == "object" and d.get("key") is not None:
            names.add(str(d["key"]))
        elif d.get("kind") == "attr" and isinstance(d.get("value"), str) and d.get("origin") != "default":
            names.add(d["value"])
    top.sort(key=lambda n: (g.nodes[n].get("lines") or [10**9])[0])
    counts = Counter(str(g.nodes[n].get("schema") or "") for n in top)
    rows = []
    for i, nid in enumerate(top[:MAX_OBJECTS], 1):
        d = g.nodes[nid]
        ref = f"n{i}"
        lines = d.get("lines") or []
        objects[ref] = {
            "type": d.get("schema"),
            "label": d.get("key") if d.get("key") is not None else nid,
            "device": "d1",
            "node": nid,
            "line": lines[0] if lines else None,
        }
        attrs = []
        for c in children.get(nid, [])[:40]:
            cd = g.nodes[c]
            if cd.get("origin") == "default":
                continue
            tail = str(cd.get("schema") or "").rsplit(".", 1)[-1]
            val = cd.get("value") if cd.get("kind") == "attr" else cd.get("key")
            if val is not None and val != "":
                attrs.append(f"{tail}={_short(val, 40)}")
            if len(attrs) >= 6:
                break
        rows.append(f"{ref} | {d.get('schema')} | {_short(objects[ref]['label'])} | {'; '.join(attrs)}")
    kinds = Counter(d.get("kind") for _, d in g.nodes(data=True))
    numbers: dict[str, Any] = {f"count.{k}": v for k, v in sorted(counts.items()) if k}
    numbers.update(
        {
            "lines": len(ver.raw_text.splitlines()),
            "objects": kinds.get("object", 0),
            "unknown_lines": kinds.get("unknown", 0),
            "raw_lines": kinds.get("raw", 0),
        }
    )
    vars_ = {
        "device": f"d1 | {dev.name} | vendor={dev.vendor} | platform={dev.platform or '-'} | "
        f"profile={g.graph.get('profile') or dev.profile or '-'}",
        "objects": "\n".join(rows) or "(none)",
        "facts": "\n".join(f"{k} = {v}" for k, v in numbers.items()),
        "lang": LANG_NAMES.get(env.lang, "English"),
    }
    facts = {
        "objects": objects,
        "numbers": numbers,
        "lines": {"d1": numbers["lines"]},
        "names": sorted(names)[:MAX_NAMES],
    }
    return Context(vars_, facts, f"device:{dev.id}", dev.id)


register_skill(
    SkillSpec(
        id="device-summary",
        build=_summary_build,
        categories=("text_only",),
        default_category="text_only",
        scope="device",
        prepare=_prepare_device,
    )
)


# ---------------------------------------------------------------- 拓扑整理：设备角色（view_hint）


def _roles_build(env: Env, params: dict[str, Any]) -> Context:
    from lmesh.core import topology

    targets = [str(x) for x in params.get("device_ids") or []] or None
    devices, missing = topology.from_db(env.db, env.kb, targets)
    if missing:
        raise SuggestError("ai_suggest.device_not_found", "not_found", id=", ".join(missing))
    if not devices:
        raise SuggestError("ai_suggest.no_devices", "state")
    devices = devices[:MAX_DEVICES]
    topo = topology.to_json(topology.build(devices, env.kb))
    ref_of: dict[str, str] = {}
    objects: dict[str, dict[str, Any]] = {}
    names: set[str] = set()
    numbers: dict[str, Any] = {"devices": len(devices), "links": topo["summary"]["links"]}
    rows = []
    for i, (d, node) in enumerate(zip(devices, topo["nodes"], strict=True), 1):
        ref = f"d{i}"
        ref_of[d.name] = ref
        objects[ref] = {"type": "device", "label": d.name, "device_id": d.device_id, "version_id": d.version_id}
        names.add(d.name)
        descs = []
        for _, nd in d.g.nodes(data=True):
            if nd.get("schema") == "interface.description" and isinstance(nd.get("value"), str):
                descs.append(_short(nd["value"], 40))
                names.add(nd["value"])
            if len(descs) >= 8:
                break
        numbers[f"links.{ref}"] = node["links"]
        rows.append(
            f"{ref} | {d.name} | family={node.get('family') or '-'} | profile={node.get('profile') or '-'} | "
            f"links={node['links']} | interfaces={node['interfaces']} | asn={node.get('asn') or '-'} | "
            f"loopbacks={len(node.get('loopbacks') or [])} | descriptions: {'; '.join(descs) or '-'}"
        )
    links = []
    for lk in topo["links"][:400]:
        a, b = lk["a"], lk["b"]
        links.append(
            f"{ref_of.get(a['device'], '?')}:{a.get('interface') or '-'} <-> "
            f"{ref_of.get(b['device'], '?')}:{b.get('interface') or '-'} ({lk['type']})"
        )
    vars_ = {
        "devices": "\n".join(rows),
        "links": "\n".join(links) or "(none)",
        "roles": ", ".join(("core", "aggregation", "access", "pe", "p", "ce")),
        "lang": LANG_NAMES.get(env.lang, "English"),
    }
    facts = {"objects": objects, "numbers": numbers, "lines": {}, "names": sorted(names)[:MAX_NAMES]}
    return Context(vars_, facts, "topology", None)


register_skill(
    SkillSpec(
        id="topology-roles",
        build=_roles_build,
        categories=("view_hint",),
        default_category="view_hint",
        scope="project",
    )
)
