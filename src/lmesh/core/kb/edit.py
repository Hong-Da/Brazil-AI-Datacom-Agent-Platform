"""知识库的界面编辑：Schema 节点、Profile 条目、新建 Profile。

所有修改写入运行时知识库的文件并提交一次（提交说明写明改了什么）；发布前这些提交都算“草稿区”的修改。
写入后重新加载并校验，引入新错误时恢复原文件并报错，知识库不会处在半坏的状态。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap

from lmesh.core.kb import KnowledgeBase, files, load, repo
from lmesh.core.kb.model import NODE_TYPES, SHOW_RULES
from lmesh.core.kb.validate import validate

NODE_FIELDS = (
    "parent",
    "type",
    "key",
    "semantic",
    "range",
    "choices",
    "ordered",
    "ref",
    "deprecated",
    "replaced_by",
    "status",
)
ENTRY_FIELDS = ("supported", "default", "show_rule", "source", "verified", "note", "when")
_ID = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
_PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9.-]{1,80}$")


class EditError(ValueError):
    def __init__(self, key: str, data: Any = None, **fmt: Any):
        super().__init__(key)
        self.key, self.data, self.fmt = key, data, fmt


# ---------- 读取 ----------


def card_credibility(kb: KnowledgeBase, cards: list[str]) -> str:
    """条目的可信度取其命令卡中最高的审核状态；没有命令卡的人工条目算 reviewed。"""
    order = {"verified": 3, "reviewed": 2, "draft": 1, "rejected": 0}
    best = ""
    for cid in cards:
        st = kb.cards[cid].status if cid in kb.cards else ""
        if order.get(st, -1) > order.get(best, -1):
            best = st
    return best or "reviewed"


def schema_tree(kb: KnowledgeBase) -> dict[str, Any]:
    domains: dict[str, dict[str, Any]] = {}
    for d in kb.domains or sorted({n.domain for n in kb.nodes.values()}):
        domains[d] = {"domain": d, "nodes": [], "deps": []}
    for n in sorted(kb.nodes.values(), key=lambda x: x.id):
        dom = domains.setdefault(n.domain, {"domain": n.domain, "nodes": [], "deps": []})
        dom["nodes"].append(
            {
                "id": n.id,
                "parent": n.parent,
                "type": n.type,
                "key": n.key,
                "semantic": n.semantic,
                "range": n.range,
                "choices": n.choices,
                "ordered": n.ordered,
                "ref": n.ref,
                "deprecated": n.deprecated,
                "replaced_by": n.replaced_by,
                "status": n.status,
                "children": sum(1 for m in kb.nodes.values() if m.parent == n.id),
            }
        )
    for r in kb.deps:
        dom = domains.get(r.domain) or next(iter(domains.values()))
        dom["deps"].append({"kind": r.kind, "from": r.src, "to": r.dst, "note": r.note, "profiles": r.profiles})
    return {
        "kb_version": kb.version,
        "node_types": sorted(NODE_TYPES),
        "domains": list(domains.values()),
        "profiles": sorted(kb.profiles),
    }


def node_usage(kb: KnowledgeBase, node_id: str) -> dict[str, Any]:
    """删除前检查：子节点、引用它的节点、依赖规则、Profile 条目、映射到它的命令卡。"""
    children = sorted(n.id for n in kb.nodes.values() if n.parent == node_id)
    refs = sorted(n.id for n in kb.nodes.values() if n.ref == node_id or n.replaced_by == node_id)
    deps = [f"{r.kind}: {r.src} → {r.dst}" for r in kb.deps if node_id in (r.src, r.dst)]
    profiles = sorted(p.id for p in kb.profiles.values() if node_id in p.entries and not p.entries[node_id].manual)
    manual = sorted(p.id for p in kb.profiles.values() if node_id in p.entries and p.entries[node_id].manual)
    cards = []
    for c in kb.cards.values():
        for target in (c.maps or {}).values():
            text = target if isinstance(target, str) else " ".join(map(str, target.values()))
            if node_id in re.split(r"[\s|{}=,]+", text):
                cards.append(c.id)
                break
    for c in kb.cards.values():
        if c.id not in cards and any(_target_node(k) == node_id for k in (c.maps or {})):
            cards.append(c.id)
    blocking = bool(children or refs or deps or profiles or manual or cards)
    return {
        "node": node_id,
        "children": children,
        "referenced_by": refs,
        "deps": deps,
        "profiles": profiles,
        "manual_entries": manual,
        "cards": sorted(cards),
        "blocking": blocking,
    }


def _target_node(target: str) -> str:
    """映射目标 `a.b{k=v}.c` → `a.b.c`。"""
    return re.sub(r"\{[^}]*\}", "", target.split("|")[0]).strip()


def profile_rows(kb: KnowledgeBase, device_counts: dict[str, int] | None = None) -> list[dict[str, Any]]:
    total = len(kb.nodes) or 1
    rows = []
    for pid in sorted(kb.profiles):
        p = kb.profiles[pid]
        r = kb.resolve_profile(pid)
        cred = {"draft": 0, "reviewed": 0, "verified": 0}
        for e in r.entries.values():
            c = card_credibility(kb, e.cards) if not e.manual else "reviewed"
            if c in cred:
                cred[c] += 1
        filled = sum(1 for nid in kb.nodes if nid in r.entries)
        rows.append(
            {
                "id": pid,
                "title": p.title,
                "vendor": p.vendor,
                "family": p.family,
                "platform": p.platform,
                "software": p.software,
                "inherits": p.inherits,
                "match": p.match,
                "own_entries": len(p.entries),
                "entries": len(r.entries),
                "coverage": round(filled / total, 4),
                "unfilled": total - filled,
                "credibility": cred,
                "devices": (device_counts or {}).get(pid, 0),
                "file": p.file,
            }
        )
    return rows


def profile_detail(kb: KnowledgeBase, pid: str) -> dict[str, Any]:
    if pid not in kb.profiles:
        raise EditError("kb.profile_unknown", profile=pid)
    p = kb.profiles[pid]
    r = kb.resolve_profile(pid)
    entries = []
    for nid in sorted(kb.nodes):
        n = kb.nodes[nid]
        e = r.entries.get(nid)
        row: dict[str, Any] = {
            "node": nid,
            "domain": n.domain,
            "type": n.type,
            "semantic": n.semantic,
            "deprecated": n.deprecated,
            "state": "unfilled" if e is None else ("supported" if e.supported else "unsupported"),
        }
        if e is not None:
            row.update(
                default=e.default,
                show_rule=e.show_rule,
                cards=e.cards,
                source=e.source,
                verified=e.verified,
                manual=e.manual,
                origin=e.origin or pid,
                inherited=bool(e.origin and e.origin != pid),
                credibility=card_credibility(kb, e.cards) if not e.manual else "reviewed",
            )
        entries.append(row)
    return {
        "profile": {
            "id": pid,
            "title": p.title,
            "vendor": p.vendor,
            "family": p.family,
            "platform": p.platform,
            "software": p.software,
            "inherits": p.inherits,
            "match": p.match,
            "side_effects": [{"from": s.src, "to": s.dst, "note": s.note} for s in p.side_effects],
            "implicit": p.implicit,
            "lineage": kb.lineage(pid),
        },
        "show_rules": sorted(SHOW_RULES),
        "entries": entries,
    }


def profile_compare(kb: KnowledgeBase, a: str, b: str) -> dict[str, Any]:
    for pid in (a, b):
        if pid not in kb.profiles:
            raise EditError("kb.profile_unknown", profile=pid)
    ra, rb = kb.resolve_profile(a), kb.resolve_profile(b)
    rows = []
    counts = {"same": 0, "only_a": 0, "only_b": 0, "default": 0, "unfilled": 0}
    for nid in sorted(kb.nodes):
        ea, eb = ra.entries.get(nid), rb.entries.get(nid)
        sa = "unfilled" if ea is None else ("supported" if ea.supported else "unsupported")
        sb = "unfilled" if eb is None else ("supported" if eb.supported else "unsupported")
        if "unfilled" in (sa, sb) and sa != sb:
            kind = "unfilled"
        elif sa == "supported" and sb != "supported":
            kind = "only_a"
        elif sb == "supported" and sa != "supported":
            kind = "only_b"
        elif sa == sb == "supported" and ea is not None and eb is not None and ea.default != eb.default:
            kind = "default"
        else:
            kind = "same"
        counts[kind] += 1
        rows.append(
            {
                "node": nid,
                "domain": kb.nodes[nid].domain,
                "semantic": kb.nodes[nid].semantic,
                "a": {"state": sa, "default": ea.default if ea else None},
                "b": {"state": sb, "default": eb.default if eb else None},
                "kind": kind,
            }
        )
    return {"a": a, "b": b, "counts": counts, "rows": rows}


# ---------- 写入 ----------


def _current(root: Path) -> KnowledgeBase:
    """编辑前的知识库：用按修改时间缓存的那份（不必每次重新加载几千张命令卡）。"""
    from lmesh.core import analysis

    return analysis.load_kb(root)


def _commit_checked(root: Path, path: Path, before: bytes | None, message: str) -> None:
    """写入后校验：与写入前相比新增了错误就恢复原文件；没问题就提交，并把新加载的知识库放进缓存。

    写入前的错误取缓存（与 load_kb 同一个键），写入后只完整加载一次。"""
    from lmesh.core import analysis

    old_errors = _pre_errors.pop(str(path), None)
    if old_errors is None:
        old_errors = set()
    kb = load(root)
    errors = {(i.code, i.message) for i in validate(kb) if i.level == "error"}
    new = errors - old_errors
    if new:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(before)
        raise EditError("kb.edit_invalid", sorted(m for _, m in new))
    if (root / ".git").exists():
        repo.commit_all(root, message)
    analysis.prime(root, kb, errors)


# 写入前的校验错误：由各编辑函数在写文件之前记录（键为要写的文件），_commit_checked 用来比较
_pre_errors: dict[str, set[tuple[str, str]]] = {}


def _remember_errors(root: Path, path: Path) -> None:
    from lmesh.core import analysis

    _pre_errors[str(path)] = analysis.validation_errors(root)


def _clean_node(body: dict[str, Any]) -> CommentedMap:
    out = CommentedMap()
    for k in NODE_FIELDS:
        v = body.get(k)
        if v in (None, "", [], {}) or (k in ("ordered", "deprecated") and v is False):
            continue
        out[k] = v
    return out


@repo.locked
def upsert_node(root: Path, node_id: str, body: dict[str, Any]) -> dict[str, Any]:
    if not _ID.match(node_id):
        raise EditError("kb.node_id_invalid", node=node_id)
    kb = _current(root)
    if body.get("type") not in NODE_TYPES:
        raise EditError("kb.node_type_invalid", type=str(body.get("type")))
    parent = body.get("parent")
    if parent and parent not in kb.nodes:
        raise EditError("kb.node_parent_missing", parent=str(parent))
    existing = kb.nodes.get(node_id)
    domain = existing.domain if existing else (kb.nodes[parent].domain if parent else node_id.split(".")[0])
    path = root / "schema" / f"{domain}.yaml"
    before = path.read_bytes() if path.exists() else None
    doc = files.load_rt(path) if path.exists() else CommentedMap(domain=domain, nodes=CommentedMap())
    doc.setdefault("nodes", CommentedMap())
    doc["nodes"][node_id] = _clean_node(body)
    _remember_errors(root, path)
    files.dump_rt(path, doc)
    _commit_checked(root, path, before, f"{'修改' if existing else '新增'} Schema 节点 {node_id}")
    return {"node": node_id, "domain": domain, "created": existing is None}


@repo.locked
def delete_node(root: Path, node_id: str) -> dict[str, Any]:
    kb = _current(root)
    if node_id not in kb.nodes:
        raise EditError("kb.node_unknown", node=node_id)
    usage = node_usage(kb, node_id)
    if usage["blocking"]:
        raise EditError("kb.node_in_use", usage, node=node_id)
    path = root / "schema" / f"{kb.nodes[node_id].domain}.yaml"
    before = path.read_bytes()
    doc = files.load_rt(path)
    del doc["nodes"][node_id]
    _remember_errors(root, path)
    files.dump_rt(path, doc)
    _commit_checked(root, path, before, f"删除 Schema 节点 {node_id}")
    return {"node": node_id, "deleted": True}


@repo.locked
def set_entry(root: Path, pid: str, node_id: str, body: dict[str, Any]) -> dict[str, Any]:
    kb = _current(root)
    if pid not in kb.profiles:
        raise EditError("kb.profile_unknown", profile=pid)
    if node_id not in kb.nodes:
        raise EditError("kb.node_unknown", node=node_id)
    if body.get("show_rule") and body["show_rule"] not in SHOW_RULES:
        raise EditError("kb.show_rule_invalid", rule=str(body["show_rule"]))
    path = root / kb.profiles[pid].file
    before = path.read_bytes()
    doc = files.load_rt(path)
    if not isinstance(doc.get("entries"), dict):
        doc["entries"] = CommentedMap()
    entry = doc["entries"].get(node_id)
    if entry is None:
        entry = CommentedMap()
        inherited = kb.resolve_profile(pid).entries.get(node_id)
        if inherited is not None:  # 覆盖继承来的条目：以父条目为底（含命令卡），再改要改的字段
            for k in ("supported", "default", "show_rule", "source", "verified"):
                v = getattr(inherited, k)
                if v not in (None, "", []):
                    entry[k] = v
            if inherited.cards:
                entry["cards"] = list(inherited.cards)
    for k in ENTRY_FIELDS:
        if k in body:
            if body[k] is None or body[k] == "":
                entry.pop(k, None)
            else:
                entry[k] = body[k]
    entry["manual"] = True
    doc["entries"][node_id] = entry
    _remember_errors(root, path)
    files.dump_rt(path, doc)
    _commit_checked(root, path, before, f"Profile {pid}：人工修改 {node_id}")
    return {"profile": pid, "node": node_id}


@repo.locked
def clear_entry(root: Path, pid: str, node_id: str) -> dict[str, Any]:
    """删除 Profile 自己的条目（继承来的条目在父 Profile 中修改）。"""
    kb = _current(root)
    if pid not in kb.profiles:
        raise EditError("kb.profile_unknown", profile=pid)
    path = root / kb.profiles[pid].file
    before = path.read_bytes()
    doc = files.load_rt(path)
    if node_id not in (doc.get("entries") or {}):
        raise EditError("kb.entry_not_own", node=node_id, profile=pid)
    del doc["entries"][node_id]
    _remember_errors(root, path)
    files.dump_rt(path, doc)
    _commit_checked(root, path, before, f"Profile {pid}：删除条目 {node_id}")
    return {"profile": pid, "node": node_id, "deleted": True}


@repo.locked
def create_profile(root: Path, body: dict[str, Any]) -> dict[str, Any]:
    kb = _current(root)
    pid = str(body.get("id") or "").strip()
    if not _PROFILE_ID.match(pid):
        raise EditError("kb.profile_id_invalid", profile=pid)
    if pid in kb.profiles:
        raise EditError("kb.profile_exists", profile=pid)
    family = str(body.get("family") or "")
    inherits = body.get("inherits") or None
    if inherits:
        if inherits not in kb.profiles:
            raise EditError("kb.profile_unknown", profile=str(inherits))
        family = family or kb.profiles[inherits].family
    if family not in kb.families:
        raise EditError("kb.family_unknown", family=family)
    vendor = str(body.get("vendor") or kb.families[family].vendor)
    version = str(body.get("version") or "").strip()
    if version:
        try:
            re.compile(version)
        except re.error as e:
            raise EditError("kb.version_regex_invalid", version=version) from e
    doc = CommentedMap()
    doc["profile"] = pid
    doc["title"] = str(body.get("title") or pid)
    doc["vendor"] = vendor
    doc["family"] = family
    for k in ("platform", "software"):
        if body.get(k):
            doc[k] = str(body[k])
    if inherits:
        doc["inherits"] = inherits
    doc["match"] = CommentedMap(vendor=vendor, **({"version": version} if version else {}))
    doc["entries"] = CommentedMap()
    path = root / "profiles" / f"{pid}.yaml"
    _remember_errors(root, path)
    files.dump_rt(path, doc)
    _commit_checked(root, path, None, f"新建 Profile {pid}")
    return {"profile": pid, "file": f"profiles/{pid}.yaml"}
