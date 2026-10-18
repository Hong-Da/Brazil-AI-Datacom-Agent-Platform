"""配置检查、冗余清理与检查规则接口。都需要令牌。"""

from __future__ import annotations

from typing import Any, Literal

import networkx as nx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from lmesh.api.common import E_NOT_FOUND, E_PARAM, E_STATE, ApiError, ok, require_token, settings_of
from lmesh.core import analysis, checks, cleanup, graphstore, importer, kbservice, store
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


def _device_graph(request: Request, kb: KnowledgeBase, device_id: int) -> nx.MultiDiGraph:
    db = settings_of(request).database_url
    store.upgrade(db)
    ver = graphstore.latest_version(db, device_id)
    if ver is None:
        raise ApiError(E_NOT_FOUND, 404)
    g, _, _ = graphstore.build_for_version(db, ver.id, kb)
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


@router.post("/check", summary="配置检查：悬空引用、孤儿对象（含级联）、互斥冲突、规则约束；按级别、规则、功能域汇总")
def check(request: Request, body: CheckBody) -> dict[str, Any]:
    kb, root = _kb(request)
    rules = _rules(kb, root)
    return ok(request, checks.check(_graph(request, kb, body), kb, rules, body.severity, body.domain))


@router.get("/devices/{device_id}/check", summary="检查设备的最新配置版本")
def device_check(
    request: Request, device_id: int, severity: Severity = "info", domain: str | None = None
) -> dict[str, Any]:
    kb, root = _kb(request)
    rules = _rules(kb, root)
    return ok(request, checks.check(_device_graph(request, kb, device_id), kb, rules, severity, domain))


@router.post("/cleanup", summary="冗余清理：为孤儿对象生成删除脚本（先删引用方），并验证删除后没有新的悬空引用")
def run_cleanup(request: Request, body: Target) -> dict[str, Any]:
    kb, _ = _kb(request)
    return ok(request, cleanup.cleanup(_graph(request, kb, body), kb))


@router.get("/kb/rules", summary="检查规则：内置检查与知识库 rules/ 中的规则（三种语言的标题、说明、建议）")
def kb_rules(request: Request) -> dict[str, Any]:
    kb, root = _kb(request)
    _rules(kb, root)
    return ok(request, checks.list_rules(kb, checks.rules_dir(root)))
