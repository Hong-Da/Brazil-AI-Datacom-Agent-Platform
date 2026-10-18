"""配置翻译与规范渲染回归（M3-3）：knowledge/samples/translate/manifest.yaml。

- 同平台族规范渲染等价：规范渲染 → 再解析 → 建图 → 与原图对比无差异（含原文行），含默认值的完整配置同样无差异；
- 翻译：译文没有未识别行，与源图按有效值对比，除告警与 unsupported 列出的项之外没有差异。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lmesh.core import analysis, canon, compare, roundtrip, translate
from lmesh.core import graph as graphmod
from lmesh.core.kb import read_yaml

pytestmark = pytest.mark.roundtrip
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
BASE = KB_ROOT / "samples" / "translate"
MANIFEST = read_yaml(BASE / "manifest.yaml") or {}
CASES: list[dict[str, Any]] = list(MANIFEST.get("cases") or [])
CANONICAL = [
    (str(KB_ROOT / "samples" / s["file"]), s.get("profile")) for s in roundtrip.manifest(KB_ROOT) if s.get("gate", True)
] + [(str(BASE / s["file"]), s.get("profile")) for s in MANIFEST.get("canonical") or []]


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


def _graph(kb: Any, path: str, profile: str | None) -> Any:
    res = analysis.parse_text(Path(path).read_text(encoding="utf-8"), kb, profile)
    return graphmod.build(res.parsed, kb, res.profile, Path(path).stem), res.profile


@pytest.mark.parametrize("include_defaults", [False, True], ids=["canonical", "with-defaults"])
@pytest.mark.parametrize("path,profile", CANONICAL, ids=[Path(p).name for p, _ in CANONICAL])
def test_canonical_equivalent(kb: Any, path: str, profile: str | None, include_defaults: bool) -> None:
    g, pid = _graph(kb, path, profile)
    r = canon.render_full(g, kb, pid, include_defaults=include_defaults)
    if not include_defaults:
        assert r.uncovered == [], f"同平台族应能写出全部节点：{r.uncovered[:5]}"
    assert r.skipped_extras == [], f"原文行没有写回：{r.skipped_extras[:5]}"
    c = compare.compare(
        compare.Side(g, "a"), compare.side_from_text(r.text, kb, pid, "canonical"), kb, include_raw=True
    )
    assert c["equal"], [(d["kind"], d["node"]) for d in c["diffs"][:10]]
    assert len(c["unknown"]["b"]) <= len(c["unknown"]["a"]), c["unknown"]["b"][:5]


def _ifmap(case: dict[str, Any]) -> dict[str, str] | None:
    m = case.get("interface_map")
    if isinstance(m, dict):
        return {str(k): str(v) for k, v in m.items()}
    return compare.load_interface_map(BASE / str(m)) if m else None


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_translate_case(kb: Any, case: dict[str, Any]) -> None:
    text = (BASE / case["src"]).read_text(encoding="utf-8")
    r = translate.translate_text(text, kb, case["dst_profile"], case["src_profile"], _ifmap(case), device=case["id"])
    assert r["verify"]["checked"]
    diffs = [w["params"] for w in r["warnings"] if w["kind"] in ("verify_diff", "verify_unknown", "verify_failed")]
    assert r["verify"]["unexplained"] == 0, diffs[:10]
    parsed = analysis.parse_text(r["text"], kb, case["dst_profile"]).parsed
    assert parsed.counts().get("unknown", 0) == 0, [ln.text for ln in parsed.unknown()][:5]
    st = r["stats"]
    assert st["rendered"] / max(st["facts"], 1) >= float(case.get("min_rendered", 0.5)), st
    kinds = {w["kind"] for w in r["warnings"]}
    for k in case.get("expect_warnings") or []:
        assert k in kinds, f"缺少告警 {k}：{sorted(kinds)}"
    # 每条告警与 unsupported 都带文案键与参数（界面、CLI 按语言显示）
    for item in r["warnings"] + r["unsupported"] + r["defaults"]:
        assert item["key"].startswith("translate.") and isinstance(item["params"], dict)


def test_manifest_files_exist() -> None:
    for c in CASES:
        assert (BASE / c["src"]).exists(), c["src"]
        if isinstance(c.get("interface_map"), str):
            assert (BASE / c["interface_map"]).exists(), c["interface_map"]
    used = {Path(str(c["src"])).name for c in CASES} | {
        Path(str(s["file"])).name for s in MANIFEST.get("canonical") or []
    }
    assert {p.name for p in BASE.glob("*.cfg")} <= used, "translate 目录下有没被使用的样本"
