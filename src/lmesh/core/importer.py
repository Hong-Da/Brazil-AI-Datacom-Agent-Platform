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
from lmesh.core.sanitize import (
    Level,
    SanitizeLeak,
    Sanitizer,
    detect_format,
    detect_vendor,
    detect_version,
    family_of,
    local_key,
)
from lmesh.core.store.models import ConfigVersion, Device, UnknownLine, iso

CONFIG_SUFFIXES = {"", ".txt", ".cfg", ".conf", ".config", ".log", ".zip"}
MAX_BYTES = 20 * 1024 * 1024
_HOST = re.compile(r"^\s*(?:sysname|hostname)\s+(\S+)", re.M)
_NOKIA_HOST = re.compile(r'^ {8}name\s+"?([^"\s]+)"?\s*$', re.M)  # configure > system > name "PE1"
# 认不出厂商时（REQ-044）再试几种常见写法：host-name X; / set system host-name X / hostname X
_GENERIC_HOST = re.compile(r'^\s*(?:set system )?host-?name\s+"?([^\s;"]+)"?;?\s*$', re.M)


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
    error_lines: list[int] = field(default_factory=list)  # 脱敏自检残留秘密值的行号（只有行号）
    duplicate: bool = False  # 内容与该设备最新的快照相同：没有存新快照，只记了一条导入记录（版本历史）
    # REQ-044：Profile 来源（auto / fallback / rule / manual / none）、匹配程度（exact / approx / none）、
    # 按哪条型号规则选的、这次“记住”新建的规则、是否只存原文（认不出厂商或没有可用的 Profile）
    profile_source: str = ""
    match_level: str = ""
    rule_id: int | None = None
    rule_created: int | None = None
    raw_only: bool = False
    # M9：设备编号与这次导入新加入的网络（默认网络、在网络里导入时的当前网络、自动加入规则命中的网络）
    device_id: int | None = None
    joined_networks: list[dict[str, Any]] = field(default_factory=list)

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


def error_message(t: Any, key: str, lines: list[int] | None = None) -> str:
    """导入失败的提示：t 是翻译函数；脱敏自检失败时附上残留所在的行号（不含值）。"""
    msg = str(t(key))
    if lines:
        msg += str(t("import.leak_lines", lines=", ".join(str(n) for n in lines[:10])))
    return msg


def guess_profile(vendor: str, version: str, kb: Any = None, fmt: str = "") -> str:
    """按厂商与版本选 Profile：优先用知识库中各 Profile 的匹配规则；没有知识库时按命名约定推断。"""
    if kb is not None:
        found = kb.match_profile(vendor, version, family_of(vendor, fmt))
        if found:
            return str(found)
    if vendor == "huawei":
        m = re.search(r"V(\d{3})R(\d{3})", version)
        if m:
            return f"huawei-atn-v{m.group(1)}r{m.group(2)}"
        return "huawei-atn-v800r025"
    if vendor == "cisco":
        return "cisco-iosxe-asr920-17.15"
    if vendor == "nokia":
        # Profile 本身在 M7-3 建立；还没有时导入照常进行（只存原文，不解析、不建图）
        return "nokia-sros-md-7750-25.10" if fmt == "md" else "nokia-sros-classic-7750-25.10"
    return ""


