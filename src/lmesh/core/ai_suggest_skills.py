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
    from lmesh.core import analysis, graphstore

    ver = graphstore.latest_version(env.db, int(device_id))
    if ver is None:
        raise SuggestError("ai_suggest.device_not_found", "not_found", id=device_id)
    try:
        return graphstore.build_for_version(env.db, ver.id, env.kb)
    except KeyError as e:
        raise SuggestError("ai_suggest.device_not_found", "not_found", id=device_id) from e
    except analysis.AnalysisError as e:  # 只存原文的设备（REQ-044）没有配置图
        raise SuggestError("model.raw_only", "state") from e


def _prepare_device(env: Env, params: dict[str, Any]) -> None:
    from lmesh.core import graphstore

    try:
        did = int(params["device_id"])
    except (TypeError, ValueError, KeyError) as e:
        raise SuggestError("ai_suggest.need_device", "param") from e
    params["device_id"] = did
    if graphstore.latest_version(env.db, did) is None:
        raise SuggestError("ai_suggest.device_not_found", "not_found", id=did)


def node_label(d: dict[str, Any], nid: str) -> str:
    """对象在文字里显示的名字：有键用键；没有键（整段功能，例如 mpls ldp、telnet server，内部键为 _）用配置路径。"""
    key = d.get("key")
    if key is not None and str(key) not in ("", "_"):
        return str(key)
    schema = str(d.get("schema") or "")
    return schema.replace(".", " ") if schema else nid


def _short(v: Any, n: int = 80) -> str:
    t = " ".join(str(v).split())
    return t if len(t) <= n else t[: n - 1] + "…"


# ---------------------------------------------------------------- 设备摘要（text_only）


def _summary_build(env: Env, params: dict[str, Any]) -> Context:
    g, ver, dev = _device_row(env, int(params["device_id"]))
    objects: dict[str, dict[str, Any]] = {
        "d1": {"type": "device", "label": dev.name, "device_id": dev.id, "version_id": ver.id}
    }
    # 代码交给 AI 的设备信息（厂商、平台、Profile）也是事实，文字里提到不算“图中没有的对象”
    profile = str(g.graph.get("profile") or dev.profile or "")
    names: set[str] = {dev.name} | {x for x in (dev.vendor, dev.platform, profile) if x}
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
            "label": node_label(d, nid),
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
    # REQ-044：近似匹配（例如 NE8000 用 ATN 的 Profile）时告诉 AI，摘要里如实说明，并带上未识别行数
    from lmesh.core import model_support

    match = model_support.device_info(dev, ver)["match_level"]
    approx_note = (
        " (approximate: no profile for this exact model; the nearest profile of the same vendor is used, "
        "commands it does not know are counted in unknown_lines - say so in the summary)"
        if match == "approx"
        else ""
    )
    vars_ = {
        "device": f"d1 | {dev.name} | vendor={dev.vendor} | platform={dev.platform or '-'} | profile={profile or '-'}"
        f" | profile_match={match}{approx_note}",
        "objects": "\n".join(rows) or "(none)",
        "facts": "\n".join(f"{k} = {v}" for k, v in numbers.items()),
        "lang": LANG_NAMES.get(env.lang, "English"),
    }
    facts = {
        "objects": objects,
        "numbers": numbers,
        "lines": {"d1": numbers["lines"]},
        "names": sorted(names)[:MAX_NAMES],
        "lang": env.lang,  # 交接文档按语言取摘要（M8-3）
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

# 拓扑整理（topology-roles）在 M8-3 移到 ai_suggest_analysis.py（加了分组、分层与推测对端）。
