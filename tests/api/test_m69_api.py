"""M6-9（M1 预览评审修改）用到的接口补充：向导确认页的写入路径与运行中的监听地址、Profile 条目的可选值与取值范围。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import TEST_TOKEN, prepare

pytestmark = pytest.mark.api
H = {"Authorization": f"Bearer {TEST_TOKEN}"}


def _client() -> Any:
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    return TestClient(create_app())


def test_setup_schema_has_config_path_and_running(tmp_root: Path) -> None:
    from lmesh.core import config

    r = _client().get("/api/v1/setup")
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["config_path"] == str(config.config_path())
    assert set(d["running"]) == {"server.host", "server.port"}
    assert isinstance(d["running"]["server.port"], int)


def test_profile_entries_carry_choices_and_range(tmp_root: Path, request: pytest.FixtureRequest) -> None:
    prepare("configured", request)
    c = _client()
    pid = c.get("/api/v1/kb/profiles", headers=H).json()["data"]["profiles"][0]["id"]
    entries = c.get(f"/api/v1/kb/profiles/{pid}", headers=H).json()["data"]["entries"]
    enums = [e for e in entries if e["type"] == "enum"]
    assert enums and all(isinstance(e["choices"], list) and e["choices"] for e in enums)
    ranged = [e for e in entries if "range" in e]
    assert ranged and all(e["type"] == "integer" and len(e["range"]) == 2 for e in ranged)
    assert all("choices" not in e for e in entries if e["type"] == "boolean")
