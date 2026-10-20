"""升级时合并程序自带的知识库（REQ-046）：无冲突采用新版本、双方都改的进审核、回滚、旧安装首次升级。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lmesh.core import review, store
from lmesh.core.kb import repo
from lmesh.core.kb import upgrade as up

pytestmark = pytest.mark.unit

V1 = {
    "kb.yaml": "kb_version: 1.0.0\n",
    "commands/a.yaml": "a: 1\n",
    "commands/b.yaml": "b: 1\n",
    "rules/c.yaml": "c: 1\n",
}


def _write(root: Path, files: dict[str, str]) -> None:
    if root.exists():
        shutil.rmtree(root)
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")


def _read(root: Path, rel: str) -> str | None:
    f = root / rel
    return f.read_text(encoding="utf-8") if f.exists() else None


def _install(tmp: Path) -> tuple[Path, Path]:
    """首次安装：自带知识库 v1 复制到运行时目录、建仓、建立 builtin 基准。"""
    builtin, rt = tmp / "builtin", tmp / "runtime"
    _write(builtin, V1)
    shutil.copytree(builtin, rt)
    repo.ensure_repo(rt)
    assert up.ensure_baseline(rt, builtin, "0.5.0")
    assert not up.ensure_baseline(rt, builtin, "0.5.0")  # 已有基准时不动
    return builtin, rt


def test_upgrade_without_conflicts(tmp_root: Path, db_url: str) -> None:
    builtin, rt = _install(tmp_root)
    # 用户改了 a（例如 kb map 在运行时仓库里提交），新版本改了 b、删了 c、新增 d
    (rt / "commands/a.yaml").write_text("a: user\n", encoding="utf-8")
    repo.commit_all(rt, "kb map")
    _write(builtin, {**V1, "commands/b.yaml": "b: 2\n", "commands/d.yaml": "d: 1\n"} | {})
    (builtin / "rules/c.yaml").unlink()

    dry = up.upgrade(rt, builtin, "0.8.0", db_url, dry_run=True)
    assert dry.updated == ["commands/b.yaml"] and dry.added == ["commands/d.yaml"] and dry.removed == ["rules/c.yaml"]
    assert _read(rt, "commands/b.yaml") == "b: 1\n"  # dry-run 不写入

    p = up.upgrade(rt, builtin, "0.8.0", db_url)
    assert p.has_base and p.changed and not p.conflicts and p.kept == ["commands/a.yaml"]
    assert _read(rt, "commands/a.yaml") == "a: user\n"
    assert _read(rt, "commands/b.yaml") == "b: 2\n" and _read(rt, "commands/d.yaml") == "d: 1\n"
    assert _read(rt, "rules/c.yaml") is None and not (rt / "rules").exists()
    assert p.release == "kb-v1.0.1" and not repo.dirty(rt)
    assert "LucidMesh 0.8.0" in up.builtin_tip(rt).message.decode()  # type: ignore[union-attr]
    # 同一版本再启动：没有变化
    assert not up.upgrade(rt, builtin, "0.8.0", db_url).changed


def test_conflicts_go_to_review(tmp_root: Path, db_url: str) -> None:
    store.upgrade(db_url)
    builtin, rt = _install(tmp_root)
    (rt / "commands/b.yaml").write_text("b: user\n", encoding="utf-8")
    (rt / "rules/c.yaml").write_text("c: user\n", encoding="utf-8")
    repo.commit_all(rt, "用户修改")
    _write(builtin, {**V1, "commands/b.yaml": "b: 2\n"})
    (builtin / "rules/c.yaml").unlink()

    p = up.upgrade(rt, builtin, "0.8.0", db_url)
    assert p.conflicts == ["commands/b.yaml", "rules/c.yaml"] and len(p.review_items) == 2
    assert _read(rt, "commands/b.yaml") == "b: user\n" and _read(rt, "rules/c.yaml") == "c: user\n"  # 不覆盖
    items = review.list_items(db_url, kind="conflict")["items"]
    assert {i["target"] for i in items} == {"commands/b.yaml", "rules/c.yaml"}
    assert all(i["source"]["via"] == "kb-upgrade" for i in items)
    # 维护员选用新版本：b 采用新内容，c 按新版本删除
    for rid in p.review_items:
        review.decide(db_url, rt, rid, approve=True)
    assert _read(rt, "commands/b.yaml") == "b: 2\n" and _read(rt, "rules/c.yaml") is None
    # 冲突处理完后，下一个版本只改 b：用户版本与基准一致，直接采用
    _write(builtin, {**V1, "commands/b.yaml": "b: 3\n"})
    (builtin / "rules/c.yaml").unlink()
    p2 = up.upgrade(rt, builtin, "0.9.0", db_url)
    assert p2.updated == ["commands/b.yaml"] and not p2.conflicts


def test_reject_keeps_user_version_and_requeue_updates(tmp_root: Path, db_url: str) -> None:
    store.upgrade(db_url)
    builtin, rt = _install(tmp_root)
    (rt / "commands/b.yaml").write_text("b: user\n", encoding="utf-8")
    _write(builtin, {**V1, "commands/b.yaml": "b: 2\n"})
    p = up.upgrade(rt, builtin, "0.8.0", db_url)
    # 下一个版本又改了 b，而上一条冲突还没处理：更新那一条，不重复建
    _write(builtin, {**V1, "commands/b.yaml": "b: 3\n"})
    p2 = up.upgrade(rt, builtin, "0.9.0", db_url)
    assert p2.review_items == p.review_items
    assert "b: 3" in review.get(db_url, p.review_items[0])["payload"]["theirs_preview"]  # type: ignore[index]
    review.decide(db_url, rt, p.review_items[0], approve=False)
    assert _read(rt, "commands/b.yaml") == "b: user\n"


def test_rollback_last_upgrade(tmp_root: Path, db_url: str) -> None:
    builtin, rt = _install(tmp_root)
    assert up.rollback_last(rt) is None
    _write(builtin, {**V1, "commands/b.yaml": "b: 2\n", "commands/d.yaml": "d: 1\n"})
    p = up.upgrade(rt, builtin, "0.8.0", db_url)
    assert up.last_upgrade(rt)["before"] == p.before  # type: ignore[index]
    res = up.rollback_last(rt)
    assert res and res["release"] == p.release
    assert _read(rt, "commands/b.yaml") == "b: 1\n" and _read(rt, "commands/d.yaml") is None
    # builtin 分支不回退：回滚后不会再自动合并回去
    assert not up.upgrade(rt, builtin, "0.8.0", db_url).changed


def test_old_install_first_upgrade_is_conservative(tmp_root: Path, db_url: str) -> None:
    store.upgrade(db_url)
    builtin, rt = tmp_root / "builtin", tmp_root / "runtime"
    # 旧安装：运行时知识库没有 builtin 分支；用户改了 b，自己加了 x
    _write(rt, {**V1, "commands/b.yaml": "b: user\n", "commands/x.yaml": "x: mine\n"})
    repo.ensure_repo(rt)
    _write(builtin, {**V1, "commands/a.yaml": "a: 2\n", "commands/d.yaml": "d: 1\n"})

    p = up.upgrade(rt, builtin, "0.8.0", db_url)
    assert not p.has_base
    # 与本次自带版本不同的文件全部当作冲突（包括新版本改了的 a 与新增的 d）；只在用户那里有的 x 保留
    assert p.conflicts == ["commands/a.yaml", "commands/b.yaml", "commands/d.yaml"]
    assert p.kept == ["commands/x.yaml"] and not (p.added or p.updated or p.removed)
    assert _read(rt, "commands/a.yaml") == "a: 1\n" and _read(rt, "commands/d.yaml") is None
    assert up.builtin_tip(rt) is not None  # 之后有了基准
    # 建立基准后，同一版本不再重复合并
    assert not up.upgrade(rt, builtin, "0.8.0", db_url).changed


def test_runtime_root_sets_baseline(tmp_root: Path) -> None:
    from lmesh.core import config, kbservice, setup

    setup.apply({"security.api_token": "t" * 32}, "zh-CN", check_port=False)
    settings = config.load()
    root = kbservice.runtime_root(settings)
    assert up.builtin_tip(root) is not None
    res = kbservice.upgrade_builtin(settings, dry_run=True)
    assert res["has_base"] and not res["changed"]