def sanitize_one(
    name: str, raw: bytes, sanitizer: Sanitizer, kb: Any = None, allow_unknown: bool = False
) -> tuple[ImportResult, str]:
    """脱敏一个文件。认不出厂商时默认拒绝（import.unknown_vendor）；allow_unknown=True 时按通用规则脱敏，
    厂商与 Profile 留空（REQ-044：只存原文或由调用方手工指定 Profile）。"""
    if len(raw) > MAX_BYTES:
        return ImportResult(name, False, error="import.too_large"), ""
    text = decode(raw)
    vendor = detect_vendor(text)
    if not vendor and not allow_unknown:
        return ImportResult(name, False, error="import.unknown_vendor"), ""
    vendor = vendor or ""
    version = detect_version(text, vendor) if vendor else ""
    fmt = detect_format(text, vendor) if vendor else ""
    try:
        result = sanitizer.sanitize(text)
    except SanitizeLeak as e:
        # 自检发现脱敏后仍残留秘密值：这个文件不入库（只报告行号，不写日志原文），批次里的其他文件照常导入
        return ImportResult(name, False, error="import.sanitize_leak", error_lines=list(e.lines)[:20]), ""
    m = (_NOKIA_HOST if vendor == "nokia" else _HOST if vendor else _GENERIC_HOST).search(result.text)
    device = m.group(1) if m else Path(name).stem
    return ImportResult(
        name,
        True,
        device=device,
        vendor=vendor,
        version=version,
        profile=guess_profile(vendor, version, kb, fmt) if vendor else "",
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
    public: bool = False,
    choices: dict[str, dict[str, Any]] | None = None,
    profile: str | None = None,
    keep_unsupported: bool = False,
    can_global: bool = True,
) -> list[ImportResult]:
    """一批文件共用一个脱敏器：同一原值在不同设备上替换成同一个值，跨设备的引用关系保持。

    项目（M6）：设备导入到当前项目（没有当前项目时为默认项目），同名设备在项目内作为新版本；public=True 时导入到
    公共设备库（管理员）。项目里引用的公共设备与新导入的设备同名时拒绝（import.name_is_public_ref）。

    版本历史（M5-2）：每个配置版本是一个快照（原文 + 当时的图 + 知识库版本 + 内容指纹）；内容与该设备最新快照相同的
    重复导入不存新快照，只记导入记录（source_kind：file / dir / zip / api，actor：导入人或令牌说明）。
    导入后按 keep（配置项 history.keep，None 时读取配置）清理旧快照，贴了标签的永久保留。

    Profile（REQ-044）：profile 对所有文件生效、choices 按文件名（来源名）指定 {profile, raw_only, remember}；
    其余按 model_support.choose 的顺序（设备之前的手工选择、型号规则、版本规则、fallback）。认不出厂商的文件默认拒绝，
    keep_unsupported=True 或该文件 raw_only 时只存原文（标为不支持的厂商）。remember={scope, name_pattern, version,
    feature, note} 时新建型号规则（同一批相同的规则只建一次）；scope=global 需要 can_global（维护员与管理员）。"""
    from lmesh.core import history, model_support, projects

    sc = None if public else projects.current()
    # 项目的脱敏补充（M8-5 脱敏复核采纳的规则）：导入到这个项目时一并替换
    sanitizer = Sanitizer(level, local_key(), redact=list(sc.redact) if sc else None)
    kb = None
    if kb_root is not None and (kb_root / "kb.yaml").exists():
        from lmesh.core.analysis import load_kb

        kb = load_kb(kb_root)

    results: list[ImportResult] = []
    graphs: list[tuple[int, Any]] = []
    new_versions: list[int] = []
    project_id = None if public else projects.target_project_id(db_url)
    choices = choices or {}
    remembered: dict[tuple[Any, ...], int] = {}
    reanalyse: list[int] = []
    with store.session(db_url) as s:
        for name, raw in sources:
            opt = choices.get(name) or choices.get(Path(name).name) or {}
            override = str(opt.get("profile") or profile or "") or None
            res, text = sanitize_one(name, raw, sanitizer, kb, allow_unknown=True)
            if res.ok and not res.vendor and not override and not (keep_unsupported or opt.get("raw_only")):
                res.ok, res.error = False, "import.unknown_vendor"
            if res.ok:
                owner = Device.project_id.is_(None) if project_id is None else Device.project_id == project_id
                dev = s.scalar(select(Device).where(owner, Device.name == res.device))
                if dev is None and project_id is not None and _ref_named(s, project_id, res.device):
                    res.ok, res.error = False, "import.name_is_public_ref"
                    results.append(res)
                    continue
                det = model_support.detect(text)
                prev = (dev.profile, dev.profile_source or "auto") if dev is not None else None
                try:
                    if opt.get("raw_only") and not override:
                        ch = model_support.Choice("", "none", None, det.vendor, det.version, det.family)
                    else:
                        rid = None
                        if override and kb is not None and opt.get("remember"):
                            rid, created = _remember(
                                s,
                                kb,
                                det,
                                override,
                                opt["remember"],
                                project_id,
                                actor,
                                can_global,
                                remembered,
                                res.device,
                            )
                            res.rule_created = rid if created else None
                        rules = model_support.ordered_rules(s, project_id)
                        ch = model_support.choose(kb, text, res.device, rules, override, prev, det)
                        hit = model_support.match_rule(kb, rules, res.device, det, text) if rid and kb else None
                        if hit is not None and hit.id == rid:
                            # 记住的规则命中了这台设备：来源记为规则，规则改指向时跟着变
                            ch = model_support.Choice(override or "", "rule", hit.id, ch.vendor, ch.version, ch.family)
                except model_support.ModelError as e:
                    res.ok, res.error = False, e.key
                    results.append(res)
                    continue
                res.profile, res.profile_source, res.match_level, res.rule_id = (
                    ch.profile,
                    ch.source,
                    ch.level,
                    ch.rule_id,
                )
                res.vendor = ch.vendor
                res.raw_only = not ch.profile or kb is None or ch.profile not in kb.profiles
                if dev is None:
                    dev = Device(
                        name=res.device,
                        vendor=res.vendor,
                        sw_version=res.version,
                        profile=res.profile,
                        project_id=project_id,
                    )
                    s.add(dev)
                    s.flush()
                res.device_id = dev.id
                changed = dev.profile != ch.profile
                dev.vendor, dev.sw_version = res.vendor, res.version
                model_support.apply_choice(dev, ch)
                digest = history.content_hash(text)
                same = history.find_duplicate(s, dev.id, digest)
                if same is not None:
                    history.add_import(s, dev.id, same.id, name, source_kind, actor, duplicate=True)
                    res.version_id, res.duplicate = same.id, True
                    if changed:
                        reanalyse.append(same.id)  # 内容相同但这次换了 Profile：按新 Profile 重新解析
                    elif same.structured:
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
    if reanalyse and kb_root is not None:
        from lmesh.core import workbench

        by_vid = {r.version_id: r for r in results if r.duplicate}
        for vid in reanalyse:
            out = workbench.analyse_version(db_url, vid, kb_root, kb=kb)
            r = by_vid.get(vid)
            if r is not None and out.get("parsed"):
                r.unknown, r.coverage = int(out.get("unknown") or 0), out.get("coverage")
    if keep is None:
        from lmesh.core import config

        keep = int(config.load().get("history.keep"))
    history.after_import(db_url, new_versions, kb, keep)
    if project_id is not None:
        from lmesh.core import networks

        ids = list(dict.fromkeys(r.device_id for r in results if r.ok and r.device_id is not None))
        joined = networks.auto_join(db_url, project_id, ids, sc, actor, kb)
        for r in results:
            if r.ok and r.device_id is not None:
                r.joined_networks = joined.get(r.device_id, [])
    return results


