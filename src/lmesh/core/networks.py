"""项目内的网络（M9，REQ-045）。CLI 与 API 共用。

- 网络是项目里平铺的独立工作区；文件夹只整理列表。设备属于项目，网络引用设备（network_members），一台设备可以在
  多个网络里；每个网络里的设备可以跟随最新版本，也可以固定在某个版本（做法同 M6 的设备引用）。
- 默认网络：每个项目一个（升级时与新建项目时自动建），始终包含全部设备、自动加入新设备，可以改名、不能删除，
  成员不能移出（D-0306）。
- 按网络独立的工作数据（network_id）：检查忽略、规则调整、脚本组与脚本、AI 建议与采纳记录、视图标注；
  拓扑、一致性、检查、基线、变更、割接、报告与导出只看当前网络的设备与版本（projects.device_clause / pins）。
- 自动加入规则：设备名（* ? 通配）、管理网段（CIDR）；导入时命中就加入，手工移出的设备记为排除、不再自动加入。
- 建网建议：连通分量、IGP 域、BGP AS、设备名规则、管理网段、AI 拓扑整理的分组；代码在配置图上计算，预览后采纳。
- 识别色：8 个颜色键，按创建顺序自动分配，可以改成组内其他颜色。
权限按项目：查看为项目成员，修改为属主、可编辑成员与管理员（scope.can_write）。
"""

from __future__ import annotations

import fnmatch
import ipaddress
import logging
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update

from lmesh.core import projects, store
from lmesh.core.projects import ProjectError, Scope
from lmesh.core.store.models import (
    AISuggestion,
    AISuggestionBatch,
    CheckIgnore,
    CheckProject,
    CheckRevision,
    CheckScript,
    ConfigImport,
    ConfigVersion,
    Device,
    Network,
    NetworkFolder,
    NetworkMember,
    NetworkRule,
    ProjectDeviceRef,
    ProjectRuleOverride,
    ViewAnnotation,
    iso,
)

PALETTE = ("slate", "indigo", "green", "rust", "teal", "violet", "amber", "rose")
DEFAULT_SLUG = "default"
DEFAULT_NAME = "默认网络"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
RULE_KINDS = ("name", "subnet")
JOIN_SOURCES = ("upgrade", "default", "manual", "rule", "suggestion", "copy", "import")
BASES = ("components", "igp", "bgp", "name", "subnet", "ai")
DEFAULT_NAME_REGEX = r"^(.+)-[^-]+$"
MAX_SUGGESTIONS = 100
# 管理口：华为 MEth、Cisco MgmtEth / GigabitEthernet0（ASR 920 等）、Juniper fxp / em；管理 VRF 的名字
_MGMT_IF = re.compile(r"^(meth|mgmteth|mgmt|management|fxp|em)\S*$|^gigabitethernet0$", re.I)
_MGMT_VRF = re.compile(r"mgmt|manage|oam", re.I)

_log = logging.getLogger("lmesh.networks")


def _now() -> datetime:
    return datetime.now(UTC)


def _err(key: str, kind: str = "param", data: Any = None, **fmt: Any) -> ProjectError:
    return ProjectError(key, kind, data, **fmt)


# ---------------------------------------------------------------- 默认网络与查找


def ensure_default(s: Any, project_id: int) -> Network:
    """项目的默认网络（没有时建：标识 default，包含项目里的全部设备）。"""
    n = s.scalar(select(Network).where(Network.project_id == project_id, Network.is_default.is_(True)).limit(1))
    if n is not None:
        return n  # type: ignore[no-any-return]
    n = Network(
        project_id=project_id,
        slug=_free_slug(s, project_id, DEFAULT_SLUG),
        name=DEFAULT_NAME,
        color=_next_color(s, project_id),
        is_default=True,
        position=0,
    )
    s.add(n)
    s.flush()
    for did in project_device_ids(s, project_id):
        s.add(NetworkMember(network_id=n.id, device_id=did, join_source="default"))
    s.flush()
    return n


def default_network_id(db_url: str, project_id: int) -> int | None:
    """项目的默认网络编号；项目不存在时 None。"""
    from lmesh.core.store.models import Project

    with store.session(db_url) as s:
        if s.get(Project, project_id) is None:
            return None
        return int(ensure_default(s, project_id).id)


def find(s: Any, project_id: int, ref: str | int) -> Network | None:
    """网络引用：标识（不分大小写）或编号。"""
    if isinstance(ref, int):
        n = s.get(Network, ref)
        return n if n is not None and n.project_id == project_id else None
    text = str(ref).strip()
    n = s.scalar(select(Network).where(Network.project_id == project_id, Network.slug == text.lower()))
    if n is None and text.isdigit():
        n = s.get(Network, int(text))
        if n is not None and n.project_id != project_id:
            n = None
    return n  # type: ignore[no-any-return]


def _get(s: Any, scope: Scope, ref: str | int) -> Network:
    ensure_default(s, scope.project_id)
    n = find(s, scope.project_id, ref)
    if n is None:
        raise _err("networks.not_found", "not_found", network=str(ref))
    return n


def project_device_ids(s: Any, project_id: int) -> list[int]:
    own = list(s.scalars(select(Device.id).where(Device.project_id == project_id)))
    refs = list(s.scalars(select(ProjectDeviceRef.device_id).where(ProjectDeviceRef.project_id == project_id)))
    return sorted(set(own) | set(refs))


def _sync_default(s: Any, n: Network) -> None:
    """默认网络包含全部设备：补上缺的成员（例如直接调用 core 导入的设备）。"""
    have = set(s.scalars(select(NetworkMember.device_id).where(NetworkMember.network_id == n.id)))
    for did in project_device_ids(s, n.project_id):
        if did not in have:
            s.add(NetworkMember(network_id=n.id, device_id=did, join_source="default"))
    s.execute(
        update(NetworkMember)
        .where(NetworkMember.network_id == n.id, NetworkMember.excluded.is_(True))
        .values(excluded=False)
    )
    s.flush()


def _free_slug(s: Any, project_id: int, base: str, ignore: int | None = None) -> str:
    b = re.sub(r"[^a-z0-9]+", "-", (base or "").lower()).strip("-")[:56] or "network"
    if not b[0].isalnum():
        b = "network"
    cand, i = b, 2
    while _slug_taken(s, project_id, cand, ignore):
        cand, i = f"{b}-{i}", i + 1
    return cand


def _slug_taken(s: Any, project_id: int, slug: str, ignore: int | None = None) -> bool:
    q = select(Network.id).where(Network.project_id == project_id, Network.slug == slug)
    if ignore is not None:
        q = q.where(Network.id != ignore)
    return s.scalar(q) is not None


def _next_color(s: Any, project_id: int) -> str:
    n = int(s.scalar(select(func.count()).select_from(Network).where(Network.project_id == project_id)) or 0)
    return PALETTE[n % len(PALETTE)]


def _validate_slug(slug: Any) -> str:
    v = str(slug or "").strip().lower()
    if not SLUG_RE.match(v):
        raise _err("networks.bad_slug", slug=str(slug))
    return v


def _validate_name(name: Any) -> str:
    v = str(name or "").strip()
    if not v or len(v) > 200:
        raise _err("networks.bad_name")
    return v


def _validate_color(color: Any) -> str:
    v = str(color or "").strip().lower()
    if v not in PALETTE:
        raise _err("networks.bad_color", color=str(color), allowed=", ".join(PALETTE))
    return v


def _folder(s: Any, project_id: int, folder_id: Any) -> int | None:
    if folder_id in (None, "", 0):
        return None
    f = s.get(NetworkFolder, int(folder_id))
    if f is None or f.project_id != project_id:
        raise _err("networks.folder_not_found", "not_found", folder=str(folder_id))
    return int(f.id)


# ---------------------------------------------------------------- 成员查询（其他模块调用）


def networks_of_devices(s: Any, project_id: int) -> dict[int, list[dict[str, Any]]]:
    """{设备: [{id, slug, name, color, default, policy, version_id}]}：设备在项目的哪些网络里（不含排除）。"""
    rows = s.execute(
        select(NetworkMember.device_id, NetworkMember.version_id, Network)
        .join(Network, Network.id == NetworkMember.network_id)
        .where(Network.project_id == project_id, NetworkMember.excluded.is_(False))
        .order_by(Network.is_default.desc(), Network.position, Network.id)
    ).all()
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for did, vid, n in rows:
        out[int(did)].append({**brief(n), "policy": "pin" if vid else "follow", "version_id": vid})
    return out


def brief(n: Network) -> dict[str, Any]:
    return {"id": n.id, "slug": n.slug, "name": n.name, "color": n.color, "default": bool(n.is_default)}


def _members(s: Any, n: Network) -> list[NetworkMember]:
    if n.is_default:
        _sync_default(s, n)
    return list(
        s.scalars(
            select(NetworkMember)
            .where(NetworkMember.network_id == n.id, NetworkMember.excluded.is_(False))
            .order_by(NetworkMember.device_id)
        )
    )


def member_device_ids(db_url: str, network_id: int) -> list[int]:
    with store.session(db_url) as s:
        n = s.get(Network, network_id)
        return [m.device_id for m in _members(s, n)] if n is not None else []


# ---------------------------------------------------------------- 加入新设备（导入、引用、复制设备）


