"""远程 API 与 Web 界面：FastAPI 应用。API 只做参数校验与序列化，业务逻辑调用 core。"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from lmesh import __version__, paths
from lmesh.api.common import E_INTERNAL, E_NOT_FOUND, E_PARAM, ApiError, error_response
from lmesh.api.routes_check import router as check_router
from lmesh.api.routes_compare import router as compare_router
from lmesh.api.routes_configs import router as configs_router
from lmesh.api.routes_graph import router as graph_router
from lmesh.api.routes_kb import router as kb_router
from lmesh.api.routes_system import router as system_router
from lmesh.api.routes_tasks_ai import router as tasks_ai_router
from lmesh.api.routes_workbench import router as workbench_router
from lmesh.core import config

API_PREFIX = "/api/v1"
_log = logging.getLogger("lmesh.api")

_NOT_BUILT = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>透网 LucidMesh</title>
<body style="font-family:system-ui;padding:40px;line-height:1.7">
<h1>透网 LucidMesh</h1><p>前端还没有构建。运行根目录的 <code>start.bat</code> / <code>./start.sh</code> 会自动构建。</p>
<p>The web UI has not been built yet. Run <code>start.bat</code> / <code>./start.sh</code>.</p>
<p>A interface web ainda não foi gerada. Execute <code>start.bat</code> / <code>./start.sh</code>.</p>
<p>API: <a href="/api/v1/health">/api/v1/health</a> · <a href="/docs">/docs</a></p></body></html>"""


def create_app(settings: config.Settings | None = None, listen_host: str | None = None) -> FastAPI:
    app = FastAPI(
        title="LucidMesh API",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        description="透网 LucidMesh 远程 API。除 /health 与首次运行向导外，所有接口都需要 Authorization: Bearer <令牌>。",
    )
    app.state.settings = settings or config.load()
    app.state.listen_host = listen_host or app.state.settings.get("server.host")

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        detail = [{"loc": list(e.get("loc", [])), "msg": e.get("msg", "")} for e in exc.errors()]
        return error_response(request, ApiError(E_PARAM, 422, data={"detail": detail}))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = E_NOT_FOUND if exc.status_code == 404 else E_INTERNAL
        return error_response(request, ApiError(code, exc.status_code))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        _log.exception("未处理的异常：%s", request.url.path)
        return error_response(request, ApiError(E_INTERNAL, 500))

    app.include_router(system_router, prefix=API_PREFIX, tags=["system"])
    app.include_router(configs_router, prefix=API_PREFIX, tags=["configs"])
    app.include_router(tasks_ai_router, prefix=API_PREFIX, tags=["tasks-ai"])
    app.include_router(kb_router, prefix=API_PREFIX, tags=["knowledge"])
    app.include_router(graph_router, prefix=API_PREFIX, tags=["graph"])
    app.include_router(compare_router, prefix=API_PREFIX, tags=["compare"])
    app.include_router(check_router, prefix=API_PREFIX, tags=["check"])
    app.include_router(workbench_router, prefix=API_PREFIX, tags=["workbench"])
    _mount_web(app)
    return app


def _mount_web(app: FastAPI) -> None:
    static = paths.static_dir()
    index = static / "index.html"
    if (static / "assets").exists():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    def spa(full_path: str) -> FileResponse | HTMLResponse:
        if full_path.startswith("api/"):
            raise ApiError(E_NOT_FOUND, 404)
        candidate = (static / full_path).resolve()
        if full_path and candidate.is_file() and static.resolve() in candidate.parents:
            return FileResponse(candidate)
        if index.exists():
            return FileResponse(index)
        return HTMLResponse(_NOT_BUILT)
