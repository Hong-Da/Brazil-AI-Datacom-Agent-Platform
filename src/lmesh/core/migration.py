"""割接迁移（M4-5，REQ-017）：旧设备配置 + 新设备的目标 Profile（可以跨厂商）+ 接口映射表 → 新设备配置、
最终接口映射表、告警、校验与割接步骤清单。

流程：
    1. 接口映射建议（suggest_map）：用户给出的映射优先；其余按接口类别（物理口 / 聚合口 / 环回口 / 桥域三层口 …）、
       速率、编号规律，在目标端口清单里分配。端口清单依次取：指定型号的知识库清单（knowledge/migration/ports/<Profile>.yaml）、
       新设备现有配置里的接口、知识库的默认型号（提示 port_inventory_assumed）；都没有时按类型换写法、编号不变（低置信度）。
       每条建议附依据（basis）与置信度（confidence）；分配不了的列入 unmapped（附原因）。管理口不迁移。
    2. 换接口前的整理（在旧图的副本上）：没有映射的接口（含管理口）连同子接口不迁移，引用它们的配置一并不迁移；
       聚合口编号变化时成员口的聚合组编号跟着改；聚合口不迁移时成员口退出聚合。
    3. 翻译：复用 core/translate.py（按最终映射表改写接口名，默认值差异、不支持项照常告警）。
    4. 新设备已有配置时（target_graph）：在现有配置上合并，只生成需要新增 / 修改的部分（delta）；
       现有配置中与迁移内容冲突的取值按 on_conflict 处理（migrate：以旧设备为准，keep：保留现有），都告警 target_conflict。
    5. 校验：新配置再解析建图，与旧设备按有效值对比（跨厂商 + 接口映射）；告警、不支持项、不迁移的接口、
       新设备原有的配置之外还有差异时记为 verify_diff。
    6. 增量下发脚本：core/change.py 可用时调用 change.plan(current_graph, target_graph, kb, profile)，不可用时不生成（script.available=false）。
    7. 割接步骤清单：割接前核对、新设备预配置（端口保持关闭、BGP 对等体隔离）、旧设备隔离 BGP 与关闭端口、
       按映射表迁移线缆、新设备按“上行先、接入后”启用端口、恢复 BGP（公网 / 骨干先、VRF 后）、割接后核对，以及回退步骤。

所有告警都带文案键（key）与参数（params），界面与 CLI 按语言显示；字段名与取值不随语言变化。
"""

from __future__ import annotations

import contextlib
import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from lmesh.core import canon
from lmesh.core import compare as cmp
from lmesh.core import translate as tr
from lmesh.core.graph import DEVICE
from lmesh.core.kb import KnowledgeBase, read_yaml

CONFLICT_POLICIES = ("migrate", "keep")
# 物理口类型的速率（Gbps），按接口名统一写法的类型；100GE 一类的写法按数字
_SPEEDS: dict[str, float] = {
    "FastEthernet": 0.1,
    "GigabitEthernet": 1,
    "XGigabitEthernet": 10,
    "TenGigabitEthernet": 10,
    "TwentyFiveGigE": 25,
    "FortyGigabitEthernet": 40,
    "HundredGigE": 100,
    "FourHundredGigE": 400,
}
# 逻辑接口类别（按接口名统一写法的类型）
_LOGICAL: dict[str, str] = {
    "Eth-Trunk": "lag",
    "Port-channel": "lag",
    "Loopback": "loopback",
    "Vbdif": "bdi",
    "BDI": "bdi",
    "Vlanif": "vlanif",
    "Vlan": "vlanif",
    "NULL": "null",
    "Tunnel": "tunnel",
}
_PHYSICAL_OTHER = {"Ethernet", "Serial", "Pos", "Cpos", "E1"}
# 目标端口在现有配置里只有这些属性时仍视为空闲
_FREE_ATTRS = {
    "interface.description",
    "interface.shutdown",
    "interface.negotiation",
    "interface.speed",
    "interface.duplex",
    "interface.mtu",
}
_CONFIDENCE = {
    "user": 1.0,
    "same_name": 0.95,
    "logical": 0.9,
    "same_index": 0.8,
    "same_speed": 0.6,
    "same_name_unverified": 0.5,
    "higher_speed": 0.4,
    "type_convert": 0.3,
}
_LINE_OFFSET = 1_000_000  # 合并进现有配置的新节点：行号加偏移，排在原有内容之后，且不会被当成现有配置的原文行
_SPLIT = re.compile(r"^(\d+GE|[A-Za-z][A-Za-z\-]*?)(\d.*)?$")


