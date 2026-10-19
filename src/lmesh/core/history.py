"""版本历史（M5-2）：每次导入保存快照，按时间查看配置变化。

快照就是一个配置版本（config_versions 一行）：脱敏后的原文、当时建的图（gzip 压缩的 JSON，graph_gz）、
解析用的知识库版本、内容指纹（content_hash）。每次导入另记一条导入记录（config_imports）；内容与最新快照相同的
重复导入不存新快照，只记导入记录（时间线上合并显示 ×N，决策 D-0091）。

保留策略：配置项 history.keep（默认 50；0 表示不限）——每台设备保留最近 keep 个快照，贴了标签的永久保留，
最新的快照总是保留。两个时间点的对比默认用快照当时保存的图（能复现当时的结论）；两边知识库版本不同时提示，
可以按当前知识库临时重建再比较（快照本身不变，决策 D-0090）。差异按对象归并；只是写法不同、有效值相同的变化
（显式写了默认值、掩码与前缀长度两种写法等）单独计数，默认不列出（决策 D-0092）。
"""

from __future__ import annotations

import contextlib
import difflib
import gzip
import hashlib
import json
import re
from collections import defaultdict
from typing import Any

import networkx as nx
from sqlalchemy import delete, select

from lmesh.core import compare, store
from lmesh.core.kb import KnowledgeBase
from lmesh.core.store.models import ConfigImport, ConfigVersion, Device, iso

DEFAULT_KEEP = 50
TAG_MAX = 200
SOURCE_KINDS = ("file", "dir", "zip", "api", "migrate", "other")
ITEM_KINDS = ("added", "modified", "removed", "renamed")
_WS = re.compile(r"\s+")


class HistoryError(ValueError):
    def __init__(self, key: str, kind: str = "param", **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.fmt = key, kind, fmt


# ---------------------------------------------------------------- 快照存取


def content_hash(text: str) -> str:
    """内容指纹：脱敏后原文的 SHA-256（行尾空白与末尾空行不计）。"""
    norm = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n")).rstrip("\n")
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def dump_graph(g: nx.MultiDiGraph) -> bytes:
    """图 → gzip 压缩的 JSON（不含解析器的语句对象；对比、检查、导出、查询都不需要它们）。"""
    data = nx.node_link_data(g, edges="edges")
    data["graph"] = {k: v for k, v in g.graph.items() if not k.startswith("_") and k != "statements"}
    raw = json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))
    return gzip.compress(raw.encode("utf-8"), compresslevel=6)


def load_graph(blob: bytes) -> nx.MultiDiGraph:
    data = json.loads(gzip.decompress(blob).decode("utf-8"))
    g = nx.node_link_graph(data, directed=True, multigraph=True, edges="edges")
    return g  # type: ignore[no-any-return]


def _graph_nodes(blob: bytes | None) -> int | None:
    if not blob:
        return None
    try:
        return int(load_graph(blob).number_of_nodes())
    except Exception:  # 损坏的快照图：当作没有保存
        return None


# ---------------------------------------------------------------- 导入时调用


def find_duplicate(s: Any, device_id: int, digest: str) -> ConfigVersion | None:
    """设备最新的快照与这份内容相同时返回它（重复导入）；否则 None。"""
    latest = s.scalar(
        select(ConfigVersion).where(ConfigVersion.device_id == device_id).order_by(ConfigVersion.id.desc()).limit(1)
    )
    if latest is None:
        return None
    if not latest.content_hash:
        latest.content_hash = content_hash(latest.raw_text)
    return latest if latest.content_hash == digest else None


def add_import(
    s: Any, device_id: int, version_id: int, source_name: str, source_kind: str, actor: str, duplicate: bool
) -> None:
    s.add(
        ConfigImport(
            device_id=device_id,
            version_id=version_id,
            source_name=source_name[:400],
            source_kind=source_kind if source_kind in SOURCE_KINDS else "other",
            actor=actor[:200],
            duplicate=duplicate,
        )
    )


