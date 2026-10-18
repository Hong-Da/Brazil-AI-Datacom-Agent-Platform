"""增量变更脚本的分块行（M4-8 界面用）：script_rows 与 script_plain 逐行对应，命令行带序号。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmesh.core import analysis, change

pytestmark = pytest.mark.unit
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
CHG = KB_ROOT / "samples" / "change"


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


def _read(name: str) -> str:
    return (CHG / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(("a", "b"), [("atn-base.cfg", "atn-add-vrf.cfg"), ("asr920-base.cfg", "asr920-add-vrf.cfg")])
def test_rows_match_plain_script(kb, a: str, b: str) -> None:  # type: ignore[no-untyped-def]
    r = change.change_text(_read(a), _read(b), kb)
    for part in (r, r["rollback"]):
        rows = part["script_rows"]
        plain = part["script_plain"].splitlines()
        assert [row["text"] for row in rows] == [ln.strip() for ln in plain]
        assert {row["kind"] for row in rows} <= {"frame", "enter", "cmd", "quit"}
        # 每条变更命令恰好一行，按序号出现；其余行没有序号
        seqs = [row["seq"] for row in rows if row["kind"] == "cmd"]
        assert seqs == [op["seq"] for op in part["ops"]]
        assert all(row["seq"] is None for row in rows if row["kind"] != "cmd")
        assert rows[0]["kind"] == "frame" and rows[-1]["kind"] == "frame"


def test_rows_depth_follows_views(kb) -> None:  # type: ignore[no-untyped-def]
    r = change.change_text(_read("atn-base.cfg"), _read("atn-add-vrf.cfg"), kb, rollback=False)
    rows = r["script_rows"]
    plain = r["script_plain"].splitlines()
    for row, ln in zip(rows, plain, strict=True):
        if row["kind"] != "frame":
            assert len(ln) - len(ln.lstrip()) == row["depth"]  # 华为缩进 1 格
