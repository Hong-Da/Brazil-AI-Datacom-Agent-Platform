"""API 用例：离线用 TestClient；--live 时向运行中的实例发送真实请求（只执行 live = true 的用例）。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import TEST_TOKEN
from tests.helpers import check_json, load_cases

CASES = load_cases("api_cases.toml")


def _request(client: Any, case: dict[str, Any], token: str) -> Any:
    headers = dict(case.get("headers", {}))
    if case.get("auth"):
        headers["Authorization"] = f"Bearer {token}"
    return client.request(case["method"], case["path"], headers=headers, json=case.get("body"))


def _check(r: Any, case: dict[str, Any]) -> None:
    assert r.status_code == case["expect_status"], f"HTTP {r.status_code}: {r.text}"
    body = r.json()
    assert set(body) >= {"code", "message", "data"}, body
    problems = check_json(body, case.get("expect_json", {}))
    assert not problems, problems


@pytest.mark.api
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_api_case(case: dict[str, Any], tmp_root: Path, request: pytest.FixtureRequest) -> None:
    from fastapi.testclient import TestClient

    from lmesh.api import create_app

    if case.get("setup") == "configured":
        request.getfixturevalue("configured_root")
    client = TestClient(create_app())
    _check(_request(client, case, TEST_TOKEN), case)


LIVE = [c for c in CASES if c.get("live")]


@pytest.mark.live
@pytest.mark.parametrize("case", LIVE, ids=[c["id"] for c in LIVE])
def test_api_live(case: dict[str, Any]) -> None:
    base = os.environ.get("LMESH_LIVE_BASE_URL")
    token = os.environ.get("LMESH_LIVE_TOKEN", "")
    if not base:
        pytest.skip("在线测试：用 test 脚本的 --live --base-url <地址> --token <令牌> 运行")
    import httpx

    with httpx.Client(base_url=base, timeout=30) as client:
        _check(_request(client, case, token), case)