def inspect_sources(
    sources: list[tuple[str, bytes]],
    db_url: str,
    level: Level = "basic",
    kb_root: Path | None = None,
    public: bool = False,
) -> list[dict[str, Any]]:
    """导入前的识别（REQ-044，不入库）：每个文件的识别结果、匹配程度、按选择顺序会用的 Profile、候选 Profile 的试解析
    结果（同厂商 / 同平台族；认不出厂商时为全部 Profile）、设备之前的选择、“记住”时预填的规则。"""
    from lmesh.core import model_support, projects

    sc = None if public else projects.current()
    sanitizer = Sanitizer(level, local_key(), redact=list(sc.redact) if sc else None)
    kb = None
    if kb_root is not None and (kb_root / "kb.yaml").exists():
        from lmesh.core.analysis import load_kb

        kb = load_kb(kb_root)
    project_id = None if public else projects.target_project_id(db_url)
    out: list[dict[str, Any]] = []
    with store.session(db_url) as s:
        rules = model_support.ordered_rules(s, project_id)
        for name, raw in sources:
            res, text = sanitize_one(name, raw, sanitizer, kb, allow_unknown=True)
            row: dict[str, Any] = {"source": name, "ok": res.ok, "error": res.error, "error_lines": res.error_lines}
            if not res.ok:
                out.append(row)
                continue
            owner = Device.project_id.is_(None) if project_id is None else Device.project_id == project_id
            dev = s.scalar(select(Device).where(owner, Device.name == res.device))
            prev = (dev.profile, dev.profile_source or "auto") if dev is not None else None
            det = model_support.detect(text)
            ch = model_support.choose(kb, text, res.device, rules, None, prev, det)
            rule = next((r for r in rules if r.id == ch.rule_id), None)
            cands = model_support.trial(kb, text, det) if kb is not None else []
            row.update(
                device=res.device,
                vendor=det.vendor,
                version=det.version,
                family=det.family,
                lines=res.lines,
                sanitized=res.sanitized,
                profile=ch.profile,
                profile_source=ch.source,
                match_level=ch.level,
                rule=model_support.rule_dict(rule) if rule is not None else None,
                previous={"profile": prev[0], "source": prev[1]} if prev else None,
                candidates=cands,
                recommended=cands[0]["profile"] if cands and det.vendor else None,
                suggested_rule=model_support.suggest_rule(res.device, det.version),
            )
            out.append(row)
    return out


