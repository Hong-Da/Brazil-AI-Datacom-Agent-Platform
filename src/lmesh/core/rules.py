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
    /mgmt.aaa          以 / 开头：从设备根节点出发（第一段写顶层对象的完整编号）
路径在加载时按 Schema 校验，写错时给出文件、规则编号与出错的位置。

扩展（M4-7，向后兼容；旧规则文件不受影响）：
    target: device                   设备级规则：每台设备求值一次，路径从设备根节点出发（例如 mgmt.telnet/enabled）
    match: {path: 路径, pattern: 正则, ignore_case: true}   路径上有节点的有效值（文本）能被正则搜索到
    range: {path: 路径, min: N, max: N, unit: min_sec}       路径上有节点的数值在范围内；unit=min_sec 时
                                     取值按“分 秒”换算成秒（例如 "15 0" → 900），缺省按整数
    key: {values: [V…] | pattern: 正则, path: 路径, ignore_case: true}
                                     实例的键（给出 path 时为路径上节点的键）在列表中 / 能被正则搜索到
    family: [平台族…]                设备的平台族在列表中（例如 huawei-vrp8）。只用于 Profile 还缺少缺省值、
                                     不得不按平台区分“没有配置时的实际行为”的情况，知识库补齐缺省值后应去掉
    $名称                            条件里的取值（value、values、min、max、pattern）可以引用文件级 vars 里的变量，
                                     基线（kind: baseline）的 profiles 可以覆盖变量，例如弱团体字清单、超时阈值
    规则可选字段：tags（分类标签）、profiles（所属基线，见 core/baseline.py）、
                  remedy（修复参考命令：{huawei: [命令…], cisco: [命令…]}，风格名与 knowledge/terms.yaml 一致，
                  命令里可用 {node}、{key}）
文件级字段：kind（check 缺省 / baseline：基线文件只由 lmesh baseline 加载，lmesh check 不加载）、vars、profiles。
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
OPS = ("exists", "count", "equals", "in", "match", "range", "key", "family", "all", "any", "not")
DEVICE_TARGET = "device"  # 设备级规则的 target
DEVICE_NODE = "device"  # 图的设备根节点编号（与 graph.DEVICE 一致）
KINDS = ("check", "baseline")
UNITS = ("min_sec",)
FILE_FIELDS = {"kind", "vars", "profiles", "rules"}
BUILTIN_FILE = "builtin.yaml"  # 内置检查的开关与级别覆盖文件（不是规则文件，见 checks.load_overrides）
CROSS_DEVICE_FILE = "cross-device.yaml"  # 跨设备一致性的链路规则（格式不同，见 core/consistency.py）
NOT_RULE_FILES = (BUILTIN_FILE, CROSS_DEVICE_FILE)


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
    tags: list[str] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)  # 所属基线（kind=baseline 的文件）
    remedy: dict[str, list[str]] = field(default_factory=dict)  # 显示风格 → 修复参考命令
    kind: str = "check"
    vars: dict[str, Any] = field(default_factory=dict)  # 文件级变量（条件中的 $名称）

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "builtin": False,
            "source": self.file,
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
            "tags": self.tags,
            "profiles": self.profiles,
            "remedy": self.remedy,
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
    if tokens and tokens[0] == "/":  # 绝对路径：从设备根节点出发
        tokens = tokens[1:]
        steps.append(Step("root", DEVICE_TARGET))
        cur = DEVICE_TARGET
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
            parent = owner_object(kb, cur) if cur != DEVICE_TARGET else None
            if parent is None:
                raise ValueError("rules.err.path_no_parent", {"path": text, "segment": cur})
            steps.append(Step("parent", parent))
            cur, expect_name = parent, False
        else:
            if steps and steps[-1].op == "deref" and not expect_name:
                pass  # group->remote_as：-> 之后直接跟名称
            elif not expect_name:
                raise ValueError("rules.err.path_syntax", {"path": text})
            if cur == DEVICE_TARGET:  # 设备根节点下是顶层对象，名称写完整编号
                child = next(
                    (n.id for n in kb.nodes.values() if n.id == tok and n.type == "object" and not n.parent), None
                )
            else:
                base = cur if kb.nodes[cur].type == "object" else None
                if base is None:
                    raise ValueError("rules.err.path_not_object", {"path": text, "segment": cur})
                child = next(
                    (
                        n.id
                        for n in kb.nodes.values()
                        if owner_object(kb, n.id) == base and short_name(n.id, base) == tok
                    ),
                    None,
                )
            if child is None:
                raise ValueError("rules.err.path_unknown", {"path": text, "segment": tok, "schema": cur})
            steps.append(Step("child", child))
            cur, expect_name = child, False
    if expect_name:
        raise ValueError("rules.err.path_syntax", {"path": text})
    return steps


