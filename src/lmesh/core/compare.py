"""配置对比：两张配置图按 Schema 节点比较有效值（同厂商或跨厂商），识别改名，按语义规范化后判断等价。

流程：
    1. 规范化（_Canon）：沿 contains 边遍历一张图，给每个对象 / 属性算出规范编号（键值按节点类型规范化：
       掩码 → 长度、接口名缩写 → 全称、RD / RT 写法、大小写等），属性取有效值（显式值，否则 Profile 默认值或派生值）。
       复合键里取值为 both 的枚举字段（RT 方向）展开成另外两个取值（import + export），与分开写的两条等价。
    2. 改名识别：Schema 中被 ref 指向的对象类型（路由策略、前缀列表、VRF、对等体组……），只在一边出现、
       除名字外内容相同（或相似度达到阈值）的成对对象判定为改名；A 侧按改名映射重新规范化，引用它们的属性不再报差异。
       引用之间可能有依赖（路由策略引用前缀列表），所以反复识别直到没有新的改名。
    3. 逐节点比较：两边都有的属性比较有效值；只在一边出现的对象只在最上层报一次；
       未映射到 Schema 的命令（ext）与原文行（raw，选项开启时）按所属对象作为多重集合比较；未识别行单独列出。

不写死功能域与特例：节点类型、键字段的类型、可被引用的类型、有序列表都从 Schema 得到。
"""

from __future__ import annotations

import ipaddress
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from lmesh.core.graph import DEVICE, _short
from lmesh.core.kb import KnowledgeBase
from lmesh.core.kb.model import NODE_TYPES, SchemaNode

KINDS = ("added", "removed", "changed", "renamed")

# 设备身份（hide_identity 选项隐藏的差异）：每台设备本来就不同的取值，模板对比、同角色设备对比时不是问题。
# 只过滤结果，不影响配对与改名识别。Schema 中不存在的节点自动忽略。
IDENTITY_ATTRS = (
    "bgp.instance.router_id",  # BGP Router ID
    "ospf.process.router_id",  # OSPF Router ID
    "bfd.session.peer",  # 静态 BFD 会话的对端地址
    "mgmt.snmp.location",  # SNMP 位置（站点）
)
IDENTITY_OBJECTS = (
    "interface.ipv4",  # 接口 IPv4 地址（以地址为键：地址不同表现为一删一增）
    "bgp.peer",  # BGP 对等体地址
    "isis.process.net",  # IS-IS NET（含系统 ID）
)
IDENTITY_OBJECTS_IP_KEY = ("bgp.af.peer",)  # 键是 IP 地址时才算身份（按组名写的不算）
IDENTITY_RAW = re.compile(r"^\s*(sysname|hostname)\s", re.IGNORECASE)  # 原文行：主机名


def identity_spec(kb: KnowledgeBase) -> list[dict[str, str]]:
    """当前知识库中有效的身份节点清单（结果的 options.hidden_identity）。"""
    out = [{"schema": s, "match": "attr"} for s in IDENTITY_ATTRS if s in kb.nodes]
    out += [{"schema": s, "match": "object"} for s in IDENTITY_OBJECTS if s in kb.nodes]
    out += [{"schema": s, "match": "object_ip_key"} for s in IDENTITY_OBJECTS_IP_KEY if s in kb.nodes]
    out.append({"schema": "", "match": "raw", "pattern": IDENTITY_RAW.pattern})
    return out


def _is_ipv4_key(v: Any) -> bool:
    try:
        ipaddress.IPv4Address(str(v).strip())
    except ValueError:
        return False
    return True


def is_identity(d: dict[str, Any]) -> bool:
    """差异是否只是设备身份不同。"""
    schema = d.get("schema") or ""
    if d["node_kind"] == "attr":
        return schema in IDENTITY_ATTRS
    if d["node_kind"] == "object" and d["kind"] in ("added", "removed"):
        if schema in IDENTITY_OBJECTS:
            return True
        if schema in IDENTITY_OBJECTS_IP_KEY:
            side = d["a"] or d["b"] or {}
            key = side.get("value")
            vals = list(key.values()) if isinstance(key, dict) else [key]
            return any(_is_ipv4_key(v) for v in vals if v not in (None, ""))
    if d["node_kind"] == "raw":
        side = d["a"] or d["b"] or {}
        return bool(IDENTITY_RAW.match(str(side.get("value") or "")))
    return False


_IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_WS = re.compile(r"\s+")