class MigrateError(ValueError):
    """迁移参数错误（文案键 + 参数）。"""

    def __init__(self, key: str, kind: str = "param", **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.fmt = key, kind, fmt


def _warn(kind: str, level: str, node: str | None = None, **params: Any) -> dict[str, Any]:
    return tr._item(kind, f"migrate.warn.{kind}", node, level=level, **params)


# ---------------------------------------------------------------- 接口名


@dataclass
class Port:
    name: str  # 原来的写法
    canon: str  # 统一写法
    type: str  # 统一写法的类型（GigabitEthernet、Eth-Trunk …）
    rest: str  # 编号部分（0/2/1）
    cls: str  # physical / lag / loopback / bdi / vlanif / null / tunnel / management / other
    speed: float | None = None

    @property
    def numbers(self) -> tuple[int, ...]:
        return tuple(int(x) for x in re.findall(r"\d+", self.rest))

    @property
    def index(self) -> int | None:
        nums = self.numbers
        return nums[-1] if nums else None


def type_speed(t: str) -> float | None:
    if t in _SPEEDS:
        return _SPEEDS[t]
    m = re.fullmatch(r"(\d+)GE", t)
    return float(m.group(1)) if m else None


def parse_port(name: str, mgmt: list[str] | None = None, speed: float | None = None) -> Port:
    c = cmp.interface_name(name)
    m = _SPLIT.match(c)
    t, rest = (m.group(1), m.group(2) or "") if m else (c, "")
    if t in _LOGICAL:
        cls = _LOGICAL[t]
    elif type_speed(t) is not None or t in _PHYSICAL_OTHER:
        cls = "physical"
    else:
        cls = "other"
    if any(re.search(p, c) for p in mgmt or []):
        cls = "management"
    return Port(str(name), c, t, rest, cls, speed if speed is not None else type_speed(t))


def _base(name: str) -> str:
    return cmp.interface_name(name).partition(".")[0]


# ---------------------------------------------------------------- 知识：平台族操作命令、端口清单


def _kfile(kb: KnowledgeBase, *parts: str) -> Path | None:
    """运行时知识库没有 migration/ 时（M4-5 之前创建的）用程序自带的。"""
    f = Path(kb.root).joinpath("migration", *parts)
    if not f.exists():
        from lmesh import paths

        f = paths.builtin_knowledge_dir().joinpath("migration", *parts)
    return f if f.exists() else None


def family_ops(kb: KnowledgeBase, family: str) -> dict[str, Any]:
    f = _kfile(kb, f"{family}.yaml")
    data = (read_yaml(f) or {}) if f else {}
    return dict(data) if isinstance(data, dict) else {}


def _expand(spec: str) -> list[str]:
    m = re.search(r"\{(\d+)-(\d+)\}", spec)
    if not m:
        return [spec]
    a, b = int(m.group(1)), int(m.group(2))
    return [x for i in range(a, b + 1) for x in _expand(spec[: m.start()] + str(i) + spec[m.end() :])]


def port_inventory(kb: KnowledgeBase, profile: str) -> dict[str, Any] | None:
    f = _kfile(kb, "ports", f"{profile}.yaml")
    data = read_yaml(f) if f else None
    return dict(data) if isinstance(data, dict) else None


def _models_ports(inv: dict[str, Any], model: str) -> list[tuple[str, float | None]]:
    out: list[tuple[str, float | None]] = []
    for p in ((inv.get("models") or {}).get(model) or {}).get("ports") or []:
        spd = p.get("speed")
        for n in _expand(str(p.get("range") or p.get("name") or "")):
            if n:
                out.append((n, float(spd) if spd is not None else None))
    return out


def models(kb: KnowledgeBase, profile: str) -> list[str]:
    inv = port_inventory(kb, profile) or {}
    return sorted((inv.get("models") or {}).keys())


# ---------------------------------------------------------------- 图的工具


def _children(g: nx.MultiDiGraph) -> dict[str, list[str]]:
    kids: dict[str, list[str]] = defaultdict(list)
    for a, b, d in g.edges(data=True):
        if d.get("kind") == "contains":
            kids[a].append(b)
    return kids


def _subtree(kids: dict[str, list[str]], nid: str) -> list[str]:
    out, stack = [], [nid]
    while stack:
        x = stack.pop()
        out.append(x)
        stack.extend(kids.get(x, []))
    return out


def _interfaces(g: nx.MultiDiGraph) -> dict[str, str]:
    """顶层接口对象：统一写法 → 节点。"""
    return {
        cmp.interface_name(str(d.get("key"))): n
        for n, d in g.nodes(data=True)
        if d.get("kind") == "object" and d.get("schema") == "interface" and d.get("key")
    }


def _parent(g: nx.MultiDiGraph, nid: str) -> str:
    return next((a for a, _, d in g.in_edges(nid, data=True) if d.get("kind") == "contains"), DEVICE)


def _seg(nid: str) -> str:
    """编号的最后一段（方括号里的 / 不算分隔）。"""
    depth = 0
    for i in range(len(nid) - 1, -1, -1):
        ch = nid[i]
        if ch == "]":
            depth += 1
        elif ch == "[":
            depth -= 1
        elif ch == "/" and depth == 0:
            return nid[i + 1 :]
    return nid


def _norm_id(nid: str) -> str:
    """不同图之间对应节点：编号里的接口名按统一写法、不分大小写。"""
    return re.sub(r"\[([^\]]*)\]", lambda m: "[" + cmp.interface_name(m.group(1)).lower() + "]", nid).lower()


def _mgmt_vrf_ports(g: nx.MultiDiGraph, patterns: list[str]) -> set[str]:
    out: set[str] = set()
    if not patterns:
        return out
    for n, d in g.nodes(data=True):
        value = d.get("value")
        if d.get("schema") == "interface.vrf" and value is not None and any(re.search(p, str(value)) for p in patterns):
            key = g.nodes[_parent(g, n)].get("key")
            if key:
                out.add(_base(str(key)))
    return out


# ---------------------------------------------------------------- 1. 接口映射建议


@dataclass
class _Src:
    port: Port
    node: str | None
    subs: list[str] = field(default_factory=list)
    configured: bool = False
    lines: list[int] = field(default_factory=list)


class _Suggester:
    def __init__(
        self,
        g_old: nx.MultiDiGraph,
        kb: KnowledgeBase,
        src_profile: str,
        dst_profile: str,
        interface_map: dict[str, str] | None,
        target_graph: nx.MultiDiGraph | None,
        model: str | None,
    ):
        for pid in (src_profile, dst_profile):
            if pid not in kb.profiles:
                raise MigrateError("parse.profile_unknown", profile=pid)
        self.g, self.kb, self.src, self.dst = g_old, kb, src_profile, dst_profile
        self.src_family = kb.profiles[src_profile].family
        self.dst_family = kb.profiles[dst_profile].family
        self.target = target_graph
        self.model = model
        self.user = {cmp.interface_name(str(k)): str(v).strip() for k, v in (interface_map or {}).items()}
        self.warnings: list[dict[str, Any]] = []
        src_ops, dst_ops = family_ops(kb, self.src_family), family_ops(kb, self.dst_family)
        self.inv = port_inventory(kb, dst_profile)
        self.src_mgmt = [str(x) for x in src_ops.get("management") or []]
        self.dst_mgmt = [str(x) for x in dst_ops.get("management") or []] + [
            str(x) for x in (self.inv or {}).get("management") or []
        ]
        self.src_mgmt_vrf_ports = _mgmt_vrf_ports(g_old, [str(x) for x in src_ops.get("management_vrf") or []])
        self.dst_mgmt_vrf = [str(x) for x in dst_ops.get("management_vrf") or []]
        _, style = canon._index(kb, self.dst_family)
        self.dst_types = [str(t) for t in style["interface_types"] if t not in (None, "None")]
        self.dst_logical = {str(k): str(v) for k, v in (dst_ops.get("logical_types") or {}).items() if v}

    # ----- 源接口 -----

    def sources(self) -> list[_Src]:
        kids = _children(self.g)
        objs = _interfaces(self.g)
        bases: dict[str, _Src] = {}
        for c, nid in sorted(objs.items()):
            b = c.partition(".")[0]
            key = str(self.g.nodes[nid].get("key"))
            if b not in bases:
                raw_base = key.partition(".")[0]
                bases[b] = _Src(parse_port(raw_base, self.src_mgmt), objs.get(b))
                if b in self.src_mgmt_vrf_ports:
                    bases[b].port.cls = "management"
            s = bases[b]
            if c != b:
                s.subs.append(key)
            for x in _subtree(kids, nid):
                d = self.g.nodes[x]
                s.lines += d.get("lines") or []
                if x != nid and d.get("origin") != "default":
                    s.configured = True
        for s in bases.values():
            s.lines = sorted(set(s.lines))
        return sorted(bases.values(), key=lambda s: (not s.configured, s.port.type, s.port.numbers, s.port.canon))

    # ----- 目标端口 -----

    def targets(self) -> tuple[list[Port], dict[str, Any], set[str], set[str]]:
        """目标物理端口清单、清单来源、现有配置中已占用的端口、目标设备上的管理口（统一写法）。"""
        occupied: set[str] = set()
        mgmt: set[str] = set()
        cfg_ports: list[Port] = []
        if self.target is not None:
            kids = _children(self.target)
            vrf_mgmt = _mgmt_vrf_ports(self.target, self.dst_mgmt_vrf)
            for c, nid in sorted(_interfaces(self.target).items()):
                p = parse_port(str(self.target.nodes[nid].get("key")), self.dst_mgmt)
                b = c.partition(".")[0]
                if p.cls == "management" or b in vrf_mgmt:
                    mgmt.add(b)
                    continue
                if c != b:
                    occupied.add(b)
                    continue
                if p.cls == "physical":
                    cfg_ports.append(p)
                busy = [
                    x
                    for x in _subtree(kids, nid)[1:]
                    if self.target.nodes[x].get("origin") != "default"
                    and self.target.nodes[x].get("kind") in ("attr", "object")
                    and self.target.nodes[x].get("schema") not in _FREE_ATTRS
                ]
                if busy:
                    occupied.add(c)
        info: dict[str, Any] = {"source": "none", "model": None, "ports": 0, "verified": None}
        ports: list[Port] = []
        inv = self.inv or {}
        model = self.model
        if model and model not in (inv.get("models") or {}):
            raise MigrateError("migrate.model_unknown", model=model, models=", ".join(models(self.kb, self.dst)) or "-")
        if model:
            ports = [parse_port(n, self.dst_mgmt, s) for n, s in _models_ports(inv, model)]
            info = {"source": "kb", "model": model, "ports": len(ports), "verified": bool(inv.get("verified"))}
        elif cfg_ports:
            ports = cfg_ports
            info = {"source": "target_config", "model": None, "ports": len(ports), "verified": True}
        elif inv.get("default_model") and inv["default_model"] in (inv.get("models") or {}):
            model = str(inv["default_model"])
            ports = [parse_port(n, self.dst_mgmt, s) for n, s in _models_ports(inv, model)]
            info = {"source": "kb", "model": model, "ports": len(ports), "verified": bool(inv.get("verified"))}
            self.warnings.append(_warn("port_inventory_assumed", "info", None, model=model, profile=self.dst))
        else:
            self.warnings.append(_warn("port_inventory_missing", "warning", None, profile=self.dst))
        ports = [p for p in ports if p.cls == "physical" and p.canon not in mgmt]
        return ports, info, occupied, mgmt

    def type_name(self, cls: str, speed: float | None = None) -> str | None:
        """目标平台族里某一类接口的类型写法：knowledge/migration 的 logical_types，其次 knowledge/render 的 interface_types。"""
        if cls in self.dst_logical:
            return self.dst_logical[cls]
        for t in self.dst_types:
            p = parse_port(t + "0")
            if cls == "physical" and p.cls == "physical" and speed is not None and p.speed == speed:
                return t
            if cls != "physical" and p.cls == cls:
                return t
        return None

    # ----- 分配 -----

    def run(self) -> dict[str, Any]:
        srcs = self.sources()
        ports, inv_info, occupied, dst_mgmt = self.targets()
        by_canon = {p.canon.lower(): p for p in ports}
        used: set[str] = set()
        rows: list[dict[str, Any]] = []
        unmapped: list[dict[str, Any]] = []
        seen_src = {s.port.canon for s in srcs}
        for k in self.user:
            if _base(k) not in seen_src:
                self.warnings.append(_warn("map_source_missing", "info", None, name=k))

        def row(s: _Src, target: str, basis: str, tport: Port | None) -> dict[str, Any]:
            tp = tport or parse_port(target, self.dst_mgmt)
            r = {
                "source": s.port.name,
                "target": target,
                "kind": s.port.cls,
                "source_speed": s.port.speed,
                "target_speed": tp.speed,
                "basis": basis,
                "confidence": _CONFIDENCE[basis],
                "subinterfaces": list(s.subs),
                "configured": s.configured,
                "node": s.node,
                "lines": s.lines,
            }
            used.add(tp.canon.lower())
            return r

        def drop(s: _Src, reason: str, level: str = "warning") -> None:
            unmapped.append(
                {
                    "source": s.port.name,
                    "kind": s.port.cls,
                    "speed": s.port.speed,
                    "reason": reason,
                    "subinterfaces": list(s.subs),
                    "configured": s.configured,
                    "node": s.node,
                    "lines": s.lines,
                }
            )

        # 用户给出的映射
        pending: list[_Src] = []
        for s in srcs:
            t = self.user.get(s.port.canon)
            if t is None:
                pending.append(s)
                continue
            if t in ("", "-"):
                drop(s, "user_excluded")
                continue
            tport = parse_port(t, self.dst_mgmt)
            if tport.canon.lower() in used:
                self.warnings.append(_warn("duplicate_target", "error", s.node, name=s.port.name, target=t))
                drop(s, "duplicate_target")
                continue
            if ports and tport.cls == "physical" and tport.canon.lower() not in by_canon:
                self.warnings.append(_warn("target_not_in_inventory", "info", s.node, name=s.port.name, target=t))
            if tport.canon.lower() in by_canon:
                tport = by_canon[tport.canon.lower()]
            rows.append(row(s, t, "user", tport))
        # 管理口、逻辑接口
        phys: list[_Src] = []
        for s in pending:
            p = s.port
            if p.cls == "management":
                drop(s, "management", "info")
                continue
            if p.cls == "physical":
                phys.append(s)
                continue
            if p.cls == "other":
                drop(s, "unknown_type")
                continue
            if self.src_family == self.dst_family:
                rows.append(row(s, p.name, "same_name", None))
                continue
            t = self.type_name(p.cls)
            if t is None:
                drop(s, "no_target_type")
                continue
            target = t + p.rest
            if target.lower() in used or cmp.interface_name(target).lower() in used:
                drop(s, "duplicate_target")
                continue
            rows.append(row(s, target, "logical", None))
        # 物理口：同名 → 同编号 → 同速率 → 更高速率
        free = [p for p in sorted(ports, key=lambda x: (x.speed or 0, x.numbers)) if p.canon not in occupied]

        def avail(p: Port) -> bool:
            return p.canon.lower() not in used

        left: list[_Src] = []
        for s in phys:
            hit = by_canon.get(s.port.canon.lower())
            if hit and avail(hit) and hit.canon not in occupied and (s.port.speed in (None, hit.speed)):
                rows.append(row(s, hit.name, "same_name", hit))
            else:
                left.append(s)
        phys, left = left, []
        for s in phys:
            hit = next(
                (
                    p
                    for p in free
                    if avail(p) and p.speed == s.port.speed and p.index == s.port.index and s.port.index is not None
                ),
                None,
            )
            if hit:
                rows.append(row(s, hit.name, "same_index", hit))
            else:
                left.append(s)
        phys, left = left, []
        for s in phys:
            hit = next((p for p in free if avail(p) and p.speed == s.port.speed and s.port.speed is not None), None)
            if hit:
                rows.append(row(s, hit.name, "same_speed", hit))
            else:
                left.append(s)
        phys, left = left, []
        for s in phys:
            hit = next(
                (
                    p
                    for p in free
                    if avail(p) and s.port.speed is not None and p.speed is not None and p.speed > s.port.speed
                ),
                None,
            )
            if hit:
                rows.append(row(s, hit.name, "higher_speed", hit))
            else:
                left.append(s)
        for s in left:
            if ports:
                drop(s, "no_free_port" if s.port.speed is not None else "speed_unknown")
                continue
            # 没有端口清单：同平台族保持原名，跨平台族按类型换写法、编号不变（低置信度）
            if self.src_family == self.dst_family:
                rows.append(row(s, s.port.name, "same_name_unverified", None))
                continue
            t = self.type_name("physical", s.port.speed)
            if t is None:
                drop(s, "no_target_type")
                continue
            rows.append(row(s, t + s.port.rest, "type_convert", None))
        self.check(rows, unmapped, occupied, dst_mgmt)
        rows.sort(key=lambda r: (parse_port(r["source"]).type, parse_port(r["source"]).numbers))
        return {
            "source": {"device": self.g.graph.get("device"), "profile": self.src, "family": self.src_family},
            "target": {"profile": self.dst, "family": self.dst_family},
            "inventory": inv_info,
            "map": rows,
            "unmapped": unmapped,
            "warnings": self.warnings,
            "stats": {
                "interfaces": len(rows) + len(unmapped),
                "mapped": len(rows),
                "unmapped": len(unmapped),
                "by_basis": {b: sum(1 for r in rows if r["basis"] == b) for b in _CONFIDENCE},
            },
        }

    def check(
        self, rows: list[dict[str, Any]], unmapped: list[dict[str, Any]], occupied: set[str], dst_mgmt: set[str]
    ) -> None:
        for r in rows:
            tp = parse_port(r["target"], self.dst_mgmt)
            sk = r["kind"]
            if tp.canon in dst_mgmt or tp.cls == "management":
                self.warnings.append(
                    _warn("target_is_management", "warning", r["node"], name=r["source"], target=r["target"])
                )
            elif (sk == "physical") != (tp.cls == "physical") or (sk != "physical" and sk != tp.cls):
                self.warnings.append(
                    _warn(
                        "type_mismatch",
                        "error",
                        r["node"],
                        name=r["source"],
                        target=r["target"],
                        src_kind=sk,
                        dst_kind=tp.cls,
                        lines=r["lines"][:1],
                    )
                )
            elif (
                r["source_speed"] is not None
                and r["target_speed"] is not None
                and r["source_speed"] != r["target_speed"]
            ):
                self.warnings.append(
                    _warn(
                        "speed_mismatch",
                        "warning" if r["target_speed"] < r["source_speed"] else "info",
                        r["node"],
                        name=r["source"],
                        target=r["target"],
                        src_speed=r["source_speed"],
                        dst_speed=r["target_speed"],
                        lines=r["lines"][:1],
                    )
                )
            if tp.canon in occupied and r["basis"] in ("user", "same_name", "logical", "same_name_unverified"):
                self.warnings.append(
                    _warn("target_occupied", "warning", r["node"], name=r["source"], target=r["target"])
                )
        for u in unmapped:
            if u["reason"] == "management":
                self.warnings.append(_warn("mgmt_not_migrated", "info", u["node"], name=u["source"], lines=u["lines"]))
            elif u["reason"] != "user_excluded":
                self.warnings.append(
                    _warn(
                        "interface_unmapped",
                        "warning" if u["configured"] else "info",
                        u["node"],
                        name=u["source"],
                        reason=u["reason"],
                        subs=len(u["subinterfaces"]),
                        lines=u["lines"],
                    )
                )


def suggest_map(
    g_old: nx.MultiDiGraph,
    kb: KnowledgeBase,
    src_profile: str,
    dst_profile: str,
    interface_map: dict[str, str] | None = None,
    target_graph: nx.MultiDiGraph | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """接口映射建议：{map[], unmapped[], warnings[], inventory, stats}。"""
    return _Suggester(g_old, kb, src_profile, dst_profile, interface_map, target_graph, model).run()


# ---------------------------------------------------------------- 2～7. 迁移


class _Migrator:
    def __init__(
        self,
        g_old: nx.MultiDiGraph,
        kb: KnowledgeBase,
        src_profile: str,
        dst_profile: str,
        interface_map: dict[str, str] | None,
        target_graph: nx.MultiDiGraph | None,
        model: str | None,
        on_conflict: str,
    ):
        if on_conflict not in CONFLICT_POLICIES:
            raise MigrateError("migrate.bad_conflict", value=on_conflict, choices=", ".join(CONFLICT_POLICIES))
        if target_graph is not None and target_graph.graph.get("profile") not in (None, dst_profile):
            raise MigrateError(
                "migrate.target_profile_mismatch", profile=str(target_graph.graph.get("profile")), to=dst_profile
            )
        self.g, self.kb, self.src, self.dst = g_old, kb, src_profile, dst_profile
        self.user_map = dict(interface_map or {})
        self.target = target_graph
        self.on_conflict = on_conflict
        self.sug = suggest_map(g_old, kb, src_profile, dst_profile, interface_map, target_graph, model)
        self.warnings: list[dict[str, Any]] = list(self.sug["warnings"])
        self.explained: set[str] = set()  # 旧图中有原因的节点（校验时不算差异）
        self.kept_b: set[str] = set()  # 冲突时保留的现有取值（新配置中的节点，统一写法）
        self.unsupported: list[dict[str, Any]] = []
        self.final_map: dict[str, str] = {r["source"]: r["target"] for r in self.sug["map"]}
        # 用户显式给出的子接口映射也带上（translate 先整名匹配）
        for k, v in self.user_map.items():
            if "." in cmp.interface_name(k) and str(v).strip() not in ("", "-"):
                self.final_map[k] = str(v).strip()
        self.dst_family = kb.profiles[dst_profile].family

    # ----- 2. 换接口前的整理 -----

    def prepare(self) -> nx.MultiDiGraph:
        g = self.g.copy()
        kids = _children(g)
        objs = _interfaces(g)
        excluded = {_base(u["source"]) for u in self.sug["unmapped"]}
        sch = cmp._Schema(self.kb)
        removed: set[str] = set()
        for c, nid in objs.items():
            if c.partition(".")[0] in excluded:
                removed.update(_subtree(kids, nid))
        # 引用不迁移的接口的配置
        for n, d in list(g.nodes(data=True)):
            if n in removed or d.get("kind") not in ("attr", "object"):
                continue
            sn = self.kb.nodes.get(str(d.get("schema")))
            if sn is None or sn.id == "interface":
                continue
            names: list[Any] = []
            if d.get("kind") == "attr" and (sn.type == "interface" or (sn.type == "ref" and sn.ref == "interface")):
                v = d.get("value")
                names = v if isinstance(v, list) else [v]
            elif d.get("kind") == "object":
                key = d.get("key")
                fields = key.items() if isinstance(key, dict) else [((sn.key or ["name"])[0], key)]
                for f, v in fields:
                    t, ref = sch.field_type(sn, f)
                    if t == "interface" or ref == "interface" or f == "interface":
                        names.append(v)
            hit = next((x for x in names if isinstance(x, str) and x and _base(x) in excluded), None)
            if hit is None:
                continue
            if d.get("origin") == "default":
                continue
            sub = _subtree(kids, n)
            removed.update(sub)
            self.warnings.append(
                _warn(
                    "ref_not_migrated",
                    "warning",
                    n,
                    schema=sn.id,
                    name=hit,
                    lines=sorted({ln for x in sub for ln in (g.nodes[x].get("lines") or [])}),
                )
            )
        self.explained |= removed
        g.remove_nodes_from(removed)
        self.lag(g, objs, excluded)
        self.subinterfaces()
        return g

    def lag(self, g: nx.MultiDiGraph, objs: dict[str, str], excluded: set[str]) -> None:
        """聚合口：编号变化时成员口的聚合组编号跟着改；聚合口不迁移时成员口退出聚合；成员不全迁移、速率不一致时告警。"""
        trunks: dict[int, str] = {}  # 旧聚合组编号 → 旧聚合口（统一写法）
        for c in objs:
            p = parse_port(c)
            if p.cls == "lag" and "." not in c and p.index is not None:
                trunks[p.index] = c
        members: dict[int, list[tuple[str, str]]] = defaultdict(list)  # 组号 → [(成员口, lag 节点)]
        for n, d in self.g.nodes(data=True):
            if d.get("schema") == "interface.lag" and d.get("origin") != "default" and d.get("value") is not None:
                owner = _parent(self.g, n)
                try:
                    members[int(d["value"])].append((cmp.interface_name(str(self.g.nodes[owner].get("key"))), n))
                except (TypeError, ValueError):
                    continue
        cmap = {cmp.interface_name(k): v for k, v in self.final_map.items()}
        speeds = {cmp.interface_name(r["source"]): r["target_speed"] for r in self.sug["map"]}
        for num, mem in sorted(members.items()):
            trunk = trunks.get(num)
            if trunk is None:
                continue
            kept = [(m, n) for m, n in mem if _base(m) not in excluded]
            if trunk in excluded:
                for m, n in kept:
                    drop = [x for x in (n, _parent(self.g, n) + "/lag_mode") if x in g]
                    g.remove_nodes_from(drop)
                    self.explained.update(drop)
                    self.warnings.append(_warn("lag_trunk_not_migrated", "warning", n, name=m, trunk=trunk))
                continue
            new_trunk = cmap.get(trunk, trunk)
            new_num = parse_port(new_trunk).index
            if len(kept) < len(mem):
                self.warnings.append(
                    _warn(
                        "lag_member_not_migrated",
                        "warning",
                        objs.get(trunk),
                        trunk=trunk,
                        members=", ".join(sorted(m for m, _ in mem if _base(m) in excluded)),
                    )
                )
            if new_num is not None and new_num != num:
                for _m, n in kept:
                    if n in g:
                        g.nodes[n]["value"] = new_num
                        g.nodes[n]["raw"] = new_num
                        self.explained.add(n)
                self.warnings.append(
                    _warn(
                        "lag_renumbered", "info", objs.get(trunk), trunk=trunk, target=new_trunk, old=num, new=new_num
                    )
                )
            spd: set[float] = {float(v) for m, _ in kept if (v := speeds.get(m)) is not None}
            if len(spd) > 1:
                self.warnings.append(
                    _warn(
                        "lag_speed_mismatch",
                        "warning",
                        objs.get(trunk),
                        trunk=trunk,
                        speeds=", ".join(f"{s:g}G" for s in sorted(spd)),
                    )
                )

    def subinterfaces(self) -> None:
        for r in self.sug["map"]:
            if r["subinterfaces"]:
                self.warnings.append(
                    _warn(
                        "subinterfaces_follow",
                        "info",
                        r["node"],
                        name=r["source"],
                        target=r["target"],
                        count=len(r["subinterfaces"]),
                    )
                )

    # ----- 4. 合并到新设备现有配置 -----

    def merge(self, g_t: nx.MultiDiGraph) -> tuple[nx.MultiDiGraph, set[str], dict[str, Any]]:
        assert self.target is not None
        ge = self.target
        gm = ge.copy()
        gm.graph["profile"] = self.dst
        gm.graph["family"] = self.dst_family
        e_index = {_norm_id(n): n for n in ge.nodes}
        facts_t = canon.default_facts(g_t, self.kb, self.dst, False)
        kids_t = _children(g_t)
        kids_e = _children(ge)
        has_fact: dict[str, bool] = {}

        def fact_below(n: str) -> bool:
            if n not in has_fact:
                has_fact[n] = n in facts_t or any(fact_below(c) for c in kids_t.get(n, []))
            return has_fact[n]

        changed: set[str] = set()
        stats = {"added": 0, "changed": 0, "same": 0, "conflicts": 0, "kept": 0}
        to_m: dict[str, str] = {DEVICE: DEVICE}
        stack = [DEVICE]
        while stack:
            tp = stack.pop()
            mp = to_m[tp]
            for c in kids_t.get(tp, []):
                d = g_t.nodes[c]
                kind = d.get("kind")
                if kind not in ("object", "attr"):
                    continue
                is_default = kind == "attr" and d.get("origin") == "default"
                if kind == "object" and not fact_below(c):
                    continue
                if kind == "attr" and c not in facts_t and not is_default:
                    continue
                hit = e_index.get(_norm_id(c))
                if hit is not None and hit in gm:
                    if kind == "object":
                        to_m[c] = hit
                        stack.append(c)
                        self.coexist(gm, ge, kids_e, hit, c, g_t, kids_t)
                        continue
                    e = gm.nodes[hit]
                    sn = self.kb.nodes.get(str(d.get("schema")))
                    ntype = sn.type if sn else "string"
                    if canon._same(e.get("value"), d.get("value"), ntype):
                        stats["same"] += 1
                        continue
                    explicit = e.get("origin") != "default"
                    if is_default and not explicit:
                        continue
                    if explicit:
                        stats["conflicts"] += 1
                        resolution = "migrated" if self.on_conflict == "migrate" else "kept"
                        self.warnings.append(
                            _warn(
                                "target_conflict",
                                "warning",
                                None,
                                target_node=hit,
                                schema=d.get("schema"),
                                existing=e.get("value"),
                                value=d.get("value"),
                                resolution=resolution,
                            )
                        )
                        if self.on_conflict == "keep":
                            stats["kept"] += 1
                            self.kept_b.add(_norm_id(hit))
                            continue
                    e.update(
                        value=d.get("value"),
                        raw=d.get("value"),
                        origin="explicit",
                        lines=[ln + _LINE_OFFSET for ln in d.get("lines") or []],
                        cards=[],
                        negated=d.get("negated", False),
                    )
                    changed.add(hit)
                    stats["changed"] += 1
                    continue
                if is_default:
                    continue
                seg = c[len(tp) + 1 :] if tp != DEVICE else c
                nid = seg if mp == DEVICE else f"{mp}/{seg}"
                attrs = {k: v for k, v in d.items() if k not in ("lines", "cards")}
                gm.add_node(nid, **attrs, lines=[ln + _LINE_OFFSET for ln in d.get("lines") or []], cards=[])
                gm.add_edge(mp, nid, kind="contains")
                to_m[c] = nid
                if c in facts_t:
                    changed.add(nid)
                    stats["added"] += 1
                if kind == "object":
                    stack.append(c)
        for a, b, d in g_t.edges(data=True):
            if d.get("kind") in ("reference", "prerequisite") and a in to_m and b in to_m:
                gm.add_edge(to_m[a], to_m[b], kind=d.get("kind"), note=d.get("note", ""))
        return gm, changed, stats

    def coexist(
        self,
        gm: nx.MultiDiGraph,
        ge: nx.MultiDiGraph,
        kids_e: dict[str, list[str]],
        e_obj: str,
        t_obj: str,
        g_t: nx.MultiDiGraph,
        kids_t: dict[str, list[str]],
    ) -> None:
        """同一对象下，现有配置有、迁移内容没有的同类子对象（例如另一个 IP 地址）：合并后并存，提示人工确认。"""
        t_keys = {(g_t.nodes[c].get("schema"), _norm_id(_seg(c))) for c in kids_t.get(t_obj, [])}
        t_schemas = {s for s, _ in t_keys}
        for c in kids_e.get(e_obj, []):
            d = ge.nodes[c]
            if d.get("kind") != "object" or d.get("origin") == "default" or d.get("schema") not in t_schemas:
                continue
            if (d.get("schema"), _norm_id(_seg(c))) in t_keys:
                continue
            self.warnings.append(
                _warn("target_coexist", "warning", None, target_node=c, schema=d.get("schema"), value=d.get("key"))
            )

    # ----- 5. 校验 -----

    def reshape_back(self, g: nx.MultiDiGraph) -> None:
        """两个平台族的二层接入点形态不同时（华为二层子接口 / Cisco 业务实例），新配置换回旧设备的形态再对比（同 translate）。"""
        reshape = getattr(tr, "reshape_access", None)
        if reshape is None:
            return
        fam = self.kb.profiles
        src_form = canon._index(self.kb, fam[self.src].family)[1].get("access_form")
        dst_form = canon._index(self.kb, fam[self.dst].family)[1].get("access_form")
        if src_form and dst_form and src_form != dst_form:
            reshape(g, src_form)

    def verify(self, text: str, existing_unknown: set[str]) -> dict[str, Any]:
        try:
            b = cmp.side_from_text(text, self.kb, self.dst, "migrated")
        except cmp.CompareError as e:
            self.warnings.append(_warn("verify_failed", "error", None, error=e.key))
            return {"checked": False, "equal": False, "diffs": 0, "unexplained": 0, "target_existing": 0}
        self.reshape_back(b.graph)
        r = cmp.compare(cmp.Side(self.g, "old"), b, self.kb, interface_map=self.final_map or None)
        explained = self.explained | {w["node"] for w in self.warnings + self.unsupported if w.get("node")}
        e_ids = {_norm_id(n) for n in self.target.nodes} if self.target is not None else set()

        def covered(node: str | None) -> bool:
            return bool(node) and any(node == x or str(node).startswith(x + "/") for x in explained)

        unexplained = existing = 0
        for d in r["diffs"]:
            na, nb = (d.get("a") or {}).get("node"), (d.get("b") or {}).get("node")
            if covered(na) or (na is None and covered(nb)):
                continue
            if nb and (_norm_id(nb) in self.kept_b or (na is None and _norm_id(nb) in e_ids)):
                existing += 1
                continue
            if na is None and nb and any(_norm_id(nb).startswith(x + "/") for x in e_ids if x != DEVICE):
                existing += 1
                continue
            unexplained += 1
            self.warnings.append(
                _warn(
                    "verify_diff",
                    "warning",
                    na or nb,
                    schema=d.get("schema"),
                    diff=d["kind"],
                    cid=d["node"],
                    src_value=(d.get("a") or {}).get("value"),
                    dst_value=(d.get("b") or {}).get("value"),
                    lines=(d.get("a") or {}).get("lines") or [],
                )
            )
        for u in r["unknown"]["b"]:
            if u["text"].strip() in existing_unknown:
                continue
            unexplained += 1
            self.warnings.append(_warn("verify_unknown", "warning", None, line=u["line"], text=u["text"]))
        return {
            "checked": True,
            "equal": r["equal"],
            "diffs": r["summary"]["total"],
            "unexplained": unexplained,
            "target_existing": existing,
        }

    # ----- 6. 增量下发脚本 -----

    def script(self, final_text: str) -> dict[str, Any]:
        """增量下发脚本（新设备现有配置或空配置 → 新配置）：复用 core/change.py；不可用时不生成。
        优先用约定的 plan(current_graph, target_graph, kb, profile)，其次用 change(current_side, target_side, kb)。"""
        try:
            from lmesh.core import change as chg
        except ImportError:
            return {"available": False, "reason": "change_module_unavailable"}
        plan, run = getattr(chg, "plan", None), getattr(chg, "change", None)
        if plan is None and run is None:
            return {"available": False, "reason": "change_module_unavailable"}
        from lmesh.core import analysis
        from lmesh.core import graph as graphmod

        current = self.target
        if current is None:
            current = graphmod.build(analysis.parse_text("", self.kb, self.dst).parsed, self.kb, self.dst, "new")
        target = cmp.side_from_text(final_text, self.kb, self.dst, "target").graph
        try:
            if plan is not None:
                res = plan(current, target, self.kb, self.dst)
                out = dict(res) if isinstance(res, dict) else {"script": res}
                rollback = out.get("rollback")
                items = out.get("items")
            elif run is not None:
                out = run(cmp.Side(current, "current"), cmp.Side(target, "target"), self.kb, with_impact=False)
                rb = out.get("rollback")
                rollback = rb.get("script") if isinstance(rb, dict) else rb
                items = out.get("ops")
        except Exception as e:  # 增量变更模块出错不影响迁移结果
            return {"available": False, "reason": "change_failed", "error": str(e)}
        return {
            "available": True,
            "script": out.get("script"),
            "rollback": rollback,
            "items": items,
            "verify": out.get("verify"),
        }

    # ----- 主流程 -----

    def run(self, verify: bool = True) -> dict[str, Any]:
        from lmesh.core import analysis
        from lmesh.core import graph as graphmod

        g = self.prepare()
        t = tr.translate(g, self.kb, self.src, self.dst, self.final_map or None, verify=False)
        self.unsupported = t["unsupported"]
        self.warnings += t["warnings"]
        merge_stats = None
        existing_unknown: set[str] = set()
        if self.target is not None:
            res = analysis.parse_text(t["text"], self.kb, self.dst)
            g_t = graphmod.build(res.parsed, self.kb, self.dst, str(self.g.graph.get("device") or "device"))
            gm, changed, merge_stats = self.merge(g_t)
            full = canon.render_full(gm, self.kb, self.dst)
            text = full.text
            delta = canon.render_full(gm, self.kb, self.dst, facts=changed, extras=False).text if changed else ""
            existing_unknown = {
                str(d.get("text") or "").strip() for _, d in self.target.nodes(data=True) if d.get("kind") == "unknown"
            }
            for st in self.target.graph.get("statements", []):
                if getattr(st.line, "kind", "") == "unknown":
                    existing_unknown.add(st.line.text.strip())
        else:
            text = delta = t["text"]
        check = (
            self.verify(text, existing_unknown)
            if verify
            else {"checked": False, "equal": False, "diffs": 0, "unexplained": 0, "target_existing": 0}
        )
        script = self.script(text)
        steps = build_steps(self.g, self.kb, self.src, self.dst, self.sug["map"], has_existing=self.target is not None)
        levels: dict[str, int] = defaultdict(int)
        for w in self.warnings:
            levels[str(w["params"].get("level") or "warning")] += 1
        return {
            "source": self.sug["source"],
            "target": {
                **self.sug["target"],
                "model": self.sug["inventory"].get("model"),
                "existing": bool(self.target),
            },
            "inventory": self.sug["inventory"],
            "interface_map": self.sug["map"],
            "unmapped": self.sug["unmapped"],
            "text": text,
            "delta": delta,
            "warnings": self.warnings,
            "unsupported": self.unsupported,
            "defaults": t["defaults"],
            "merge": merge_stats,
            "verify": check,
            "script": script,
            "steps": steps,
            "stats": {
                **self.sug["stats"],
                "translate": t["stats"],
                "warnings": len(self.warnings),
                "by_level": dict(levels),
                "lines": sum(1 for ln in text.splitlines() if ln.strip() and ln.strip() not in ("#", "!")),
                "delta_lines": sum(1 for ln in delta.splitlines() if ln.strip() and ln.strip() not in ("#", "!")),
            },
        }


def migrate(
    g_old: nx.MultiDiGraph,
    kb: KnowledgeBase,
    src_profile: str,
    dst_profile: str,
    interface_map: dict[str, str] | None = None,
    target_graph: nx.MultiDiGraph | None = None,
    model: str | None = None,
    on_conflict: str = "migrate",
    verify: bool = True,
) -> dict[str, Any]:
    """割接迁移：返回 {text, delta, interface_map[], unmapped[], warnings[], unsupported[], defaults[], merge, verify,
    script, steps[], stats, source, target, inventory}。"""
    return _Migrator(g_old, kb, src_profile, dst_profile, interface_map, target_graph, model, on_conflict).run(verify)


def target_graph_from_text(text: str, kb: KnowledgeBase, dst_profile: str) -> nx.MultiDiGraph:
    """新设备现有配置（按目标 Profile 解析）。"""
    from lmesh.core import analysis
    from lmesh.core import graph as graphmod

    if dst_profile not in kb.profiles:
        raise MigrateError("parse.profile_unknown", profile=dst_profile)
    try:
        res = analysis.parse_text(text, kb, dst_profile)
    except analysis.AnalysisError as e:
        raise MigrateError(str(e), profile=dst_profile) from e
    return graphmod.build(res.parsed, kb, res.profile, "target")


# ---------------------------------------------------------------- 7. 割接步骤


def _ops_lines(ops: dict[str, Any], body: list[str]) -> list[str]:
    if not body:
        return []
    return [*(ops.get("enter") or []), *body, *(ops.get("commit") or []), *(ops.get("leave") or [])]


def _if_cmds(ops: dict[str, Any], names: list[str], action: str) -> list[str]:
    i = ops.get("interface") or {}
    out: list[str] = []
    for n in names:
        out += [
            str(i.get("enter", "interface {name}")).format(name=n),
            " " + str(i.get(action, action)),
            " " + str(i.get("exit", "quit")),
        ]
    return out


def _bgp_cmds(ops: dict[str, Any], asn: Any, peers: list[tuple[str | None, str]], action: str) -> list[str]:
    b = ops.get("bgp") or {}
    if not peers or not b:
        return []
    out = [str(b.get("enter", "bgp {asn}")).format(asn=asn)]
    by_vrf: dict[str | None, list[str]] = defaultdict(list)
    for vrf, p in peers:
        by_vrf[vrf].append(p)
    for vrf in sorted(by_vrf, key=lambda v: (v is not None, v or "")):
        if vrf is None:
            out += [" " + str(b.get(action, "")).format(peer=p) for p in by_vrf[vrf]]
        else:
            out.append(" " + str(b.get("vrf_enter", "")).format(vrf=vrf))
            out += ["  " + str(b.get(action, "")).format(peer=p) for p in by_vrf[vrf]]
            out.append(" " + str(b.get("vrf_exit", "quit")))
    out.append(str(b.get("exit", "quit")))
    return out


def _bgp_peers(g: nx.MultiDiGraph) -> tuple[Any, list[tuple[str | None, str]]]:
    """BGP 本地 AS 与对等体：[(VRF 或 None, 地址)]，公网 / 骨干对等体在前。"""
    asn = None
    peers: list[tuple[str | None, str]] = []
    for n, d in g.nodes(data=True):
        if d.get("kind") != "object":
            continue
        if d.get("schema") == "bgp.instance" and asn is None:
            asn = d.get("key")
        elif d.get("schema") == "bgp.peer" and cmp._is_ipv4_key(d.get("key")):
            peers.append((None, str(d.get("key"))))
        elif d.get("schema") == "bgp.af.peer" and cmp._is_ipv4_key(d.get("key")):
            af = g.nodes[_parent(g, n)]
            key = af.get("key") if isinstance(af.get("key"), dict) else {}
            vrf = str(key.get("vrf") or "") if isinstance(key, dict) else ""
            if vrf:
                peers.append((vrf, str(d.get("key"))))
    uniq = sorted(set(peers), key=lambda x: (x[0] is not None, x[0] or "", x[1]))
    return asn, uniq


def _core_bases(g: nx.MultiDiGraph) -> set[str]:
    """上行（骨干）接口：本身或子接口上有 IGP / MPLS 配置的接口（统一写法的主接口名）。"""
    out: set[str] = set()
    for n, d in g.nodes(data=True):
        s = str(d.get("schema") or "")
        if d.get("origin") == "default" or not re.match(r"^interface\.(ospf|isis|mpls)\b", s):
            continue
        owner = cmp._top(n)
        key = g.nodes[owner].get("key") if owner in g else None
        if key:
            out.add(_base(str(key)))
    return out


def build_steps(
    g_old: nx.MultiDiGraph,
    kb: KnowledgeBase,
    src_profile: str,
    dst_profile: str,
    rows: list[dict[str, Any]],
    has_existing: bool = False,
) -> list[dict[str, Any]]:
    """割接步骤清单：每步 {no, phase, device(old/new/site), key, params, commands[]}；回退步骤 phase=rollback。"""
    so = family_ops(kb, kb.profiles[src_profile].family)
    do = family_ops(kb, kb.profiles[dst_profile].family)
    core = _core_bases(g_old)
    # 聚合口是骨干时，成员口也算骨干
    lag_of: dict[str, int] = {}
    for n, d in g_old.nodes(data=True):
        if d.get("schema") == "interface.lag" and d.get("origin") != "default":
            owner = _parent(g_old, n)
            with contextlib.suppress(TypeError, ValueError):
                lag_of[cmp.interface_name(str(g_old.nodes[owner].get("key")))] = int(d.get("value"))
    core_lags = {parse_port(c).index for c in core if parse_port(c).cls == "lag"}
    phys = [r for r in rows if r["kind"] == "physical"]

    def is_core(r: dict[str, Any]) -> bool:
        c = cmp.interface_name(r["source"])
        return c in core or lag_of.get(c) in core_lags

    core_rows = [r for r in phys if is_core(r)]
    access_rows = [r for r in phys if not is_core(r)]
    asn, peers = _bgp_peers(g_old)
    dom = {str(d.get("schema") or "").split(".", 1)[0] for _, d in g_old.nodes(data=True) if d.get("schema")}
    has = {
        "bgp": bool(peers),
        "ospf": "ospf" in dom,
        "isis": "isis" in dom,
        "ldp": any(str(d.get("schema") or "").startswith("interface.mpls") for _, d in g_old.nodes(data=True)),
        "lag": bool(lag_of),
    }

    def shows(ops: dict[str, Any], names: list[str]) -> list[str]:
        sh = ops.get("show") or {}
        out = [str(sh[k]) for k in names if k in sh and (k not in has or has[k])]
        if "bgp" in names and any(v for v, _ in peers) and "bgp_vrf" in sh:
            out.append(str(sh["bgp_vrf"]))
        return out

    old_names = lambda rs: [r["source"] for r in rs]  # noqa: E731
    new_names = lambda rs: [r["target"] for r in rs]  # noqa: E731
    steps: list[dict[str, Any]] = []

    def add(phase: str, device: str, key: str, commands: list[str], **params: Any) -> None:
        if not commands and key not in ("load_config", "load_delta"):
            return  # 没有要做的（例如没有上行口）
        steps.append(
            {
                "no": len(steps) + 1,
                "phase": phase,
                "device": device,
                "key": f"migrate.step.{key}",
                "params": params,
                "commands": commands,
            }
        )

    check_items = ["interfaces", "routes", "bgp", "ospf", "isis", "ldp", "lag"]
    add("precheck", "old", "precheck", shows(so, [*check_items, "config"]))
    add(
        "prepare",
        "new",
        "load_delta" if has_existing else "load_config",
        [],
        file="delta.cfg" if has_existing else "new-config.cfg",
    )
    add(
        "prepare",
        "new",
        "hold_new",
        _ops_lines(do, _if_cmds(do, new_names(phys), "shutdown") + _bgp_cmds(do, asn, peers, "drain")),
        ports=len(phys),
        peers=len(peers),
    )
    if peers:
        drain_order = sorted(peers, key=lambda x: (x[0] is None, x[0] or "", x[1]))  # VRF（业务）先隔离，骨干后
        add("drain", "old", "drain_bgp", _ops_lines(so, _bgp_cmds(so, asn, drain_order, "drain")), peers=len(peers))
    add(
        "cutover",
        "old",
        "shutdown_old",
        _ops_lines(so, _if_cmds(so, old_names(access_rows) + old_names(core_rows), "shutdown")),
        access=len(access_rows),
        core=len(core_rows),
    )
    add(
        "cutover",
        "site",
        "move_cables",
        [f"{r['source']} -> {r['target']}" for r in core_rows + access_rows],
        ports=len(phys),
    )
    add(
        "enable",
        "new",
        "enable_core",
        _ops_lines(do, _if_cmds(do, new_names(core_rows), "no_shutdown")),
        ports=len(core_rows),
    )
    add("enable", "new", "check_core", shows(do, ["interfaces", "lag", "ospf", "isis", "ldp"]))
    add(
        "enable",
        "new",
        "enable_access",
        _ops_lines(do, _if_cmds(do, new_names(access_rows), "no_shutdown")),
        ports=len(access_rows),
    )
    if peers:
        add("enable", "new", "restore_bgp", _ops_lines(do, _bgp_cmds(do, asn, peers, "restore")), peers=len(peers))
    add("verify", "new", "postcheck", shows(do, check_items))
    # 回退
    add(
        "rollback",
        "new",
        "rb_hold_new",
        _ops_lines(do, _if_cmds(do, new_names(phys), "shutdown") + _bgp_cmds(do, asn, peers, "drain")),
        ports=len(phys),
    )
    add(
        "rollback",
        "site",
        "rb_move_cables",
        [f"{r['target']} -> {r['source']}" for r in core_rows + access_rows],
        ports=len(phys),
    )
    add(
        "rollback",
        "old",
        "rb_enable_old",
        _ops_lines(
            so,
            _if_cmds(so, old_names(core_rows) + old_names(access_rows), "no_shutdown")
            + _bgp_cmds(so, asn, peers, "restore"),
        ),
        ports=len(phys),
        peers=len(peers),
    )
    add("rollback", "old", "rb_check", shows(so, check_items))
    return steps


# ---------------------------------------------------------------- 输出文件


MAP_COLUMNS = [
    "source",
    "target",
    "kind",
    "source_speed",
    "target_speed",
    "basis",
    "confidence",
    "subinterfaces",
    "configured",
]


def map_csv(result: dict[str, Any]) -> str:
    """接口映射表 CSV（可以改了再用 --interface-map 传回）：映射上的在前，未映射的 target 为空、basis 为原因。"""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(MAP_COLUMNS)
    for r in result["interface_map"]:
        w.writerow(
            [
                r["source"],
                r["target"],
                r["kind"],
                "" if r["source_speed"] is None else f"{r['source_speed']:g}",
                "" if r["target_speed"] is None else f"{r['target_speed']:g}",
                r["basis"],
                f"{r['confidence']:.2f}",
                " ".join(r["subinterfaces"]),
                "yes" if r["configured"] else "no",
            ]
        )
    for u in result["unmapped"]:
        w.writerow(
            [
                u["source"],
                "",
                u["kind"],
                "" if u["speed"] is None else f"{u['speed']:g}",
                "",
                u["reason"],
                "",
                " ".join(u["subinterfaces"]),
                "yes" if u["configured"] else "no",
            ]
        )
    return buf.getvalue()


def load_map_file(path: Path) -> dict[str, str]:
    """接口映射表：CSV（map_csv 的格式，至少有 source、target 两列；target 为空的行跳过，为 - 的行表示不迁移），
    其余格式同 compare.load_interface_map（JSON / YAML / 两列文本）。"""
    if path.suffix.lower() != ".csv":
        return cmp.load_interface_map(path)
    if not path.exists():
        raise cmp.CompareError("compare.ifmap_missing", "not_found", path=str(path))
    rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
    if rows and not {"source", "target"} <= set(rows[0].keys()):
        raise cmp.CompareError("compare.ifmap_invalid", path=str(path))
    return {
        str(r["source"]).strip(): str(r["target"]).strip()
        for r in rows
        if str(r.get("source") or "").strip() and str(r.get("target") or "").strip()
    }
