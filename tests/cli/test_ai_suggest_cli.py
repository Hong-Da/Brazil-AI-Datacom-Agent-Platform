"""AI 建议命令行（M8-2）的连续操作：回放运行 → 列表 → 采纳 → 视图标注 → 撤销（用例数据里每条用例各自准备，连续操作写在这里）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import INPUTS, prepare, run_cli

pytestmark = pytest.mark.cli
PROJ = ["--output", "json", "--project", "alice/lab", "ai", "suggest"]


def _ok(args: list[str], root: Path) -> dict:  # type: ignore[type-arg]
    r = run_cli([*PROJ, *args], root)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["data"]  # type: ignore[no-any-return]


def test_run_adopt_revert(tmp_root: Path, request: pytest.FixtureRequest) -> None:
    prepare("configured-fullkb-suggest", request)
    b = _ok(
        ["run", "device-summary", "--device", "ATN-CHANGE-01", "--replay", str(INPUTS / "ai-suggest" / "summary.json")],
        tmp_root,
    )
    sid = b["items"][0]["id"]
    assert b["batch"]["mode"] == "replay" and b["items"][0]["check"]["display"].startswith("ATN-CHANGE-01 has ")
    assert _ok(["list", "--batch", str(b["batch"]["id"])], tmp_root)["total"] == 1
    assert _ok(["adopt", str(sid)], tmp_root)["items"][0]["status"] == "adopted"
    assert _ok(["adopt", "1"], tmp_root)["items"][0]["adopt_info"]["value"] == "access"
    ann = _ok(["annotations"], tmp_root)["items"]
    assert [(a["key"], a["value"], a["source"]) for a in ann] == [("role", "access", "ai")]
    back = _ok(["revert", "1", str(sid)], tmp_root)["items"]
    assert [x["status"] for x in back] == ["reverted", "reverted"]
    assert _ok(["annotations"], tmp_root)["items"] == []
    assert _ok(["list", "--status", "reverted"], tmp_root)["total"] == 2
