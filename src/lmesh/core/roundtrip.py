"""往返测试：配置 → 结构化 → 图 → 配置，逐字比较；0.1.0 的验收门槛与知识库发布前的回归测试都用它。"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from lmesh.core import analysis
from lmesh.core import graph as graphmod
from lmesh.core.importer import decode
from lmesh.core.kb import KnowledgeBase, read_yaml
from lmesh.core.renderer import render_roundtrip


def run(
    text: str, kb: KnowledgeBase, profile: str | None = None, device: str = "device", diff_limit: int = 20
) -> dict[str, Any]:
    text = text.replace("\r\n", "\n")
    res = analysis.parse_text(text, kb, profile)
    g = graphmod.build(res.parsed, kb, res.profile, device)
    out = render_roundtrip(g, kb)
    ok = out == text
    diffs: list[dict[str, Any]] = []
    if not ok:
        a, b = text.split("\n"), out.split("\n")
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
            if tag == "equal":
                continue
            diffs.append({"line": i1 + 1, "original": a[i1:i2], "rendered": b[j1:j2]})
            if len(diffs) >= diff_limit:
                break
    counts = res.parsed.counts()
    return {
        "ok": ok,
        "profile": res.profile,
        "lines": len(text.split("\n")),
        "counts": counts,
        "unknown": counts.get("unknown", 0),
        "coverage": round(res.parsed.coverage(), 4),
        "graph": graphmod.summary(g),
        "diffs": diffs,
    }


def manifest(kb_root: Path) -> list[dict[str, Any]]:
    f = kb_root / "samples" / "manifest.yaml"
    if f.exists():
        return list((read_yaml(f) or {}).get("samples") or [])
    # 没有清单时：样本目录下的全部文件都参与
    return [
        {"file": p.relative_to(kb_root / "samples").as_posix(), "gate": True}
        for p in sorted((kb_root / "samples").rglob("*"))
        if p.is_file()
        and p.suffix in (".cfg", ".txt")
        and not p.name.startswith(("LICENSE", "README"))
        and p.relative_to(kb_root / "samples").parts[0] != "compare"  # 对比基准的变体有自己的清单
    ]


def regression(kb_root: Path, files: list[Path] | None = None, kb: KnowledgeBase | None = None) -> dict[str, Any]:
    """全部样本跑往返：门槛样本必须逐字一致、且功能域内没有未识别行。"""
    kb = kb or analysis.load_kb(kb_root)
    results = []
    failed = 0
    for item in manifest(kb_root):
        path = kb_root / "samples" / str(item["file"])
        if not path.exists():
            results.append(
                {"file": item["file"], "ok": False, "error": "missing", "gate": bool(item.get("gate", True))}
            )
            failed += 1
            continue
        r = run(decode(path.read_bytes()), kb, item.get("profile"), path.stem, diff_limit=5)
        gate = bool(item.get("gate", True))
        passed = r["ok"] and (r["unknown"] == 0 or not gate)
        results.append(
            {
                "file": item["file"],
                "gate": gate,
                "passed": passed,
                **{k: r[k] for k in ("ok", "profile", "lines", "unknown", "coverage", "graph", "diffs")},
            }
        )
        if gate and not passed:
            failed += 1
    return {"samples": len(results), "failed": failed, "results": results, "kb_version": kb.version}