def join_new_device(s: Any, scope: Scope | None, device_id: int, source: str = "default") -> list[dict[str, Any]]:
    """新设备进入项目时：加入默认网络；当前网络不是默认网络时同时加入当前网络（在网络里导入 / 添加）。"""
    if scope is None:
        return []
    out = []
    d = ensure_default(s, scope.project_id)
    if _join(s, d, device_id, source, None, scope.identity.username, force=True):
        out.append({**brief(d), "via": "default"})
    if scope.network_id is not None and not scope.network_default:
        n = s.get(Network, scope.network_id)
        if n is not None and _join(s, n, device_id, "import", None, scope.identity.username, force=True):
            out.append({**brief(n), "via": "current"})
    return out


def _join(
    s: Any, n: Network, device_id: int, source: str, rule_id: int | None, actor: str, force: bool = False
) -> bool:
    """加入网络；已经是成员时不变。排除的设备只有 force（手工、在网络里导入）才重新加入。返回是否新加入。"""
    m = s.scalar(select(NetworkMember).where(NetworkMember.network_id == n.id, NetworkMember.device_id == device_id))
    if m is not None and not m.excluded:
        return False
    if m is not None and m.excluded and not force:
        return False
    if m is None:
        m = NetworkMember(network_id=n.id, device_id=device_id)
        s.add(m)
    m.excluded, m.join_source, m.rule_id, m.version_id = False, source, rule_id, None
    m.joined_by, m.joined_at = actor[:200], _now()
    s.flush()
    return True


def auto_join(
    db_url: str, project_id: int, device_ids: list[int], scope: Scope | None, actor: str = "", kb: Any = None
) -> dict[int, list[dict[str, Any]]]:
    """导入后的自动加入（M9）：默认网络（全部新设备）、当前网络（在网络里导入）、各网络的自动加入规则（设备名、
    管理网段；管理网段要有知识库才能算出管理地址）。手工移出（排除）的设备不会再被规则加入。
    返回 {设备: [{id, slug, name, color, default, via: default|current|rule, rule}]}，只列这次新加入的。"""
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if not device_ids:
        return out
    with store.session(db_url) as s:
        d = ensure_default(s, project_id)
        rules = list(
            s.execute(
                select(NetworkRule, Network)
                .join(Network, Network.id == NetworkRule.network_id)
                .where(Network.project_id == project_id, NetworkRule.enabled.is_(True))
                .order_by(Network.position, Network.id, NetworkRule.id)
            ).all()
        )
        names = {
            int(i): str(nm) for i, nm in s.execute(select(Device.id, Device.name).where(Device.id.in_(device_ids)))
        }
        cur = None
        if scope is not None and scope.project_id == project_id and scope.network_id and not scope.network_default:
            cur = s.get(Network, scope.network_id)
        for did in device_ids:
            if _join(s, d, did, "default", None, actor, force=True):
                out[did].append({**brief(d), "via": "default", "rule": None})
            if cur is not None and _join(s, cur, did, "import", None, actor, force=True):
                out[did].append({**brief(cur), "via": "current", "rule": None})
    if not rules:
        return out
    need_mgmt = any(r.kind == "subnet" for r, _ in rules)
    mgmt = mgmt_addresses(db_url, device_ids, kb) if need_mgmt and kb is not None else {}
    with store.session(db_url) as s:
        for did in device_ids:
            for r, n in rules:
                if n.is_default or any(x["id"] == n.id for x in out[did]):
                    continue
                if not rule_matches(r.kind, r.pattern, names.get(did, ""), (mgmt.get(did) or {}).get("address")):
                    continue
                net = s.get(Network, n.id)
                if net is not None and _join(s, net, did, "rule", r.id, actor):
                    out[did].append(
                        {**brief(n), "via": "rule", "rule": {"id": r.id, "kind": r.kind, "pattern": r.pattern}}
                    )
    return out


# ---------------------------------------------------------------- 管理地址


_MGMT_CACHE: dict[int, dict[str, Any] | None] = {}


def mgmt_of_facts(f: Any) -> dict[str, Any] | None:
    """管理地址：管理口的地址；其次管理 VRF（名字含 mgmt / manage / oam）里的接口地址；再次 LSR ID（通常是
    Loopback0 / system）；最后第一个 Loopback 地址。返回 {address, source: mgmt_if|mgmt_vrf|lsr_id|loopback, interface}。"""
    ifaces = list(f.ifaces.values())
    for itf in ifaces:
        if _MGMT_IF.match(itf.name) and itf.primary is not None:
            return {"address": str(itf.primary.ip), "source": "mgmt_if", "interface": itf.name}
    for itf in ifaces:
        if itf.vrf and _MGMT_VRF.search(itf.vrf) and not itf.loopback and itf.primary is not None:
            return {"address": str(itf.primary.ip), "source": "mgmt_vrf", "interface": itf.name}
    if f.lsr_id:
        return {"address": str(f.lsr_id), "source": "lsr_id", "interface": None}
    for itf in ifaces:
        if itf.loopback and itf.vrf == "" and itf.primary is not None:
            return {"address": str(itf.primary.ip), "source": "loopback", "interface": itf.name}
    return None


def mgmt_addresses(db_url: str, device_ids: list[int], kb: Any) -> dict[int, dict[str, Any] | None]:
    """设备当前版本（项目里的当前版本）的管理地址；按版本缓存。"""
    from lmesh.core import analysis, graphstore, topology

    out: dict[int, dict[str, Any] | None] = {}
    with store.session(db_url) as s:
        vids = {did: projects.current_version_id(s, did) for did in device_ids}
        names = {int(i): str(n) for i, n in s.execute(select(Device.id, Device.name).where(Device.id.in_(device_ids)))}
    for did, vid in vids.items():
        if vid is None:
            out[did] = None
            continue
        if vid not in _MGMT_CACHE:
            try:
                g, _, _ = graphstore.build_for_version(db_url, vid, kb)
                f = topology.DevFacts(topology.Device(names.get(did, str(did)), g, did, vid), kb)
                _MGMT_CACHE[vid] = mgmt_of_facts(f)
            except (analysis.AnalysisError, KeyError, ValueError):
                _MGMT_CACHE[vid] = None
        out[did] = _MGMT_CACHE[vid]
    return out


# ---------------------------------------------------------------- 自动加入规则


def _check_rule(kind: Any, pattern: Any) -> tuple[str, str]:
    k = str(kind or "").strip().lower()
    if k not in RULE_KINDS:
        raise _err("networks.bad_rule_kind", kind=str(kind), allowed=", ".join(RULE_KINDS))
    p = str(pattern or "").strip()
    if not p or len(p) > 200:
        raise _err("networks.bad_rule_pattern", pattern=p)
    if k == "subnet":
        try:
            p = str(ipaddress.ip_network(p, strict=False))
        except ValueError as e:
            raise _err("networks.bad_rule_pattern", pattern=p) from e
    return k, p


def rule_matches(kind: str, pattern: str, name: str, address: str | None) -> bool:
    if kind == "name":
        return fnmatch.fnmatchcase(name.lower(), pattern.lower())
    if kind == "subnet" and address:
        try:
            return ipaddress.ip_address(address) in ipaddress.ip_network(pattern, strict=False)
        except ValueError:
            return False
    return False


def _rule_dict(r: NetworkRule) -> dict[str, Any]:
    return {
        "id": r.id,
        "kind": r.kind,
        "pattern": r.pattern,
        "enabled": r.enabled,
        "created_by": r.created_by,
        "created_at": iso(r.created_at),
    }


def preview_rule(db_url: str, scope: Scope, ref: str | int, kind: Any, pattern: Any, kb: Any = None) -> dict[str, Any]:
    """规则命中预览：项目里现在命中的设备，其中哪些不在本网络、哪些是排除的。"""
    k, p = _check_rule(kind, pattern)
    with store.session(db_url) as s:
        n = _get(s, scope, ref)
        nid = n.id
        all_ids = project_device_ids(s, scope.project_id)
        names = {int(i): str(nm) for i, nm in s.execute(select(Device.id, Device.name).where(Device.id.in_(all_ids)))}
        rows = {int(m.device_id): m for m in s.scalars(select(NetworkMember).where(NetworkMember.network_id == nid))}
    mgmt = mgmt_addresses(db_url, all_ids, kb) if k == "subnet" and kb is not None else {}
    hits = []
    for did in all_ids:
        addr = (mgmt.get(did) or {}).get("address")
        if rule_matches(k, p, names[did], addr):
            m = rows.get(did)
            state = "member" if m is not None and not m.excluded else ("excluded" if m is not None else "outside")
            hits.append({"id": did, "name": names[did], "mgmt_address": addr, "state": state})
    return {
        "kind": k,
        "pattern": p,
        "matches": len(hits),
        "not_in_network": sum(1 for h in hits if h["state"] == "outside"),
        "excluded": sum(1 for h in hits if h["state"] == "excluded"),
        "devices": hits,
        "mgmt_available": k != "subnet" or kb is not None,
    }


def list_rules(db_url: str, scope: Scope, ref: str | int) -> dict[str, Any]:
    with store.session(db_url) as s:
        n = _get(s, scope, ref)
        rules = list(s.scalars(select(NetworkRule).where(NetworkRule.network_id == n.id).order_by(NetworkRule.id)))
        excluded = list(
            s.execute(
                select(Device.id, Device.name)
                .join(NetworkMember, NetworkMember.device_id == Device.id)
                .where(NetworkMember.network_id == n.id, NetworkMember.excluded.is_(True))
                .order_by(Device.name)
            ).all()
        )
        return {
            "network": brief(n),
            "all_new_devices": bool(n.is_default),
            "rules": [_rule_dict(r) for r in rules],
            "excluded": [{"id": i, "name": nm} for i, nm in excluded],
        }


