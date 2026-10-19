"""拓扑还原（M4-6）：多台设备的配置图 → 三层拓扑与跨设备依赖边。全部由代码在图上计算，不用 AI。

链路类型（links[].type）与推导规则（basis.rule）：
    subnet      同网段接口：两台设备的接口地址落在同一网段（VRF 内与公网分开，排除 Loopback 与 /32）。
                /30、/31 且恰好两端为点到点（high）；多点网段两两成链（medium）；
                只有一端的掩码包含对端地址（掩码不一致）为 low；任一端 shutdown 时降为 low。
    ospf        OSPF 邻接：同网段链路两端都在 OSPF 中启用（接口下 ospf enable … area，或进程 network 覆盖接口地址）。
    isis        IS-IS 邻接：同网段链路两端都在 IS-IS 中启用（接口下 isis enable / ip router isis）。
    ldp         本地 LDP 会话：同网段链路两端接口都使能 MPLS LDP。
    ldp_remote  远端 LDP 会话：remote-peer 的地址是另一台设备的 LSR ID / Loopback。
    bgp         BGP 对等：对等体地址落在另一台设备的接口 / Loopback 上；本端地址取 update-source / connect-interface，
                没有时取与对端同网段的接口地址。两端互相配置为 high，只有一端配置为 medium。
    pw          L2VPN 伪线：PW 对端地址 = 对端设备的 LSR ID / Loopback；两端 VC ID 相同为 high，
                两台设备之间只剩一对没配上的伪线时按 VC ID 不一致配对（low），否则为单端（medium）。
    bfd         BFD 会话：静态会话的对端地址是另一台设备的接口地址（mode static）；
                同网段链路两端接口都配置了接口 BFD 参数（mode interface）。
每条链路有两端 a / b（设备、接口、地址、端点节点、事实 facts），以及推导依据 basis（规则、两端节点、说明）与置信度。
事实（facts）由代码计算（例如 OSPF 区域要考虑进程下的 network 语句），跨设备一致性规则（core/consistency.py）直接比较它们。

跨设备依赖边（cross_edges）：按 Schema deps 中 kind: cross_device 的规则生成——
    源与终点类型不同：源节点的取值（对象取键）等于另一台设备上终点类型节点的取值；
    源与终点类型相同（例如 interface.ospf.area → interface.ospf.area）：在同网段链路的两端之间连边。
"""

from __future__ import annotations

import ipaddress
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from lmesh.core.kb import KnowledgeBase
from lmesh.core.kb.model import Note

LINK_TYPES = ("subnet", "ospf", "isis", "ldp", "ldp_remote", "bgp", "pw", "bfd")
CONFIDENCE = ("high", "medium", "low")
_HOST = re.compile(r"^\s*(?:sysname|hostname)\s+(\S+)", re.M)
# Nokia（M7-5）：configure > system > name "PE1"（Classic 与 MD-CLI 花括号格式缩进 8 格；info flat 写作 system name "PE1"）
_NOKIA_HOST = re.compile(r'^(?: {8}|(?:/configure )?system )name\s+"?([^"\s]+)"?\s*$', re.M)
_LOOPBACK = re.compile(r"^loopback", re.I)
# Nokia 的 BGP family 取值 → 统一 Schema 的地址族 afi（与 translate._FAMILY 相反方向，M7-5）
_NOKIA_AFI = {
    "ipv4": "ipv4",
    "ipv6": "ipv6",
    "vpn-ipv4": "vpnv4",
    "vpn-ipv6": "vpnv6",
    "evpn": "evpn",
    "l2-vpn": "l2vpn",
}
_MAX_HOSTS = 1024  # 网段内逐个查找对端地址的上限（更大的网段只按相同网段配对）


@dataclass
class Device:
    """参与拓扑还原的一台设备：名称、配置图，以及来源（已导入设备的编号与版本，或文件名）。"""

    name: str
    g: nx.MultiDiGraph
    device_id: int | None = None
    version_id: int | None = None
    source: str = ""


def hostname(text: str) -> str | None:
    m = _HOST.search(text)
    if m:
        return m.group(1)
    from lmesh.core.sanitize import detect_vendor

    if detect_vendor(text) == "nokia":
        m = _NOKIA_HOST.search(text)
        return m.group(1) if m else None
    return None


def unique_names(names: list[str]) -> list[str]:
    """重名时依次加 #2、#3。"""
    seen: dict[str, int] = {}
    out = []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else f"{n}#{seen[n]}")
    return out


# ---------- 单台设备上的索引 ----------


class DevIndex:
    def __init__(self, dev: Device, kb: KnowledgeBase):
        self.dev, self.kb, self.g = dev, kb, dev.g
        self.children: dict[str, list[str]] = defaultdict(list)
        self.parent: dict[str, str] = {}
        self.refs: dict[str, list[str]] = defaultdict(list)
        self.by_schema: dict[str, list[str]] = defaultdict(list)
        for a, b, d in self.g.edges(data=True):
            if d.get("kind") == "contains":
                self.children[a].append(b)
                self.parent[b] = a
            elif d.get("kind") == "reference":
                self.refs[a].append(b)
        for n, d in self.g.nodes(data=True):
            if d.get("schema") and not d.get("negated"):
                self.by_schema[str(d["schema"])].append(n)
        self.profile = str(self.g.graph.get("profile") or "")
        self._defaults: dict[str, Any] | None = None

    def d(self, n: str) -> dict[str, Any]:
        return self.g.nodes[n]  # type: ignore[no-any-return]

    def kids(self, n: str, schema: str) -> list[str]:
        return [
            c for c in self.children.get(n, []) if self.d(c).get("schema") == schema and not self.d(c).get("negated")
        ]

    def kid(self, n: str, schema: str) -> str | None:
        k = self.kids(n, schema)
        return k[0] if k else None

    def val(self, n: str | None, schema: str) -> Any:
        """子属性的有效值（含隐藏的默认值）；没有时 None。"""
        if n is None:
            return None
        c = self.kid(n, schema)
        return self.d(c).get("value") if c else None

    def key(self, n: str) -> str:
        k = self.d(n).get("key")
        if isinstance(k, dict):
            return ",".join(f"{a}={'' if b is None else b}" for a, b in k.items())
        return "" if k is None else str(k)

    def objects(self, schema: str) -> list[str]:
        return [n for n in self.by_schema.get(schema, []) if self.d(n).get("kind") == "object"]

    def profile_default(self, schema: str, siblings: dict[str, Any] | None = None) -> Any:
        """Profile 中登记的缺省值（对象不存在、建图时没有补默认节点的情况，例如只靠 network 语句启用 OSPF 的接口）。"""
        if not self.profile or self.profile not in self.kb.profiles:
            return None
        if self._defaults is None:
            self._defaults = dict(self.kb.resolve_profile(self.profile).entries)
        e = self._defaults.get(schema)
        if e is None or e.default is None or not e.supported:
            return None
        for attr, want in ((e.when or {}).get("attr") or {}).items():
            got = (siblings or {}).get(attr)
            wants = want if isinstance(want, list) else [want]
            if str(got) not in [str(w) for w in wants]:
                return None
        return e.default

    def lines(self, n: str | None) -> list[int]:
        return sorted(self.d(n).get("lines") or []) if n else []