def after_import(
    db_url: str, version_ids: list[int], kb: KnowledgeBase | None, keep: int | None
) -> dict[int, list[int]]:
    """新快照导入后：算出相对上一个快照的变化计数（时间线用），再按保留策略清理。返回 {设备: 删除的快照}。"""
    devices: set[int] = set()
    for vid in version_ids:
        with store.session(db_url) as s:
            ver = s.get(ConfigVersion, vid)
            if ver is None:
                continue
            devices.add(ver.device_id)
        if kb is not None:
            with contextlib.suppress(Exception):  # 变化计数只用于展示，失败时留空，下次查看时间线再算
                ensure_summary(db_url, vid, kb)
    out = {}
    for d in devices:
        removed = apply_retention(db_url, d, DEFAULT_KEEP if keep is None else keep)
        if removed:
            out[d] = removed
    return out


def apply_retention(db_url: str, device_id: int, keep: int) -> list[int]:
    """保留最近 keep 个快照 + 贴了标签的 + 最新的；keep 为 0 时不清理。返回删除的快照编号。"""
    if keep <= 0:
        return []
    with store.session(db_url) as s:
        rows = list(
            s.execute(
                select(ConfigVersion.id, ConfigVersion.tag)
                .where(ConfigVersion.device_id == device_id)
                .order_by(ConfigVersion.id.desc())
            )
        )
        drop = [vid for i, (vid, tag) in enumerate(rows) if i >= keep and not tag]
        if drop:
            s.execute(delete(ConfigImport).where(ConfigImport.version_id.in_(drop)))
            s.execute(delete(ConfigVersion).where(ConfigVersion.id.in_(drop)))
        return drop


# ---------------------------------------------------------------- 取图


def _snapshot_graph(db_url: str, version_id: int, kb: KnowledgeBase, rebuild: bool) -> tuple[nx.MultiDiGraph, str]:
    """快照的图：默认用保存的图；没有保存（旧数据）或要求重建时按当前知识库重新解析原文。返回 (图, 来源)。"""
    from lmesh.core import analysis
    from lmesh.core import graph as graphmod

    with store.session(db_url) as s:
        ver = s.get(ConfigVersion, version_id)
        if ver is None:
            raise HistoryError("history.snapshot_not_found", "not_found", snapshot=version_id)
        dev = s.get(Device, ver.device_id)
        assert dev is not None
        blob, text, profile, name = ver.graph_gz, ver.raw_text, dev.profile, dev.name
    if blob and not rebuild:
        try:
            return load_graph(blob), "stored"
        except Exception:
            pass
    try:
        res = analysis.parse_text(text, kb, profile if profile in kb.profiles else None)
    except analysis.AnalysisError as e:
        raise HistoryError(str(e), profile=profile or "") from e
    return graphmod.build(res.parsed, kb, res.profile, name), "rebuilt"


def ensure_summary(db_url: str, version_id: int, kb: KnowledgeBase) -> dict[str, Any]:
    """快照的节点数与相对上一个快照的变化计数；没有算过时计算并保存。"""
    with store.session(db_url) as s:
        ver = s.get(ConfigVersion, version_id)
        if ver is None:
            raise HistoryError("history.snapshot_not_found", "not_found", snapshot=version_id)
        if ver.change_summary:
            return dict(ver.change_summary)
        prev_id = s.scalar(
            select(ConfigVersion.id)
            .where(ConfigVersion.device_id == ver.device_id, ConfigVersion.id < ver.id)
            .order_by(ConfigVersion.id.desc())
            .limit(1)
        )
    g_b, _ = _snapshot_graph(db_url, version_id, kb, False)
    summary: dict[str, Any] = {"nodes": g_b.number_of_nodes(), "vs_previous": None}
    if prev_id is not None:
        g_a, _ = _snapshot_graph(db_url, prev_id, kb, False)
        if g_a.graph.get("family") == g_b.graph.get("family"):
            d = _diff_graphs(g_a, g_b, kb, _text(db_url, prev_id), _text(db_url, version_id))
            summary["vs_previous"] = {k: d["summary"][k] for k in (*ITEM_KINDS, "noneff", "fmt")}
    with store.session(db_url) as s:
        ver = s.get(ConfigVersion, version_id)
        if ver is not None:
            ver.change_summary = summary
    return summary


