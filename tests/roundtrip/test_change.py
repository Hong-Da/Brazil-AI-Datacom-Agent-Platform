"""增量变更脚本回归（M4-3）：knowledge/samples/change/manifest.yaml。

每个用例的下发脚本与回滚脚本都要通过模拟执行验证（与目标按有效值一致、没有新的悬空引用、顺序正确、取消命令都能匹配），
再检查用例给出的动作个数、必须出现的命令与先后顺序、整体风险。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lmesh.core import analysis, change
from lmesh.core.kb import read_yaml

pytestmark = pytest.mark.roundtrip
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
BASE = KB_ROOT / "samples" / "change"
CASES: list[dict[str, Any]] = list((read_yaml(BASE / "manifest.yaml") or {}).get("cases") or [])


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


def _index(script: str, cmd: str) -> int:
    lines = [ln.strip() for ln in script.splitlines()]
    hits = [i for i, ln in enumerate(lines) if ln == cmd] or [
        i for i, ln in enumerate(lines) if ln.startswith(cmd + " ")
    ]
    assert hits, f"脚本中没有 {cmd!r}：\n{script}"
    return hits[0]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_change_case(kb: Any, case: dict[str, Any]) -> None:
    cur = (BASE / case["current"]).read_text(encoding="utf-8")
    tgt = (BASE / case["target"]).read_text(encoding="utf-8")
    r = change.change_text(cur, tgt, kb)
    assert r["ops"], "应当有变更"
    for name, part in (("script", r), ("rollback", r["rollback"])):
        v = part["verify"]
        assert v["ok"], (name, v)
        assert v["unknown"] == 0, (name, v)
        assert part["summary"]["fallbacks"] == 0, (name, [d["text"] for d in part["ops"] if d["fallback"]])
        assert part["unsupported"] == [], (name, part["unsupported"])
    exp = case.get("expect") or {}
    plain = r["script_plain"]
    for action, n in (exp.get("actions") or {}).items():
        assert r["summary"]["by_action"][action] >= n, r["summary"]
    last = -1
    for cmd in exp.get("contains") or []:
        i = _index(plain, cmd)
        assert i > last, f"{cmd!r} 的位置不对"
        last = i
    for a, b in exp.get("before") or []:
        assert _index(plain, a) < _index(plain, b), f"{a!r} 应排在 {b!r} 之前：\n{plain}"
    if exp.get("risk"):
        assert r["risk"]["level"] == exp["risk"]
    # 每条命令都有说明所需的字段；依赖原因指向排在前面的命令
    for d in r["ops"]:
        assert d["action"] in change.ACTIONS and d["risk"] in change.RISKS
        assert all(a["seq"] < d["seq"] for a in d["after"]), d


def test_manifest_files_exist() -> None:
    assert len(CASES) >= 12
    for c in CASES:
        assert (BASE / c["current"]).exists() and (BASE / c["target"]).exists(), c["id"]