class CompareError(ValueError):
    """对比参数错误。key 是文案键；kind 为 param（参数错误）或 not_found（资源不存在）。"""

    def __init__(self, key: str, kind: str = "param", **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.fmt = key, kind, fmt


# ---------------------------------------------------------------- 值的规范化

# 接口类型名：小写写法 / 缩写 → 统一写法。没有列出的缩写按“唯一前缀”匹配全称。
_IF_CANON = {
    "gigabitethernet": "GigabitEthernet",
    "ge": "GigabitEthernet",
    "gi": "GigabitEthernet",
    "gig": "GigabitEthernet",
    "xgigabitethernet": "XGigabitEthernet",
    "xge": "XGigabitEthernet",
    "tengigabitethernet": "TenGigabitEthernet",
    "te": "TenGigabitEthernet",
    "tengige": "TenGigabitEthernet",
    "fortygigabitethernet": "FortyGigabitEthernet",
    "fo": "FortyGigabitEthernet",
    "hundredgige": "HundredGigE",
    "hu": "HundredGigE",
    "fastethernet": "FastEthernet",
    "fa": "FastEthernet",
    "ethernet": "Ethernet",
    "eth": "Ethernet",
    "eth-trunk": "Eth-Trunk",
    "port-channel": "Port-channel",
    "po": "Port-channel",
    "loopback": "Loopback",
    "lo": "Loopback",
    "vlanif": "Vlanif",
    "vlan": "Vlan",
    "vbdif": "Vbdif",
    "bdi": "BDI",
    "null": "NULL",
    "nu": "NULL",
    "tunnel": "Tunnel",
    "tu": "Tunnel",
    "serial": "Serial",
    "se": "Serial",
    "meth": "MEth",
    "virtual-template": "Virtual-Template",
    "virtual-ethernet": "Virtual-Ethernet",
    "global-ve": "Global-VE",
}
_IF_FULL = sorted({v.lower(): v for v in _IF_CANON.values()}.items())
_IF_SPLIT = re.compile(r"^(\d+GE|[A-Za-z][A-Za-z\-]*?)\s*(\d.*)?$")


def interface_name(name: str) -> str:
    """接口名的统一写法：GE0/0/1、Gi0/0/1、gigabitethernet 0/0/1 → GigabitEthernet0/0/1。"""
    s = str(name).strip()
    m = _IF_SPLIT.match(s)
    if not m:
        return s
    kind, rest = m.group(1), (m.group(2) or "").replace(" ", "")
    low = kind.lower()
    canon = _IF_CANON.get(low)
    if canon is None and re.fullmatch(r"\d+ge", low):
        canon = kind.upper()
    if canon is None and len(low) >= 2:
        hits = [full for lf, full in _IF_FULL if lf.startswith(low)]
        canon = hits[0] if len(hits) == 1 else None
    return (canon or kind) + rest


def _int_text(s: str) -> str:
    return str(int(s)) if s.isdigit() else s


def _asn(s: str) -> str:
    """AS 号：asdot（1.2）换成 asplain（65538），去掉前导零。"""
    s = s.strip()
    if re.fullmatch(r"\d+\.\d+", s):
        hi, lo = s.split(".")
        return str(int(hi) * 65536 + int(lo))
    return _int_text(s)


def _rd(s: str) -> str:
    """RD / RT：ASN:nn、IP:nn、asdot:nn 统一写法。"""
    s = s.strip()
    left, sep, right = s.rpartition(":")
    if not sep:
        return s
    left = _ipv4(left) if _IPV4.match(left) else _asn(left)
    return f"{left}:{_int_text(right)}"


def _ipv4(s: str) -> str:
    try:
        return str(ipaddress.IPv4Address(s.strip()))
    except ValueError:
        return s.strip()


def _mask_len(s: str) -> str:
    s = s.strip()
    if _IPV4.match(s):
        try:
            n = int(ipaddress.IPv4Address(s))
        except ValueError:
            return s
        inv = (~n) & 0xFFFFFFFF
        if (inv & (inv + 1)) == 0:
            return str(bin(n).count("1"))
    return _int_text(s)


def _prefix(s: str) -> str:
    s = _WS.sub(" ", s.strip())
    if "/" in s:
        addr, _, length = s.partition("/")
    elif " " in s:
        addr, _, length = s.partition(" ")
    else:
        return _ipv4(s)
    return f"{_ipv4(addr)}/{_mask_len(length)}"


def norm_scalar(node_type: str, value: Any, ifmap: dict[str, str] | None = None) -> Any:
    """按节点类型规范化一个取值，用于判断语义等价。"""
    if value is None:
        return None
    if node_type in ("boolean", "flag"):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "enable", "enabled")
    if isinstance(value, bool):
        return value
    s = str(value)
    if node_type == "integer":
        t = _mask_len(s)
        return int(t) if t.isdigit() else t
    if node_type == "mask":
        t = _mask_len(s)
        return int(t) if t.isdigit() else t
    if node_type == "ipv4":
        return _ipv4(s)
    if node_type == "prefix":
        return _prefix(s)
    if node_type in ("rd", "community"):
        return " ".join(_rd(x) for x in s.split())
    if node_type == "asn":
        return _asn(s)
    if node_type == "enum":
        return s.strip().lower()
    if node_type == "interface":
        n = interface_name(s)
        return map_interface(n, ifmap) if ifmap else n
    if node_type == "text":
        return s.strip()
    return _WS.sub(" ", s.strip())


def map_interface(name: str, ifmap: dict[str, str]) -> str:
    """跨厂商接口映射（已规范化的名字）：先整名匹配，再按父接口匹配（GE0/2/1.101 → 映射后的父接口 + .101）。"""
    if name.lower() in ifmap:
        return ifmap[name.lower()]
    base, dot, sub = name.partition(".")
    if dot and base.lower() in ifmap:
        return f"{ifmap[base.lower()]}.{sub}"
    return name


def _sort_key(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)