def _text(db_url: str, version_id: int) -> str:
    with store.session(db_url) as s:
        ver = s.get(ConfigVersion, version_id)
        return ver.raw_text if ver is not None else ""


# ---------------------------------------------------------------- 时间线


def _snap_rows(db_url: str, device_id: int) -> tuple[Device, list[ConfigVersion], dict[int, list[ConfigImport]]]:
    from lmesh.core import projects

    with store.session(db_url) as s:
        dev = s.get(Device, device_id)
        if dev is None or not projects.visible(s, device_id):
            raise HistoryError("history.device_not_found", "not_found", device=device_id)
        vers = list(
            s.scalars(select(ConfigVersion).where(ConfigVersion.device_id == device_id).order_by(ConfigVersion.id))
        )
        imps: dict[int, list[ConfigImport]] = defaultdict(list)
        for im in s.scalars(select(ConfigImport).where(ConfigImport.device_id == device_id).order_by(ConfigImport.id)):
            imps[im.version_id].append(im)
        s.expunge_all()
        return dev, vers, imps


def _snap_info(ver: ConfigVersion, seq: int, imps: list[ConfigImport], current_kb: str, latest: bool) -> dict[str, Any]:
    imports = [
        {
            "id": im.id,
            "imported_at": iso(im.imported_at),
            "source_kind": im.source_kind,
            "source_name": im.source_name,
            "actor": im.actor,
            "duplicate": im.duplicate,
        }
        for im in imps
    ]
    if not imports:  # 版本历史上线前导入的版本：用版本本身的信息补一条
        imports = [
            {
                "id": None,
                "imported_at": iso(ver.collected_at),
                "source_kind": "file",
                "source_name": ver.source_name,
                "actor": "",
                "duplicate": False,
            }
        ]
    summary = ver.change_summary or {}
    return {
        "id": ver.id,
        "seq": seq,
        "collected_at": iso(ver.collected_at),
        "source_name": ver.source_name,
        "imports": imports,
        "import_count": len(imports),
        "kb_version": ver.kb_version,
        "kb_current": ver.kb_version == current_kb,
        "fingerprint": ver.content_hash or content_hash(ver.raw_text),
        "tag": ver.tag,
        "lines": len(ver.raw_text.split("\n")),
        "nodes": summary.get("nodes"),
        "graph_stored": bool(ver.graph_gz),
        "vs_previous": summary.get("vs_previous"),
        "latest": latest,
    }


def timeline(db_url: str, device_id: int, kb: KnowledgeBase, keep: int = DEFAULT_KEEP) -> dict[str, Any]:
    """设备的快照时间线（旧的在前）：导入记录、知识库版本、指纹、标签、相对上一快照的变化计数。"""
    dev, vers, imps = _snap_rows(db_url, device_id)
    missing = [v.id for v in vers if not v.change_summary]
    for vid in missing:
        try:
            ensure_summary(db_url, vid, kb)
        except HistoryError:
            continue
    if missing:
        dev, vers, imps = _snap_rows(db_url, device_id)
    snaps = [_snap_info(v, i + 1, imps.get(v.id, []), kb.version, i == len(vers) - 1) for i, v in enumerate(vers)]
    return {
        "device": _dev_info(dev),
        "snapshots": snaps,
        "count": len(snaps),
        "imports": sum(s["import_count"] for s in snaps),
        "tagged": sum(1 for s in snaps if s["tag"]),
        "keep": keep,
        "kb_version": kb.version,
    }


def _dev_info(dev: Device) -> dict[str, Any]:
    return {
        "id": dev.id,
        "name": dev.name,
        "vendor": dev.vendor,
        "sw_version": dev.sw_version,
        "profile": dev.profile,
    }


