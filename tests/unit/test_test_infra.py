"""单元测试：测试基础设施——增量测试的选择规则（scripts/run_tests.py --changed）、并行进程数、共用知识库的改动检查。"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from tests.conftest import ROOT, SharedKnowledge

pytestmark = pytest.mark.unit


def _load_run_tests():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("run_tests", ROOT / "scripts" / "run_tests.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rt = _load_run_tests()


@pytest.mark.parametrize(
    ("path", "cats"),
    [
        ("frontend/src/pages/Home.vue", ["frontend"]),
        ("frontend/src/i18n/en.json", ["docs", "frontend"]),
        ("src/lmesh/api/routes_configs.py", ["api", "cli", "docs"]),
        ("src/lmesh/cli/cmd_parse.py", ["cli", "docs"]),
        ("src/lmesh/core/parser.py", ["roundtrip", "unit"]),
        ("src/lmesh/core/translate.py", ["roundtrip", "unit"]),
        ("src/lmesh/core/change.py", ["roundtrip", "unit"]),
        ("src/lmesh/core/kb/load.py", ["api", "cli", "roundtrip", "unit"]),
        ("src/lmesh/core/graphstore.py", ["api", "cli", "roundtrip", "unit"]),
        ("src/lmesh/core/users.py", ["api", "cli", "unit"]),
        ("src/lmesh/core/report_change.py", ["api", "cli", "unit"]),
        ("knowledge/commands/huawei-vrp/bgp.yaml", ["roundtrip", "unit"]),
        ("docs/cli.md", ["docs"]),
        ("README.md", ["docs"]),
        ("tests/cases/cli_cases.toml", ["api", "cli", "docs"]),
        ("tests/roundtrip/test_samples.py", ["roundtrip"]),
        ("tests/api/test_users_api.py", ["api"]),
        # 未登记的路径跑全部
        ("tests/conftest.py", sorted(rt.ALL)),
        ("pyproject.toml", sorted(rt.ALL)),
        ("src/lmesh/paths.py", sorted(rt.ALL)),
    ],
)
def test_changed_rules(path: str, cats: list[str]) -> None:
    picked, detail = rt.pick_changed([path], False)
    assert sorted(picked) == cats
    assert detail == [(path, detail[0][1])] and sorted(detail[0][1]) == cats


def test_changed_added_file_adds_docs() -> None:
    picked, _ = rt.pick_changed(["src/lmesh/core/parser.py"], True)
    assert picked == ["unit", "docs", "roundtrip"]


def test_worker_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "cpu_count", lambda: 32)
    monkeypatch.delenv("LMESH_TEST_MAX_WORKERS", raising=False)
    assert rt.worker_count(None, None) == rt.DEFAULT_MAX_WORKERS
    assert rt.worker_count("auto", 8) == 8
    assert rt.worker_count("0", None) == 0
    assert rt.worker_count("3", None) == 3
    monkeypatch.setenv("LMESH_TEST_MAX_WORKERS", "64")
    assert rt.worker_count(None, None) == 32
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    assert rt.worker_count(None, None) == 4


def test_shared_knowledge_detects_and_restores(tmp_path: Path) -> None:
    shared = SharedKnowledge(tmp_path)
    lite = shared.path("lite")
    assert (lite / "kb.yaml").exists() and shared.check("lite") == []
    original = (lite / "kb.yaml").read_bytes()
    (lite / "kb.yaml").write_bytes(original + b"\n# changed\n")
    (lite / "extra.txt").write_text("x", encoding="utf-8")
    assert shared.check("lite") == ["extra.txt", "kb.yaml"]
    assert (lite / "kb.yaml").read_bytes() == original and not (lite / "extra.txt").exists()
    assert shared.check("lite") == []


def test_tmp_root_links_shared_knowledge(tmp_root: Path) -> None:
    """默认的 tmp_root/knowledge 是共用副本的链接；kb_write 用例是自己的副本（见下一条）。"""
    kb = tmp_root / "knowledge"
    assert (kb / "kb.yaml").exists()
    if os.environ.get("LMESH_TEST_KB_COPY") != "1":
        assert kb.resolve().name == "lite" and kb.resolve() != tmp_root.resolve() / "knowledge"


@pytest.mark.kb_write
def test_kb_write_gets_own_copy(tmp_root: Path) -> None:
    kb = tmp_root / "knowledge"
    assert kb.resolve() == tmp_root.resolve() / "knowledge"
    (kb / "extra.txt").write_text("x", encoding="utf-8")  # 写自己的副本，不会报错