def norm_value(node_type: str, value: Any, ordered: bool = False, ifmap: dict[str, str] | None = None) -> Any:
    """列表：只有一个元素时等同于标量；无序（Schema 没标 ordered）时排序后比较。"""
    if isinstance(value, list | tuple):
        items = [norm_scalar(node_type, v, ifmap) for v in value]
        if len(items) == 1:
            return items[0]
        return items if ordered else sorted(items, key=_sort_key)
    if isinstance(value, dict):
        return {k: norm_scalar("string", v) for k, v in sorted(value.items())}
    return norm_scalar(node_type, value, ifmap)


def load_interface_map(path: Path) -> dict[str, str]:
    """接口映射表文件：JSON / YAML 的 {A 接口: B 接口}，或每行两列（空白、逗号或 = 分隔，# 开头为注释）。"""
    if not path.exists():
        raise CompareError("compare.ifmap_missing", "not_found", path=str(path))
    text = path.read_text(encoding="utf-8-sig")
    data: Any = None
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise CompareError("compare.ifmap_invalid", path=str(path)) from e
    elif path.suffix.lower() in (".yaml", ".yml"):
        from ruamel.yaml import YAML

        try:
            data = YAML(typ="safe", pure=True).load(text)
        except Exception as e:  # YAML 语法错误
            raise CompareError("compare.ifmap_invalid", path=str(path)) from e
    else:
        data = {}
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            parts = [p for p in re.split(r"[\s,=;]+", line) if p]
            if len(parts) != 2:
                raise CompareError("compare.ifmap_invalid", path=str(path))
            data[parts[0]] = parts[1]
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise CompareError("compare.ifmap_invalid", path=str(path))
    return dict(data)


# ---------------------------------------------------------------- 规范化一张图


@dataclass
class Item:
    cid: str  # 规范编号（显示用）
    kind: str  # object / attr
    node: str  # 图中的原始编号
    schema: str
    domain: str
    value: Any
    origin: str
    lines: list[int]
    parent: str  # 父对象的规范编号；顶层为 ""
    key: Any = None  # 对象的规范键（单键为字符串，复合键为字典）


@dataclass
class Multi:
    """按所属对象比较的多重集合成员：未映射的命令（ext）或原文行（raw）。"""

    owner: str
    group: str  # ext：命令卡编号；raw：固定为 raw
    sig: str  # 比较用的签名
    value: Any
    node: str
    lines: list[int]
    domain: str


@dataclass
class _Canon:
    items: dict[str, Item] = field(default_factory=dict)
    ext: list[Multi] = field(default_factory=list)
    raw: list[Multi] = field(default_factory=list)
    unknown: list[dict[str, Any]] = field(default_factory=list)
    node_cids: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    subtree_lines: dict[str, list[int]] = field(default_factory=dict)


class _Schema:
    """从 Schema 推出比较所需的信息：键字段的类型、键字段引用的对象类型、可被引用的类型、both 展开。"""

    def __init__(self, kb: KnowledgeBase):
        self.kb = kb
        self.ref_types = {n.ref for n in kb.nodes.values() if n.type == "ref" and n.ref}
        by_short: dict[str, set[str]] = defaultdict(set)
        for n in kb.nodes.values():
            if n.type == "ref" and n.ref:
                by_short[n.id.rsplit(".", 1)[-1]].add(n.ref)
        # 没有对应属性节点的键字段（bgp.af 的 vrf）：同名的 ref 属性都指向同一类型时，按引用该类型处理
        self.ref_by_name = {k: next(iter(v)) for k, v in by_short.items() if len(v) == 1}

    def node(self, sid: str | None) -> SchemaNode | None:
        return self.kb.nodes.get(sid) if sid else None

    def field_type(self, sn: SchemaNode, f: str) -> tuple[str, str | None]:
        """键字段 f 的（节点类型, 引用的对象类型）。"""
        child = self.kb.nodes.get(f"{sn.id}.{f}")
        if child is not None:
            return child.type, child.ref if child.type == "ref" else None
        if len(sn.key) <= 1 and sn.id in NODE_TYPES:  # 对象本身就是一种取值类型（接口名）
            return sn.id, None
        ref = self.ref_by_name.get(f)
        return ("ref", ref) if ref else ("string", None)

    def both_fields(self, sn: SchemaNode) -> dict[str, list[str]]:
        """复合键中可写成 both 的枚举字段 → both 代表的取值（choices 为另外两项）。"""
        out: dict[str, list[str]] = {}
        if len(sn.key) < 2:
            return out
        for f in sn.key:
            child = self.kb.nodes.get(f"{sn.id}.{f}")
            if child and child.type == "enum" and child.choices and "both" in child.choices and len(child.choices) == 3:
                out[f] = [c for c in child.choices if c != "both"]
        return out


def _key_text(key: Any) -> str:
    if isinstance(key, dict):
        return ",".join(f"{k}={'' if v is None else v}" for k, v in key.items())
    return "" if key is None else str(key)


def _join(parent: str, seg: str) -> str:
    return f"{parent}/{seg}" if parent else seg


def _ws(text: str) -> str:
    return _WS.sub(" ", text.strip())


