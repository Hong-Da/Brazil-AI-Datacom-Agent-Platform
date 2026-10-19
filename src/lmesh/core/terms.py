"""显示风格（REQ-026）：同一张配置图按华为、Cisco 或 Nokia 的叫法与命令写法显示。

术语表在知识库的 terms.yaml（objects：对象的名称与命令写法模板；attrs：属性的命令关键字；
contexts：按视图层级显示时顶层对象所在的配置上下文，M7-5 的 Nokia）。
只影响显示（界面、报告），不影响解析、建图、对比、检查的结果。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lmesh.core.kb import KnowledgeBase, read_yaml

STYLES = ("huawei", "cisco", "nokia")
# 每个对象必须登记的风格（M7-5 起 nokia 也必须登记）；属性没有登记某种风格的关键字时，非华为 / Cisco 的风格按华为显示
REQUIRED_STYLES = ("huawei", "cisco", "nokia")
BASE_STYLES = ("huawei", "cisco")
_FIELD = re.compile(r"\{([\w\-]+)\}")


@dataclass
class Terms:
    default: str = "huawei"
    styles: dict[str, dict[str, str]] = field(default_factory=dict)
    objects: dict[str, dict[str, Any]] = field(default_factory=dict)
    attrs: dict[str, dict[str, str]] = field(default_factory=dict)
    contexts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "default": self.default,
            "styles": self.styles,
            "objects": self.objects,
            "attrs": self.attrs,
            "contexts": self.contexts,
        }

    def context(self, schema: str, key: Any, attrs: dict[str, Any], style: str) -> list[str]:
        """顶层对象在该风格下的配置上下文路径（按视图层级显示时的分组）；没有登记或都不命中时为空。
        attrs：对象的直接子属性 {短名: 取值}（例如 interface 的 vrf）。"""
        keys = _key_dict(key, schema)
        ktext = str(keys.get("_", "")) if "_" in keys else ",".join(f"{k}={v}" for k, v in keys.items())
        for c in self.contexts.get(_style(style)) or []:
            if not re.search(str(c.get("schema") or "$^"), schema):
                continue
            if c.get("key") and not re.search(str(c["key"]), ktext):
                continue
            attr = c.get("attr")
            if attr and attrs.get(str(attr)) in (None, "", False):
                continue
            fields = {str(k): str(v) for k, v in attrs.items()}
            return [_fill(str(p), fields) for p in c.get("path") or []]
        return []

    # ---------- 渲染 ----------

    def name(self, schema: str, style: str, lang: str = "zh-CN", kb: KnowledgeBase | None = None) -> str:
        """对象类型的叫法；没有登记时用 Schema 的 semantic。"""
        spec = _spec(self.objects.get(schema), style)
        names = spec.get("name") or {}
        if names:
            return str(names.get(lang) or names.get("en") or next(iter(names.values())))
        node = kb.nodes.get(schema) if kb else None
        if node and node.semantic:
            return str(node.semantic.get(lang) or node.semantic.get("en") or next(iter(node.semantic.values())))
        return schema

    def label(self, schema: str, key: Any, style: str) -> str:
        """对象节点在该风格下的命令写法，例如 vrf.instance + {"name": "RAN"} → ip vpn-instance RAN / vrf definition RAN。"""
        spec = _spec(self.objects.get(schema), style)
        keys = _key_dict(key, schema)
        values = spec.get("values") or {}
        shown = {k: str((values.get(k) or {}).get(str(v), v)) for k, v in keys.items()}
        for cand in spec.get("label") or []:
            tpl, _, req = str(cand).partition(" ? ")
            need = [r.strip() for r in req.split(",") if r.strip()]
            if not all(_has(keys, r) for r in need):
                continue
            return re.sub(r"\s+", " ", _FIELD.sub(lambda m: shown.get(m.group(1), ""), tpl)).strip()
        text = " ".join(str(v) for v in keys.values() if str(v).strip())
        return f"{schema.rsplit('.', 1)[-1]} {text}".strip()

    def attr(self, schema: str, style: str) -> str | None:
        """属性在该风格下的命令关键字；没有登记时返回 None（界面用 Schema 的名称）。"""
        spec = self.attrs.get(schema) or {}
        v = spec.get(_style(style)) or (spec.get("huawei") if _style(style) not in BASE_STYLES else None)
        return str(v) if v else None


def _fill(tpl: str, fields: dict[str, str]) -> str:
    return _FIELD.sub(lambda m: fields.get(m.group(1), ""), tpl).strip()


def _has(keys: dict[str, Any], req: str) -> bool:
    """label 候选的条件：字段有值；写成 “字段~正则” 时取值还要能被正则搜索到（M7-5：Nokia 的端口与路由器接口）。"""
    name, _, pattern = req.partition("~")
    v = str(keys.get(name.strip()) or "").strip()
    return bool(v) and (not pattern or re.search(pattern, v) is not None)


def _style(style: str) -> str:
    return style if style in STYLES else "huawei"


def _spec(obj: dict[str, Any] | None, style: str) -> dict[str, Any]:
    """对象在该风格下的写法；华为 / Cisco 之外的风格没有登记时用华为风格（check() 要求都登记，这里只是兜底）。"""
    obj = obj or {}
    return obj.get(_style(style)) or (obj.get("huawei") if _style(style) not in BASE_STYLES else None) or {}


def _key_dict(key: Any, schema: str) -> dict[str, Any]:
    """图节点的 key 可能是字符串（单键）或字典（复合键）。单键时字段名用 Schema 的第一个键名（由调用方给出时更准）。"""
    if isinstance(key, dict):
        return {str(k): v for k, v in key.items()}
    if key is None:
        return {}
    return {
        "_": key,
        **{
            name: key
            for name in _KEY_NAMES.get(
                schema, ["name", "id", "address", "asn", "seq", "value", "prefix", "interface", "protocol", "peer"]
            )
        },
    }


# 单键对象的键名：由 load() 按 Schema 填充，未加载时用常见键名兜底
_KEY_NAMES: dict[str, list[str]] = {}


def load(kb_root: Path, kb: KnowledgeBase | None = None) -> Terms:
    f = kb_root / "terms.yaml"
    raw = (read_yaml(f) or {}) if f.exists() else {}
    t = Terms(
        default=_style(str(raw.get("default") or "huawei")),
        styles=dict(raw.get("styles") or {}),
        objects=dict(raw.get("objects") or {}),
        attrs={str(k): {s: str(x) for s, x in (v or {}).items()} for k, v in (raw.get("attrs") or {}).items()},
        contexts={str(s): [dict(c) for c in (v or [])] for s, v in (raw.get("contexts") or {}).items()},
    )
    if kb is not None:
        for nid, node in kb.nodes.items():
            if node.type == "object" and len(node.key) == 1:
                _KEY_NAMES[nid] = list(node.key)
    return t


def check(kb: KnowledgeBase, terms: Terms) -> list[str]:
    """术语表里引用了 Schema 中不存在的节点、或对象缺少某种风格时返回问题清单（测试与校验用）。"""
    problems = []
    for nid, spec in terms.objects.items():
        if nid not in kb.nodes:
            problems.append(f"objects.{nid}: Schema 中没有这个节点")
        for s in STYLES:
            if s not in REQUIRED_STYLES and s not in (spec or {}):
                continue  # 可选风格没有登记：按华为风格显示
            if not (spec or {}).get(s, {}).get("label"):
                problems.append(f"objects.{nid}.{s}: 缺少 label")
    for nid in terms.attrs:
        if nid not in kb.nodes:
            problems.append(f"attrs.{nid}: Schema 中没有这个节点")
    for s, rows in terms.contexts.items():
        if s not in STYLES:
            problems.append(f"contexts.{s}: 不是已知的显示风格")
        for i, c in enumerate(rows):
            if not c.get("schema") or not isinstance(c.get("path"), list) or not c["path"]:
                problems.append(f"contexts.{s}[{i}]: 缺少 schema 或 path")
                continue
            for k in ("schema", "key"):
                try:
                    re.compile(str(c.get(k) or ""))
                except re.error as e:
                    problems.append(f"contexts.{s}[{i}].{k}: 正则错误 {e}")
    for nid, node in kb.nodes.items():
        if node.type == "object" and nid not in terms.objects:
            problems.append(f"objects.{nid}: 对象没有登记显示风格")
    return problems


# ---------- 规范编号 → 命令路径 ----------


def split_node_id(node_id: str) -> list[tuple[str, str | None]]:
    """把图的节点编号按层拆开（方括号里的 / 不拆）：
    interface[GigabitEthernet0/2/1]/ospf[_]/cost → [("interface", "GigabitEthernet0/2/1"), ("ospf", "_"), ("cost", None)]"""
    parts: list[tuple[str, str | None]] = []
    depth, buf = 0, ""
    for ch in node_id:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "/" and depth == 0:
            parts.append(_seg(buf))
            buf = ""
        else:
            buf += ch
    if buf:
        parts.append(_seg(buf))
    return parts


def _seg(text: str) -> tuple[str, str | None]:
    if text.endswith("]") and "[" in text:
        i = text.index("[")
        return text[:i], text[i + 1 : -1]
    return text, None


def _parse_key(raw: str | None) -> Any:
    if raw is None:
        return None
    if "=" in raw and all("=" in p for p in raw.split(",")):
        return dict(p.split("=", 1) for p in raw.split(","))
    return raw


def describe(node_id: str, kb: KnowledgeBase, terms: Terms, style: str, sep: str = " › ") -> str:
    """规范编号按显示风格写成命令路径；认不出的层原样保留。"""
    out: list[str] = []
    parent: str | None = None
    for short, raw_key in split_node_id(node_id):
        if short in ("raw", "ext", "unknown"):
            out.append(f"{short} {raw_key or ''}".strip())
            continue
        schema = (
            short
            if short in kb.nodes
            else (f"{parent}.{short}" if parent and f"{parent}.{short}" in kb.nodes else short)
        )
        if raw_key is not None:
            out.append(terms.label(schema, _parse_key(raw_key), style))
        else:
            out.append(terms.attr(schema, style) or short)
        parent = schema
    return sep.join(x for x in out if x)


def namer(kb_root: Path, kb: KnowledgeBase, style: str) -> Callable[[str], str]:
    """报告用：规范编号 → 该风格的命令路径。"""
    t = load(kb_root, kb)
    return lambda node_id: describe(node_id, kb, t, style)
