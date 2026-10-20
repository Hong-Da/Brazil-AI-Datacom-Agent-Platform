"""升级时合并程序自带的知识库（CLI，REQ-046）：自带知识库变化 → kb upgrade 采用未改过的文件、冲突进审核 → review → 回滚。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import prepare, run_cli

pytestmark = [pytest.mark.cli, pytest.mark.kb_write]


def test_upgrade_conflict_review_and_rollback(tmp_root: Path, request: pytest.FixtureRequest) -> None:
    prepare("configured", request)
    # 先用一次运行时知识库：从自带知识库复制、建仓并建立 builtin 基准
    r = run_cli(["--output", "json", "kb", "upgrade", "--dry-run"], tmp_root)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["data"]["changed"] is False

    builtin, runtime = tmp_root / "knowledge", tmp_root / "data" / "knowledge"
    adopt, both = "rules/common.yaml", "rules/cross-device.yaml"
    old_adopt = (runtime / adopt).read_text(encoding="utf-8")
    # 用户改了 both；新版本自带知识库改了 adopt 和 both
    (runtime / both).write_text((runtime / both).read_text(encoding="utf-8") + "# user\n", encoding="utf-8")
    for rel in (adopt, both):
        (builtin / rel).write_text((builtin / rel).read_text(encoding="utf-8") + "# new version\n", encoding="utf-8")

    r = run_cli(["--output", "json", "kb", "upgrade", "--dry-run"], tmp_root)
    plan = json.loads(r.stdout)["data"]
    assert plan["updated"] == [adopt] and plan["conflicts"] == [both] and plan["commit"] is None

    r = run_cli(["kb", "upgrade"], tmp_root)
    assert r.returncode == 0, r.stderr
    assert "冲突" in r.stdout and both in r.stdout and "--rollback" in r.stdout
    assert (runtime / adopt).read_text(encoding="utf-8").endswith("# new version\n")
    assert (runtime / both).read_text(encoding="utf-8").endswith("# user\n")  # 不覆盖用户版本

    r = run_cli(["--output", "json", "review", "list", "--kind", "conflict"], tmp_root)
    items = json.loads(r.stdout)["data"]["items"]
    assert [i["target"] for i in items] == [both] and items[0]["source"]["via"] == "kb-upgrade"

    r = run_cli(["--output", "json", "kb", "releases"], tmp_root)
    assert "LucidMesh" in json.loads(r.stdout)["data"]["releases"][0]["message"]

    r = run_cli(["--output", "json", "--yes", "kb", "upgrade", "--rollback"], tmp_root)
    assert r.returncode == 0, r.stderr
    assert (runtime / adopt).read_text(encoding="utf-8") == old_adopt
    # 回滚后不会在下次启动时再自动合并回去
    r = run_cli(["--output", "json", "kb", "upgrade", "--dry-run"], tmp_root)
    assert json.loads(r.stdout)["data"]["changed"] is False