class _Canonicalizer:
    def __init__(
        self,
        g: nx.MultiDiGraph,
        kb: KnowledgeBase,
        sch: _Schema,
        renames: dict[tuple[str, str], str] | None = None,
        ifmap: dict[str, str] | None = None,
    ):
        self.g, self.kb, self.sch = g, kb, sch
        self.renames = renames or {}
        self.old_names = {old: new for (_, old), new in self.renames.items()}
        self.ifmap = ifmap or None
        self.out = _Canon()
        self.children: dict[str, list[str]] = defaultdict(list)
        for a, b, d in g.edges(data=True):
            if d.get("kind") == "contains":
                self.children[a].append(b)
        fam = kb.families.get(str(g.graph.get("family") or ""))
        self.separators = {fam.separator, fam.end} if fam else set()
        pid = g.graph.get("profile")
        self.defaults: dict[str, Any] = {}
        if pid and pid in kb.profiles:
            for nid, e in kb.resolve_profile(pid).entries.items():
                if e.supported and e.default is not None:
                    self.defaults[nid] = e.default

    def _rename(self, ref: str | None, v: Any) -> Any:
        if ref is None or not self.renames:
            return v
        if isinstance(v, list):
            return [self.renames.get((ref, str(x)), x) for x in v]
        return self.renames.get((ref, str(v)), v)

    def _rename_any(self, v: Any) -> Any:
        """未映射命令的参数没有类型信息：取值恰好等于某个被改名对象的旧名字时按改名替换。"""
        if not self.renames:
            return v
        if isinstance(v, dict):
            return {k: self._rename_any(x) for k, x in v.items()}
        if isinstance(v, list):
            return [self._rename_any(x) for x in v]
        return self.old_names.get(str(v), v) if isinstance(v, str) else v

    def _key(self, sn: SchemaNode, key: Any) -> Any:
        if isinstance(key, dict):
            out = {}
            for f, v in key.items():
                t, ref = self.sch.field_type(sn, f)
                v = self._rename(ref, v)
                out[f] = "" if v in (None, "") else norm_scalar(t, v, self.ifmap)
            return out
        f = sn.key[0] if sn.key else "name"
        t, ref = self.sch.field_type(sn, f)
        if sn.id in self.sch.ref_types:  # 被改名的对象本身
            key = self.renames.get((sn.id, str(key)), key)
        key = self._rename(ref, key)
        return norm_scalar(t, key, self.ifmap) if key not in (None, "") else key

    def run(self) -> _Canon:
        self._walk(DEVICE, "", None, {})
        return self.out

    def _domain(self, sid: str | None) -> str:
        sn = self.sch.node(sid)
        return sn.domain if sn else ""

    def _lines_under(self, nid: str) -> list[int]:
        acc: set[int] = set(self.g.nodes[nid].get("lines") or [])
        stack = list(self.children.get(nid, []))
        while stack:
            n = stack.pop()
            acc.update(self.g.nodes[n].get("lines") or [])
            stack.extend(self.children.get(n, []))
        return sorted(acc)

    def _walk(self, nid: str, parent_cid: str, parent_schema: str | None, override: dict[str, Any]) -> None:
        for child in self.children.get(nid, []):
            d = self.g.nodes[child]
            kind = d.get("kind")
            if kind == "object":
                self._object(child, d, parent_cid, parent_schema)
            elif kind == "attr":
                self._attr(child, d, parent_cid, parent_schema, override)
            elif kind == "ext":
                card = str(d.get("schema") or "")[4:]
                c = self.kb.cards.get(card)
                val = norm_value("string", self._rename_any(d.get("value")))
                sig = ("!" if d.get("negated") else "") + _sort_key(val)
                self.out.ext.append(
                    Multi(parent_cid, card, sig, val, child, list(d.get("lines") or []), c.domain if c else "")
                )
            elif kind in ("raw", "unknown"):
                self._raw(child, d, parent_cid, parent_schema, [])

    def _raw(self, nid: str, d: dict[str, Any], owner: str, owner_schema: str | None, chain: list[str]) -> None:
        text = str(d.get("text") or "")
        if d.get("kind") == "unknown":
            self.out.unknown.append({"line": min(d.get("lines") or [0]), "text": text.strip(), "owner": owner})
        elif text.strip() not in self.separators:  # 异常缩进的分隔行被解析成原文子行：不是配置内容
            sig = " > ".join([*chain, _ws(text)])
            self.out.raw.append(
                Multi(
                    owner,
                    "raw",
                    sig,
                    text.strip(),
                    nid,
                    list(d.get("lines") or []),
                    self._domain(owner_schema) or "raw",
                )
            )
        for child in self.children.get(nid, []):
            cd = self.g.nodes[child]
            if cd.get("kind") in ("raw", "unknown"):
                self._raw(child, cd, owner, owner_schema, [*chain, _ws(text)])

    def _object(self, nid: str, d: dict[str, Any], parent_cid: str, parent_schema: str | None) -> None:
        sn = self.sch.node(d.get("schema"))
        if sn is None:
            return
        key = self._key(sn, d.get("key"))
        variants: list[tuple[Any, dict[str, Any]]] = [(key, {})]
        if isinstance(key, dict):
            for f, alts in self.sch.both_fields(sn).items():
                if str(key.get(f, "")).lower() == "both":
                    variants = [({**key, f: a}, {f: a}) for a in alts]
        short = _short(sn.id, parent_schema)
        lines = self._lines_under(nid)
        for k, ov in variants:
            cid = _join(parent_cid, f"{short}[{_key_text(k)}]")
            self.out.items[cid] = Item(
                cid,
                "object",
                nid,
                sn.id,
                sn.domain,
                None,
                str(d.get("origin", "explicit")),
                list(d.get("lines") or []),
                parent_cid,
                k,
            )
            self.out.node_cids[nid].append(cid)
            self.out.subtree_lines[cid] = lines
            self._walk(nid, cid, sn.id, ov)

    def _attr(
        self, nid: str, d: dict[str, Any], parent_cid: str, parent_schema: str | None, override: dict[str, Any]
    ) -> None:
        sn = self.sch.node(d.get("schema"))
        if sn is None:
            return
        short = _short(sn.id, parent_schema)
        cid = _join(parent_cid, short)
        origin = str(d.get("origin", "explicit"))
        value = d.get("value")
        if short in override:
            value = override[short]
        elif d.get("negated") and not isinstance(value, bool):
            # undo / no 取消了一个取值：有效值回到 Profile 默认值，没有默认值时视为没有配置
            if sn.id not in self.defaults:
                return
            value, origin = self.defaults[sn.id], "default"
        value = self._rename(sn.ref if sn.type == "ref" else None, value)
        self.out.items[cid] = Item(
            cid,
            "attr",
            nid,
            sn.id,
            sn.domain,
            norm_value(sn.type, value, sn.ordered, self.ifmap),
            origin,
            list(d.get("lines") or []),
            parent_cid,
        )
        self.out.node_cids[nid].append(cid)


