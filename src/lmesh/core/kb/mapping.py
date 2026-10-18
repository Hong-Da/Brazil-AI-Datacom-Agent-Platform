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
           tail:关键字[:截止词]  关键字之后的全部词（到截止词为止）
           flag             开关：true；undo / no 形式时为 false
           auto             按出现顺序自动编号（没有序号的列表项）；$序号||auto 有序号用序号，否则自动编号
           其他             文字常量
    对象节点的表达式给出对象的键：单键直接写；复合键写成 {字段: 表达式}。

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
_PARAM = re.compile(r"\$([\w\-]+)|\{([\w\-|]+)\}")
_IPV4 = re.compile(r"^\d+\.\d+\.\d+\.\d+$")


@dataclass
class Target:
    node: str  # 去掉固定键后的节点路径
    fixed: dict[str, dict[str, str]] = field(default_factory=dict)  # 对象节点路径 → 固定键


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
            out.add(m.group(1))
        else:
            out.update(m.group(2).split("|"))
    return out


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


def evaluate(expr: Any, values: dict[str, Any], tokens: list[str], negated: bool, auto: int = 0) -> Any:
    """计算表达式；取不到值时返回 None。列表参数返回列表。"""
    if isinstance(expr, dict):
        return {k: evaluate(v, values, tokens, negated, auto) for k, v in expr.items()}
    e = str(expr)
    low = [t.lower() for t in tokens]
    if "||" in e and not e.startswith("$"):
        # 多个候选：依次计算，取第一个有值的（每个候选本身可以是 kw: / if: / fmt: / tail: / $参数 / 字面量）
        for alt in e.split("||"):
            v = evaluate(alt.strip(), values, tokens, negated, auto)
            if v not in (None, "", []):
                return v
        return None
    if e == "flag":
        return not negated
    if e == "auto":
        return str(auto)
    if e.startswith("if:"):
        _, kw, rest = e.split(":", 2)
        if kw.startswith("$"):  # if:$参数:表达式——该参数有值时才取（Cisco host X 记反掩码 0.0.0.0）
            return evaluate(rest, values, tokens, negated, auto) if values.get(kw[1:]) not in (None, "", []) else None
        return evaluate(rest, values, tokens, negated, auto) if kw.lower() in low else None
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
        elif alt.startswith(("fmt:", "kw:", "tail:", "if:")):
            v = evaluate(alt, values, tokens, negated, auto)
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
