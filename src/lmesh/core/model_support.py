"""未支持型号的处理（M8-7，REQ-044）：Profile 的选择顺序、试解析推荐、型号规则、申请支持与派生 Profile。

选择顺序（导入与重新解析共用 choose）：
1. 本次指定（导入时按文件指定、设备页更换）→ manual；
2. 设备之前的手工选择 → manual（一直沿用，直到改回自动）；
3. 型号规则（本项目 > 全局；条件多的优先；一样多时先建的优先）→ rule；
4. Profile 的版本规则命中 → auto；
5. 只按厂商套用标了 fallback 的 Profile → fallback；
6. 都没有（认不出厂商或没有可用的 Profile）→ none，只存原文、不解析。
手工与规则只允许同厂商 / 同平台族的 Profile；认不出厂商时可在全部 Profile 中选。fallback、rule、manual 属于“近似”。

试解析：用候选 Profile 各解析一次，按识别出的命令行比例排序（Profile 明确不支持的命令不算识别），不用 AI。
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select

from lmesh.core import store
from lmesh.core.kb import KnowledgeBase
from lmesh.core.parser import line_count
from lmesh.core.sanitize import detect_format, detect_vendor, detect_version, family_of
from lmesh.core.store.models import ConfigVersion, Device, ModelRule, Project, UnknownLine, iso

SOURCES = ("auto", "fallback", "rule", "manual", "none")
APPROX = frozenset({"fallback", "rule", "manual"})
SCOPES = ("project", "global")


class ModelError(ValueError):
    """kind：param 参数不对 / not_found / forbidden / state 状态不允许。"""

    def __init__(self, key: str, kind: str = "param", data: Any = None, **fmt: Any) -> None:
        super().__init__(key)
        self.key, self.kind, self.data, self.fmt = key, kind, data, fmt


def level_of(source: str) -> str:
    """匹配程度：exact 精确（版本规则命中）/ approx 近似 / none 无。"""
    return "exact" if source == "auto" else "none" if source == "none" else "approx"


# ---------------------------------------------------------------- 识别与候选


@dataclass
class Detected:
    vendor: str
    version: str
    fmt: str
    family: str | None  # 同一厂商有多种配置格式时确定的平台族（Nokia），其他厂商为 None（不限定）


def detect(text: str) -> Detected:
    vendor = detect_vendor(text) or ""
    fmt = detect_format(text, vendor) if vendor else ""
    return Detected(
        vendor, detect_version(text, vendor) if vendor else "", fmt, family_of(vendor, fmt) if vendor else None
    )


def allowed(kb: KnowledgeBase, det: Detected, pid: str) -> bool:
    """手工或规则选择的 Profile 是否允许：同厂商（同平台族，Nokia 两种格式不能混用）；认不出厂商时任意。"""
    p = kb.profiles.get(pid)
    if p is None:
        return False
    if not det.vendor:
        return True
    return p.vendor == det.vendor and (det.family is None or p.family == det.family)


def candidates(kb: KnowledgeBase, det: Detected) -> list[str]:
    return sorted(pid for pid in kb.profiles if allowed(kb, det, pid))


def _version_hit(kb: KnowledgeBase, pid: str, version: str) -> bool:
    mver = kb.profiles[pid].match.get("version", "")
    try:
        return bool(mver and version and re.search(mver, version))
    except re.error:
        return False


def _is_fallback(kb: KnowledgeBase, pid: str) -> bool:
    return str(kb.profiles[pid].match.get("fallback", "")).lower() in ("true", "1", "yes")


def _unsupported_cards(kb: KnowledgeBase, pid: str) -> set[str]:
    """该 Profile（继承展开后）明确标为不支持的节点所对应的命令卡。"""
    nodes = {n for n, e in kb.resolve_profile(pid).entries.items() if not e.supported}
    if not nodes:
        return set()
    return {c.id for c in kb.cards.values() if any(n in nodes for n in c.maps)}


def trial(
    kb: KnowledgeBase, text: str, det: Detected | None = None, profiles: list[str] | None = None
) -> list[dict[str, Any]]:
    """试解析：候选 Profile 各解析一次（同一平台族只解析一次），按识别出的命令行比例排序。

    比例 = （命令行 − 本 Profile 明确不支持的命令）/（命令行 + 未识别行）；相同时版本规则命中 > fallback > 编号。"""
    from lmesh.core import parser

    det = det or detect(text)
    pids = profiles if profiles is not None else candidates(kb, det)
    parsed: dict[str, Any] = {}
    out: list[dict[str, Any]] = []
    for pid in pids:
        if pid not in kb.profiles:
            continue
        fam = kb.profiles[pid].family
        if fam not in parsed:
            try:
                parsed[fam] = parser.parse(text, kb, fam)
            except Exception:  # noqa: BLE001 试解析失败的平台族记为全部未识别
                parsed[fam] = None
        pr = parsed[fam]
        if pr is None:
            cmd = unk = bad = 0
        else:
            c = pr.counts()
            cmd, unk = int(c.get("command", 0)), int(c.get("unknown", 0))
            nope = _unsupported_cards(kb, pid)
            bad = sum(1 for ln in pr.lines if ln.kind == "command" and ln.card in nope) if nope else 0
        total = cmd + unk
        out.append(
            {
                "profile": pid,
                "title": kb.profiles[pid].title or pid,
                "vendor": kb.profiles[pid].vendor,
                "family": fam,
                "ratio": round((cmd - bad) / total, 4) if total else 0.0,
                "recognized": cmd - bad,
                "command": cmd,
                "unknown": unk,
                "unsupported": bad,
                "exact": _version_hit(kb, pid, det.version),
                "fallback": _is_fallback(kb, pid),
            }
        )
    out.sort(key=lambda r: (-r["ratio"], not r["exact"], not r["fallback"], r["profile"]))
    return out


# ---------------------------------------------------------------- 型号规则


def _conditions(r: ModelRule | dict[str, Any]) -> int:
    get = r.get if isinstance(r, dict) else lambda k, d="": getattr(r, k, d)
    return sum(1 for k in ("name_pattern", "version", "feature", "vendor") if str(get(k, "") or "").strip())


def rule_matches(r: ModelRule, name: str, det: Detected, text: str) -> bool:
    if r.vendor and r.vendor != det.vendor:
        return False
    if r.name_pattern and not fnmatch.fnmatchcase((name or "").lower(), r.name_pattern.lower()):
        return False
    try:
        if r.version and not (det.version and re.search(r.version, det.version)):
            return False
        if r.feature and not re.search(r.feature, text, re.M):
            return False
    except re.error:
        return False
    return _conditions(r) > 0


def ordered_rules(s: Any, project_id: int | None) -> list[ModelRule]:
    """生效顺序：本项目规则在前，全局规则在后；同一范围内条件多的优先，一样多时编号小的优先。只含启用的规则。"""
    q = select(ModelRule).where(ModelRule.enabled.is_(True))
    q = q.where(
        or_(ModelRule.project_id.is_(None), ModelRule.project_id == project_id)
        if project_id is not None
        else ModelRule.project_id.is_(None)
    )
    rules = list(s.scalars(q))
    return sorted(rules, key=lambda r: (r.project_id is None, -_conditions(r), r.id))


def match_rule(kb: KnowledgeBase, rules: list[ModelRule], name: str, det: Detected, text: str) -> ModelRule | None:
    for r in rules:
        if rule_matches(r, name, det, text) and allowed(kb, det, r.profile):
            return r
    return None


# ---------------------------------------------------------------- 选择


@dataclass
class Choice:
    profile: str
    source: str
    rule_id: int | None
    vendor: str
    version: str
    family: str | None

    @property
    def level(self) -> str:
        return level_of(self.source)

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "level": self.level}


def choose(
    kb: KnowledgeBase | None,
    text: str,
    name: str,
    rules: list[ModelRule] | None = None,
    override: str | None = None,
    previous: tuple[str, str] | None = None,
    det: Detected | None = None,
) -> Choice:
    """按选择顺序确定 Profile（见模块说明）。override 不允许时抛 ModelError（import.profile_not_allowed）。"""
    det = det or detect(text)
    if kb is None:  # 没有知识库（只脱敏入库）：按命名约定推断，不解析
        from lmesh.core.importer import guess_profile

        pid = guess_profile(det.vendor, det.version, None, det.fmt) if det.vendor else ""
        return Choice(pid, "auto" if pid else "none", None, det.vendor, det.version, det.family)

    def pick(pid: str, source: str, rule_id: int | None = None) -> Choice:
        vendor = det.vendor or kb.profiles[pid].vendor
        return Choice(pid, source, rule_id, vendor, det.version, det.family)

    if override:
        if not allowed(kb, det, override):
            raise ModelError("import.profile_not_allowed", profile=override, vendor=det.vendor or "-")
        return pick(override, "manual")
    if previous and previous[1] == "manual" and allowed(kb, det, previous[0]):
        return pick(previous[0], "manual")
    if not det.vendor:
        return Choice("", "none", None, "", "", None)
    r = match_rule(kb, rules or [], name, det, text)
    if r is not None:
        return pick(r.profile, "rule", r.id)
    found = kb.match_profile(det.vendor, det.version, det.family)
    if found:
        return pick(found, "auto" if _version_hit(kb, found, det.version) else "fallback")
    return Choice("", "none", None, det.vendor, det.version, det.family)


def suggest_rule(name: str, version: str) -> dict[str, str]:
    """“记住”时预填的规则：设备名去掉末尾编号换成 *；版本取主版本（华为 VxxxRyyy、Cisco / Nokia 前两段）。"""
    pattern = re.sub(r"\d+$", "*", name) if name else ""
    ver = ""
    m = re.match(r"(V\d{3}R\d{3})", version or "")
    if m:
        ver = m.group(1)
    elif version:
        m2 = re.match(r"(\d+)\.(\d+)", version)
        ver = rf"^{m2.group(1)}\.{m2.group(2)}" if m2 else re.escape(version)
    return {"name_pattern": pattern, "version": ver, "feature": ""}


# ---------------------------------------------------------------- 规则的增删改


def rule_dict(r: ModelRule, s: Any = None) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": r.id,
        "scope": "global" if r.project_id is None else "project",
        "project_id": r.project_id,
        "vendor": r.vendor,
        "name_pattern": r.name_pattern,
        "version": r.version,
        "feature": r.feature,
        "profile": r.profile,
        "note": r.note,
        "enabled": r.enabled,
        "conditions": _conditions(r),
        "created_by": r.created_by,
        "created_at": iso(r.created_at),
        "updated_at": iso(r.updated_at),
    }
    if s is not None:
        d["devices"] = int(s.scalar(select(func.count(Device.id)).where(Device.profile_rule_id == r.id)) or 0)
    return d


def clean_rule(body: dict[str, Any], kb: KnowledgeBase) -> dict[str, Any]:
    out = {
        k: str(body.get(k) or "").strip() for k in ("vendor", "name_pattern", "version", "feature", "profile", "note")
    }
    for k in ("version", "feature"):
        if out[k]:
            try:
                re.compile(out[k])
            except re.error as e:
                raise ModelError("model.regex_invalid", field=k, value=out[k]) from e
    if not _conditions(out):
        raise ModelError("model.rule_no_condition")
    p = kb.profiles.get(out["profile"])
    if p is None:
        raise ModelError("model.profile_unknown", profile=out["profile"])
    if out["vendor"] and out["vendor"] != p.vendor:
        raise ModelError("import.profile_not_allowed", profile=out["profile"], vendor=out["vendor"])
    if not out["vendor"]:
        out["vendor"] = p.vendor  # 规则只能指向同厂商的 Profile：没写厂商时按 Profile 的厂商
    if len(out["name_pattern"]) > 200 or len(out["version"]) > 200 or len(out["feature"]) > 400:
        raise ModelError("model.too_long")
    return out


def list_rules(db_url: str, project_id: int | None, scope: str = "all") -> dict[str, Any]:
    with store.session(db_url) as s:
        out: dict[str, Any] = {}
        if scope in ("all", "project") and project_id is not None:
            rs = [r for r in ordered_rules(s, project_id) if r.project_id is not None]
            off = [
                r
                for r in s.scalars(
                    select(ModelRule).where(ModelRule.project_id == project_id, ModelRule.enabled.is_(False))
                )
            ]
            out["project"] = [rule_dict(r, s) for r in rs + sorted(off, key=lambda r: r.id)]
        if scope in ("all", "global"):
            rs = [r for r in ordered_rules(s, None)]
            off = [
                r
                for r in s.scalars(
                    select(ModelRule).where(ModelRule.project_id.is_(None), ModelRule.enabled.is_(False))
                )
            ]
            out["global"] = [rule_dict(r, s) for r in rs + sorted(off, key=lambda r: r.id)]
        return out


def create_rule(
    db_url: str, kb: KnowledgeBase, project_id: int | None, body: dict[str, Any], actor: str
) -> dict[str, Any]:
    data = clean_rule(body, kb)
    with store.session(db_url) as s:
        r = ModelRule(project_id=project_id, created_by=actor, enabled=bool(body.get("enabled", True)), **data)
        s.add(r)
        s.flush()
        return rule_dict(r, s)


def _get_rule(s: Any, rule_id: int, project_id: int | None, scope_ok: Any) -> ModelRule:
    r = s.get(ModelRule, rule_id)
    if r is None or (r.project_id is not None and r.project_id != project_id):
        raise ModelError("model.rule_not_found", "not_found", rule=rule_id)
    if not scope_ok(r):
        raise ModelError("api.error.kb_editor_only", "forbidden")
    return r


def update_rule(
    db_url: str, kb: KnowledgeBase, rule_id: int, project_id: int | None, body: dict[str, Any], can_global: bool
) -> dict[str, Any]:
    with store.session(db_url) as s:
        r = _get_rule(s, rule_id, project_id, lambda x: x.project_id is not None or can_global)
        cur = {k: getattr(r, k) for k in ("vendor", "name_pattern", "version", "feature", "profile", "note")}
        merged = {**cur, **{k: v for k, v in body.items() if k in cur and v is not None}}
        if "vendor" not in body and "profile" in body and body["profile"] != r.profile:
            merged["vendor"] = ""
        data = clean_rule(merged, kb)
        for k, v in data.items():
            setattr(r, k, v)
        if body.get("enabled") is not None:
            r.enabled = bool(body["enabled"])
        r.updated_at = datetime.now(UTC)
        return rule_dict(r, s)


def delete_rule(db_url: str, rule_id: int, project_id: int | None, can_global: bool) -> dict[str, Any]:
    with store.session(db_url) as s:
        r = _get_rule(s, rule_id, project_id, lambda x: x.project_id is not None or can_global)
        d = rule_dict(r, s)
        s.delete(r)
        return d


def test_rules(db_url: str, kb: KnowledgeBase, project_id: int | None, body: dict[str, Any]) -> dict[str, Any]:
    """试匹配：用规则条件（未保存的）对本项目设备的当前版本逐台判断，并给出实际会生效的规则（考虑更早的规则）。"""
    from lmesh.core import projects

    data = clean_rule(body, kb)
    probe = ModelRule(id=0, project_id=project_id, **data)
    hits = []
    with store.session(db_url) as s:
        rules = ordered_rules(s, project_id)
        q = (
            projects.scoped_devices(select(Device))
            if project_id is not None
            else select(Device).where(Device.project_id.is_(None))
        )
        for d in s.scalars(q.order_by(Device.name)):
            ver = max(d.versions, key=lambda v: v.id, default=None)
            if ver is None:
                continue
            det = detect(ver.raw_text)
            if not rule_matches(probe, d.name, det, ver.raw_text) or not allowed(kb, det, data["profile"]):
                continue
            first = match_rule(kb, rules, d.name, det, ver.raw_text)
            hits.append(
                {
                    "id": d.id,
                    "name": d.name,
                    "profile": d.profile,
                    "source": d.profile_source,
                    "taken_by": first.id if first is not None and first.id != body.get("id") else None,
                }
            )
    return {"devices": hits, "count": len(hits)}


# ---------------------------------------------------------------- 设备


def device_info(dev: Device, ver: ConfigVersion | None = None) -> dict[str, Any]:
    """设备的 Profile 来源与近似标记（设备列表、配置图、报告、下发前提示共用）。"""
    st = (ver.structured or {}) if ver is not None else {}
    cov = st.get("coverage")
    src = dev.profile_source or ("none" if not dev.profile else "auto")
    return {
        "profile": dev.profile,
        "profile_source": src,
        "profile_rule_id": dev.profile_rule_id,
        "match_level": level_of(src),
        "approx": src in APPROX,
        "unsupported": not dev.vendor,
        "unknown_ratio": round(1 - float(cov), 4) if isinstance(cov, int | float) else None,
    }


def device_choice(s: Any, kb: KnowledgeBase, dev: Device, text: str, override: str | None = None) -> Choice:
    """重新解析时的选择：沿用手工选择；否则按本设备所属项目的型号规则、版本规则、fallback。"""
    rules = ordered_rules(s, dev.project_id)
    return choose(kb, text, dev.name, rules, override, (dev.profile, dev.profile_source or "auto"))


def approx_note(db_url: str, device_id: int | None) -> dict[str, Any] | None:
    """变更脚本、翻译结果下发前的提示：设备使用近似 Profile 时返回说明，否则 None。"""
    if not device_id:
        return None
    with store.session(db_url) as s:
        dev = s.get(Device, device_id)
        if dev is None or (dev.profile_source or "auto") not in APPROX:
            return None
        return {
            "device": dev.name,
            "profile": dev.profile,
            "source": dev.profile_source,
            "rule_id": dev.profile_rule_id,
        }


def apply_choice(dev: Device, ch: Choice) -> None:
    dev.profile, dev.profile_source, dev.profile_rule_id = ch.profile, ch.source, ch.rule_id
    if ch.vendor:
        dev.vendor = ch.vendor


def _latest(s: Any, dev: Device) -> ConfigVersion | None:
    return max(dev.versions, key=lambda v: v.id, default=None)


def device_candidates(db_url: str, kb: KnowledgeBase, device_id: int) -> dict[str, Any]:
    """设备页“更换 Profile”：当前选择与候选 Profile 的试解析结果（最新版本）。"""
    from lmesh.core import projects

    with store.session(db_url) as s:
        dev = s.get(Device, device_id)
        if dev is None or not projects.visible(s, device_id):
            raise ModelError("compare.device_not_found", "not_found", target=str(device_id))
        ver = _latest(s, dev)
        if ver is None:
            raise ModelError("history.no_snapshots", "not_found", device=device_id)
        text, info, name = ver.raw_text, device_info(dev, ver), dev.name
        rule = s.get(ModelRule, dev.profile_rule_id) if dev.profile_rule_id else None
        auto = choose(kb, text, name, ordered_rules(s, dev.project_id))
    det = detect(text)
    cands = trial(kb, text, det)
    return {
        "device": {"id": device_id, "name": name, "vendor": det.vendor, "version": det.version, "family": det.family},
        **info,
        "rule": rule_dict(rule) if rule is not None else None,
        "auto": auto.as_dict(),
        "candidates": cands,
        "recommended": cands[0]["profile"] if cands and det.vendor else None,
        "suggested_rule": suggest_rule(name, det.version),
    }


def set_device_profile(
    db_url: str,
    root: Path,
    kb: KnowledgeBase,
    device_id: int,
    profile: str | None,
    actor: str,
    remember: dict[str, Any] | None = None,
    can_global: bool = False,
    is_admin: bool = False,
) -> dict[str, Any]:
    """更换 Profile 并重新解析最新版本：profile 为空时改回自动选择。remember 时同时新建型号规则（范围 project / global），
    规则命中这台设备时来源记为 rule。公共设备库的设备只有管理员能改。"""
    from lmesh.core import projects, workbench

    with store.session(db_url) as s:
        dev = s.get(Device, device_id)
        if dev is None or not projects.visible(s, device_id):
            raise ModelError("compare.device_not_found", "not_found", target=str(device_id))
        if dev.project_id is None and not is_admin:
            raise ModelError("model.public_device", "forbidden", device=dev.name)
        ver = _latest(s, dev)
        if ver is None:
            raise ModelError("history.no_snapshots", "not_found", device=device_id)
        det = detect(ver.raw_text)
        if profile and not allowed(kb, det, profile):
            raise ModelError("import.profile_not_allowed", profile=profile, vendor=det.vendor or "-")
        rule_id = None
        if profile and remember:
            scope = str(remember.get("scope") or "project")
            if scope not in SCOPES:
                raise ModelError("model.scope_invalid", scope=scope)
            if scope == "global" and not can_global:
                raise ModelError("api.error.kb_editor_only", "forbidden")
            data = clean_rule({**remember, "profile": profile, "vendor": det.vendor}, kb)
            r = ModelRule(project_id=None if scope == "global" else dev.project_id, created_by=actor, **data)
            s.add(r)
            s.flush()
            rule_id = r.id
        if not profile or rule_id:
            dev.profile_source = "auto"  # 改回自动（或交给刚记住的规则）：不再沿用之前的手工选择
        vid = ver.id
    out = workbench.analyse_version(db_url, vid, root, kb=kb, override=None if (not profile or rule_id) else profile)
    if profile and rule_id and out.get("profile") != profile:
        # 刚记住的规则被更早的规则抢先：按手工选择
        out = workbench.analyse_version(db_url, vid, root, kb=kb, override=profile)
    with store.session(db_url) as s:
        dev = s.get(Device, device_id)
        assert dev is not None
        ver = s.get(ConfigVersion, vid)
        return {"result": out, "rule_created": rule_id, **device_info(dev, ver)}


# ---------------------------------------------------------------- 申请支持与派生


def request_support(
    db_url: str, device_id: int, actor: str, model: str, reason: str, project: str | None = None
) -> dict[str, Any]:
    """设备页“申请支持此型号”：附设备信息与最新版本未识别行的前 20 种写法（已脱敏的模式），进审核队列（建议）。"""
    from lmesh.core import projects, review

    with store.session(db_url) as s:
        dev = s.get(Device, device_id)
        if dev is None or not projects.visible(s, device_id):
            raise ModelError("compare.device_not_found", "not_found", target=str(device_id))
        ver = max(dev.versions, key=lambda v: v.id, default=None)
        rows = []
        if ver is not None:
            rows = [
                {"pattern": p, "count": int(n)}
                for p, n in s.execute(
                    select(UnknownLine.pattern, func.count(UnknownLine.id))
                    .where(UnknownLine.version_id == ver.id)
                    .group_by(UnknownLine.pattern)
                    .order_by(func.count(UnknownLine.id).desc(), UnknownLine.pattern)
                    .limit(20)
                )
            ]
        info = device_info(dev, ver)
        det = detect(ver.raw_text) if ver is not None else Detected(dev.vendor, dev.sw_version, "", None)
        st = (ver.structured or {}) if ver is not None else {}
        counts = st.get("counts") or {}
        proj = s.get(Project, dev.project_id) if dev.project_id else None
        payload = {
            "kind": "model",
            "target": model,
            "model": model,
            "reason": reason,
            "current": dev.profile,
            "proposed": "",
            "project": project or (proj.slug if proj is not None else None),
            "device_id": dev.id,
            "device": dev.name,
            "vendor": dev.vendor,
            "family": det.family or "",
            "version": dev.sw_version,
            "lines": line_count(ver.raw_text) if ver is not None else 0,
            "command": int(counts.get("command", 0)),
            "unknown": int(counts.get("unknown", 0)),
            "patterns": rows,
            "suggested_rule": suggest_rule(dev.name, dev.sw_version),
            **{k: info[k] for k in ("profile", "profile_source", "profile_rule_id", "unknown_ratio")},
        }
    rid = review.add(
        db_url,
        "suggestion",
        f"{model} · model",
        model,
        payload,
        {"method": "user", "user": actor, "project": payload["project"]},
    )
    return {"id": rid, "status": "pending"}


def _support_item(s: Any, item_id: int) -> Any:
    from lmesh.core.store.models import ReviewItem

    item = s.get(ReviewItem, item_id)
    if item is None or item.kind != "suggestion" or (item.payload or {}).get("kind") != "model":
        raise ModelError("model.request_not_found", "not_found", item=item_id)
    return item


def released(root: Path, pid: str) -> bool:
    """Profile 是否已在最近一次发布的知识库版本中（没有仓库时视为已发布）。"""
    from lmesh.core.kb import repo

    if not (root / ".git").exists():
        return True
    rels = repo.releases(root)
    if not rels:
        return False
    from dulwich.objects import Tree
    from dulwich.repo import Repo

    try:
        with Repo(str(root)) as r:
            commit = repo._resolve(r, rels[0].tag)
            tree = r[commit.tree]
            assert isinstance(tree, Tree)
            repo._blob_at(r, tree, f"profiles/{pid}.yaml".encode())
        return True
    except (KeyError, AssertionError):
        return False


def support_status(db_url: str, root: Path, kb: KnowledgeBase, item_id: int) -> dict[str, Any]:
    """申请的处理状态：派生的 Profile、是否已发布、将改指向的规则与将重新解析的设备（预演，不修改）。"""
    from lmesh.core import review

    with store.session(db_url) as s:
        item = _support_item(s, item_id)
        payload = dict(item.payload or {})
    derived = (payload.get("derived") or {}).get("profile")
    out: dict[str, Any] = {
        "item": review.get(db_url, item_id),
        "derived": payload.get("derived"),
        "result": payload.get("retarget"),
    }
    if derived and derived in kb.profiles:
        out["released"] = released(root, derived)
        out["plan"] = _plan(db_url, kb, payload, derived)
    else:
        out["released"] = False
        out["plan"] = None
    out["bases"] = trial_for_device(db_url, kb, int(payload.get("device_id") or 0)) if payload.get("device_id") else []
    return out


def trial_for_device(db_url: str, kb: KnowledgeBase, device_id: int) -> list[dict[str, Any]]:
    with store.session(db_url) as s:
        dev = s.get(Device, device_id)
        ver = max(dev.versions, key=lambda v: v.id, default=None) if dev is not None else None
        text = ver.raw_text if ver is not None else ""
    return trial(kb, text) if text else []


def derive(db_url: str, root: Path, item_id: int, body: dict[str, Any], actor: str) -> dict[str, Any]:
    """从现有 Profile 派生（继承，只写差异）：在知识库草稿区新建 Profile，并记在申请上。"""
    from lmesh.core.kb import edit

    with store.session(db_url) as s:
        item = _support_item(s, item_id)
        if item.status != "pending":
            raise ModelError("review.already_decided", "state")
    base = str(body.get("base") or "")
    if not base:
        raise ModelError("model.base_required")
    try:
        r = edit.create_profile(
            root,
            {
                "id": body.get("id"),
                "title": body.get("title") or "",
                "platform": body.get("platform") or "",
                "software": body.get("software") or "",
                "inherits": base,
                "version": body.get("version") or "",
            },
        )
    except edit.EditError as e:
        kind = "not_found" if e.key == "kb.profile_unknown" else "param"
        raise ModelError(e.key, kind, e.data, **e.fmt) from e
    with store.session(db_url) as s:
        item = _support_item(s, item_id)
        item.payload = {
            **(item.payload or {}),
            "derived": {"profile": r["profile"], "base": base, "by": actor, "at": datetime.now(UTC).isoformat()},
        }
    return {"profile": r["profile"], "base": base, "file": r["file"]}


def _plan(db_url: str, kb: KnowledgeBase, payload: dict[str, Any], derived: str) -> dict[str, Any]:
    """改指向的预演：匹配申请设备的规则（各范围）与将重新解析的设备（所有项目；手工选择的不动，申请设备本身除外）。"""
    dev_id = int(payload.get("device_id") or 0)
    with store.session(db_url) as s:
        dev = s.get(Device, dev_id) if dev_id else None
        ver = max(dev.versions, key=lambda v: v.id, default=None) if dev is not None else None
        rules: list[ModelRule] = []
        if dev is not None and ver is not None:
            det = detect(ver.raw_text)
            for r in s.scalars(select(ModelRule).where(ModelRule.enabled.is_(True)).order_by(ModelRule.id)):
                hit = r.id == payload.get("profile_rule_id") or rule_matches(r, dev.name, det, ver.raw_text)
                if hit and (r.project_id is None or r.project_id == dev.project_id):
                    rules.append(r)
        change = (
            [r for r in rules if r.profile != derived and allowed(kb, detect(ver.raw_text), derived)] if ver else []
        )
        create = None
        if not rules and dev is not None:
            sug = payload.get("suggested_rule") or suggest_rule(dev.name, dev.sw_version)
            create = {
                "scope": "global",
                **{k: sug.get(k, "") for k in ("name_pattern", "version", "feature")},
                "profile": derived,
            }
        ids = {r.id for r in rules}
        targets: dict[int, dict[str, Any]] = {}
        if ids:
            for d in s.scalars(select(Device).where(Device.profile_rule_id.in_(ids))):
                targets[d.id] = _dev_row(s, d)
        # 还没有被规则选中、但会被这些规则（或将新建的规则）命中的设备
        probe = rules or (
            [
                ModelRule(
                    id=0,
                    project_id=None,
                    vendor=kb.profiles[derived].vendor,
                    **{k: create[k] for k in ("name_pattern", "version", "feature")},
                    profile=derived,
                )
            ]
            if create
            else []
        )
        for d in s.scalars(
            select(Device).where(
                Device.profile_source.in_(("auto", "fallback", "rule")), Device.vendor == kb.profiles[derived].vendor
            )
        ):
            if d.id in targets:
                continue
            v = max(d.versions, key=lambda x: x.id, default=None)
            if v is None:
                continue
            det2 = detect(v.raw_text)
            if any(
                (r.project_id is None or r.project_id == d.project_id) and rule_matches(r, d.name, det2, v.raw_text)
                for r in probe
            ):
                targets[d.id] = _dev_row(s, d)
        if dev is not None and dev.id not in targets:
            targets[dev.id] = _dev_row(s, dev)
        return {
            "rules": [{**rule_dict(r), "to": derived, "change": r in change} for r in rules],
            "create_rule": create,
            "devices": sorted(targets.values(), key=lambda x: (x["project"] or "", x["name"])),
        }


def _dev_row(s: Any, d: Device) -> dict[str, Any]:
    proj = s.get(Project, d.project_id) if d.project_id else None
    return {
        "id": d.id,
        "name": d.name,
        "project": proj.slug if proj is not None else None,
        "profile": d.profile,
        "source": d.profile_source,
    }


def retarget(db_url: str, root: Path, kb: KnowledgeBase, item_id: int, actor: str, note: str = "") -> dict[str, Any]:
    """派生 Profile 之后：匹配申请设备的型号规则改指向它（没有规则时新建一条全局规则），相关设备重新解析，申请标为通过。

    手工选择过 Profile 的其他设备不动；申请设备本身如果是手工选择的近似 Profile，改回自动（由规则选中新 Profile）。"""
    from lmesh.core import review, workbench

    with store.session(db_url) as s:
        item = _support_item(s, item_id)
        if item.status != "pending":
            raise ModelError("review.already_decided", "state")
        payload = dict(item.payload or {})
    derived = (payload.get("derived") or {}).get("profile")
    if not derived:
        raise ModelError("model.not_derived", "state")
    if derived not in kb.profiles:
        raise ModelError("model.profile_unknown", "state", profile=derived)
    plan = _plan(db_url, kb, payload, derived)
    changed: list[int] = []
    created = None
    with store.session(db_url) as s:
        for r in plan["rules"]:
            if r["change"]:
                obj = s.get(ModelRule, r["id"])
                if obj is not None:
                    obj.profile, obj.vendor, obj.updated_at = derived, kb.profiles[derived].vendor, datetime.now(UTC)
                    changed.append(obj.id)
        if plan["create_rule"]:
            c = plan["create_rule"]
            obj = ModelRule(
                project_id=None,
                vendor=kb.profiles[derived].vendor,
                name_pattern=c["name_pattern"],
                version=c["version"],
                feature=c["feature"],
                profile=derived,
                note=f"REQ-044 #{item_id}",
                created_by=actor,
            )
            if _conditions(obj):
                s.add(obj)
                s.flush()
                created = rule_dict(obj)
        dev = s.get(Device, int(payload.get("device_id") or 0))
        if dev is not None and dev.profile_source == "manual" and dev.profile == payload.get("profile"):
            dev.profile_source = "auto"
    reparsed = []
    for d in plan["devices"]:
        with store.session(db_url) as s:
            dv = s.get(Device, d["id"])
            ver = max(dv.versions, key=lambda v: v.id, default=None) if dv is not None else None
            vid = ver.id if ver is not None else None
        if vid is None:
            continue
        r = workbench.analyse_version(db_url, vid, root, kb=kb)
        with store.session(db_url) as s:
            dv = s.get(Device, d["id"])
            reparsed.append(
                {
                    **d,
                    "profile": dv.profile if dv else "",
                    "source": dv.profile_source if dv else "",
                    "unknown": r.get("unknown"),
                }
            )
    result = {
        "profile": derived,
        "released": released(root, derived),
        "rules_changed": changed,
        "rule_created": created,
        "devices": reparsed,
    }
    with store.session(db_url) as s:
        item = _support_item(s, item_id)
        item.payload = {
            **(item.payload or {}),
            "retarget": {**result, "by": actor, "at": datetime.now(UTC).isoformat()},
        }
    review.decide(db_url, root, item_id, True, note or f"retarget → {derived}", commit=False)
    return result
