"""首次配置与环境变量（REQ-046 部署）：环境变量提供的数据库连接串不写进配置文件。"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_setup_does_not_write_env_database_url(tmp_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """数据库连接串来自环境变量（Docker 的 PostgreSQL 版）时，命令行向导 --defaults 不把带密码的连接串写进配置文件。"""
    from lmesh.core import config, setup

    url = "sqlite:///" + (tmp_root / "data" / "env.db").as_posix()
    monkeypatch.setenv("LMESH_DATABASE__URL", url)
    current = config.load()
    setup.apply({k: current.get(k) for k in current.values}, "zh-CN", check_port=False)
    assert url not in config.config_path().read_text(encoding="utf-8")
    assert config.load().database_url == url  # 环境变量照样生效
