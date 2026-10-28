"""配置翻译（M3-3，REQ-012）：一张配置图 → 另一个 Profile（平台族）的配置文本，按有效值翻译并给出告警。

流程：
    1. 换目标：复制源图的语义节点（对象、显式属性、目标 Profile 不隐式创建的派生对象），接口名按映射表改写
       （对象键与接口类型的取值；子接口按父接口映射；没给映射表时同名）。
    2. 默认值差异（目标默认值按目标 Profile 计算，含 when 条件）：
       - 源设备依赖默认值、目标默认值不同     → 显式写出，告警 default_differs；
       - 源设备依赖默认值、目标没有登记默认值 → 不写，提示 default_unknown（请人工确认）；
       - 两边默认值相同                       → 不写；
       - 源设备显式值等于目标默认值           → 省略，在 defaults[] 说明（explicit_equals_default）。
    3. 目标 Profile 标为不支持的节点 → unsupported[]（reason=profile_unsupported，附原文行号），不写；
       写不出命令的节点（目标平台族没有对应的命令卡或映射）→ unsupported[]（reason=no_render）；
       密码类取值（Schema 节点名为 password / secret，或节点标了 secret: true，例如 SNMP 团体字）跨平台族时不写 → unsupported[]（reason=secret），人工重新设置；
       未映射命令（ext）、功能域外原文（raw）、未识别行（unknown）不翻译 → unsupported[]（kind=ext / raw / unknown），人工处理。
    4. 用规范渲染器（canon）生成目标配置。
    5. 校验：译文用目标 Profile 解析建图，与源图按有效值对比（跨厂商 + 接口映射）；
       上面列出的项之外还有差异时，每条差异记为告警 verify_diff（不应出现，出现说明知识库的映射两边不一致）。

所有告警都带文案键（key）与参数（params），界面与 CLI 按语言显示；字段名与取值不随语言变化。
"""

from __future__ import annotations

import ipaddress
import re
from collections import Counter, defaultdict
from typing import Any

import networkx as nx

from lmesh.core import canon
from lmesh.core import compare as cmp
from lmesh.core.graph import DEVICE, Builder, _key_text, _short
from lmesh.core.kb import KnowledgeBase, mapping
from lmesh.core.kb.model import NODE_TYPES, SchemaNode

# 密码类属性（按 Schema 节点名）：跨平台族时不翻译取值；名称看不出来的（团体字、共享密钥）在 Schema 上标 secret: true
_SECRET = re.compile(r"(^|_)(password|secret)$")


def is_secret(sn: SchemaNode) -> bool:
    return sn.secret or bool(_SECRET.search(sn.id.rsplit(".", 1)[-1]))


def _contains_parent(g: nx.MultiDiGraph, nid: str) -> str | None:
    return next((a for a, _, d in g.in_edges(nid, data=True) if d.get("kind") == "contains"), None)


def _move(g: nx.MultiDiGraph, old: str, new: str, new_parent: str, ren: dict[str, str]) -> None:
    """把节点 old 及其子树改挂到 new_parent 下、编号改为 new（依赖边随节点一起改名）。"""
    sub = [n for n in g.nodes if n == old or n.startswith(old + "/")]
    mapping_ = {n: new + n[len(old) :] for n in sub}
    parent = _contains_parent(g, old)
    nx.relabel_nodes(g, mapping_, copy=False)
    if parent is not None:
        for k, d in list(g.get_edge_data(parent, new, default={}).items()):
            if d.get("kind") == "contains":
                g.remove_edge(parent, new, key=k)
    g.add_edge(new_parent, new, kind="contains")
    for a, b in mapping_.items():
        ren[a] = b


def _attr(g: nx.MultiDiGraph, nid: str) -> dict[str, Any] | None:
    d = g.nodes.get(nid)
    return d if d is not None and d.get("kind") == "attr" else None


def _add(g: nx.MultiDiGraph, parent: str, nid: str, kind: str, schema: str, lines: list[int], **attrs: Any) -> None:
    g.add_node(nid, kind=kind, schema=schema, origin="explicit", cards=[], lines=list(lines), **attrs)
    g.add_edge(parent, nid, kind="contains")


def _set_attr(g: nx.MultiDiGraph, owner: str, name: str, schema: str, value: Any, lines: list[int], src: str) -> str:
    """新建属性节点（reshaped_from 记来源节点的原编号）。"""
    nid = f"{owner}/{name}"
    if nid not in g:
        _add(g, owner, nid, "attr", schema, lines, value=value, raw=value, negated=False, reshaped_from=src)
    return nid


def _drop_if_empty(g: nx.MultiDiGraph, nid: str, ren: dict[str, str], to: str) -> None:
    """接入点移走后只剩默认值（或未映射命令、原文）的接口一并去掉：只为承载接入点而存在的子接口 / 父接口。"""
    rest = [c for _, c, d in g.out_edges(nid, data=True) if d.get("kind") == "contains"]
    if all(g.nodes[c].get("origin") == "default" or g.nodes[c].get("kind") in ("ext", "raw", "unknown") for c in rest):
        ren[nid] = to
        g.remove_nodes_from([n for n in list(g.nodes) if n == nid or n.startswith(nid + "/")])


def reshape_access(g: nx.MultiDiGraph, to_form: str) -> dict[str, str]:
    """业务接入点在两种形态间换结构（就地修改图，返回 {旧编号: 新编号}；新建的节点带 reshaped_from = 来源节点的原编号）：

    subinterface（华为）：接入点是子接口 interface[P.N]/access[N]——二层子接口（interface.l2 = true，封装、
                          rewrite、桥域在接入点上），或终结 VLAN 的子接口（vlan-type dot1q V）上的伪线；描述在子接口上；
    instance（Cisco）：   接入点是父接口下的业务实例 interface[P]/access[N]，封装与描述都在接入点上。
    接入点编号两边相同（子接口编号 = 实例编号）；主接口上的接入点（编号 "_"，端口模式）两边一样，不换。
    """
    ren: dict[str, str] = {}
    accesses = [n for n, d in g.nodes(data=True) if d.get("schema") == "interface.access" and d.get("kind") == "object"]
    for acc in accesses:
        key = str(g.nodes[acc].get("key"))
        parent = _contains_parent(g, acc)
        if parent is None or key in ("_", "") or g.nodes[parent].get("schema") != "interface":
            continue
        pkey = str(g.nodes[parent].get("key"))
        base, dot, sub = pkey.rpartition(".")
        lines = list(g.nodes[acc].get("lines") or [])
        if to_form == "instance" and dot and sub == key:
            l2 = _attr(g, f"{parent}/l2")
            is_l2 = bool(l2 and l2.get("value") is True and not l2.get("negated"))
            vlan = _attr(g, f"{parent}/dot1q_termination")
            top = f"interface[{base}]"
            new = f"{top}/access[{key}]"
            if not (is_l2 or vlan) or new in g:
                continue
            if top not in g:
                _add(
                    g, _contains_parent(g, parent) or DEVICE, top, "object", "interface",
                    list(g.nodes[parent].get("lines") or []), key=base, raw=base, reshaped_from=parent,
                )  # fmt: skip
            _move(g, acc, new, top, ren)
            desc = f"{parent}/description"
            if _attr(g, desc) and f"{new}/description" not in g:
                _move(g, desc, f"{new}/description", new, ren)
                g.nodes[f"{new}/description"]["schema"] = "interface.access.description"
            if vlan is not None and f"{new}/encapsulation" not in g:
                # 终结 VLAN 的子接口 → 业务实例匹配这个 VLAN（encapsulation dot1q V）
                vid, vlines = vlan.get("value"), list(vlan.get("lines") or [])
                old = f"{parent}/dot1q_termination"
                ren[old] = _set_attr(g, new, "vlan", "interface.access.vlan", vid, vlines, old)
                _set_attr(g, new, "encapsulation", "interface.access.encapsulation", "dot1q", vlines, old)
                g.remove_node(f"{parent}/dot1q_termination")
            if is_l2:
                ren[f"{parent}/l2"] = new
                g.remove_node(f"{parent}/l2")
            _drop_if_empty(g, parent, ren, new)
        elif to_form == "subinterface" and not dot:
            name = f"{pkey}.{key}"
            subif = f"interface[{name}]"
            new = f"{subif}/access[{key}]"
            if new in g:
                continue
            if subif not in g:  # 排在原来业务实例的位置
                _add(
                    g, _contains_parent(g, parent) or DEVICE, subif, "object", "interface", lines,
                    key=name, raw=name, reshaped_from=acc,
                )  # fmt: skip
            _set_attr(g, subif, "l2", "interface.l2", True, [], acc)
            _move(g, acc, new, subif, ren)
            desc = f"{new}/description"
            if _attr(g, desc) and f"{subif}/description" not in g:
                _move(g, desc, f"{subif}/description", subif, ren)
                g.nodes[f"{subif}/description"]["schema"] = "interface.description"
            _drop_if_empty(g, parent, ren, subif)
    return ren