@dataclass
class Iface:
    device: str
    name: str
    node: str
    vrf: str
    loopback: bool
    shutdown: bool
    addrs: list[tuple[ipaddress.IPv4Interface, str, bool]] = field(
        default_factory=list
    )  # (地址, address 节点, secondary)

    @property
    def primary(self) -> ipaddress.IPv4Interface | None:
        prim = [a for a, _, sec in self.addrs if not sec]
        return prim[0] if prim else (self.addrs[0][0] if self.addrs else None)


def _ipv4(text: Any) -> ipaddress.IPv4Address | None:
    try:
        return ipaddress.IPv4Address(str(text).strip())
    except (ValueError, ipaddress.AddressValueError):
        return None


def _wild_net(text: str) -> ipaddress.IPv4Network | None:
    """network 语句的键：“地址 反掩码”或“地址/长度”。"""
    t = text.strip()
    try:
        if "/" in t:
            return ipaddress.IPv4Network(t, strict=False)
        parts = t.split()
        if len(parts) == 2:
            wild = ipaddress.IPv4Address(parts[1])
            mask = ipaddress.IPv4Address(int(wild) ^ 0xFFFFFFFF)
            return ipaddress.IPv4Network(f"{parts[0]}/{mask}", strict=False)
        if len(parts) == 1:
            return ipaddress.IPv4Network(f"{parts[0]}/32")
    except ValueError:
        return None
    return None


def _area(v: Any) -> str | None:
    """OSPF 区域统一成点分写法（0 → 0.0.0.0）。"""
    if v is None or v == "":
        return None
    s = str(v).strip()
    if s.isdigit():
        return str(ipaddress.IPv4Address(int(s)))
    return s


_LEVELS = {"level-1": {"level-1"}, "level-2": {"level-2"}, "level-1-2": {"level-1", "level-2"}}


