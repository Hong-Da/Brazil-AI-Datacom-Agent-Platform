"""往返回归（0.1.0 验收门槛）：knowledge/samples/manifest.yaml 中的门槛样本必须逐字一致、且功能域内没有未识别行。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmesh.core import analysis, roundtrip

pytestmark = pytest.mark.roundtrip
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
SAMPLES = roundtrip.manifest(KB_ROOT)


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


@pytest.mark.parametrize("item", SAMPLES, ids=[s["file"] for s in SAMPLES])
def test_sample_roundtrip(item: dict, kb) -> None:  # type: ignore[no-untyped-def]
    path = KB_ROOT / "samples" / item["file"]
    r = roundtrip.run(path.read_text(encoding="utf-8"), kb, item.get("profile"), path.stem)
    assert r["ok"], r["diffs"][:3]
    if item.get("gate", True):
        assert r["unknown"] == 0, f"功能域内有未识别行：{r['unknown']}"
    # 悬空引用属于配置检查（M2）的发现，不是往返门槛；这里只要求能统计出来
    assert r["graph"]["dangling"] >= 0


def test_manifest_covers_all_samples() -> None:
    listed = {s["file"] for s in SAMPLES}
    files = {
        p.relative_to(KB_ROOT / "samples").as_posix()
        for p in (KB_ROOT / "samples").rglob("*")
        if p.is_file()
        and p.suffix in (".cfg", ".txt")
        and not p.name.startswith(("LICENSE", "README"))
        and p.relative_to(KB_ROOT / "samples").parts[0]
        not in (
            "compare",
            "translate",
            "topology",
            "migration",
            "change",
        )  # 对比、翻译、拓扑、迁移、变更基准有自己的清单
    }
    assert files == listed, f"样本清单与实际文件不一致：{files ^ listed}"