# ---------------------------------------------------------------- 三层接口形态（M7-3，Nokia）

# 三层属性：Nokia 写在路由器逻辑接口上，华为 / Cisco 写在端口（或子接口）上
L3_ATTRS = (
    "ipv4", "vrf", "ospf", "isis", "mpls", "bfd", "vrrp", "acl_in", "acl_out", "prefix_sid", "dot1q_termination",
    "loopback", "ies",
)  # fmt: skip
NOKIA_PORT = re.compile(r"^(\d+/\d+/|lag-\d+$|esat-|pxc-)")


def _children(g: nx.MultiDiGraph, nid: str) -> list[str]:
    return [c for _, c, d in g.out_edges(nid, data=True) if d.get("kind") == "contains"]


def _rel(g: nx.MultiDiGraph, owner: str, child: str) -> str:
    return child[len(owner) + 1 :]


def _rename_refs(g: nx.MultiDiGraph, kb: KnowledgeBase, old: str, new: str, skip: tuple[str, ...]) -> None:
    """接口改名后，其他节点里按名称引用它的取值一并改（静态路由出接口、源接口…）；skip 中的 Schema 节点不改。"""
    for _n, d in g.nodes(data=True):
        if d.get("kind") != "attr" or d.get("schema") in skip or str(d.get("value")) != old:
            continue
        sn = kb.nodes.get(str(d.get("schema")))
        if sn is not None and (sn.type == "interface" or (sn.type == "ref" and sn.ref == "interface")):
            d["value"] = d["raw"] = new


def reshape_l3(
    g: nx.MultiDiGraph,
    kb: KnowledgeBase,
    to_form: str,
    name_of: Any = None,
    orig_key: Any = None,
) -> dict[str, str]:
    """三层接口在两种形态间换结构（就地修改图，返回 {旧编号: 新编号}；新建节点带 reshaped_from）：

    logical（Nokia）：三层配置在路由器逻辑接口上，port 绑定端口（端口:VLAN 时终结该 VLAN）；
    physical（华为 / Cisco）：三层配置就在端口或子接口上。
    换成 physical：逻辑接口的节点并到它绑定的端口（带 VLAN 时是子接口 <端口>.<VLAN>），端口上已有的同名属性保留端口的；
    换成 logical：端口（或子接口）上的三层属性移到新的逻辑接口 "if-<原接口名>"（子接口的 . 换成 -），port 指向端口；
    环回口不移，补 loopback；目标名是 system 的不动（Nokia 的 system 接口）。
    name_of：对象键 → 目标平台的接口名（判断是不是 Nokia 端口）；orig_key：节点 → 源配置里的接口名（逻辑接口取名用）。
    """
    ren: dict[str, str] = {}
    name_of = name_of or (lambda k: k)
    orig_key = orig_key or (lambda n: str(g.nodes[n].get("key")))
    ifaces = [n for n, d in g.nodes(data=True) if d.get("schema") == "interface" and d.get("kind") == "object"]
    for itf in ifaces:
        if itf not in g:
            continue
        key = str(g.nodes[itf].get("key"))
        kids = _children(g, itf)
        lines = list(g.nodes[itf].get("lines") or [])
        parent = _contains_parent(g, itf) or DEVICE
        if to_form == "physical":
            bp = _attr(g, f"{itf}/bind_port")
            if bp is None:
                continue
            port = str(bp.get("value"))
            vlan = _attr(g, f"{itf}/dot1q_termination")
            tkey = f"{port}.{vlan.get('value')}" if vlan is not None else port
            tgt = f"interface[{tkey}]"
            if tgt == itf:
                continue
            if tgt not in g:
                _add(g, parent, tgt, "object", "interface", lines, key=tkey, raw=tkey, reshaped_from=itf)
            for c in kids:
                if c == f"{itf}/bind_port":
                    ren[c] = tgt
                    g.remove_node(c)
                    continue
                dest = f"{tgt}/{_rel(g, itf, c)}"
                if dest in g:  # 端口上已有（描述、管理状态）：保留端口的
                    ren[c] = dest
                    g.remove_nodes_from([n for n in list(g.nodes) if n == c or n.startswith(c + "/")])
                    continue
                _move(g, c, dest, tgt, ren)
            ren[itf] = tgt
            g.remove_node(itf)
            _rename_refs(g, kb, key, tkey, ("interface.bind_port",))
            continue
        # → logical
        if f"{itf}/bind_port" in g:
            continue
        l3 = [
            c
            for c in kids
            if str(g.nodes[c].get("schema", "")).split(".")[1:2] and _rel(g, itf, c).split("[")[0] in L3_ATTRS
            and g.nodes[c].get("origin") != "default"
        ]  # fmt: skip
        if not l3:
            continue
        tname = str(name_of(key))
        base, dot, sub = tname.partition(".")
        if tname == "system":
            continue
        if not NOKIA_PORT.match(base):
            if re.match(r"(?i)^loop", key) and f"{itf}/loopback" not in g:
                _set_attr(g, itf, "loopback", "interface.loopback", True, [], itf)
            continue
        name = "if-" + str(orig_key(itf)).replace(".", "-")
        new = f"interface[{name}]"
        if new in g:
            continue
        _add(g, parent, new, "object", "interface", lines, key=name, raw=name, reshaped_from=itf)
        _set_attr(g, new, "bind_port", "interface.bind_port", base, [], itf)
        movable = l3 + ([c for c in kids if c not in l3] if dot else [])  # 子接口整个并到逻辑接口
        for c in movable:
            if c == f"{itf}/shutdown" or g.nodes[c].get("origin") == "default":
                continue
            _move(g, c, f"{new}/{_rel(g, itf, c)}", new, ren)
        if dot and f"{new}/dot1q_termination" not in g and sub.isdigit():
            _set_attr(g, new, "dot1q_termination", "interface.dot1q_termination", int(sub), [], itf)
        if dot:
            ren[itf] = new
            g.remove_nodes_from([n for n in list(g.nodes) if n == itf or n.startswith(itf + "/")])
        _rename_refs(g, kb, key, name, ("interface.bind_port",))
    return ren


