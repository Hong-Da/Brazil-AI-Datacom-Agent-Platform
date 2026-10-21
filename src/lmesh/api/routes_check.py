"""配置检查、冗余清理与检查规则接口。都需要令牌。"""

from __future__ import annotations

from typing import Any, Literal

import networkx as nx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from lmesh.api.common import E_NOT_FOUND, E_PARAM, E_STATE, ApiError, ok, require_token, settings_of
from lmesh.core import analysis, checks, cleanup, graphstore, ignores, importer, kbservice, networks, store
from lmesh.core import graph as graphmod
from lmesh.core import rules as rulesmod
from lmesh.core.kb import KnowledgeBase

router = APIRouter(dependencies=[Depends(require_token)])
Severity = Literal["error", "warning", "info"]


def _kb(request: Request) -> tuple[KnowledgeBase, Any]:
    root = kbservice.runtime_root(settings_of(request))
    return analysis.load_kb(root), root


def _rules(kb: KnowledgeBase, root: Any) -> list[rulesmod.Rule]:
    try:
        return rulesmod.load_cached(kb, checks.rules_dir(root))
    except rulesmod.RuleError as e:
        raise ApiError(E_STATE, 409, "rules.invalid", data={"issues": e.issues}, n=len(e.issues)) from e


def _overrides(root: Any) -> dict[str, dict[str, Any]]:
    try:
        return checks.load_overrides(checks.rules_dir(root))
    except rulesmod.RuleError as e:
        raise ApiError(E_STATE, 409, "rules.invalid", data={"issues": e.issues}, n=len(e.issues)) from e


def _ignores(request: Request, device_id: int | None) -> dict[tuple[str, str], dict[str, Any]] | None:
    if device_id is None:
        return None
    return ignores.index(settings_of(request).database_url, device_id)


def _device_graph(
    request: Request, kb: KnowledgeBase, device_id: int, version_id: int | None = None
) -> nx.MultiDiGraph:
    """设备的最新配置版本；给出 version_id 时取该版本（必须属于这台设备）。"""
    db = settings_of(request).database_url
    store.upgrade(db)
    if version_id is None:
        ver = graphstore.latest_version(db, device_id)
        if ver is None:
            raise ApiError(E_NOT_FOUND, 404)
        version_id = ver.id
    try:
        g, ver, _ = graphstore.build_for_version(db, version_id, kb)
    except KeyError as e:
        raise ApiError(E_NOT_FOUND, 404, "compare.version_not_found", version=version_id) from e
    except analysis.AnalysisError as e:
        # REQ-044：认不出厂商（或没有可用 Profile）的设备只存原文，没有配置图
        raise ApiError(E_STATE, 409, "model.raw_only", data={"raw_only": True, "version_id": version_id}) from e
    if ver.device_id != device_id:
        raise ApiError(E_NOT_FOUND, 404, "compare.version_not_found", version=version_id)
    return g


class Target(BaseModel):
    text: str | None = Field(None, max_length=importer.MAX_BYTES, description="配置文本（与 device_id 二选一）")
    device_id: int | None = Field(None, description="已导入设备的编号：取最新配置版本")
    profile: str | None = None


class CheckBody(Target):
    severity: Severity = Field("info", description="最低级别")
    domain: str | None = Field(None, description="只保留该功能域的发现")


def _graph(request: Request, kb: KnowledgeBase, body: Target) -> nx.MultiDiGraph:
    if (body.text is None) == (body.device_id is None):
        raise ApiError(E_PARAM, 422)
    if body.device_id is not None:
        return _device_graph(request, kb, body.device_id)
    try:
        res = analysis.parse_text(body.text or "", kb, body.profile)
    except analysis.AnalysisError as e:
        raise ApiError(E_PARAM, 422, str(e), profile=body.profile or "") from e
    return graphmod.build(res.parsed, kb, res.profile)


def run_check(request: Request, body: CheckBody) -> tuple[dict[str, Any], nx.MultiDiGraph, KnowledgeBase]:
    """POST /check 与报告共用：规则、内置检查的覆盖、设备的忽略记录。"""
    kb, root = _kb(request)
    rules = _rules(kb, root)
    g = _graph(request, kb, body)
    res = checks.check(g, kb, rules, body.severity, body.domain, _overrides(root), _ignores(request, body.device_id))
    if body.device_id is not None:
        _record(request, body.device_id, None, body.severity, body.domain, res)
    return res, g, kb


def _record(
    request: Request, device_id: int, version_id: int | None, severity: str, domain: str | None, res: dict[str, Any]
) -> None:
    """完整检查（全部级别、不限功能域）的结果记到当前网络（M9：各网络的检查汇总）。"""
    if severity != "info" or domain:
        return
    db = settings_of(request).database_url
    if version_id is None:
        ver = graphstore.latest_version(db, device_id)
        version_id = ver.id if ver is not None else None
    networks.record_check(db, device_id, version_id, res.get("summary") or {})


@router.post("/check", summary="配置检查：悬空引用、孤儿对象（含级联）、互斥冲突、规则约束；按级别、规则、功能域汇总")
def check(request: Request, body: CheckBody) -> dict[str, Any]:
    return ok(request, run_check(request, body)[0])


@router.get("/devices/{device_id}/check", summary="检查设备的最新配置版本（或 version_id 指定的版本）")
def device_check(
    request: Request,
    device_id: int,
    severity: Severity = "info",
    domain: str | None = None,
    version_id: int | None = None,
) -> dict[str, Any]:
    kb, root = _kb(request)
    rules = _rules(kb, root)
    g = _device_graph(request, kb, device_id, version_id)
    res = checks.check(g, kb, rules, severity, domain, _overrides(root), _ignores(request, device_id))
    _record(request, device_id, version_id, severity, domain, res)
    return ok(request, res)


class CleanupBody(Target):
    objects: list[str] | None = Field(
        None, description="只清理这些对象（发现中的 node）；级联孤儿随父对象，父对象仍在时子对象跳过（skipped）"
    )


@router.post("/cleanup", summary="冗余清理：为孤儿对象生成删除脚本（先删引用方），并验证删除后没有新的悬空引用")
def run_cleanup(request: Request, body: CleanupBody) -> dict[str, Any]:
    kb, _ = _kb(request)
    return ok(request, cleanup.cleanup(_graph(request, kb, body), kb, objects=body.objects))


@router.get("/kb/rules", summary="检查规则：内置检查与知识库 rules/ 中的规则（三种语言的标题、说明、建议）")
def kb_rules(request: Request) -> dict[str, Any]:
    kb, root = _kb(request)
    _rules(kb, root)
    return ok(request, checks.list_rules(kb, checks.rules_dir(root)))
