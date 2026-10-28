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
from lmesh.core.parser import line_count
from lmesh.core.renderer import render_roundtrip
from lmesh.core.store.models import ConfigVersion, Device, UnknownLine, iso

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
        "lines": line_count(ver.raw_text),
        "parsed": bool(st),
        "unknown": int(counts.get("unknown", 0)),
        "coverage": st.get("coverage"),
        "roundtrip": st.get("roundtrip"),
        "graph": st.get("graph"),
        "kb_version": ver.kb_version,
    }


def device_rows(db_url: str, kb_version: str) -> list[dict[str, Any]]:
    """当前项目的设备（私有与引用的公共设备）：当前版本（引用固定了版本时为该版本）、解析状态、来源、
    Profile 来源与近似标记（REQ-044）。"""
    from lmesh.core import model_support, networks, projects
    from lmesh.core.store.models import Network

    with store.session(db_url) as s:
        pinned = projects.pins(s)
        sc = projects.current()
        nets = networks.networks_of_devices(s, sc.project_id) if sc is not None else {}
        cur = s.get(Network, sc.network_id) if sc is not None and sc.network_id else None
        checks = (cur.stats or {}).get("checks") or {} if cur is not None else {}
        out = []
        for d in s.scalars(projects.scoped_devices(select(Device)).order_by(Device.name)):
            newest = max(d.versions, key=lambda v: v.id, default=None)
            pin = pinned.get(d.id)
            latest = next((v for v in d.versions if v.id == pin), newest) if pin else newest
            row: dict[str, Any] = {
                "id": d.id,
                "name": d.name,
                "vendor": d.vendor,
                "sw_version": d.sw_version,
                "profile": d.profile,
                "versions": len(d.versions),
                "latest_version_id": latest.id if latest else None,
                "source_name": latest.source_name if latest else "",
                "collected_at": iso(latest.collected_at) if latest else None,
            }
            if latest is not None:
                row.update(_status(latest))
                row["stale"] = bool(latest.kb_version) and latest.kb_version != kb_version
            row.update(model_support.device_info(d, latest))
            row.update(projects.source_info(s, d, newest.id if newest else None))
            if sc is not None:
                # M9：设备在哪些网络里（与各网络用的版本）、本网络最近的检查结果
                row["networks"] = nets.get(d.id, [])
                row["network_findings"] = checks.get(str(d.id))
            out.append(row)
        return out


def analyse_version(
    db_url: str, version_id: int, kb_root: Path, kb: Any = None, override: str | None = None
) -> dict[str, Any]:
    """按当前知识库重新解析一个配置版本：结构化结果、未识别行、配置图、往返结果。

    Profile 按 REQ-044 的选择顺序确定（override 是设备页“更换 Profile”的手工选择；之前的手工选择沿用；
    再按设备所属项目的型号规则、版本规则、fallback）；选不出时只存原文（parsed=False）。"""
    from lmesh.core import model_support

    kb = kb if kb is not None else analysis.load_kb(kb_root)
    with store.session(db_url) as s:
        ver = s.get(ConfigVersion, version_id)
        if ver is None:
            raise KeyError(version_id)
        dev = ver.device
        text = ver.raw_text
        ch = model_support.device_choice(s, kb, dev, text, override)
        model_support.apply_choice(dev, ch)
        try:
            if not ch.profile:
                raise analysis.AnalysisError("parse.no_profile")
            res = analysis.parse_text(text, kb, ch.profile)
        except analysis.AnalysisError:
            ver.structured = None
            s.execute(delete(UnknownLine).where(UnknownLine.version_id == version_id))
            return {"version_id": version_id, "parsed": False, "profile": ch.profile, "profile_source": ch.source}
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
        "coverage": st.get("coverage"),
        "profile": ch.profile,
        "profile_source": ch.source,
        "profile_rule_id": ch.rule_id,
    }


