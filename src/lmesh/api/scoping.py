"""把路由按项目归属与权限级别挂到应用上（M6）。

- 项目接口：/api/v1/projects/{project}/… （依赖 project_guard）与旧路径 /api/v1/…（依赖 legacy_guard：调用者的默认
  项目；OpenAPI 标为 deprecated，响应头 Deprecation: true、Link: </api/v1/projects/<默认项目>/…>; rel="successor-version"）。
- 其他需要登录的接口：global_guard（只读令牌、知识库权限；普通账号的当前项目为其默认项目，用到时才解析）。
- 不需要登录的接口：不加依赖。
守卫是 async 依赖：在请求的上下文里设置当前项目与调用者（contextvars），随后在线程池里运行的路由函数能读到。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Path, Request
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from lmesh.api import access
from lmesh.api.common import E_FORBIDDEN, ApiError, Principal, db_of, project_error, require_token
from lmesh.core import projects

PROJECT_PREFIX = "/projects/{project}"


def _check_level(p: Principal, lvl: str) -> None:
    if p.read_only and lvl not in ("read", "compute", "public"):
        raise ApiError(E_FORBIDDEN, 403, "api.error.read_only_token")
    if lvl == "kb" and not p.is_kb_editor:
        raise ApiError(E_FORBIDDEN, 403, "api.error.kb_editor_only")


def _enter(request: Request, p: Principal, scope: projects.Scope, lvl: str, via: str) -> None:
    write = lvl in ("write", "kb")
    if lvl == "kb" and via == "path" and not p.is_kb_editor:
        raise ApiError(E_FORBIDDEN, 403, "api.error.kb_editor_only")
    if write and not scope.can_write:
        raise ApiError(E_FORBIDDEN, 403, "projects.read_only", project=scope.slug)
    projects.set_identity(p.identity())
    projects.set_scope(scope)
    request.state.scope = scope
    request.state.project_via = via


def _after(request: Request, scope: projects.Scope, lvl: str, audit: bool = True) -> None:
    """管理员访问他人项目写审计；写操作记录项目的最近活动。"""
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    db = db_of(request)
    if audit:
        projects.admin_access(db, scope, request.method, path, lvl in ("write", "kb", "self"))
    if lvl in ("write", "kb"):
        projects.touch(db, scope, f"{request.method} {path.replace('/api/v1', '').replace(PROJECT_PREFIX, '')}")


def project_guard(lvl: str) -> Callable[..., Awaitable[None]]:
    async def guard(
        request: Request,
        project: str = Path(..., description="项目标识（也可以写属主/标识或项目编号）"),
        p: Principal = Depends(require_token),
    ) -> None:
        _check_level(p, lvl)
        try:
            scope = await run_in_threadpool(projects.resolve, db_of(request), p.identity(), project)
        except projects.ProjectError as e:
            raise project_error(e) from e
        _enter(request, p, scope, lvl, "path")
        await run_in_threadpool(_after, request, scope, lvl)

    return guard


def legacy_guard(lvl: str) -> Callable[..., Awaitable[None]]:
    async def guard(request: Request, p: Principal = Depends(require_token)) -> None:
        _check_level(p, lvl)
        scope = await run_in_threadpool(projects.default_scope, db_of(request), p.identity())
        _enter(request, p, scope, lvl, "legacy")
        request.state.deprecated_successor = scope.slug
        # 全局令牌走旧路径时落到第一个管理员的默认项目，这是系统自身的调用，不按“管理员访问他人项目”审计
        await run_in_threadpool(_after, request, scope, lvl, p.user_id is not None)

    return guard


def global_guard(lvl: str) -> Callable[..., Awaitable[None]]:
    async def guard(request: Request, p: Principal = Depends(require_token)) -> None:
        _check_level(p, lvl)
        ident = p.identity()
        projects.set_identity(ident)
        if p.is_admin:
            projects.set_lazy(None)
        else:  # 普通账号：全局接口里万一用到设备，也只能是自己默认项目里的（用到时才解析）
            db = db_of(request)
            projects.set_lazy(lambda: projects.default_scope(db, ident))

    return guard


def _sub(routes: list[Any]) -> APIRouter:
    r = APIRouter()
    r.routes = routes
    return r


def mount(app: FastAPI, router: APIRouter, prefix: str, tag: str, project_only: bool = False) -> None:
    """按接口归属与级别分组挂载一个路由器。project_only：只挂在项目路径下（没有旧路径别名）。"""
    groups: dict[tuple[bool, str], list[Any]] = {}
    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        method = sorted(route.methods or {"GET"})[0]
        lvl = access.level(method, route.path, project_only)
        groups.setdefault((project_only or access.is_project(route.path), lvl), []).append(route)
    for (is_project, lvl), routes in groups.items():
        sub = _sub(routes)
        if lvl == "public":
            app.include_router(sub, prefix=prefix, tags=[tag])
        elif project_only:
            app.include_router(
                sub, prefix=prefix + PROJECT_PREFIX, tags=[tag], dependencies=[Depends(project_guard(lvl))]
            )
        elif is_project:
            app.include_router(
                sub, prefix=prefix + PROJECT_PREFIX, tags=[tag], dependencies=[Depends(project_guard(lvl))]
            )
            app.include_router(
                sub, prefix=prefix, tags=[tag], deprecated=True, dependencies=[Depends(legacy_guard(lvl))]
            )
        else:
            app.include_router(sub, prefix=prefix, tags=[tag], dependencies=[Depends(global_guard(lvl))])


def add_deprecation_headers(app: FastAPI, prefix: str) -> None:
    @app.middleware("http")
    async def _deprecation(request: Request, call_next: Callable[[Request], Awaitable[Any]]) -> Any:
        response = await call_next(request)
        slug = getattr(request.state, "deprecated_successor", None)
        if slug:
            rest = request.url.path[len(prefix) :] if request.url.path.startswith(prefix) else request.url.path
            response.headers["Deprecation"] = "true"
            response.headers["Link"] = f'<{prefix}/projects/{slug}{rest}>; rel="successor-version"'
        return response
