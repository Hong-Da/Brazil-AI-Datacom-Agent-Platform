"""远程 API 与 Web 界面：FastAPI 应用。API 只做参数校验与序列化，业务逻辑调用 core。"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from lmesh import __version__, paths
from lmesh.api import scoping
from lmesh.api.common import E_INTERNAL, E_NOT_FOUND, E_PARAM, E_STATE, ApiError, error_response, project_error
from lmesh.api.routes_ai import admin as ai_admin_router
from lmesh.api.routes_ai import router as ai_router
from lmesh.api.routes_ai_change import router as ai_change_router
from lmesh.api.routes_ai_kb import router as ai_kb_router
from lmesh.api.routes_ai_suggest import router as ai_suggest_router
from lmesh.api.routes_analysis import router as analysis_router
from lmesh.api.routes_ask import router as ask_router
from lmesh.api.routes_ask_sessions import router as ask_sessions_router
from lmesh.api.routes_auth import admin as users_router
from lmesh.api.routes_auth import router as auth_router
from lmesh.api.routes_baseline import router as baseline_router
from lmesh.api.routes_change import router as change_router
from lmesh.api.routes_check import router as check_router
from lmesh.api.routes_check_projects import router as check_projects_router
from lmesh.api.routes_compare import router as compare_router
from lmesh.api.routes_configs import router as configs_router
from lmesh.api.routes_devices import router as devices_router
from lmesh.api.routes_export import router as export_router
from lmesh.api.routes_features import router as features_router
from lmesh.api.routes_graph import router as graph_router
from lmesh.api.routes_history import router as history_router
from lmesh.api.routes_joining import admin as joining_admin_router
from lmesh.api.routes_joining import project as joining_project_router
from lmesh.api.routes_joining import router as joining_router
from lmesh.api.routes_kb import router as kb_router
from lmesh.api.routes_migrate import router as migrate_router
from lmesh.api.routes_models import router as models_router
from lmesh.api.routes_networks import router as networks_router
from lmesh.api.routes_projects import admin as projects_admin_router
from lmesh.api.routes_projects import project as project_router
from lmesh.api.routes_projects import router as projects_router
from lmesh.api.routes_report import router as report_router
from lmesh.api.routes_rules import router as rules_router
from lmesh.api.routes_skills import admin as skills_admin_router
from lmesh.api.routes_skills import router as skills_router
from lmesh.api.routes_system import router as system_router
from lmesh.api.routes_tasks_ai import router as tasks_ai_router
from lmesh.api.routes_template import router as template_router
from lmesh.api.routes_tokens import router as tokens_router
from lmesh.api.routes_topology import router as topology_router
from lmesh.api.routes_translate import router as translate_router
from lmesh.api.routes_translate_rules import router as translate_rules_router
from lmesh.api.routes_workbench import router as workbench_router
from lmesh.core import analysis, config, history, projects

API_PREFIX = "/api/v1"
_log = logging.getLogger("lmesh.api")

_NOT_BUILT = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>透网 LucidMesh</title>
<body style="font-family:system-ui;padding:40px;line-height:1.7">
<h1>透网 LucidMesh</h1><p>前端还没有构建。运行根目录的 <code>start.bat</code> / <code>./start.sh</code> 会自动构建。</p>
<p>The web UI has not been built yet. Run <code>start.bat</code> / <code>./start.sh</code>.</p>
<p>A interface web ainda não foi gerada. Execute <code>start.bat</code> / <code>./start.sh</code>.</p>
<p>API: <a href="/api/v1/health">/api/v1/health</a> · <a href="/docs">/docs</a></p></body></html>"""


def _parse_error(key: str) -> ApiError:
    if key == "parse.no_profile":
        return ApiError(E_STATE, 409, "model.raw_only", data={"raw_only": True})
    return ApiError(E_PARAM, 422, key, profile="")