def add_rule(
    db_url: str, scope: Scope, ref: str | int, kind: Any, pattern: Any, apply_existing: bool = False, kb: Any = None
) -> dict[str, Any]:
    """添加自动加入规则；apply_existing 时把现在命中、还不在本网络（也没有被排除）的设备加进来。"""
    projects.require_write(scope)
    k, p = _check_rule(kind, pattern)
    with store.session(db_url) as s:
        n = _get(s, scope, ref)
        if n.is_default:
            raise _err("networks.default_all_devices", "state")
        dup = s.scalar(
            select(NetworkRule.id).where(
                NetworkRule.network_id == n.id, NetworkRule.kind == k, NetworkRule.pattern == p
            )
        )
        if dup is not None:
            raise _err("networks.rule_exists", "state", pattern=p)
        r = NetworkRule(network_id=n.id, kind=k, pattern=p, created_by=scope.identity.username[:200])
        s.add(r)
        s.flush()
        rid, nid = int(r.id), int(n.id)
        out = _rule_dict(r)
    added: list[dict[str, Any]] = []
    if apply_existing:
        pv = preview_rule(db_url, scope, nid, k, p, kb)
        with store.session(db_url) as s:
            net = s.get(Network, nid)
            assert net is not None
            for h in pv["devices"]:
                if h["state"] == "outside" and _join(s, net, h["id"], "rule", rid, scope.identity.username):
                    added.append({"id": h["id"], "name": h["name"]})
    return {**out, "added": added}


def update_rule(db_url: str, scope: Scope, ref: str | int, rule_id: int, data: dict[str, Any]) -> dict[str, Any]:
    projects.require_write(scope)
    with store.session(db_url) as s:
        n = _get(s, scope, ref)
        r = s.get(NetworkRule, rule_id)
        if r is None or r.network_id != n.id:
            raise _err("networks.rule_not_found", "not_found", rule=rule_id)
        if data.get("kind") is not None or data.get("pattern") is not None:
            r.kind, r.pattern = _check_rule(data.get("kind") or r.kind, data.get("pattern") or r.pattern)
        if data.get("enabled") is not None:
            r.enabled = bool(data["enabled"])
        s.flush()
        return _rule_dict(r)


def delete_rule(db_url: str, scope: Scope, ref: str | int, rule_id: int) -> dict[str, Any]:
    """删除规则；已经加入的设备不受影响。"""
    projects.require_write(scope)
    with store.session(db_url) as s:
        n = _get(s, scope, ref)
        r = s.get(NetworkRule, rule_id)
        if r is None or r.network_id != n.id:
            raise _err("networks.rule_not_found", "not_found", rule=rule_id)
        s.delete(r)
    return {"deleted": True, "id": rule_id}


# ---------------------------------------------------------------- 网络信息


def _counts(s: Any, n: Network, pool: set[int], others: dict[int, int]) -> dict[str, Any]:
    members = [m.device_id for m in _members(s, n)]
    cps = list(s.scalars(select(CheckProject.id).where(CheckProject.network_id == n.id)))
    scripts, script_err = 0, 0
    if cps:
        rows = list(s.scalars(select(CheckScript).where(CheckScript.project_id.in_(cps))))
        scripts = len(rows)
        script_err = sum(1 for x in rows if int((x.last_check or {}).get("errors") or 0) > 0)
    pending = int(
        s.scalar(
            select(func.count())
            .select_from(AISuggestion)
            .where(AISuggestion.network_id == n.id, AISuggestion.status == "pending")
        )
        or 0
    )
    findings = check_summary(n, set(members))
    return {
        "devices": len(members),
        "shared": sum(1 for d in members if others.get(d, 0) > 0),
        "pinned": int(
            s.scalar(
                select(func.count())
                .select_from(NetworkMember)
                .where(
                    NetworkMember.network_id == n.id,
                    NetworkMember.excluded.is_(False),
                    NetworkMember.version_id.is_not(None),
                )
            )
            or 0
        ),
        "scripts": scripts,
        "scripts_with_errors": script_err,
        "check_groups": len(cps),
        "ai_pending": pending,
        "annotations": _count(s, ViewAnnotation, n.id),
        "ignores": _count(s, CheckIgnore, n.id),
        "overrides": _count(s, ProjectRuleOverride, n.id),
        "rules": int(
            s.scalar(select(func.count()).select_from(NetworkRule).where(NetworkRule.network_id == n.id)) or 0
        ),
        "findings": findings,
    }


def _count(s: Any, model: Any, nid: int) -> int:
    return int(s.scalar(select(func.count()).select_from(model).where(model.network_id == nid)) or 0)


def check_summary(n: Network, members: set[int]) -> dict[str, Any]:
    """本网络最近的检查结果（按设备记下的，见 record_check）：错误、警告、提示、检查过的设备数、最近一次时间。"""
    checks = {int(k): v for k, v in ((n.stats or {}).get("checks") or {}).items() if int(k) in members}
    out: dict[str, Any] = {"error": 0, "warning": 0, "info": 0, "devices_checked": len(checks), "last_run": None}
    for v in checks.values():
        for k in ("error", "warning", "info"):
            out[k] += int(v.get(k) or 0)
        if v.get("at") and (out["last_run"] is None or v["at"] > out["last_run"]):
            out["last_run"] = v["at"]
    return out


def network_dict(
    s: Any, n: Network, pool: set[int] | None = None, others: dict[int, int] | None = None
) -> dict[str, Any]:
    if pool is None or others is None:
        pool = set(project_device_ids(s, n.project_id))
        others = _other_counts(s, n.project_id)
    folder = s.get(NetworkFolder, n.folder_id) if n.folder_id else None
    return {
        **brief(n),
        "description": n.description,
        "folder_id": n.folder_id,
        "folder": folder.name if folder else None,
        "position": n.position,
        "copied_from": n.copied_from,
        "last_activity": n.last_activity,
        "created_by": n.created_by,
        "created_at": iso(n.created_at),
        "updated_at": iso(n.updated_at),
        "counts": _counts(s, n, pool, {d: c - 1 for d, c in others.items()} if not n.is_default else others),
    }


def _other_counts(s: Any, project_id: int) -> dict[int, int]:
    """{设备: 在几个非默认网络里}。"""
    rows = s.execute(
        select(NetworkMember.device_id, func.count())
        .join(Network, Network.id == NetworkMember.network_id)
        .where(Network.project_id == project_id, Network.is_default.is_(False), NetworkMember.excluded.is_(False))
        .group_by(NetworkMember.device_id)
    ).all()
    return {int(d): int(c) for d, c in rows}


def list_networks(db_url: str, scope: Scope) -> dict[str, Any]:
    """网络列表（按文件夹与位置）、文件夹、颜色组、项目概览（全部设备的汇总）。
    每个网络的 counts：设备数、与其他网络共用的设备数、固定版本数、脚本与有问题的脚本、待处理的 AI 建议、标注、忽略、
    规则调整、自动加入规则、最近的检查结果（findings）。"""
    with store.session(db_url) as s:
        ensure_default(s, scope.project_id)
        nets = list(
            s.scalars(
                select(Network)
                .where(Network.project_id == scope.project_id)
                .order_by(Network.is_default.desc(), Network.position, Network.id)
            )
        )
        pool = set(project_device_ids(s, scope.project_id))
        others = _other_counts(s, scope.project_id)
        rows = [network_dict(s, n, pool, others) for n in nets]
        folders = [
            {
                "id": f.id,
                "name": f.name,
                "position": f.position,
                "networks": [r["slug"] for r in rows if r["folder_id"] == f.id],
            }
            for f in s.scalars(
                select(NetworkFolder)
                .where(NetworkFolder.project_id == scope.project_id)
                .order_by(NetworkFolder.position, NetworkFolder.id)
            )
        ]
        return {
            "networks": rows,
            "folders": folders,
            "palette": list(PALETTE),
            "current": scope.network_slug if scope.network_explicit else None,
            "overview": _overview(s, scope.project_id, pool, others),
        }


def _overview(s: Any, project_id: int, pool: set[int], others: dict[int, int]) -> dict[str, Any]:
    since = _now() - timedelta(days=1)
    today = set(
        s.scalars(
            select(ConfigImport.device_id).where(
                ConfigImport.device_id.in_(pool) if pool else ConfigImport.device_id == -1,
                ConfigImport.imported_at >= since,
            )
        )
    )
    by_rule = int(
        s.scalar(
            select(func.count())
            .select_from(NetworkMember)
            .join(Network, Network.id == NetworkMember.network_id)
            .where(
                Network.project_id == project_id,
                NetworkMember.join_source == "rule",
                NetworkMember.joined_at >= since,
                NetworkMember.excluded.is_(False),
            )
        )
        or 0
    )
    return {
        "devices": len(pool),
        "networks": int(
            s.scalar(select(func.count()).select_from(Network).where(Network.project_id == project_id)) or 0
        ),
        "in_several": sum(1 for d in pool if others.get(d, 0) >= 2),
        "only_default": sum(1 for d in pool if others.get(d, 0) == 0),
        "imported_today": len(today),
        "joined_by_rule_today": by_rule,
    }


