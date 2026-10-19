"""Nokia SR OS Classic 合成样本（knowledge/samples/nokia-sros-classic-synthetic/，有自己的清单）的解析与往返（M7-2）。

Profile 在 M7-3 建立；还没有时用一个只有匹配规则、没有条目的临时 Profile 建图（没有映射的命令卡按现有机制成为 ext 节点）。
门槛：逐字一致、未识别 0、没有靠原文兜底（fmt）的命令行。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmesh.core import analysis, roundtrip
from lmesh.core.kb import read_yaml
from lmesh.core.kb.model import Profile

pytestmark = pytest.mark.roundtrip
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
BASE = KB_ROOT / "samples" / "nokia-sros-classic-synthetic"
MANIFEST = read_yaml(BASE / "manifest.yaml") or {}
SAMPLES = list(MANIFEST.get("samples") or [])


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    kb = analysis.load_kb(KB_ROOT)
    pid, family = str(MANIFEST["profile"]), str(MANIFEST["family"])
    if pid not in kb.profiles:
        kb.profiles[pid] = Profile(id=pid, vendor="nokia", family=family, match={"vendor": "nokia"})
    return kb


@pytest.mark.parametrize("item", SAMPLES, ids=[s["file"] for s in SAMPLES])
def test_nokia_sample_roundtrip(item: dict, kb) -> None:  # type: ignore[no-untyped-def]
    text = (BASE / item["file"]).read_text(encoding="utf-8")
    r = roundtrip.run(text, kb, str(MANIFEST["profile"]), Path(item["file"]).stem)
    assert r["ok"], r["diffs"][:3]
    assert r["unknown"] == 0, f"有未识别行：{r['unknown']}"
    parsed = analysis.parse_text(text, kb, str(MANIFEST["profile"])).parsed
    assert [ln.no for ln in parsed.lines if ln.fmt is not None] == []  # 命令行都能按卡的语法（含引号）原样重放


def test_manifest_covers_nokia_samples() -> None:
    files = {p.name for p in BASE.glob("*.cfg")}
    assert files == {s["file"] for s in SAMPLES}
