"""个人 API 令牌接口（REQ-035）：生成、列表、撤销、从列表移除。只管理自己的令牌；令牌只在生成时返回一次。

全局令牌（security.api_token）没有对应账号，调用这些接口返回 409（tokens.need_account）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from lmesh.api.common import E_NOT_FOUND, E_PARAM, E_STATE, ApiError, Principal, db_of, ok, principal_of, require_token
from lmesh.core import tokens

router = APIRouter(dependencies=[Depends(require_token)])


def _me(request: Request) -> Principal:
    p = principal_of(request)
    if p.user_id is None:
        raise ApiError(E_STATE, 409, "tokens.need_account")
    return p


def _err(e: tokens.TokenError) -> ApiError:
    if e.kind == "not_found":
        return ApiError(E_NOT_FOUND, 404, e.key, **e.fmt)
    if e.kind == "state":
        return ApiError(E_STATE, 409, e.key, **e.fmt)
    return ApiError(E_PARAM, 422, e.key, **e.fmt)


@router.get("/tokens", summary="我的个人令牌：名称、前 8 个字符、只读、创建 / 过期时间、最后使用时间与地址、状态")
def list_tokens(request: Request) -> dict[str, Any]:
    p = _me(request)
    return ok(request, {"tokens": tokens.list_tokens(db_of(request), p.username)})


class TokenBody(BaseModel):
    name: str = Field(..., max_length=200, description="用途说明")
    read_only: bool = Field(False, description="只读：只能读取与计算，不能修改")
    days: int | None = Field(
        tokens.DEFAULT_DAYS, ge=0, le=tokens.MAX_DAYS, description="有效天数；0 或 null 表示不过期"
    )


@router.post("/tokens", summary="生成个人令牌：返回的 token 只出现这一次（lmp_ 开头），之后只显示前 8 个字符")
def create_token(request: Request, body: TokenBody) -> dict[str, Any]:
    p = _me(request)
    try:
        return ok(request, tokens.create(db_of(request), p.username, body.name, body.read_only, body.days))
    except tokens.TokenError as e:
        raise _err(e) from e


@router.post("/tokens/{token_id}/revoke", summary="撤销令牌（立即失效）")
def revoke_token(request: Request, token_id: int) -> dict[str, Any]:
    p = _me(request)
    try:
        return ok(request, tokens.revoke(db_of(request), p.username, token_id))
    except tokens.TokenError as e:
        raise _err(e) from e


@router.delete("/tokens/{token_id}", summary="从列表移除已撤销或已过期的令牌（有效的令牌先撤销，409）")
def remove_token(request: Request, token_id: int) -> dict[str, Any]:
    p = _me(request)
    try:
        return ok(request, tokens.remove(db_of(request), p.username, token_id))
    except tokens.TokenError as e:
        raise _err(e) from e