def get_network(db_url: str, scope: Scope, ref: str | int) -> dict[str, Any]:
    with store.session(db_url) as s:
        n = _get(s, scope, ref)
        out = network_dict(s, n)
        out["rules"] = [
            _rule_dict(r)
            for r in s.scalars(select(NetworkRule).where(NetworkRule.network_id == n.id).order_by(NetworkRule.id))
        ]
        return out


# ---------------------------------------------------------------- 新建、修改、复制、删除


def create_network(db_url: str, scope: Scope, data: dict[str, Any], kb: Any = None) -> dict[str, Any]:
    """新建网络：name 必填；slug 不给时由名称生成；color 不给时按创建顺序自动分配；可以同时给 device_ids（加入方式
    manual，policy=pin 时固定在设备当前的最新版本）与 rules（[{kind, pattern}]，apply_existing 时把命中的设备加进来）。"""
    projects.require_write(scope)
    name = _validate_name(data.get("name"))
    with store.session(db_url) as s:
        ensure_default(s, scope.project_id)
        slug = _validate_slug(data["slug"]) if data.get("slug") else _free_slug(s, scope.project_id, name)
        if _slug_taken(s, scope.project_id, slug):
            raise _err("networks.slug_taken", "state", slug=slug)
        pos = int(s.scalar(select(func.max(Network.position)).where(Network.project_id == scope.project_id)) or 0) + 1
        n = Network(
            project_id=scope.project_id,
            slug=slug,
            name=name,
            description=str(data.get("description") or "")[:4000],
            color=_validate_color(data["color"]) if data.get("color") else _next_color(s, scope.project_id),
            folder_id=_folder(s, scope.project_id, data.get("folder_id")),
            position=pos,
            created_by=scope.identity.username[:200],
            last_activity={"actor": scope.identity.username, "action": "create", "at": iso(_now())},
            copied_from=data.get("_copied_from"),
        )
        s.add(n)
        s.flush()
        nid = int(n.id)
    if data.get("device_ids"):
        add_members(
            db_url,
            scope,
            nid,
            [int(x) for x in data["device_ids"]],
            data.get("policy") or "follow",
            source=str(data.get("_source") or "manual"),
        )
    for r in data.get("rules") or []:
        add_rule(db_url, scope, nid, r.get("kind"), r.get("pattern"), bool(r.get("apply_existing")), kb)
    _log.info("网络已创建：%s/%s（操作者 %s）", scope.slug, slug, scope.identity.username)
    return get_network(db_url, scope, nid)


def update_network(db_url: str, scope: Scope, ref: str | int, data: dict[str, Any]) -> dict[str, Any]:
    """改名称、标识、说明、颜色、文件夹、位置。默认网络可以改名，不能删除。"""
    projects.require_write(scope)
    with store.session(db_url) as s:
        n = _get(s, scope, ref)
        if data.get("name") is not None:
            n.name = _validate_name(data["name"])
        if data.get("slug"):
            slug = _validate_slug(data["slug"])
            if _slug_taken(s, scope.project_id, slug, ignore=n.id):
                raise _err("networks.slug_taken", "state", slug=slug)
            n.slug = slug
        if data.get("description") is not None:
            n.description = str(data["description"])[:4000]
        if data.get("color"):
            n.color = _validate_color(data["color"])
        if "folder_id" in data:
            n.folder_id = _folder(s, scope.project_id, data.get("folder_id"))
        if data.get("position") is not None:
            n.position = int(data["position"])
        n.updated_at = _now()
        s.flush()
        nid = int(n.id)
    return get_network(db_url, scope, nid)


def _work_counts(s: Any, nid: int) -> dict[str, int]:
    cps = list(s.scalars(select(CheckProject.id).where(CheckProject.network_id == nid)))
    sids = list(s.scalars(select(CheckScript.id).where(CheckScript.project_id.in_(cps)))) if cps else []
    revs = (
        int(s.scalar(select(func.count()).select_from(CheckRevision).where(CheckRevision.script_id.in_(sids))) or 0)
        if sids
        else 0
    )
    return {
        "members": int(
            s.scalar(
                select(func.count())
                .select_from(NetworkMember)
                .where(NetworkMember.network_id == nid, NetworkMember.excluded.is_(False))
            )
            or 0
        ),
        "rules": int(s.scalar(select(func.count()).select_from(NetworkRule).where(NetworkRule.network_id == nid)) or 0),
        "annotations": _count(s, ViewAnnotation, nid),
        "ignores": _count(s, CheckIgnore, nid),
        "overrides": _count(s, ProjectRuleOverride, nid),
        "check_groups": len(cps),
        "scripts": len(sids),
        "revisions": revs,
        "ai_batches": _count(s, AISuggestionBatch, nid),
        "ai_suggestions": _count(s, AISuggestion, nid),
        "ai_adopted": int(
            s.scalar(
                select(func.count())
                .select_from(AISuggestion)
                .where(AISuggestion.network_id == nid, AISuggestion.status.in_(("adopted", "reverted")))
            )
            or 0
        ),
    }


def delete_preview(db_url: str, scope: Scope, ref: str | int) -> dict[str, Any]:
    """删除网络会一起删除的工作数据（设备不删）。"""
    with store.session(db_url) as s:
        n = _get(s, scope, ref)
        return {"network": brief(n), "deletable": not n.is_default, "counts": _work_counts(s, n.id)}


def delete_network(db_url: str, scope: Scope, ref: str | int, confirm: str | None) -> dict[str, Any]:
    """删除网络与它的工作数据（不进回收站，不删设备）；confirm 必须等于网络名称（或标识）。默认网络不能删除。"""
    projects.require_write(scope)
    info = delete_preview(db_url, scope, ref)
    with store.session(db_url) as s:
        n = _get(s, scope, ref)
        if n.is_default:
            raise _err("networks.default_undeletable", "state")
        if confirm is None or str(confirm).strip() not in (n.name, n.slug):
            raise _err("networks.confirm_mismatch", name=n.name)
        nid = int(n.id)
        cps = list(s.scalars(select(CheckProject.id).where(CheckProject.network_id == nid)))
        if cps:
            sids = list(s.scalars(select(CheckScript.id).where(CheckScript.project_id.in_(cps))))
            if sids:
                s.execute(delete(CheckRevision).where(CheckRevision.script_id.in_(sids)))
                s.execute(delete(CheckScript).where(CheckScript.id.in_(sids)))
            s.execute(delete(CheckProject).where(CheckProject.id.in_(cps)))
        s.execute(delete(ViewAnnotation).where(ViewAnnotation.network_id == nid))
        s.execute(delete(AISuggestion).where(AISuggestion.network_id == nid))
        s.execute(delete(AISuggestionBatch).where(AISuggestionBatch.network_id == nid))
        for model in (CheckIgnore, ProjectRuleOverride, NetworkMember, NetworkRule):
            s.execute(delete(model).where(model.network_id == nid))  # type: ignore[attr-defined]
        s.execute(delete(Network).where(Network.id == nid))
    from lmesh.core import script_check

    script_check.clear_cache()
    _log.info("网络已删除：%s/%s（操作者 %s）", scope.slug, info["network"]["slug"], scope.identity.username)
    return {"deleted": True, **info}


def copy_network(db_url: str, scope: Scope, ref: str | int, data: dict[str, Any]) -> dict[str, Any]:
    """复制网络（连同工作数据）：成员与版本选择、自动加入规则、排除、视图标注、检查忽略、规则调整、脚本组与脚本（含修订）、
    已采纳（与已撤销）的 AI 建议与采纳记录（注明复制自）；不复制待处理与已忽略的建议。设备不复制。"""
    projects.require_write(scope)
    with store.session(db_url) as s:
        src = _get(s, scope, ref)
        if src.is_default:
            _sync_default(s, src)
        src_info = {"network_id": src.id, "slug": src.slug, "name": src.name, "at": iso(_now())}
        sid = int(src.id)
        folder = src.folder_id
    created = create_network(
        db_url,
        scope,
        {
            "name": data.get("name") or f"{src_info['name']} copy",
            "slug": data.get("slug"),
            "description": data.get("description"),
            "color": data.get("color"),
            "folder_id": data.get("folder_id", folder),
            "_copied_from": src_info,
        },
    )
    nid = int(created["id"])
    copied = copy_work_data(db_url, sid, nid, scope.identity.username, src_info)
    out = get_network(db_url, scope, nid)
    out["copied"] = copied
    return out