# ---------- 加载与校验 ----------


ALLOWED_ARGS = {
    "count": {"path", "min", "max"},
    "equals": {"path", "value"},
    "in": {"path", "values"},
    "match": {"path", "pattern", "ignore_case"},
    "range": {"path", "min", "max", "unit"},
    "key": {"path", "values", "pattern", "ignore_case"},
}


def is_var(v: Any) -> bool:
    return isinstance(v, str) and len(v) > 1 and v.startswith("$")


def resolve(v: Any, variables: dict[str, Any]) -> Any:
    """$名称 → 变量的值（列表里的元素也可以是变量；列表变量会展开）。"""
    if is_var(v):
        return variables.get(v[1:])
    if isinstance(v, list):
        out: list[Any] = []
        for item in v:
            r = resolve(item, variables)
            out.extend(r if isinstance(r, list) and is_var(item) else [r])
        return out
    return v


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
    if op == "family":
        families = sorted({p.family for p in kb.profiles.values()})
        if not isinstance(arg, list) or not arg or not all(isinstance(x, str) for x in arg):
            bad("rules.err.cond_args", op=op, need="[family…]")
            return
        for x in arg:
            if x not in families:
                bad("rules.err.unknown_family", value=x, allowed=", ".join(families))
        return

    def val(k: str) -> Any:
        """条件参数的取值；$名称 必须在文件级 vars 中声明。"""
        v = arg.get(k)
        if is_var(v) and v[1:] not in rule.vars:
            bad("rules.err.unknown_var", name=v[1:])
            return None
        if isinstance(v, list):
            for item in v:
                if is_var(item) and item[1:] not in rule.vars:
                    bad("rules.err.unknown_var", name=item[1:])
        return resolve(v, rule.vars)

    path: Any = None
    if op == "exists":
        path = arg
    else:
        if not isinstance(arg, dict) or ("path" not in arg and op != "key"):
            bad("rules.err.cond_args", op=op, need="path")
            return
        path = arg.get("path")
        extra = set(arg) - ALLOWED_ARGS[op]
        if extra:
            bad("rules.err.cond_extra", op=op, keys=", ".join(sorted(map(str, extra))))
        if op in ("count", "range"):
            if "min" not in arg and "max" not in arg:
                bad("rules.err.cond_args", op=op, need="min / max")
            for k in ("min", "max"):
                v = val(k) if k in arg else 0
                if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                    bad("rules.err.cond_int", op=op, key=k)
        if op == "range" and "unit" in arg and arg["unit"] not in UNITS:
            bad("rules.err.bad_unit", value=str(arg["unit"]), allowed=", ".join(UNITS))
        if op == "equals":
            if "value" not in arg:
                bad("rules.err.cond_args", op=op, need="value")
            else:
                val("value")
        if op in ("in", "key") and "values" in arg and not isinstance(val("values"), list):
            bad("rules.err.cond_args", op=op, need="values")
        if op == "in" and "values" not in arg:
            bad("rules.err.cond_args", op=op, need="values")
        if op == "key" and ("values" in arg) == ("pattern" in arg):
            bad("rules.err.cond_args", op=op, need="values / pattern")
        if op in ("match", "key") and ("pattern" in arg or op == "match"):
            pattern = val("pattern")
            if not isinstance(pattern, str):
                bad("rules.err.cond_args", op=op, need="pattern")
            else:
                try:
                    re.compile(pattern)
                except re.error as e:
                    bad("rules.err.bad_pattern", pattern=pattern, error=str(e))
        if "ignore_case" in arg and not isinstance(arg["ignore_case"], bool):
            bad("rules.err.bad_bool")
        if op == "key" and path is None:
            return
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
        kind, variables, profiles = _file_header(fname, doc, issues)
        for i, raw in enumerate(doc["rules"]):
            if not isinstance(raw, dict):
                issues.append(
                    {"file": fname, "rule": f"#{i + 1}", "field": "", "code": "rules.err.format", "params": {}}
                )
                continue
            rid = raw.get("id")
            rule = Rule(
                id=str(rid) if rid else f"#{i + 1}",
                target="",
                severity="",
                assert_=None,
                file=fname,
                kind=kind,
                vars=variables,
            )

            def bad(field_: str, code: str, rule: Rule = rule, **params: Any) -> None:
                issues.append({"file": rule.file, "rule": rule.id, "field": field_, "code": code, "params": params})

            known = {"id", "target", "when", "assert", "severity", "title", "message", "suggestion", "enabled"}
            known |= {"tags", "profiles", "remedy"}
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
            if target == DEVICE_TARGET:
                rule.target = DEVICE_TARGET
            elif tnode is None or tnode.type != "object":
                bad("target", "rules.err.unknown_target", value=str(target))
            else:
                rule.target, rule.domain = tnode.id, tnode.domain
            rule.tags = _str_list(raw.get("tags"), "tags", bad)
            rule.profiles = _str_list(raw.get("profiles"), "profiles", bad)
            for name in rule.profiles:
                if name not in profiles:
                    bad("profiles", "rules.err.unknown_profile", name=name, allowed=", ".join(profiles) or "-")
            if kind == "baseline" and not rule.profiles:
                bad("profiles", "rules.err.missing_field", name="profiles")
            rule.remedy = _remedy(raw.get("remedy"), bad)
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


