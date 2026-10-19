"""AI 接口：公共与个人（REQ-040）。

- 管理员：/ai/connections（增删改查、测试连接）。个人接口对管理员也不可见。
- 本人：/me/ai（选择 auto / connection / personal / none，个人接口，测试）。只读令牌不能修改；全局 API 令牌没有账号，
  只能查看生效来源。
- 用量统计：/ai/usage 与 /ai/usage/export（CSV）；管理员看全部，其他账号只看自己的。
API Key 只进不出：任何返回值只有 api_key_set。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from lmesh.api.common import (
    E_EXTERNAL,
    E_NOT_FOUND,
    E_PARAM,
    E_STATE,
    ApiError,
    db_of,
    ok,
    principal_of,
    require_admin,
    require_token,
    settings_of,
)
from lmesh.core import ai, ai_connections

router = APIRouter(dependencies=[Depends(require_token)])
admin = APIRouter(dependencies=[Depends(require_admin)])

Provider = Literal["anthropic", "openai", "local"]


def _err(e: ai_connections.ConnError) -> ApiError:
    if e.kind == "not_found":
        return ApiError(E_NOT_FOUND, 404, e.key, data=e.data, **e.fmt)
    if e.kind == "state":
        return ApiError(E_STATE, 409, e.key, data=e.data, **e.fmt)
    return ApiError(E_PARAM, 422, e.key, data=e.data, **e.fmt)


class ConnFields(BaseModel):
    provider: Provider | None = None
    base_url: str | None = Field(None, max_length=500)
    api_key: str | None = Field(None, description="只写不读；不传时保留原值")
    clear_api_key: bool = False
    model: str | None = Field(None, max_length=120)
    model_extract: str | None = Field(None, max_length=120)
    model_merge: str | None = Field(None, max_length=120)
    model_ask: str | None = Field(None, max_length=120)
    model_generate: str | None = Field(None, max_length=120)


class ConnBody(ConnFields):
    name: str | None = Field(None, max_length=64)
    public: bool | None = Field(None, description="允许公共使用（普通账号可以选用）")
    enabled: bool | None = None


def _test(request: Request, conn: ai_connections.Conn) -> dict[str, Any]:
    try:
        return ok(request, ai.test(settings_of(request), conn))
    except ai.AIError as e:
        raise ApiError(E_EXTERNAL, 502, str(e)) from e


# ---------------------------------------------------------------- 管理员接口


@admin.get(
    "/ai/connections",
    summary="管理员 AI 接口列表：类型、地址、各用途模型、允许公共使用、启用、默认、选用人数、本月用量（不含 API Key）",
)
def list_connections(request: Request) -> dict[str, Any]:
    db_of(request)
    return ok(request, ai_connections.list_connections(settings_of(request)))


@admin.post("/ai/connections", summary="新建管理员 AI 接口（名称唯一；API Key 加密保存）")
def create_connection(request: Request, body: ConnBody) -> dict[str, Any]:
    db_of(request)
    try:
        return ok(request, ai_connections.create_connection(settings_of(request), body.model_dump()))
    except ai_connections.ConnError as e:
        raise _err(e) from e


@admin.get("/ai/connections/{cid}", summary="一个管理员 AI 接口的设置（不含 API Key）")
def get_connection(request: Request, cid: int) -> dict[str, Any]:
    db_of(request)
    try:
        return ok(request, ai_connections.get_connection(settings_of(request), cid))
    except ai_connections.ConnError as e:
        raise _err(e) from e


@admin.put(
    "/ai/connections/{cid}",
    summary="修改管理员 AI 接口：各字段可选，不传 api_key 时保留原值，clear_api_key 清除；关闭 public 后选了它的普通账号提示改选",
)
def update_connection(request: Request, cid: int, body: ConnBody) -> dict[str, Any]:
    db_of(request)
    try:
        return ok(request, ai_connections.update_connection(settings_of(request), cid, body.model_dump()))
    except ai_connections.ConnError as e:
        raise _err(e) from e


@admin.delete("/ai/connections/{cid}", summary="删除管理员 AI 接口；返回选了它的账号数（他们会看到改选提示）")
def delete_connection(request: Request, cid: int) -> dict[str, Any]:
    db_of(request)
    try:
        return ok(request, ai_connections.delete_connection(settings_of(request), cid))
    except ai_connections.ConnError as e:
        raise _err(e) from e


@admin.post("/ai/connections/{cid}/test", summary="测试管理员 AI 接口（不论是否启用、是否公共）；记入调用记录")
def test_connection(request: Request, cid: int) -> dict[str, Any]:
    db_of(request)
    s = settings_of(request)
    try:
        conn = ai_connections.admin_conn(s, cid)
    except ai_connections.ConnError as e:
        raise _err(e) from e
    if not ai_connections.complete(conn.provider, conn.base_url, conn.api_key_enc, conn.models.get("model", "")):
        raise ApiError(E_STATE, 409, "ai.conn.incomplete")
    return _test(request, conn)


# ---------------------------------------------------------------- 本人


@router.get(
    "/me/ai",
    summary="我的 AI：选择（auto / connection / personal / none）、个人接口（不含 Key）、可选的管理员接口、当前生效来源",
)
def get_mine(request: Request) -> dict[str, Any]:
    db_of(request)
    p = principal_of(request)
    return ok(request, ai_connections.mine(settings_of(request), p.identity() if p.user_id is not None else None))


class PersonalBody(ConnFields):
    pass


class MineBody(BaseModel):
    choice: Literal["auto", "connection", "personal", "none"] | None = None
    connection_id: int | None = Field(None, description="choice = connection 时必填：可选的管理员接口编号")
    personal: PersonalBody | None = Field(None, description="个人接口（新建或修改；不传 api_key 时保留原值）")
    remove_personal: bool = False
    no_token_warn: bool | None = Field(None, description="个人偏好：不提示大请求（优先于全局 ai.warn_tokens）")


@router.put(
    "/me/ai",
    summary="修改我的 AI：选择与个人接口（全局 API 令牌没有账号：409）；个人接口只有本人可见，管理员也看不到",
)
def put_mine(request: Request, body: MineBody) -> dict[str, Any]:
    db_of(request)
    p = principal_of(request)
    data = body.model_dump(exclude_none=True)
    try:
        return ok(request, ai_connections.save_mine(settings_of(request), p.identity(), data))
    except ai_connections.ConnError as e:
        raise _err(e) from e


class MineTestBody(BaseModel):
    target: Literal["personal", "effective"] = "personal"


@router.post("/me/ai/test", summary="测试我的个人接口（target = personal）或当前生效的接口（effective）")
def test_mine(request: Request, body: MineTestBody | None = None) -> dict[str, Any]:
    db_of(request)
    s = settings_of(request)
    target = body.target if body else "personal"
    if target == "personal":
        conn = ai_connections.personal_conn(s, principal_of(request).identity())
        if conn is None:
            raise ApiError(E_STATE, 409, "ai.personal_missing", data={"reason": "personal_missing"})
        return _test(request, conn)
    res = ai.resolve(s)
    if res.conn is None:
        raise ApiError(E_STATE, 409, "ai.not_configured", data=ai.not_configured_data(s))
    return _test(request, res.conn)


# ---------------------------------------------------------------- 用量统计

Group = Literal["day", "user", "connection", "feature", "model"]


def _usage(request: Request, start: date | None, end: date | None, user: str | None, cid: int | None) -> dict[str, Any]:
    p = principal_of(request)
    db = db_of(request)
    if p.is_admin:
        data = ai.usage(db, start, end, connection_id=cid, actor=user)
        return {**data, "scope": "all"}
    data = ai.usage(db, start, end, user_id=p.user_id if p.user_id is not None else -1, connection_id=cid)
    return {**data, "scope": "mine"}


@router.get(
    "/ai/usage",
    summary="AI 用量统计：范围内按天、账号、接口、功能、模型汇总调用次数、失败与 token（管理员看全部，其他账号只看自己的）",
)
def get_usage(
    request: Request,
    start: date | None = Query(None, alias="from", description="起始日期（UTC，含），默认结束日期前 29 天"),
    end: date | None = Query(None, alias="to", description="结束日期（UTC，含），默认今天"),
    user: str | None = Query(None, description="只统计这个账号（管理员）"),
    connection_id: int | None = Query(None, description="只统计这个管理员接口"),
) -> dict[str, Any]:
    return ok(request, _usage(request, start, end, user, connection_id))


@router.get(
    "/ai/usage/export", summary="导出用量统计的一组为 CSV（UTF-8 带 BOM；列 key,calls,errors,tokens_in,tokens_out）"
)
def export_usage(
    request: Request,
    group: Group = "day",
    start: date | None = Query(None, alias="from"),
    end: date | None = Query(None, alias="to"),
    user: str | None = Query(None),
    connection_id: int | None = Query(None),
) -> Response:
    data = _usage(request, start, end, user, connection_id)
    name = f"ai-usage-{group}-{data['from']}-{data['to']}.csv"
    return Response(
        ai.usage_csv(data, group),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
