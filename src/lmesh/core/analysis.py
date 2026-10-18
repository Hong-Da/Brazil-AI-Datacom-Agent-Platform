"""解析、建图、往返的服务层（CLI、API、导入共用）：知识库缓存、自动选择 Profile、未识别行汇总、应用映射。"""

from __future__ import annotations

import re
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from lmesh.core import kb as kbmod
from lmesh.core import parser, store
from lmesh.core.kb import KnowledgeBase, mapping, profilegen, repo
from lmesh.core.sanitize import detect_vendor, detect_version
from lmesh.core.store.models import UnknownLine

_cache: dict[str, tuple[tuple[float, int], KnowledgeBase]] = {}
_lock = threading.Lock()


class AnalysisError(ValueError):
    pass


def _signature(root: Path) -> tuple[float, int]:
    """缓存键：最新的修改时间 + 文件数（删除文件时修改时间不一定变大）。"""
    latest, count = 0.0, 0
    for sub in ("kb.yaml", "commands", "schema", "profiles"):
        p = root / sub
        if p.is_file():
            latest, count = max(latest, p.stat().st_mtime), count + 1
        elif p.is_dir():
            for f in p.rglob("*.yaml"):
                latest, count = max(latest, f.stat().st_mtime), count + 1
    return latest, count


_errors_cache: dict[str, tuple[tuple[float, int], set[tuple[str, str]]]] = {}


def prime(root: Path, kb: KnowledgeBase, errors: set[tuple[str, str]] | None = None) -> None:
    """刚写入并加载过的知识库直接放进缓存（界面编辑之后的下一个请求不用再加载一次）。"""
    key = str(root.resolve())
    sig = _signature(root)
    with _lock:
        _cache[key] = (sig, kb)
        if errors is not None:
            _errors_cache[key] = (sig, errors)


def validation_errors(root: Path) -> set[tuple[str, str]]:
    """当前知识库的校验错误（code, message），按与 load_kb 相同的键缓存。"""
    from lmesh.core.kb.validate import validate

    key = str(root.resolve())
    kb = load_kb(root)
    sig = _signature(root)
    with _lock:
        hit = _errors_cache.get(key)
        if hit and hit[0] == sig:
            return hit[1]
    errors = {(i.code, i.message) for i in validate(kb) if i.level == "error"}
    with _lock:
        _errors_cache[key] = (sig, errors)
    return errors


def load_kb(root: Path) -> KnowledgeBase:
    """知识库加载较慢（几千张命令卡）：按文件修改时间缓存，文件变了才重新加载。"""
    key = str(root.resolve())
    sig = _signature(root)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == sig:
            return hit[1]
        kb = kbmod.load(root)
        _cache[key] = (sig, kb)
        return kb


@dataclass
class ParseResult:
    profile: str
    family: str
    vendor: str
    version: str
    parsed: parser.Parsed

    def as_dict(self) -> dict[str, Any]:
        d = self.parsed.as_dict()
        d.update(profile=self.profile, vendor=self.vendor, version=self.version)
        return d


def resolve_profile(text: str, kb: KnowledgeBase, profile: str | None = None) -> tuple[str, str, str]:
    """返回 (Profile, 厂商, 版本)。"""
    vendor = detect_vendor(text) or ""
    version = detect_version(text, vendor)
    if profile:
        if profile not in kb.profiles:
            raise AnalysisError("parse.profile_unknown")
        return profile, kb.profiles[profile].vendor or vendor, version
    found = kb.match_profile(vendor, version) if vendor else None
    if not found:
        raise AnalysisError("parse.no_profile")
    return found, vendor, version


def parse_text(text: str, kb: KnowledgeBase, profile: str | None = None) -> ParseResult:
    text = text.replace("\r\n", "\n")
    pid, vendor, version = resolve_profile(text, kb, profile)
    family = kb.profiles[pid].family
    return ParseResult(pid, family, vendor, version, parser.parse(text, kb, family))


def unknown_summary(db_url: str, limit: int = 50) -> list[dict[str, Any]]:
    with store.session(db_url) as s:
        rows = s.execute(select(UnknownLine.view, UnknownLine.pattern, UnknownLine.text))
        counter: Counter[tuple[str, str]] = Counter()
        example: dict[tuple[str, str], str] = {}
        for view, pattern, text in rows:
            counter[(view, pattern)] += 1
            example.setdefault((view, pattern), text)
    return [
        {"view": v, "pattern": p, "count": n, "example": example[(v, p)]} for (v, p), n in counter.most_common(limit)
    ]


def store_unknown(db_url: str, version_id: int, parsed: parser.Parsed) -> int:
    with store.session(db_url) as s:
        n = 0
        for ln in parsed.unknown():
            s.add(
                UnknownLine(
                    version_id=version_id,
                    line_no=ln.no,
                    text=ln.text,
                    view=ln.view,
                    pattern=parser.normalize_pattern(ln.text)[:400],
                )
            )
            n += 1
        return n


def apply_mappings(root: Path) -> dict[str, Any]:
    """映射规则写进命令卡 → 重新汇总 Profile → 提交运行时知识库。"""
    fams = sorted(p.stem for p in (root / "mappings").glob("*.yaml")) if (root / "mappings").exists() else []
    out: dict[str, Any] = {"families": {}, "profiles": {}}
    for fam in fams:
        out["families"][fam] = mapping.apply_rules(root, fam)
    out["profiles"] = profilegen.generate(root)
    if (root / ".git").exists():
        out["commit"] = repo.commit_all(root, "应用映射规则并重新汇总 Profile")
    return out


def strip_trailing_blank(text: str) -> str:
    return re.sub(r"\n+\Z", "\n", text)
