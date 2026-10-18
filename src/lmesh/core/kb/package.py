"""知识库包：整个 knowledge 目录打成 zip，便于备份、迁移、分享。

导入时先校验；新文件直接加入，内容相同的跳过，内容不同的作为冲突送进审核队列，不直接覆盖。
"""

from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from lmesh.core import kb as kbmod
from lmesh.core.kb.validate import validate

MANIFEST = "lmesh-kb-manifest.json"


def kb_version(root: Path) -> str:
    """只读 kb.yaml 的版本号（不加载整个知识库）。"""
    f = root / "kb.yaml"
    data = kbmod.read_yaml(f) if f.exists() else None
    return str((data or {}).get("kb_version", "0.0.0"))


def export(root: Path, target: Path | None = None) -> bytes:
    buf = io.BytesIO()
    files = [p for p in sorted(root.rglob("*")) if p.is_file() and ".git" not in p.relative_to(root).parts]
    manifest = {"kb_version": kb_version(root), "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "files": {}}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            rel = p.relative_to(root).as_posix()
            data = p.read_bytes()
            manifest["files"][rel] = hashlib.sha256(data).hexdigest()  # type: ignore[index]
            z.writestr(f"knowledge/{rel}", data)
        z.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
    data = buf.getvalue()
    if target:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return data


@dataclass
class ImportPlan:
    kb_version: str = ""
    added: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    issues: list[dict[str, str]] = field(default_factory=list)
    applied: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PackageError(ValueError):
    pass


def _members(data: bytes) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            if info.is_dir() or info.filename == MANIFEST:
                continue
            p = PurePosixPath(info.filename)
            parts = p.parts[1:] if p.parts and p.parts[0] == "knowledge" else p.parts
            if not parts or any(x in ("..", "") for x in parts) or p.is_absolute():
                raise PackageError(f"包内路径不安全：{info.filename}")
            out["/".join(parts)] = z.read(info)
    return out


def import_package(root: Path, data: bytes, dry_run: bool = False) -> tuple[ImportPlan, dict[str, bytes]]:
    """返回 (计划, 冲突文件的包内内容)。dry_run 时只计划不写入。校验有错误时不写入任何文件。"""
    members = _members(data)
    plan = ImportPlan()
    # 先在临时目录里加载包，单独校验
    import tempfile

    from lmesh import paths

    base = paths.root_path("tmp")
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as tmp:
        for rel, content in members.items():
            t = Path(tmp) / rel
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_bytes(content)
        pkg_kb = kbmod.load(Path(tmp))
        plan.kb_version = pkg_kb.version
        errors = [i for i in validate(pkg_kb) if i.level == "error"]
        plan.issues = [i.as_dict() for i in errors]
    conflicts: dict[str, bytes] = {}
    for rel, content in sorted(members.items()):
        target = root / rel
        if not target.exists():
            plan.added.append(rel)
        elif target.read_bytes() == content:
            plan.unchanged.append(rel)
        else:
            plan.conflicts.append(rel)
            conflicts[rel] = content
    if errors or dry_run:
        return plan, conflicts
    for rel in plan.added:
        t = root / rel
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_bytes(members[rel])
    plan.applied = True
    return plan, conflicts
