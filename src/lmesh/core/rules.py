"""配置检查规则：knowledge/rules/*.yaml 的加载、校验与求值（不用 eval，条件写成结构化的 YAML）。

规则文件格式：
    rules:
      - id: vrf.rd_without_rt              # 唯一编号（小写字母、数字、. _ -）
        target: vrf.instance.af            # 适用的 Schema 对象节点：对图中该类型的每个实例求值
        when: {exists: rd}                 # 前提（可省）：不满足时跳过
        assert: {count: {path: rt, min: 1}}  # 断言：前提满足而断言不成立时产生一条发现
        severity: warning                  # error / warning / info
        title:      {zh-CN: …, en: …, pt-BR: …}
        message:    {zh-CN: …, en: …, pt-BR: …}   # 可用占位符 {node}（节点编号）、{key}（实例的键）
        suggestion: {zh-CN: …, en: …, pt-BR: …}
        enabled: true                      # 可省，默认 true

条件（每个条件是只有一个键的字典）：
    exists: 路径                     路径上至少有一个“生效”的节点（对象；或取值不为空、不为 false、不是 undo 形式的属性）
    count: {path: 路径, min: N, max: N}  生效节点的个数在范围内（min / max 至少写一个）
    equals: {path: 路径, value: V}    路径上有节点的有效值等于 V（按文本比较）
    in: {path: 路径, values: [V…]}    路径上有节点的有效值在列表中
    all: [条件…] / any: [条件…] / not: 条件

路径从实例出发，按 Schema 逐段走：
    remote_as          子节点（编号中的一段，例如 interface 下的 vrf、ipv4，vrf.instance.af 下的 rt）
    af/rt              逐层往下
    group->remote_as   沿引用边到被引用的对象，再取它的子节点；group-> 表示被引用的对象本身
    ^                  所属的上一级对象
路径在加载时按 Schema 校验，写错时给出文件、规则编号与出错的位置。
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from lmesh.core.i18n import LANGS
from lmesh.core.kb import KnowledgeBase, read_yaml

SEVERITIES = ("error", "warning", "info")
SEVERITY_RANK = {"error": 3, "warning": 2, "info": 1}
_ID = re.compile(r"^[a-z0-9][a-z0-9_.\-]*$")
_PATH_TOKEN = re.compile(r"->|/|\^|[A-Za-z0-9_.]+")
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
PLACEHOLDERS = ("node", "key")
TEXT_FIELDS = ("title", "message", "suggestion")
OPS = ("exists", "count", "equals", "in", "all", "any", "not")


class RuleError(ValueError):
    """规则文件有错：issues 是 [{file, rule, field, code, params}]，code 是文案键（rules.err.*）。"""

    def __init__(self, issues: list[dict[str, Any]]):
        super().__init__(f"{len(issues)} rule issue(s)")
        self.issues = issues


@dataclass
class Step:
    op: str  # child / deref / parent
    schema: str  # 走到的节点类型


@dataclass
class Rule:
    id: str
    target: str
    severity: str
    assert_: Any
    when: Any = None
    title: dict[str, str] = field(default_factory=dict)
    message: dict[str, str] = field(default_factory=dict)
    suggestion: dict[str, str] = field(default_factory=dict)
    file: str = ""
    domain: str = ""
    enabled: bool = True
    paths: dict[str, list[Step]] = field(default_factory=dict)  # 条件里出现的路径 → 编译结果

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "builtin": False,
            "target": self.target,
            "domain": self.domain,
            "severity": self.severity,
            "enabled": self.enabled,
            "when": self.when,
            "assert": self.assert_,
            "title": self.title,
            "message": self.message,
            "suggestion": self.suggestion,
            "file": self.file,
        }


# ---------- Schema 上的路径 ----------


def owner_object(kb: KnowledgeBase, schema_id: str) -> str | None:
    """Schema 节点所属的最近的对象类型（属性挂在它下面）。"""
    node = kb.nodes.get(schema_id)
    cur = kb.nodes.get(node.parent) if node and node.parent else None
    while cur is not None and cur.type != "object":
        cur = kb.nodes.get(cur.parent) if cur.parent else None
    return cur.id if cur else None


def short_name(schema_id: str, owner: str | None) -> str:
    """图中节点编号的一段：去掉所属对象的前缀（与 graph._short 一致）。"""
    if owner and schema_id.startswith(owner + "."):
        return schema_id[len(owner) + 1 :]
    return schema_id


def ref_target(kb: KnowledgeBase, schema_id: str) -> str | None:
    """引用属性指向的对象类型：Schema 的 ref，或 reference 依赖规则的终点。"""
    node = kb.nodes.get(schema_id)
    if node is not None and node.type == "ref" and node.ref:
        return node.ref
    return next((d.dst for d in kb.deps if d.kind == "reference" and d.src == schema_id), None)


def compile_path(kb: KnowledgeBase, start: str, text: str) -> list[Step]:
    """把路径编译成步骤并按 Schema 校验；出错时抛出 ValueError(文案键, 参数)。"""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("rules.err.path_empty", {})
    compact = text.replace(" ", "")
    tokens = _PATH_TOKEN.findall(compact)
    if "".join(tokens) != compact:
        raise ValueError("rules.err.path_syntax", {"path": text})
    steps: list[Step] = []
    cur = start
    expect_name = True  # 下一个记号应该是名称（开头、/ 之后）
    for tok in tokens:
        if tok == "/":
            if expect_name:
                raise ValueError("rules.err.path_syntax", {"path": text})
            expect_name = True
        elif tok == "->":
            target = ref_target(kb, cur)
            if target is None:
                raise ValueError("rules.err.path_not_ref", {"path": text, "segment": cur})
            steps.append(Step("deref", target))
            cur, expect_name = target, False
        elif tok == "^":
            parent = owner_object(kb, cur)
            if parent is None:
                raise ValueError("rules.err.path_no_parent", {"path": text, "segment": cur})
            steps.append(Step("parent", parent))
            cur, expect_name = parent, False
        else:
            if steps and steps[-1].op == "deref" and not expect_name:
                pass  # group->remote_as：-> 之后直接跟名称
            elif not expect_name:
                raise ValueError("rules.err.path_syntax", {"path": text})
            base = cur if kb.nodes[cur].type == "object" else None
            if base is None:
                raise ValueError("rules.err.path_not_object", {"path": text, "segment": cur})
            child = next(
                (n.id for n in kb.nodes.values() if owner_object(kb, n.id) == base and short_name(n.id, base) == tok),
                None,
            )
            if child is None:
                raise ValueError("rules.err.path_unknown", {"path": text, "segment": tok, "schema": base})
            steps.append(Step("child", child))
            cur, expect_name = child, False
    if expect_name:
        raise ValueError("rules.err.path_syntax", {"path": text})
    return steps


# ---------- 加载与校验 ----------


def _check_cond(
    kb: KnowledgeBase, target: str, cond: Any, where: str, rule: Rule, issues: list[dict[str, Any]]
) -> None:
    def bad(code: str, **params: Any) -> None:
        issues.append({"file": rule.file, "rule": rule.id, "field": where, "code": code, "params": params})

    if not isinstance(cond, dict) or len(cond) != 1:
        bad("rules.err.cond_shape")
        return
    op, arg = next(iter(cond.items()))
    if op not in OPS:
        bad("rules.err.bad_operator", op=op, ops=", ".join(OPS))
        return
    if op in ("all", "any"):
        if not isinstance(arg, list) or not arg:
            bad("rules.err.cond_list", op=op)
            return
        for i, sub in enumerate(arg):
            _check_cond(kb, target, sub, f"{where}.{op}[{i}]", rule, issues)
        return
    if op == "not":
        _check_cond(kb, target, arg, f"{where}.not", rule, issues)
        return
    if op == "exists":
        path = arg
    else:
        if not isinstance(arg, dict) or "path" not in arg:
            bad("rules.err.cond_args", op=op, need="path")
            return
        path = arg["path"]
        allowed = {"count": {"path", "min", "max"}, "equals": {"path", "value"}, "in": {"path", "values"}}[op]
        extra = set(arg) - allowed
        if extra:
            bad("rules.err.cond_extra", op=op, keys=", ".join(sorted(map(str, extra))))
        if op == "count":
            if "min" not in arg and "max" not in arg:
                bad("rules.err.cond_args", op=op, need="min / max")
            for k in ("min", "max"):
                if k in arg and (not isinstance(arg[k], int) or isinstance(arg[k], bool) or arg[k] < 0):
                    bad("rules.err.cond_int", op=op, key=k)
        if op == "equals" and "value" not in arg:
            bad("rules.err.cond_args", op=op, need="value")
        if op == "in" and not isinstance(arg.get("values"), list):
            bad("rules.err.cond_args", op=op, need="values")
    try:
        rule.paths[str(path)] = compile_path(kb, target, path)
    except ValueError as e:
        code, params = e.args if len(e.args) == 2 else ("rules.err.path_syntax", {"path": path})
        bad(code, **params)


def _texts(raw: Any, name: str, rule: Rule, issues: list[dict[str, Any]]) -> dict[str, str]:
    if not isinstance(raw, dict):
        issues.append(
            {
                "file": rule.file,
                "rule": rule.id,
                "field": name,
                "code": "rules.err.missing_field",
                "params": {"name": name},
            }
        )
        return {}
    out: dict[str, str] = {}
    for lang in LANGS:
        v = raw.get(lang)
        if not isinstance(v, str) or not v.strip():
            issues.append(
                {
                    "file": rule.file,
                    "rule": rule.id,
                    "field": name,
                    "code": "rules.err.missing_lang",
                    "params": {"lang": lang},
                }
            )
            continue
        for ph in _PLACEHOLDER.findall(v):
            if ph not in PLACEHOLDERS:
                issues.append(
                    {
                        "file": rule.file,
                        "rule": rule.id,
                        "field": f"{name}.{lang}",
                        "code": "rules.err.placeholder",
                        "params": {"name": ph, "allowed": ", ".join(PLACEHOLDERS)},
                    }
                )
        out[lang] = v
    return out


def parse_rules(kb: KnowledgeBase, docs: list[tuple[str, Any]]) -> list[Rule]:
    """docs：[(文件名, YAML 内容)]。有任何错误时抛出 RuleError，列出全部问题。"""
    issues: list[dict[str, Any]] = []
    rules: list[Rule] = []
    seen: dict[str, str] = {}
    for fname, doc in docs:
        if not isinstance(doc, dict) or not isinstance(doc.get("rules"), list):
            issues.append({"file": fname, "rule": "", "field": "rules", "code": "rules.err.no_rules", "params": {}})
            continue
        for i, raw in enumerate(doc["rules"]):
            if not isinstance(raw, dict):
                issues.append(
                    {"file": fname, "rule": f"#{i + 1}", "field": "", "code": "rules.err.format", "params": {}}
                )
                continue
            rid = raw.get("id")
            rule = Rule(id=str(rid) if rid else f"#{i + 1}", target="", severity="", assert_=None, file=fname)

            def bad(field_: str, code: str, rule: Rule = rule, **params: Any) -> None:
                issues.append({"file": rule.file, "rule": rule.id, "field": field_, "code": code, "params": params})

            known = {"id", "target", "when", "assert", "severity", "title", "message", "suggestion", "enabled"}
            for k in sorted(set(map(str, raw)) - known):
                bad(k, "rules.err.unknown_field", name=k)
            if not isinstance(rid, str) or not _ID.match(rid):
                bad("id", "rules.err.bad_id", value=str(rid))
            elif rid in seen:
                bad("id", "rules.err.duplicate_id", other=seen[rid])
            else:
                seen[rid] = fname
            sev = raw.get("severity")
            if sev not in SEVERITIES:
                bad("severity", "rules.err.bad_severity", value=str(sev), allowed=", ".join(SEVERITIES))
            else:
                rule.severity = sev
            target = raw.get("target")
            tnode = kb.nodes.get(str(target)) if target else None
            if tnode is None or tnode.type != "object":
                bad("target", "rules.err.unknown_target", value=str(target))
            else:
                rule.target, rule.domain = tnode.id, tnode.domain
            enabled = raw.get("enabled", True)
            if not isinstance(enabled, bool):
                bad("enabled", "rules.err.bad_bool")
            rule.enabled = bool(enabled)
            rule.title = _texts(raw.get("title"), "title", rule, issues)
            rule.message = _texts(raw.get("message"), "message", rule, issues)
            rule.suggestion = _texts(raw.get("suggestion"), "suggestion", rule, issues)
            if "assert" not in raw:
                bad("assert", "rules.err.missing_field", name="assert")
            if rule.target:
                if "when" in raw and raw["when"] is not None:
                    rule.when = raw["when"]
                    _check_cond(kb, rule.target, rule.when, "when", rule, issues)
                if "assert" in raw:
                    rule.assert_ = raw["assert"]
                    _check_cond(kb, rule.target, rule.assert_, "assert", rule, issues)
            rules.append(rule)
    if issues:
        raise RuleError(issues)
    return rules


def load_dir(kb: KnowledgeBase, directory: Path) -> list[Rule]:
    """读取目录下的全部规则文件（*.yaml，按文件名排序）；目录不存在时没有规则。"""
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise RuleError([{"file": str(directory), "rule": "", "field": "", "code": "rules.err.not_dir", "params": {}}])
    docs: list[tuple[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for f in sorted(directory.glob("*.yaml")):
        try:
            docs.append((f.name, read_yaml(f)))
        except Exception as e:  # YAML 语法错误
            first = str(e).splitlines()[0] if str(e) else ""
            issues.append(
                {"file": f.name, "rule": "", "field": "", "code": "rules.err.yaml", "params": {"error": first}}
            )
    if issues:
        raise RuleError(issues)
    return parse_rules(kb, docs)


_cache: dict[tuple[str, int], tuple[float, list[Rule]]] = {}
_lock = threading.Lock()


def load_cached(kb: KnowledgeBase, directory: Path) -> list[Rule]:
    """按目录与文件修改时间缓存（同一个知识库对象）。"""
    sig = max((f.stat().st_mtime for f in directory.glob("*.yaml")), default=0.0) if directory.is_dir() else -1.0
    key = (str(directory.resolve()), id(kb))
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == sig:
            return hit[1]
    rules = load_dir(kb, directory)
    with _lock:
        _cache[key] = (sig, rules)
    return rules


# ---------- 求值 ----------


def live(d: dict[str, Any]) -> bool:
    """节点是否“生效”：对象存在即生效；属性要求取值不为空、不为 false、不是取消形式。默认（隐藏）节点按有效值参与。"""
    if d.get("negated"):
        return False
    if d.get("kind") == "object":
        return True
    v = d.get("value")
    return not (v is None or v is False or v == "" or v == [])


class Evaluator:
    def __init__(self, g: nx.MultiDiGraph):
        self.g = g
        self.children: dict[str, list[str]] = {}
        self.parent: dict[str, str] = {}
        self.refs: dict[str, list[str]] = {}
        for a, b, d in g.edges(data=True):
            kind = d.get("kind")
            if kind == "contains":
                self.children.setdefault(a, []).append(b)
                self.parent[b] = a
            elif kind == "reference":
                self.refs.setdefault(a, []).append(b)

    def walk(self, start: str, steps: list[Step]) -> list[str]:
        cur = [start]
        for st in steps:
            nxt: list[str] = []
            for n in cur:
                if st.op == "child":
                    nxt += [c for c in self.children.get(n, []) if self.g.nodes[c].get("schema") == st.schema]
                elif st.op == "deref":
                    nxt += [t for t in self.refs.get(n, []) if self.g.nodes[t].get("schema") == st.schema]
                else:
                    p = self.parent.get(n)
                    while p is not None and self.g.nodes[p].get("schema") != st.schema:
                        p = self.parent.get(p)
                    if p is not None:
                        nxt.append(p)
            cur = list(dict.fromkeys(nxt))
        return [n for n in cur if live(self.g.nodes[n])]

    def test(self, rule: Rule, node: str, cond: Any) -> bool:
        op, arg = next(iter(cond.items()))
        if op == "all":
            return all(self.test(rule, node, c) for c in arg)
        if op == "any":
            return any(self.test(rule, node, c) for c in arg)
        if op == "not":
            return not self.test(rule, node, arg)
        path = arg if op == "exists" else arg["path"]
        found = self.walk(node, rule.paths[str(path)])
        if op == "exists":
            return bool(found)
        if op == "count":
            n = len(found)
            return n >= arg.get("min", 0) and ("max" not in arg or n <= arg["max"])
        values = {_text(self.g.nodes[n].get("value")) for n in found}
        if op == "equals":
            return _text(arg["value"]) in values
        return bool(values & {_text(v) for v in arg["values"]})


def _text(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return "" if v is None else str(v)


def key_text(key: Any) -> str:
    if isinstance(key, dict):
        return ",".join(f"{k}={'' if v is None else v}" for k, v in key.items())
    return "" if key is None else str(key)


def evaluate(g: nx.MultiDiGraph, rules: list[Rule]) -> list[tuple[Rule, str]]:
    """对图中每个适用的实例求值，返回违反规则的 (规则, 节点)。派生节点（被引用即隐式存在）不检查。"""
    ev = Evaluator(g)
    by_schema: dict[str, list[str]] = {}
    for n, d in g.nodes(data=True):
        if d.get("kind") == "object" and d.get("origin") != "derived" and not d.get("negated"):
            by_schema.setdefault(str(d.get("schema")), []).append(n)
    out: list[tuple[Rule, str]] = []
    for r in rules:
        if not r.enabled:
            continue
        for n in by_schema.get(r.target, []):
            if r.when is not None and not ev.test(r, n, r.when):
                continue
            if not ev.test(r, n, r.assert_):
                out.append((r, n))
    return out
