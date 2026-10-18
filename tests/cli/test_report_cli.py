"""按设备忽略检查发现并导出报告（CLI）：导入 → ignore add（原因必填）→ check 统计变化 → report check → ignore remove。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import INPUTS, prepare, run_cli

pytestmark = pytest.mark.cli


def test_ignore_flow_and_device_report(tmp_root: Path, request: pytest.FixtureRequest) -> None:
    prepare("configured-fullkb", request)
    r = run_cli(
        ["--output", "json", "config", "import", str(INPUTS / "configs" / "check" / "cisco-issues.cfg")], tmp_root
    )
    assert r.returncode == 0, r.stderr
    name = json.loads(r.stdout)["data"]["files"][0]["device"]
    node = "rp.policy[UNUSED-MAP]"

    r = run_cli(["ignore", "add", name, "ref.orphan", node], tmp_root)  # 没写原因
    assert r.returncode == 2 and "reason" in r.stderr
    r = run_cli(["ignore", "add", name, "no.such.rule", node, "--reason", "x"], tmp_root)
    assert r.returncode == 4
    r = run_cli(["--output", "json", "ignore", "add", name, "ref.orphan", node, "--reason", "保留"], tmp_root)
    assert r.returncode == 0, r.stderr
    ig = json.loads(r.stdout)["data"]

    r = run_cli(["--output", "json", "check", name], tmp_root)
    assert r.returncode == 1  # 仍有 error 级发现
    data = json.loads(r.stdout)["data"]
    assert data["summary"]["ignored"] == 1
    assert next(f for f in data["findings"] if f["node"] == node)["ignore_reason"] == "保留"
    r = run_cli(["--lang", "en", "check", name], tmp_root)
    assert "(ignored: 保留)" in r.stdout

    out = tmp_root / "out" / "check.md"
    r = run_cli(["--output", "json", "report", "check", name, "--format", "md", "-o", str(out)], tmp_root)
    assert r.returncode == 0, r.stderr
    text = out.read_text(encoding="utf-8")
    assert "## 已忽略的发现 (1)" in text and "| 配置版本 | #" in text

    r = run_cli(["--output", "json", "ignore", "list", "--device", name], tmp_root)
    assert [x["id"] for x in json.loads(r.stdout)["data"]["ignores"]] == [ig["id"]]
    r = run_cli(["--output", "json", "ignore", "remove", str(ig["id"])], tmp_root)
    assert r.returncode == 0 and json.loads(r.stdout)["data"]["deleted"]
