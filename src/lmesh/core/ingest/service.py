"""产品文档导入：按抽取规则得到命令卡 → 合并进运行时知识库 → 送审核队列 → 提交。

合并规则：
- 新卡：以 draft 写入，加一条审核记录（通过后状态改为 reviewed）。
- 已有的 draft 卡内容变了：直接更新（还在等审核，不重复加记录）。
- 已审核（reviewed / verified）的卡内容变了：不改文件，加一条“更新”审核记录，由人决定是否采用。
- 内容没变：跳过。
规则抽取失败、且配置了 AI 时，交给 AI 修正语法；AI 的结果必须能通过语法解析才会采用，并在来源中注明 extracted_by: ai。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select

from lmesh.core import ai, config, review, store
from lmesh.core.ingest.extractor import ExtractResult, extract, load_rules
from lmesh.core.kb import files as kbfiles
from lmesh.core.kb import repo
from lmesh.core.kb import syntax as syn
from lmesh.core.store.models import ReviewItem

Progress = Callable[[int, str], None]
HEADER = "命令卡（由 lmesh kb ingest 按抽取规则生成；审核通过后 status 为 reviewed）。手工修改后运行 lmesh kb validate 检查。"

AI_SYSTEM = (
    "You convert router command syntax from vendor documentation into a strict notation: keywords as plain words, "
    "parameters as <name>, optional parts in [ ], required choices in { a | b }, repetition as &<1-N> after an element. "
    "Reply with the corrected syntax only, on one line, nothing else."
)


def find_rules(kb_root: Path, name: str) -> Path:
    p = Path(name)
    if p.exists():
        return p
    cand = kb_root / "extractors" / (name if name.endswith(".yaml") else f"{name}.yaml")
    if cand.exists():
        return cand
    raise FileNotFoundError(name)


def _pending_cards(db_url: str) -> set[str]:
    with store.session(db_url) as s:
        return {
            t
            for (t,) in s.execute(
                select(ReviewItem.target).where(ReviewItem.kind == "card", ReviewItem.status == "pending")
            )
        }


def _ai_fix(settings: config.Settings, res: ExtractResult, family: str, progress: Progress) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, f in enumerate(res.failed):
        progress(60 + int(20 * i / max(1, len(res.failed))), f"AI：{f['title']}")
        prompt = f"Command: {f['title']}\nDocumentation syntax line (Markdown, bold = keyword, italic = parameter):\n{f['format']}\n"
        try:
            reply = ai.complete(settings, "extract", prompt, AI_SYSTEM)
        except ai.AIError:
            break  # AI 不可用时整批停止，保留规则抽取的结果
        fixed = reply.text.strip().strip("`").splitlines()[0].strip() if reply.text.strip() else ""
        try:
            parsed = syn.parse(fixed)
        except syn.SyntaxErrorKB:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"\s*\(.*?\)\s*", " ", f["title"].lower())).strip("-")
        for view in f["views"]:
            out.append(
                {
                    "id": f"{family}.{slug}.ai@{view}",
                    "syntax": fixed,
                    "view": view,
                    "domain": f["domain"],
                    "status": "draft",
                    "params": {n: f["params"].get(n, {"type": "word"}) for n in dict.fromkeys(parsed.params())},
                    "source": {
                        "file": f["file"],
                        "title": f["title"],
                        "line": f["line"],
                        "extracted_by": "ai",
                        "model": reply.model,
                    },
                }
            )
    return out


def _avoid_foreign_ids(
    kb_root: Path, family: str, by_domain: dict[str, list[dict[str, Any]]], stats: Counter[str]
) -> None:
    """抽取编号只在一次抽取内唯一；分批抽取不同功能域时，新卡可能与其他功能域文件里已有的卡同号。
    同号且语法、视图相同 → 那张卡已在别的功能域，跳过；同号但内容不同 → 改用下一个空闲的 ~N 编号。
    结果只取决于知识库现状与本次抽取，重复抽取得到同样的编号。"""
    fam_dir = kb_root / "commands" / family
    foreign: dict[str, dict[str, tuple[str, str]]] = {}  # 功能域 → {编号: (语法, 视图)}
    for f in sorted(fam_dir.glob("*.yaml")) if fam_dir.exists() else []:
        if f.name == "views.yaml":
            continue
        doc = kbfiles.load_rt(f) or {}
        foreign[f.stem] = {str(c.get("id")): (str(c.get("syntax")), str(c.get("view"))) for c in doc.get("cards") or []}
    for domain, items in by_domain.items():
        others = {cid: sv for d, ids in foreign.items() if d != domain for cid, sv in ids.items()}
        # 本功能域文件里已有的编号不算占用：重复抽取时同一张卡应当得到同一个编号
        taken = set(others) | {str(c["id"]) for its in by_domain.values() for c in its}
        keep = []
        for card in items:
            cid = str(card["id"])
            if cid in others:
                if others[cid] == (str(card["syntax"]), str(card["view"])):
                    stats["in_other_domain"] += 1
                    continue
                base = cid.split("~", 1)[0]
                n = 2
                while f"{base}~{n}" in taken:
                    n += 1
                card["id"] = f"{base}~{n}"
                taken.add(card["id"])
                stats["renumbered"] += 1
            keep.append(card)
        items[:] = keep


def ingest(
    doc_dir: Path,
    rules_name: str,
    kb_root: Path,
    db_url: str,
    settings: config.Settings | None = None,
    domains: list[str] | None = None,
    version: str = "",
    use_ai: bool = False,
    progress: Progress | None = None,
) -> dict[str, Any]:
    progress = progress or (lambda pct, msg: None)
    rules = load_rules(find_rules(kb_root, rules_name))
    progress(2, "准备文档")
    import tempfile

    from lmesh import paths
    from lmesh.core.ingest import convert

    tmp_base = paths.root_path("tmp")
    tmp_base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ingest-", dir=tmp_base) as work:
        source = convert.prepare(doc_dir, Path(work))
        progress(5, "抽取命令卡")
        res = extract(source, rules, domains, version)
    cards = [dict(c) for c in res.cards]  # 合并时会改动字典，摘要仍用原结果
    if use_ai and res.failed and settings is not None and ai.is_configured(settings):
        cards += _ai_fix(settings, res, rules.family, progress)
    progress(80, "合并进知识库")
    pending = _pending_cards(db_url)
    stats: Counter[str] = Counter()
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for c in cards:
        by_domain.setdefault(c.pop("domain"), []).append(c)
    _avoid_foreign_ids(kb_root, rules.family, by_domain, stats)
    reviews: list[tuple[str, str, str, dict[str, Any], dict[str, Any]]] = []
    for domain, items in by_domain.items():
        path = kbfiles.card_file(kb_root, rules.family, domain)
        doc = kbfiles.load_card_doc(path, domain, HEADER)
        index = {str(c.get("id")): i for i, c in enumerate(doc["cards"])}
        # 先按内容（语法 + 视图）对上已有的卡：编号与抽取时一起处理的功能域有关，内容才是稳定的
        by_content = {(str(c.get("syntax")), str(c.get("view"))): str(c.get("id")) for c in doc["cards"]}
        for card in items:
            same = by_content.get((str(card["syntax"]), str(card["view"])))
            if same and same != card["id"]:
                card["id"] = same
                stats["matched_by_content"] += 1
            cid = card["id"]
            if cid not in index:
                doc["cards"].append(kbfiles.to_card_map(card))
                index[cid] = len(doc["cards"]) - 1
                stats["new"] += 1
                reviews.append(
                    (
                        "card",
                        f"{cid}：{card['syntax']}",
                        cid,
                        {"action": "new", "file": path.relative_to(kb_root).as_posix()},
                        card["source"],
                    )
                )
                continue
            existing = doc["cards"][index[cid]]
            for keep in ("maps", "maps_manual"):  # 映射来自映射规则，重新抽取时保留
                if existing.get(keep) is not None:
                    card[keep] = existing.get(keep)
            if kbfiles.comparable(existing) == kbfiles.comparable(card):
                stats["unchanged"] += 1
            elif str(existing.get("status", "draft")) == "draft" and not existing.get("curated"):
                doc["cards"][index[cid]] = kbfiles.to_card_map(card)
                stats["updated_draft"] += 1
                if cid not in pending:
                    reviews.append(
                        (
                            "card",
                            f"{cid}：{card['syntax']}",
                            cid,
                            {"action": "new", "file": path.relative_to(kb_root).as_posix()},
                            card["source"],
                        )
                    )
            else:
                stats["changed_reviewed"] += 1
                reviews.append(
                    (
                        "card",
                        f"{cid}（文档有变化）：{card['syntax']}",
                        cid,
                        {
                            "action": "update",
                            "file": path.relative_to(kb_root).as_posix(),
                            "card": json.loads(json.dumps(card)),
                        },
                        card["source"],
                    )
                )
        kbfiles.dump_rt(path, doc)
    progress(90, "写入审核队列")
    with store.session(db_url) as s:
        for kind, title, target, payload, src in reviews:
            s.add(
                ReviewItem(
                    kind=kind, title=title[:400], target=target, payload=payload, source=dict(src, rules=rules.name)
                )
            )
    commit = (
        repo.commit_all(
            kb_root,
            f"抽取命令卡（{rules.name}）：新增 {stats['new']}，更新 {stats['updated_draft']}，待确认变化 {stats['changed_reviewed']}",
        )
        if (kb_root / ".git").exists()
        else None
    )
    summary = res.summary()
    summary.update(
        {
            "rules": rules.name,
            "family": rules.family,
            "merge": dict(stats),
            "review_items": len(reviews),
            "commit": commit,
            "ai_cards": sum(1 for c in cards if c.get("source", {}).get("extracted_by") == "ai"),
        }
    )
    return summary


@review.register_action("card")
def _approve_card(kb_root: Path, item: ReviewItem, edited: dict[str, Any] | None) -> None:
    """通过命令卡：新卡把状态改为 reviewed；“更新”类采用文档中的新内容。审核时可修改字段（edited）。"""
    found = kbfiles.find_card(kb_root, item.target)
    payload = item.payload or {}
    if found is None:
        if payload.get("action") != "update" or not payload.get("card"):
            raise review.ReviewError("review.card_missing")
        card = dict(payload["card"])
        path = kb_root / str(payload["file"])
        doc = kbfiles.load_card_doc(path, path.stem, HEADER)
        doc["cards"].append(kbfiles.to_card_map(card))
        idx = len(doc["cards"]) - 1
    else:
        path, doc, idx = found
        if payload.get("action") == "update" and payload.get("card"):
            doc["cards"][idx] = kbfiles.to_card_map(dict(payload["card"]))
    target = doc["cards"][idx]
    for k, v in (edited or {}).items():
        if k in kbfiles.CARD_FIELDS and k != "id":
            target[k] = v
    if edited and "syntax" in edited:
        syn.parse(str(target["syntax"]))  # 改过的语法必须能解析
    target["status"] = "reviewed"
    kbfiles.dump_rt(path, doc)


def approve_matching(
    db_url: str,
    kb_root: Path,
    kind: str = "card",
    title_contains: str | None = None,
    rules: str | None = None,
    limit: int = 10000,
) -> dict[str, Any]:
    """批量通过：按类型、标题关键字、抽取规则筛选（批量审核）。每张卡逐一写回，最后统一提交一次。"""
    with store.session(db_url) as s:
        q = select(ReviewItem.id, ReviewItem.title, ReviewItem.source).where(
            ReviewItem.kind == kind, ReviewItem.status == "pending"
        )
        rows = [(i, t, src) for i, t, src in s.execute(q.order_by(ReviewItem.id).limit(limit))]
    ids = [
        i
        for i, t, src in rows
        if (not title_contains or title_contains in t) and (not rules or (src or {}).get("rules") == rules)
    ]
    done, failed = 0, 0
    for i in ids:
        try:
            review.decide(db_url, kb_root, i, True, commit=False)
            done += 1
        except review.ReviewError:
            failed += 1
    if done and (kb_root / ".git").exists():
        repo.commit_all(kb_root, f"批量审核通过 {done} 条（{kind}）")
    return {"approved": done, "failed": failed}