def reshape_ospf_networks(g: nx.MultiDiGraph) -> dict[str, str]:
    """OSPF 的 network 宣告（华为 / Cisco）换成接口所属区域（Nokia 只在区域下列接口，M7-3）：
    接口地址落在某个 network 里时，接口上的 OSPF 参数记进程与区域（已有的不改），network 对象去掉。就地修改，返回 {旧编号: 新编号}。"""
    ren: dict[str, str] = {}
    addrs: list[tuple[str, ipaddress.IPv4Address]] = []
    for n, d in g.nodes(data=True):
        if d.get("schema") == "interface.ipv4.address" and d.get("kind") == "attr":
            itf = n.split("/ipv4[")[0]
            try:
                addrs.append((itf, ipaddress.IPv4Address(str(d.get("value")))))
            except ValueError:
                continue
    nets = [
        n for n, d in g.nodes(data=True) if d.get("schema") == "ospf.process.area.network" and d.get("kind") == "object"
    ]
    for net in nets:
        area = _contains_parent(g, net)
        proc = _contains_parent(g, area) if area else None
        if not area or not proc:
            continue
        key = str(g.nodes[net].get("key"))
        addr, _, wild = key.replace("/", " ").partition(" ")
        length = mapping.wildcard_len(wild) if "." in wild else (wild or "32")
        try:
            network = ipaddress.IPv4Network(f"{addr}/{length}", strict=False)
        except ValueError:
            continue
        hits = [itf for itf, a in addrs if a in network]
        for itf in hits:
            o = f"{itf}/ospf[_]"
            if o not in g:
                _add(g, itf, o, "object", "interface.ospf", list(g.nodes[net].get("lines") or []), key="_", raw="_",
                     reshaped_from=net)  # fmt: skip
            if f"{o}/process" not in g:
                _set_attr(g, o, "process", "interface.ospf.process", g.nodes[proc].get("key"), [], net)
            if f"{o}/area" not in g:
                _set_attr(g, o, "area", "interface.ospf.area", g.nodes[area].get("key"), [], net)
        if hits:
            ren[net] = f"{hits[0]}/ospf[_]"
            g.remove_nodes_from([x for x in list(g.nodes) if x == net or x.startswith(net + "/")])
    return ren


def _sysid_from_ip(ip: str) -> str | None:
    """Router ID 推出 IS-IS 系统 ID（10.255.0.2 → 0102.5500.0002，各段补到三位后每四位一组）。"""
    parts = str(ip).split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return None
    digits = "".join(f"{int(p):03d}" for p in parts)
    return ".".join(digits[i : i + 4] for i in range(0, 12, 4))


def reshape_isis_net(g: nx.MultiDiGraph, to_net: bool) -> dict[str, str]:
    """IS-IS 的区域与系统 ID：华为 / Cisco 写成 NET（isis.process.net），Nokia 分成 area-id 与 system-id。
    to_net：area_id（+ system_id，不写时按 Router ID 推出）拼成 NET；否则把 NET 拆开。就地修改，返回 {旧编号: 新编号}。"""
    ren: dict[str, str] = {}
    procs = [n for n, d in g.nodes(data=True) if d.get("schema") == "isis.process" and d.get("kind") == "object"]
    for p in procs:
        if to_net:
            area = _attr(g, f"{p}/area_id")
            if area is None or any(str(c).startswith(f"{p}/net[") for c in _children(g, p)):
                continue
            sysid = _attr(g, f"{p}/system_id")
            sid = str(sysid.get("value")) if sysid else None
            if sid is None:
                rid = next(
                    (
                        d.get("value")
                        for n, d in g.nodes(data=True)
                        if d.get("schema") in ("mgmt.system.router_id", "isis.process.router_id")
                        and d.get("kind") == "attr"
                    ),
                    None,
                )
                sid = _sysid_from_ip(str(rid)) if rid else None
            if sid is None:
                continue
            net = f"{area.get('value')}.{sid}.00"
            nid = f"{p}/net[{net}]"
            _add(g, p, nid, "object", "isis.process.net", list(area.get("lines") or []), key=net, raw=net,
                 reshaped_from=f"{p}/area_id")  # fmt: skip
            ren[f"{p}/area_id"] = nid
            g.remove_node(f"{p}/area_id")
            if sysid is not None:
                ren[f"{p}/system_id"] = nid
                g.remove_node(f"{p}/system_id")
        else:
            nets = [c for c in _children(g, p) if g.nodes[c].get("schema") == "isis.process.net"]
            if not nets or _attr(g, f"{p}/area_id") is not None:
                continue
            net = str(g.nodes[nets[0]].get("key"))
            parts = net.split(".")
            if len(parts) < 5:
                continue
            area_s, sid = ".".join(parts[:-4]), ".".join(parts[-4:-1])
            lines = list(g.nodes[nets[0]].get("lines") or [])
            ren[nets[0]] = _set_attr(g, p, "area_id", "isis.process.area_id", area_s, lines, nets[0])
            _set_attr(g, p, "system_id", "isis.process.system_id", sid, lines, nets[0])
            for n in nets:
                g.remove_nodes_from([x for x in list(g.nodes) if x == n or x.startswith(n + "/")])
    return ren


# BGP 地址族：统一 Schema 的 afi（华为 / Cisco 地址族视图）↔ Nokia bgp / group 下的 family 取值（M7-5）
_FAMILY = {"ipv4": "ipv4", "ipv6": "ipv6", "vpnv4": "vpn-ipv4", "vpnv6": "vpn-ipv6", "evpn": "evpn", "l2vpn": "l2-vpn"}
_AFI = {v: k for k, v in _FAMILY.items()}


def _af_id(inst: str, afi: str) -> str:
    return f"{inst}/bgp.af[afi={afi},vrf=]"


def reshape_bgp_family(g: nx.MultiDiGraph, to_family: bool) -> dict[str, str]:
    """BGP 地址族的两种写法（M7-5）：华为 / Cisco 在地址族视图里逐个对等体（组）启用（bgp.af / bgp.af.peer.enabled），
    Nokia 在 bgp 与 group 下写 family（bgp.instance.family、bgp.peer_group.family）。只换公网地址族（VRF 内的不动）。
    to_family：地址族视图 → family；否则 family → 地址族视图。就地修改，返回 {旧编号: 新编号}。"""
    ren: dict[str, str] = {}
    insts = [n for n, d in g.nodes(data=True) if d.get("schema") == "bgp.instance" and d.get("kind") == "object"]
    for inst in insts:
        kids = _children(g, inst)
        groups = [c for c in kids if g.nodes[c].get("schema") == "bgp.peer_group"]
        peers = [c for c in kids if g.nodes[c].get("schema") == "bgp.peer"]
        if to_family:
            if _attr(g, f"{inst}/family") is not None:
                continue
            afs = [
                c
                for c in kids
                if g.nodes[c].get("schema") == "bgp.af"
                and isinstance(g.nodes[c].get("key"), dict)
                and not g.nodes[c]["key"].get("vrf")
                and str(g.nodes[c]["key"].get("afi")) in _FAMILY
            ]
            if not afs:
                continue
            fams = [_FAMILY[str(g.nodes[a]["key"]["afi"])] for a in afs]
            lines = sorted({x for a in afs for x in g.nodes[a].get("lines") or []})
            fam_node = _set_attr(g, inst, "family", "bgp.instance.family", " ".join(fams), lines, afs[0])
            member = {
                str(g.nodes[p].get("key")): str(_attr(g, f"{p}/group").get("value"))  # type: ignore[union-attr]
                for p in peers
                if _attr(g, f"{p}/group") is not None
            }
            by_group: dict[str, list[str]] = {str(g.nodes[gr].get("key")): [] for gr in groups}
            for a, fam in zip(afs, fams, strict=True):
                for ap in [c for c in _children(g, a) if g.nodes[c].get("schema") == "bgp.af.peer"]:
                    en = _attr(g, f"{ap}/enabled")
                    if en is None or en.get("value") is not True:
                        continue
                    k = str(g.nodes[ap].get("key"))
                    grp = k if k in by_group else member.get(k)
                    if grp in by_group and fam not in by_group[grp]:
                        by_group[grp].append(fam)
                    ren[f"{ap}/enabled"] = fam_node
                    g.remove_node(f"{ap}/enabled")
                    if not _children(g, ap):
                        ren[ap] = fam_node
                        g.remove_node(ap)
                if not _children(g, a):
                    ren[a] = fam_node
                    g.remove_node(a)
            for gr in groups:
                got = by_group[str(g.nodes[gr].get("key"))]
                if got and sorted(got) != sorted(fams) and _attr(g, f"{gr}/family") is None:
                    _set_attr(
                        g, gr, "family", "bgp.peer_group.family", " ".join(f for f in fams if f in got), lines, afs[0]
                    )
        else:
            fam_attr = _attr(g, f"{inst}/family")
            if fam_attr is None or fam_attr.get("origin") == "default":
                continue
            fams = [f for f in str(fam_attr.get("value") or "").split() if f in _AFI]
            if not fams:
                continue
            lines = list(fam_attr.get("lines") or [])
            for f in fams:
                af = _af_id(inst, _AFI[f])
                if af not in g:
                    key = {"afi": _AFI[f], "vrf": ""}
                    _add(g, inst, af, "object", "bgp.af", lines, key=key, raw=key, reshaped_from=f"{inst}/family")
            for gr in groups:
                gf = _attr(g, f"{gr}/family")
                gfams = [f for f in str(gf.get("value") or "").split() if f in _AFI] if gf else fams
                for f in gfams:
                    af = _af_id(inst, _AFI[f])
                    if af not in g:
                        continue
                    name = str(g.nodes[gr].get("key"))
                    ap = f"{af}/peer[{name}]"
                    if ap not in g:
                        _add(
                            g,
                            af,
                            ap,
                            "object",
                            "bgp.af.peer",
                            lines,
                            key=name,
                            raw=name,
                            reshaped_from=f"{inst}/family",
                        )
                    _set_attr(g, ap, "enabled", "bgp.af.peer.enabled", True, lines, f"{inst}/family")
                if gf is not None:
                    ren[f"{gr}/family"] = _af_id(inst, _AFI[gfams[0]]) if gfams else inst
                    g.remove_node(f"{gr}/family")
            ren[f"{inst}/family"] = _af_id(inst, _AFI[fams[0]])
            g.remove_node(f"{inst}/family")
    return ren


