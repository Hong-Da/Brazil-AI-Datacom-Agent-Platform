"""配置图的存取：nodes / edges 表（每个配置版本一份，记录建图时的知识库版本），以及按设备重建图。"""

from __future__ import annotations

from typing import Any

import networkx as nx
from sqlalchemy import delete, select

from lmesh.core import analysis, store
from lmesh.core import graph as graphmod
from lmesh.core.kb import KnowledgeBase
from lmesh.core.store.models import ConfigVersion, Device, Edge, Node


def save(db_url: str, version_id: int, g: nx.MultiDiGraph) -> int:
    with store.session(db_url) as s:
        s.execute(delete(Edge).where(Edge.version_id == version_id))
        s.execute(delete(Node).where(Node.version_id == version_id))
        parent: dict[str, str] = {b: a for a, b, d in g.edges(data=True) if d.get("kind") == "contains"}
        s.bulk_insert_mappings(
            Node,
            [  # type: ignore[arg-type]
                {
                    "version_id": version_id,
                    "node_key": n,
                    "schema_type": d.get("schema") or d.get("kind", ""),
                    "value": _jsonable(d.get("value") if d.get("kind") not in ("raw", "unknown") else d.get("text")),
                    "origin": d.get("origin", "explicit"),
                    "line_start": min(d.get("lines") or [0]) or None,
                    "line_end": max(d.get("lines") or [0]) or None,
                    "parent_key": parent.get(n),
                }
                for n, d in g.nodes(data=True)
            ],
        )
        s.bulk_insert_mappings(
            Edge,
            [  # type: ignore[arg-type]
                {
                    "version_id": version_id,
                    "src_key": a,
                    "dst_key": b,
                    "kind": d.get("kind", "contains"),
                    "attrs": {"note": d["note"]} if d.get("note") else None,
                }
                for a, b, d in g.edges(data=True)
            ],
        )
        ver = s.get(ConfigVersion, version_id)
        if ver is not None:
            ver.kb_version = str(g.graph.get("kb_version", ""))
        return g.number_of_nodes()


def _jsonable(v: Any) -> Any:
    if isinstance(v, dict | list | str | int | float | bool) or v is None:
        return v
    return str(v)


def latest_version(db_url: str, device_id: int) -> ConfigVersion | None:
    with store.session(db_url) as s:
        return s.scalar(
            select(ConfigVersion).where(ConfigVersion.device_id == device_id).order_by(ConfigVersion.id.desc()).limit(1)
        )


def build_for_version(db_url: str, version_id: int, kb: KnowledgeBase) -> tuple[nx.MultiDiGraph, ConfigVersion, Device]:
    """用当前知识库重新建图（知识库更新后可以按新版本重新计算）。"""
    with store.session(db_url) as s:
        ver = s.get(ConfigVersion, version_id)
        if ver is None:
            raise KeyError(version_id)
        dev = s.get(Device, ver.device_id)
        assert dev is not None
        text, profile, name = ver.raw_text, dev.profile or None, dev.name
    res = analysis.parse_text(text, kb, profile if profile in kb.profiles else None)
    return graphmod.build(res.parsed, kb, res.profile, name), ver, dev
