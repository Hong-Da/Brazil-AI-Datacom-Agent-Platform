"""删除设备与单个配置版本（REQ-038）。

- 删除设备：连带删除配置版本（含快照）、图的节点与边、未识别行、导入记录、检查忽略项；
  被配置检查项目作基线时默认拒绝（列出项目与脚本），force 时把这些项目的基线设备与版本置空。
- 删除配置版本：最后一个版本不能单独删除（应删除设备）；删除最新版本后“最新”自然指向上一个版本；
  下一个版本的“相对上一快照的变化计数”作废并重算；被项目固定为基线的版本默认拒绝，force 时改为跟随最新版本。
- 删除预览：只返回计数与受影响的项目和脚本，不删除。
删除在一个事务内按子表到父表的顺序显式执行（不依赖数据库的级联设置），SQLite 与 PostgreSQL 行为一致；
日志只记录操作者、设备名与编号、删除的版本个数，不记录配置内容。
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from sqlalchemy import delete, func, select, update

from lmesh.core import store
from lmesh.core.store.models import (
    CheckIgnore,
    CheckProject,
    CheckScript,
    ConfigImport,
    ConfigVersion,
    Device,
    Edge,
    Node,
    UnknownLine,
    iso,
)

_log = logging.getLogger("lmesh.devices")


class DeleteError(ValueError):
    """kind：not_found（404 / 退出码 4）、conflict（409 / 退出码 1）。data 附删除预览或受影响的项目。"""

    def __init__(self, key: str, kind: str = "conflict", data: Any = None, **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.data, self.fmt = key, kind, data, fmt


# ---------------------------------------------------------------- 查询


def _device(s: Any, device_id: int) -> Device:
    dev = s.get(Device, device_id)
    if dev is None:
        raise DeleteError("device_delete.device_not_found", "not_found", device=device_id)
    return dev


def _version_ids(s: Any, device_id: int) -> list[int]:
    return list(
        s.scalars(select(ConfigVersion.id).where(ConfigVersion.device_id == device_id).order_by(ConfigVersion.id))
    )


def _count(s: Any, model: Any, col: Any, ids: list[int]) -> int:
    if not ids:
        return 0
    return int(s.scalar(select(func.count()).select_from(model).where(col.in_(ids))) or 0)


def _counts(s: Any, vids: list[int]) -> dict[str, int]:
    return {
        "versions": len(vids),
        "imports": _count(s, ConfigImport, ConfigImport.version_id, vids),
        "nodes": _count(s, Node, Node.version_id, vids),
        "edges": _count(s, Edge, Edge.version_id, vids),
        "unknown_lines": _count(s, UnknownLine, UnknownLine.version_id, vids),
    }


def _ignores(s: Any, device_id: int) -> int:
    return int(s.scalar(select(func.count()).select_from(CheckIgnore).where(CheckIgnore.device_id == device_id)) or 0)


def _project_refs(s: Any, projects: list[CheckProject]) -> list[dict[str, Any]]:
    out = []
    for p in projects:
        scripts = s.scalars(
            select(CheckScript).where(CheckScript.project_id == p.id).order_by(CheckScript.position, CheckScript.id)
        )
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "version_id": p.version_id,
                "follows_latest": p.version_id is None,
                "scripts": [{"id": x.id, "name": x.name, "kind": x.kind} for x in scripts],
            }
        )
    return out


def _projects_of_device(s: Any, device_id: int) -> list[CheckProject]:
    return list(s.scalars(select(CheckProject).where(CheckProject.device_id == device_id).order_by(CheckProject.id)))


def _dev_info(dev: Device) -> dict[str, Any]:
    return {"id": dev.id, "name": dev.name, "vendor": dev.vendor, "profile": dev.profile}


def _baseline(refs: list[dict[str, Any]]) -> dict[str, Any]:
    return {"projects": refs, "scripts": sum(len(p["scripts"]) for p in refs)}


def preview(db_url: str, device_id: int) -> dict[str, Any]:
    """删除设备的预览：将删除的内容计数、作基线的检查项目与脚本、每个版本（序号、是否最新、导入次数、固定它的项目）。"""
    with store.session(db_url) as s:
        dev = _device(s, device_id)
        vids = _version_ids(s, device_id)
        refs = _project_refs(s, _projects_of_device(s, device_id))
        imports: dict[int, int] = dict(
            s.execute(  # type: ignore[arg-type]
                select(ConfigImport.version_id, func.count())
                .where(ConfigImport.version_id.in_(vids))
                .group_by(ConfigImport.version_id)
            ).all()
        )
        rows = {v.id: v for v in s.scalars(select(ConfigVersion).where(ConfigVersion.device_id == device_id))}
        versions = [
            {
                "id": vid,
                "seq": i + 1,
                "latest": i == len(vids) - 1,
                "collected_at": iso(rows[vid].collected_at),
                "tag": rows[vid].tag,
                "imports": int(imports.get(vid, 0)),
                "pinned_by": [p["id"] for p in refs if p["version_id"] == vid],
            }
            for i, vid in enumerate(vids)
        ]
        return {
            "device": _dev_info(dev),
            "counts": {**_counts(s, vids), "check_ignores": _ignores(s, device_id)},
            "baseline": _baseline(refs),
            "versions": versions,
            "blocked": bool(refs),
        }


def _clear_caches() -> None:
    """进程内缓存的基线图（配置检查项目用）可能来自被删除的版本，一并清空。"""
    from lmesh.core import script_check

    script_check.clear_cache()


def _delete_versions(s: Any, vids: list[int]) -> None:
    if not vids:
        return
    s.execute(delete(Edge).where(Edge.version_id.in_(vids)))
    s.execute(delete(Node).where(Node.version_id.in_(vids)))
    s.execute(delete(UnknownLine).where(UnknownLine.version_id.in_(vids)))
    s.execute(delete(ConfigImport).where(ConfigImport.version_id.in_(vids)))
    s.execute(delete(ConfigVersion).where(ConfigVersion.id.in_(vids)))


# ---------------------------------------------------------------- 删除设备


def delete_device(db_url: str, device_id: int, force: bool = False, actor: str = "") -> dict[str, Any]:
    """删除设备与它的全部数据。被检查项目作基线时：不加 force 抛出 conflict（data 为删除预览）；加 force 时把基线置空。"""
    with store.session(db_url) as s:
        dev = _device(s, device_id)
        refs = _project_refs(s, _projects_of_device(s, device_id))
        blocked = bool(refs) and not force
        if not blocked:
            info = {"device": _dev_info(dev)}
            vids = _version_ids(s, device_id)
            counts = {**_counts(s, vids), "check_ignores": _ignores(s, device_id)}
            if refs:
                s.execute(
                    update(CheckProject)
                    .where(CheckProject.device_id == device_id)
                    .values(device_id=None, version_id=None)
                )
            s.execute(delete(CheckIgnore).where(CheckIgnore.device_id == device_id))
            _delete_versions(s, vids)
            name = dev.name
            s.execute(delete(Device).where(Device.id == device_id))
    if blocked:
        data = preview(db_url, device_id)
        raise DeleteError(
            "device_delete.baseline_in_use",
            data=data,
            projects=len(data["baseline"]["projects"]),
            scripts=data["baseline"]["scripts"],
        )
    _clear_caches()
    _log.info(
        "设备已删除：%s（编号 %d，配置版本 %d 个，清空基线的检查项目 %d 个，操作者 %s）",
        name,
        device_id,
        counts["versions"],
        len(refs),
        actor or "-",
    )
    return {
        "deleted": True,
        "device": info["device"],
        "counts": counts,
        "baseline_cleared": refs,
    }


# ---------------------------------------------------------------- 删除单个配置版本


def delete_version(
    db_url: str, device_id: int, version_id: int, force: bool = False, actor: str = "", kb: Any = None
) -> dict[str, Any]:
    """删除设备的一个配置版本。最后一个版本不能单独删除；被项目固定为基线时不加 force 拒绝，加 force 时这些项目改为跟随最新版本。
    给出 kb 时立即重算下一个版本相对上一快照的变化计数，否则留空（查看时间线时再算）。"""
    with store.session(db_url) as s:
        dev = _device(s, device_id)
        vids = _version_ids(s, device_id)
        if version_id not in vids:
            raise DeleteError("device_delete.version_not_found", "not_found", version=version_id, device=device_id)
        if len(vids) == 1:
            raise DeleteError("device_delete.last_version", device=dev.name)
        idx = vids.index(version_id)
        was_latest = idx == len(vids) - 1
        projects = _projects_of_device(s, device_id)
        pinned = _project_refs(s, [p for p in projects if p.version_id == version_id])
        moved = _project_refs(s, [p for p in projects if p.version_id is None]) if was_latest else []
        if pinned and not force:
            raise DeleteError(
                "device_delete.version_pinned",
                data={"baseline": _baseline(pinned)},
                version=version_id,
                projects=len(pinned),
            )
        counts = _counts(s, [version_id])
        counts.pop("versions")
        if pinned:
            s.execute(update(CheckProject).where(CheckProject.version_id == version_id).values(version_id=None))
        _delete_versions(s, [version_id])
        nxt = vids[idx + 1] if not was_latest else None
        if nxt is not None:  # 下一个版本的变化计数相对的是被删除的版本，作废后重算
            s.execute(update(ConfigVersion).where(ConfigVersion.id == nxt).values(change_summary=None))
        name, seq = dev.name, idx + 1
        latest = vids[-2] if was_latest else vids[-1]
    _clear_caches()
    if nxt is not None and kb is not None:
        from lmesh.core import history

        with contextlib.suppress(Exception):  # 变化计数只用于展示，失败时留空，查看时间线时再算
            history.ensure_summary(db_url, nxt, kb)
    _log.info(
        "配置版本已删除：设备 %s（编号 %d）的版本 %d（第 %d 个，%s），操作者 %s",
        name,
        device_id,
        version_id,
        seq,
        "最新" if was_latest else "非最新",
        actor or "-",
    )
    return {
        "deleted": True,
        "device_id": device_id,
        "version": {"id": version_id, "seq": seq, "latest": was_latest},
        "latest_version_id": latest,
        "versions_left": len(vids) - 1,
        "counts": counts,
        "baseline_cleared": pinned,
        "baseline_moved": moved,
        "recomputed": nxt,
    }