def resolve_snapshot(db_url: str, device_id: int, ref: str | int | None, default: str = "latest") -> int:
    """快照引用 → 版本编号：版本编号（int、数字字符串或 v<编号>）；latest / prev / #<序号> / seq:<序号> / tag:<标签>。"""
    _, vers, _ = _snap_rows(db_url, device_id)
    if not vers:
        raise HistoryError("history.no_snapshots", "not_found", device=device_id)
    r = default if ref in (None, "") else ref
    if isinstance(r, int):
        if not any(v.id == r for v in vers):
            raise HistoryError("history.snapshot_not_found", "not_found", snapshot=r)
        return r
    text = str(r).strip()
    if text == "latest":
        return vers[-1].id
    if text in ("prev", "previous"):
        return vers[-2].id if len(vers) > 1 else vers[-1].id
    if text.startswith(("#", "seq:")):
        n = text.lstrip("#").removeprefix("seq:")
        if n.isdigit() and 1 <= int(n) <= len(vers):
            return vers[int(n) - 1].id
        raise HistoryError("history.snapshot_not_found", "not_found", snapshot=text)
    if text.startswith("tag:"):
        hit = [v for v in vers if v.tag == text[4:]]
        if hit:
            return hit[-1].id
        raise HistoryError("history.snapshot_not_found", "not_found", snapshot=text)
    if text.isdigit():
        return resolve_snapshot(db_url, device_id, int(text))
    if text[:1] in ("v", "V") and text[1:].isdigit():
        return resolve_snapshot(db_url, device_id, int(text[1:]))
    raise HistoryError("history.snapshot_not_found", "not_found", snapshot=text)


def set_tag(db_url: str, device_id: int, version_id: int, tag: str | None) -> dict[str, Any]:
    """给快照贴标签（永久保留）；tag 为空时去掉标签。"""
    tag = (tag or "").strip() or None
    if tag is not None and len(tag) > TAG_MAX:
        raise HistoryError("history.tag_too_long", max=TAG_MAX)
    from lmesh.core import projects

    with store.session(db_url) as s:
        ver = s.get(ConfigVersion, version_id)
        if ver is None or ver.device_id != device_id or not projects.visible(s, device_id):
            raise HistoryError("history.snapshot_not_found", "not_found", snapshot=version_id)
        dev = s.get(Device, device_id)
        sc = projects.current()
        if dev is not None and dev.project_id is None and sc is not None and not sc.identity.is_admin:
            # 公共设备的快照是共享的：项目里只能看，标签由管理员在公共设备库里贴
            raise HistoryError("history.public_readonly", "forbidden", device=device_id)
        ver.tag = tag
        return {"id": ver.id, "device_id": device_id, "tag": tag}


# ---------------------------------------------------------------- 对比


def _owner(cid: str, ca: Any, cb: Any) -> str:
    """属性 / 未映射命令所属的对象：沿规范编号向上找最近的对象（跳过编号为 _ 的参数容器）。"""
    cur = cid
    while True:
        cur = _parent_cid(cur)
        if not cur:
            return ""
        it = ca.items.get(cur) or cb.items.get(cur)
        if it is not None and it.kind == "object" and str(it.key) != "_":
            return cur


def _parent_cid(cid: str) -> str:
    depth = 0
    for i in range(len(cid) - 1, -1, -1):
        ch = cid[i]
        if ch == "]":
            depth += 1
        elif ch == "[":
            depth -= 1
        elif ch == "/" and depth == 0:
            return cid[:i]
    return ""


def _short_field(cid: str, owner: str) -> str:
    return cid[len(owner) + 1 :] if owner and cid.startswith(owner + "/") else cid


