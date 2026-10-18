"""Web 界面需要的汇总与操作：首页概况、设备状态、按当前知识库重建、样本回归结果、未识别行送审、AI 设置。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select

from lmesh import paths
from lmesh.core import analysis, config, graphstore, kbservice, review, store
from lmesh.core import graph as graphmod
from lmesh.core.kb import repo
from lmesh.core.renderer import render_roundtrip
from lmesh.core.store.models import ConfigVersion, Device, UnknownLine

LAST_REGRESSION = "roundtrip-last.json"


# ---------- 样本回归 ----------


def regression_path() -> Path:
    return paths.data_dir() / LAST_REGRESSION


def run_regression(kb_root: Path) -> dict[str, Any]:
    """跑全部样本并保存结果（首页与发布页显示最近一次）。"""
    from lmesh.core import roundtrip

    r = roundtrip.regression(kb_root, kb=analysis.load_kb(kb_root))
    r["at"] = datetime.now(UTC).isoformat()
    try:
        regression_path().parent.mkdir(parents=True, exist_ok=True)
        regression_path().write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return r


def last_regression() -> dict[str, Any] | None:
    try:
        return json.loads(regression_path().read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (OSError, ValueError):
        return None


# ---------- 设备 ----------


def _status(ver: ConfigVersion) -> dict[str, Any]:
    st = ver.structured or {}
    counts = st.get("counts") or {}
    return {
        "lines": ver.raw_text.count("\n") + 1,
        "parsed": bool(st),
        "unknown": int(counts.get("unknown", 0)),
        "coverage": st.get("coverage"),
        "roundtrip": st.get("roundtrip"),
        "graph": st.get("graph"),
        "kb_version": ver.kb_version,
    }


def device_rows(db_url: str, kb_version: str) -> list[dict[str, Any]]:
    with store.session(db_url) as s:
        out = []
        for d in s.scalars(select(Device).order_by(Device.name)):
            latest = max(d.versions, key=lambda v: v.id, default=None)
            row: dict[str, Any] = {
                "id": d.id,
                "name": d.name,
                "vendor": d.vendor,
                "sw_version": d.sw_version,
                "profile": d.profile,
                "versions": len(d.versions),
                "latest_version_id": latest.id if latest else None,
                "source_name": latest.source_name if latest else "",
                "collected_at": latest.collected_at.isoformat() if latest else None,
            }
            if latest is not None:
                row.update(_status(latest))
                row["stale"] = bool(latest.kb_version) and latest.kb_version != kb_version
            out.append(row)
        return out


def analyse_version(db_url: str, version_id: int, kb_root: Path) -> dict[str, Any]:
    """按当前知识库重新解析一个配置版本：结构化结果、未识别行、配置图、往返结果。"""
    kb = analysis.load_kb(kb_root)
    with store.session(db_url) as s:
        ver = s.get(ConfigVersion, version_id)
        if ver is None:
            raise KeyError(version_id)
        dev = ver.device
        text = ver.raw_text
        try:
            res = analysis.parse_text(text, kb, dev.profile if dev.profile in kb.profiles else None)
        except analysis.AnalysisError:
            ver.structured = None
            return {"version_id": version_id, "parsed": False}
        dev.profile = res.profile
        g = graphmod.build(res.parsed, kb, res.profile, dev.name)
        st = res.parsed.as_dict()
        st["roundtrip"] = render_roundtrip(g, kb) == text.replace("\r\n", "\n")
        st["graph"] = graphmod.summary(g)
        ver.structured = st
        ver.kb_version = kb.version
        s.execute(delete(UnknownLine).where(UnknownLine.version_id == version_id))
    analysis.store_unknown(db_url, version_id, res.parsed)
    graphstore.save(db_url, version_id, g)
    return {
        "version_id": version_id,
        "parsed": True,
        "roundtrip": st["roundtrip"],
        "unknown": st["counts"].get("unknown", 0),
    }


def rebuild_all(db_url: str, kb_root: Path, progress: Any = None) -> dict[str, Any]:
    with store.session(db_url) as s:
        ids = [max(d.versions, key=lambda v: v.id).id for d in s.scalars(select(Device)) if d.versions]
    results = []
    for i, vid in enumerate(ids):
        results.append(analyse_version(db_url, vid, kb_root))
        if progress:
            progress(int((i + 1) * 100 / max(len(ids), 1)), f"{i + 1}/{len(ids)}")
    return {
        "devices": len(results),
        "roundtrip_failed": sum(1 for r in results if r.get("parsed") and not r.get("roundtrip")),
        "parse_failed": sum(1 for r in results if not r.get("parsed")),
    }


# ---------- 未识别行 ----------


def unknown_to_review(db_url: str, patterns: list[str]) -> dict[str, Any]:
    """把选中的未识别行模式送入审核队列（kind=unknown_line），已经送过的跳过。"""
    added, skipped = [], []
    with store.session(db_url) as s:
        pending = {i.target for i in review.list_items_raw(s, kind="unknown_line", status="pending")}
        for p in patterns:
            if p in pending:
                skipped.append(p)
                continue
            rows = s.execute(
                select(UnknownLine.text, UnknownLine.view, Device.name)
                .join(ConfigVersion, ConfigVersion.id == UnknownLine.version_id)
                .join(Device, Device.id == ConfigVersion.device_id)
                .where(UnknownLine.pattern == p)
                .limit(5)
            ).all()
            total = s.scalar(select(func.count()).select_from(UnknownLine).where(UnknownLine.pattern == p)) or 0
            if not rows:
                skipped.append(p)
                continue
            examples = [{"text": t, "view": v, "device": n} for t, v, n in rows]
            added.append((p, examples, total))
    ids = [
        review.add(db_url, "unknown_line", p, p, {"pattern": p, "examples": ex, "count": n}, {"method": "parser"})
        for p, ex, n in added
    ]
    return {"added": len(ids), "skipped": skipped, "ids": ids}


def unknown_states(db_url: str) -> dict[str, str]:
    """每个模式的处理状态：pending（已送审）/ approved / rejected；未送审的不在结果里。"""
    with store.session(db_url) as s:
        return {i.target: i.status for i in review.list_items_raw(s, kind="unknown_line")}


# ---------- 首页 ----------


def summary(settings: config.Settings) -> dict[str, Any]:
    from lmesh.core import ai
    from lmesh.core.kb import edit

    db = settings.database_url
    root = kbservice.runtime_root(settings)
    kb = analysis.load_kb(root)
    rows = edit.profile_rows(kb)
    counts = review.counts(db)
    unknown = analysis.unknown_summary(db, 1000)
    devices = device_rows(db, kb.version)
    rels = repo.releases(root) if (root / ".git").exists() else []
    draft = _draft_count(root, rels[0].tag if rels else None)
    return {
        "kb": {
            "version": kb.version,
            "released": rels[0].version if rels else None,
            "draft_changes": draft,
            "profiles": len(rows),
            "avg_coverage": round(sum(r["coverage"] for r in rows) / len(rows), 4) if rows else 0,
            "unfilled_profiles": sum(1 for r in rows if r["own_entries"] == 0 and not r["inherits"]),
            "cards": len(kb.cards),
            "nodes": len(kb.nodes),
        },
        "review": {"pending": sum(counts.values()), "by_kind": counts},
        "unknown": {
            "patterns": len(unknown),
            "total": sum(int(u.get("count", 0)) for u in unknown),
        },
        "devices": {
            "count": len(devices),
            "stale": sum(1 for d in devices if d.get("stale")),
            "roundtrip_failed": sum(1 for d in devices if d.get("parsed") and d.get("roundtrip") is False),
            "recent": sorted(devices, key=lambda d: d.get("collected_at") or "", reverse=True)[:5],
        },
        "regression": last_regression(),
        "ai": {"configured": ai.is_configured(settings)},
    }


def _draft_count(root: Path, tag: str | None) -> int:
    """草稿区修改数：上次发布以来变化的节点、命令卡、Profile 条目数；从未发布时为 0。"""
    if not tag:
        return 0
    try:
        d = kbservice.diff(root, tag)
    except Exception:  # noqa: BLE001 知识库仓库异常时首页仍能打开
        return 0
    return sum(len(v) for k, v in d.items() if isinstance(v, list))


# ---------- AI 设置 ----------

AI_KEYS = (
    "ai.provider",
    "ai.base_url",
    "ai.model",
    "ai.model_extract",
    "ai.model_merge",
    "ai.timeout",
    "ai.max_tokens",
)


def ai_settings(settings: config.Settings) -> dict[str, Any]:
    out: dict[str, Any] = {k.split(".", 1)[1]: settings.get(k) for k in AI_KEYS}
    out["api_key_set"] = bool(settings.get("ai.api_key"))
    out["sources"] = {k.split(".", 1)[1]: settings.sources.get(k, "default") for k in (*AI_KEYS, "ai.api_key")}
    return out


def save_ai_settings(body: dict[str, Any], lang: str) -> config.Settings:
    """写回配置文件：只改 AI 分组；API Key 为空表示保持原值，`clear_api_key` 为 true 时清除。"""
    current = config.load()
    values = {k: v for k, v in current.values.items() if current.sources.get(k) == "file"}
    for k in AI_KEYS:
        name = k.split(".", 1)[1]
        if name in body and body[name] is not None:
            values[k] = config.validate(k, body[name])
    if body.get("clear_api_key"):
        values["ai.api_key"] = ""
    elif body.get("api_key"):
        values["ai.api_key"] = config.encrypt_secret(str(body["api_key"]))
    config.write(values, lang)
    return config.load()
