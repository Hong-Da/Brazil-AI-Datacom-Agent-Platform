"""API 公共部分：统一返回结构、错误码、语言、令牌认证。

返回结构：{"code": 0, "message": "ok", "data": {...}}；message 按 Accept-Language 返回对应语言，code 与 data 不随语言变化。
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from lmesh.core import config, i18n

# 错误码表（同时写入 docs/api.md）
OK = 0
E_INTERNAL = 1000
E_PARAM = 1001
E_AUTH = 1002
E_STATE = 1003  # 未配置 / 已配置等状态不允许
E_NOT_FOUND = 1004
E_EXTERNAL = 1005

ERROR_CODES = {
    OK: "api.ok",
    E_INTERNAL: "api.error.internal",
    E_PARAM: "api.error.param",
    E_AUTH: "api.error.auth",
    E_STATE: "api.error.state",
    E_NOT_FOUND: "api.error.not_found",
    E_EXTERNAL: "api.error.external",
}


class ApiError(Exception):
    def __init__(self, code: int, http_status: int = 400, message_key: str | None = None, data: Any = None, **fmt: Any):
        super().__init__(code)
        self.code, self.http_status = code, http_status
        self.message_key = message_key or ERROR_CODES.get(code, "api.error.internal")
        self.data, self.fmt = data, fmt


def lang_of(request: Request) -> str:
    return i18n.from_accept_language(request.headers.get("accept-language"))


def ok(request: Request, data: Any = None) -> dict[str, Any]:
    return {"code": OK, "message": i18n.t("api.ok", lang_of(request)), "data": data}


def error_response(request: Request, err: ApiError) -> JSONResponse:
    lang = lang_of(request)
    body = {"code": err.code, "message": i18n.t(err.message_key, lang, **err.fmt), "data": err.data}
    return JSONResponse(body, status_code=err.http_status)


def settings_of(request: Request) -> config.Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def require_token(request: Request, settings: config.Settings = Depends(settings_of)) -> None:
    """需要认证的接口：Authorization: Bearer <令牌>。"""
    expected = str(settings.get("security.api_token") or "")
    header = request.headers.get("authorization", "")
    given = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not expected or not given or not secrets.compare_digest(given, expected):
        raise ApiError(E_AUTH, 401)
