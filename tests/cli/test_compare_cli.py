"""lmesh compare 按设备名与配置版本对比：先导入同一设备的两个版本，再用 设备名@版本编号 与 设备名（最新版本）对比。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import SAMPLES, prepare, run_cli

pytestmark = pytest.mark.cli


def test_compare_device_versions(tmp_root: Path, request: pytest.FixtureRequest) -> None:
    prepare("configured-fullkb", request)
    src = (SAMPLES / "cisco-iosxe-asr920-synthetic" / "pe-asr920-01.cfg").read_text(encoding="utf-8")
    d = tmp_root / "in"
    d.mkdir()
    (d / "v1.cfg").write_text(src, encoding="utf-8")
    (d / "v2.cfg").write_text(
        src.replace(" mtu 9216\n ip address 10.1.0.2", " mtu 9000\n ip address 10.1.0.2"), "utf-8"
    )
    r = run_cli(["--output", "json", "config", "import", str(d)], tmp_root)
    assert r.returncode == 0, r.stderr
    files = json.loads(r.stdout)["data"]["files"]
    name, v1, v2 = files[0]["device"], files[0]["version_id"], files[1]["version_id"]
    assert files[1]["device"] == name

    r = run_cli(["--output", "json", "compare", f"{name}@{v1}", name], tmp_root)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)["data"]
    assert [(x["kind"], x["node"]) for x in data["diffs"]] == [("changed", "interface[GigabitEthernet0/0/0]/mtu")]
    assert data["a"]["version_id"] == v1 and data["b"]["version_id"] == v2 and data["a"]["label"] == f"{name}@{v1}"

    r = run_cli(["--lang", "en", "compare", f"{name}@{v2}", str(d / "v2.cfg")], tmp_root)  # 设备版本与文件混合
    assert r.returncode == 0 and "No differences" in r.stdout, r.stdout

    r = run_cli(["compare", f"{name}@9999", name], tmp_root)
    assert r.returncode == 4 and "9999" in r.stderr
