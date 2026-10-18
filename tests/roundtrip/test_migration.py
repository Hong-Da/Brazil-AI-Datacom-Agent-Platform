"""割接迁移回归（M4-5）：knowledge/samples/migration/manifest.yaml。

每个用例：新配置再解析没有未识别行，与旧设备按有效值对比（跨厂商 + 接口映射）除告警列出的差异外没有差异；
接口映射、未映射清单、告警种类符合清单中的期望。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lmesh.core import analysis, migration
from lmesh.core import graph as graphmod
from lmesh.core.kb import read_yaml

pytestmark = pytest.mark.roundtrip
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
BASE = KB_ROOT / "samples" / "migration"
CASES: list[dict[str, Any]] = list((read_yaml(BASE / "manifest.yaml") or {}).get("cases") or [])


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


def _run(kb: Any, case: dict[str, Any]) -> dict[str, Any]:
    res = analysis.parse_text((BASE / case["src"]).read_text(encoding="utf-8"), kb, case["src_profile"])
    g = graphmod.build(res.parsed, kb, res.profile, case["id"])
    ifmap = migration.load_map_file(BASE / case["interface_map"]) if case.get("interface_map") else None
    tg = (
        migration.target_graph_from_text(
            (BASE / case["target_config"]).read_text(encoding="utf-8"), kb, case["dst_profile"]
        )
        if case.get("target_config")
        else None
    )
    return migration.migrate(g, kb, res.profile, case["dst_profile"], ifmap, tg, case.get("model"))


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_migration_case(kb: Any, case: dict[str, Any]) -> None:
    r = _run(kb, case)
    assert r["verify"]["checked"]
    diffs = [w["params"] for w in r["warnings"] if w["kind"] in ("verify_diff", "verify_unknown", "verify_failed")]
    assert r["verify"]["unexplained"] == 0, diffs[:10]
    parsed = analysis.parse_text(r["text"], kb, case["dst_profile"]).parsed
    known_unknown = 0
    if case.get("target_config"):
        known_unknown = (
            analysis.parse_text((BASE / case["target_config"]).read_text(encoding="utf-8"), kb, case["dst_profile"])
            .parsed.counts()
            .get("unknown", 0)
        )
    assert parsed.counts().get("unknown", 0) <= known_unknown, [ln.text for ln in parsed.unknown()][:5]
    got = {m["source"]: m["target"] for m in r["interface_map"]}
    for src, dst in (case.get("expect_map") or {}).items():
        assert got.get(src) == dst, (src, got.get(src))
    unmapped = {u["source"]: u["reason"] for u in r["unmapped"]}
    for src, reason in (case.get("expect_unmapped") or {}).items():
        assert unmapped.get(src) == reason, (src, unmapped.get(src))
    kinds = {w["kind"] for w in r["warnings"]}
    for k in case.get("expect_warnings") or []:
        assert k in kinds, f"缺少告警 {k}：{sorted(kinds)}"
    assert len(r["interface_map"]) >= int(case.get("min_mapped", 1))
    # 有新设备现有配置时，增量配置只含需要新增 / 修改的部分
    if case.get("target_config"):
        assert r["merge"] and r["delta"].strip() and len(r["delta"]) <= len(r["text"])
    # 割接步骤：每步都有文案键、设备与阶段；回退步骤在最后
    assert r["steps"] and all(s["key"].startswith("migrate.step.") for s in r["steps"])
    assert r["steps"][-1]["phase"] == "rollback"
    for item in r["warnings"]:
        assert item["key"].startswith(("migrate.", "translate.")) and isinstance(item["params"], dict)


def test_manifest_files_exist() -> None:
    used = set()
    for c in CASES:
        for k in ("src", "interface_map", "target_config"):
            if c.get(k):
                assert (BASE / c[k]).exists(), c[k]
                used.add(Path(str(c[k])).name)
    assert {p.name for p in BASE.glob("*.cfg")} <= used, "migration 目录下有没被使用的样本"
