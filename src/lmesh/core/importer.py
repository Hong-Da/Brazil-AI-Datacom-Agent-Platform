"""配置导入：文件 / 目录 / zip → 识别厂商 → 脱敏 → 入库（解析与建图在后续阶段接入）。"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select

from lmesh.core import store
from lmesh.core.parser import normalize_pattern
from lmesh.core.sanitize import Level, SanitizeLeak, Sanitizer, detect_vendor, detect_version, local_key
from lmesh.core.store.models import ConfigVersion, Device, UnknownLine, iso

CONFIG_SUFFIXES = {"", ".txt", ".cfg", ".conf", ".config", ".log", ".zip"}
MAX_BYTES = 20 * 1024 * 1024
_HOST = re.compile(r"^\s*(?:sysname|hostname)\s+(\S+)", re.M)


@dataclass
class ImportResult:
    source: str
    ok: bool
    device: str = ""
    vendor: str = ""
    version: str = ""
    profile: str = ""
    lines: int = 0
    version_id: int | None = None
    sanitized: dict[str, int] = field(default_factory=dict)
    unknown: int = 0
    coverage: float | None = None
    error: str = ""  # 文案键
    duplicate: bool = False  # 内容与该设备最新的快照相同：没有存新快照，只记了一条导入记录（版本历史）

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def decode(raw: bytes) -> str:
    """配置文件编码不一：依次尝试 UTF-8（含 BOM）、GB18030、Latin-1。统一成 \\n 换行。"""
    for enc in ("utf-8-sig", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("latin-1")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def iter_sources(path: Path) -> Iterator[tuple[str, bytes]]:
    """展开为 (名称, 内容)：单个文件、目录（递归）或 zip 包。"""
    if path.is_dir():
        for p in sorted(path.rglob("*")):
            if p.is_file() and p.suffix.lower() in CONFIG_SUFFIXES and not p.name.startswith("."):
                yield from iter_sources(p)
        return
    data = path.read_bytes()
    yield from iter_bytes(path.name, data)


def iter_bytes(name: str, data: bytes) -> Iterator[tuple[str, bytes]]:
    if name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                if not info.is_dir() and info.file_size <= MAX_BYTES:
                    yield f"{name}/{info.filename}", z.read(info)
        return
    yield name, data


def guess_profile(vendor: str, version: str, kb: Any = None) -> str:
    """按厂商与版本选 Profile：优先用知识库中各 Profile 的匹配规则；没有知识库时按命名约定推断。"""
    if kb is not None:
        found = kb.match_profile(vendor, version)
        if found:
            return str(found)
    if vendor == "huawei":
        m = re.search(r"V(\d{3})R(\d{3})", version)
        if m:
            return f"huawei-atn-v{m.group(1)}r{m.group(2)}"
        return "huawei-atn-v800r025"
    if vendor == "cisco":
        return "cisco-iosxe-asr920-17.15"
    return ""


def sanitize_one(name: str, raw: bytes, sanitizer: Sanitizer, kb: Any = None) -> tuple[ImportResult, str]:
    if len(raw) > MAX_BYTES:
        return ImportResult(name, False, error="import.too_large"), ""
    text = decode(raw)
    vendor = detect_vendor(text)
    if not vendor:
        return ImportResult(name, False, error="import.unknown_vendor"), ""
    version = detect_version(text, vendor)
    try:
        result = sanitizer.sanitize(text)
    except SanitizeLeak:
        # 自检发现脱敏后仍残留秘密值：这个文件不入库（只报告，不写日志原文），批次里的其他文件照常导入
        return ImportResult(name, False, error="import.sanitize_leak"), ""
    m = _HOST.search(result.text)
    device = m.group(1) if m else Path(name).stem
    return ImportResult(
        name,
        True,
        device=device,
        vendor=vendor,
        version=version,
        profile=guess_profile(vendor, version, kb),
        lines=text.count("\n") + 1,
        sanitized=result.summary(),
    ), result.text


def import_sources(
    sources: list[tuple[str, bytes]],
    db_url: str,
    level: Level = "basic",
    kb_root: Path | None = None,
    source_kind: str = "file",
    actor: str = "",
    keep: int | None = None,
) -> list[ImportResult]:
    """一批文件共用一个脱敏器：同一原值在不同设备上替换成同一个值，跨设备的引用关系保持。

    版本历史（M5-2）：每个配置版本是一个快照（原文 + 当时的图 + 知识库版本 + 内容指纹）；内容与该设备最新快照相同的
    重复导入不存新快照，只记导入记录（source_kind：file / dir / zip / api，actor：导入人或令牌说明）。
    导入后按 keep（配置项 history.keep，None 时读取配置）清理旧快照，贴了标签的永久保留。"""
    from lmesh.core import history

    sanitizer = Sanitizer(level, local_key())
    kb = None
    if kb_root is not None and (kb_root / "kb.yaml").exists():
        from lmesh.core.analysis import load_kb

        kb = load_kb(kb_root)
    results: list[ImportResult] = []
    graphs: list[tuple[int, Any]] = []
    new_versions: list[int] = []
    with store.session(db_url) as s:
        for name, raw in sources:
            res, text = sanitize_one(name, raw, sanitizer, kb)
            if res.ok:
                dev = s.scalar(select(Device).where(Device.name == res.device))
                if dev is None:
                    dev = Device(name=res.device, vendor=res.vendor, sw_version=res.version, profile=res.profile)
                    s.add(dev)
                    s.flush()
                else:
                    dev.vendor, dev.sw_version, dev.profile = res.vendor, res.version, res.profile
                digest = history.content_hash(text)
                same = history.find_duplicate(s, dev.id, digest)
                if same is not None:
                    history.add_import(s, dev.id, same.id, name, source_kind, actor, duplicate=True)
                    res.version_id, res.duplicate = same.id, True
                    if same.structured:
                        res.unknown = sum(1 for ln in same.structured.get("lines", []) if ln.get("kind") == "unknown")
                        res.coverage = same.structured.get("coverage", res.coverage)
                    results.append(res)
                    continue
                ver = ConfigVersion(
                    device_id=dev.id,
                    source_name=name,
                    raw_text=text,
                    sanitized=True,
                    kb_version=kb.version if kb is not None else "",
                    content_hash=digest,
                )
                if kb is not None and res.profile in kb.profiles:
                    from lmesh.core import graph as graphmod
                    from lmesh.core import parser
                    from lmesh.core.renderer import render_roundtrip

                    parsed = parser.parse(text, kb, kb.profiles[res.profile].family)
                    g = graphmod.build(parsed, kb, res.profile, res.device)
                    st = parsed.as_dict()
                    st["roundtrip"] = render_roundtrip(g, kb) == text
                    st["graph"] = graphmod.summary(g)
                    ver.structured = st
                    ver.graph_gz = history.dump_graph(g)
                    res.unknown = len(parsed.unknown())
                    res.coverage = round(parsed.coverage(), 4)
                s.add(ver)
                s.flush()
                res.version_id = ver.id
                history.add_import(s, dev.id, ver.id, name, source_kind, actor, duplicate=False)
                new_versions.append(ver.id)
                if kb is not None and ver.structured and res.profile in kb.profiles:
                    graphs.append((ver.id, g))
                if kb is not None and ver.structured:
                    for ln in ver.structured["lines"]:
                        if ln["kind"] == "unknown":
                            s.add(
                                UnknownLine(
                                    version_id=ver.id,
                                    line_no=ln["no"],
                                    text=ln["text"],
                                    view=ln["view"],
                                    pattern=normalize_pattern(ln["text"])[:400],
                                )
                            )
            results.append(res)
    # 配置图写入 nodes / edges 表（会话提交后再写，避免长事务）
    from lmesh.core import graphstore

    for vid, g in graphs:
        graphstore.save(db_url, vid, g)
    if keep is None:
        from lmesh.core import config

        keep = int(config.load().get("history.keep"))
    history.after_import(db_url, new_versions, kb, keep)
    return results


def list_devices(db_url: str) -> list[dict[str, Any]]:
    with store.session(db_url) as s:
        out = []
        for d in s.scalars(select(Device).order_by(Device.name)):
            latest = max(d.versions, key=lambda v: v.id, default=None)
            out.append(
                {
                    "id": d.id,
                    "name": d.name,
                    "vendor": d.vendor,
                    "sw_version": d.sw_version,
                    "profile": d.profile,
                    "versions": len(d.versions),
                    "latest_version_id": latest.id if latest else None,
                    "collected_at": iso(latest.collected_at) if latest else None,
                }
            )
        return out