class TranslateError(ValueError):
    """翻译参数错误（文案键 + 参数）。"""

    def __init__(self, key: str, kind: str = "param", **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.fmt = key, kind, fmt


def _item(kind: str, key: str, node: str | None = None, **params: Any) -> dict[str, Any]:
    """告警 / 不支持 / 省略项：kind 与文案键 key 固定，params 是文案参数（含 node、schema，取值不随语言变化）。"""
    lines = params.pop("lines", [])
    params = {"node": node, **params}
    return {"kind": kind, "key": key, "node": node, "schema": params.get("schema"), "lines": lines, "params": params}


class _Translator:
    def __init__(
        self,
        g_src: nx.MultiDiGraph,
        kb: KnowledgeBase,
        src_profile: str,
        dst_profile: str,
        interface_map: dict[str, str] | None,
    ):
        for pid in (src_profile, dst_profile):
            if pid not in kb.profiles:
                raise TranslateError("parse.profile_unknown", profile=pid)
        self.g, self.kb = g_src, kb
        self.src, self.dst = src_profile, dst_profile
        self.sch = cmp._Schema(kb)
        self.raw_map = dict(interface_map or {})
        # 键按统一写法（GE0/2/1 与 GigabitEthernet0/2/1 是同一个口），值保留映射表里的写法
        self.ifmap = {cmp.interface_name(k).lower(): str(v).strip() for k, v in self.raw_map.items()}
        self.dst_res = kb.resolve_profile(dst_profile)
        self.src_res = kb.resolve_profile(src_profile)
        self.cross_family = kb.profiles[src_profile].family != kb.profiles[dst_profile].family
        self.children: dict[str, list[str]] = defaultdict(list)
        for a, b, d in g_src.edges(data=True):
            if d.get("kind") == "contains":
                self.children[a].append(b)
        self.warnings: list[dict[str, Any]] = []
        self.unsupported: list[dict[str, Any]] = []
        self.defaults: list[dict[str, Any]] = []
        self.unmapped: set[str] = set()  # 映射表中没有的接口（保持原名）
        self.secret_shells: set[str] = set()  # 只装着敏感对象的占位对象（源图编号）：不写，校验时视为已说明
        self.omitted: set[str] = set()  # 目标平台族没有、源设备是“启用”的管理状态（源图编号）：省略，校验时视为已说明

    # ----- 接口名 -----

    def rename(self, name: Any) -> Any:
        if isinstance(name, list):
            return [self.rename(x) for x in name]
        if not isinstance(name, str) or not name or not self.ifmap:
            return name
        canon_name = cmp.interface_name(name)
        if canon_name.lower() in self.ifmap:
            return self.ifmap[canon_name.lower()]
        base, dot, sub = canon_name.partition(".")
        if dot and base.lower() in self.ifmap:
            return f"{self.ifmap[base.lower()]}.{sub}"  # 子接口按父接口映射
        self.unmapped.add(base)
        return name

    def is_if_field(self, sn: SchemaNode, f: str) -> bool:
        t, ref = self.sch.field_type(sn, f)
        return t == "interface" or ref == "interface" or f == "interface"

    def new_key(self, sn: SchemaNode, key: Any) -> Any:
        if isinstance(key, dict):
            return {f: (self.rename(v) if self.is_if_field(sn, f) else v) for f, v in key.items()}
        f = sn.key[0] if sn.key else "name"
        if (len(sn.key) <= 1 and sn.id in NODE_TYPES and sn.id == "interface") or self.is_if_field(sn, f):
            return self.rename(key)
        # 取值可能是接口名、也可能是别的的键（例如时钟源 ptp / bits0 / 接口名）：正好是映射表里的接口时才换
        if isinstance(key, str) and self.ifmap and cmp.interface_name(key).lower() in self.ifmap:
            return self.ifmap[cmp.interface_name(key).lower()]
        return key

    # ----- 1. 换目标 -----

    def retarget(self) -> nx.MultiDiGraph:
        prof = self.kb.profiles[self.dst]
        gt = nx.MultiDiGraph(
            device=self.g.graph.get("device"), profile=self.dst, family=prof.family, kb_version=self.kb.version
        )
        gt.add_node(
            DEVICE, kind="device", schema=None, value=self.g.graph.get("device"), origin="explicit", lines=[], cards=[]
        )
        self.to_new: dict[str, str] = {DEVICE: DEVICE}
        self.to_src: dict[str, str] = {DEVICE: DEVICE}
        self.src_defaults: list[tuple[str, str, Any]] = []  # (目标图中的属主, 源默认节点, 值)
        implicit = set(self.dst_res.implicit)
        stack = [DEVICE]
        while stack:
            pid = stack.pop()
            new_parent = self.to_new[pid]
            parent_schema = gt.nodes[new_parent].get("schema")
            for c in self.children.get(pid, []):
                d = self.g.nodes[c]
                kind = d.get("kind")
                sn = self.kb.nodes.get(str(d.get("schema")))
                if kind not in ("object", "attr") or sn is None:
                    continue
                if kind == "attr" and d.get("origin") == "default":
                    self.src_defaults.append((new_parent, c, d.get("value")))
                    continue
                if kind == "object":
                    if d.get("origin") == "derived" and sn.id in implicit:
                        continue
                    key = self.new_key(sn, d.get("key"))
                    seg = f"{_short(sn.id, parent_schema)}[{_key_text(key)}]"
                    attrs = {"key": key, "raw": key}
                else:
                    seg = c[len(pid) + 1 :] if pid != DEVICE else c
                    value = d.get("value")
                    if sn.type == "interface" or (sn.type == "ref" and sn.ref == "interface"):
                        value = self.rename(value)
                    attrs = {"value": value, "raw": value, "negated": d.get("negated", False)}
                nid = seg if new_parent == DEVICE else f"{new_parent}/{seg}"
                gt.add_node(
                    nid,
                    kind=kind,
                    schema=sn.id,
                    origin=d.get("origin", "explicit"),
                    lines=list(d.get("lines") or []),
                    cards=[],
                    **attrs,
                )
                gt.add_edge(new_parent, nid, kind="contains")
                self.to_new[c] = nid
                self.to_src[nid] = c
                if kind == "object":
                    stack.append(c)
        for a, b, d in self.g.edges(data=True):
            if d.get("kind") in ("reference", "prerequisite") and a in self.to_new and b in self.to_new:
                gt.add_edge(self.to_new[a], self.to_new[b], kind=d.get("kind"), note=d.get("note", ""))
        self.builder = Builder(self.kb, prof, str(self.g.graph.get("device") or "device"))
        self.builder.g = gt
        return gt

    def secret_item(self, src: str, sn: SchemaNode, d: dict[str, Any]) -> dict[str, Any]:
        """敏感取值不写（参数里不带取值本身）。"""
        return _item(
            "node",
            "translate.unsupported.secret",
            src,
            reason="secret",
            schema=sn.id,
            profile=self.dst,
            lines=list(d.get("lines") or []),
        )

    def dst_default(self, gt: nx.MultiDiGraph, sn: SchemaNode, owner: str) -> Any:
        e = self.dst_res.entries.get(sn.id)
        if e is None or not e.supported or e.default is None:
            return None
        v = self.builder.default_for(owner, gt.nodes[owner], e.default, e.when)
        return None if v is None else mapping.normalize(sn.type, sn.id, v)

    # ----- 2、3. 默认值与支持情况 -----

    def classify(self, gt: nx.MultiDiGraph) -> set[str]:
        facts: set[str] = set()
        dead: set[str] = set()  # 目标不支持的对象（子树都不写）
        implicit = set(self.dst_res.implicit)
        kids: dict[str, list[str]] = defaultdict(list)
        parent: dict[str, str] = {}
        for a, b, ed in gt.edges(data=True):
            if ed.get("kind") == "contains":
                kids[a].append(b)
                parent[b] = a
        order: list[str] = []
        stack = [DEVICE]
        while stack:
            x = stack.pop()
            order.append(x)
            stack.extend(reversed(kids.get(x, [])))
        for nid in order:
            if nid == DEVICE:
                continue
            if parent.get(nid) in dead:
                dead.add(nid)
                continue
            d = gt.nodes[nid]
            sn = self.kb.nodes[str(d["schema"])]
            src = self.to_src.get(nid, nid)
            e = self.dst_res.entries.get(sn.id)
            if e is not None and not e.supported:
                self.unsupported.append(
                    _item(
                        "node",
                        "translate.unsupported.profile",
                        src,
                        reason="profile_unsupported",
                        schema=sn.id,
                        value=d.get("key") if d.get("kind") == "object" else d.get("value"),
                        profile=self.dst,
                        lines=list(d.get("lines") or []),
                    )
                )
                if d.get("kind") == "object":
                    dead.add(nid)
                continue
            if d.get("kind") == "object":
                if sn.id in implicit and not any(True for _ in kids.get(nid, [])):
                    # 目标平台被引用即隐式存在的对象（ASR 920 的桥域）：不单独写；没有被引用时提示
                    if not any(ed.get("kind") == "reference" for _, _, ed in gt.in_edges(nid, data=True)):
                        self.warnings.append(
                            _item(
                                "implicit_object",
                                "translate.warn.implicit_object",
                                src,
                                level="info",
                                schema=sn.id,
                                value=d.get("key"),
                                profile=self.dst,
                                lines=list(d.get("lines") or []),
                            )
                        )
                    continue
                if canon.negated_object(self.g, src):
                    continue  # 只由取消形式产生的对象：作为原文列出，不翻译
                if self.cross_family and sn.secret:
                    # 键本身是敏感内容（SNMP 团体字）：对象整棵子树都不写，人工重新设置
                    self.unsupported.append(self.secret_item(src, sn, d))
                    dead.add(nid)
                    continue
                facts.add(nid)
                continue
            if not canon.valued(d) or d.get("value") is None:
                continue
            if self.cross_family and is_secret(sn):
                # 密码类取值是源平台的密文（或脱敏后的占位），换平台后不能直接用：不写，人工重新设置
                self.unsupported.append(self.secret_item(src, sn, d))
                continue
            src_e = self.src_res.entries.get(sn.id)
            if (
                self.cross_family
                and e is None
                and src_e is not None
                and src_e.assume is not None
                and canon._same(d.get("value"), src_e.assume, sn.type)
            ):
                # 源平台族显式写了“启用”（Nokia 的 no shutdown），目标平台族没有这个开关、本来就是这个状态：省略并说明
                self.omitted.add(src)
                self.defaults.append(
                    _item(
                        "explicit_equals_default",
                        "translate.default.omitted",
                        src,
                        schema=sn.id,
                        value=d.get("value"),
                        profile=self.dst,
                        lines=list(d.get("lines") or []),
                    )
                )
                continue
            dd = self.dst_default(gt, sn, parent[nid])
            if dd is not None and canon._same(d.get("value"), dd, sn.type):
                self.defaults.append(
                    _item(
                        "explicit_equals_default",
                        "translate.default.omitted",
                        src,
                        schema=sn.id,
                        value=d.get("value"),
                        profile=self.dst,
                        lines=list(d.get("lines") or []),
                    )
                )
                continue
            facts.add(nid)
        # 敏感对象（团体字）不写之后，只剩空壳的占位父对象（mgmt.snmp[_]）也不写，免得为了写出它编造别的命令
        for nid in [
            n for n in dead if gt.nodes[n].get("kind") == "object" and self.kb.nodes[str(gt.nodes[n]["schema"])].secret
        ]:
            p = parent.get(nid)
            if p in facts and gt.nodes[p].get("key") in ("_", "") and not any(c in facts for c in kids.get(p, [])):
                facts.discard(p)
                self.secret_shells.add(self.to_src.get(p, p))
        self.dead = dead
        # 源设备依赖默认值的节点
        self.default_counts: Counter[str] = Counter()
        for owner, src_nid, value in self.src_defaults:
            if owner not in gt or owner in dead:
                continue
            sd = self.g.nodes[src_nid]
            sn = self.kb.nodes[str(sd["schema"])]
            e = self.dst_res.entries.get(sn.id)
            if e is not None and not e.supported:
                continue
            dd = self.dst_default(gt, sn, owner)
            if dd is not None and canon._same(value, dd, sn.type):
                self.default_counts["same"] += 1
                continue
            if dd is None:
                self.default_counts["unknown"] += 1
                self.warnings.append(
                    _item(
                        "default_unknown",
                        "translate.warn.default_unknown",
                        src_nid,
                        level="info",
                        schema=sn.id,
                        src_default=value,
                        profile=self.dst,
                    )
                )
                continue
            nid = f"{owner}/{_short(sn.id, gt.nodes[owner].get('schema'))}"
            gt.add_node(
                nid,
                kind="attr",
                schema=sn.id,
                value=value,
                raw=value,
                origin="explicit",
                lines=[],
                cards=[],
                negated=False,
            )
            gt.add_edge(owner, nid, kind="contains")
            self.to_src[nid] = src_nid
            facts.add(nid)
            self.omitted.add(nid)  # 显式写出的默认值差异（已告警）：译文里按目标编号出现，校验时视为已说明
            self.default_counts["differs"] += 1
            self.warnings.append(
                _item(
                    "default_differs",
                    "translate.warn.default_differs",
                    src_nid,
                    level="warning",
                    schema=sn.id,
                    src_default=value,
                    dst_default=dd,
                    profile=self.dst,
                )
            )
        self.assumed(gt, facts, parent, dead)
        # 目标 Profile 的默认节点（渲染时判断顺带写出的取值是否等于默认值）
        self.builder._defaults()
        return facts

    def assumed(self, gt: nx.MultiDiGraph, facts: set[str], parent: dict[str, str], dead: set[str]) -> None:
        """目标 Profile 标了 assume 的节点（M7-3：Nokia 的协议实例、NTP、静态路由缺省关闭）：源平台族没有这个节点时
        按 assume 理解源设备的状态，目标缺省值与它不同（或没有登记）就显式写出并告警 default_differs。"""
        for node_id, e in self.dst_res.entries.items():
            if e.assume is None or not e.supported:
                continue
            src_e = self.src_res.entries.get(node_id)
            if src_e is not None and src_e.supported:
                continue
            sn = self.kb.nodes.get(node_id)
            if sn is None or sn.parent is None:
                continue
            owner_schema = sn.parent
            while owner_schema and self.kb.nodes[owner_schema].type != "object":
                owner_schema = str(self.kb.nodes[owner_schema].parent)
            for owner, d in list(gt.nodes(data=True)):
                if d.get("schema") != owner_schema or d.get("kind") != "object" or owner in dead or owner not in facts:
                    continue
                nid = f"{owner}/{_short(sn.id, owner_schema)}"
                if nid in gt:
                    continue
                dd = self.dst_default(gt, sn, owner)
                value = mapping.normalize(sn.type, sn.id, e.assume)
                if dd is not None and canon._same(dd, value, sn.type):
                    continue
                gt.add_node(nid, kind="attr", schema=sn.id, value=value, raw=value, origin="explicit", lines=[],
                            cards=[], negated=False)  # fmt: skip
                gt.add_edge(owner, nid, kind="contains")
                parent[nid] = owner
                facts.add(nid)
                self.warnings.append(
                    _item(
                        "default_differs",
                        "translate.warn.default_differs",
                        nid,
                        level="warning",
                        schema=sn.id,
                        src_default=value,
                        dst_default=dd,
                        profile=self.dst,
                    )
                )

    def extras(self) -> None:
        """源图中不翻译的行：未映射命令、功能域外原文、未识别行（原文块只列块的第一行，附整块的行号）。"""
        stmts = {st.line.no: st for st in self.g.graph.get("statements", [])}
        for nid, d in self.g.nodes(data=True):
            kind = d.get("kind")
            if kind == "object" and canon.negated_object(self.g, nid):
                kind = "negated"
            elif kind not in ("ext", "raw", "unknown"):
                continue
            parent = next((a for a, _, ed in self.g.in_edges(nid, data=True) if ed.get("kind") == "contains"), DEVICE)
            if kind in ("raw", "unknown") and self.g.nodes[parent].get("kind") in ("raw", "unknown"):
                continue
            lines = sorted(d.get("lines") or [])
            block = list(lines)
            stack = list(self.children.get(nid, []))
            while stack:
                x = stack.pop()
                if self.g.nodes[x].get("kind") in ("raw", "unknown"):
                    block += self.g.nodes[x].get("lines") or []
                    stack.extend(self.children.get(x, []))
            st = stmts.get(lines[0]) if lines else None
            text = st.line.text if st else str(d.get("text") or "").strip()
            if kind == "raw" and text in ("#", "!"):
                continue
            self.unsupported.append(
                _item(
                    kind,
                    f"translate.unsupported.{kind}",
                    nid,
                    reason="not_translated",
                    text=text,
                    line=lines[0] if lines else None,
                    owner=parent if parent != DEVICE else None,
                    lines=sorted(set(block)),
                )
            )

    # ----- 5. 校验 -----

    def verify(self, text: str, explained: set[str]) -> dict[str, Any]:
        a = cmp.Side(self.g, "source")
        try:
            b = cmp.side_from_text(text, self.kb, self.dst, "translated")
        except cmp.CompareError as e:  # 译文解析失败（不应出现）
            self.warnings.append(
                _item("verify_failed", "translate.warn.verify_failed", None, level="error", error=e.key)
            )
            return {"checked": False, "equal": False, "diffs": 0, "unexplained": 0}
        back: dict[str, str] = {}  # 换结构后的编号 → 源图中的编号
        src_form, dst_form = self.forms()
        s3, d3 = self.l3_forms()
        if (src_form and dst_form and src_form != dst_form) or s3 != d3:
            # 源图按目标平台族的形态换结构后再对比（单向换，不要求两种形态互逆）
            ga = self.g.copy()
            ren = self.reshape_shapes(ga, True)
            if src_form and dst_form and src_form != dst_form:
                ren.update(reshape_access(ga, dst_form))
            back = {new: old for old, new in ren.items() if new in ga}
            back.update({n: d["reshaped_from"] for n, d in ga.nodes(data=True) if d.get("reshaped_from")})
            a = cmp.Side(ga, "source")
        r = cmp.compare(a, b, self.kb, interface_map=self.raw_map or None)

        def covered(node: str | None) -> bool:
            if not node:
                return False
            node = back.get(node, node)
            return any(node == x or node.startswith(x + "/") for x in explained)

        unexplained = 0
        for d in r["diffs"]:
            node_a = (d.get("a") or {}).get("node")
            node_b = (d.get("b") or {}).get("node")
            if covered(node_a) or (node_a is None and covered(node_b)):
                continue
            src_entry = self.kb.resolve_profile(self.src).entries.get(str(d.get("schema") or ""))
            if d["kind"] == "added" and src_entry is not None and not src_entry.supported:
                # 源平台没有这个开关（Profile 标了 supported: false，例如 Cisco 没有 SSH 服务开关），目标取缺省值是预期结果
                continue
            if (
                d["kind"] == "removed"
                and str(d.get("schema") or "") in self.dst_res.implicit
                and node_a
                and self.g.nodes.get(back.get(node_a, node_a), {}).get("origin") == "derived"
            ):
                continue  # 源图里被引用而隐式存在的对象（桥域）：目标平台同样隐式，引用它的节点已列为不支持
            dst_entry = self.dst_res.entries.get(str(d.get("schema") or ""))
            if d["kind"] == "added" and src_entry is None and dst_entry is not None and dst_entry.assume is not None:
                continue  # 按 assume 显式写出的管理状态（已告警 default_differs）
            unexplained += 1
            self.warnings.append(
                _item(
                    "verify_diff",
                    "translate.warn.verify_diff",
                    node_a or (d.get("b") or {}).get("node"),
                    level="warning",
                    schema=d.get("schema"),
                    diff=d["kind"],
                    cid=d["node"],
                    src_value=(d.get("a") or {}).get("value"),
                    dst_value=(d.get("b") or {}).get("value"),
                    lines=(d.get("a") or {}).get("lines") or [],
                )
            )
        for u in r["unknown"]["b"]:
            unexplained += 1
            self.warnings.append(
                _item(
                    "verify_unknown",
                    "translate.warn.verify_unknown",
                    None,
                    level="warning",
                    line=u["line"],
                    text=u["text"],
                )
            )
        return {"checked": True, "equal": r["equal"], "diffs": r["summary"]["total"], "unexplained": unexplained}

    def interface_types(self, gt: nx.MultiDiGraph) -> None:
        """接口名的类型不属于目标平台族（knowledge/render 的 interface_types）、又没有映射时告警。"""
        _, style = canon._index(self.kb, self.kb.profiles[self.dst].family)
        types = {t.lower() for t in style["interface_types"]}
        if not types:
            return
        seen: set[str] = set()
        for nid, d in gt.nodes(data=True):
            if d.get("kind") != "object" or d.get("schema") != "interface":
                continue
            name = str(d.get("key") or "")
            m = re.match(r"^(\d+GE|[A-Za-z][A-Za-z\-]*)", name)
            kind = m.group(1) if m else name
            if kind.lower() in types or kind.lower() in seen:
                continue
            seen.add(kind.lower())
            self.warnings.append(
                _item(
                    "interface_type",
                    "translate.warn.interface_type",
                    self.to_src.get(nid, nid),
                    level="warning",
                    name=name,
                    type=kind,
                    family=self.kb.profiles[self.dst].family,
                    lines=list(d.get("lines") or []),
                )
            )

    # ----- 主流程 -----

    def forms(self) -> tuple[str, str]:
        """源、目标平台族的接入点形态（knowledge/render 的 access_form）。"""
        fam = self.kb.profiles
        src = canon._index(self.kb, fam[self.src].family)[1]["access_form"]
        dst = canon._index(self.kb, fam[self.dst].family)[1]["access_form"]
        return src, dst

    def l3_forms(self) -> tuple[str, str]:
        """源、目标平台族的三层接口形态（knowledge/render 的 l3_form；没写为 physical）。"""
        fam = self.kb.profiles
        src = canon._index(self.kb, fam[self.src].family)[1]["l3_form"] or "physical"
        dst = canon._index(self.kb, fam[self.dst].family)[1]["l3_form"] or "physical"
        return src, dst

    def reshape_shapes(self, g: nx.MultiDiGraph, src_names: bool) -> dict[str, str]:
        """接入点之外的形态差异（M7-3，Nokia）：三层接口（逻辑接口 ↔ 端口 / 子接口）、IS-IS 的 NET（area-id + system-id）。
        src_names：g 是源图的副本（校验用），接口名按映射表换成目标写法后再判断是不是 Nokia 端口。"""
        ren: dict[str, str] = {}

        def step(r: dict[str, str]) -> None:
            ren.update(r)
            if not src_names:
                self._apply_ren(g, r)  # 译文图：每一步之后更新到源图的对应，下一步按新编号找

        step(self.rekey_instances(g))
        s3, d3 = self.l3_forms()
        if s3 != d3 and d3 == "logical":
            step(reshape_ospf_networks(g))
        if s3 != d3:
            if src_names:
                step(reshape_l3(g, self.kb, d3, lambda k: self.rename_quiet(k)))
            else:
                orig = {n: str(self.g.nodes[self.to_src[n]].get("key")) for n in g if self.to_src.get(n) in self.g}
                step(reshape_l3(g, self.kb, d3, None, lambda n: orig.get(n, str(g.nodes[n].get("key")))))
            step(reshape_isis_net(g, d3 == "physical"))
            step(reshape_bgp_family(g, d3 == "logical"))
        return ren

    def rekey_instances(self, g: nx.MultiDiGraph) -> dict[str, str]:
        """协议实例编号的对应（knowledge/render 的 instance_keys，M7-3）：Nokia 的基本实例 0（ospf 0、isis 0）对应
        华为 / Cisco 缺省的进程 1；换平台族时改对象编号，并改按编号引用它的属性（接口上的 interface.ospf.process）。"""
        fam = self.kb.profiles
        src = canon._index(self.kb, fam[self.src].family)[1]["instance_keys"]
        dst = canon._index(self.kb, fam[self.dst].family)[1]["instance_keys"]
        table: dict[str, dict[str, str]] = {}
        for schema, m in src.items():
            table[schema] = {str(k): str(v) for k, v in m.items()}
        for schema, m in dst.items():
            table.setdefault(schema, {}).update({str(v): str(k) for k, v in m.items()})
        for schema in [x for x in table if src.get(x) and src.get(x) == dst.get(x)]:
            del table[schema]  # 两边编号习惯相同（同一设备的两种配置格式：Nokia Classic ↔ MD-CLI，M7-4）：不改编号
        ren: dict[str, str] = {}
        if not table or not self.cross_family:
            return ren
        for schema, m in table.items():
            sn = self.kb.nodes.get(schema)
            for n, d in list(g.nodes(data=True)):
                if d.get("schema") != schema or d.get("kind") != "object" or str(d.get("key")) not in m:
                    continue
                old_key = str(d.get("key"))
                new_key = m[old_key]
                parent = _contains_parent(g, n) or DEVICE
                new = n[: n.rindex("[") + 1] + new_key + "]"
                if new in g:
                    continue
                _move(g, n, new, parent, ren)
                g.nodes[new]["key"] = g.nodes[new]["raw"] = new_key
                for _x, a in g.nodes(data=True):  # 按编号引用这个实例的属性（Schema 里 ref / 名为 process 的属性）
                    asn = self.kb.nodes.get(str(a.get("schema")))
                    if (
                        a.get("kind") == "attr"
                        and asn is not None
                        and str(a.get("value")) == old_key
                        and (
                            (asn.type == "ref" and asn.ref == schema)
                            or (sn and asn.id.endswith(".process"))
                            and asn.id.split(".")[1] == schema.split(".")[0]
                        )
                    ):
                        a["value"] = a["raw"] = new_key
        return ren

    def rename_quiet(self, name: Any) -> Any:
        unmapped = set(self.unmapped)
        out = self.rename(name)
        self.unmapped = unmapped
        return out

    def reshape(self, gt: nx.MultiDiGraph) -> None:
        """源、目标平台族的接入点形态不同时换结构（华为二层子接口 ↔ Cisco 业务实例）；三层接口与 IS-IS NET 的形态
        不同时也换（Nokia，M7-3）。"""
        self.reshape_shapes(gt, False)
        src_form, dst_form = self.forms()
        if not (src_form and dst_form and src_form != dst_form):
            return
        self._apply_ren(gt, reshape_access(gt, dst_form))

    def _apply_ren(self, gt: nx.MultiDiGraph, ren: dict[str, str]) -> None:
        if not ren:
            return
        old_src = dict(self.to_src)
        for old, new in ren.items():
            self.to_src.pop(old, None)
            if old in old_src and new not in self.to_src:
                self.to_src[new] = old_src[old]
        for n, d in gt.nodes(data=True):
            if d.get("reshaped_from") in old_src:
                self.to_src[n] = old_src[d["reshaped_from"]]
        self.src_defaults = [(ren.get(o, o), s, v) for o, s, v in self.src_defaults]

    def run(self, verify: bool = True) -> dict[str, Any]:
        gt = self.retarget()
        self.reshape(gt)
        facts = self.classify(gt)
        rendered = canon.render_full(gt, self.kb, self.dst, facts=facts, extras=False)
        uncovered = set(rendered.uncovered)
        parent = {b: a for a, b, d in gt.edges(data=True) if d.get("kind") == "contains"}
        for nid in rendered.uncovered:
            if parent.get(nid) in uncovered:
                continue  # 所属对象已经报了
            d = gt.nodes[nid]
            sub = sum(1 for x in uncovered if x.startswith(nid + "/"))
            self.unsupported.append(
                _item(
                    "node",
                    "translate.unsupported.no_render",
                    self.to_src.get(nid, nid),
                    reason="no_render",
                    schema=d.get("schema"),
                    value=d.get("key") if d.get("kind") == "object" else d.get("value"),
                    profile=self.dst,
                    count=sub,
                    lines=list(d.get("lines") or []),
                )
            )
        self.extras()
        for inf in rendered.inferred:
            self.warnings.append(
                _item(
                    "inferred_value",
                    "translate.warn.inferred_value",
                    inf["node"],
                    level="warning",
                    schema=inf["schema"],
                    value=inf["value"],
                    profile=self.dst,
                )
            )
        self.interface_types(gt)
        text = rendered.text
        explained = {u["node"] for u in self.unsupported if u["node"]} | self.secret_shells | self.omitted
        explained |= {w["node"] for w in self.warnings if w["node"]}
        check = self.verify(text, explained) if verify else {"checked": False}
        src_family = self.kb.profiles[self.src].family
        stats = {
            "facts": len(facts),
            "rendered": len(rendered.covered),
            "lines": sum(1 for ln in rendered.lines if ln.kind == "command"),
            "unsupported": sum(1 for u in self.unsupported if u["kind"] == "node"),
            "not_translated": sum(1 for u in self.unsupported if u["kind"] != "node"),
            "defaults_omitted": len(self.defaults),
            "default_differs": self.default_counts["differs"],
            "default_unknown": self.default_counts["unknown"],
            "defaults_same": self.default_counts["same"],
            "warnings": len(self.warnings),
        }
        return {
            "source": {
                "device": self.g.graph.get("device"),
                "profile": self.src,
                "family": src_family,
            },
            "target": {"profile": self.dst, "family": self.kb.profiles[self.dst].family},
            "interface_map": self.raw_map,
            "text": text,
            "lines": rendered.line_dicts(),
            "warnings": self.warnings,
            "unsupported": self.unsupported,
            "defaults": self.defaults,
            "stats": stats,
            "verify": check,
        }


def translate(
    g_src: nx.MultiDiGraph,
    kb: KnowledgeBase,
    src_profile: str,
    dst_profile: str,
    interface_map: dict[str, str] | None = None,
    verify: bool = True,
    rules: Any = None,
    target_graph: nx.MultiDiGraph | None = None,
) -> dict[str, Any]:
    """翻译：返回 {text, lines, warnings[], unsupported[], defaults[], stats, verify, source, target}。

    rules（naming.RuleSet，REQ-032）：先在源图副本上按规则集改名（对象与引用一起改），端口映射并入接口映射表
    （显式给出的 interface_map 优先），结果另有 naming（改名清单、冲突、命名规范告警）；不给时结果与原来完全一致。
    target_graph：目标设备现有配置的图（新名与其中已有的名称重名时报冲突）。

    跨平台族时，没有给出映射的接口按目标平台的类型写法改名、编号不变（LoopBack ↔ Loopback、Eth-Trunk ↔ Port-channel…），
    结果的 interface_map_auto 列出这些自动换名（REQ-055-26）。"""
    auto = _auto_map(g_src, kb, src_profile, dst_profile, interface_map)
    if auto:
        interface_map = {**auto, **(interface_map or {})}
    if rules is None:
        res = _Translator(g_src, kb, src_profile, dst_profile, interface_map).run(verify)
        res["interface_map_auto"] = auto
        renum = _renumber(res, g_src, kb, dst_profile)
        if not renum:
            return res
        # 目标平台要求编号是数字的对象（Cisco IS-IS 的进程名 CORE → 华为 isis 1）：编上号、引用一起改，再译一次
        res = _Translator(_apply_renumber(g_src, kb, renum), kb, src_profile, dst_profile, interface_map).run(verify)
        res["interface_map_auto"] = auto
        res["warnings"] += [
            _item("key_renumbered", "translate.warn.key_renumbered", f"{_short(t, None)}[{k}]", schema=t, old=k, new=v)
            for t, k, v in renum
        ]
        res["stats"]["warnings"] = len(res["warnings"])
        return res
    from lmesh.core import naming

    if dst_profile not in kb.profiles:
        raise TranslateError("parse.profile_unknown", profile=dst_profile)
    g2, ports, report = naming.run(g_src, kb, rules, dst_profile, target_graph)
    result = _Translator(g2, kb, src_profile, dst_profile, {**ports, **(interface_map or {})}).run(verify)
    result["naming"] = report
    result["interface_map_auto"] = {k: v for k, v in auto.items() if k not in ports}
    return result


def _int_keyed(kb: KnowledgeBase, family: str, schema: str) -> bool:
    """目标平台族里写出这类对象的命令卡，键参数都是整数（华为 isis <process-id>）。"""
    types = set()
    for card in kb.cards.values():
        if card.family != family:
            continue
        expr = str((card.maps or {}).get(schema) or "")
        if expr.startswith("$") and "||" not in expr and expr[1:] in card.params:
            types.add(str(card.params[expr[1:]].get("type") or ""))
    return types == {"integer"}


def _apply_renumber(g: nx.MultiDiGraph, kb: KnowledgeBase, renum: list[tuple[str, str, str]]) -> nx.MultiDiGraph:
    """图副本上给顶层对象换键（节点编号与子树一起换），并改掉按名称引用它的属性取值。"""
    g2 = g.copy()
    for schema, old, new in renum:
        src_id, dst_id = f"{_short(schema, None)}[{old}]", f"{_short(schema, None)}[{new}]"
        mapping = {n: dst_id + n[len(src_id) :] for n in g2.nodes if n == src_id or n.startswith(src_id + "/")}
        nx.relabel_nodes(g2, mapping, copy=False)
        g2.nodes[dst_id]["key"] = g2.nodes[dst_id]["raw"] = new
        refs = {d.src for d in kb.deps if d.kind == "reference" and d.dst == schema}
        refs |= {n.id for n in kb.nodes.values() if n.type == "ref" and n.ref == schema}
        for _, d in g2.nodes(data=True):
            if d.get("kind") == "attr" and d.get("schema") in refs and str(d.get("value")) == old:
                d["value"] = d["raw"] = new
    return g2


def _renumber(res: dict[str, Any], g: nx.MultiDiGraph, kb: KnowledgeBase, dst: str) -> list[tuple[str, str, str]]:
    """没能写出、键不是数字、而目标平台要求数字编号的顶层对象：[(Schema, 旧键, 新编号)]，新编号从 1 起取没用过的。"""
    fam = kb.profiles[dst].family
    out: list[tuple[str, str, str]] = []
    used: dict[str, set[str]] = defaultdict(set)
    for _, d in g.nodes(data=True):
        if d.get("kind") == "object" and isinstance(d.get("key"), (str, int)):
            used[str(d.get("schema"))].add(str(d.get("key")))
    for u in res.get("unsupported") or []:
        node = str(u.get("node") or "")
        d = g.nodes.get(node) if node in g else None
        if u.get("kind") != "node" or d is None or d.get("kind") != "object" or "/" in node:
            continue
        key, schema = d.get("key"), str(d.get("schema"))
        if not isinstance(key, str) or key.isdigit() or not _int_keyed(kb, fam, schema):
            continue
        n = 1
        while str(n) in used[schema]:
            n += 1
        used[schema].add(str(n))
        out.append((schema, key, str(n)))
    return out


def _auto_map(g: nx.MultiDiGraph, kb: KnowledgeBase, src: str, dst: str, user: dict[str, str] | None) -> dict[str, str]:
    """跨平台族时没有给出映射的接口：{源接口: 目标平台写法}（割接迁移的建议，不用端口清单）。"""
    if src not in kb.profiles or dst not in kb.profiles or kb.profiles[src].family == kb.profiles[dst].family:
        return {}
    from lmesh.core import migration

    try:
        sug = migration.suggest_map(g, kb, src, dst, user, inventory=False)
    except migration.MigrateError:
        return {}
    given = {cmp.interface_name(str(k)).lower() for k in (user or {})}
    return {
        r["source"]: r["target"]
        for r in sug["map"]
        if r.get("target") and r["target"] != r["source"] and cmp.interface_name(r["source"]).lower() not in given
    }


def translate_text(
    text: str,
    kb: KnowledgeBase,
    dst_profile: str,
    src_profile: str | None = None,
    interface_map: dict[str, str] | None = None,
    device: str = "device",
    verify: bool = True,
    rules: Any = None,
) -> dict[str, Any]:
    """配置文本 → 解析建图 → 翻译（CLI、API 共用）。"""
    from lmesh.core import analysis
    from lmesh.core import graph as graphmod

    if dst_profile not in kb.profiles:
        raise TranslateError("parse.profile_unknown", profile=dst_profile)
    try:
        res = analysis.parse_text(text, kb, src_profile)
    except analysis.AnalysisError as e:
        raise TranslateError(str(e), profile=src_profile or "") from e
    g = graphmod.build(res.parsed, kb, res.profile, device)
    return translate(g, kb, res.profile, dst_profile, interface_map, verify, rules)
