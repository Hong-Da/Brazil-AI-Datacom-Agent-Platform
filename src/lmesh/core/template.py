"""参数化配置模板：格式、加载与校验、变量取值的类型检查、模板正文的渲染（M3-4 / M3-5）。

模板文件 knowledge/templates/<编号>.yaml：元数据 + 变量 + 块 + 带占位符的配置正文。

    id: cisco-asr920-efp-bdi-vrf
    title: {zh-CN: …, en: …, pt-BR: …}
    profile: cisco-iosxe-asr920-17.15     # 解析模板正文、生成配置用的 Profile
    profiles: [cisco-iosxe-asr920-17.15]   # 适用的 Profile（可省：与 profile 同一平台族的都适用）
    match: {extra: allow, extra_scope: matched}
    vars:
      uplink: {type: interface, example: GigabitEthernet0/0/1}
      lan:    {type: prefix, length: [24, 30]}
      gw:     {expr: "lan|host(1)"}       # 派生变量：由别的变量计算
    blocks:
      svc: {repeat: {min: 1, max: 32}, vars: {vlan: {type: vlan, unique: true}}}
      bfd: {optional: true}
    body: |
      interface {{uplink}}
       service instance {{svc.vlan}} ethernet       ← 写在 {% repeat svc %} … {% end %} 之间
      …

占位符 {{名字}} 或 {{名字|过滤器|过滤器}}；块内的变量写成 {{块名.变量}}。块用独占一行的
{% repeat 名字 %} / {% optional 名字 %} 开始、{% end %} 结束，不能嵌套；同一个块可以出现在正文的多处
（例如每个业务既要 VRF 定义、又要子接口和 BGP 地址族），各处按同样的实例展开。

过滤器：ip、network、len、mask、wildcard、broadcast、host(n)（网段第 n 个地址，负数从广播地址往回数）、
add(n)（整数或 IPv4 地址加 n）、upper、lower。

一行参数（生成的输入、提取的输出）：{"变量": 值, "重复块": [{"变量": 值}, …], "可选块": true | false | {"变量": 值}}。
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from lmesh.core.kb import KnowledgeBase

VAR_TYPES = ("ipv4", "prefix", "integer", "vlan", "asn", "rd", "enum", "interface", "word", "text")
INT_TYPES = ("integer", "vlan", "asn")
EXTRA_POLICIES = ("allow", "deny")
EXTRA_SCOPES = ("none", "matched", "domains")
FILTERS = ("ip", "network", "len", "mask", "wildcard", "broadcast", "host", "add", "upper", "lower")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")
PLACEHOLDER = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
CONTROL = re.compile(r"^\s*\{%\s*(repeat|optional|end)(?:\s+([A-Za-z_][A-Za-z0-9_]*))?\s*%\}\s*$")
_FILTER_RE = re.compile(r"^([a-z]+)(?:\(\s*(-?\d+)\s*\))?$")
RESERVED = ("device",)  # 参数表中的设备名列


class TemplateError(ValueError):
    """模板或参数错误。key 是文案键；kind 为 param / not_found / invalid（模板本身有问题，附问题清单）。"""

    def __init__(self, key: str, kind: str = "param", issues: list[dict[str, Any]] | None = None, **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.issues, self.fmt = key, kind, issues or [], fmt


# ---------------------------------------------------------------- 模型


@dataclass
class Var:
    name: str  # 全名：基础变量 vlan、块变量 svc.vlan
    type: str = "word"
    block: str | None = None
    default: Any = None
    example: Any = None
    min: int | None = None
    max: int | None = None
    choices: list[str] = field(default_factory=list)
    pattern: str | None = None
    length: tuple[int, int] | None = None  # prefix：允许的前缀长度
    within: list[str] = field(default_factory=list)  # ipv4 / prefix：必须落在这些网段内
    network: bool = False  # prefix：必须是网络地址（主机位为 0）
    unique: bool = False  # 块变量：各实例取值不同
    expr: str | None = None  # 派生变量的表达式
    title: dict[str, str] = field(default_factory=dict)

    @property
    def short(self) -> str:
        return self.name.rsplit(".", 1)[-1]

    @property
    def derived(self) -> bool:
        return self.expr is not None

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "type": self.type, "block": self.block, "derived": self.derived}
        for k in ("default", "example", "min", "max", "pattern", "expr"):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        if self.choices:
            d["choices"] = list(self.choices)
        if self.length:
            d["length"] = list(self.length)
        if self.within:
            d["within"] = list(self.within)
        if self.network:
            d["network"] = True
        if self.unique:
            d["unique"] = True
        if self.title:
            d["title"] = dict(self.title)
        return d


@dataclass
class Block:
    name: str
    kind: str  # repeat / optional
    min: int = 0
    max: int | None = None
    anchor: str | None = None  # 识别实例时优先用这种 Schema 对象
    title: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "kind": self.kind}
        if self.kind == "repeat":
            d.update(min=self.min, max=self.max)
        if self.anchor:
            d["anchor"] = self.anchor
        if self.title:
            d["title"] = dict(self.title)
        return d


@dataclass
class Segment:
    """正文的一段：普通行（line_no 为模板正文中的行号）或块。"""

    line_no: int = 0
    text: str = ""
    block: str | None = None
    lines: list[Segment] = field(default_factory=list)


@dataclass
class Template:
    id: str
    profile: str
    body: str
    title: dict[str, str] = field(default_factory=dict)
    description: dict[str, str] = field(default_factory=dict)
    version: int = 1
    profiles: list[str] = field(default_factory=list)
    extra: str = "allow"
    extra_scope: str = "matched"
    vars: dict[str, Var] = field(default_factory=dict)  # 全名 → 变量（含派生变量与块变量）
    blocks: dict[str, Block] = field(default_factory=dict)
    segments: list[Segment] = field(default_factory=list)
    file: str | None = None
    source: str = ""  # 模板文件原文

    @property
    def digest(self) -> str:
        return hashlib.sha1(self.source.encode("utf-8")).hexdigest()[:12]

    def base_vars(self) -> list[Var]:
        return [v for v in self.vars.values() if v.block is None]

    def block_vars(self, block: str) -> list[Var]:
        return [v for v in self.vars.values() if v.block == block]

    def input_vars(self, block: str | None = None) -> list[Var]:
        """需要给出取值的变量（不含派生变量）。"""
        return [v for v in self.vars.values() if v.block == block and not v.derived]

    def info(self, kb: KnowledgeBase | None = None) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "version": self.version,
            "title": dict(self.title),
            "description": dict(self.description),
            "profile": self.profile,
            "profiles": list(self.profiles),
            "family": kb.profiles[self.profile].family if kb and self.profile in kb.profiles else None,
            "match": {"extra": self.extra, "extra_scope": self.extra_scope},
            "vars": [v.as_dict() for v in self.vars.values()],
            "blocks": [b.as_dict() for b in self.blocks.values()],
            "file": self.file,
            "digest": self.digest,
        }
        return d


# ---------------------------------------------------------------- 表达式


@dataclass(frozen=True)
class Expr:
    var: str  # 变量全名
    filters: tuple[tuple[str, int | None], ...] = ()

    @property
    def text(self) -> str:
        parts = [self.var]
        for name, arg in self.filters:
            parts.append(f"{name}({arg})" if arg is not None else name)
        return "|".join(parts)


def parse_expr(text: str) -> tuple[str, list[tuple[str, int | None]]]:
    parts = [p.strip() for p in text.split("|")]
    name, filters = parts[0], []
    for p in parts[1:]:
        m = _FILTER_RE.match(p)
        if not m or m.group(1) not in FILTERS:
            raise TemplateError("template.bad_filter", filter=p)
        arg = int(m.group(2)) if m.group(2) is not None else None
        if m.group(1) in ("host", "add") and arg is None:
            raise TemplateError("template.bad_filter", filter=p)
        filters.append((m.group(1), arg))
    return name, filters


def resolve_name(t: Template, name: str, block: str | None) -> str | None:
    """占位符中的名字 → 变量全名：块内先找本块变量（svc.vlan 或 vlan），再找基础变量。"""
    if block:
        if name.startswith(block + ".") and name in t.vars:
            return name
        if f"{block}.{name}" in t.vars:
            return f"{block}.{name}"
    return name if name in t.vars and t.vars[name].block is None else None


def resolve_expr(t: Template, text: str, block: str | None, _depth: int = 0) -> Expr:
    """展开派生变量：{{gw}}（gw = lan|host(1)）→ Expr(lan, host(1))。"""
    name, filters = parse_expr(text)
    full = resolve_name(t, name, block)
    if full is None:
        raise TemplateError("template.unknown_var", var=name)
    v = t.vars[full]
    if v.expr is not None:
        if _depth > 8:
            raise TemplateError("template.expr_cycle", var=full)
        inner = resolve_expr(t, v.expr, v.block, _depth + 1)
        return Expr(inner.var, inner.filters + tuple(filters))
    return Expr(full, tuple(filters))


def _iface(value: Any) -> ipaddress.IPv4Interface:
    s = re.sub(r"\s+", " ", str(value).strip())
    if " " in s and "/" not in s:
        s = s.replace(" ", "/")
    return ipaddress.IPv4Interface(s)


def apply_filter(value: Any, name: str, arg: int | None) -> str:
    """过滤器：输入输出都是字符串（整数写成十进制）。"""
    if name == "upper":
        return str(value).upper()
    if name == "lower":
        return str(value).lower()
    if name == "add":
        s = str(value).strip()
        if re.fullmatch(r"-?\d+", s):
            return str(int(s) + (arg or 0))
        return str(ipaddress.IPv4Address(s) + (arg or 0))
    ifc = _iface(value)
    net = ifc.network
    if name == "ip":
        return str(ifc.ip)
    if name == "network":
        return str(net.network_address)
    if name == "len":
        return str(net.prefixlen)
    if name == "mask":
        return str(net.netmask)
    if name == "wildcard":
        return str(net.hostmask)
    if name == "broadcast":
        return str(net.broadcast_address)
    if name == "host":
        n = arg or 0
        addr = net.network_address + n if n >= 0 else net.broadcast_address + n
        if addr not in net:
            raise TemplateError("template.host_out_of_range", value=str(value), n=n)
        return str(addr)
    raise TemplateError("template.bad_filter", filter=name)


def evaluate(e: Expr, values: dict[str, Any]) -> str | None:
    v = values.get(e.var)
    if v is None or v == "":
        return None
    out = format_value(v)
    for name, arg in e.filters:
        out = apply_filter(out, name, arg)
    return out


def format_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


# ---------------------------------------------------------------- 变量取值的检查


def check_value(var: Var, value: Any) -> tuple[Any, str | None]:
    """检查并规范化一个取值。返回 (规范化后的取值, 问题文案键或 None)。整数类型返回 int，其余返回字符串。"""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None, "template.value.required"
    s = str(value).strip()
    t = var.type
    try:
        if t in INT_TYPES:
            if t == "asn" and re.fullmatch(r"\d+\.\d+", s):
                hi, lo = s.split(".")
                n = int(hi) * 65536 + int(lo)
            elif re.fullmatch(r"-?\d+", s):
                n = int(s)
            else:
                return s, "template.value.not_integer"
            lo_, hi_ = {"vlan": (1, 4094), "asn": (1, 4294967295)}.get(t, (None, None))
            lo2 = var.min if var.min is not None else lo_
            hi2 = var.max if var.max is not None else hi_
            if (lo2 is not None and n < lo2) or (hi2 is not None and n > hi2):
                return n, "template.value.out_of_range"
            return n, None
        if t == "ipv4":
            a = ipaddress.IPv4Address(s)
            if var.within and not any(a in ipaddress.IPv4Network(w, strict=False) for w in var.within):
                return str(a), "template.value.not_within"
            return str(a), None
        if t == "prefix":
            ifc = _iface(s)
            out = f"{ifc.ip}/{ifc.network.prefixlen}"
            if var.network and ifc.ip != ifc.network.network_address:
                return out, "template.value.not_network"
            if var.length and not var.length[0] <= ifc.network.prefixlen <= var.length[1]:
                return out, "template.value.bad_length"
            if var.within and not any(
                ifc.network.subnet_of(ipaddress.IPv4Network(w, strict=False)) for w in var.within
            ):
                return out, "template.value.not_within"
            return out, None
        if t == "rd":
            left, sep, right = s.rpartition(":")
            if not sep or not right.isdigit() or not left:
                return s, "template.value.bad_rd"
            if "." in left and left.count(".") == 3:
                ipaddress.IPv4Address(left)
            elif not re.fullmatch(r"\d+(\.\d+)?", left):
                return s, "template.value.bad_rd"
        elif t == "enum":
            hit = next((c for c in var.choices if c.lower() == s.lower()), None)
            if hit is None:
                return s, "template.value.not_choice"
            s = hit
        elif t in ("interface", "word"):
            if re.search(r"\s", s):
                return s, "template.value.has_space"
        elif t == "text" and "\n" in s:
            return s, "template.value.multiline"
    except (ValueError, ipaddress.AddressValueError, ipaddress.NetmaskValueError):
        return s, f"template.value.bad_{t}"
    if var.pattern and not re.fullmatch(var.pattern, s):
        return s, "template.value.pattern"
    return s, None


def same_value(var: Var, a: Any, b: Any) -> bool:
    """两个取值按变量类型是否相同（接口名缩写、掩码写法、大小写等不算不同）。"""
    from lmesh.core.compare import norm_scalar

    if a is None or b is None:
        return a is None and b is None
    t = {"vlan": "integer", "word": "string", "enum": "enum"}.get(var.type, var.type)
    if var.type == "prefix":
        try:
            ia, ib = _iface(a), _iface(b)
            return ia.ip == ib.ip and ia.network.prefixlen == ib.network.prefixlen
        except ValueError:
            return str(a) == str(b)
    return bool(norm_scalar(t, a) == norm_scalar(t, b))


# ---------------------------------------------------------------- 加载与校验


def _texts(v: Any) -> dict[str, str]:
    if isinstance(v, dict):
        return {str(k): str(x) for k, x in v.items()}
    if v is None:
        return {}
    return {"zh-CN": str(v), "en": str(v), "pt-BR": str(v)}


def _var(name: str, spec: Any, block: str | None, issues: list[dict[str, Any]]) -> Var:
    where = f"vars.{name}" if block is None else f"blocks.{block}.vars.{name}"
    full = name if block is None else f"{block}.{name}"
    if not NAME_RE.match(name):
        issues.append({"where": where, "key": "template.issue.bad_name", "args": {"name": name}})
    if spec is None:
        spec = {}
    if isinstance(spec, str):  # 简写：vlan: integer
        spec = {"type": spec}
    if not isinstance(spec, dict):
        issues.append({"where": where, "key": "template.issue.bad_var", "args": {"name": name}})
        return Var(full, block=block)
    v = Var(full, block=block, title=_texts(spec.get("title")))
    if spec.get("expr") is not None:
        v.expr = str(spec["expr"])
        v.type = str(spec.get("type") or "word")
    else:
        v.type = str(spec.get("type") or "word")
    if v.type not in VAR_TYPES:
        issues.append({"where": where, "key": "template.issue.bad_type", "args": {"type": v.type}})
    for k in ("min", "max"):
        if spec.get(k) is not None:
            try:
                setattr(v, k, int(spec[k]))
            except (TypeError, ValueError):
                issues.append({"where": f"{where}.{k}", "key": "template.issue.bad_number", "args": {}})
    v.default = spec.get("default")
    v.example = spec.get("example")
    v.choices = [str(c) for c in spec.get("choices") or []]
    if v.type == "enum" and not v.choices:
        issues.append({"where": where, "key": "template.issue.enum_choices", "args": {}})
    v.pattern = str(spec["pattern"]) if spec.get("pattern") else None
    if v.pattern:
        try:
            re.compile(v.pattern)
        except re.error:
            issues.append({"where": f"{where}.pattern", "key": "template.issue.bad_pattern", "args": {}})
    if spec.get("length") is not None:
        ln = spec["length"]
        try:
            pair = (int(ln[0]), int(ln[1])) if isinstance(ln, list) else (int(ln), int(ln))
            if not 0 <= pair[0] <= pair[1] <= 32:
                raise ValueError
            v.length = pair
        except (TypeError, ValueError, IndexError):
            issues.append({"where": f"{where}.length", "key": "template.issue.bad_length", "args": {}})
    v.within = [str(w) for w in spec.get("within") or []]
    for w in v.within:
        try:
            ipaddress.IPv4Network(w, strict=False)
        except ValueError:
            issues.append({"where": f"{where}.within", "key": "template.issue.bad_network", "args": {"value": w}})
    v.network = bool(spec.get("network", False))
    v.unique = bool(spec.get("unique", False))
    if v.unique and block is None:
        issues.append({"where": where, "key": "template.issue.unique_base", "args": {}})
    if v.default is not None and v.expr is None:
        _, problem = check_value(v, v.default)
        if problem:
            issues.append({"where": f"{where}.default", "key": problem, "args": {"value": str(v.default)}})
    return v


def _segments(body: str, blocks: dict[str, Block], issues: list[dict[str, Any]]) -> list[Segment]:
    out: list[Segment] = []
    current: Segment | None = None
    seen: set[str] = set()
    for no, line in enumerate(body.split("\n"), start=1):
        m = CONTROL.match(line)
        if m:
            kind, name = m.group(1), m.group(2)
            if kind == "end":
                if current is None:
                    issues.append({"where": f"body:{no}", "key": "template.issue.stray_end", "args": {}})
                current = None
                continue
            if current is not None:
                issues.append({"where": f"body:{no}", "key": "template.issue.nested_block", "args": {}})
                continue
            b = blocks.get(name or "")
            if b is None or b.kind != kind:
                issues.append({"where": f"body:{no}", "key": "template.issue.unknown_block", "args": {"name": name}})
            seen.add(name or "")
            current = Segment(no, "", name)
            out.append(current)
            continue
        seg = Segment(no, line)
        (current.lines if current is not None else out).append(seg)
    if current is not None:
        issues.append({"where": f"body:{current.line_no}", "key": "template.issue.unclosed_block", "args": {}})
    for name in blocks:
        if name not in seen:
            issues.append({"where": f"blocks.{name}", "key": "template.issue.block_unused", "args": {"name": name}})
    return out


def parse(source: str, kb: KnowledgeBase | None = None, file: str | None = None) -> Template:
    """解析模板文件；有问题时抛出 TemplateError（kind=invalid，issues 是问题清单：where、key、args）。"""
    issues: list[dict[str, Any]] = []
    try:
        doc = YAML(typ="safe", pure=True).load(source)
    except Exception as e:  # YAML 语法错误
        raise TemplateError(
            "template.invalid", "invalid", [{"where": "yaml", "key": "template.issue.yaml", "args": {"error": str(e)}}]
        ) from e
    if not isinstance(doc, dict):
        raise TemplateError("template.invalid", "invalid", [{"where": "", "key": "template.issue.not_map", "args": {}}])
    tid = str(doc.get("id") or "")
    if not ID_RE.match(tid):
        issues.append({"where": "id", "key": "template.issue.bad_id", "args": {"id": tid}})
    profile = str(doc.get("profile") or "")
    if not profile:
        issues.append({"where": "profile", "key": "template.issue.no_profile", "args": {}})
    elif kb is not None and profile not in kb.profiles:
        issues.append({"where": "profile", "key": "template.issue.unknown_profile", "args": {"profile": profile}})
    body = str(doc.get("body") or "")
    if not body.strip():
        issues.append({"where": "body", "key": "template.issue.no_body", "args": {}})
    match = doc.get("match") or {}
    t = Template(
        id=tid,
        profile=profile,
        body=body.rstrip("\n"),
        title=_texts(doc.get("title")),
        description=_texts(doc.get("description")),
        version=int(doc.get("version") or 1),
        profiles=[str(p) for p in doc.get("profiles") or []],
        extra=str(match.get("extra", "allow")),
        extra_scope=str(match.get("extra_scope", "matched")),
        file=file,
        source=source,
    )
    if kb is not None:
        for p in t.profiles:
            if p not in kb.profiles:
                issues.append({"where": "profiles", "key": "template.issue.unknown_profile", "args": {"profile": p}})
    if t.extra not in EXTRA_POLICIES:
        issues.append({"where": "match.extra", "key": "template.issue.bad_extra", "args": {"value": t.extra}})
    if t.extra_scope not in EXTRA_SCOPES:
        issues.append(
            {"where": "match.extra_scope", "key": "template.issue.bad_scope", "args": {"value": t.extra_scope}}
        )
    for name, spec in (doc.get("vars") or {}).items():
        if str(name) in RESERVED:
            issues.append({"where": f"vars.{name}", "key": "template.issue.reserved", "args": {"name": name}})
        t.vars[str(name)] = _var(str(name), spec, None, issues)
    for name, spec in (doc.get("blocks") or {}).items():
        name = str(name)
        spec = spec or {}
        if not NAME_RE.match(name) or name in t.vars:
            issues.append({"where": f"blocks.{name}", "key": "template.issue.bad_name", "args": {"name": name}})
        if spec.get("repeat") is not None:
            rep = spec["repeat"] if isinstance(spec["repeat"], dict) else {}
            b = Block(name, "repeat", int(rep.get("min", 1)), rep.get("max"))
            if b.max is not None:
                b.max = int(b.max)
                if b.max < b.min:
                    issues.append({"where": f"blocks.{name}.repeat", "key": "template.issue.bad_count", "args": {}})
        elif spec.get("optional"):
            b = Block(name, "optional")
        else:
            issues.append({"where": f"blocks.{name}", "key": "template.issue.block_kind", "args": {"name": name}})
            continue
        b.anchor = str(spec["anchor"]) if spec.get("anchor") else None
        b.title = _texts(spec.get("title"))
        t.blocks[name] = b
        for vname, vspec in (spec.get("vars") or {}).items():
            v = _var(str(vname), vspec, name, issues)
            t.vars[v.name] = v
    t.segments = _segments(t.body, t.blocks, issues)
    # 占位符与派生变量的表达式都要能解析
    for v in t.vars.values():
        if v.expr is not None:
            try:
                resolve_expr(t, v.expr, v.block)
            except TemplateError as e:
                issues.append({"where": f"vars.{v.name}.expr", "key": e.key, "args": e.fmt})
    for seg in t.segments:
        for line in seg.lines if seg.block else [seg]:
            for m in PLACEHOLDER.finditer(line.text):
                try:
                    resolve_expr(t, m.group(1), seg.block)
                except TemplateError as e:
                    issues.append({"where": f"body:{line.line_no}", "key": e.key, "args": e.fmt})
    if issues:
        raise TemplateError("template.invalid", "invalid", issues, n=len(issues))
    return t


# ---------------------------------------------------------------- 渲染正文


@dataclass
class OutLine:
    text: str
    src: int  # 模板正文中的行号
    block: str | None
    instance: int | None
    exprs: dict[str, str]  # 这一行用到的表达式（文本）→ 渲染出的字符串


def _scope_values(t: Template, row: dict[str, Any], block: str | None, inst: dict[str, Any] | None) -> dict[str, Any]:
    vals = {v.name: row.get(v.name) for v in t.base_vars() if not v.derived}
    if block and inst is not None:
        for v in t.block_vars(block):
            if not v.derived:
                vals[v.name] = inst.get(v.short)
    return vals


def render_lines(t: Template, row: dict[str, Any]) -> list[OutLine]:
    """按一行参数渲染正文（参数已检查过，见 generate.prepare_row）。缺少取值的占位符抛出 TemplateError。"""
    out: list[OutLine] = []

    def emit(seg: Segment, block: str | None, idx: int | None, inst: dict[str, Any] | None) -> None:
        vals = _scope_values(t, row, block, inst)
        used: dict[str, str] = {}

        def sub(m: re.Match[str]) -> str:
            e = resolve_expr(t, m.group(1), block)
            v = evaluate(e, vals)
            if v is None:
                raise TemplateError("template.missing_value", var=e.var, line=seg.line_no)
            used[e.text] = v
            return v

        text = PLACEHOLDER.sub(sub, seg.text)
        out.append(OutLine(text, seg.line_no, block, idx, used))

    for seg in t.segments:
        if seg.block is None:
            emit(seg, None, None, None)
            continue
        b = t.blocks[seg.block]
        val = row.get(seg.block)
        if b.kind == "optional":
            if val:
                inst = val if isinstance(val, dict) else {}
                for ln in seg.lines:
                    emit(ln, seg.block, 0, inst)
            continue
        for i, inst in enumerate(val or []):
            for ln in seg.lines:
                emit(ln, seg.block, i, inst)
    return out


def render_text(t: Template, row: dict[str, Any]) -> str:
    return "\n".join(ln.text for ln in render_lines(t, row)) + "\n"


# ---------------------------------------------------------------- 存放


def templates_dir(kb_root: Path) -> Path:
    return kb_root / "templates"


def private_dir() -> Path:
    """用户私有模板（“我的模板”，M6）：data/user-templates/，归属记在数据库 user_assets。"""
    from lmesh import paths

    return paths.data_dir() / "user-templates"


def _shared_dirs(kb_root: Path) -> list[Path]:
    """共享模板：运行时知识库 templates/；没有时（早于 M3 复制出的）用程序自带的模板。"""
    own = templates_dir(kb_root)
    if own.is_dir():
        return [own]
    from lmesh import paths

    builtin = templates_dir(paths.builtin_knowledge_dir())
    return [builtin] if builtin.is_dir() else []


def _dirs(kb_root: Path) -> list[Path]:
    """共享模板在前，私有模板在后（编号全站唯一，不会互相遮盖）。"""
    priv = private_dir()
    return _shared_dirs(kb_root) + ([priv] if priv.is_dir() else [])


def is_private_file(f: Path) -> bool:
    return f.parent.resolve() == private_dir().resolve()


def list_templates(kb_root: Path, kb: KnowledgeBase | None = None) -> list[dict[str, Any]]:
    out = []
    for d in _dirs(kb_root):
        for f in sorted(d.glob("*.yaml")):
            text = f.read_text(encoding="utf-8")
            try:
                t = parse(text, kb, f.name)
                info = t.info(kb)
                out.append(
                    {
                        k: info[k]
                        for k in ("id", "version", "title", "description", "profile", "profiles", "family", "file")
                    }
                    | {
                        "vars": len([v for v in t.vars.values() if not v.derived]),
                        "blocks": len(t.blocks),
                        "valid": True,
                        "issues": [],
                        "private": is_private_file(f),
                    }
                )
            except TemplateError as e:
                out.append(
                    {"id": f.stem, "file": f.name, "valid": False, "issues": e.issues, "private": is_private_file(f)}
                )
    return out


def find_file(kb_root: Path, template_id: str) -> Path | None:
    for d in _dirs(kb_root):
        f = d / f"{template_id}.yaml"
        if f.is_file():
            return f
        for g in sorted(d.glob("*.yaml")):  # 文件名与编号不一致时按内容找
            try:
                doc = YAML(typ="safe", pure=True).load(g.read_text(encoding="utf-8"))
            except Exception:  # 坏文件跳过
                continue
            if isinstance(doc, dict) and str(doc.get("id")) == template_id:
                return g
    return None


def load(kb_root: Path, template_id: str, kb: KnowledgeBase | None = None) -> Template:
    f = find_file(kb_root, template_id)
    if f is None:
        raise TemplateError("template.not_found", "not_found", id=template_id)
    return parse(f.read_text(encoding="utf-8"), kb, f.name)


def load_any(kb_root: Path, ref: str, kb: KnowledgeBase | None = None) -> Template:
    """模板编号，或模板文件路径（CLI 用）。"""
    p = Path(ref)
    if p.suffix.lower() in (".yaml", ".yml") and p.is_file():
        return parse(p.read_text(encoding="utf-8"), kb, p.name)
    return load(kb_root, ref, kb)


def save(kb_root: Path, template_id: str, source: str, kb: KnowledgeBase) -> Template:
    """校验后写入运行时知识库的 templates/<编号>.yaml 并提交（编号必须与内容一致）。"""
    from lmesh.core.kb import repo

    t = parse(source, kb, f"{template_id}.yaml")
    if t.id != template_id:
        raise TemplateError("template.id_mismatch", id=template_id, got=t.id)
    from lmesh.core import template_match

    template_match.compile_template(t, kb)  # 正文要能解析、建图
    with repo.WRITE_LOCK:
        d = templates_dir(kb_root)
        if not d.exists():
            import shutil

            from lmesh import paths

            builtin = templates_dir(paths.builtin_knowledge_dir())
            if builtin.is_dir() and builtin.resolve() != d.resolve():
                shutil.copytree(builtin, d)
            else:
                d.mkdir(parents=True, exist_ok=True)
        existing = find_file(kb_root, template_id)
        path = existing if existing is not None and existing.parent == d else d / f"{template_id}.yaml"
        tmp = path.with_suffix(".yaml.tmp")
        tmp.write_text(source if source.endswith("\n") else source + "\n", encoding="utf-8", newline="\n")
        tmp.replace(path)
        if (kb_root / ".git").exists():
            repo.commit_all(kb_root, f"保存配置模板 {template_id}")
    t.file = path.name
    return t


def save_private(template_id: str, source: str, kb: KnowledgeBase) -> Template:
    """校验后写入 data/user-templates/<编号>.yaml（我的模板，不进知识库仓库）。"""
    t = parse(source, kb, f"{template_id}.yaml")
    if t.id != template_id:
        raise TemplateError("template.id_mismatch", id=template_id, got=t.id)
    from lmesh.core import template_match

    template_match.compile_template(t, kb)
    d = private_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{template_id}.yaml"
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(source if source.endswith("\n") else source + "\n", encoding="utf-8", newline="\n")
    tmp.replace(path)
    t.file = path.name
    return t


def delete_private(template_id: str) -> bool:
    f = private_dir() / f"{template_id}.yaml"
    if f.is_file():
        f.unlink()
        return True
    return False


def copy_private(kb_root: Path, template_id: str, new_id: str, kb: KnowledgeBase) -> Template:
    """把模板复制为私有模板 new_id（只改 id，其余原样保留，含注释）。"""
    import io

    from lmesh.core.kb.files import load_rt

    f = find_file(kb_root, template_id)
    if f is None:
        raise TemplateError("template.not_found", "not_found", id=template_id)
    if not ID_RE.match(new_id):
        raise TemplateError("template.bad_id", id=new_id)
    doc = load_rt(f)
    doc["id"] = new_id
    buf = io.StringIO()
    y = YAML()
    y.width = 4096
    y.dump(doc, buf)
    return save_private(new_id, buf.getvalue(), kb)