def rebuild_all(
    db_url: str, kb_root: Path, progress: Any = None, device_ids: list[int] | None = None
) -> dict[str, Any]:
    """按当前知识库重新解析设备的最新版本：device_ids 为空时全部设备（管理员），否则只解析这些设备（本项目）。"""
    with store.session(db_url) as s:
        q = select(Device) if device_ids is None else select(Device).where(Device.id.in_(device_ids))
        ids = [max(d.versions, key=lambda v: v.id).id for d in s.scalars(q) if d.versions]
    results = []
    kb = analysis.load_kb(kb_root)
    for i, vid in enumerate(ids):
        results.append(analyse_version(db_url, vid, kb_root, kb=kb))
        if progress:
            progress(int((i + 1) * 100 / max(len(ids), 1)), f"{i + 1}/{len(ids)}")
    return {
        "devices": len(results),
        "roundtrip_failed": sum(1 for r in results if r.get("parsed") and not r.get("roundtrip")),
        "parse_failed": sum(1 for r in results if not r.get("parsed")),
    }


# ---------- 未识别行 ----------


def unknown_to_review(db_url: str, patterns: list[str]) -> dict[str, Any]:
    """把选中的未识别行模式送入审核队列（kind=unknown_line），已经送过的跳过；示例只取当前项目中的设备。"""
    from lmesh.core import projects

    added, skipped = [], []
    with store.session(db_url) as s:
        pending = {i.target for i in review.list_items_raw(s, kind="unknown_line", status="pending")}
        for p in patterns:
            if p in pending:
                skipped.append(p)
                continue
            rows = s.execute(
                projects.scoped_devices(
                    select(UnknownLine.text, UnknownLine.view, Device.name)
                    .join(ConfigVersion, ConfigVersion.id == UnknownLine.version_id)
                    .join(Device, Device.id == ConfigVersion.device_id)
                    .where(UnknownLine.pattern == p)
                ).limit(5)
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
        "ai": {"configured": (res := ai.resolve(settings)).configured, "reason": res.reason},
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
_CONN_KEYS = ("provider", "base_url", "model", "model_extract", "model_merge")


def ai_settings(settings: config.Settings) -> dict[str, Any]:
    """旧接口 GET /ai/settings（deprecated，REQ-040）：第一个管理员 AI 接口的内容，加全局的超时与 max_tokens。"""
    from lmesh.core import ai_connections

    cid = ai_connections.first_admin_id(settings)
    conn = ai_connections.get_connection(settings, cid) if cid is not None else None
    out: dict[str, Any] = {k: (conn[k] if conn and conn["enabled"] else "") for k in _CONN_KEYS}
    out["timeout"], out["max_tokens"] = settings.get("ai.timeout"), settings.get("ai.max_tokens")
    out["api_key_set"] = bool(conn and conn["api_key_set"])
    src = "db" if conn else "default"
    out["sources"] = {
        **{k: src for k in (*_CONN_KEYS, "api_key")},
        **{k: settings.sources.get(f"ai.{k}", "default") for k in ("timeout", "max_tokens")},
    }
    out["connection_id"] = cid
    out["deprecated"] = True
    return out


def save_ai_settings(settings: config.Settings, body: dict[str, Any], lang: str) -> config.Settings | None:
    """旧接口 PUT /ai/settings（deprecated）：接口字段写入第一个管理员 AI 接口（没有时新建 default，允许公共使用；
    provider 为空表示停用它）；timeout / max_tokens 仍写配置文件（改了时返回重新读取的配置，否则 None）。
    校验失败抛 config.ConfigError。"""
    from lmesh.core import ai_connections

    limits = {k: body[k] for k in ("timeout", "max_tokens") if body.get(k) is not None}
    for k, v in limits.items():
        config.validate(f"ai.{k}", v)
    fields = {k: body[k] for k in (*_CONN_KEYS, "api_key", "clear_api_key") if body.get(k) not in (None, False)}
    cid = ai_connections.first_admin_id(settings)
    try:
        if body.get("provider") == "":
            if cid is not None:
                ai_connections.update_connection(settings, cid, {"enabled": False})
        elif fields:
            if body.get("provider") is not None:
                config.validate("ai.provider", body["provider"])
            if cid is None:
                ai_connections.create_connection(
                    settings, {"name": ai_connections.SEED_NAME, "public": True, "enabled": True, **fields}
                )
            else:
                ai_connections.update_connection(settings, cid, {**fields, "enabled": True})
    except ai_connections.ConnError as e:
        raise config.ConfigError(str((e.data or {}).get("error") or e.key)) from e
    if limits:
        return config.update_file({f"ai.{k}": v for k, v in limits.items()}, lang)
    return None
