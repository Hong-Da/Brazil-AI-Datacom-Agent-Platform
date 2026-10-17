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
from lmesh.core.sanitize import Level, Sanitizer, detect_vendor, detect_version, local_key
from lmesh.core.store.models import ConfigVersion, Device

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
    error: str = ""  # 文案键

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
    result = sanitizer.sanitize(text)
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
    sources: list[tuple[str, bytes]], db_url: str, level: Level = "basic", kb_root: Path | None = None
) -> list[ImportResult]:
    """一批文件共用一个脱敏器：同一原值在不同设备上替换成同一个值，跨设备的引用关系保持。"""
    sanitizer = Sanitizer(level, local_key())
    kb = None
    if kb_root is not None and (kb_root / "kb.yaml").exists():
        from lmesh.core import kb as kbmod

        kb = kbmod.load(kb_root)
    results: list[ImportResult] = []
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
                ver = ConfigVersion(device_id=dev.id, source_name=name, raw_text=text, sanitized=True)
                s.add(ver)
                s.flush()
                res.version_id = ver.id
            results.append(res)
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
                    "collected_at": latest.collected_at.isoformat() if latest else None,
                }
            )
        return out