def _str_list(v: Any, name: str, bad: Any) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, str) and _ID.match(x) for x in v):
        bad(name, "rules.err.bad_list", name=name)
        return []
    return list(v)


def _remedy(v: Any, bad: Any) -> dict[str, list[str]]:
    """修复参考命令：{显示风格: [命令…]}，风格名与 knowledge/terms.yaml 的 styles 一致。"""
    if v is None:
        return {}
    from lmesh.core.terms import STYLES

    if not isinstance(v, dict):
        bad("remedy", "rules.err.bad_remedy", allowed=", ".join(STYLES))
        return {}
    out: dict[str, list[str]] = {}
    for style, cmds in v.items():
        if style not in STYLES or not isinstance(cmds, list) or not all(isinstance(c, str) and c for c in cmds):
            bad(f"remedy.{style}", "rules.err.bad_remedy", allowed=", ".join(STYLES))
            continue
        for c in cmds:
            for ph in _PLACEHOLDER.findall(c):
                if ph not in PLACEHOLDERS:
                    bad(f"remedy.{style}", "rules.err.placeholder", name=ph, allowed=", ".join(PLACEHOLDERS))
        out[str(style)] = list(cmds)
    return out


def _file_header(
    fname: str, doc: dict[str, Any], issues: list[dict[str, Any]]
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """文件级字段：kind、vars（条件里的 $名称）、profiles（基线：{名称: {title, description, includes, vars}}）。"""

    def bad(field_: str, code: str, **params: Any) -> None:
        issues.append({"file": fname, "rule": "", "field": field_, "code": code, "params": params})

    for k in sorted(set(map(str, doc)) - FILE_FIELDS):
        bad(k, "rules.err.unknown_field", name=k)
    kind = doc.get("kind", "check")
    if kind not in KINDS:
        bad("kind", "rules.err.bad_kind", value=str(kind), allowed=", ".join(KINDS))
        kind = "check"
    variables = doc.get("vars") or {}
    if not isinstance(variables, dict) or not all(isinstance(k, str) and _ID.match(k) for k in variables):
        bad("vars", "rules.err.bad_vars")
        variables = {}
    profiles = doc.get("profiles") or {}
    if not isinstance(profiles, dict):
        bad("profiles", "rules.err.bad_profiles")
        profiles = {}
    if kind == "baseline" and not profiles:
        bad("profiles", "rules.err.missing_field", name="profiles")
    for name, prof in profiles.items():
        where = f"profiles.{name}"
        if not isinstance(name, str) or not _ID.match(name) or not isinstance(prof, dict):
            bad(where, "rules.err.bad_profiles")
            continue
        for k in sorted(set(map(str, prof)) - {"title", "description", "includes", "vars"}):
            bad(f"{where}.{k}", "rules.err.unknown_field", name=k)
        for f in ("title", "description"):
            texts = prof.get(f)
            for lang in LANGS:
                if not isinstance(texts, dict) or not isinstance(texts.get(lang), str) or not texts[lang].strip():
                    bad(f"{where}.{f}", "rules.err.missing_lang", lang=lang)
        for inc in prof.get("includes") or []:
            if inc not in profiles or inc == name:
                bad(f"{where}.includes", "rules.err.unknown_profile", name=str(inc), allowed=", ".join(profiles))
        over = prof.get("vars") or {}
        if not isinstance(over, dict):
            bad(f"{where}.vars", "rules.err.bad_vars")
            continue
        for k in over:
            if k not in variables:
                bad(f"{where}.vars", "rules.err.unknown_var", name=str(k))
    return str(kind), dict(variables), dict(profiles)


def read_docs(directory: Path, kind: str = "check") -> list[tuple[str, Any]]:
    """读取目录下同一类（check / baseline）的规则文件（*.yaml，按文件名排序）；YAML 语法错误时抛出 RuleError。"""
    docs: list[tuple[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for f in sorted(directory.glob("*.yaml")):
        if f.name in NOT_RULE_FILES:
            continue
        try:
            doc = read_yaml(f)
        except Exception as e:  # YAML 语法错误
            first = str(e).splitlines()[0] if str(e) else ""
            issues.append(
                {"file": f.name, "rule": "", "field": "", "code": "rules.err.yaml", "params": {"error": first}}
            )
            continue
        doc_kind = doc.get("kind", "check") if isinstance(doc, dict) else "check"
        if (doc_kind == "baseline") == (kind == "baseline"):
            docs.append((f.name, doc))
    if issues:
        raise RuleError(issues)
    return docs


def load_dir(kb: KnowledgeBase, directory: Path, kind: str = "check") -> list[Rule]:
    """读取目录下的全部规则文件（*.yaml，按文件名排序）；目录不存在时没有规则。

    kind=check（缺省）只读检查规则文件，kind=baseline 只读基线文件（文件级 kind: baseline）。
    """
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise RuleError([{"file": str(directory), "rule": "", "field": "", "code": "rules.err.not_dir", "params": {}}])
    return parse_rules(kb, read_docs(directory, kind))


_cache: dict[tuple[str, int, str], tuple[float, list[Rule]]] = {}
_lock = threading.Lock()


def load_cached(kb: KnowledgeBase, directory: Path, kind: str = "check") -> list[Rule]:
    """按目录与文件修改时间缓存（同一个知识库对象）。"""
    sig = max((f.stat().st_mtime for f in directory.glob("*.yaml")), default=0.0) if directory.is_dir() else -1.0
    key = (str(directory.resolve()), id(kb), kind)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == sig:
            return hit[1]
    rules = load_dir(kb, directory, kind)
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
    """variables：覆盖规则文件 vars 的变量（基线的 profiles.vars）；trace：求值时路径上找到的节点（用作证据行号）。"""

    def __init__(self, g: nx.MultiDiGraph, variables: dict[str, Any] | None = None):
        self.g = g
        self.variables = variables or {}
        self.trace: set[str] = set()
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
            if st.op == "root":
                cur = [DEVICE_NODE] if DEVICE_NODE in self.g else []
                continue
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

    def test(self, rule: Rule, node: str, cond: Any, neg: bool = False) -> bool:
        """neg：条件处在奇数层 not 之下。证据（trace）：正向条件记路径上找到的节点（取值不符或缺少时看它们），
        取反条件只记满足条件的节点（正是它们让断言不成立）。"""
        op, arg = next(iter(cond.items()))
        if op == "all":  # 不短路：断言不成立时每个分支的证据都要记下
            return all([self.test(rule, node, c, neg) for c in arg])
        if op == "any":
            return any(self.test(rule, node, c, neg) for c in arg)
        if op == "not":
            return not self.test(rule, node, arg, not neg)
        if op == "family":
            return str(self.g.graph.get("family") or "") in arg
        variables = {**rule.vars, **{k: v for k, v in self.variables.items() if k in rule.vars}}

        def val(k: str, default: Any = None) -> Any:
            return resolve(arg.get(k, default), variables)

        flags = re.IGNORECASE if op != "exists" and arg.get("ignore_case") else 0
        if op == "key":
            found = self.walk(node, rule.paths[str(arg["path"])]) if "path" in arg else [node]
            if "values" in arg:
                wanted = {_text(v).lower() if flags else _text(v) for v in val("values") or []}

                def ok(n: str) -> bool:
                    k = key_text(self.g.nodes[n].get("key"))
                    return (k.lower() if flags else k) in wanted
            else:
                pattern = str(val("pattern"))

                def ok(n: str) -> bool:
                    return re.search(pattern, key_text(self.g.nodes[n].get("key")), flags) is not None

            hits = [n for n in found if ok(n)]
            self.trace.update(n for n in (hits if neg else found) if n != node)
            return bool(hits)
        path = arg if op == "exists" else arg["path"]
        found = self.walk(node, rule.paths[str(path)])
        if op in ("exists", "count"):
            self.trace.update(found)
            if op == "exists":
                return bool(found)
            n = len(found)
            return n >= val("min", 0) and ("max" not in arg or n <= val("max"))
        lo, hi, unit = val("min", 0), val("max"), arg.get("unit")
        pattern, wanted = str(val("pattern")), {_text(v) for v in (val("values") or [])}
        target = _text(val("value"))

        def hit(n: str) -> bool:
            v = self.g.nodes[n].get("value")
            if op == "range":
                x = _number(v, unit)
                return x is not None and x >= lo and ("max" not in arg or x <= hi)
            if op == "match":
                return re.search(pattern, _text(v), flags) is not None
            if op == "equals":
                return _text(v) == target
            return _text(v) in wanted

        hits = [n for n in found if hit(n)]
        self.trace.update(hits if neg else found)
        return bool(hits)


def _number(v: Any, unit: str | None) -> int | None:
    """数值比较用：整数；unit=min_sec 时 "分 秒" 换算成秒（"15 0" → 900，"10" → 600）。取不到时为 None。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v * 60 if unit == "min_sec" else v
    parts = str(v if v is not None else "").split()
    if not parts or not all(p.isdigit() for p in parts):
        return None
    if unit == "min_sec":
        return int(parts[0]) * 60 + (int(parts[1]) if len(parts) > 1 else 0)
    return int(parts[0]) if len(parts) == 1 else None


def _text(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return "" if v is None else str(v)


def key_text(key: Any) -> str:
    if isinstance(key, dict):
        return ",".join(f"{k}={'' if v is None else v}" for k, v in key.items())
    return "" if key is None else str(key)


def instances(g: nx.MultiDiGraph) -> dict[str, list[str]]:
    """规则适用的实例：Schema 类型 → 对象节点（派生、取消形式的不算）；设备级规则的实例是设备根节点。"""
    by_schema: dict[str, list[str]] = {}
    for n, d in g.nodes(data=True):
        if d.get("kind") == "object" and d.get("origin") != "derived" and not d.get("negated"):
            by_schema.setdefault(str(d.get("schema")), []).append(n)
    if DEVICE_NODE in g:
        by_schema[DEVICE_TARGET] = [DEVICE_NODE]
    return by_schema


def evaluate(g: nx.MultiDiGraph, rules: list[Rule]) -> list[tuple[Rule, str]]:
    """对图中每个适用的实例求值，返回违反规则的 (规则, 节点)。派生节点（被引用即隐式存在）不检查。"""
    ev = Evaluator(g)
    by_schema = instances(g)
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