def _remember(
    s: Any,
    kb: Any,
    det: Any,
    profile: str,
    rem: dict[str, Any],
    project_id: int | None,
    actor: str,
    can_global: bool,
    seen: dict[tuple[Any, ...], int],
    device: str = "",
) -> tuple[int, bool]:
    """导入时“记住”：新建型号规则（同一批相同的规则只建一次），返回 (规则编号, 是否新建)。"""
    from lmesh.core import model_support
    from lmesh.core.store.models import ModelRule

    scope = str(rem.get("scope") or "project")
    if scope not in model_support.SCOPES:
        raise model_support.ModelError("model.scope_invalid", scope=scope)
    if scope == "global" and not can_global:
        raise model_support.ModelError("api.error.kb_editor_only", "forbidden")
    if not model_support.allowed(kb, det, profile):
        raise model_support.ModelError("import.profile_not_allowed", profile=profile, vendor=det.vendor or "-")
    rem = dict(rem)
    if not any(str(rem.get(k) or "").strip() for k in ("name_pattern", "version", "feature")):
        rem.update(model_support.suggest_rule(device, det.version))  # 没写条件：按设备名与版本预填
    data = model_support.clean_rule({**rem, "profile": profile, "vendor": det.vendor}, kb)
    pid = None if scope == "global" or project_id is None else project_id
    key = (pid, *(data[k] for k in ("vendor", "name_pattern", "version", "feature", "profile")))
    if key in seen:
        return seen[key], False
    r = ModelRule(project_id=pid, created_by=actor, **data)
    s.add(r)
    s.flush()
    seen[key] = int(r.id)
    return int(r.id), True


def _ref_named(s: Any, project_id: int, name: str) -> bool:
    from lmesh.core.store.models import ProjectDeviceRef

    refs = select(ProjectDeviceRef.device_id).where(ProjectDeviceRef.project_id == project_id)
    return s.scalar(select(Device.id).where(Device.id.in_(refs), Device.name == name)) is not None


def list_devices(db_url: str) -> list[dict[str, Any]]:
    """当前项目的设备（私有设备与引用的公共设备）；latest_version_id 是设备在项目中的当前版本（引用固定了版本时为该版本）。"""
    from lmesh.core import projects

    with store.session(db_url) as s:
        pinned = projects.pins(s)
        out = []
        for d in s.scalars(projects.scoped_devices(select(Device)).order_by(Device.name)):
            newest = max(d.versions, key=lambda v: v.id, default=None)
            pin = pinned.get(d.id)
            latest = next((v for v in d.versions if v.id == pin), newest) if pin else newest
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
                    "source": "private" if d.project_id is not None else "public",
                }
            )
        return out
