"""命令卡 → Schema 节点的映射（语义归并的结果）。

命令卡的 maps 是 {目标: 表达式}：
    目标   节点路径，例如 interface.mtu；路径中的对象可以带固定键 vrf.instance.af{afi=ipv4}.rd；
           a | b 表示二选一（例如 bgp.peer | bgp.peer_group），按第一个对象键的取值判断：是 IP 地址取前者，否则取后者；
           同一张卡里其他带 | 的目标按同一个选择取对应的那一支。
    表达式
           $参数            参数的取值（重复组里的参数是列表，展开成多个对象）
           $a||$b||文字     取第一个有值的；最后可以是文字
           fmt:{a}/{b|c}    拼接，{b|c} 取第一个有值的参数
           kw:a|b|c[:默认]  行里出现了哪个关键字；kw:single=pop 1|double=pop 2 把关键字翻译成值
           if:关键字:表达式  行里有这个关键字时才设置；if:$参数:表达式 该参数有值时才设置
           unless:关键字:表达式  行里没有这个关键字时才设置（M4-2：timers advertise [ msec ] <间隔> 的秒 / 毫秒分开记）
           tail:关键字[:截止词]  关键字之后的全部词（到截止词为止）
           flag             开关：true；undo / no 形式时为 false
           !flag            反向开关：no 形式时为 true（M7-3，Nokia 的 no shutdown → enabled、server-shutdown → 未启用）
           auto             按出现顺序自动编号（没有序号的列表项）；$序号||auto 有序号用序号，否则自动编号
           ctx:subif        上下文中接口的子接口编号（GE0/2/1.101 → 101；主接口为 _）：接入点在接口视图里的编号，
                            华为二层子接口与 Cisco 子接口上的接入点按它编号，与 Cisco service instance 的编号对应
           ctx:参数         父上下文行（由近到远第一个有该参数的祖先行）的参数取值（M7-3，Nokia：static-route-entry
                            <前缀> 下的 next-hop 取前缀、OSPF area <区域> 下的 interface 取区域、lag <编号> 下的 port 取编号）
           sap:部分:表达式  按 SAP 写法（端口[:外层[.内层]]）拆分表达式的取值（M7-3，Nokia）：port 端口、vlan 外层 VLAN、
                            inner 内层 VLAN、tag 端口后的整段封装（没有时为 _）、encap 封装方式（untagged / dot1q / qinq / default）
           pfx:部分:表达式  按前缀写法（地址/长度）拆分（M7-3，Nokia address 10.0.0.1/30）：addr 地址、len 长度、
                            wild 长度换成反掩码（过滤器 src-ip 192.0.2.0/24 → 0.0.0.255）
           pre:词:表达式    取值写成 词:值 时去掉前缀（M7-3，Nokia vrf-target target:64500:1 → 64500:1）
           via:对象类型:属性:表达式  以表达式的取值为键找到该类型的对象，取它的属性（M7-3，Nokia spoke-sdp 12:1001
                            的伪线对端 = SDP 12 的 far-end）；对象要先出现
           其他             文字常量
    对象节点的表达式给出对象的键：单键直接写；复合键写成 {字段: 表达式}。
    目标路径里的固定键也可以是表达式（M7-3）：interface{name=$port-id}.lag 表示“属于键为参数 port-id 的那个接口”，
    不用上下文中的同类对象（Nokia 在 lag 下列成员口、在 OSPF 区域下列接口）。表达式里不能有逗号与 ||。
    以 @ 开头的目标是指令而不是节点：@container 表示这张卡只是进入一个容器视图（Nokia 的 system、router Base、
    static-route-entry <前缀>），本身不产生节点，也不作为未映射命令（ext）；@share 表示这一行建立的对象对它后面的
    兄弟行也可见（Nokia router 下的 autonomous-system 建立 BGP 实例，之后的 bgp 块在它下面）；@frame 表示编辑会话的
    框架命令（Nokia policy-options 下的 begin / commit），不产生节点，规范渲染与变更脚本按 render 的 wrap 写出。

映射规则文件 knowledge/mappings/<平台族>.yaml：{view（正则，可省）, syntax（正则）, maps}，
lmesh kb map 把规则套到所有匹配的命令卡上（同一命令在多个视图中的变体一次覆盖），结果写进命令卡的 maps。
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SEG = re.compile(r"([^.{}]+)(\{[^}]*\})?")
_PARAM = re.compile(r"\$([\w\-/]+(?::[\w\-]+)*)|\{([\w\-|/]+)\}")
_IPV4 = re.compile(r"^\d+\.\d+\.\d+\.\d+$")


CONTAINER = "@container"  # 目标指令：容器卡（见模块说明）
SHARE = "@share"  # 目标指令：这一行建立的对象对后面的兄弟行可见（见模块说明）
FRAME = "@frame"  # 目标指令：编辑会话的框架命令（Nokia policy-options 的 begin / commit），不产生节点，渲染时按 render 的 wrap 写
DIRECTIVES = (CONTAINER, SHARE, FRAME)
_DYNAMIC = ("$", "ctx:", "sap:", "pfx:", "pre:", "via:", "fmt:", "kw:", "tail:")


@dataclass
class Target:
    node: str  # 去掉固定键后的节点路径
    fixed: dict[str, dict[str, str]] = field(default_factory=dict)  # 对象节点路径 → 固定键

    def dynamic(self) -> dict[str, dict[str, str]]:
        """固定键里取值是表达式的对象路径（键取自参数或上下文，M7-3）。"""
        return {p: kv for p, kv in self.fixed.items() if any(is_dynamic(v) for v in kv.values())}


def is_dynamic(v: str) -> bool:
    return str(v).startswith(_DYNAMIC)


def is_directive(target: str) -> bool:
    """以 @ 开头的映射目标是指令（@container），不是 Schema 节点。"""
    return str(target).startswith("@")


def is_container(maps: dict[str, Any] | None) -> bool:
    return bool(maps) and CONTAINER in (maps or {})


def is_frame(maps: dict[str, Any] | None) -> bool:
    return bool(maps) and FRAME in (maps or {})


def tokens(text: str, quotes: bool = False) -> list[str]:
    """命令行按词拆开（kw: / tail: 用）；quotes 时引号字符串算一个词并去掉引号（Nokia 的名称可含空格）。"""
    if not quotes:
        return text.split()
    from lmesh.core.kb import syntax as syn

    return [syn.unquote(w)[0] for w, _ in syn.tokenize_line(text, True)]


def split_sap(value: Any) -> dict[str, str] | None:
    """SAP 写法拆分：1/1/4:100.10 → {port: 1/1/4, tag: 100.10, vlan: 100, inner: 10, encap: qinq}。"""
    if value in (None, "", []):
        return None
    s = str(value[0] if isinstance(value, list) else value)
    port, colon, tag = s.partition(":")
    outer, dot, inner = tag.partition(".")
    # 封装方式按统一 Schema 的写法：没有 VLAN 为 untagged，:* 为 default，端口:外层.内层 为 qinq
    encap = "untagged" if not colon else ("default" if outer == "*" else ("qinq" if dot else "dot1q"))
    out = {"port": port, "tag": tag if colon else "_", "encap": encap}
    if colon and outer:
        out["vlan"] = outer
    if dot and inner:
        out["inner"] = inner
    return out


def join_sap(parts: dict[str, Any]) -> str | None:
    """split_sap 的逆：给出端口与（外层、内层 VLAN 或整段封装）拼回 SAP 写法；没有端口时返回 None。"""
    port = parts.get("port")
    if port in (None, ""):
        return None
    tag = parts.get("tag")
    if tag in (None, "", "_"):
        vlan, inner = parts.get("vlan"), parts.get("inner")
        tag = "" if vlan in (None, "") else (f"{vlan}.{inner}" if inner not in (None, "") else str(vlan))
    return f"{port}:{tag}" if tag else str(port)


def parse_target(text: str) -> list[Target]:
    """'a.b{k=v}.c | x.y' → 每个备选一个 Target。"""
    out = []
    for alt in text.split("|"):
        alt = alt.strip()
        parts, fixed, prefix = [], {}, []
        for m in _SEG.finditer(alt):
            name, keys = m.group(1).strip("."), m.group(2)
            if not name:
                continue
            prefix.append(name)
            parts.append(name)
            if keys:
                fixed[".".join(prefix)] = dict(kv.split("=", 1) for kv in keys.strip("{}").split(",") if "=" in kv)
        out.append(Target(".".join(parts), fixed))
    return out


def params_in_expr(expr: Any) -> set[str]:
    if isinstance(expr, dict):
        return set().union(*(params_in_expr(v) for v in expr.values())) if expr else set()
    out: set[str] = set()
    for m in _PARAM.finditer(str(expr)):
        if m.group(1):
            # 参数名可以含 / 与 :（Nokia 的 ip-prefix/prefix-length、sdp-id:vc-id）；if:$a:表达式 的 : 之后不是参数名，两种都记
            out.add(m.group(1))
            out.add(m.group(1).split(":")[0])
        else:
            out.update(m.group(2).split("|"))
    return out


def wildcard(length: Any) -> str | None:
    """掩码长度 → 反掩码（24 → 0.0.0.255）。"""
    if not str(length).isdigit() or not 0 <= int(length) <= 32:
        return None
    n = int(length)
    return str(ipaddress.IPv4Address(~((0xFFFFFFFF << (32 - n)) & 0xFFFFFFFF) & 0xFFFFFFFF))


def wildcard_len(v: Any) -> str | None:
    """反掩码 → 掩码长度（0.0.0.255 → 24）；不是连续的反掩码时返回 None。"""
    try:
        n = int(ipaddress.IPv4Address(str(v)))
    except ValueError:
        return None
    inv = (~n) & 0xFFFFFFFF
    return str(bin(inv).count("1")) if (n & (n + 1)) == 0 else None


def _mask_to_len(v: str) -> str:
    if _IPV4.match(v):
        try:
            n = int(ipaddress.IPv4Address(v))
            inv = (~n) & 0xFFFFFFFF
            if (inv & (inv + 1)) == 0:
                return str(bin(n).count("1"))
        except ValueError:
            pass
    return v


def context_value(expr: str, ctx: dict[str, Any] | None) -> Any:
    """ctx: 表达式：取决于所在上下文的取值（ctx 是 {对象类型: 上下文中该对象的键}，
    以及 params：{参数名: 父上下文行的取值}，由近到远第一个有该参数的祖先行）。"""
    if expr == "ctx:subif":
        name = str((ctx or {}).get("interface") or "")
        _, dot, sub = name.rpartition(".")
        return sub if dot and sub else "_"
    v = ((ctx or {}).get("params") or {}).get(expr[4:])
    return None if v in (None, "", []) else v


def evaluate(
    expr: Any,
    values: dict[str, Any],
    tokens: list[str],
    negated: bool,
    auto: int = 0,
    ctx: dict[str, Any] | None = None,
) -> Any:
    """计算表达式；取不到值时返回 None。列表参数返回列表。ctx 是上下文中的对象键（ctx: 表达式用）。"""
    if isinstance(expr, dict):
        return {k: evaluate(v, values, tokens, negated, auto, ctx) for k, v in expr.items()}
    e = str(expr)
    low = [t.lower() for t in tokens]
    if "||" in e and not e.startswith("$"):
        # 多个候选：依次计算，取第一个有值的（每个候选本身可以是 kw: / if: / fmt: / tail: / $参数 / 字面量）
        for alt in e.split("||"):
            v = evaluate(alt.strip(), values, tokens, negated, auto, ctx)
            if v not in (None, "", []):
                return v
        return None
    if e == "flag":
        return not negated
    if e == "!flag":
        return negated
    if e == "auto":
        return str(auto)
    if e.startswith("ctx:"):
        return context_value(e, ctx)
    if e.startswith("sap:"):
        _, part, rest = e.split(":", 2)
        parts = split_sap(evaluate(rest, values, tokens, negated, auto, ctx))
        return None if parts is None else parts.get(part)
    if e.startswith("pfx:"):
        _, part, rest = e.split(":", 2)
        v = evaluate(rest, values, tokens, negated, auto, ctx)
        v = v[0] if isinstance(v, list) and v else v
        if v in (None, "", []):
            return None
        addr, slash, length = str(v).partition("/")
        if part == "addr":
            return addr
        if not (slash and length):
            return None
        if part == "wild":
            return wildcard(length)
        return length
    if e.startswith("pre:"):
        _, word, rest = e.split(":", 2)
        v = evaluate(rest, values, tokens, negated, auto, ctx)
        if isinstance(v, str) and v.lower().startswith(word.lower() + ":"):
            return v[len(word) + 1 :]
        return v
    if e.startswith("via:"):
        _, schema, attr, rest = e.split(":", 3)
        key = evaluate(rest, values, tokens, negated, auto, ctx)
        look = (ctx or {}).get("lookup")
        if key in (None, "", []) or look is None:
            return None
        return look(schema, str(key[0] if isinstance(key, list) else key), attr)
    if e.startswith("if:"):
        _, kw, rest = e.split(":", 2)
        if kw.startswith("$"):  # if:$参数:表达式——该参数有值时才取（Cisco host X 记反掩码 0.0.0.0）
            return (
                evaluate(rest, values, tokens, negated, auto, ctx) if values.get(kw[1:]) not in (None, "", []) else None
            )
        return evaluate(rest, values, tokens, negated, auto, ctx) if kw.lower() in low else None
    if e.startswith("unless:"):
        _, kw, rest = e.split(":", 2)
        return None if kw.lower() in low else evaluate(rest, values, tokens, negated, auto, ctx)
    if e.startswith("tail:"):
        # 关键字之后的全部词（多个关键字选项重复出现时，例如 service-type ftp terminal telnet）
        # tail:关键字:截止词——只取到截止词之前（tunnel select-seq lsp cr-lsp load-balance-number 1 → "lsp cr-lsp"）
        kw, _, stop = e[5:].lower().partition(":")
        if kw in low:
            after = tokens[low.index(kw) + 1 :]
            if stop and stop in [t.lower() for t in after]:
                after = after[: [t.lower() for t in after].index(stop)]
            return " ".join(after) if after else None
        return None
    if e.startswith("kw:"):
        spec, _, default = e[3:].partition(":")
        for item in spec.split("|"):
            kw, _, out = item.partition("=")
            if kw.lower() in low:
                return out or kw
        return default or None
    if e.startswith("fmt:"):
        missing = False

        def sub(m: re.Match[str]) -> str:
            nonlocal missing
            for name in m.group(1).split("|"):
                v = values.get(name)
                if v not in (None, ""):
                    return str(v[0] if isinstance(v, list) else v)
            missing = True
            return ""

        text = re.sub(r"\{([\w\-|]+)\}", sub, e[4:])
        if missing:
            # 只缺最后的掩码部分（例如有类网段不带掩码）时，去掉末尾的分隔符
            text = re.sub(r"\s+", " ", text).strip().rstrip("/")
            if not text:
                return None
        return text
    for alt in e.split("||"):
        alt = alt.strip()
        if alt.startswith("$"):
            v = values.get(alt[1:])
            if v not in (None, "", []):
                return v
        elif alt.startswith(("fmt:", "kw:", "tail:", "if:", "unless:", "ctx:", "sap:", "pfx:", "pre:", "via:")):
            v = evaluate(alt, values, tokens, negated, auto, ctx)
            if v not in (None, "", []):
                return v
        elif alt != "":
            return alt
    return None


def normalize(node_type: str, node_id: str, value: Any) -> Any:
    """按节点类型归一化，用于比较有效值：掩码换算成长度、整数去前导零、前缀里的掩码换成长度。"""
    if isinstance(value, list):
        # 重复组（&<1-N>）里的参数取出来是列表：只有一个值时就是这个值；多个值的文本拼成一行
        if len(value) == 1 and node_type != "object":
            return normalize(node_type, node_id, value[0])
        if node_type in ("string", "text") and value:
            return " ".join(str(v) for v in value)
        return [normalize(node_type, node_id, v) for v in value]
    if value is None:
        return None
    if node_type == "boolean":
        return (
            bool(value) if isinstance(value, bool) else str(value).lower() in ("true", "1", "yes", "enable", "enabled")
        )
    v = str(value)
    if node_type == "integer":
        v = _mask_to_len(v)
        return int(v) if v.isdigit() else v
    if node_type == "prefix" and "/" in v:
        addr, _, length = v.partition("/")
        return f"{addr}/{_mask_to_len(length)}"
    return v


def choose_branch(values: list[Any]) -> int:
    """二选一目标（bgp.peer | bgp.peer_group）：取值是 IP 地址取第一支，否则第二支。"""
    v = values[0] if values else None
    v = v[0] if isinstance(v, list) and v else v
    return 0 if isinstance(v, str) and _IPV4.match(v) else 1


# ---------- 规则 → 命令卡 ----------


def load_rules(kb_root: Path, family: str) -> list[dict[str, Any]]:
    from lmesh.core.kb import read_yaml

    f = kb_root / "mappings" / f"{family}.yaml"
    if not f.exists():
        return []
    return list((read_yaml(f) or {}).get("rules") or [])


def apply_rules(kb_root: Path, family: str) -> dict[str, Any]:
    """把映射规则写进命令卡：命中规则的卡更新 maps（人工写的 maps 标了 maps_manual 的不动）。"""
    from lmesh.core.kb import files as kbfiles

    rules = load_rules(kb_root, family)
    used = [0] * len(rules)
    stats: dict[str, Any] = {"cards": 0, "mapped": 0, "unchanged": 0, "rules": len(rules)}
    for f in sorted((kb_root / "commands" / family).glob("*.yaml")):
        if f.name == "views.yaml":
            continue
        doc = kbfiles.load_rt(f)
        changed = False
        for card in (doc or {}).get("cards") or []:
            stats["cards"] += 1
            if card.get("maps_manual"):
                continue
            for i, r in enumerate(rules):
                if r.get("view") and not re.search(str(r["view"]), str(card.get("view", ""))):
                    continue
                if not re.search(str(r["syntax"]), str(card.get("syntax", ""))):
                    continue
                used[i] += 1
                # 一条规则覆盖同一命令的多个变体：某个变体没有的可选属性（参数都不在语法里）不写入
                from lmesh.core.kb import syntax as syn

                try:
                    have = set(syn.parse(str(card.get("syntax", ""))).params())
                except syn.SyntaxErrorKB:
                    have = set()
                maps = {}
                for k, v in (r.get("maps") or {}).items():
                    need = params_in_expr(v)
                    if not need or need & have:
                        maps[str(k)] = v
                if dict(card.get("maps") or {}) != maps:
                    card["maps"] = maps
                    stats["mapped"] += 1
                    changed = True
                else:
                    stats["unchanged"] += 1
                break
        if changed:
            kbfiles.dump_rt(f, doc)
    stats["unused_rules"] = [str(r.get("syntax")) for r, n in zip(rules, used, strict=True) if n == 0]
    return stats