def _line_owner(g: nx.MultiDiGraph) -> dict[int, str]:
    """配置行号 → 最具体的节点（属性、未映射命令、原文行优先于对象）。"""
    rank = {"attr": 3, "ext": 3, "raw": 2, "unknown": 2, "object": 1}
    best: dict[int, tuple[int, str]] = {}
    for n, d in g.nodes(data=True):
        r = rank.get(str(d.get("kind")), 0)
        for ln in d.get("lines") or []:
            if ln not in best or r > best[ln][0]:
                best[ln] = (r, n)
    return {k: v[1] for k, v in best.items()}


def text_diff(
    a: str, b: str, ga: nx.MultiDiGraph | None = None, gb: nx.MultiDiGraph | None = None, context: int = 3
) -> dict[str, Any]:
    """两份原文的行差异（分块，每行带行号与所属节点）；只是缩进、空白或位置变化的行标为 fmt。"""
    la, lb = a.split("\n"), b.split("\n")
    sm = difflib.SequenceMatcher(None, la, lb, autojunk=False)
    oa = _line_owner(ga) if ga is not None else {}
    ob = _line_owner(gb) if gb is not None else {}
    removed_norm = [
        _WS.sub(" ", x.strip())
        for tag, i1, i2, _, _ in sm.get_opcodes()
        if tag in ("replace", "delete")
        for x in la[i1:i2]
    ]
    added_norm = [
        _WS.sub(" ", x.strip())
        for tag, _, _, j1, j2 in sm.get_opcodes()
        if tag in ("replace", "insert")
        for x in lb[j1:j2]
    ]
    rset, aset = set(removed_norm), set(added_norm)
    hunks = []
    stats = {"added": 0, "removed": 0, "fmt": 0}

    def fmt_line(text: str, other: set[str]) -> bool:
        n = _WS.sub(" ", text.strip())
        return n in other or n in ("", "#", "!")

    for group in sm.get_grouped_opcodes(context):
        lines = []
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for k in range(i2 - i1):
                    lines.append(
                        {
                            "op": "equal",
                            "a": i1 + k + 1,
                            "b": j1 + k + 1,
                            "text": la[i1 + k],
                            "node": ob.get(j1 + k + 1),
                        }
                    )
                continue
            for k in range(i1, i2):
                f = fmt_line(la[k], aset)
                stats["fmt" if f else "removed"] += 1
                lines.append({"op": "del", "a": k + 1, "b": None, "text": la[k], "node": oa.get(k + 1), "fmt": f})
            for k in range(j1, j2):
                f = fmt_line(lb[k], rset)
                stats["fmt" if f else "added"] += 1
                lines.append({"op": "add", "a": None, "b": k + 1, "text": lb[k], "node": ob.get(k + 1), "fmt": f})
        first, last = group[0], group[-1]
        hunks.append(
            {
                "a_start": first[1] + 1,
                "a_len": last[2] - first[1],
                "b_start": first[3] + 1,
                "b_len": last[4] - first[3],
                "lines": lines,
            }
        )
    return {"hunks": hunks, "stats": stats, "equal": not hunks}


