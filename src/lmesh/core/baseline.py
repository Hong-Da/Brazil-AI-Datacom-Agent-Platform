"""安全基线审计（REQ-020）：对一台或多台设备的配置图跑基线规则，输出设备 × 规则的矩阵、不符合项与分数。

基线规则写在知识库 rules/ 下的基线文件里（文件级 kind: baseline，格式见 core/rules.py 开头），与检查规则共用同一套
条件与求值；lmesh check 不加载基线文件。每个基线文件可以定义多套基线（profiles，例如 basic / strict）：
    profiles.<名称>.includes   包含的其他基线（strict 包含 basic）
    profiles.<名称>.vars       覆盖文件级变量（例如更短的空闲超时）
    rules[].profiles            规则直接属于哪些基线；一套基线的规则 = 自身的规则 + 所含基线的规则

每条规则在一台设备上的结论：
    pass  有适用的实例且全部满足断言
    fail  至少一个适用的实例不满足断言（每个这样的实例是一条不符合项）
    na    没有适用的实例（对象不存在，或前提 when 都不满足）
分数：按级别加权（error 3、warning 2、info 1），通过的权重 / 适用的权重 × 100，取整；没有适用规则时为 null。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from lmesh.core import rules as rulesmod
from lmesh.core.kb import KnowledgeBase

STATUSES = ("pass", "fail", "na")
WEIGHTS = {"error": 3, "warning": 2, "info": 1}
DEFAULT_PROFILE = "basic"


class BaselineError(ValueError):
    """key 是文案键。"""

    def __init__(self, key: str, **fmt: Any):
        super().__init__(key)
        self.key, self.fmt = key, fmt


@dataclass
class Baseline:
    rules: list[rulesmod.Rule]
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)  # 名称 → {title, description, includes}
    file_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)  # 文件 → 该文件的 profiles 原文


def baseline_dir(kb_root: Path) -> Path:
    """知识库的规则目录里有基线文件时用它；早于 M4 复制出的运行时知识库没有基线文件时，用程序自带的规则目录。"""
    from lmesh import paths
    from lmesh.core import checks

    own = checks.rules_dir(kb_root)
    if own.is_dir() and rulesmod.read_docs(own, "baseline"):
        return own
    return paths.builtin_knowledge_dir() / "rules"


def load(kb: KnowledgeBase, directory: Path) -> Baseline:
    """读取并校验目录下的基线文件；有错误时抛出 rules.RuleError。"""
    rules = rulesmod.load_cached(kb, directory, "baseline")
    docs = rulesmod.read_docs(directory, "baseline") if directory.is_dir() else []
    profiles: dict[str, dict[str, Any]] = {}
    file_profiles: dict[str, dict[str, Any]] = {}
    for fname, doc in docs:
        own = dict(doc.get("profiles") or {})
        file_profiles[fname] = own
        for name, prof in own.items():
            entry = profiles.setdefault(
                str(name),
                {"id": str(name), "title": prof.get("title"), "description": prof.get("description"), "includes": []},
            )
            for inc in prof.get("includes") or []:
                if inc not in entry["includes"]:
                    entry["includes"].append(str(inc))
    return Baseline(rules, profiles, file_profiles)


def expand(bl: Baseline, profile: str) -> list[str]:
    """基线及其（递归）包含的基线，被包含的在前。"""
    out: list[str] = []

    def visit(name: str, stack: tuple[str, ...]) -> None:
        if name in out or name in stack or name not in bl.profiles:
            return
        for inc in bl.profiles[name]["includes"]:
            visit(inc, (*stack, name))
        out.append(name)

    visit(profile, ())
    return out


def select(bl: Baseline, profile: str) -> tuple[list[rulesmod.Rule], dict[str, dict[str, Any]]]:
    """一套基线的规则（启用的）与每个文件的变量覆盖（被包含的基线先覆盖，自身最后覆盖）。"""
    if profile not in bl.profiles:
        raise BaselineError("baseline.unknown_profile", profile=profile, allowed=", ".join(bl.profiles) or "-")
    chain = expand(bl, profile)
    rules = [r for r in bl.rules if r.enabled and set(r.profiles) & set(chain)]
    overrides: dict[str, dict[str, Any]] = {}
    for fname, own in bl.file_profiles.items():
        merged: dict[str, Any] = {}
        for name in chain:
            merged.update((own.get(name) or {}).get("vars") or {})
        overrides[fname] = merged
    return rules, overrides


def rule_view(r: rulesmod.Rule) -> dict[str, Any]:
    return {
        "id": r.id,
        "severity": r.severity,
        "target": r.target,
        "domain": r.domain,
        "tags": r.tags,
        "profiles": r.profiles,
        "enabled": r.enabled,
        "title": r.title,
        "message": r.message,
        "suggestion": r.suggestion,
        "remedy": r.remedy,
        "source": r.file,
    }


def list_rules(bl: Baseline, profile: str | None = None) -> dict[str, Any]:
    """基线与规则（三种语言的标题、说明、建议与两种写法的修复参考命令）；给出 profile 时只列该基线的规则。"""
    rules = select(bl, profile)[0] if profile else [r for r in bl.rules]
    return {
        "profiles": [
            {**p, "rules": len(select(bl, name)[0]), "chain": expand(bl, name)} for name, p in bl.profiles.items()
        ],
        "profile": profile,
        "total": len(rules),
        "rules": [rule_view(r) for r in rules],
    }


def style_of(family: str | None) -> str:
    """平台族对应的显示风格（修复参考命令的写法）：huawei-vrp8 → huawei，cisco-iosxe → cisco。"""
    from lmesh.core.terms import STYLES

    head = (family or "").split("-")[0]
    return head if head in STYLES else STYLES[0]


def _format(cmd: str, params: dict[str, Any]) -> str:
    out = cmd
    for k, v in params.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def audit_device(
    g: nx.MultiDiGraph, rules: list[rulesmod.Rule], overrides: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """一台设备：每条规则的结论、不符合项（实例、原文行号、证据节点、修复参考命令）与分数。"""
    ev = rulesmod.Evaluator(g)
    by_schema = rulesmod.instances(g)
    style = style_of(g.graph.get("family"))
    results: dict[str, str] = {}
    failures: list[dict[str, Any]] = []
    for r in rules:
        ev.variables = overrides.get(r.file, {})
        applicable = 0
        failed: list[dict[str, Any]] = []
        for n in by_schema.get(r.target, []):
            if r.when is not None and not ev.test(r, n, r.when):
                continue
            applicable += 1
            ev.trace = set()
            if ev.test(r, n, r.assert_):
                continue
            evidence = sorted(x for x in ev.trace if x != n)
            # 行号：实例的第一行（对象声明所在行；单例对象的行很多，只取第一行）加上证据节点的行
            lines: set[int] = set(sorted(g.nodes[n].get("lines") or [])[:1])
            for x in evidence:
                lines.update(g.nodes[x].get("lines") or [])
            params = {"node": n, "key": rulesmod.key_text(g.nodes[n].get("key"))}
            failed.append(
                {
                    "rule": r.id,
                    "severity": r.severity,
                    "node": n,
                    "schema": g.nodes[n].get("schema"),
                    "key": params["key"],
                    "lines": sorted(lines),
                    "evidence": evidence,
                    "message": {"key": f"baseline.{r.id}.message", "params": params},
                    "suggestion": {"key": f"baseline.{r.id}.suggestion", "params": params},
                    "remedy": [_format(c, params) for c in r.remedy.get(style, [])],
                }
            )
        results[r.id] = "na" if applicable == 0 else ("fail" if failed else "pass")
        failures += failed
    failures.sort(key=lambda f: (-rulesmod.SEVERITY_RANK[f["severity"]], f["lines"][:1] or [0], f["rule"], f["node"]))
    sev = {r.id: r.severity for r in rules}
    counts = {s: sum(1 for v in results.values() if v == s) for s in STATUSES}
    failed_sev = {s: 0 for s in rulesmod.SEVERITIES}
    for rid, v in results.items():
        if v == "fail":
            failed_sev[sev[rid]] += 1
    return {
        "device": g.graph.get("device"),
        "profile": g.graph.get("profile"),
        "family": g.graph.get("family"),
        "style": style,
        "score": _score(results, sev),
        "summary": {**counts, "failed_by_severity": failed_sev, "has_errors": failed_sev["error"] > 0},
        "results": results,
        "failures": failures,
    }


def _score(results: dict[str, str], sev: dict[str, str]) -> int | None:
    total = sum(WEIGHTS[sev[rid]] for rid, v in results.items() if v != "na")
    if total == 0:
        return None
    passed = sum(WEIGHTS[sev[rid]] for rid, v in results.items() if v == "pass")
    return round(100 * passed / total)


def audit(graphs: list[nx.MultiDiGraph], bl: Baseline, profile: str = DEFAULT_PROFILE) -> dict[str, Any]:
    """多台设备：矩阵（rules × devices）、每台设备的结果、汇总；文案放在 texts（{键: {语言: 文字}}）。"""
    rules, overrides = select(bl, profile)
    devices = [audit_device(g, rules, overrides) for g in graphs]
    sev = {r.id: r.severity for r in rules}
    by_rule = {r.id: {s: sum(1 for d in devices if d["results"][r.id] == s) for s in STATUSES} for r in rules}
    cells = [(rid, v) for d in devices for rid, v in d["results"].items()]
    total_w = sum(WEIGHTS[sev[rid]] for rid, v in cells if v != "na")
    pass_w = sum(WEIGHTS[sev[rid]] for rid, v in cells if v == "pass")
    texts: dict[str, dict[str, str]] = {}
    for r in rules:
        texts[f"baseline.{r.id}.title"] = r.title
        texts[f"baseline.{r.id}.message"] = r.message
        texts[f"baseline.{r.id}.suggestion"] = r.suggestion
    return {
        "baseline": profile,
        "baseline_info": {**bl.profiles[profile], "chain": expand(bl, profile)},
        "rules": [rule_view(r) for r in rules],
        "matrix": {
            "rules": [r.id for r in rules],
            "devices": [d["device"] for d in devices],
            "cells": [[d["results"][r.id] for d in devices] for r in rules],
        },
        "devices": devices,
        "summary": {
            "devices": len(devices),
            "rules": len(rules),
            "score": round(100 * pass_w / total_w) if total_w else None,
            "pass": sum(d["summary"]["pass"] for d in devices),
            "fail": sum(d["summary"]["fail"] for d in devices),
            "na": sum(d["summary"]["na"] for d in devices),
            "failures": sum(len(d["failures"]) for d in devices),
            "has_errors": any(d["summary"]["has_errors"] for d in devices),
            "by_rule": by_rule,
        },
        "texts": texts,
    }


def render_text(ref: dict[str, Any], lang: str, texts: dict[str, dict[str, str]]) -> str:
    """{key, params} 按语言渲染（与 checks.render_text 相同的规则）。"""
    from lmesh.core import checks

    return checks.render_text(ref, lang, texts)
