"""文档测试：调用文档示例与 OpenAPI 最新、README 目录结构与实际一致、多语言键一致、相对链接有效。"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
pytestmark = pytest.mark.docs


def test_call_docs_up_to_date(tmp_path: Path) -> None:
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_docs.py"), "--check"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        env={**__import__("os").environ, "LMESH_ROOT": str(tmp_path)},
    )
    assert r.returncode == 0, r.stdout + r.stderr


def _tree_entries() -> list[tuple[str, str]]:
    """README「项目结构」代码块中的条目：(相对路径, 说明)。"""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    block = text.split("## 项目结构", 1)[1].split("```", 2)[1]
    entries: list[tuple[str, str]] = []
    stack: list[str] = []
    for line in block.splitlines()[2:]:
        m = re.match(r"^((?:│   |    )*)[├└]── (.+)$", line)
        if not m:
            continue
        depth = len(m.group(1)) // 4
        name, _, note = m.group(2).partition("  ")
        name = name.strip()
        stack = stack[:depth]
        if name.endswith("/") and " " not in name:
            stack.append(name.rstrip("/"))
            entries.append(("/".join(stack), note.strip()))
        else:
            for part in re.split(r"\s+/\s+", name):
                if re.fullmatch(r"[\w.\-/]+", part):
                    entries.append(("/".join([*stack, part]), note.strip()))
    return entries


# 说明中带这些标记的条目还没到创建的阶段，或不入库，不要求存在
_LATER = re.compile(r"不入库|阶段三|M\d-\d 起")


def test_readme_tree_matches() -> None:
    missing = [p for p, note in _tree_entries() if not _LATER.search(note) and not (ROOT / p).exists()]
    assert not missing, f"README 项目结构中列出但不存在：{missing}"


def test_top_level_dirs_listed() -> None:
    listed = {p.split("/")[0] for p, _ in _tree_entries()}
    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, encoding="utf-8", cwd=ROOT
    ).stdout.split()
    actual = {t.split("/")[0] for t in tracked if "/" in t}
    assert not (actual - listed), f"已入库但 README 项目结构中没有列出的目录：{actual - listed}"


def test_locales_consistent() -> None:
    for d in (ROOT / "src" / "lmesh" / "locales", ROOT / "frontend" / "src" / "i18n"):
        keys = {p.stem: set(json.loads(p.read_text(encoding="utf-8"))) for p in d.glob("*.json")}
        assert set(keys) == {"zh-CN", "en", "pt-BR"}, d
        assert keys["zh-CN"] == keys["en"] == keys["pt-BR"], d


def test_relative_links_exist() -> None:
    bad = []
    for md in [ROOT / "README.md", ROOT / "tests" / "README.md", *(ROOT / "docs").glob("*.md")]:
        for link in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", md.read_text(encoding="utf-8")):
            if "://" in link or link.startswith("mailto:"):
                continue
            if not (md.parent / link).exists():
                bad.append(f"{md.relative_to(ROOT)} → {link}")
    assert not bad, bad