def _diff_graphs(
    ga: nx.MultiDiGraph,
    gb: nx.MultiDiGraph,
    kb: KnowledgeBase,
    text_a: str,
    text_b: str,
    domain: str | None = None,
    context: int = 3,
) -> dict[str, Any]:
    """两张快照图的差异：compare 的逐节点结果按对象归并，另算只是写法不同的变化与只是格式不同的行。"""
    res = compare.compare(compare.Side(ga, "a"), compare.Side(gb, "b"), kb, domain=domain)
    sch = compare._Schema(kb)
    ca = compare._Canonicalizer(ga, kb, sch).run()
    cb = compare._Canonicalizer(gb, kb, sch).run()
    items: dict[str, dict[str, Any]] = {}

    def item(cid: str, kind: str, d: dict[str, Any] | None = None) -> dict[str, Any]:
        it = ca.items.get(cid) or cb.items.get(cid)
        if cid not in items:
            items[cid] = {
                "object": cid,
                "schema": it.schema if it else (d or {}).get("schema"),
                "domain": it.domain if it else (d or {}).get("domain", ""),
                "key": it.key if it else None,
                "kind": kind,
                "parent": _owner(cid, ca, cb) if it else "",
                "from": None,
                "to": None,
                "lines_a": ca.subtree_lines.get(cid, []),
                "lines_b": cb.subtree_lines.get(cid, []),
                "changes": [],
            }
        return items[cid]

    for d in res["diffs"]:
        if d["node_kind"] == "object" and d["kind"] in ("added", "removed"):
            item(d["node"], d["kind"], d)
            continue
        if d["kind"] == "renamed":
            it = item(d["node"], "renamed", d)
            it["kind"], it["from"], it["to"] = "renamed", d["from"], d["to"]
            continue
        owner = _owner(d["node"], ca, cb) if d["node_kind"] != "ext" else _parent_cid(d["node"])
        it = item(owner, "modified", d) if owner else item(d["node"], "modified", d)
        it["changes"].append(
            {
                "node": d["node"],
                "field": _short_field(d["node"], owner),
                "schema": d["schema"],
                "node_kind": d["node_kind"],
                "kind": d["kind"],
                "a": d["a"],
                "b": d["b"],
            }
        )

    # 只是写法不同：两边都有、有效值相同，但一边是显式写的默认值，或原始写法不同（掩码 / 前缀长度、接口名缩写……）
    noneff = []
    for cid in sorted(set(ca.items) & set(cb.items)):
        ia, ib = ca.items[cid], cb.items[cid]
        if ia.kind != "attr" or ia.value != ib.value:
            continue
        if domain and ia.domain != domain:
            continue
        reason = None
        if {ia.origin, ib.origin} == {"explicit", "default"}:
            reason = "default_explicit"
        elif ia.origin == ib.origin == "explicit":
            ra, rb = ga.nodes[ia.node].get("raw"), gb.nodes[ib.node].get("raw")
            if ra is not None and rb is not None and json.dumps(ra, default=str) != json.dumps(rb, default=str):
                reason = "spelling"
        if reason:
            noneff.append(
                {
                    "node": cid,
                    "schema": ia.schema,
                    "domain": ia.domain,
                    "object": _owner(cid, ca, cb),
                    "reason": reason,
                    "a": {
                        "value": ia.value,
                        "origin": ia.origin,
                        "raw": ga.nodes[ia.node].get("raw"),
                        "lines": ia.lines,
                    },
                    "b": {
                        "value": ib.value,
                        "origin": ib.origin,
                        "raw": gb.nodes[ib.node].get("raw"),
                        "lines": ib.lines,
                    },
                }
            )
    td = text_diff(text_a, text_b, ga, gb, context)
    order = {dm: i for i, dm in enumerate(kb.domains)}
    out_items = sorted(items.values(), key=lambda x: (order.get(x["domain"], 99), x["domain"], x["object"]))
    counts = dict.fromkeys(ITEM_KINDS, 0)
    by_domain: dict[str, dict[str, int]] = {}
    for it in out_items:
        counts[it["kind"]] += 1
        dm = by_domain.setdefault(it["domain"] or "other", {**dict.fromkeys(ITEM_KINDS, 0), "total": 0})
        dm[it["kind"]] += 1
        dm["total"] += 1
    return {
        "items": out_items,
        "noneff": noneff,
        "text": td,
        "compare": {
            "diffs": res["diffs"],
            "renames": res["renames"],
            "default_only": res["default_only"],
            "unknown": res["unknown"],
            "summary": res["summary"],
        },
        "summary": {
            **counts,
            "total": len(out_items),
            "noneff": len(noneff),
            "fmt": td["stats"]["fmt"],
            "by_domain": by_domain,
        },
    }


