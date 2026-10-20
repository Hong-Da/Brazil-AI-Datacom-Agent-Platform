# 透网 LucidMesh Docker 镜像（多阶段构建）：Node 构建前端 → Python 运行。
# 构建：docker build -t lmesh:<版本> .（或 scripts/build_release.sh <版本> --targets docker，同时导出离线镜像）
# 运行：见 packaging/docker/compose.yaml（SQLite）与 compose.postgres.yaml（PostgreSQL），说明见 docs/deploy.md
# 基础镜像固定版本；代理与镜像源用 --build-arg 传入（HTTP_PROXY、HTTPS_PROXY、UV_INDEX_URL、NPM_CONFIG_REGISTRY）。

ARG NODE_IMAGE=node:24.22.0-trixie-slim
ARG PYTHON_IMAGE=python:3.12.13-slim-trixie
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.1

FROM ${UV_IMAGE} AS uv

# ---------- 前端 ----------
FROM ${NODE_IMAGE} AS web
ARG NPM_CONFIG_REGISTRY
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
WORKDIR /build/frontend
RUN corepack enable
# 先复制依赖清单与锁文件，利用构建缓存
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
# 产物输出到 ../src/lmesh/web/static（vite.config.ts）
RUN pnpm build

# ---------- 运行 ----------
FROM ${PYTHON_IMAGE} AS app
ARG LMESH_VERSION=dev
ARG UV_INDEX_URL
LABEL org.opencontainers.image.title="LucidMesh" \
      org.opencontainers.image.description="透网 LucidMesh：多厂商路由器配置的统一配置图" \
      org.opencontainers.image.version="${LMESH_VERSION}"
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUTF8=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LMESH_ROOT=/app \
    TMPDIR=/app/tmp/os \
    PATH=/app/.venv/bin:$PATH \
    LMESH_SERVER__HOST=0.0.0.0 \
    LMESH_SERVER__PORT=9090
WORKDIR /app
# 依赖（不含项目本身）：先复制锁文件，源码变化时不用重装
COPY pyproject.toml uv.lock ./
RUN mkdir -p /app/tmp/os \
    && uv sync --frozen --no-dev --no-install-project --no-cache \
    && rm /usr/local/bin/uv
# 程序：src/ 直接加入导入路径（python -m lmesh），版本号读 pyproject.toml
COPY src/lmesh ./src/lmesh
COPY --from=web /build/src/lmesh/web/static ./src/lmesh/web/static
COPY knowledge ./knowledge
COPY assets/brand ./assets/brand
COPY config/config.example.toml ./config/config.example.toml
RUN echo "/app/src" > "$(/app/.venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')/lmesh-src.pth" \
    && /app/.venv/bin/python -c "import lmesh, sys; sys.exit(0 if lmesh.__version__ != '0.0.0' else 1)" \
    && printf '#!/bin/sh\nexec /app/.venv/bin/python -m lmesh "$@"\n' > /app/.venv/bin/lmesh \
    && chmod 755 /app/.venv/bin/lmesh \
    && rm -rf /app/knowledge/.git \
    && /app/.venv/bin/python -m compileall -q /app/src \
    && groupadd --system --gid 10001 lmesh \
    && useradd --system --uid 10001 --gid lmesh --home-dir /app --no-create-home --shell /usr/sbin/nologin lmesh \
    && mkdir -p data logs cache tmp/os \
    && chown -R lmesh:lmesh data config logs cache tmp
USER lmesh
EXPOSE 9090
# 数据、配置、日志用卷挂载（compose 中为命名卷）：/app/data、/app/config、/app/logs
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/v1/health' % os.environ.get('LMESH_SERVER__PORT', '9090'), timeout=4)"
CMD ["python", "-m", "lmesh", "serve"]