# ---------------------------------------------------------------- 改名识别


def _signature(c: _Canon, cid: str) -> set[str]:
    """对象内容（不含自己的名字）：子树中各属性的相对编号与有效值、未映射命令的签名。"""
    prefix = cid + "/"
    sig = {
        f"{k[len(prefix) :]}={_sort_key(it.value) if it.kind == 'attr' else '{}'}"
        for k, it in c.items.items()
        if k.startswith(prefix)
    }
    sig |= {
        f"{m.owner[len(cid) :]}/ext[{m.group}]={m.sig}" for m in c.ext if m.owner == cid or m.owner.startswith(prefix)
    }
    return sig


def _similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _detect_renames(ca: _Canon, cb: _Canon, sch: _Schema, threshold: float) -> dict[tuple[str, str], tuple[str, float]]:
    """只在一边出现、同一父对象下、同类型的可引用对象：内容相同（或相似度达到阈值）的唯一配对判定为改名。"""
    found: dict[tuple[str, str], tuple[str, float]] = {}
    for t in sorted(sch.ref_types):
        sn = sch.node(t)
        if sn is None or len(sn.key) > 1:
            continue
        only_a = [it for k, it in ca.items.items() if it.schema == t and it.kind == "object" and k not in cb.items]
        only_b = [it for k, it in cb.items.items() if it.schema == t and it.kind == "object" and k not in ca.items]
        if not only_a or not only_b:
            continue
        sa = {it.cid: _signature(ca, it.cid) for it in only_a}
        sb = {it.cid: _signature(cb, it.cid) for it in only_b}
        scores: dict[tuple[str, str], float] = {}
        for ia in only_a:
            if not sa[ia.cid]:  # 空对象（没有任何内容）无从判断
                continue
            for ib in only_b:
                if ia.parent != ib.parent or not sb[ib.cid]:
                    continue
                s = 1.0 if sa[ia.cid] == sb[ib.cid] else _similarity(sa[ia.cid], sb[ib.cid])
                if s >= threshold:
                    scores[(ia.cid, ib.cid)] = s
        best_a: dict[str, float] = defaultdict(float)
        best_b: dict[str, float] = defaultdict(float)
        for (ca_, cb_), s in scores.items():
            best_a[ca_], best_b[cb_] = max(best_a[ca_], s), max(best_b[cb_], s)
        by_cid_a = {it.cid: it for it in only_a}
        by_cid_b = {it.cid: it for it in only_b}
        for (ca_, cb_), s in scores.items():
            if s < best_a[ca_] or s < best_b[cb_]:
                continue
            # 有并列的最佳候选时不确定，不判定
            if sum(1 for (x, _), v in scores.items() if x == ca_ and v == s) > 1:
                continue
            if sum(1 for (_, y), v in scores.items() if y == cb_ and v == s) > 1:
                continue
            found[(t, str(by_cid_a[ca_].key))] = (str(by_cid_b[cb_].key), s)
    return found


# ---------------------------------------------------------------- 对比


@dataclass
class Side:
    graph: nx.MultiDiGraph
    label: str
    device_id: int | None = None
    version_id: int | None = None

    def info(self) -> dict[str, Any]:
        g = self.graph
        return {
            "label": self.label,
            "device": g.graph.get("device"),
            "profile": g.graph.get("profile"),
            "family": g.graph.get("family"),
            "kb_version": g.graph.get("kb_version"),
            "device_id": self.device_id,
            "version_id": self.version_id,
            "nodes": g.number_of_nodes(),
        }


def _side_value(it: Item | None, lines: list[int] | None = None) -> dict[str, Any] | None:
    if it is None:
        return None
    return {
        "node": it.node,
        "value": it.value if it.kind == "attr" else it.key,
        "origin": it.origin,
        "lines": lines if lines is not None else it.lines,
    }


def _multi_value(m: Multi | None) -> dict[str, Any] | None:
    if m is None:
        return None
    return {"node": m.node, "value": m.value, "origin": "explicit", "lines": m.lines}


def _top(cid: str) -> str:
    depth, i = 0, 0
    for i, ch in enumerate(cid):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "/" and depth == 0:
            return cid[:i]
    return cid


