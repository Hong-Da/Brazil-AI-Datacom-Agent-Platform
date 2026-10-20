"""拓扑还原与跨设备一致性接口。都需要令牌。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from lmesh.api.common import E_NOT_FOUND, E_PARAM, E_STATE, ApiError, ok, require_token, settings_of
from lmesh.core import analysis, consistency, importer, kbservice, networks, projects, store, topology
from lmesh.core import rules as rulesmod
from lmesh.core.kb import KnowledgeBase

router = APIRouter(dependencies=[Depends(require_token)])
Severity = Literal["error", "warning", "info"]
MAX_CONFIGS = 200


def _kb(request: Request) -> tuple[KnowledgeBase, Any]:
    root = kbservice.runtime_root(settings_of(request))
    return analysis.load_kb(root), root


class ConfigText(BaseModel):
    name: str = Field("", max_length=200, description="文件名（配置中没有 sysname / hostname 时作为设备名）")
    text: str = Field(..., max_length=importer.MAX_BYTES, description="配置文本")
    profile: str | None = Field(None, description="Profile（默认自动识别）")


class TopologyBody(BaseModel):
    configs: list[ConfigText] = Field(default_factory=list, max_length=MAX_CONFIGS, description="上传的配置文本")
    device_ids: list[int] = Field(
        default_factory=list, description="已导入设备的编号（取最新配置版本）；configs 与 device_ids 都为空时取全部设备"
    )
    outside: bool = Field(False, description="同时返回网络外的对端（M9，只在非默认网络里有内容）")


class ConsistencyBody(TopologyBody):
    severity: Severity = Field("info", description="最低级别")


def _devices(request: Request, kb: KnowledgeBase, configs: list[ConfigText], targets: list[str] | None):
    """targets 为 None 表示全部已导入设备，[] 表示不取数据库中的设备。"""
    try:
        devices = topology.from_texts([c.model_dump() for c in configs], kb)
    except analysis.AnalysisError as e:
        raise ApiError(E_PARAM, 422, str(e), data={"source": getattr(e, "source", "")}, profile="") from e
    if targets is None or targets:
        db = settings_of(request).database_url
        store.upgrade(db)
        found, missing = topology.from_db(db, kb, targets)
        if missing:
            raise ApiError(E_NOT_FOUND, 404, "graph.target_not_found", target=", ".join(missing))
        devices += found
    if not devices:
        raise ApiError(E_STATE, 409, "topology.no_devices")
    for d, n in zip(devices, topology.unique_names([d.name for d in devices]), strict=True):
        d.name = n
    return devices


def _body_devices(request: Request, kb: KnowledgeBase, body: TopologyBody):
    if not body.configs and not body.device_ids:
        return _devices(request, kb, [], None)
    return _devices(request, kb, body.configs, [str(i) for i in body.device_ids])


def _with_networks(request: Request, kb: KnowledgeBase, devs: list[Any], outside: bool) -> dict[str, Any]:
    """拓扑结果加上网络信息（M9）：network（当前网络）、节点的 also_in（还在哪些网络，不含当前与默认网络）；
    outside=True 时 outside（网络外的对端：一端在本网络、另一端不在的链路，对端标出设备与所在的网络）。"""
    out = topology.to_json(topology.build(devs, kb))
    sc = projects.current()
    if sc is None or sc.network_id is None:
        return out
    db = settings_of(request).database_url
    out["network"] = {
        "id": sc.network_id,
        "slug": sc.network_slug,
        "name": sc.network_name,
        "default": sc.network_default,
    }
    also = networks.node_networks(db, sc)
    for n in out["nodes"]:
        n["also_in"] = also.get(n.get("device_id") or 0, [])
    if outside:
        inside = [d for d in devs if d.device_id is not None]
        out["outside"] = networks.outside_peers(db, sc, kb, inside)
        out["summary"]["outside"] = out["outside"]["count"]
    return out


@router.get(
    "/topology",
    summary="已导入设备的三层拓扑：nodes（设备）、links（两端设备与接口、网段、推导依据、类型、置信度）、跨设备依赖边；"
    "outside=true 时另给网络外的对端",
)
def get_topology(request: Request, devices: str | None = None, outside: bool = False) -> dict[str, Any]:
    kb, _ = _kb(request)
    targets = [t for t in (devices or "").split(",") if t.strip()] or None
    return ok(request, _with_networks(request, kb, _devices(request, kb, [], targets), outside))


@router.post("/topology", summary="上传多台设备的配置（可与已导入设备混合）推导三层拓扑")
def post_topology(request: Request, body: TopologyBody) -> dict[str, Any]:
    kb, _ = _kb(request)
    return ok(request, _with_networks(request, kb, _body_devices(request, kb, body), body.outside))


@router.post("/consistency", summary="跨设备一致性检查：拓扑 + 发现（挂在链路上），按级别、规则、链路、设备汇总")
def post_consistency(request: Request, body: ConsistencyBody) -> dict[str, Any]:
    kb, root = _kb(request)
    try:
        ruleset = consistency.load_cached(kb, consistency.rules_file(root))
    except rulesmod.RuleError as e:
        raise ApiError(E_STATE, 409, "rules.invalid", data={"issues": e.issues}, n=len(e.issues)) from e
    topo = topology.build(_body_devices(request, kb, body), kb)
    return ok(request, consistency.check(topo, kb, ruleset, body.severity))