def copy_work_data(
    db_url: str, src_id: int, dst_id: int, actor: str, note: dict[str, Any], id_map: dict[int, int] | None = None
) -> dict[str, int]:
    """把一个网络的工作数据复制到另一个网络（同项目时 id_map 为空；复制项目时 id_map 是设备对应关系）。"""
    dmap = id_map
    counts = {"members": 0, "rules": 0, "annotations": 0, "ignores": 0, "overrides": 0, "scripts": 0, "ai_adopted": 0}

    def dev(d: int | None) -> int | None:
        if d is None:
            return None
        return d if dmap is None else dmap.get(d)

    with store.session(db_url) as s:
        dst = s.get(Network, dst_id)
        assert dst is not None
        rule_map: dict[int, int] = {}
        for r in s.scalars(select(NetworkRule).where(NetworkRule.network_id == src_id).order_by(NetworkRule.id)):
            nr = NetworkRule(
                network_id=dst_id, kind=r.kind, pattern=r.pattern, enabled=r.enabled, created_by=actor[:200]
            )
            s.add(nr)
            s.flush()
            rule_map[r.id] = nr.id
            counts["rules"] += 1
        have = {m.device_id: m for m in s.scalars(select(NetworkMember).where(NetworkMember.network_id == dst_id))}
        for m in s.scalars(select(NetworkMember).where(NetworkMember.network_id == src_id)):
            d = dev(m.device_id)
            if d is None:
                continue
            same = d == m.device_id
            row = have.get(d)
            if row is None:
                row = NetworkMember(network_id=dst_id, device_id=d)
                s.add(row)
            row.version_id = m.version_id if same else None
            row.excluded, row.join_source = m.excluded, "copy"
            row.rule_id = rule_map.get(m.rule_id or 0)
            row.joined_by, row.joined_at = actor[:200], _now()
            counts["members"] += 0 if m.excluded else 1
        s.flush()
        for o in s.scalars(select(ProjectRuleOverride).where(ProjectRuleOverride.network_id == src_id)):
            s.add(
                ProjectRuleOverride(
                    project_id=dst.project_id,
                    network_id=dst_id,
                    rule=o.rule,
                    enabled=o.enabled,
                    severity=o.severity,
                    reason=o.reason,
                    updated_by=actor[:200],
                )
            )
            counts["overrides"] += 1
        for ig in s.scalars(select(CheckIgnore).where(CheckIgnore.network_id == src_id)):
            d = dev(ig.device_id)
            if d is None:
                continue
            s.add(
                CheckIgnore(
                    project_id=dst.project_id,
                    network_id=dst_id,
                    device_id=d,
                    rule=ig.rule,
                    node=ig.node,
                    reason=ig.reason,
                )
            )
            counts["ignores"] += 1
        # AI：只复制已采纳（与已撤销）的建议与采纳记录，批次一并复制（建议引用的事实在批次里）
        sugg_map: dict[int, int] = {}
        batch_map: dict[int, int] = {}
        rows = list(
            s.scalars(
                select(AISuggestion)
                .where(AISuggestion.network_id == src_id, AISuggestion.status.in_(("adopted", "reverted")))
                .order_by(AISuggestion.id)
            )
        )
        if dmap is None:
            for sg in rows:
                if sg.batch_id not in batch_map:
                    b = s.get(AISuggestionBatch, sg.batch_id)
                    assert b is not None
                    nb = AISuggestionBatch(
                        **{
                            c: getattr(b, c)
                            for c in _cols(AISuggestionBatch)
                            if c not in ("id", "network_id", "project_id")
                        },
                        project_id=dst.project_id,
                        network_id=dst_id,
                    )
                    nb.params = {**(b.params or {}), "copied_from": {**note, "batch_id": b.id}}
                    s.add(nb)
                    s.flush()
                    batch_map[sg.batch_id] = nb.id
                ns = AISuggestion(
                    **{
                        c: getattr(sg, c)
                        for c in _cols(AISuggestion)
                        if c not in ("id", "network_id", "project_id", "batch_id")
                    },
                    project_id=dst.project_id,
                    network_id=dst_id,
                    batch_id=batch_map[sg.batch_id],
                )
                ns.note = (f"复制自 {note.get('name')}（#{sg.id}）" + (f"；{sg.note}" if sg.note else ""))[:4000]
                ns.adopt_info = {**(sg.adopt_info or {}), "copied_from": {**note, "suggestion_id": sg.id}}
                s.add(ns)
                s.flush()
                sugg_map[sg.id] = ns.id
                counts["ai_adopted"] += 1
        for a in s.scalars(select(ViewAnnotation).where(ViewAnnotation.network_id == src_id)):
            target = a.target
            if dmap is not None and a.target_type == "device":
                d = dev(int(a.target)) if a.target.isdigit() else None
                if d is None:
                    continue
                target = str(d)
            elif dmap is not None:
                continue
            s.add(
                ViewAnnotation(
                    project_id=dst.project_id,
                    network_id=dst_id,
                    target_type=a.target_type,
                    target=target,
                    key=a.key,
                    value=a.value,
                    source=a.source,
                    suggestion_id=sugg_map.get(a.suggestion_id or 0),
                    updated_by=actor[:200],
                )
            )
            counts["annotations"] += 1
        # 脚本组、脚本与全部修订
        for cp in s.scalars(select(CheckProject).where(CheckProject.network_id == src_id).order_by(CheckProject.id)):
            nd = dev(cp.device_id)
            ncp = CheckProject(
                **{
                    c: getattr(cp, c)
                    for c in _cols(CheckProject)
                    if c not in ("id", "network_id", "project_id", "device_id", "version_id")
                },
                project_id=dst.project_id,
                network_id=dst_id,
                device_id=nd,
                version_id=cp.version_id if nd is not None and nd == cp.device_id else None,
            )
            s.add(ncp)
            s.flush()
            for sc in s.scalars(select(CheckScript).where(CheckScript.project_id == cp.id).order_by(CheckScript.id)):
                ns2 = CheckScript(
                    **{c: getattr(sc, c) for c in _cols(CheckScript) if c not in ("id", "project_id")},
                    project_id=ncp.id,
                )
                s.add(ns2)
                s.flush()
                for rv in s.scalars(
                    select(CheckRevision).where(CheckRevision.script_id == sc.id).order_by(CheckRevision.seq)
                ):
                    s.add(
                        CheckRevision(
                            **{c: getattr(rv, c) for c in _cols(CheckRevision) if c not in ("id", "script_id")},
                            script_id=ns2.id,
                        )
                    )
                counts["scripts"] += 1
    return counts


def _cols(model: Any) -> list[str]:
    return [c.key for c in model.__table__.columns]


def copy_project_networks(
    db_url: str, src_pid: int, dst_pid: int, id_map: dict[int, int], actor: str
) -> dict[int, int]:
    """复制项目时复制网络（M9）：文件夹、网络（默认网络对应默认网络）、成员（按设备对应关系）、自动加入规则、标注、忽略；
    规则调整与脚本由 projects.copy_project 按返回的网络对应关系复制。返回 {源网络: 目标网络}。"""
    net_map: dict[int, int] = {}
    with store.session(db_url) as s:
        ensure_default(s, src_pid)
        dst_default = ensure_default(s, dst_pid)
        fmap: dict[int, int] = {}
        for f in s.scalars(select(NetworkFolder).where(NetworkFolder.project_id == src_pid).order_by(NetworkFolder.id)):
            nf = NetworkFolder(project_id=dst_pid, name=f.name, position=f.position)
            s.add(nf)
            s.flush()
            fmap[f.id] = nf.id
        srcs = list(s.scalars(select(Network).where(Network.project_id == src_pid).order_by(Network.id)))
        for n in srcs:
            if n.is_default:
                dst_default.name, dst_default.color = n.name, n.color
                net_map[n.id] = dst_default.id
                continue
            nn = Network(
                project_id=dst_pid,
                slug=_free_slug(s, dst_pid, n.slug),
                name=n.name,
                description=n.description,
                color=n.color,
                folder_id=fmap.get(n.folder_id or 0),
                position=n.position,
                created_by=actor[:200],
                copied_from={"network_id": n.id, "slug": n.slug, "name": n.name, "at": iso(_now())},
            )
            s.add(nn)
            s.flush()
            net_map[n.id] = nn.id
        pairs = [(n.id, net_map[n.id], n.slug, n.name) for n in srcs]
    for sid, did, slug, name in pairs:
        note = {"network_id": sid, "slug": slug, "name": name}
        _copy_for_project(db_url, sid, did, actor, note, id_map)
    return net_map


def _copy_for_project(
    db_url: str, sid: int, did: int, actor: str, note: dict[str, Any], id_map: dict[int, int]
) -> None:
    """复制项目时的网络工作数据：成员、规则、标注、忽略（规则调整与脚本由 copy_project 复制，AI 记录不复制）。"""
    with store.session(db_url) as s:
        dst = s.get(Network, did)
        assert dst is not None
        rule_map: dict[int, int] = {}
        for r in s.scalars(select(NetworkRule).where(NetworkRule.network_id == sid).order_by(NetworkRule.id)):
            nr = NetworkRule(network_id=did, kind=r.kind, pattern=r.pattern, enabled=r.enabled, created_by=actor[:200])
            s.add(nr)
            s.flush()
            rule_map[r.id] = nr.id
        have = {m.device_id: m for m in s.scalars(select(NetworkMember).where(NetworkMember.network_id == did))}
        for m in s.scalars(select(NetworkMember).where(NetworkMember.network_id == sid)):
            d = id_map.get(m.device_id)
            if d is None:
                continue
            row = have.get(d)
            if row is None:
                row = NetworkMember(network_id=did, device_id=d)
                s.add(row)
            row.version_id = m.version_id if d == m.device_id else None
            row.excluded, row.join_source, row.rule_id = m.excluded, "copy", rule_map.get(m.rule_id or 0)
            row.joined_by = actor[:200]
        for ig in s.scalars(select(CheckIgnore).where(CheckIgnore.network_id == sid)):
            d = id_map.get(ig.device_id)
            if d is not None:
                s.add(
                    CheckIgnore(
                        project_id=dst.project_id,
                        network_id=did,
                        device_id=d,
                        rule=ig.rule,
                        node=ig.node,
                        reason=ig.reason,
                    )
                )
        for a in s.scalars(
            select(ViewAnnotation).where(ViewAnnotation.network_id == sid, ViewAnnotation.target_type == "device")
        ):
            d = id_map.get(int(a.target)) if a.target.isdigit() else None
            if d is not None:
                s.add(
                    ViewAnnotation(
                        project_id=dst.project_id,
                        network_id=did,
                        target_type="device",
                        target=str(d),
                        key=a.key,
                        value=a.value,
                        source=a.source,
                        suggestion_id=None,
                        updated_by=actor[:200],
                    )
                )