def compare(
    a: Side,
    b: Side,
    kb: KnowledgeBase,
    domain: str | None = None,
    include_raw: bool = False,
    interface_map: dict[str, str] | None = None,
    rename_threshold: float = 1.0,
    hide_identity: bool = False,
) -> dict[str, Any]:
    """对比两张配置图，返回可直接序列化为 JSON 的结果（差异、改名、统计、未识别行）。

    hide_identity：隐藏设备身份差异（IDENTITY_*），被隐藏的差异放在 hidden_diffs，个数为 summary.hidden_identity。"""
    if not 0 < rename_threshold <= 1:
        raise CompareError("compare.bad_threshold", value=rename_threshold)
    domains = set(kb.domains) | {n.domain for n in kb.nodes.values()}
    if domain and domain not in domains:
        raise CompareError("compare.bad_domain", domain=domain, domains=", ".join(sorted(domains)))
    sch = _Schema(kb)
    ifmap = {interface_name(k).lower(): interface_name(v) for k, v in (interface_map or {}).items()}
    cb = _Canonicalizer(b.graph, kb, sch).run()
    renames: dict[tuple[str, str], tuple[str, float]] = {}
    ca = ca0 = _Canonicalizer(a.graph, kb, sch, ifmap=ifmap).run()
    for _ in range(6):  # 引用链上的改名（策略 → 前缀列表）逐轮识别
        new = _detect_renames(ca, cb, sch, rename_threshold)
        new = {k: v for k, v in new.items() if k not in renames}
        if not new:
            break
        renames.update(new)
        ca = _Canonicalizer(a.graph, kb, sch, {k: v[0] for k, v in renames.items()}, ifmap).run()

    diffs: list[dict[str, Any]] = []

    def add(kind: str, node_kind: str, cid: str, schema: str | None, dom: str, va: Any, vb: Any, **extra: Any) -> None:
        diffs.append(
            {
                "kind": kind,
                "node_kind": node_kind,
                "node": cid,
                "schema": schema,
                "domain": dom,
                "a": va,
                "b": vb,
                "from": extra.get("from_"),
                "to": extra.get("to"),
                "similarity": extra.get("similarity"),
                "count": extra.get("count"),
                "related": [],
            }
        )

    def present(c: _Canon, cid: str) -> bool:
        return cid == "" or cid in c.items

    # 改名
    renamed_cids: dict[str, str] = {}
    for (t, old_name), (new_name, score) in sorted(renames.items()):
        sn = sch.node(t)
        cid_b = next(
            (k for k, it in cb.items.items() if it.schema == t and it.kind == "object" and str(it.key) == new_name),
            None,
        )
        if cid_b is None or cid_b not in ca.items:
            continue
        ra, rb = ca.items[cid_b], cb.items[cid_b]
        a_cid_orig = next(iter(ca0.node_cids.get(ra.node, [])), cid_b)
        add(
            "renamed",
            "object",
            cid_b,
            t,
            sn.domain if sn else "",
            {**(_side_value(ra, ca.subtree_lines.get(cid_b)) or {}), "value": old_name, "cid": a_cid_orig},
            _side_value(rb, cb.subtree_lines.get(cid_b)),
            from_=old_name,
            to=new_name,
            similarity=round(score, 4),
        )
        renamed_cids[cid_b] = old_name

    # 对象与属性
    default_only: list[dict[str, Any]] = []
    for cid in sorted(set(ca.items) | set(cb.items)):
        ia, ib = ca.items.get(cid), cb.items.get(cid)
        it = ia or ib
        assert it is not None
        if ia is not None and ib is not None:
            if it.kind == "attr" and ia.value != ib.value:
                add("changed", "attr", cid, it.schema, it.domain, _side_value(ia), _side_value(ib))
            continue
        if not (present(ca, it.parent) and present(cb, it.parent)):
            continue  # 祖先对象已经报了新增 / 删除
        kind = "removed" if ia is not None else "added"
        if it.kind == "object":
            c = ca if ia is not None else cb
            count = sum(1 for k in c.items if k.startswith(cid + "/"))
            sv = _side_value(it, c.subtree_lines.get(cid))
            add(kind, "object", cid, it.schema, it.domain, sv if ia else None, None if ia else sv, count=count)
        elif it.origin == "default":
            # 只有一边的 Profile 给这个属性定义了默认值、另一边没有配置也没有默认值：两边不可比，不算差异，单独列出
            if not domain or it.domain == domain:
                default_only.append(
                    {
                        "node": cid,
                        "schema": it.schema,
                        "domain": it.domain,
                        "side": "a" if ia is not None else "b",
                        "value": it.value,
                    }
                )
        else:
            add(kind, "attr", cid, it.schema, it.domain, _side_value(ia), _side_value(ib))

    # 未映射命令（ext）：同厂商（同平台族）才比较；跨平台族时这些厂商私有命令没有对应关系
    same_family = a.graph.graph.get("family") == b.graph.graph.get("family")
    multis = [("ext", ca.ext, cb.ext)] if same_family else []
    if include_raw:
        multis.append(("raw", ca.raw, cb.raw))
    for node_kind, la, lb in multis:
        ga: dict[tuple[str, str], list[Multi]] = defaultdict(list)
        gb: dict[tuple[str, str], list[Multi]] = defaultdict(list)
        for m in la:
            ga[(m.owner, m.group)].append(m)
        for m in lb:
            gb[(m.owner, m.group)].append(m)
        for key in sorted(set(ga) | set(gb)):
            owner, group = key
            if not (present(ca, owner) and present(cb, owner)):
                continue
            ma, mb = list(ga.get(key, [])), list(gb.get(key, []))
            common = Counter(m.sig for m in ma) & Counter(m.sig for m in mb)
            left = Counter(common)
            ma2 = []
            for m in ma:
                if left[m.sig] > 0:
                    left[m.sig] -= 1
                else:
                    ma2.append(m)
            left = Counter(common)
            mb2 = []
            for m in mb:
                if left[m.sig] > 0:
                    left[m.sig] -= 1
                else:
                    mb2.append(m)
            seg = f"ext[{group}]" if node_kind == "ext" else "raw"
            if node_kind == "ext" and len(ma2) == 1 and len(mb2) == 1:
                add(
                    "changed", "ext", _join(owner, seg), None, ma2[0].domain, _multi_value(ma2[0]), _multi_value(mb2[0])
                )
                continue
            for m in ma2:
                cid = _join(owner, seg if node_kind == "ext" else f"raw[{m.sig}]")
                add("removed", node_kind, cid, None, m.domain, _multi_value(m), None)
            for m in mb2:
                cid = _join(owner, seg if node_kind == "ext" else f"raw[{m.sig}]")
                add("added", node_kind, cid, None, m.domain, None, _multi_value(m))

    # 关联差异：两边图里的引用边，两端都在差异里（或一端是改名的对象）时互相关联
    by_cid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in diffs:
        by_cid[d["node"]].append(d)
    for c, side in ((ca, a), (cb, b)):
        for src, dst, ed in side.graph.edges(data=True):
            if ed.get("kind") != "reference":
                continue
            for s_cid in c.node_cids.get(src, []):
                for d_cid in c.node_cids.get(dst, []):
                    if d_cid in by_cid and (s_cid in by_cid or d_cid in renamed_cids):
                        for d in by_cid[d_cid]:
                            if s_cid not in d["related"]:
                                d["related"].append(s_cid)
                    if s_cid in by_cid and d_cid in by_cid:
                        for d in by_cid[s_cid]:
                            if d_cid not in d["related"]:
                                d["related"].append(d_cid)
    for d in diffs:
        d["related"].sort()

    if domain:
        diffs = [d for d in diffs if d["domain"] == domain]
    order = {dm: i for i, dm in enumerate(kb.domains)}
    diffs.sort(key=lambda d: (order.get(d["domain"], len(order)), d["domain"], d["node"], KINDS.index(d["kind"])))
    hidden: list[dict[str, Any]] = []
    if hide_identity:
        hidden = [d for d in diffs if is_identity(d)]
        diffs = [d for d in diffs if not is_identity(d)]

    return {
        "a": a.info(),
        "b": b.info(),
        "options": {
            "domain": domain,
            "include_raw": include_raw,
            "interface_map": len(ifmap),
            "rename_threshold": rename_threshold,
            "compare_ext": same_family,
            "hide_identity": hide_identity,
            "hidden_identity": identity_spec(kb) if hide_identity else [],
        },
        "equal": not diffs,
        "diffs": diffs,
        "hidden_diffs": hidden,
        "renames": [
            {"schema": t, "from": old, "to": new, "similarity": round(s, 4)}
            for (t, old), (new, s) in sorted(renames.items())
            if not domain or (sch.node(t) and sch.node(t).domain == domain)  # type: ignore[union-attr]
        ],
        "unknown": {"a": ca.unknown, "b": cb.unknown},
        "default_only": default_only,
        "summary": {**summarize(diffs, ca, cb), "default_only": len(default_only), "hidden_identity": len(hidden)},
    }