def create_app(settings: config.Settings | None = None, listen_host: str | None = None) -> FastAPI:
    app = FastAPI(
        title="LucidMesh API",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        description=(
            "透网 LucidMesh 远程 API。除 /health、/auth/status、/auth/login 与首次运行向导外，所有接口都需要登录："
            "网页用会话 Cookie，脚本用 Authorization: Bearer <令牌>（全局令牌或个人令牌 lmp_…）。"
            "设备相关接口在 /api/v1/projects/{project}/… 下；旧的无项目路径保留为兼容别名（调用者的默认项目，已弃用）。"
            "按网络的接口另挂在 /api/v1/projects/{project}/n/{network}/…；不带网络时作用于项目的默认网络。"
        ),
    )
    app.state.settings = settings or config.load()
    app.state.listen_host = listen_host or app.state.settings.get("server.host")
    app.state.boot_settings = app.state.settings  # 启动时的配置：系统设置页据此判断哪些修改要重启后才生效（REQ-049）
    # 创建项目的总开关（M9-8，REQ-050）：core 判断权限时用；保存设置时随之更新
    projects.set_create_open(bool(app.state.settings.get("auth.user_create_projects")))
    # 大响应压缩（REQ-055-24）：2 万行设备的配置分析 JSON 有二十多 MB，压缩后约十分之一；小响应不压
    app.add_middleware(GZipMiddleware, minimum_size=4096, compresslevel=5)

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(request, exc)

    @app.exception_handler(projects.ProjectError)
    async def _project_error(request: Request, exc: projects.ProjectError) -> JSONResponse:
        # 守卫或延迟解析默认项目时的项目错误（例如没有项目也不能创建项目：projects.no_project → 409）
        return error_response(request, project_error(exc))

    # 兜底（REQ-044）：只存原文的设备（认不出厂商或没有可用 Profile）没有配置图；某条路径没单独处理时也不报 500
    @app.exception_handler(analysis.AnalysisError)
    async def _analysis_error(request: Request, exc: analysis.AnalysisError) -> JSONResponse:
        return error_response(request, _parse_error(str(exc)))

    @app.exception_handler(history.HistoryError)
    async def _history_error(request: Request, exc: history.HistoryError) -> JSONResponse:
        if exc.key.startswith("parse."):
            return error_response(request, _parse_error(exc.key))
        status = {"not_found": 404, "state": 409}.get(exc.kind, 422)
        code = {404: E_NOT_FOUND, 409: E_STATE}.get(status, E_PARAM)
        return error_response(request, ApiError(code, status, exc.key, **exc.fmt))

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

    scoping.mount(app, system_router, API_PREFIX, "system")
    scoping.mount(app, auth_router, API_PREFIX, "auth")
    scoping.mount(app, users_router, API_PREFIX, "auth")
    scoping.mount(app, models_router, API_PREFIX, "models")
    scoping.mount(app, configs_router, API_PREFIX, "configs")
    scoping.mount(app, devices_router, API_PREFIX, "configs")
    scoping.mount(app, tasks_ai_router, API_PREFIX, "tasks-ai")
    scoping.mount(app, ai_router, API_PREFIX, "ai")
    scoping.mount(app, ai_admin_router, API_PREFIX, "ai")
    scoping.mount(app, kb_router, API_PREFIX, "knowledge")
    scoping.mount(app, graph_router, API_PREFIX, "graph")
    scoping.mount(app, analysis_router, API_PREFIX, "analysis")
    scoping.mount(app, compare_router, API_PREFIX, "compare")
    scoping.mount(app, check_router, API_PREFIX, "check")
    scoping.mount(app, rules_router, API_PREFIX, "check")
    scoping.mount(app, check_projects_router, API_PREFIX, "check-projects")
    scoping.mount(app, report_router, API_PREFIX, "report")
    scoping.mount(app, workbench_router, API_PREFIX, "workbench")
    scoping.mount(app, template_router, API_PREFIX, "template")
    scoping.mount(app, translate_router, API_PREFIX, "translate")
    scoping.mount(app, translate_rules_router, API_PREFIX, "translate")
    scoping.mount(app, topology_router, API_PREFIX, "topology")
    scoping.mount(app, migrate_router, API_PREFIX, "migrate")
    scoping.mount(app, baseline_router, API_PREFIX, "baseline")
    scoping.mount(app, change_router, API_PREFIX, "change")
    scoping.mount(app, history_router, API_PREFIX, "history")
    scoping.mount(app, export_router, API_PREFIX, "export")
    scoping.mount(app, features_router, API_PREFIX, "features")
    scoping.mount(app, ask_router, API_PREFIX, "ask")
    scoping.mount(app, ask_sessions_router, API_PREFIX, "ask")
    scoping.mount(app, skills_router, API_PREFIX, "ai-skills")
    scoping.mount(app, skills_admin_router, API_PREFIX, "ai-skills")
    scoping.mount(app, projects_router, API_PREFIX, "projects")
    scoping.mount(app, projects_admin_router, API_PREFIX, "projects")
    scoping.mount(app, project_router, API_PREFIX, "projects", project_only=True)
    scoping.mount(app, joining_router, API_PREFIX, "projects")
    scoping.mount(app, joining_admin_router, API_PREFIX, "projects")
    scoping.mount(app, joining_project_router, API_PREFIX, "projects", project_only=True)
    scoping.mount(app, networks_router, API_PREFIX, "networks", project_only=True)
    scoping.mount(app, ai_suggest_router, API_PREFIX, "ai-suggestions", project_only=True)
    scoping.mount(app, ai_change_router, API_PREFIX, "ai-suggestions", project_only=True)
    scoping.mount(app, ai_kb_router, API_PREFIX, "ai-suggestions", project_only=True)
    scoping.mount(app, tokens_router, API_PREFIX, "tokens")
    scoping.add_deprecation_headers(app, API_PREFIX)
    scoping.add_project_ref_rewrite(app, API_PREFIX)
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