# ---------------------------------------------------------------- 文件夹


def _folder_dict(f: NetworkFolder) -> dict[str, Any]:
    return {"id": f.id, "name": f.name, "position": f.position, "created_at": iso(f.created_at)}


def create_folder(db_url: str, scope: Scope, name: Any) -> dict[str, Any]:
    projects.require_write(scope)
    nm = _validate_name(name)
    with store.session(db_url) as s:
        pos = int(
            s.scalar(select(func.max(NetworkFolder.position)).where(NetworkFolder.project_id == scope.project_id)) or 0
        )
        f = NetworkFolder(project_id=scope.project_id, name=nm, position=pos + 1)
        s.add(f)
        s.flush()
        return _folder_dict(f)


def update_folder(db_url: str, scope: Scope, folder_id: int, data: dict[str, Any]) -> dict[str, Any]:
    projects.require_write(scope)
    with store.session(db_url) as s:
        f = s.get(NetworkFolder, _folder(s, scope.project_id, folder_id))
        assert f is not None
        if data.get("name") is not None:
            f.name = _validate_name(data["name"])
        if data.get("position") is not None:
            f.position = int(data["position"])
        s.flush()
        return _folder_dict(f)


def delete_folder(db_url: str, scope: Scope, folder_id: int) -> dict[str, Any]:
    """只删文件夹，里面的网络移到最外层。"""
    projects.require_write(scope)
    with store.session(db_url) as s:
        fid = _folder(s, scope.project_id, folder_id)
        moved = [n.slug for n in s.scalars(select(Network).where(Network.folder_id == fid))]
        s.execute(update(Network).where(Network.folder_id == fid).values(folder_id=None))
        s.execute(delete(NetworkFolder).where(NetworkFolder.id == fid))
        return {"deleted": True, "id": fid, "moved": moved}


# ---------------------------------------------------------------- 成员


def _versions(s: Any, device_id: int) -> list[int]:
    return list(
        s.scalars(select(ConfigVersion.id).where(ConfigVersion.device_id == device_id).order_by(ConfigVersion.id))
    )


def list_members(db_url: str, scope: Scope, ref: str | int, kb: Any = None) -> dict[str, Any]:
    """网络的成员：设备、本网络用的版本（跟随最新 / 固定，固定时是否有更新的版本）、还在哪些网络、怎么加入的、
    管理地址（给出知识库时）。"""
    with store.session(db_url) as s:
        n = _get(s, scope, ref)
        nid = int(n.id)
        rows = _members(s, n)
        nets = networks_of_devices(s, scope.project_id)
        refs = {
            int(r.device_id): r.version_id
            for r in s.scalars(select(ProjectDeviceRef).where(ProjectDeviceRef.project_id == scope.project_id))
        }
        rules = {r.id: r for r in s.scalars(select(NetworkRule).where(NetworkRule.network_id == nid))}
        out: list[dict[str, Any]] = []
        for m in rows:
            d = s.get(Device, m.device_id)
            if d is None:
                continue
            vers = _versions(s, d.id)
            latest = refs.get(d.id) or (vers[-1] if vers else None)  # 项目里的当前版本（引用固定时为固定的版本）
            used = m.version_id or latest
            r = rules.get(m.rule_id or 0)
            out.append(
                {
                    "device_id": d.id,
                    "name": d.name,
                    "vendor": d.vendor,
                    "platform": d.platform,
                    "profile": d.profile,
                    "source": "private" if d.project_id is not None else "public",
                    "versions": len(vers),
                    "latest_version_id": latest,
                    "latest_seq": vers.index(latest) + 1 if latest in vers else None,
                    "policy": "pin" if m.version_id else "follow",
                    "version_id": used,
                    "seq": vers.index(used) + 1 if used in vers else None,
                    "newer_available": bool(m.version_id and latest and latest != m.version_id),
                    "also_in": [x for x in nets.get(d.id, []) if x["id"] != nid],
                    "join_source": m.join_source,
                    "rule": _rule_dict(r) if r is not None else None,
                    "joined_by": m.joined_by,
                    "joined_at": iso(m.joined_at),
                }
            )
        net = brief(n)
    if kb is not None and out:
        mg = mgmt_addresses(db_url, [int(x["device_id"]) for x in out], kb)
        for x in out:
            x["mgmt_address"] = (mg.get(x["device_id"]) or {}).get("address")
    return {"network": net, "members": out, "total": len(out)}


def _pool_device(s: Any, project_id: int, device_id: int) -> Device:
    d = s.get(Device, device_id)
    if d is None or device_id not in set(project_device_ids(s, project_id)):
        raise _err("networks.device_not_found", "not_found", device=device_id)
    return d  # type: ignore[no-any-return]


def add_members(
    db_url: str, scope: Scope, ref: str | int, device_ids: list[int], policy: str = "follow", source: str = "manual"
) -> dict[str, Any]:
    """从项目设备池添加设备（手工加入会清除排除标记）。policy：follow 跟随最新 / pin 固定在设备当前的最新版本。"""
    projects.require_write(scope)
    if policy not in ("follow", "pin"):
        raise _err("networks.bad_policy", policy=policy)
    added, already = [], []
    with store.session(db_url) as s:
        n = _get(s, scope, ref)
        for did in dict.fromkeys(int(x) for x in device_ids):
            d = _pool_device(s, scope.project_id, did)
            if _join(s, n, did, source, None, scope.identity.username, force=True):
                added.append({"id": d.id, "name": d.name})
            else:
                already.append({"id": d.id, "name": d.name})
            if policy == "pin":
                m = s.scalar(
                    select(NetworkMember).where(NetworkMember.network_id == n.id, NetworkMember.device_id == did)
                )
                ref_v = s.scalar(
                    select(ProjectDeviceRef.version_id).where(
                        ProjectDeviceRef.project_id == scope.project_id, ProjectDeviceRef.device_id == did
                    )
                )
                vers = _versions(s, did)
                if m is not None:
                    m.version_id = ref_v or (vers[-1] if vers else None)
        nid = int(n.id)
    touch(db_url, scope, nid, "members.add")
    return {"added": added, "already": already}


def set_policy(
    db_url: str, scope: Scope, ref: str | int, device_ids: list[int], policy: str, version_id: int | None = None
) -> dict[str, Any]:
    """改版本策略（可批量）：follow 跟随最新；pin 固定（version_id 给出时固定到该版本，只能单台；不给时固定在当前最新）。"""
    projects.require_write(scope)
    if policy not in ("follow", "pin"):
        raise _err("networks.bad_policy", policy=policy)
    if version_id is not None and len(device_ids) != 1:
        raise _err("networks.version_needs_one_device")
    updated = []
    with store.session(db_url) as s:
        n = _get(s, scope, ref)
        for did in dict.fromkeys(int(x) for x in device_ids):
            m = s.scalar(
                select(NetworkMember).where(
                    NetworkMember.network_id == n.id, NetworkMember.device_id == did, NetworkMember.excluded.is_(False)
                )
            )
            if m is None:
                raise _err("networks.member_not_found", "not_found", device=did)
            vers = _versions(s, did)
            if policy == "follow":
                m.version_id = None
            elif version_id is not None:
                if version_id not in vers:
                    raise _err("networks.version_not_found", "not_found", version=version_id)
                m.version_id = version_id
            else:
                ref_v = s.scalar(
                    select(ProjectDeviceRef.version_id).where(
                        ProjectDeviceRef.project_id == scope.project_id, ProjectDeviceRef.device_id == did
                    )
                )
                m.version_id = ref_v or (vers[-1] if vers else None)
            updated.append(
                {
                    "device_id": did,
                    "policy": "pin" if m.version_id else "follow",
                    "version_id": m.version_id,
                    "seq": vers.index(m.version_id) + 1 if m.version_id in vers else None,
                }
            )
        nid = int(n.id)
    from lmesh.core import script_check

    script_check.clear_cache()
    touch(db_url, scope, nid, "members.policy")
    return {"updated": updated}


def remove_members(db_url: str, scope: Scope, ref: str | int, device_ids: list[int]) -> dict[str, Any]:
    """移出网络（可批量）：设备本身、版本历史与它在其他网络里的数据都不变；记为排除，之后的导入不会再按规则加入。
    默认网络始终包含全部设备，不能移出。"""
    projects.require_write(scope)
    removed = []
    with store.session(db_url) as s:
        n = _get(s, scope, ref)
        if n.is_default:
            raise _err("networks.default_all_devices", "state")
        for did in dict.fromkeys(int(x) for x in device_ids):
            m = s.scalar(
                select(NetworkMember).where(
                    NetworkMember.network_id == n.id, NetworkMember.device_id == did, NetworkMember.excluded.is_(False)
                )
            )
            if m is None:
                raise _err("networks.member_not_found", "not_found", device=did)
            m.excluded, m.version_id = True, None
            m.joined_by, m.joined_at = scope.identity.username[:200], _now()
            removed.append(did)
        nid = int(n.id)
    touch(db_url, scope, nid, "members.remove")
    return {"removed": removed, "excluded": removed}


