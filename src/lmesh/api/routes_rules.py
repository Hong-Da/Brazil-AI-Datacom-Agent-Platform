"""检查规则的开关与级别、忽略检查发现（M2-5）。都需要令牌。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from lmesh.api.common import E_NOT_FOUND, E_PARAM, E_STATE, ApiError, ok, require_token, settings_of
from lmesh.api.routes_check import Severity, _kb, _rules
from lmesh.core import checks, ignores, rule_edit, store
from lmesh.core import rules as rulesmod

router = APIRouter(dependencies=[Depends(require_token)])


class RulePatch(BaseModel):
    enabled: bool | None = Field(None, description="启用或停用")
    severity: Severity | None = Field(None, description="级别：error / warning / info")


@router.put(
    "/kb/rules/{rule_id}", summary="修改检查规则的开关与级别（内置检查写入 rules/builtin.yaml），提交运行时知识库"
)
def put_rule(request: Request, rule_id: str, body: RulePatch) -> dict[str, Any]:
    kb, root = _kb(request)
    try:
        return ok(request, rule_edit.set_rule(root, kb, rule_id, body.enabled, body.severity))
    except rule_edit.RuleEditError as e:
        status, code = (404, E_NOT_FOUND) if e.kind == "not_found" else (422, E_PARAM)
        raise ApiError(code, status, e.key, **e.fmt) from e
    except rulesmod.RuleError as e:
        raise ApiError(E_STATE, 409, "rules.invalid", data={"issues": e.issues}, n=len(e.issues)) from e


class IgnoreBody(BaseModel):
    device_id: int
    rule: str = Field(..., max_length=120, description="规则编号")
    node: str = Field(..., max_length=600, description="发现的节点（规范编号，即发现的 node）")
    reason: str = Field(..., max_length=2000, description="忽略原因（必填）")


def _db(request: Request) -> str:
    url = settings_of(request).database_url
    store.upgrade(url)
    return url


def _ignore_error(e: ignores.IgnoreError) -> ApiError:
    if e.kind == "not_found":
        return ApiError(E_NOT_FOUND, 404, e.key, **e.fmt)
    return ApiError(E_PARAM, 422, e.key, **e.fmt)


@router.get("/check/ignores", summary="忽略的检查发现（可按设备筛选）")
def list_ignores(request: Request, device_id: int | None = None) -> dict[str, Any]:
    try:
        return ok(request, {"ignores": ignores.list_ignores(_db(request), device_id)})
    except ignores.IgnoreError as e:
        raise _ignore_error(e) from e


@router.post("/check/ignores", summary="忽略一条检查发现（按设备、规则、节点；必须写原因，重复提交时更新原因）")
def add_ignore(request: Request, body: IgnoreBody) -> dict[str, Any]:
    kb, root = _kb(request)
    known = set(checks.BUILTIN) | {r.id for r in _rules(kb, root)}
    try:
        return ok(request, ignores.add_ignore(_db(request), body.device_id, body.rule, body.node, body.reason, known))
    except ignores.IgnoreError as e:
        raise _ignore_error(e) from e


@router.delete("/check/ignores/{ignore_id}", summary="取消忽略")
def remove_ignore(request: Request, ignore_id: int) -> dict[str, Any]:
    try:
        return ok(request, ignores.remove_ignore(_db(request), ignore_id))
    except ignores.IgnoreError as e:
        raise _ignore_error(e) from e