def summarize(diffs: list[dict[str, Any]], ca: _Canon | None = None, cb: _Canon | None = None) -> dict[str, Any]:
    by_kind = dict.fromkeys(KINDS, 0)
    by_domain: dict[str, dict[str, int]] = {}
    by_object: dict[str, dict[str, Any]] = {}
    for d in diffs:
        by_kind[d["kind"]] += 1
        dm = by_domain.setdefault(d["domain"], {**dict.fromkeys(KINDS, 0), "total": 0})
        dm[d["kind"]] += 1
        dm["total"] += 1
        top = _top(d["node"]) if not d["node"].startswith("raw[") else ""
        ob = by_object.setdefault(top, {"object": top, "domain": d["domain"], **dict.fromkeys(KINDS, 0), "total": 0})
        ob[d["kind"]] += 1
        ob["total"] += 1
    return {
        "total": len(diffs),
        "by_kind": by_kind,
        "by_domain": by_domain,
        "by_object": sorted(by_object.values(), key=lambda x: (-x["total"], x["object"])),
        "unknown": {"a": len(ca.unknown) if ca else 0, "b": len(cb.unknown) if cb else 0},
    }


# ---------------------------------------------------------------- 输入：配置文本、设备、配置版本


def side_from_text(text: str, kb: KnowledgeBase, profile: str | None = None, label: str = "text") -> Side:
    from lmesh.core import analysis
    from lmesh.core import graph as graphmod

    try:
        res = analysis.parse_text(text, kb, profile)
    except analysis.AnalysisError as e:
        raise CompareError(str(e), profile=profile or "") from e
    return Side(graphmod.build(res.parsed, kb, res.profile, label), label)