def diff(
    db_url: str,
    device_id: int,
    kb: KnowledgeBase,
    a: str | int | None = None,
    b: str | int | None = None,
    rebuild: bool = False,
    show_noneff: bool = False,
    domain: str | None = None,
    with_text: bool = True,
    context: int = 3,
) -> dict[str, Any]:
    """两个快照之间的变化（A 较早、B 较晚；默认上一个 → 最新）。

    rebuild：两边都按当前知识库重新解析原文后比较（知识库升级带来的差异就排除了）；
    show_noneff：同时列出只是写法不同的变化（默认只计数）；
    context：原文差异每块前后保留的相同行数（界面取大值，拿到整份原文后在本地折叠 / 展开）。"""
    tl = timeline(db_url, device_id, kb)
    va = resolve_snapshot(db_url, device_id, a, "prev")
    vb = resolve_snapshot(db_url, device_id, b, "latest")
    snaps = {s["id"]: s for s in tl["snapshots"]}
    if snaps[va]["seq"] > snaps[vb]["seq"]:
        va, vb = vb, va
    ga, src_a = _snapshot_graph(db_url, va, kb, rebuild)
    gb, src_b = _snapshot_graph(db_url, vb, kb, rebuild)
    if ga.graph.get("family") != gb.graph.get("family"):
        raise HistoryError("history.family_changed", a=str(ga.graph.get("family")), b=str(gb.graph.get("family")))
    domains = set(kb.domains) | {n.domain for n in kb.nodes.values()}
    if domain and domain not in domains:
        raise HistoryError("history.bad_domain", domain=domain, domains=", ".join(sorted(domains)))
    d = _diff_graphs(ga, gb, kb, _text(db_url, va), _text(db_url, vb), domain, max(0, context))
    kb_a, kb_b = snaps[va]["kb_version"], snaps[vb]["kb_version"]
    out = {
        "device": tl["device"],
        "a": {**snaps[va], "graph": src_a},
        "b": {**snaps[vb], "graph": src_b},
        "kb": {
            "a": kb_a,
            "b": kb_b,
            "current": kb.version,
            "differs": kb_a != kb_b,
            "rebuilt": rebuild,
        },
        "options": {"rebuild": rebuild, "show_noneff": show_noneff, "domain": domain},
        "equal": not d["items"],
        "summary": d["summary"],
        "items": d["items"],
        "noneff": d["noneff"] if show_noneff else [],
        "compare": d["compare"],
    }
    if with_text:
        out["text"] = d["text"]
    return out


# ---------------------------------------------------------------- 对象历史


def object_history(db_url: str, device_id: int, node: str, kb: KnowledgeBase, rebuild: bool = False) -> dict[str, Any]:
    """一个对象（规范编号，例如 interface[GigabitEthernet0/0/0]、bgp.instance[64512]/peer[10.0.0.1]）在每个快照中的取值。"""
    tl = timeline(db_url, device_id, kb)
    sch = compare._Schema(kb)
    rows = []
    fields: list[str] = []
    prev: dict[str, Any] | None = None
    schema = None
    for snap in tl["snapshots"]:
        g, src = _snapshot_graph(db_url, snap["id"], kb, rebuild)
        c = compare._Canonicalizer(g, kb, sch).run()
        cid = node if node in c.items else next(iter(c.node_cids.get(node, [])), node)
        it = c.items.get(cid)
        values: dict[str, Any] = {}
        if it is not None:
            schema = it.schema
            prefix = cid + "/"
            for k, sub in c.items.items():
                if k.startswith(prefix) and sub.kind == "attr":
                    f = k[len(prefix) :]
                    values[f] = {"value": sub.value, "origin": sub.origin, "lines": sub.lines}
                    if f not in fields:
                        fields.append(f)
        changed = []
        if prev is not None:
            changed = sorted(
                f
                for f in set(values) | set(prev["values"])
                if (values.get(f) or {}).get("value") != (prev["values"].get(f) or {}).get("value")
            )
            if bool(prev["present"]) != (it is not None):
                changed = ["@presence", *changed]
        row = {
            "id": snap["id"],
            "seq": snap["seq"],
            "collected_at": snap["collected_at"],
            "tag": snap["tag"],
            "kb_version": snap["kb_version"],
            "graph": src,
            "present": it is not None,
            "lines": c.subtree_lines.get(cid, []) if it is not None else [],
            "values": values,
            "changed": changed,
        }
        rows.append(row)
        prev = row
    if schema is None:
        raise HistoryError("history.object_not_found", "not_found", node=node)
    return {
        "device": tl["device"],
        "node": node,
        "schema": schema,
        "fields": sorted(fields),
        "snapshots": rows,
        "changes": sum(1 for r in rows if r["changed"]),
    }


