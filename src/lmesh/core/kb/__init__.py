"""知识库：纯文本 YAML 文件，命令卡是唯一事实来源。

目录：
    kb.yaml                       知识库版本、功能域
    commands/<族>/views.yaml      平台族的书写习惯与视图树
    commands/<族>/<功能域>.yaml   命令卡
    schema/<功能域>.yaml          统一 Schema 节点与依赖规则
    profiles/<Profile>.yaml       厂商 + 版本：匹配规则、继承、各节点的支持情况与默认值
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from lmesh.core.kb.model import Card, DepRule, Family, Issue, Profile, ProfileEntry, SchemaNode, View

# ruamel 的 YAML 实例不是线程安全的（Web 服务多个请求线程同时读知识库），每个线程用自己的实例
_local = threading.local()


def read_yaml(path: Path) -> Any:
    y = getattr(_local, "yaml", None)
    if y is None:
        y = _local.yaml = YAML(typ="safe", pure=True)
    with path.open("r", encoding="utf-8") as fh:
        return y.load(fh)


@dataclass
class KnowledgeBase:
    root: Path
    version: str = "0.0.0"
    domains: list[str] = field(default_factory=list)
    families: dict[str, Family] = field(default_factory=dict)
    cards: dict[str, Card] = field(default_factory=dict)
    nodes: dict[str, SchemaNode] = field(default_factory=dict)
    deps: list[DepRule] = field(default_factory=list)
    profiles: dict[str, Profile] = field(default_factory=dict)
    load_issues: list[Issue] = field(default_factory=list)

    # ----- 查询 -----

    def cards_of(self, family: str, include_rejected: bool = False) -> list[Card]:
        return [c for c in self.cards.values() if c.family == family and (include_rejected or c.status != "rejected")]

    def children(self, node_id: str | None) -> list[SchemaNode]:
        return [n for n in self.nodes.values() if n.parent == node_id]

    def match_profile(self, vendor: str, version: str) -> str | None:
        """按 Profile 的 match 规则选择：版本正则匹配上的优先；都不匹配时用标了 fallback 的 Profile。"""
        best: tuple[int, str] | None = None
        for p in sorted(self.profiles.values(), key=lambda x: x.id):
            mv, mver = p.match.get("vendor"), p.match.get("version", "")
            if mv and mv != vendor:
                continue
            if mver and version and re.search(mver, version):
                score = 2
            elif str(p.match.get("fallback", "")).lower() in ("true", "1", "yes"):
                score = 1
            else:
                continue
            if best is None or score > best[0]:
                best = (score, p.id)
        return best[1] if best else None

    def lineage(self, profile_id: str) -> list[str]:
        """从自身到最顶层的继承链；有环或缺失时截断（由校验报告）。"""
        chain: list[str] = []
        cur: str | None = profile_id
        while cur and cur in self.profiles and cur not in chain:
            chain.append(cur)
            cur = self.profiles[cur].inherits
        return chain

    def resolve_profile(self, profile_id: str) -> Profile:
        """继承展开：从最顶层往下覆盖，每个条目记录来自哪个 Profile。"""
        base = self.profiles[profile_id]
        merged: dict[str, ProfileEntry] = {}
        side: list[DepRule] = []
        implicit: list[str] = []
        for pid in reversed(self.lineage(profile_id)):
            p = self.profiles[pid]
            implicit += [x for x in p.implicit if x not in implicit]
            for node, e in p.entries.items():
                merged[node] = ProfileEntry(**{**e.__dict__, "origin": pid})
            side.extend(p.side_effects)
        return Profile(
            id=base.id,
            vendor=base.vendor,
            family=base.family,
            file=base.file,
            platform=base.platform,
            software=base.software,
            inherits=base.inherits,
            match=base.match,
            title=base.title,
            entries=merged,
            side_effects=side,
            implicit=implicit,
        )


# ---------- 加载 ----------


def _err(issues: list[Issue], code: str, msg: str, file: Path | str = "") -> None:
    issues.append(Issue("error", code, msg, str(file)))


def load(root: Path) -> KnowledgeBase:
    """读取整个知识库。格式错误记入 load_issues，不抛出（校验时统一报告）。"""
    kb = KnowledgeBase(root=root)
    issues = kb.load_issues
    meta_file = root / "kb.yaml"
    if meta_file.exists():
        meta = _safe_read(meta_file, issues) or {}
        kb.version = str(meta.get("kb_version", "0.0.0"))
        kb.domains = list(meta.get("domains", []))
    else:
        _err(issues, "kb.missing_meta", "缺少 kb.yaml", meta_file)

    cmd_root = root / "commands"
    for fam_dir in sorted(p for p in cmd_root.glob("*") if p.is_dir()) if cmd_root.exists() else []:
        _load_family(kb, fam_dir, issues)
    for f in sorted((root / "schema").glob("*.yaml")) if (root / "schema").exists() else []:
        _load_schema(kb, f, issues)
    for f in sorted((root / "profiles").glob("*.yaml")) if (root / "profiles").exists() else []:
        _load_profile(kb, f, issues)
    return kb


def _safe_read(path: Path, issues: list[Issue]) -> Any:
    try:
        return read_yaml(path)
    except Exception as e:  # YAML 语法错误
        _err(
            issues,
            "yaml.syntax",
            f"YAML 格式错误：{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}",
            path,
        )
        return None


def _rel(kb: KnowledgeBase, path: Path) -> str:
    try:
        return path.relative_to(kb.root).as_posix()
    except ValueError:
        return str(path)


def _load_family(kb: KnowledgeBase, d: Path, issues: list[Issue]) -> None:
    views_file = d / "views.yaml"
    if not views_file.exists():
        _err(issues, "family.no_views", f"平台族 {d.name} 缺少 views.yaml", d)
        return
    data = _safe_read(views_file, issues) or {}
    fam = Family(
        id=d.name,
        vendor=str(data.get("vendor", "")),
        separator=str(data.get("separator", "#")),
        end=str(data.get("end", "")),
        indent=int(data.get("indent", 1)),
        negative=str(data.get("negative", "undo")),
        root_view=str(data.get("root_view", "system")),
    )
    for vid, v in (data.get("views") or {}).items():
        v = v or {}
        fam.views[str(vid)] = View(
            id=str(vid),
            parent=v.get("parent"),
            enter=list(v.get("enter", []) or []),
            exit=list(v.get("exit", []) or []),
            title=str(v.get("title", "")),
        )
    kb.families[fam.id] = fam
    for f in sorted(d.glob("*.yaml")):
        if f.name == "views.yaml":
            continue
        doc = _safe_read(f, issues)
        if not doc:
            continue
        domain = str(doc.get("domain", f.stem))
        for raw in doc.get("cards", []) or []:
            try:
                card = Card(
                    id=str(raw["id"]),
                    family=fam.id,
                    domain=domain,
                    syntax=str(raw["syntax"]),
                    view=str(raw.get("view", fam.root_view)),
                    file=_rel(kb, f),
                    undo=raw.get("undo"),
                    enters_view=raw.get("enters_view"),
                    params={str(k): dict(v or {}) for k, v in (raw.get("params") or {}).items()},
                    default=None if raw.get("default") is None else str(raw.get("default")),
                    maps={
                        str(k): (dict(v) if isinstance(v, dict) else str(v)) for k, v in (raw.get("maps") or {}).items()
                    },
                    depends_on=list(raw.get("depends_on") or []),
                    side_effects=list(raw.get("side_effects") or []),
                    source=dict(raw.get("source") or {}),
                    status=str(raw.get("status", "draft")),
                    note=str(raw.get("note", "")),
                )
            except (KeyError, TypeError) as e:
                _err(issues, "card.format", f"命令卡缺少字段 {e}：{raw!r:.80}", f)
                continue
            if card.id in kb.cards:
                _err(issues, "card.duplicate", f"命令卡编号重复：{card.id}", f)
            kb.cards[card.id] = card


def _load_schema(kb: KnowledgeBase, f: Path, issues: list[Issue]) -> None:
    doc = _safe_read(f, issues)
    if not doc:
        return
    domain = str(doc.get("domain", f.stem))
    for nid, raw in (doc.get("nodes") or {}).items():
        raw = raw or {}
        sem = raw.get("semantic", {})
        node = SchemaNode(
            id=str(nid),
            domain=domain,
            parent=raw.get("parent"),
            type=str(raw.get("type", "string")),
            semantic=sem if isinstance(sem, dict) else {"zh-CN": str(sem)},
            key=list(raw.get("key") or []),
            range=raw.get("range"),
            choices=raw.get("choices"),
            ordered=bool(raw.get("ordered", False)),
            ref=raw.get("ref"),
            deprecated=bool(raw.get("deprecated", False)),
            replaced_by=raw.get("replaced_by"),
            status=str(raw.get("status", "draft")),
        )
        if node.id in kb.nodes:
            _err(issues, "node.duplicate", f"Schema 节点重复：{node.id}", f)
        kb.nodes[node.id] = node
    for raw in doc.get("deps") or []:
        try:
            kb.deps.append(
                DepRule(
                    kind=str(raw["kind"]),
                    src=str(raw["from"]),
                    dst=str(raw["to"]),
                    note=str(raw.get("note", "")),
                    profiles=list(raw.get("profiles") or []),
                    domain=domain,
                )
            )
        except (KeyError, TypeError) as e:
            _err(issues, "dep.format", f"依赖规则缺少字段 {e}", f)


def _load_profile(kb: KnowledgeBase, f: Path, issues: list[Issue]) -> None:
    doc = _safe_read(f, issues)
    if not doc:
        return
    try:
        p = Profile(
            id=str(doc["profile"]),
            vendor=str(doc.get("vendor", "")),
            family=str(doc.get("family", "")),
            file=_rel(kb, f),
            platform=str(doc.get("platform", "")),
            software=str(doc.get("software", "")),
            inherits=doc.get("inherits"),
            match={str(k): str(v) for k, v in (doc.get("match") or {}).items()},
            title=str(doc.get("title", "")),
        )
    except KeyError:
        _err(issues, "profile.format", "Profile 缺少 profile 字段", f)
        return
    for node, raw in (doc.get("entries") or {}).items():
        raw = raw or {}
        cards = raw.get("cards", raw.get("card", []))
        p.entries[str(node)] = ProfileEntry(
            node=str(node),
            supported=bool(raw.get("supported", True)),
            default=raw.get("default"),
            show_rule=str(raw.get("show_rule", "hide_when_default")),
            cards=[cards] if isinstance(cards, str) else list(cards or []),
            source=str(raw.get("source", "")),
            verified=str(raw.get("verified", "doc")),
            manual=bool(raw.get("manual", False)),
            when=dict(raw.get("when") or {}),
        )
    for raw in doc.get("side_effects") or []:
        try:
            p.side_effects.append(
                DepRule(
                    kind="side_effect",
                    src=str(raw["from"]),
                    dst=str(raw["to"]),
                    note=str(raw.get("note", "")),
                    profiles=[p.id],
                )
            )
        except (KeyError, TypeError):
            _err(issues, "profile.side_effect", "副作用规则缺少 from / to", f)
    p.implicit = [str(x) for x in (doc.get("implicit") or [])]
    if p.id in kb.profiles:
        _err(issues, "profile.duplicate", f"Profile 重复：{p.id}", f)
    kb.profiles[p.id] = p
