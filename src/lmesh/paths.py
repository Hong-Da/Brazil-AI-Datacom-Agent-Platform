"""项目内的路径。所有运行时文件都以项目根目录为基准，可用环境变量 LMESH_ROOT 覆盖。"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def project_root() -> Path:
    env = os.environ.get("LMESH_ROOT")
    if env:
        return Path(env).resolve()
    if getattr(sys, "frozen", False):  # PyInstaller 打包后：可执行文件所在目录
        return Path(sys.executable).resolve().parent
    # 源码运行：src/lmesh/ 向上两级；找不到 pyproject.toml 时用当前目录
    candidate = PACKAGE_DIR.parent.parent
    if (candidate / "pyproject.toml").exists():
        return candidate
    return Path.cwd().resolve()


def root_path(*parts: str) -> Path:
    return project_root().joinpath(*parts)


def config_dir() -> Path:
    return root_path("config")


def data_dir() -> Path:
    return root_path("data")


def logs_dir() -> Path:
    return root_path("logs")


def static_dir() -> Path:
    return PACKAGE_DIR / "web" / "static"


def builtin_knowledge_dir() -> Path:
    """程序自带的知识库（随版本发布）。"""
    return root_path("knowledge")


def ensure_runtime_dirs() -> None:
    for d in (config_dir(), data_dir(), logs_dir(), root_path("cache"), root_path("tmp")):
        d.mkdir(parents=True, exist_ok=True)
