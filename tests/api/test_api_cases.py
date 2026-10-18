"""API 用例：离线用 TestClient；--live 时向运行中的实例发送真实请求（只执行 live = true 的用例）。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import INPUTS, TEST_TOKEN, prepare
from tests.helpers import check_json, load_cases

CASES = load_cases("api_cases.toml")


def _request(client: Any, case: dict[str, Any], token: str) -> Any:
    headers = dict(case.get("headers", {}))
    if case.get("auth"):
        headers["Authorization"] = f"Bearer {token}"
    if case.get("files"):
        files = [("files", (Path(f).name, (INPUTS / f).read_bytes(), "text/plain")) for f in case["files"]]
        return client.request(case["method"], case["path"], headers=headers, files=files, data=case.get("form", {}))
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

    prepare(case.get("setup"), request)
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


@pytest.mark.api
def test_ingest_background_task(configured_root: Path) -> None:
    """后台任务：提交导入 → 轮询到完成 → 结果中有新增的命令卡。"""
    import time

    from fastapi.testclient import TestClient

    from lmesh.api import create_app
    from tests.conftest import INPUTS

    client = TestClient(create_app())
    h = {"Authorization": f"Bearer {TEST_TOKEN}"}
    r = client.post(
        "/api/v1/kb/ingest",
        headers=h,
        json={"doc_dir": str(INPUTS / "docs" / "huawei"), "rules": str(INPUTS / "docs" / "rules-huawei-test.yaml")},
    )
    assert r.status_code == 200, r.text
    task_id = r.json()["data"]["task_id"]
    for _ in range(100):
        t = client.get(f"/api/v1/tasks/{task_id}", headers=h).json()["data"]
        if t["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert t["status"] == "done", t
    assert t["result"]["merge"]["new"] == 4
    exp = client.get("/api/v1/kb/export", headers=h)
    assert exp.status_code == 200 and exp.headers["content-type"] == "application/zip"


@pytest.mark.api
def test_import_then_device_graph(tmp_root: Path, request: pytest.FixtureRequest) -> None:
    """导入配置 → 建图入库 → GET /devices/{id}/graph 返回节点、依赖边与原文。"""
    from fastapi.testclient import TestClient

    from lmesh.api import create_app
    from tests.conftest import INPUTS

    prepare("configured-fullkb", request)
    client = TestClient(create_app())
    h = {"Authorization": f"Bearer {TEST_TOKEN}"}
    files = [("files", ("hw.cfg", (INPUTS / "configs" / "huawei" / "basic.cfg").read_bytes(), "text/plain"))]
    r = client.post("/api/v1/configs", headers=h, files=files, data={"level": "basic"})
    assert r.status_code == 200, r.text
    f = r.json()["data"]["files"][0]
    assert f["ok"] and f["unknown"] == 0 and f["coverage"] == 1.0
    dev = client.get("/api/v1/devices", headers=h).json()["data"]["devices"][0]
    g = client.get(f"/api/v1/devices/{dev['id']}/graph?raw=true", headers=h).json()["data"]
    kinds = {e["kind"] for e in g["edges"]}
    assert {"contains", "reference", "prerequisite", "side_effect"} <= kinds
    assert g["text"].startswith("!Software Version") and g["summary"]["nodes"] > 20