class DevFacts:
    """单台设备上拓扑推导用到的信息：接口、OSPF / IS-IS / LDP / BGP / PW / BFD。"""

    def __init__(self, dev: Device, kb: KnowledgeBase):
        self.dev, self.ix = dev, DevIndex(dev, kb)
        self.ifaces: dict[str, Iface] = {}
        for n in self.ix.objects("interface"):
            name = self.ix.key(n)
            vrf = self.ix.val(n, "interface.vrf") or ""
            itf = Iface(
                dev.name,
                name,
                n,
                str(vrf),
                bool(_LOOPBACK.match(name)) or self._nokia_loopback(n, name),
                self.ix.val(n, "interface.shutdown") is True or self._port_down(n),
            )
            for a in self.ix.kids(n, "interface.ipv4"):
                addr_node = self.ix.kid(a, "interface.ipv4.address")
                ip = _ipv4(self.ix.d(addr_node).get("value") if addr_node else self.ix.key(a))
                plen = self.ix.val(a, "interface.ipv4.prefix_length")
                if ip is None:
                    continue
                try:
                    itf.addrs.append(
                        (
                            ipaddress.IPv4Interface(f"{ip}/{int(plen) if plen is not None else 32}"),
                            addr_node or a,
                            self.ix.val(a, "interface.ipv4.secondary") is True,
                        )
                    )
                except ValueError:
                    continue
            self.ifaces[name] = itf
        self.lsr_id = self._lsr_id()

    def _nokia_loopback(self, n: str, name: str) -> bool:
        """Nokia 的 system 接口与 loopback 接口（M7-5）：相当于华为 / Cisco 的 Loopback。"""
        if self.ix.val(n, "interface.loopback") is True:
            return True
        return name == "system" and self.ix.val(n, "interface.bind_port") is None

    def _port_down(self, n: str) -> bool:
        """Nokia 路由器接口绑定的端口 / LAG 处于关闭状态（端口缺省关闭，M7-5）：接口实际不通。"""
        port = self.ix.val(n, "interface.bind_port")
        if port in (None, ""):
            return False
        node = f"interface[{port}]"
        return node in self.ix.g and self.ix.val(node, "interface.shutdown") is True

    # ----- 地址 -----

    def addresses(self, vrf: str = "") -> set[str]:
        out = {str(a.ip) for i in self.ifaces.values() if i.vrf == vrf for a, _, _ in i.addrs}
        if vrf == "" and self.lsr_id:
            out.add(self.lsr_id)
        return out

    def iface_addr(self, name: str | None) -> str | None:
        if not name:
            return None
        itf = self.ifaces.get(name) or next((i for i in self.ifaces.values() if i.name.lower() == name.lower()), None)
        p = itf.primary if itf else None
        return str(p.ip) if p else None

    def iface_of(self, ip: str, vrf: str = "") -> Iface | None:
        for i in self.ifaces.values():
            if i.vrf == vrf and any(str(a.ip) == ip for a, _, _ in i.addrs):
                return i
        return None

    def connected(self, ip: str, vrf: str = "") -> Iface | None:
        """与该地址同网段的本端接口（非 Loopback）。"""
        addr = _ipv4(ip)
        if addr is None:
            return None
        for i in self.ifaces.values():
            if i.vrf == vrf and not i.loopback and any(addr in a.network and a.ip != addr for a, _, _ in i.addrs):
                return i
        return None

    def _lsr_id(self) -> str | None:
        ix = self.ix
        for n in ix.objects("mpls.global"):
            v = ix.val(n, "mpls.global.lsr_id")
            if v:
                return str(v)
        for n in ix.objects("mpls.ldp"):
            v = ix.val(n, "mpls.ldp.lsr_id")
            if v:
                return str(v)
            a = self.iface_addr(ix.val(n, "mpls.ldp.router_id_interface"))
            if a:
                return a
        # Nokia（M7-5）：LSR ID 是 system 接口地址，其次 router-id
        sys_if = self.ifaces.get("system")
        if sys_if is not None and sys_if.loopback and sys_if.primary is not None:
            return str(sys_if.primary.ip)
        for n in ix.objects("mgmt.system"):
            v = ix.val(n, "mgmt.system.router_id")
            if v:
                return str(v)
        return None

    # ----- OSPF -----

    def ospf(self, itf: Iface) -> dict[str, Any] | None:
        ix = self.ix
        prim = itf.primary
        on = ix.kid(itf.node, "interface.ospf")
        area, process, via = None, None, None
        if on is not None and ix.val(on, "interface.ospf.area") not in (None, ""):
            area, process, via = ix.val(on, "interface.ospf.area"), ix.val(on, "interface.ospf.process"), "interface"
        proc_node = None
        for p in ix.objects("ospf.process"):
            if str(ix.val(p, "ospf.process.vrf") or "") != itf.vrf:
                continue
            if process is not None:
                if ix.key(p) == str(process):
                    proc_node = p
                    break
                continue
            if prim is None:
                continue
            best: tuple[int, str] | None = None
            for a in ix.kids(p, "ospf.process.area"):
                for nw in ix.kids(a, "ospf.process.area.network"):
                    net = _wild_net(ix.key(nw))
                    if net is not None and prim.ip in net and (best is None or net.prefixlen > best[0]):
                        best = (net.prefixlen, ix.key(a))
            if best is not None:
                area, process, via, proc_node = best[1], ix.key(p), "network", p
                break
        if area is None:
            return None
        passive = None
        if proc_node is not None:
            explicit = next(
                (
                    ix.val(s, "ospf.process.passive.enabled")
                    for s in ix.kids(proc_node, "ospf.process.passive")
                    if ix.key(s).lower() == itf.name.lower()
                ),
                None,
            )
            passive = explicit if explicit is not None else ix.val(proc_node, "ospf.process.passive_default")
        facts: dict[str, Any] = {
            "area": _area(area),
            "process": str(process or ""),
            "via": via,
            "passive": bool(passive),
        }
        for attr in ("network_type", "hello", "dead", "authentication", "priority"):
            v = ix.val(on, f"interface.ospf.{attr}")
            if v is None:
                v = ix.profile_default(f"interface.ospf.{attr}", facts)
            facts[attr] = v
        if facts["authentication"] in (None, "", "none") and proc_node is not None:
            ar = next((a for a in ix.kids(proc_node, "ospf.process.area") if _area(ix.key(a)) == facts["area"]), None)
            facts["authentication"] = ix.val(ar, "ospf.process.area.authentication") or facts["authentication"]
        facts["authentication"] = facts["authentication"] or "none"
        facts["_node"] = on
        return facts

    # ----- IS-IS -----

    def isis(self, itf: Iface) -> dict[str, Any] | None:
        ix = self.ix
        n = ix.kid(itf.node, "interface.isis")
        if n is None:
            return None
        process = ix.val(n, "interface.isis.process")
        procs = ix.objects("isis.process")
        proc = next((p for p in procs if ix.key(p) == str(process)), procs[0] if len(procs) == 1 else None)
        plevel = ix.val(proc, "isis.process.level") or "level-1-2"
        ctype = ix.val(n, "interface.isis.circuit_type") or "level-1-2"
        levels = sorted(_LEVELS.get(str(plevel), set()) & _LEVELS.get(str(ctype), set()))
        areas = sorted(
            {".".join(ix.key(net).split(".")[:-4]) for net in (ix.kids(proc, "isis.process.net") if proc else [])}
        )
        if not areas and proc is not None and ix.val(proc, "isis.process.area_id"):
            areas = [str(ix.val(proc, "isis.process.area_id"))]  # Nokia 的 area-id（M7-5）
        return {
            "process": str(process or ""),
            "levels": levels,
            "areas": areas,
            "p2p": ix.val(n, "interface.isis.p2p") is True,
            "passive": ix.val(n, "interface.isis.passive") is True or self._isis_proc_passive(proc, itf),
            "_node": n,
        }

    def _isis_proc_passive(self, proc: str | None, itf: Iface) -> bool:
        """进程下的被动设置（Cisco passive-interface 写在 router isis 下）：接口例外优先，其次进程缺省。"""
        if proc is None:
            return False
        ix = self.ix
        explicit = next(
            (
                ix.val(s, "isis.process.passive.enabled")
                for s in ix.kids(proc, "isis.process.passive")
                if ix.key(s).lower() == itf.name.lower()
            ),
            None,
        )
        return bool(explicit if explicit is not None else ix.val(proc, "isis.process.passive_default"))

    # ----- LDP -----

    def ldp(self, itf: Iface) -> bool:
        m = self.ix.kid(itf.node, "interface.mpls")
        return m is not None and self.ix.val(m, "interface.mpls.ldp") is True

    def ldp_auth(self, peer_lsr: str | None) -> bool:
        if not peer_lsr:
            return False
        return any(
            self.ix.key(a) == peer_lsr and self.ix.val(a, "mpls.ldp.auth.password") not in (None, "")
            for a in self.ix.objects("mpls.ldp.auth")
        )

    def ldp_remote(self) -> list[dict[str, Any]]:
        out = []
        for n in self.ix.objects("mpls.ldp.remote_peer"):
            ip = self.ix.val(n, "mpls.ldp.remote_peer.remote_ip") or self.ix.key(n)
            if _ipv4(ip):
                out.append({"node": n, "peer": str(ip)})
        return out

    # ----- BGP -----

    def bgp_peers(self) -> list[dict[str, Any]]:
        ix = self.ix
        out = []
        for inst in ix.objects("bgp.instance"):
            asn = ix.key(inst)
            groups = {ix.key(gn): gn for gn in ix.kids(inst, "bgp.peer_group")}
            afs = [(af, ix.d(af).get("key") or {}) for af in ix.kids(inst, "bgp.af")]
            for p in ix.kids(inst, "bgp.peer"):
                addr = ix.key(p)
                if _ipv4(addr) is None:
                    continue
                gname = ix.val(p, "bgp.peer.group")
                gn = groups.get(str(gname)) if gname else None
                remote_as = ix.val(p, "bgp.peer.remote_as") or ix.val(gn, "bgp.peer_group.remote_as")
                if remote_as in (None, "") and ix.val(gn, "bgp.peer_group.type") == "internal":
                    remote_as = asn
                upd = ix.val(p, "bgp.peer.update_source") or ix.val(gn, "bgp.peer_group.update_source")
                auth = ix.val(p, "bgp.peer.password") not in (None, "") or (
                    ix.val(gn, "bgp.peer_group.password") not in (None, "")
                )
                enabled: set[str] = set()
                unknown_afs = False
                # Nokia 在 bgp / group 下写 family（M7-5）：组的 family 优先，其次全局 family。MD-CLI 的 family 是逐个布尔叶子、
                # 还没有归并（图里只有缺省值），这时地址族记为未知，不参与比较
                fam_node = ix.kid(gn, "bgp.peer_group.family") if gn else None
                fam_node = fam_node or ix.kid(inst, "bgp.instance.family")
                if fam_node is not None and not any(not key.get("vrf") for _, key in afs):
                    if ix.d(fam_node).get("origin") == "default" and self.dev.g.graph.get("family") == "nokia-sros-md":
                        unknown_afs = True
                    fam = ix.d(fam_node).get("value") or ""
                    enabled |= {_NOKIA_AFI[f] for f in str(fam).split() if f in _NOKIA_AFI}
                for af, key in afs:
                    if key.get("vrf"):
                        continue
                    for ap in ix.kids(af, "bgp.af.peer"):
                        k = ix.key(ap)
                        if (k == addr or (gname and k == str(gname))) and ix.val(
                            ap, "bgp.af.peer.enabled"
                        ) is not False:
                            enabled.add(str(key.get("afi") or ""))
                local = self.iface_addr(str(upd)) if upd else None
                if local is None and upd and _ipv4(upd):
                    local = str(upd)  # Nokia local-address 直接写地址（M7-5）
                if local is None:
                    c = self.connected(addr)
                    local = str(c.primary.ip) if c and c.primary else None
                out.append(
                    {
                        "node": p,
                        "address": addr,
                        "local_as": asn,
                        "remote_as": None if remote_as in (None, "") else str(remote_as),
                        "update_source": str(upd) if upd else None,
                        "local_address": local,
                        "auth": auth,
                        "afs": None if unknown_afs else sorted(enabled),
                        "vrf": "",
                    }
                )
            # VPN 实例（VRF）内的对等体（PE–CE，M4-2 起知识库有 bgp.af.peer.remote_as）：只在该 VRF 的地址族中存在
            for af, key in afs:
                vrf = str(key.get("vrf") or "")
                if not vrf:
                    continue
                for ap in ix.kids(af, "bgp.af.peer"):
                    addr = ix.key(ap)
                    remote_as = ix.val(ap, "bgp.af.peer.remote_as")
                    if _ipv4(addr) is None or remote_as in (None, ""):
                        continue
                    upd = ix.val(ap, "bgp.af.peer.update_source")
                    local = self.iface_addr(str(upd)) if upd else None
                    if local is None:
                        c = self.connected(addr, vrf)
                        local = str(c.primary.ip) if c and c.primary else None
                    enabled_vrf = [] if ix.val(ap, "bgp.af.peer.enabled") is False else [str(key.get("afi") or "")]
                    out.append(
                        {
                            "node": ap,
                            "address": addr,
                            "local_as": asn,
                            "remote_as": str(remote_as),
                            "update_source": str(upd) if upd else None,
                            "local_address": local,
                            "auth": ix.val(ap, "bgp.af.peer.password") not in (None, ""),
                            "afs": enabled_vrf,
                            "vrf": vrf,
                        }
                    )
        return out

    # ----- 伪线 -----

    def pws(self) -> list[dict[str, Any]]:
        ix = self.ix
        classes = {ix.key(c): c for c in ix.objects("l2vpn.pw_class")}
        out = []
        for n in ix.objects("interface.access.pw"):
            cls = classes.get(str(ix.val(n, "interface.access.pw.pw_class") or ""))
            peer = ix.val(n, "interface.access.pw.peer") or ix.val(cls, "l2vpn.pw_class.peer")
            cw = ix.val(n, "interface.access.pw.control_word")
            if cw is None:
                cw = ix.val(cls, "l2vpn.pw_class.control_word")
            itf = n
            while itf in ix.parent and ix.d(itf).get("schema") != "interface":
                itf = ix.parent[itf]
            out.append(
                {
                    "node": n,
                    "kind": "vpws",
                    "peer": str(peer) if peer else None,
                    "vc_id": ix.val(n, "interface.access.pw.vc_id"),
                    "role": ix.key(n),
                    "attachment": ix.key(itf) if ix.d(itf).get("schema") == "interface" else "",
                    "control_word": cw is True,
                    "mtu": ix.val(cls, "l2vpn.pw_class.mtu"),
                }
            )
        for n in ix.objects("l2vpn.xconnect.pw"):
            key = ix.d(n).get("key") or {}
            cls = classes.get(str(ix.val(n, "l2vpn.xconnect.pw.pw_class") or ""))
            xc = ix.parent.get(n, n)
            out.append(
                {
                    "node": n,
                    "kind": "vpws",
                    "peer": str(key.get("peer")) if key.get("peer") else None,
                    "vc_id": key.get("vc_id"),
                    "role": "primary",
                    "attachment": ix.key(xc),
                    "control_word": ix.val(cls, "l2vpn.pw_class.control_word") is True,
                    "mtu": ix.val(cls, "l2vpn.pw_class.mtu"),
                }
            )
        for n in ix.objects("l2vpn.vsi.peer"):
            vsi = ix.parent.get(n, n)
            cls = classes.get(str(ix.val(n, "l2vpn.vsi.peer.pw_class") or ""))
            out.append(
                {
                    "node": n,
                    "kind": "vpls",
                    "peer": ix.key(n),
                    "vc_id": ix.val(n, "l2vpn.vsi.peer.vc_id") or ix.val(vsi, "l2vpn.vsi.vsi_id"),
                    "role": "vsi",
                    "attachment": ix.key(vsi),
                    "control_word": ix.val(cls, "l2vpn.pw_class.control_word") is True,
                    "mtu": ix.val(vsi, "l2vpn.vsi.mtu") or ix.val(cls, "l2vpn.pw_class.mtu"),
                }
            )
        for p in out:
            p["vc_id"] = None if p["vc_id"] in (None, "") else str(p["vc_id"])
        return [p for p in out if p["peer"] and _ipv4(p["peer"])]

    # ----- BFD -----

    def bfd_sessions(self) -> list[dict[str, Any]]:
        ix = self.ix
        out = []
        for n in ix.objects("bfd.session"):
            peer = ix.val(n, "bfd.session.peer")
            if not _ipv4(peer):
                continue
            out.append(
                {
                    "node": n,
                    "peer": str(peer),
                    "interface": ix.val(n, "bfd.session.interface"),
                    "local_discr": _s(ix.val(n, "bfd.session.local_discriminator")),
                    "remote_discr": _s(ix.val(n, "bfd.session.remote_discriminator")),
                    "min_tx": _s(ix.val(n, "bfd.session.min_tx")),
                    "min_rx": _s(ix.val(n, "bfd.session.min_rx")),
                    "multiplier": _s(ix.val(n, "bfd.session.multiplier")),
                }
            )
        return out

    def bfd_iface(self, itf: Iface) -> dict[str, Any] | None:
        n = self.ix.kid(itf.node, "interface.bfd")
        if n is None:
            return None
        return {
            "node": n,
            "min_tx": _s(self.ix.val(n, "interface.bfd.min_tx")),
            "min_rx": _s(self.ix.val(n, "interface.bfd.min_rx")),
            "multiplier": _s(self.ix.val(n, "interface.bfd.multiplier")),
        }