def unexclude(db_url: str, scope: Scope, ref: str | int, device_ids: list[int]) -> dict[str, Any]:
    """撤销排除（不加入，只让自动加入规则以后可以再加入它）。"""
    projects.require_write(scope)
    with store.session(db_url) as s:
        n = _get(s, scope, ref)
        q = delete(NetworkMember).where(
            NetworkMember.network_id == n.id, NetworkMember.device_id.in_(device_ids), NetworkMember.excluded.is_(True)
        )
        cnt = s.execute(q).rowcount  # type: ignore[attr-defined]
    return {"cleared": int(cnt or 0)}


# ---------------------------------------------------------------- 活动与检查结果


def touch(db_url: str, scope: Scope, network_id: int | None, action: str) -> None:
    """记录网络的最近活动（写操作）。"""
    if network_id is None:
        return
    with store.session(db_url) as s:
        n = s.get(Network, network_id)
        if n is not None:
            n.last_activity = {"actor": scope.identity.username, "action": action, "at": iso(_now())}
            n.updated_at = _now()


def record_check(db_url: str, device_id: int, version_id: int | None, summary: dict[str, Any]) -> None:
    """记下当前网络里一台设备最近的检查结果（网络汇总页用）：{error, warning, info, version_id, at}。"""
    sc = projects.current()
    if sc is None or sc.network_id is None:
        return
    by = summary.get("by_severity") or summary
    with store.session(db_url) as s:
        n = s.get(Network, sc.network_id)
        if n is None:
            return
        stats = dict(n.stats or {})
        checks = dict(stats.get("checks") or {})
        checks[str(device_id)] = {
            "error": int(by.get("error") or 0),
            "warning": int(by.get("warning") or 0),
            "info": int(by.get("info") or 0),
            "version_id": version_id,
            "at": iso(_now()),
        }
        stats["checks"] = checks
        n.stats = stats


# ---------------------------------------------------------------- 建网建议


def _project_scope(db_url: str, scope: Scope) -> Scope:
    """建议在整个项目设备池上计算：同一项目的默认网络。"""
    return projects.with_network(db_url, scope, None)


def _topo(db_url: str, scope: Scope, kb: Any) -> Any:
    from lmesh.core import topology

    with projects.use(_project_scope(db_url, scope), scope.identity):
        devices, _ = topology.from_db(db_url, kb, None)
    return topology.build(devices, kb) if devices else None


def _is_mgmt_iface(f: Any, name: str | None) -> bool:
    if not name:
        return False
    itf = f.ifaces.get(name)
    if itf is None:
        return bool(_MGMT_IF.match(name))
    return bool(_MGMT_IF.match(itf.name) or (itf.vrf and _MGMT_VRF.search(itf.vrf)))


def _groups_components(topo: Any, params: dict[str, Any]) -> list[dict[str, Any]]:
    ignore_mgmt = str(params.get("ignore_mgmt", "true")).lower() not in ("0", "false", "no")
    ids = {d.name: d.device_id for d in topo.devices}
    adj: dict[str, set[str]] = {d.name: set() for d in topo.devices}
    for lk in topo.links:
        if lk["type"] != "subnet":
            continue
        a, b = lk["a"], lk["b"]
        if ignore_mgmt and (
            _is_mgmt_iface(topo.facts[a["device"]], a.get("interface"))
            or _is_mgmt_iface(topo.facts[b["device"]], b.get("interface"))
        ):
            continue
        adj[a["device"]].add(b["device"])
        adj[b["device"]].add(a["device"])
    seen: set[str] = set()
    comps = []
    for name in sorted(adj):
        if name in seen:
            continue
        stack, comp = [name], []
        seen.add(name)
        while stack:
            x = stack.pop()
            comp.append(x)
            for y in adj[x]:
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        comps.append(sorted(comp))
    comps.sort(key=lambda c: (-len(c), c[0]))
    out = []
    for i, c in enumerate(comps, 1):
        label = c[0] if len(c) == 1 else f"{c[0]} …"
        out.append(
            {
                "key": f"component-{i}",
                "name": f"连通分量 {i}（{label}）",
                "slug": f"component-{i}",
                "ids": [ids[x] for x in c],
            }
        )
    return out


def _groups_igp(topo: Any, params: dict[str, Any]) -> list[dict[str, Any]]:
    proto = str(params.get("protocol") or "all").lower()
    groups: dict[str, set[int]] = defaultdict(set)
    for d in topo.devices:
        f = topo.facts[d.name]
        for itf in f.ifaces.values():
            if itf.vrf:
                continue
            if proto in ("all", "isis"):
                x = f.isis(itf)
                if x is not None:
                    groups[f"isis:{x['process'] or '-'}"].add(d.device_id)
            if proto in ("all", "ospf"):
                o = f.ospf(itf)
                if o is not None:
                    groups[f"ospf:{o['process'] or '-'}:{o['area']}"].add(d.device_id)
    out = []
    for key in sorted(groups):
        parts = key.split(":")
        if parts[0] == "isis":
            name, slug = f"IS-IS {parts[1]}", f"isis-{parts[1]}"
        else:
            name, slug = f"OSPF {parts[1]} 区域 {parts[2]}", f"ospf-{parts[1]}-area-{parts[2]}"
        out.append({"key": key, "name": name, "slug": slug, "ids": sorted(groups[key])})
    return out


def _groups_bgp(topo: Any, params: dict[str, Any]) -> list[dict[str, Any]]:
    from lmesh.core import topology

    groups: dict[str, set[int]] = defaultdict(set)
    for d in topo.devices:
        asn = topology._local_as(topo.facts[d.name])
        if asn:
            groups[str(asn)].add(d.device_id)
    return [
        {"key": f"as:{a}", "name": f"AS {a}", "slug": f"as-{a}", "ids": sorted(v)} for a, v in sorted(groups.items())
    ]


def _groups_name(names: dict[int, str], params: dict[str, Any]) -> list[dict[str, Any]]:
    pattern = str(params.get("regex") or DEFAULT_NAME_REGEX)
    try:
        rx = re.compile(pattern)
    except re.error as e:
        raise _err("networks.bad_regex", regex=pattern) from e
    groups: dict[str, set[int]] = defaultdict(set)
    for did, nm in names.items():
        m = rx.search(nm)
        if m is None:
            continue
        key = m.group(1) if m.groups() else m.group(0)
        if key:
            groups[key].add(did)
    return [
        {"key": f"name:{k}", "name": k, "slug": k, "ids": sorted(v), "rule": {"kind": "name", "pattern": f"{k}-*"}}
        for k, v in sorted(groups.items())
    ]