def side_from_version(
    db_url: str, kb: KnowledgeBase, version_id: int, profile: str | None = None, device_id: int | None = None
) -> Side:
    from lmesh.core import analysis, store
    from lmesh.core import graph as graphmod
    from lmesh.core.store.models import ConfigVersion, Device

    with store.session(db_url) as s:
        ver = s.get(ConfigVersion, version_id)
        if ver is None or (device_id is not None and ver.device_id != device_id):
            raise CompareError("compare.version_not_found", "not_found", version=version_id)
        dev = s.get(Device, ver.device_id)
        assert dev is not None
        text, dev_profile, name, dev_id = ver.raw_text, dev.profile or None, dev.name, dev.id
    use = profile or (dev_profile if dev_profile in kb.profiles else None)
    try:
        res = analysis.parse_text(text, kb, use)
    except analysis.AnalysisError as e:
        raise CompareError(str(e), profile=profile or "") from e
    return Side(graphmod.build(res.parsed, kb, res.profile, name), f"{name}@{version_id}", dev_id, version_id)


def side_from_device(db_url: str, kb: KnowledgeBase, device_id: int, profile: str | None = None) -> Side:
    vers = versions(db_url, device_id)
    if not vers:
        raise CompareError("compare.device_not_found", "not_found", target=str(device_id))
    return side_from_version(db_url, kb, vers[0]["id"], profile, device_id)


def device_id_by_name(db_url: str, name: str) -> int | None:
    from sqlalchemy import select

    from lmesh.core import store
    from lmesh.core.store.models import Device

    with store.session(db_url) as s:
        return s.scalar(select(Device.id).where(Device.name == name))


def versions(db_url: str, device_id: int) -> list[dict[str, Any]] | None:
    """设备的配置版本，新的在前；设备不存在时返回 None。seq 是该设备内的序号（从 1 开始）。"""
    from sqlalchemy import select

    from lmesh.core import store
    from lmesh.core.store.models import ConfigVersion, Device, iso

    with store.session(db_url) as s:
        dev = s.get(Device, device_id)
        if dev is None:
            return None
        rows = list(s.scalars(select(ConfigVersion).where(ConfigVersion.device_id == device_id)))
        rows.sort(key=lambda v: v.id)
        out = [
            {
                "id": v.id,
                "seq": i + 1,
                "source_name": v.source_name,
                "collected_at": iso(v.collected_at),
                "kb_version": v.kb_version,
                "lines": len(v.raw_text.split("\n")),
                "latest": i == len(rows) - 1,
            }
            for i, v in enumerate(rows)
        ]
        return list(reversed(out))


def version_text(db_url: str, device_id: int, version_id: int) -> dict[str, Any] | None:
    """配置版本的原文；版本不存在或不属于该设备时返回 None。"""
    from lmesh.core import store
    from lmesh.core.store.models import ConfigVersion

    with store.session(db_url) as s:
        ver = s.get(ConfigVersion, version_id)
        if ver is None or ver.device_id != device_id:
            return None
        return {"version_id": ver.id, "device_id": ver.device_id, "source_name": ver.source_name, "text": ver.raw_text}


# ---------------------------------------------------------------- 对比基准


def benchmark(kb_root: Path, kb: KnowledgeBase | None = None) -> dict[str, Any]:
    """对比基准（验收门槛“真实配置无假差异”）：knowledge/samples/compare/manifest.yaml 中的每个用例
    报出的差异（kind + node）必须与期望完全一致——等价变体为 0 差异，真实修改只报预期的差异。"""
    from lmesh.core import analysis
    from lmesh.core.importer import decode
    from lmesh.core.kb import read_yaml

    kb = kb or analysis.load_kb(kb_root)
    base = kb_root / "samples" / "compare"
    doc = read_yaml(base / "manifest.yaml") or {}
    results = []
    failed = 0
    for case in doc.get("cases") or []:
        pa, pb = (base / str(case["a"])).resolve(), (base / str(case["b"])).resolve()
        profile = case.get("profile")
        sa = side_from_text(decode(pa.read_bytes()), kb, case.get("profile_a", profile), pa.stem)
        sb = side_from_text(decode(pb.read_bytes()), kb, case.get("profile_b", profile), pb.stem)
        r = compare(
            sa,
            sb,
            kb,
            domain=case.get("domain"),
            include_raw=bool(case.get("raw", False)),
            interface_map=case.get("interface_map"),
            rename_threshold=float(case.get("rename_threshold", 1.0)),
        )
        got = {(d["kind"], d["node"]) for d in r["diffs"]}
        want = {(str(e["kind"]), str(e["node"])) for e in case.get("expect") or []}
        passed = got == want
        failed += 0 if passed else 1
        results.append(
            {
                "id": case["id"],
                "passed": passed,
                "diffs": len(r["diffs"]),
                "expected": len(want),
                "unexpected": sorted([list(x) for x in got - want]),
                "missing": sorted([list(x) for x in want - got]),
                "renames": r["renames"],
                "note": case.get("note", ""),
            }
        )
    return {"cases": len(results), "failed": failed, "results": results, "kb_version": kb.version}
