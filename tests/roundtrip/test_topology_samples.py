"""拓扑样本（knowledge/samples/topology/，有自己的清单）的往返回归：逐字一致、没有未识别行，清单覆盖目录中的全部样本。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmesh.core import analysis, roundtrip
from lmesh.core.kb import read_yaml

pytestmark = pytest.mark.roundtrip
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
TOPO = KB_ROOT / "samples" / "topology"
SAMPLES = list(read_yaml(TOPO / "manifest.yaml")["samples"])


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


@pytest.mark.parametrize("item", SAMPLES, ids=[s["file"] for s in SAMPLES])
def test_topology_sample_roundtrip(item: dict, kb) -> None:  # type: ignore[no-untyped-def]
    path = TOPO / item["file"]
    r = roundtrip.run(path.read_text(encoding="utf-8"), kb, item.get("profile"), path.stem)
    assert r["ok"], r["diffs"][:3]
    assert r["unknown"] == 0, f"有未识别行：{r['unknown']}"
    assert r["profile"] == item["profile"]


def test_manifest_covers_topology_samples() -> None:
    files = {p.name for p in TOPO.glob("*.cfg")}
    assert files == {s["file"] for s in SAMPLES}
