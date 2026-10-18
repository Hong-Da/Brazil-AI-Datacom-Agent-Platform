"""CLI 用例：以子进程执行真实命令，检查退出码、stdout（JSON 按字段）、stderr。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import INPUTS, SAMPLES, prepare, run_cli
from tests.helpers import check_json, load_cases

CASES = load_cases("cli_cases.toml")


@pytest.mark.cli
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_cli_case(case: dict, tmp_root: Path, request: pytest.FixtureRequest) -> None:
    prepare(case.get("setup"), request)
    out = tmp_root / "out"
    args = [
        a.replace("{inputs}", str(INPUTS)).replace("{out}", str(out)).replace("{samples}", str(SAMPLES))
        for a in case["args"]
    ]
    r = run_cli(args, tmp_root, env=case.get("env"))
    assert r.returncode == case["expect_exit"], f"退出码 {r.returncode}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    for s in case.get("expect_stdout", []):
        assert s in r.stdout, f"stdout 中没有 {s!r}:\n{r.stdout}"
    for s in case.get("expect_stderr", []):
        assert s in r.stderr, f"stderr 中没有 {s!r}:\n{r.stderr}"
    if case.get("expect_json"):
        data = json.loads(r.stdout)
        assert not check_json(data, case["expect_json"]), check_json(data, case["expect_json"])
    if case["expect_exit"] != 0:
        assert r.stderr.strip(), "出错时 stderr 应有提示"
