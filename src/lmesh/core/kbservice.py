"""知识库操作（CLI 与 API 共用）：运行时知识库、校验、导入导出、发布、对比、回滚、覆盖矩阵。"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from lmesh.core import config, review, setup
from lmesh.core import kb as kbmod
from lmesh.core.kb import diff as kbdiff
from lmesh.core.kb import package, repo
from lmesh.core.kb.validate import summary, validate


def runtime_root(settings: config.Settings) -> Path:
    """运行时知识库：首次使用时从程序自带的 knowledge/ 复制，并初始化为独立的 Git 仓库。"""
    setup.ensure_runtime_knowledge(settings)
    root = settings.knowledge_dir
    root.mkdir(parents=True, exist_ok=True)
    repo.ensure_repo(root)
    return root


def load(root: Path) -> kbmod.KnowledgeBase:
    return kbmod.load(root)


def validate_report(root: Path) -> dict[str, Any]:
    kb = kbmod.load(root)
    issues = validate(kb)
    return {
        "kb_version": kb.version,
        **summary(issues),
        "issues": [i.as_dict() for i in issues],
        "counts": {
            "cards": len(kb.cards),
            "nodes": len(kb.nodes),
            "profiles": len(kb.profiles),
            "families": len(kb.families),
        },
    }


def import_package(root: Path, data: bytes, db_url: str, dry_run: bool = False) -> dict[str, Any]:
    plan, conflicts = package.import_package(root, data, dry_run=dry_run)
    out = plan.as_dict()
    out["review_items"] = []
    if plan.applied:
        for rel, content in conflicts.items():
            ours = (root / rel).read_bytes()
            rid = review.add(
                db_url,
                "conflict",
                f"导入冲突：{rel}",
                rel,
                {
                    "theirs_b64": base64.b64encode(content).decode(),
                    "theirs_sha256": hashlib.sha256(content).hexdigest(),
                    "ours_sha256": hashlib.sha256(ours).hexdigest(),
                    "theirs_preview": content[:4000].decode("utf-8", "replace"),
                },
                {"via": "kb-package", "kb_version": plan.kb_version},
            )
            out["review_items"].append(rid)
        if plan.added:
            repo.commit_all(root, f"导入知识库包（{len(plan.added)} 个新文件）")
    return out


def _set_kb_version(root: Path, version: str) -> None:
    y = YAML()  # 往返模式：保留注释与顺序
    y.preserve_quotes = True
    f = root / "kb.yaml"
    with f.open("r", encoding="utf-8") as fh:
        data = y.load(fh)
    data["kb_version"] = version
    with f.open("w", encoding="utf-8", newline="\n") as fh:
        y.dump(data, fh)


RegressionFn = Callable[[Path], dict[str, Any]]


class ReleaseError(ValueError):
    def __init__(self, key: str, data: Any = None):
        super().__init__(key)
        self.key, self.data = key, data


def release(root: Path, version: str | None, message: str, regression: RegressionFn | None = None) -> dict[str, Any]:
    """发布：校验无错误 → 回归测试通过 → 写入版本号 → 提交 → 打标签。版本号不填时按差异自动建议。"""
    repo.commit_all(root, "发布前保存工作区")
    report = validate_report(root)
    if report["errors"]:
        raise ReleaseError("kb.release_invalid", report["issues"])
    reg = regression(root) if regression else {"skipped": True}
    if reg.get("failed"):
        raise ReleaseError("kb.release_regression", reg)
    current = kbmod.load(root)
    last = repo.releases(root)
    if last:
        with repo.checkout_to_temp(root, last[0].tag) as snap:
            d = kbdiff.compare(kbmod.load(snap), current)
        base = last[0].version
    else:
        d = kbdiff.compare(kbmod.KnowledgeBase(root=root), current)
        base = current.version
    if last and d.empty():
        raise ReleaseError("kb.release_nothing")
    version = version or kbdiff.next_version(base, d.bump())
    if any(r.version == version for r in last):
        raise ReleaseError("kb.release_exists", version)
    _set_kb_version(root, version)
    repo.commit_all(root, f"知识库 {version}：{message}")
    tag = repo.tag(root, version, message or f"知识库 {version}")
    return {"version": version, "tag": tag, "diff": d.as_dict(), "regression": reg}


def releases(root: Path) -> list[dict[str, Any]]:
    return [r.__dict__ for r in repo.releases(root)]


def diff(root: Path, ref_from: str, ref_to: str | None = None) -> dict[str, Any]:
    with repo.checkout_to_temp(root, ref_from) as a:
        old = kbmod.load(a)
        if ref_to:
            with repo.checkout_to_temp(root, ref_to) as b:
                new = kbmod.load(b)
        else:
            new = kbmod.load(root)
    return kbdiff.compare(old, new).as_dict()


def coverage(root: Path, profile: str | None = None) -> dict[str, Any]:
    """覆盖矩阵：每个 Schema 节点在各 Profile（继承展开后）中是支持、不支持还是未填写。"""
    kb = kbmod.load(root)
    profiles = [profile] if profile else sorted(kb.profiles)
    matrix: dict[str, dict[str, str]] = {}
    totals: dict[str, dict[str, int]] = {}
    for pid in profiles:
        if pid not in kb.profiles:
            raise KeyError(pid)
        resolved = kb.resolve_profile(pid)
        t = {"supported": 0, "unsupported": 0, "unfilled": 0}
        for nid in sorted(kb.nodes):
            e = resolved.entries.get(nid)
            state = "unfilled" if e is None else ("supported" if e.supported else "unsupported")
            matrix.setdefault(nid, {})[pid] = state
            t[state] += 1
        totals[pid] = t
    return {"profiles": profiles, "totals": totals, "matrix": matrix}
