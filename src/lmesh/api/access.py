"""接口的项目归属与权限级别（M6，REQ-035 / REQ-036）：权限矩阵集中在这里，路由文件不必各自判断。

- 项目接口（PROJECT）：同时挂在 /api/v1/projects/{project}/… 与旧的 /api/v1/…（兼容别名，落到调用者的默认项目，
  响应头 Deprecation: true 与 Link 指向项目路径）。项目内的权限按项目角色：属主、可编辑成员、管理员可以修改；
  只读成员只能查看与计算（read / compute）。不是成员的普通账号返回 404。
- 级别：read（GET）、compute（不修改数据的 POST：对比、检查、翻译……）、write（修改数据）、kb（知识库与共享内容，
  管理员与知识库维护员）、self（项目管理中由 core 按项目角色判断）、public（不需要登录）。
  没有列出的非 GET 接口一律按 write。
- 只在项目路径下的接口（项目设置、成员、引用、规则调整、脚本一览……）由 routes_projects 的 project 路由器提供，
  没有旧路径别名。
- 只读的个人令牌只能调用 read 与 compute。
- 网络（M9，REQ-045）：项目接口同时挂在 /api/v1/projects/{project}/n/{network}/…（当前网络）；不带网络的项目路径与旧路径
  作用于项目的默认网络。项目层的操作（删除设备与版本、型号规则、项目设置、成员、引用、复制项目、网络管理本身）
  不挂网络路径，见 network_ok。权限仍按项目。
管理员专属接口仍由路由自己的 require_admin 判断。
"""

from __future__ import annotations

PUBLIC: set[str] = {
    "/health",
    "/setup",
    "/auth/status",
    "/auth/login",
    "/auth/bootstrap",
    "/auth/register",
    "/auth/logout",
}

PROJECT: set[str] = {
    "/summary",
    "/configs",
    "/configs/inspect",
    "/devices",
    "/devices/rebuild",
    "/devices/{device_id}/rebuild",
    "/devices/{device_id}/delete-preview",
    "/devices/{device_id}",
    "/devices/{device_id}/versions/{version_id}",
    "/devices/{device_id}/analysis",
    "/devices/{device_id}/check",
    "/devices/{device_id}/graph",
    "/devices/{device_id}/versions",
    "/devices/{device_id}/versions/{version_id}/text",
    "/devices/{device_id}/history",
    "/devices/{device_id}/history/diff",
    "/devices/{device_id}/history/object",
    "/devices/{device_id}/history/{version_id}/tag",
    "/devices/{device_id}/history/restore",
    "/devices/{device_id}/history/report",
    "/devices/{device_id}/profile-candidates",
    "/devices/{device_id}/profile",
    "/devices/{device_id}/support-request",
    "/model-rules",
    "/model-rules/test",
    "/model-rules/{rule_id}",
    "/unknown-lines",
    "/unknown-lines/states",
    "/unknown-lines/review",
    "/check",
    "/cleanup",
    "/check/ignores",
    "/check/ignores/{ignore_id}",
    "/compare",
    "/topology",
    "/consistency",
    "/migrate",
    "/migrate/suggest-map",
    "/baseline",
    "/baseline/report",
    "/change",
    "/change/report",
    "/impact",
    "/export/table",
    "/reports",
    "/translate",
    "/translate-rules/test",
    "/templates/check",
    "/templates/extract",
    "/query",
    "/ask",
    "/guard",
    "/generate",
    "/check-projects",
    "/check-projects/ai-rules",
    "/check-projects/{pid}",
    "/check-projects/{pid}/scripts",
    "/check-projects/{pid}/scripts/{sid}",
    "/check-projects/{pid}/scripts/{sid}/check",
    "/check-projects/{pid}/scripts/{sid}/reorder",
    "/check-projects/{pid}/scripts/{sid}/revisions",
    "/check-projects/{pid}/scripts/{sid}/revisions/{rid}",
    "/check-projects/{pid}/scripts/{sid}/revisions/{rid}/restore",
    "/check-projects/diff",
    "/check-projects/diff/report",
    "/scripts",
}

