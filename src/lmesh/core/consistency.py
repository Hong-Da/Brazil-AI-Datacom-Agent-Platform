"""跨设备一致性检查（M4-6）：在拓扑（core/topology.py）的链路上比较两端，规则在 knowledge/rules/cross-device.yaml。

链路规则格式：
    rules:
      - id: xd.subnet.mtu                 # 唯一编号（小写字母、数字、. _ -）
        link: subnet                      # 链路类型（topology.LINK_TYPES）
        compare: {value: mtu}             # 两端取同一项；或 {a: 取值, b: 取值, symmetric: true}：a 端的 a 对 b 端的 b（反向再比一次）
        op: equal                         # equal（默认）/ same_presence / both / overlap
        when: {both: [取值…], either: [取值…]}  # 可省：两端都为真 / 至少一端为真时才检查
        pair: vrrp                        # 可省：端点对象下按键配对的子对象（Schema 路径），compare 从配对对象出发
        requires: [interface.vrrp]        # 可省：Schema 中缺少这些节点时跳过（rules_skipped）
        domain: interface                 # 可省：默认按链路类型
        severity: error / warning / info
        title / message / suggestion: {zh-CN, en, pt-BR}   # 占位符见 PLACEHOLDERS
        enabled: true
取值：
    fact:名称      拓扑推导出的事实（topology 中各链路端点的 facts，配对时另有 fact:paired）
    Schema 路径    从链路端点对象出发（subnet / ospf / isis / ldp 的端点是 interface，bgp 是 bgp.peer），写法同 rules.py；
                   其他链路类型只能用 fact:。属性取有效值（含隐藏的默认值），对象取键；多个时按文本排序成列表。
比较：
    equal          两端都有值且不同时报出（列表按集合比较）
    same_presence  一端为真、一端为假时报出（例如只有一端使能 LDP）
    both           任一端为假时报出（例如对等体只在一端配置）
    overlap        两端都是非空列表且没有交集时报出（例如 IS-IS 级别）
内置检查：xd.ip_duplicate（同一 VRF 中同一地址出现在多台设备上），文案在 locales（consistency.xd.ip_duplicate.*）。

结果与单台检查（checks.check）一致：findings（rule、severity、domain、node、schema、nodes、lines、message / suggestion 为
文案键 + 参数），再加上 link（链路编号）、link_type、device（node 所在设备）、devices、ends（两端的设备、节点、取值与行号）；
summary 在 checks.summarize 之外加 by_link、by_device。拓扑中的每条链路带 issues（发现的 id）与 severity（最高级别）。
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lmesh.core import checks, i18n
from lmesh.core import rules as rulesmod
from lmesh.core import topology as topomod
from lmesh.core.kb import KnowledgeBase, read_yaml

RULES_FILE = rulesmod.CROSS_DEVICE_FILE
OPS = ("equal", "same_presence", "both", "overlap")
PLACEHOLDERS = ("link", "a_device", "a_end", "a_value", "b_device", "b_end", "b_value")
END_SCHEMA = {"subnet": "interface", "ospf": "interface", "isis": "interface", "ldp": "interface", "bgp": "bgp.peer"}
LINK_DOMAIN = {
    "subnet": "interface",
    "ospf": "ospf",
    "isis": "isis",
    "ldp": "mpls",
    "ldp_remote": "mpls",
    "bgp": "bgp",
    "pw": "l2vpn",
    "bfd": "bfd",
}
BUILTIN = {"xd.ip_duplicate": "error"}
_ID = re.compile(r"^[a-z0-9][a-z0-9_.\-]*$")
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_FIELDS = {
    "id",
    "link",
    "compare",
    "op",
    "when",
    "pair",
    "requires",
    "domain",
    "severity",
    "title",
    "message",
    "suggestion",
    "enabled",
}


@dataclass
class LinkRule:
    id: str
    link: str
    a: str
    b: str
    symmetric: bool = False
    op: str = "equal"
    when_both: list[str] = field(default_factory=list)
    when_either: list[str] = field(default_factory=list)
    pair: str | None = None
    pair_schema: str | None = None
    requires: list[str] = field(default_factory=list)
    domain: str = ""
    severity: str = "warning"
    title: dict[str, str] = field(default_factory=dict)
    message: dict[str, str] = field(default_factory=dict)
    suggestion: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    file: str = ""
    paths: dict[str, list[rulesmod.Step]] = field(default_factory=dict)
    pair_steps: list[rulesmod.Step] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "link": self.link,
            "compare": {"a": self.a, "b": self.b, "symmetric": self.symmetric},
            "op": self.op,
            "when": {"both": self.when_both, "either": self.when_either},
            "pair": self.pair,
            "requires": self.requires,
            "domain": self.domain,
            "severity": self.severity,
            "enabled": self.enabled,
            "title": self.title,
            "message": self.message,
            "suggestion": self.suggestion,
            "file": self.file,
        }


@dataclass
class RuleSet:
    rules: list[LinkRule]
    skipped: list[dict[str, Any]]  # requires 不满足的规则：{id, missing}


# ---------- 加载与校验 ----------


def rules_file(kb_root: Path) -> Path:
    """知识库 rules/ 中的跨设备规则；早于 M4 复制出的运行时知识库没有这个文件时，用程序自带的。"""
    own = checks.rules_dir(kb_root) / RULES_FILE
    if own.is_file():
        return own
    from lmesh import paths

    return paths.builtin_knowledge_dir() / "rules" / RULES_FILE


def _texts(raw: Any, name: str, rid: str, fname: str, issues: list[dict[str, Any]]) -> dict[str, str]:
    def bad(field_: str, code: str, **params: Any) -> None:
        issues.append({"file": fname, "rule": rid, "field": field_, "code": code, "params": params})

    if not isinstance(raw, dict):
        bad(name, "rules.err.missing_field", name=name)
        return {}
    out: dict[str, str] = {}
    for lang in i18n.LANGS:
        v = raw.get(lang)
        if not isinstance(v, str) or not v.strip():
            bad(name, "rules.err.missing_lang", lang=lang)
            continue
        for ph in _PLACEHOLDER.findall(v):
            if ph not in PLACEHOLDERS:
                bad(f"{name}.{lang}", "rules.err.placeholder", name=ph, allowed=", ".join(PLACEHOLDERS))
        out[lang] = v
    return out


def parse(kb: KnowledgeBase, doc: Any, fname: str = RULES_FILE) -> RuleSet:
    """有任何错误时抛出 rules.RuleError（与单台检查的规则文件相同的问题格式）。"""
    issues: list[dict[str, Any]] = []
    out: list[LinkRule] = []
    skipped: list[dict[str, Any]] = []
    if not isinstance(doc, dict) or not isinstance(doc.get("rules"), list):
        raise rulesmod.RuleError(
            [{"file": fname, "rule": "", "field": "rules", "code": "rules.err.no_rules", "params": {}}]
        )
    seen: set[str] = set()
    for i, raw in enumerate(doc["rules"]):
        if not isinstance(raw, dict):
            issues.append({"file": fname, "rule": f"#{i + 1}", "field": "", "code": "rules.err.format", "params": {}})
            continue
        rid = str(raw.get("id") or f"#{i + 1}")

        def bad(field_: str, code: str, rid: str = rid, **params: Any) -> None:
            issues.append({"file": fname, "rule": rid, "field": field_, "code": code, "params": params})

        for k in sorted(set(map(str, raw)) - _FIELDS):
            bad(k, "rules.err.unknown_field", name=k)
        if not isinstance(raw.get("id"), str) or not _ID.match(raw["id"]):
            bad("id", "rules.err.bad_id", value=str(raw.get("id")))
        elif rid in seen or rid in BUILTIN:
            bad("id", "rules.err.duplicate_id", other=fname)
        seen.add(rid)
        link = raw.get("link")
        if link not in topomod.LINK_TYPES:
            bad("link", "consistency.err.bad_link", value=str(link), allowed=", ".join(topomod.LINK_TYPES))
            link = None
        sev = raw.get("severity")
        if sev not in rulesmod.SEVERITIES:
            bad("severity", "rules.err.bad_severity", value=str(sev), allowed=", ".join(rulesmod.SEVERITIES))
        op = raw.get("op", "equal")
        if op not in OPS:
            bad("op", "consistency.err.bad_op", value=str(op), allowed=", ".join(OPS))
        enabled = raw.get("enabled", True)
        if not isinstance(enabled, bool):
            bad("enabled", "rules.err.bad_bool")
        cmp_ = raw.get("compare")
        a = b = None
        symmetric = False
        if isinstance(cmp_, dict) and set(cmp_) <= {"value"} and isinstance(cmp_.get("value"), str):
            a = b = cmp_["value"]
        elif (
            isinstance(cmp_, dict)
            and set(cmp_) <= {"a", "b", "symmetric"}
            and isinstance(cmp_.get("a"), str)
            and isinstance(cmp_.get("b"), str)
        ):
            a, b, symmetric = cmp_["a"], cmp_["b"], bool(cmp_.get("symmetric", False))
        else:
            bad("compare", "consistency.err.compare")
        when = raw.get("when") or {}
        if not isinstance(when, dict) or set(when) - {"both", "either"}:
            bad("when", "consistency.err.when")
            when = {}
        both = [str(x) for x in (when.get("both") or [])] if isinstance(when.get("both", []), list) else []
        either = [str(x) for x in (when.get("either") or [])] if isinstance(when.get("either", []), list) else []
        requires = raw.get("requires") or []
        if not isinstance(requires, list):
            bad("requires", "consistency.err.requires")
            requires = []
        missing = [str(r) for r in requires if str(r) not in kb.nodes]
        domain = raw.get("domain") or LINK_DOMAIN.get(str(link), "")
        rule = LinkRule(
            id=rid,
            link=str(link or ""),
            a=a or "",
            b=b or "",
            symmetric=symmetric,
            op=str(op),
            when_both=both,
            when_either=either,
            pair=str(raw["pair"]) if raw.get("pair") else None,
            requires=[str(r) for r in requires],
            domain=str(domain),
            severity=str(sev),
            enabled=bool(enabled),
            file=fname,
            title=_texts(raw.get("title"), "title", rid, fname, issues),
            message=_texts(raw.get("message"), "message", rid, fname, issues),
            suggestion=_texts(raw.get("suggestion"), "suggestion", rid, fname, issues),
        )
        if missing:
            skipped.append({"id": rid, "missing": missing})
            continue
        if link is None:
            continue
        start = END_SCHEMA.get(str(link))
        if rule.pair:
            if start is None:
                bad("pair", "consistency.err.fact_only", link=link)
            else:
                try:
                    rule.pair_steps = rulesmod.compile_path(kb, start, rule.pair)
                    rule.pair_schema = rule.pair_steps[-1].schema
                    if kb.nodes[rule.pair_schema].type != "object":
                        bad("pair", "rules.err.path_not_object", path=rule.pair, segment=rule.pair_schema)
                    start = rule.pair_schema
                except ValueError as e:
                    code, params = e.args if len(e.args) == 2 else ("rules.err.path_syntax", {"path": rule.pair})
                    bad("pair", code, **params)
                    continue
        specs = [("compare", rule.a), ("compare", rule.b)] + [("when", s) for s in both + either]
        for where, spec in dict.fromkeys(specs):
            if spec.startswith("fact:") or spec in rule.paths:
                continue
            if start is None:
                bad(where, "consistency.err.fact_only", link=link)
                continue
            try:
                rule.paths[spec] = rulesmod.compile_path(kb, start, spec)
            except ValueError as e:
                code, params = e.args if len(e.args) == 2 else ("rules.err.path_syntax", {"path": spec})
                bad(where, code, **params)
        out.append(rule)
    if issues:
        raise rulesmod.RuleError(issues)
    return RuleSet(out, skipped)


def load(kb: KnowledgeBase, path: Path) -> RuleSet:
    if not path.is_file():
        return RuleSet([], [])
    try:
        doc = read_yaml(path)
    except Exception as e:  # YAML 语法错误
        first = str(e).splitlines()[0] if str(e) else ""
        raise rulesmod.RuleError(
            [{"file": path.name, "rule": "", "field": "", "code": "rules.err.yaml", "params": {"error": first}}]
        ) from e
    return parse(kb, doc, path.name)


_cache: dict[tuple[str, int], tuple[float, RuleSet]] = {}
_lock = threading.Lock()


def load_cached(kb: KnowledgeBase, path: Path) -> RuleSet:
    sig = path.stat().st_mtime if path.is_file() else -1.0
    key = (str(path.resolve()), id(kb))
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == sig:
            return hit[1]
    rs = load(kb, path)
    with _lock:
        _cache[key] = (sig, rs)
    return rs


# ---------- 求值 ----------


def _truthy(v: Any) -> bool:
    return not (v is None or v is False or v == "" or v == [] or v == "false")


def _norm(v: Any) -> Any:
    if isinstance(v, list):
        return sorted({str(x) for x in v})
    if isinstance(v, bool):
        return "true" if v else "false"
    return None if v is None else str(v)


def _show(v: Any) -> str:
    if v is None or v == []:
        return "-"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


class _Ends:
    """一条链路（或配对对象）两端的取值。"""

    def __init__(self, topo: topomod.Topology, lk: dict[str, Any]):
        self.topo, self.lk = topo, lk
        self.ev: dict[str, rulesmod.Evaluator] = {}

    def evaluator(self, dev: str) -> rulesmod.Evaluator:
        if dev not in self.ev:
            self.ev[dev] = rulesmod.Evaluator(self.topo.facts[dev].ix.g)
        return self.ev[dev]

    def value(self, rule: LinkRule, side: str, spec: str, node: str | None, facts: dict[str, Any]) -> Any:
        if spec.startswith("fact:"):
            return facts.get(spec[5:])
        if node is None:
            return None
        dev = self.lk[side]["device"]
        ix = self.topo.facts[dev].ix
        found = self.evaluator(dev).walk(node, rule.paths[spec])
        vals = [ix.key(n) if ix.d(n).get("kind") == "object" else ix.d(n).get("value") for n in found]
        vals = [v for v in vals if v is not None]
        if not vals:
            return None
        return vals[0] if len(vals) == 1 else sorted(str(v) for v in vals)


def _units(topo: topomod.Topology, rule: LinkRule, lk: dict[str, Any], ends: _Ends) -> list[dict[str, Any]]:
    """规则在一条链路上的比较单元：没有 pair 时就是两端；有 pair 时是两端按键配对的子对象（并集）。"""
    a_node, b_node = lk["a"]["node"], lk["b"]["node"]
    if not rule.pair:
        return [{"suffix": "", "a": (a_node, lk["a"]["facts"]), "b": (b_node, lk["b"]["facts"])}]
    by_side: dict[str, dict[str, str]] = {}
    for side, node in (("a", a_node), ("b", b_node)):
        dev = lk[side]["device"]
        ix = topo.facts[dev].ix
        found = ends.evaluator(dev).walk(node, rule.pair_steps) if node else []
        by_side[side] = {ix.key(n): n for n in found}
    out = []
    for key in sorted(set(by_side["a"]) | set(by_side["b"])):
        unit: dict[str, Any] = {"suffix": key}
        for side in ("a", "b"):
            n = by_side[side].get(key)
            unit[side] = (n, {**lk[side]["facts"], "paired": n is not None})
        out.append(unit)
    return out


def _violates(op: str, va: Any, vb: Any) -> bool:
    if op == "equal":
        return va is not None and vb is not None and _norm(va) != _norm(vb)
    if op == "same_presence":
        return _truthy(va) != _truthy(vb)
    if op == "both":
        return not (_truthy(va) and _truthy(vb))
    la = va if isinstance(va, list) else ([] if va is None else [va])
    lb = vb if isinstance(vb, list) else ([] if vb is None else [vb])
    return bool(la) and bool(lb) and not ({str(x) for x in la} & {str(x) for x in lb})


def _end_label(e: dict[str, Any]) -> str:
    return str(e.get("interface") or e.get("address") or "-")


def _finding(
    topo: topomod.Topology,
    kb: KnowledgeBase,
    lk: dict[str, Any],
    rule_id: str,
    severity: str,
    domain: str,
    nodes: tuple[str | None, str | None],
    values: tuple[Any, Any],
    flip: bool,
    suffix: str,
    msg_key: str,
    sug_key: str,
    specs: tuple[str | None, str | None] = (None, None),
) -> dict[str, Any]:
    sa, sb = ("b", "a") if flip else ("a", "b")
    ends = []
    for side, node, val, spec in ((sa, nodes[0], values[0], specs[0]), (sb, nodes[1], values[1], specs[1])):
        e = lk[side]
        ix = topo.facts[e["device"]].ix
        # 比较的是对象下的一个属性（例如 mtu）且配置里写了它：定位到那一行，而不是对象头（REQ-055-23）
        attr = f"{node}/{spec}" if node and spec and ":" not in spec and "." not in spec else None
        if attr is not None and attr in ix.g and ix.d(attr).get("origin") != "default" and ix.lines(attr):
            node = attr
        ends.append(
            {
                "device": e["device"],
                "end": _end_label(e),
                "node": node,
                "schema": ix.d(node).get("schema") if node else None,
                "value": val,
                "lines": ix.lines(node),
            }
        )
    first = ends[0] if ends[0]["node"] else ends[1]
    params = {
        "link": lk["id"],
        "a_device": ends[0]["device"],
        "a_end": ends[0]["end"],
        "a_value": _show(values[0]),
        "b_device": ends[1]["device"],
        "b_end": ends[1]["end"],
        "b_value": _show(values[1]),
    }
    return {
        "id": f"{rule_id}@{lk['id']}" + (f"[{suffix}]" if suffix else ""),
        "rule": rule_id,
        "severity": severity,
        "domain": domain,
        "link": lk["id"],
        "link_type": lk["type"],
        "device": first["device"],
        "node": first["node"],
        "schema": first["schema"],
        "nodes": [e["node"] for e in ends if e["node"]],
        "lines": first["lines"],
        "devices": [ends[0]["device"], ends[1]["device"]],
        "ends": ends,
        "message": {"key": msg_key, "params": params},
        "suggestion": {"key": sug_key, "params": params},
    }


def evaluate(topo: topomod.Topology, kb: KnowledgeBase, rules: list[LinkRule]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    by_type: dict[str, list[dict[str, Any]]] = {}
    for lk in topo.links:
        by_type.setdefault(lk["type"], []).append(lk)
    for rule in rules:
        if not rule.enabled:
            continue
        mk, sk = f"xd.{rule.id}.message", f"xd.{rule.id}.suggestion"
        for lk in by_type.get(rule.link, []):
            ends = _Ends(topo, lk)
            for unit in _units(topo, rule, lk, ends):
                (na, fa), (nb, fb) = unit["a"], unit["b"]

                def val(
                    side: str,
                    spec: str,
                    na: Any = na,
                    nb: Any = nb,
                    fa: Any = fa,
                    fb: Any = fb,
                    ends: _Ends = ends,
                    rule: LinkRule = rule,
                ) -> Any:
                    return ends.value(rule, side, spec, na if side == "a" else nb, fa if side == "a" else fb)

                if rule.when_both and not all(_truthy(val(s, w)) for w in rule.when_both for s in ("a", "b")):
                    continue
                if rule.when_either and not any(_truthy(val(s, w)) for w in rule.when_either for s in ("a", "b")):
                    continue
                directions = [(False, val("a", rule.a), val("b", rule.b))]
                if rule.symmetric:
                    directions.append((True, val("b", rule.a), val("a", rule.b)))
                for flip, va, vb in directions:
                    if _violates(rule.op, va, vb):
                        nodes = (nb, na) if flip else (na, nb)
                        out.append(
                            _finding(
                                topo,
                                kb,
                                lk,
                                rule.id,
                                rule.severity,
                                rule.domain,
                                nodes,
                                (va, vb),
                                flip,
                                unit["suffix"],
                                mk,
                                sk,
                                (rule.a, rule.b),  # 翻转时 nodes[0] 也是按 rule.a 取的值
                            )
                        )
                        break
    return out


def _duplicates(topo: topomod.Topology, severity: str) -> list[dict[str, Any]]:
    out = []
    for d in topo.duplicates:
        ends = []
        for e in d["ends"]:
            ix = topo.facts[e["device"]].ix
            ends.append(
                {
                    "device": e["device"],
                    "end": e["interface"],
                    "node": e["node"],
                    "schema": ix.d(e["node"]).get("schema"),
                    "value": d["address"],
                    "lines": ix.lines(e["node"]),
                }
            )
        params = {
            "address": d["address"],
            "vrf": d["vrf"] or "-",
            "where": ", ".join(f"{e['device']} {e['end']}" for e in ends),
        }
        out.append(
            {
                "id": f"xd.ip_duplicate@{d['vrf']}:{d['address']}",
                "rule": "xd.ip_duplicate",
                "severity": severity,
                "domain": "interface",
                "link": None,
                "link_type": None,
                "device": ends[0]["device"],
                "node": ends[0]["node"],
                "schema": ends[0]["schema"],
                "nodes": [e["node"] for e in ends],
                "lines": ends[0]["lines"],
                "devices": sorted({e["device"] for e in ends}),
                "ends": ends,
                "message": {"key": "consistency.xd.ip_duplicate.message", "params": params},
                "suggestion": {"key": "consistency.xd.ip_duplicate.suggestion", "params": params},
            }
        )
    return out


def check(topo: topomod.Topology, kb: KnowledgeBase, ruleset: RuleSet, severity: str | None = None) -> dict[str, Any]:
    """拓扑 + 一致性发现。severity 是最低级别（info 表示全部）。"""
    findings = _duplicates(topo, BUILTIN["xd.ip_duplicate"]) + evaluate(topo, kb, ruleset.rules)
    for f in findings:
        f["ignored"], f["ignore_reason"], f["ignore_id"] = False, None, None
    total = len(findings)
    floor = rulesmod.SEVERITY_RANK.get(severity or "info", 1)
    findings = [f for f in findings if rulesmod.SEVERITY_RANK[f["severity"]] >= floor]
    order = {lk["id"]: k for k, lk in enumerate(topo.links)}
    findings.sort(
        key=lambda f: (-rulesmod.SEVERITY_RANK[f["severity"]], order.get(f["link"] or "", -1), f["rule"], f["id"])
    )
    texts: dict[str, dict[str, str]] = {}
    for r in ruleset.rules:
        texts[f"xd.{r.id}.message"], texts[f"xd.{r.id}.suggestion"] = r.message, r.suggestion
    used = {f["message"]["key"] for f in findings} | {f["suggestion"]["key"] for f in findings}
    data = topomod.to_json(topo)
    issues: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        if f["link"]:
            issues.setdefault(f["link"], []).append(f)
    for lk in data["links"]:
        mine = issues.get(lk["id"], [])
        lk["issues"] = [f["id"] for f in mine]
        lk["severity"] = max((f["severity"] for f in mine), key=lambda s: rulesmod.SEVERITY_RANK[s], default=None)
    per_dev: dict[str, int] = {}
    for f in findings:
        for d in f["devices"]:
            per_dev[d] = per_dev.get(d, 0) + 1
    for n in data["nodes"]:
        n["issues"] = per_dev.get(n["id"], 0)
    summary = checks.summarize(findings, total)
    summary["by_link"] = dict(sorted((k, len(v)) for k, v in issues.items()))
    summary["by_device"] = dict(sorted(per_dev.items()))
    return {
        **data,
        "filters": {"severity": severity or "info"},
        "rules_loaded": len([r for r in ruleset.rules if r.enabled]),
        "rules_skipped": ruleset.skipped,
        "findings": findings,
        "summary": {**summary, "topology": data["summary"]},
        "texts": {k: v for k, v in sorted(texts.items()) if k in used},
    }


def builtin_rules() -> list[dict[str, Any]]:
    return [
        {
            "id": rid,
            "builtin": True,
            "severity": sev,
            **{
                f: {lang: i18n.catalog(lang).get(f"consistency.{rid}.{f}", "") for lang in i18n.LANGS}
                for f in ("title", "message", "suggestion")
            },
        }
        for rid, sev in BUILTIN.items()
    ]