def _s(v: Any) -> str | None:
    return None if v in (None, "") else str(v)


# ---------- 拓扑 ----------


@dataclass
class Topology:
    devices: list[Device]
    facts: dict[str, DevFacts]
    links: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    cross_edges: list[dict[str, Any]] = field(default_factory=list)
    duplicates: list[dict[str, Any]] = field(default_factory=list)  # 同一地址出现在多台设备上（同一 VRF）

    def link(self, link_id: str) -> dict[str, Any] | None:
        return next((lk for lk in self.links if lk["id"] == link_id), None)


def _end(
    dev: str, interface: str | None, address: str | None, node: str | None, facts: dict[str, Any]
) -> dict[str, Any]:
    return {"device": dev, "interface": interface, "address": address, "node": node, "facts": facts}


def _link_id(kind: str, a: dict[str, Any], b: dict[str, Any], extra: str = "") -> str:
    def side(e: dict[str, Any]) -> str:
        return f"{e['device']}:{e.get('interface') or e.get('address') or '-'}"

    return f"{kind}:{side(a)}~{side(b)}" + (f"#{extra}" if extra else "")


def _order(a: dict[str, Any], b: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """两端按（设备、接口 / 地址）排序，结果稳定。"""
    ka = (a["device"], a.get("interface") or "", a.get("address") or "")
    kb = (b["device"], b.get("interface") or "", b.get("address") or "")
    return (a, b) if ka <= kb else (b, a)


class _Resolver:
    """地址 → 设备：接口地址（含 Loopback）与 LSR ID。"""

    def __init__(self, facts: dict[str, DevFacts]):
        self.by_ip: dict[tuple[str, str], list[tuple[str, Iface | None]]] = defaultdict(list)
        for name, f in facts.items():
            for i in f.ifaces.values():
                for a, _, _ in i.addrs:
                    self.by_ip[(i.vrf, str(a.ip))].append((name, i))
            if f.lsr_id and not any(d == name for d, _ in self.by_ip.get(("", f.lsr_id), [])):
                self.by_ip[("", f.lsr_id)].append((name, None))

    def owner(self, ip: str, vrf: str = "", exclude: str | None = None) -> tuple[str, Iface | None] | None:
        hits = [h for h in self.by_ip.get((vrf, ip), []) if h[0] != exclude]
        return hits[0] if len(hits) == 1 else (hits[0] if hits else None)


def build(devices: list[Device], kb: KnowledgeBase) -> Topology:
    facts = {d.name: DevFacts(d, kb) for d in devices}
    topo = Topology(devices, facts)
    res = _Resolver(facts)
    topo.duplicates = _duplicates(facts)
    subnet_links = _subnet_links(topo)
    topo.links += subnet_links
    for lk in subnet_links:
        topo.links += _on_subnet(topo, lk)
    topo.links += _bgp_links(topo, res)
    topo.links += _ldp_remote_links(topo, res)
    topo.links += _pw_links(topo, res)
    topo.links += _bfd_session_links(topo, res)
    topo.cross_edges = _cross_edges(topo, kb)
    topo.links.sort(key=lambda lk: (LINK_TYPES.index(lk["type"]), lk["id"]))
    return topo


# ----- 同网段 -----


def _duplicates(facts: dict[str, DevFacts]) -> list[dict[str, Any]]:
    """同一 VRF 中同一地址出现在多台设备上（含 Loopback）。"""
    by_ip: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for f in facts.values():
        for i in f.ifaces.values():
            for a, node, _ in i.addrs:
                by_ip[(i.vrf, str(a.ip))].append({"device": i.device, "interface": i.name, "node": node})
    return [
        {"vrf": vrf, "address": ip, "ends": ends}
        for (vrf, ip), ends in sorted(by_ip.items())
        if len({e["device"] for e in ends}) > 1
    ]


def _subnet_links(topo: Topology) -> list[dict[str, Any]]:
    entries: list[tuple[Iface, ipaddress.IPv4Interface, str]] = []
    for f in topo.facts.values():
        for i in f.ifaces.values():
            if i.loopback:
                continue
            for a, node, _ in i.addrs:
                if a.network.prefixlen < 32:
                    entries.append((i, a, node))
    by_ip: dict[tuple[str, str], list[int]] = defaultdict(list)
    by_net: dict[tuple[str, str], list[int]] = defaultdict(list)
    for k, (i, a, _) in enumerate(entries):
        by_ip[(i.vrf, str(a.ip))].append(k)
        by_net[(i.vrf, str(a.network))].append(k)
    pairs: dict[tuple[int, int], str] = {}  # (k1, k2) → 方式：same / mask
    for (_vrf, _net), ks in by_net.items():
        for x in range(len(ks)):
            for y in range(x + 1, len(ks)):
                k1, k2 = ks[x], ks[y]
                if entries[k1][0].device != entries[k2][0].device:
                    pairs[(min(k1, k2), max(k1, k2))] = "same"
    for k, (i, a, _) in enumerate(entries):  # 掩码不一致：对端地址落在本端网段内，但两端网段不同
        if a.network.num_addresses > _MAX_HOSTS:
            continue
        for host in a.network:
            for k2 in by_ip.get((i.vrf, str(host)), []):
                i2 = entries[k2][0]
                if i2.device != i.device and entries[k2][1].network != a.network:
                    pairs.setdefault((min(k, k2), max(k, k2)), "mask")
    members = {key: len({entries[k][0].device for k in ks}) for key, ks in by_net.items()}
    out = []
    for (k1, k2), how in sorted(pairs.items()):
        (i1, a1, n1), (i2, a2, n2) = entries[k1], entries[k2]
        net_key = (i1.vrf, str(a1.network))
        p2p = how == "same" and a1.network.prefixlen >= 30 and members.get(net_key, 0) == 2
        confidence = "high" if p2p else ("medium" if how == "same" else "low")
        if i1.shutdown or i2.shutdown:
            confidence = "low"
        ea = _end(i1.device, i1.name, str(a1.ip), i1.node, _subnet_facts(topo.facts[i1.device], i1, a1))
        eb = _end(i2.device, i2.name, str(a2.ip), i2.node, _subnet_facts(topo.facts[i2.device], i2, a2))
        first = ea
        ea, eb = _order(ea, eb)
        if ea is not first:
            (a1, n1), (a2, n2) = (a2, n2), (a1, n1)
        rule = {"same": "subnet.same_network", "mask": "subnet.mask_overlap"}[how]
        if p2p:
            rule = "subnet.p2p"
        out.append(
            {
                "id": _link_id("subnet", ea, eb),
                "type": "subnet",
                "a": ea,
                "b": eb,
                "vrf": i1.vrf,
                "segment": str(a1.network) if how == "same" else f"{a1.network} / {a2.network}",
                "p2p": p2p,
                "confidence": confidence,
                "basis": {
                    "rule": rule,
                    "a_node": n1,
                    "b_node": n2,
                    "detail": f"{a1.with_prefixlen} ~ {a2.with_prefixlen}",
                },
            }
        )
    return out


def _subnet_facts(f: DevFacts, itf: Iface, a: ipaddress.IPv4Interface) -> dict[str, Any]:
    return {
        "address": str(a.ip),
        "prefix_length": a.network.prefixlen,
        "network": str(a.network),
        "vrf": itf.vrf,
        "shutdown": itf.shutdown,
        "mtu": _s(f.ix.val(itf.node, "interface.mtu")),
        "ospf": f.ospf(itf) is not None,
        "isis": f.isis(itf) is not None,
        "ldp": f.ldp(itf),
        "bfd": f.ix.kid(itf.node, "interface.bfd") is not None,
    }


def _on_subnet(topo: Topology, lk: dict[str, Any]) -> list[dict[str, Any]]:
    """同网段链路上的 OSPF / IS-IS 邻接、本地 LDP 会话、接口 BFD。"""
    fa, fb = topo.facts[lk["a"]["device"]], topo.facts[lk["b"]["device"]]
    ia, ib = fa.ifaces[lk["a"]["interface"]], fb.ifaces[lk["b"]["interface"]]
    out = []

    def mk(kind: str, facts_a: dict[str, Any], facts_b: dict[str, Any], rule: str, confidence: str) -> None:
        na, nb = facts_a.pop("_node", None) or ia.node, facts_b.pop("_node", None) or ib.node
        ea = _end(ia.device, ia.name, lk["a"]["address"], ia.node, facts_a)
        eb = _end(ib.device, ib.name, lk["b"]["address"], ib.node, facts_b)
        out.append(
            {
                "id": _link_id(kind, ea, eb),
                "type": kind,
                "a": ea,
                "b": eb,
                "vrf": lk["vrf"],
                "segment": lk["segment"],
                "over": lk["id"],
                "confidence": confidence if lk["confidence"] != "low" else "low",
                "basis": {"rule": rule, "a_node": na, "b_node": nb, "detail": lk["segment"]},
            }
        )

    oa, ob = fa.ospf(ia), fb.ospf(ib)
    if oa and ob:
        same = oa["area"] == ob["area"] and not oa["passive"] and not ob["passive"]
        mk("ospf", oa, ob, "ospf.both_enabled", "high" if same else "medium")
    sa, sb = fa.isis(ia), fb.isis(ib)
    if sa and sb:
        ok = bool(set(sa["levels"]) & set(sb["levels"])) and not sa["passive"] and not sb["passive"]
        mk("isis", sa, sb, "isis.both_enabled", "high" if ok else "medium")
    if fa.ldp(ia) and fb.ldp(ib):
        mk(
            "ldp",
            {"ldp": True, "auth": fa.ldp_auth(fb.lsr_id), "lsr_id": fa.lsr_id},
            {"ldp": True, "auth": fb.ldp_auth(fa.lsr_id), "lsr_id": fb.lsr_id},
            "ldp.both_enabled",
            "high",
        )
    ba, bb = fa.bfd_iface(ia), fb.bfd_iface(ib)
    if ba and bb:
        ba_f = {"mode": "interface", "static": False, "configured": True, **ba}
        bb_f = {"mode": "interface", "static": False, "configured": True, **bb}
        ba_f["_node"], bb_f["_node"] = ba.get("node"), bb.get("node")
        ba_f.pop("node", None)
        bb_f.pop("node", None)
        mk("bfd", ba_f, bb_f, "bfd.interface_both", "high")
    return out


# ----- BGP -----


def _bgp_links(topo: Topology, res: _Resolver) -> list[dict[str, Any]]:
    peers = {name: f.bgp_peers() for name, f in topo.facts.items()}
    sessions: dict[tuple[str, tuple[tuple[str, str], tuple[str, str]]], dict[str, Any]] = {}
    for dname, plist in peers.items():
        for p in plist:
            vrf = p.get("vrf") or ""
            hit = res.owner(p["address"], vrf, exclude=dname)
            if hit is None:
                topo.unresolved.append(
                    {"type": "bgp", "device": dname, "node": p["node"], "address": p["address"], "vrf": vrf}
                )
                continue
            ename, eitf = hit
            mine = topo.facts[dname].addresses(vrf)
            back = [
                q
                for q in peers.get(ename, [])
                if (q.get("vrf") or "") == vrf
                and q["address"] in mine
                and (p["local_address"] is None or q["address"] == p["local_address"])
            ]
            q = back[0] if back else None
            addr_d = q["address"] if q else (p["local_address"] or "?")
            key = tuple(sorted([(dname, addr_d), (ename, p["address"])]))
            s = sessions.setdefault((vrf, key), {"ends": {}, "vrf": vrf})  # type: ignore[arg-type]
            s["ends"][(dname, addr_d)] = p
            s["ends"].setdefault((ename, p["address"]), q)
            s.setdefault("iface", {})[(ename, p["address"])] = eitf.name if eitf else None
    out = []
    for (vrf, key), s in sorted(sessions.items()):
        ends = []
        for dev, addr in key:
            p = s["ends"].get((dev, addr))
            f = topo.facts[dev]
            itf = f.iface_of(addr, vrf) if addr != "?" else None
            facts = {
                "configured": p is not None,
                "local_address": addr if addr != "?" else None,
                "peer_address": p["address"] if p else None,
                "local_as": p["local_as"] if p else _local_as(f),
                "remote_as": p["remote_as"] if p else None,
                "update_source": p["update_source"] if p else None,
                "auth": p["auth"] if p else False,
                "afs": p["afs"] if p else [],
            }
            ends.append(_end(dev, itf.name if itf else None, facts["local_address"], p["node"] if p else None, facts))
        ea, eb = _order(ends[0], ends[1])
        both = ea["node"] is not None and eb["node"] is not None
        out.append(
            {
                "id": _link_id("bgp", ea, eb),
                "type": "bgp",
                "a": ea,
                "b": eb,
                "vrf": vrf,
                "segment": None,
                "ibgp": ea["facts"]["local_as"] == eb["facts"]["local_as"],
                "confidence": "high" if both else "medium",
                "basis": {
                    "rule": "bgp.peer_address" if both else "bgp.peer_address_one_sided",
                    "a_node": ea["node"] or _addr_node(topo, ea),
                    "b_node": eb["node"] or _addr_node(topo, eb),
                    "detail": f"{ea['address'] or '?'} ~ {eb['address'] or '?'}",
                },
            }
        )
    return out


def _local_as(f: DevFacts) -> str | None:
    inst = f.ix.objects("bgp.instance")
    return f.ix.key(inst[0]) if inst else None


def _addr_node(topo: Topology, e: dict[str, Any]) -> str | None:
    f = topo.facts[e["device"]]
    itf = f.ifaces.get(e.get("interface") or "")
    if itf is None:
        return None
    return next((n for a, n, _ in itf.addrs if str(a.ip) == e.get("address")), itf.node)


# ----- 远端 LDP -----


def _ldp_remote_links(topo: Topology, res: _Resolver) -> list[dict[str, Any]]:
    rp = {name: f.ldp_remote() for name, f in topo.facts.items()}
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for dname, lst in rp.items():
        for r in lst:
            hit = res.owner(r["peer"], "", exclude=dname)
            if hit is None:
                topo.unresolved.append({"type": "ldp_remote", "device": dname, "node": r["node"], "address": r["peer"]})
                continue
            ename = hit[0]
            pair = tuple(sorted([dname, ename]))
            s = seen.setdefault(pair, {})  # type: ignore[arg-type]
            s[dname] = r
    out = []
    for (d1, d2), s in sorted(seen.items()):
        ends = []
        for dev, other in ((d1, d2), (d2, d1)):
            rp_: dict[str, Any] | None = s.get(dev)
            f, fo = topo.facts[dev], topo.facts[other]
            facts = {
                "configured": rp_ is not None,
                "peer": rp_["peer"] if rp_ else None,
                "lsr_id": f.lsr_id,
                "auth": f.ldp_auth(fo.lsr_id),
            }
            ends.append(_end(dev, None, f.lsr_id, rp_["node"] if rp_ else None, facts))
        ea, eb = _order(ends[0], ends[1])
        both = ea["node"] is not None and eb["node"] is not None
        out.append(
            {
                "id": _link_id("ldp_remote", ea, eb),
                "type": "ldp_remote",
                "a": ea,
                "b": eb,
                "vrf": "",
                "segment": None,
                "confidence": "high" if both else "medium",
                "basis": {
                    "rule": "ldp.remote_peer_lsr_id",
                    "a_node": ea["node"],
                    "b_node": eb["node"],
                    "detail": f"{ea['address'] or '?'} ~ {eb['address'] or '?'}",
                },
            }
        )
    return out


# ----- 伪线 -----


def _pw_links(topo: Topology, res: _Resolver) -> list[dict[str, Any]]:
    by_pair: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for dname, f in topo.facts.items():
        for p in f.pws():
            hit = res.owner(str(p["peer"]), "", exclude=dname)
            if hit is None:
                topo.unresolved.append({"type": "pw", "device": dname, "node": p["node"], "address": p["peer"]})
                continue
            pair = tuple(sorted([dname, hit[0]]))
            by_pair[pair][dname].append(p)  # type: ignore[index]
    out = []
    for (d1, d2), sides in sorted(by_pair.items()):
        l1, l2 = list(sides.get(d1, [])), list(sides.get(d2, []))
        matched: list[tuple[dict[str, Any] | None, dict[str, Any] | None, str, str]] = []
        for p in list(l1):
            q = next((x for x in l2 if x["kind"] == p["kind"] and x["vc_id"] == p["vc_id"]), None)
            if q is not None:
                l1.remove(p)
                l2.remove(q)
                matched.append((p, q, "pw.peer_lsr_id_vc_id", "high"))
        for kind in ("vpws", "vpls"):
            r1 = [p for p in l1 if p["kind"] == kind]
            r2 = [q for q in l2 if q["kind"] == kind]
            if len(r1) == 1 and len(r2) == 1:
                matched.append((r1[0], r2[0], "pw.peer_lsr_id_vc_mismatch", "low"))
                l1.remove(r1[0])
                l2.remove(r2[0])
        matched += [(p, None, "pw.peer_lsr_id_one_sided", "medium") for p in l1]
        matched += [(None, q, "pw.peer_lsr_id_one_sided", "medium") for q in l2]
        for pp, qq, rule, conf in matched:
            ends = []
            for dev, x in ((d1, pp), (d2, qq)):
                f = topo.facts[dev]
                facts = {
                    "configured": x is not None,
                    "kind": x["kind"] if x else None,
                    "peer": x["peer"] if x else None,
                    "vc_id": x["vc_id"] if x else None,
                    "role": x["role"] if x else None,
                    "attachment": x["attachment"] if x else None,
                    "control_word": x["control_word"] if x else None,
                    "mtu": _s(x["mtu"]) if x else None,
                    "lsr_id": f.lsr_id,
                }
                ends.append(_end(dev, x["attachment"] if x else None, f.lsr_id, x["node"] if x else None, facts))
            ea, eb = _order(ends[0], ends[1])
            vc = (pp or qq or {}).get("vc_id") or "-"
            out.append(
                {
                    "id": _link_id("pw", ea, eb, str(vc)),
                    "type": "pw",
                    "a": ea,
                    "b": eb,
                    "vrf": "",
                    "segment": None,
                    "confidence": conf,
                    "basis": {
                        "rule": rule,
                        "a_node": ea["node"],
                        "b_node": eb["node"],
                        "detail": f"vc {ea['facts']['vc_id'] or '-'} ~ vc {eb['facts']['vc_id'] or '-'}",
                    },
                }
            )
    return out


# ----- BFD 静态会话 -----


def _bfd_session_links(topo: Topology, res: _Resolver) -> list[dict[str, Any]]:
    sess = {name: f.bfd_sessions() for name, f in topo.facts.items()}
    pairs: dict[tuple[tuple[str, str], tuple[str, str]], dict[tuple[str, str], dict[str, Any] | None]] = {}
    for dname, lst in sess.items():
        f = topo.facts[dname]
        for s in lst:
            itf = f.ifaces.get(str(s["interface"] or ""))
            vrf = itf.vrf if itf else ""
            hit = res.owner(s["peer"], vrf, exclude=dname)
            if hit is None:
                topo.unresolved.append({"type": "bfd", "device": dname, "node": s["node"], "address": s["peer"]})
                continue
            ename = hit[0]
            local = f.connected(s["peer"], vrf)
            laddr = str(local.primary.ip) if local and local.primary else "?"
            key = tuple(sorted([(dname, laddr), (ename, s["peer"])]))
            ends = pairs.setdefault(key, {})  # type: ignore[arg-type]
            ends[(dname, laddr)] = s
    out = []
    for key, ends in sorted(pairs.items()):
        es = []
        for dev, addr in key:
            one = ends.get((dev, addr))
            itf = topo.facts[dev].iface_of(addr) if addr != "?" else None
            facts = {
                "mode": "static",
                "static": True,
                "configured": one is not None,
                **{k: (one or {}).get(k) for k in ("local_discr", "remote_discr", "min_tx", "min_rx", "multiplier")},
            }
            es.append(
                _end(dev, itf.name if itf else None, None if addr == "?" else addr, one["node"] if one else None, facts)
            )
        ea, eb = _order(es[0], es[1])
        both = ea["node"] is not None and eb["node"] is not None
        out.append(
            {
                "id": _link_id("bfd", ea, eb, "static"),
                "type": "bfd",
                "a": ea,
                "b": eb,
                "vrf": "",
                "segment": None,
                "confidence": "high" if both else "medium",
                "basis": {
                    "rule": "bfd.session_peer",
                    "a_node": ea["node"],
                    "b_node": eb["node"],
                    "detail": f"{ea['address'] or '?'} ~ {eb['address'] or '?'}",
                },
            }
        )
    return out


# ----- 跨设备依赖边 -----


def _values(ix: DevIndex, n: str) -> list[str]:
    d = ix.d(n)
    if d.get("kind") == "object":
        return [ix.key(n)]
    v = d.get("value")
    return [str(x) for x in (v if isinstance(v, list) else [v]) if x not in (None, "", True, False)]


def _cross_edges(topo: Topology, kb: KnowledgeBase) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for r in (d for d in kb.deps if d.kind == "cross_device"):
        rule = f"{r.src}->{r.dst}"

        def applies(f: DevFacts, r: Any = r) -> bool:
            p = f.ix.profile
            return not r.profiles or p in r.profiles or bool(set(r.profiles) & set(f.ix.kb.lineage(p)))

        def add(sd: str, sn: str, dd: str, dn: str, value: str, rule: str = rule, note: Note = r.note) -> None:
            k = (rule, sd, sn, dd, dn)
            if k not in seen:
                seen.add(k)
                out.append(
                    {
                        "kind": "cross_device",
                        "rule": rule,
                        "note": note,
                        "value": value,
                        "src": {"device": sd, "node": sn},
                        "dst": {"device": dd, "node": dn},
                    }
                )

        if r.src == r.dst:  # 链路两端的同类节点
            for lk in topo.links:
                if lk["type"] != "subnet":
                    continue
                fa, fb = topo.facts[lk["a"]["device"]], topo.facts[lk["b"]["device"]]
                if not (applies(fa) and applies(fb)):
                    continue
                na = [n for n in fa.ix.by_schema.get(r.src, []) if n.startswith(lk["a"]["node"] + "/")]
                nb = [n for n in fb.ix.by_schema.get(r.src, []) if n.startswith(lk["b"]["node"] + "/")]
                for x in na:
                    for y in nb:
                        add(lk["a"]["device"], x, lk["b"]["device"], y, ",".join(_values(fa.ix, x)))
            continue
        index: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for name, f in topo.facts.items():
            for n in f.ix.by_schema.get(r.dst, []):
                if f.ix.d(n).get("origin") == "default":
                    continue
                for v in _values(f.ix, n):
                    index[v].append((name, n))
        for name, f in topo.facts.items():
            if not applies(f):
                continue
            for n in f.ix.by_schema.get(r.src, []):
                if f.ix.d(n).get("origin") == "default":
                    continue
                for v in _values(f.ix, n):
                    for dname, dn in index.get(v, []):
                        if dname != name:
                            add(name, n, dname, dn, v)
    out.sort(key=lambda e: (e["rule"], e["src"]["device"], e["src"]["node"], e["dst"]["device"], e["dst"]["node"]))
    return out


# ---------- 输出 ----------


def _clean(facts: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in facts.items() if not k.startswith("_")}


def to_json(topo: Topology) -> dict[str, Any]:
    """适合画拓扑图的结构：nodes（设备）、links（两端设备与接口、网段、推导依据、类型、置信度）、
    cross_edges（跨设备依赖边）、unresolved（对端不在这批设备中的对等体 / 伪线 / 会话）、duplicates（地址冲突）。"""
    nodes = []
    degree: dict[str, int] = defaultdict(int)
    for lk in topo.links:
        degree[lk["a"]["device"]] += 1
        degree[lk["b"]["device"]] += 1
    for d in topo.devices:
        f = topo.facts[d.name]
        loops = sorted(str(a.ip) for i in f.ifaces.values() if i.loopback and i.vrf == "" for a, _, _ in i.addrs)
        nodes.append(
            {
                "id": d.name,
                "device_id": d.device_id,
                "version_id": d.version_id,
                "source": d.source,
                "profile": d.g.graph.get("profile"),
                "family": d.g.graph.get("family"),
                "loopbacks": loops,
                "lsr_id": f.lsr_id,
                "asn": _local_as(f),
                "interfaces": len(f.ifaces),
                "links": degree.get(d.name, 0),
            }
        )
    links = []
    for lk in topo.links:
        item = dict(lk)
        item["a"] = {**lk["a"], "facts": _clean(lk["a"]["facts"])}
        item["b"] = {**lk["b"], "facts": _clean(lk["b"]["facts"])}
        links.append(item)
    by_type = {t: 0 for t in LINK_TYPES}
    by_conf = {c: 0 for c in CONFIDENCE}
    for lk in topo.links:
        by_type[lk["type"]] += 1
        by_conf[lk["confidence"]] += 1
    return {
        "nodes": nodes,
        "links": links,
        "cross_edges": topo.cross_edges,
        "unresolved": sorted(topo.unresolved, key=lambda u: (u["type"], u["device"], u["address"])),
        "duplicates": topo.duplicates,
        "summary": {
            "devices": len(topo.devices),
            "links": len(topo.links),
            "by_type": by_type,
            "by_confidence": by_conf,
            "cross_edges": len(topo.cross_edges),
            "unresolved": len(topo.unresolved),
            "duplicates": len(topo.duplicates),
        },
    }


# ---------- 设备来源 ----------


def from_texts(items: list[dict[str, Any]], kb: KnowledgeBase) -> list[Device]:
    """items：[{name, text, profile}]；设备名取配置中的 sysname / hostname，没有时用 name。
    解析失败（无法识别厂商或 Profile）时抛出 analysis.AnalysisError，参数里带 name。"""
    from lmesh.core import analysis
    from lmesh.core import graph as graphmod

    parsed = []
    for it in items:
        text = str(it.get("text") or "")
        try:
            res = analysis.parse_text(text, kb, it.get("profile") or None)
        except analysis.AnalysisError as e:
            e.source = str(it.get("name") or "")  # type: ignore[attr-defined]
            raise
        parsed.append((hostname(text) or str(it.get("name") or "device"), res, str(it.get("name") or "")))
    names = unique_names([p[0] for p in parsed])
    return [
        Device(name, graphmod.build(res.parsed, kb, res.profile, name), source=src)
        for name, (_, res, src) in zip(names, parsed, strict=True)
    ]


def from_db(db_url: str, kb: KnowledgeBase, targets: list[str] | None = None) -> tuple[list[Device], list[str]]:
    """已导入设备的最新配置版本。targets 是设备名或编号；None 表示全部。返回 (设备, 找不到的目标)。"""
    from lmesh.core import graphstore, importer

    devs = importer.list_devices(db_url)
    chosen: list[dict[str, Any]] = []
    missing: list[str] = []
    if targets is None:
        chosen = [d for d in devs if d["latest_version_id"]]
    else:
        for t in targets:
            t = t.strip()
            if not t:
                continue
            hit = next((d for d in devs if d["name"] == t or (t.isdigit() and d["id"] == int(t))), None)
            if hit is None or not hit["latest_version_id"]:
                missing.append(t)
            elif hit not in chosen:
                chosen.append(hit)
    out = []
    for d in chosen:
        g, ver, _ = graphstore.build_for_version(db_url, d["latest_version_id"], kb)
        out.append(Device(d["name"], g, device_id=d["id"], version_id=ver.id, source="device"))
    return out, missing
