"""对比基准（M2 验收门槛“真实配置无假差异”）：knowledge/samples/compare/manifest.yaml 的每个用例差异与期望完全一致。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmesh.core import analysis, compare
from lmesh.core.kb import read_yaml

pytestmark = pytest.mark.roundtrip
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
CASES = list((read_yaml(KB_ROOT / "samples" / "compare" / "manifest.yaml") or {}).get("cases") or [])


@pytest.fixture(scope="module")
def result() -> dict:  # type: ignore[type-arg]
    return compare.benchmark(KB_ROOT, analysis.load_kb(KB_ROOT))


@pytest.mark.parametrize("case_id", [c["id"] for c in CASES])
def test_compare_case(case_id: str, result: dict) -> None:  # type: ignore[type-arg]
    r = next(x for x in result["results"] if x["id"] == case_id)
    assert r["passed"], f"多报：{r['unexpected']}；漏报：{r['missing']}"


def test_benchmark_has_both_platforms(result: dict) -> None:  # type: ignore[type-arg]
    ids = [x["id"] for x in result["results"]]
    assert any(i.startswith("atn-") for i in ids) and any(i.startswith("asr920-") for i in ids)
    assert result["failed"] == 0


def test_variant_files_listed() -> None:
    base = KB_ROOT / "samples" / "compare"
    used = {Path(str(c[k])).name for c in CASES for k in ("a", "b")}
    assert {p.name for p in base.glob("*.cfg")} <= used, "compare 目录下有没被用例使用的变体文件"