# 不修改数据的 POST（只读成员、只读令牌也可以调用）
COMPUTE: set[tuple[str, str]] = {
    ("POST", p)
    for p in (
        "/sanitize",
        "/parse",
        "/render",
        "/analysis",
        "/check",
        "/cleanup",
        "/compare",
        "/topology",
        "/consistency",
        "/migrate",
        "/migrate/suggest-map",
        "/baseline",
        "/baseline/report",
        "/change",
        "/change/report",
        "/impact",
        "/export/table",
        "/reports",
        "/translate",
        "/translate-rules/match",
        "/translate-rules/test",
        "/templates/check",
        "/templates/extract",
        "/templates/draft",
        "/templates/generate",
        "/query",
        "/ask",
        "/guard",
        "/generate",
        "/devices/{device_id}/history/restore",
        "/devices/{device_id}/history/report",
        "/check-projects/{pid}/scripts/{sid}/check",
        "/check-projects/diff",
        "/check-projects/diff/report",
        "/kb/validate",
        "/unknown-lines/review",
        "/ai/suggestions/estimate",
        "/ai/kb/extract-text",
        "/configs/inspect",
        "/devices/{device_id}/support-request",
        "/model-rules/test",
    )
}

# 项目管理中由 core 按项目角色判断的操作（守卫不要求可写，只拦只读令牌）：删除项目、成员、转交只限属主与管理员，
# 退出项目（移除自己）、复制项目或设备到自己的项目只需能查看（D-0179）
SELF: set[tuple[str, str]] = {
    ("DELETE", ""),
    ("PUT", "/members/{username}"),
    ("DELETE", "/members/{username}"),
    ("POST", "/transfer"),
    ("POST", "/copy"),
    ("POST", "/devices/{device_id}/copy"),
}

# 知识库与共享内容：管理员与知识库维护员（REQ-036）
KB: set[tuple[str, str]] = {
    ("PUT", "/kb/schema/nodes/{node_id}"),
    ("DELETE", "/kb/schema/nodes/{node_id}"),
    ("POST", "/kb/profiles"),
    ("PUT", "/kb/profiles/{profile_id}/entries/{node_id}"),
    ("DELETE", "/kb/profiles/{profile_id}/entries/{node_id}"),
    ("POST", "/kb/import"),
    ("POST", "/kb/ingest"),
    ("POST", "/kb/releases"),
    ("POST", "/kb/rollback"),
    ("POST", "/review/{item_id}"),
    ("POST", "/review/batch"),
    ("PUT", "/kb/rules/{rule_id}"),
    ("POST", "/kb/model-support/{item_id}/derive"),
    ("POST", "/kb/model-support/{item_id}/retarget"),
}


# 只在项目层、不挂网络路径的项目接口（项目设备池的管理）
NETWORK_EXCLUDE: set[tuple[str, str]] = {
    ("DELETE", "/devices/{device_id}"),
    ("DELETE", "/devices/{device_id}/versions/{version_id}"),
    ("GET", "/devices/{device_id}/delete-preview"),
    ("GET", "/model-rules"),
    ("POST", "/model-rules"),
    ("POST", "/model-rules/test"),
    ("PUT", "/model-rules/{rule_id}"),
    ("DELETE", "/model-rules/{rule_id}"),
    ("PUT", "/devices/{device_id}/history/{version_id}/tag"),
    ("DELETE", "/devices/{device_id}/history/{version_id}/tag"),
}

# 只在项目路径下的接口（project_only 路由器）里，按网络的那些（其余为项目管理，不挂网络路径）
NETWORK_PROJECT_ONLY: tuple[str, ...] = ("/rules", "/scripts", "/ai/", "/view-annotations")


def network_ok(method: str, path: str, project_only: bool = False) -> bool:
    """接口是否也挂在网络路径 /projects/{project}/n/{network}/… 下。"""
    if (method, path) in NETWORK_EXCLUDE:
        return False
    if project_only:
        if path == "/ai/kb/sanitize-redact":
            return False
        return any(path == x or path.startswith(x if x.endswith("/") else x + "/") for x in NETWORK_PROJECT_ONLY)
    return path in PROJECT


def level(method: str, path: str, project_only: bool = False) -> str:
    """接口的权限级别（path 是不带 /api/v1 与项目前缀的路由路径）。"""
    if path in PUBLIC:
        return "public"
    if method in ("GET", "HEAD", "OPTIONS"):
        return "read"
    if project_only and (method, path) in SELF:
        return "self"
    if (method, path) in KB:
        return "kb"
    if (method, path) in COMPUTE:
        return "compute"
    return "write"


def is_project(path: str) -> bool:
    return path in PROJECT
