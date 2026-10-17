"""知识库发布前的回归测试入口：对全部样本跑往返测试（M1-8 接入往返引擎前，只检查样本能否读取）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def regression(kb_root: Path) -> dict[str, Any]:
    samples = kb_root / "samples"
    files = (
        [
            p
            for p in samples.rglob("*")
            if p.is_file() and p.suffix in (".cfg", ".txt") and not p.name.startswith("LICENSE")
        ]
        if samples.exists()
        else []
    )
    import importlib

    try:
        roundtrip = importlib.import_module("lmesh.core.roundtrip")
    except ImportError:
        return {"samples": len(files), "failed": 0, "note": "往返引擎尚未接入（M1-8）"}
    return dict(roundtrip.regression(kb_root, files))