# ---------------------------------------------------------------- 回到 A 的变更脚本


def restore(
    db_url: str,
    device_id: int,
    kb: KnowledgeBase,
    target: str | int | None,
    current: str | int | None = None,
    namer: Any = None,
    lang: str = "zh-CN",
) -> dict[str, Any]:
    """把设备从当前快照（默认最新）恢复到目标快照 A 的增量变更脚本（含回滚与模拟验证）。

    变更脚本按配置原文用当前知识库重新解析（脚本要用当前的命令卡渲染）。"""
    from lmesh.core import change

    vt = resolve_snapshot(db_url, device_id, target, "prev")
    vc = resolve_snapshot(db_url, device_id, current, "latest")
    try:
        cur = compare.side_from_version(db_url, kb, vc, device_id=device_id)
        tgt = compare.side_from_version(db_url, kb, vt, device_id=device_id)
    except compare.CompareError as e:
        raise HistoryError(e.key, e.kind, **e.fmt) from e
    try:
        result = change.change(cur, tgt, kb, namer=namer, lang=lang)
    except change.ChangeError as e:
        raise HistoryError(e.key, getattr(e, "kind", "param"), **getattr(e, "fmt", {})) from e
    tl = timeline(db_url, device_id, kb)
    snaps = {s["id"]: s for s in tl["snapshots"]}
    return {"device": tl["device"], "from": snaps[vc], "to": snaps[vt], "change": result}


# ---------------------------------------------------------------- 其他模块取最新快照的图


def devices_from_db(db_url: str, kb: KnowledgeBase, targets: list[str] | None = None) -> tuple[list[Any], list[str]]:
    """已导入设备的最新快照（topology.Device）：快照保存的图与当前知识库版本一致时直接用，否则按当前知识库重新解析。

    targets 是设备名或编号，None 表示全部。返回 (设备, 找不到的目标)。"""
    from lmesh.core import importer, topology

    devs = importer.list_devices(db_url)
    chosen: list[dict[str, Any]] = []
    missing: list[str] = []
    if targets is None:
        chosen = [d for d in devs if d["latest_version_id"]]
    else:
        for t in targets:
            t = str(t).strip()
            if not t:
                continue
            hit = next((d for d in devs if d["name"] == t or (t.isdigit() and d["id"] == int(t))), None)
            if hit is None or not hit["latest_version_id"]:
                missing.append(t)
            elif hit not in chosen:
                chosen.append(hit)
    out = []
    for d in chosen:
        vid = d["latest_version_id"]
        with store.session(db_url) as s:
            ver = s.get(ConfigVersion, vid)
            fresh = ver is not None and ver.kb_version == kb.version and bool(ver.graph_gz)
        g, _ = _snapshot_graph(db_url, vid, kb, rebuild=not fresh)
        dev = topology.Device(d["name"], g, device_id=d["id"], version_id=vid, source="device")
        dev.collected_at = d.get("collected_at")  # type: ignore[attr-defined]
        out.append(dev)
    return out, missing


def latest_text(db_url: str, device: str) -> tuple[int, str, str, str] | None:
    """设备（名称或编号）最新快照的 (设备编号, 设备名, Profile, 原文)；没有时 None。"""
    from lmesh.core import importer

    hit = next(
        (
            d
            for d in importer.list_devices(db_url)
            if d["name"] == device or (device.isdigit() and d["id"] == int(device))
        ),
        None,
    )
    if hit is None or not hit["latest_version_id"]:
        return None
    return hit["id"], hit["name"], hit["profile"], _text(db_url, hit["latest_version_id"])