def _groups_subnet(mgmt: dict[int, dict[str, Any] | None], params: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        plen = int(params.get("prefix") or 24)
    except ValueError as e:
        raise _err("networks.bad_prefix", prefix=str(params.get("prefix"))) from e
    if not 8 <= plen <= 32:
        raise _err("networks.bad_prefix", prefix=str(plen))
    groups: dict[str, set[int]] = defaultdict(set)
    for did, m in mgmt.items():
        if m and m.get("address"):
            net = ipaddress.ip_network(f"{m['address']}/{plen}", strict=False)
            groups[str(net)].add(did)
    return [
        {
            "key": f"subnet:{k}",
            "name": f"管理网段 {k}",
            "slug": "mgmt-" + k.replace(".", "-").replace("/", "-"),
            "ids": sorted(v),
            "rule": {"kind": "subnet", "pattern": k},
        }
        for k, v in sorted(groups.items(), key=lambda kv: ipaddress.ip_network(kv[0]))
    ]


def _groups_ai(db_url: str, scope: Scope, topo: Any, pool: set[int]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """AI 拓扑整理（M8 topology-roles）已采纳的分组：本网络（不带网络时为默认网络）的视图标注 group，来源 ai。
    代码校验：设备都在项目里、组内按同网段链路互相连通。"""
    nid = scope.network_id
    with store.session(db_url) as s:
        rows = list(
            s.scalars(
                select(ViewAnnotation).where(
                    ViewAnnotation.network_id == nid,
                    ViewAnnotation.key == "group",
                    ViewAnnotation.target_type == "device",
                    ViewAnnotation.source == "ai",
                )
            )
        )
        sugg = {r.suggestion_id: s.get(AISuggestion, r.suggestion_id) for r in rows if r.suggestion_id is not None}
        batch = s.scalar(
            select(AISuggestionBatch)
            .where(AISuggestionBatch.network_id == nid, AISuggestionBatch.skill == "topology-roles")
            .order_by(AISuggestionBatch.id.desc())
            .limit(1)
        )
        source = (
            {"batch_id": batch.id, "at": iso(batch.created_at), "model": batch.model, "status": batch.status}
            if batch is not None
            else None
        )
    groups: dict[str, set[int]] = defaultdict(set)
    refs: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        if str(r.target).isdigit() and isinstance(r.value, str):
            groups[r.value].add(int(r.target))
            if r.suggestion_id in sugg:
                refs[r.value].append(int(r.suggestion_id))
    adj: dict[int, set[int]] = defaultdict(set)
    if topo is not None:
        by_name = {d.name: d.device_id for d in topo.devices}
        for lk in topo.links:
            if lk["type"] == "subnet":
                a, b = by_name.get(lk["a"]["device"]), by_name.get(lk["b"]["device"])
                if a is not None and b is not None:
                    adj[a].add(b)
                    adj[b].add(a)
    out = []
    for i, (g, ids) in enumerate(sorted(groups.items()), 1):
        reasons = []
        missing = sorted(d for d in ids if d not in pool)
        if missing:
            reasons.append({"code": "device_not_in_project", "devices": missing})
        present = [d for d in ids if d in pool]
        if len(present) > 1:
            seen, stack = {present[0]}, [present[0]]
            while stack:
                x = stack.pop()
                for y in adj[x]:
                    if y in ids and y not in seen:
                        seen.add(y)
                        stack.append(y)
            if len(seen) < len(present):
                reasons.append({"code": "not_connected", "devices": sorted(set(present) - seen)})
        out.append(
            {
                "key": f"ai:{g}",
                "name": g,
                "slug": f"ai-{i}",
                "ids": sorted(present),
                "suggestion_ids": sorted(refs.get(g, [])),
                "check": {"status": "reject" if reasons else "pass", "reasons": reasons},
            }
        )
    return out, {"source": source}


def suggest(
    db_url: str, scope: Scope, basis: str, params: dict[str, Any] | None = None, kb: Any = None
) -> dict[str, Any]:
    """建网建议（代码计算，不入库）：按依据把项目设备池分组，每个建议给出设备、设备数、和现有网络重叠的设备、
    与现有网络完全相同的标出、和其他建议重叠的设备；name / subnet 依据给出可作自动加入规则的 rule；
    ai 依据的分组带代码校验结果（check），不通过的不能采纳。"""
    from lmesh.core import ai

    params = dict(params or {})
    if basis not in BASES:
        raise _err("networks.bad_basis", basis=basis, allowed=", ".join(BASES))
    with store.session(db_url) as s:
        ensure_default(s, scope.project_id)
        pool_ids = project_device_ids(s, scope.project_id)
        names = {int(i): str(n) for i, n in s.execute(select(Device.id, Device.name).where(Device.id.in_(pool_ids)))}
        existing = {}
        for n in s.scalars(select(Network).where(Network.project_id == scope.project_id).order_by(Network.id)):
            existing[n.id] = (brief(n), {m.device_id for m in _members(s, n)})
    pool = set(pool_ids)
    extra: dict[str, Any] = {}
    if basis == "name":
        groups = _groups_name(names, params)
    elif kb is None:
        raise _err("networks.need_kb", "state")
    elif basis == "subnet":
        with projects.use(_project_scope(db_url, scope), scope.identity):
            groups = _groups_subnet(mgmt_addresses(db_url, pool_ids, kb), params)
    else:
        topo = _topo(db_url, scope, kb)
        if basis == "ai":
            groups, extra = _groups_ai(db_url, scope, topo, pool)
            extra["ai_configured"] = ai.is_configured(_settings())
        elif topo is None:
            groups = []
        elif basis == "components":
            groups = _groups_components(topo, params)
        elif basis == "igp":
            groups = _groups_igp(topo, params)
        else:
            groups = _groups_bgp(topo, params)
    groups = groups[:MAX_SUGGESTIONS]
    member_of: dict[int, list[str]] = defaultdict(list)
    for g in groups:
        for d in g["ids"]:
            member_of[d].append(g["key"])
    out = []
    for g in groups:
        ids = set(g["ids"])
        overlaps = []
        same_as = None
        for _nid, (b, mem) in existing.items():
            inter = ids & mem
            if mem == ids and ids:
                same_as = b
            if inter and not b["default"]:
                overlaps.append({**b, "devices": len(inter)})
        other = sorted({k for d in ids for k in member_of[d] if k != g["key"]})
        chk = g.get("check") or {"status": "pass", "reasons": []}
        out.append(
            {
                "key": g["key"],
                "name": g["name"],
                "slug": g["slug"],
                "devices": [
                    {"id": d, "name": names.get(d, str(d))} for d in sorted(ids, key=lambda x: names.get(x, ""))
                ],
                "count": len(ids),
                "overlap_existing": overlaps,
                "same_as": same_as,
                "overlap_suggestions": other,
                "overlap_devices": sorted(d for d in ids if len(member_of[d]) > 1),
                "rule": g.get("rule"),
                "suggestion_ids": g.get("suggestion_ids"),
                "check": chk,
                "adoptable": chk["status"] != "reject" and same_as is None and bool(ids),
            }
        )
    return {"basis": basis, "params": params, "suggestions": out, "total": len(out), "devices": len(pool), **extra}


def _settings() -> Any:
    from lmesh.core import config

    return config.load()


def adopt(
    db_url: str,
    scope: Scope,
    basis: str,
    params: dict[str, Any] | None = None,
    keys: list[str] | None = None,
    kb: Any = None,
    with_rules: bool = False,
    folder_id: int | None = None,
    names: dict[str, str] | None = None,
) -> dict[str, Any]:
    """采纳建网建议：按同样的依据与参数重新计算，keys 为空时采纳全部可采纳的建议；每个建议建一个网络（成员加入方式
    suggestion），with_rules 时把 name / subnet 依据的规则设为新网络的自动加入规则。不能采纳的（校验不通过、与现有网络
    相同、空）跳过并说明。names：{key: 网络名称} 覆盖建议的名称。"""
    projects.require_write(scope)
    res = suggest(db_url, scope, basis, params, kb)
    want = set(keys or [])
    created, skipped = [], []
    for g in res["suggestions"]:
        if want and g["key"] not in want:
            continue
        if not g["adoptable"]:
            reason = (
                "same_as_existing"
                if g["same_as"]
                else ("check_failed" if g["check"]["status"] == "reject" else "empty")
            )
            skipped.append({"key": g["key"], "reason": reason})
            continue
        name = (names or {}).get(g["key"]) or g["name"]
        with store.session(db_url) as s:
            slug = _free_slug(s, scope.project_id, g["slug"])
        net = create_network(
            db_url,
            scope,
            {
                "name": name,
                "slug": slug,
                "folder_id": folder_id,
                "device_ids": [d["id"] for d in g["devices"]],
                "_source": "suggestion",
                "rules": [g["rule"]] if with_rules and g.get("rule") else [],
            },
            kb,
        )
        created.append({"key": g["key"], "network": brief_of(net)})
    missing = sorted(want - {g["key"] for g in res["suggestions"]})
    for k in missing:
        skipped.append({"key": k, "reason": "not_found"})
    return {"basis": basis, "created": created, "skipped": skipped}


def brief_of(net: dict[str, Any]) -> dict[str, Any]:
    return {k: net[k] for k in ("id", "slug", "name", "color", "default")}


# ---------------------------------------------------------------- 拓扑：网络外的对端


def outside_peers(db_url: str, scope: Scope, kb: Any, inside: list[Any]) -> dict[str, Any]:
    """网络外的对端：在整个项目设备池上还原拓扑，取一端在本网络、另一端不在的链路；对端标出设备与它所在的网络。
    inside：本网络参与拓扑的设备（topology.Device）。"""
    from lmesh.core import topology

    if scope.network_default or scope.network_id is None:
        return {"links": [], "count": 0}
    inside_ids = {d.device_id for d in inside if d.device_id is not None}
    with projects.use(_project_scope(db_url, scope), scope.identity):
        others, _ = topology.from_db(db_url, kb, None)
    others = [d for d in others if d.device_id not in inside_ids]
    if not others:
        return {"links": [], "count": 0}
    devs = list(inside) + others
    names = topology.unique_names([d.name for d in devs])
    for d, n in zip(devs, names, strict=True):
        d.name = n
    topo = topology.build(devs, kb)
    tj = topology.to_json(topo)
    by_name = {d.name: d.device_id for d in devs}
    with store.session(db_url) as s:
        nets = networks_of_devices(s, scope.project_id)
    links = []
    for lk in tj["links"]:
        a_in = by_name.get(lk["a"]["device"]) in inside_ids
        b_in = by_name.get(lk["b"]["device"]) in inside_ids
        if a_in == b_in:
            continue
        mine, peer = (lk["a"], lk["b"]) if a_in else (lk["b"], lk["a"])
        pid = by_name.get(peer["device"])
        links.append(
            {
                "id": lk["id"],
                "type": lk["type"],
                "confidence": lk.get("confidence"),
                "inside": {k: mine.get(k) for k in ("device", "interface", "address")},
                "peer": {
                    "device": peer["device"],
                    "device_id": pid,
                    "interface": peer.get("interface"),
                    "address": peer.get("address"),
                    "networks": [x for x in nets.get(pid or 0, []) if not x["default"]]
                    or [x for x in nets.get(pid or 0, [])],
                },
            }
        )
    return {"links": links, "count": len(links)}


def node_networks(db_url: str, scope: Scope) -> dict[int, list[dict[str, Any]]]:
    """拓扑节点的“还在哪些网络”（不含当前网络与默认网络）。"""
    with store.session(db_url) as s:
        nets = networks_of_devices(s, scope.project_id)
    return {d: [x for x in v if x["id"] != scope.network_id and not x["default"]] for d, v in nets.items()}
