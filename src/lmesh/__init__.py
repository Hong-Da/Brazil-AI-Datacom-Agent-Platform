"""透网 LucidMesh：把多厂商路由器配置转换成统一配置图。"""

import re as _re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path as _Path


def _source_version() -> str | None:
    """从源码目录运行时（开发、离线安装包）读项目根目录 pyproject.toml 的版本：比已安装的元数据新（可编辑安装不会随版本号更新）。"""
    pp = _Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
    if not pp.exists():
        return None
    m = _re.search(r'(?m)^version\s*=\s*"([^"]+)"', pp.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def _version() -> str:
    found = _source_version()
    if found:
        return found
    try:
        return version("lmesh")
    except PackageNotFoundError:
        return "0.0.0"


__version__ = _version()
