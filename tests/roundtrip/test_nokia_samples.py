"""Nokia SR OS 合成样本（knowledge/samples/nokia-sros-classic-synthetic/，M7-4 起还有 nokia-sros-md-synthetic/）的补充门槛。

M7-2 时样本有自己的清单、用临时 Profile；M7-3 建好 Profile `nokia-sros-classic-7750-25.10` 后样本并入总清单
（往返与未识别行由 test_samples.py 检查，规范渲染等价由 test_translate.py 检查）。这里另外要求：
命令行都能按卡的语法（含引号）原样重放（没有靠原文兜底 fmt 的行），建图后没有悬空引用、关键对象都映射到了 Schema。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmesh.core import analysis, graph, roundtrip

pytestmark = pytest.mark.roundtrip
KB_ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"
DIRS = ("nokia-sros-classic-synthetic", "nokia-sros-md-synthetic")
SAMPLES = [s for s in roundtrip.manifest(KB_ROOT) if str(s["file"]).split("/")[0] in DIRS]
# 关键对象的入口命令：这些行必须映射到 Schema（不是 ext）
KEY_COMMANDS = ("port ", "lag ", "interface ", "static-route-entry", "next-hop", "ospf", "isis", "group ", "neighbor ",
                "policy-statement", "prefix-list ", "customer ", "sdp ", "epipe ", "vpls ", "vprn ", "ies ", "sap ",
                "spoke-sdp ", "mesh-sdp ", "ip-filter ", "entry ", "vrrp ")  # fmt: skip


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


@pytest.mark.parametrize("item", SAMPLES, ids=[s["file"] for s in SAMPLES])
def test_nokia_sample_replay_and_graph(item: dict, kb) -> None:  # type: ignore[no-untyped-def]
    text = (KB_ROOT / "samples" / item["file"]).read_text(encoding="utf-8")
    profile = str(item["profile"])
    r = roundtrip.run(text, kb, profile, Path(item["file"]).stem)
    assert r["ok"], r["diffs"][:3]
    assert r["unknown"] == 0, f"有未识别行：{r['unknown']}"
    parsed = analysis.parse_text(text, kb, profile).parsed
    assert [ln.no for ln in parsed.lines if ln.fmt is not None] == []  # 命令行都能按卡的语法（含引号）原样重放
    g = graph.build(parsed, kb, profile)
    assert g.graph["dangling"] == []
    ext_lines = {no for _, d in g.nodes(data=True) if d.get("kind") == "ext" for no in d.get("lines") or []}
    key_ext = [
        ln.text
        for ln in parsed.lines
        # RSVP-TE（rsvp、LSP、路径）在统一 Schema 中还没有对象，按未映射命令保留（M7-3 说明）
        if ln.no in ext_lines and ln.view != "opaque" and "rsvp" not in ln.view and ln.text.startswith(KEY_COMMANDS)
    ]
    assert key_ext == [], f"关键对象没有映射：{key_ext}"


def test_manifest_covers_nokia_samples() -> None:
    files = {f"{d}/{p.name}" for d in DIRS for p in (KB_ROOT / "samples" / d).glob("*.cfg")}
    assert files == {str(s["file"]) for s in SAMPLES}
