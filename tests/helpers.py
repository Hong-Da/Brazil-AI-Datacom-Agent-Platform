"""测试辅助：读取用例数据、按字段路径取值。"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

CASES = Path(__file__).resolve().parent / "cases"
_MISSING = object()


def load_cases(name: str) -> list[dict[str, Any]]:
    with (CASES / name).open("rb") as fh:
        return list(tomllib.load(fh)["case"])


def jget(obj: Any, path: str) -> Any:
    """按 a.b.c 取值；键本身含点（如 security.api_token）时取最长匹配。"""
    parts = path.split(".")
    cur = obj
    i = 0
    while i < len(parts):
        if isinstance(cur, list) and parts[i].isdigit():  # 列表下标：files.0.vendor
            idx = int(parts[i])
            if idx >= len(cur):
                return _MISSING
            cur, i = cur[idx], i + 1
            continue
        if not isinstance(cur, dict):
            return _MISSING
        for j in range(len(parts), i, -1):
            key = ".".join(parts[i:j])
            if key in cur:
                cur, i = cur[key], j
                break
        else:
            return _MISSING
    return cur


def check_json(data: Any, expect: dict[str, Any]) -> list[str]:
    problems = []
    for path, want in expect.items():
        got = jget(data, path)
        if got is _MISSING:
            problems.append(f"{path}: 缺少该字段")
        elif got != want:
            problems.append(f"{path}: 期望 {want!r}，实际 {got!r}")
    return problems
