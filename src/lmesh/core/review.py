"""审核队列：AI 或规则抽取的命令卡、提议的新节点、未识别行的映射建议、导入冲突，统一在这里通过或驳回。

通过时按条目类型执行对应动作（写回知识库文件），然后在运行时知识库中提交一次。
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from lmesh.core import store
from lmesh.core.store.models import ReviewItem, iso

KINDS = ("card", "schema_node", "mapping", "conflict", "profile_entry", "suggestion")
Action = Callable[[Path, ReviewItem, dict[str, Any] | None], None]
_ACTIONS: dict[str, Action] = {}


def register_action(kind: str) -> Callable[[Action], Action]:
    def deco(fn: Action) -> Action:
        _ACTIONS[kind] = fn
        return fn

    return deco


def add(
    db_url: str, kind: str, title: str, target: str, payload: dict[str, Any], source: dict[str, Any] | None = None
) -> int:
    with store.session(db_url) as s:
        item = ReviewItem(kind=kind, title=title, target=target, payload=payload, source=source or {})
        s.add(item)
        s.flush()
        return int(item.id)


def as_dict(i: ReviewItem, with_payload: bool = True) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": i.id,
        "kind": i.kind,
        "status": i.status,
        "title": i.title,
        "target": i.target,
        "source": i.source,
        "note": i.note,
        "created_at": iso(i.created_at),
        "decided_at": iso(i.decided_at),
    }
    if with_payload:
        d["payload"] = i.payload
    return d


def list_items(
    db_url: str, status: str | None = "pending", kind: str | None = None, limit: int = 200, offset: int = 0
) -> dict[str, Any]:
    with store.session(db_url) as s:
        q = select(ReviewItem)
        cq = select(func.count(ReviewItem.id))
        if status:
            q, cq = q.where(ReviewItem.status == status), cq.where(ReviewItem.status == status)
        if kind:
            q, cq = q.where(ReviewItem.kind == kind), cq.where(ReviewItem.kind == kind)
        total = s.scalar(cq) or 0
        items = [
            as_dict(i, with_payload=False) for i in s.scalars(q.order_by(ReviewItem.id).offset(offset).limit(limit))
        ]
        return {"total": total, "items": items}


def list_items_raw(s: Any, kind: str | None = None, status: str | None = None) -> list[ReviewItem]:
    """在调用方的会话里查询（不转换成字典）。"""
    q = select(ReviewItem)
    if kind:
        q = q.where(ReviewItem.kind == kind)
    if status:
        q = q.where(ReviewItem.status == status)
    return list(s.scalars(q))


def get(db_url: str, item_id: int) -> dict[str, Any] | None:
    with store.session(db_url) as s:
        i = s.get(ReviewItem, item_id)
        return as_dict(i) if i else None


def counts(db_url: str) -> dict[str, int]:
    with store.session(db_url) as s:
        rows = s.execute(
            select(ReviewItem.kind, func.count(ReviewItem.id))
            .where(ReviewItem.status == "pending")
            .group_by(ReviewItem.kind)
        )
        return {k: int(n) for k, n in rows}


class ReviewError(ValueError):
    pass


def _load_actions() -> None:
    """各类型的通过动作分散在各自模块里注册，用到前先导入。"""
    # M8-5：rule、unknown_card、card_maps
    from lmesh.core import ai_suggest_kb  # noqa: F401
    from lmesh.core.ingest import service  # noqa: F401  命令卡


def decide(
    db_url: str,
    kb_root: Path,
    item_id: int,
    approve: bool,
    note: str = "",
    edited: dict[str, Any] | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """通过（可带修改后的内容）或驳回。通过时执行该类型的动作；commit=True 时随即提交知识库（批量审核时最后统一提交）。"""
    from lmesh.core.kb import repo

    _load_actions()
    with repo.WRITE_LOCK, store.session(db_url) as s:
        item = s.get(ReviewItem, item_id)
        if item is None:
            raise ReviewError("review.not_found")
        if item.status != "pending":
            raise ReviewError("review.already_decided")
        if approve:
            action = _ACTIONS.get(item.kind)
            if action is None:
                raise ReviewError("review.no_action")
            action(kb_root, item, edited)
        item.status = "approved" if approve else "rejected"
        item.note = note
        item.decided_at = datetime.now(UTC)
        if edited:
            item.payload = {**(item.payload or {}), "edited": edited}
        result = as_dict(item)
    if approve and commit and (kb_root / ".git").exists():
        repo.commit_all(kb_root, f"审核通过 #{item_id}：{result['title']}")
    return result


@register_action("suggestion")
def _apply_suggestion(kb_root: Path, item: ReviewItem, edited: dict[str, Any] | None) -> None:
    """用户对知识库的建议（M6）：采纳只记录结论，知识库由维护员在对应页面修改（“采纳并编辑”）。"""
    return None


@register_action("conflict")
def _apply_conflict(kb_root: Path, item: ReviewItem, edited: dict[str, Any] | None) -> None:
    """导入或升级冲突：采用包内 / 新版本自带的内容（或审核时修改后的内容）覆盖知识库文件。

    升级冲突里新版本已删除该文件（theirs_deleted）时，采用新版本就是删除它。
    """
    payload = item.payload or {}
    target = (kb_root / item.target).resolve()
    if kb_root.resolve() not in target.parents:
        raise ReviewError("review.unsafe_path")
    if payload.get("theirs_deleted") and not (edited and "text" in edited):
        target.unlink(missing_ok=True)
        return
    if edited and "text" in edited:
        data = str(edited["text"]).encode("utf-8")
    else:
        data = base64.b64decode(payload["theirs_b64"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


@register_action("unknown_line")
def _apply_unknown_line(kb_root: Path, item: ReviewItem, edited: dict[str, Any] | None) -> None:
    """未识别行：审核时可附上一张新命令卡（edited.card），通过后写入知识库；不附卡表示确认为功能域外，下次按原文保留。"""
    from lmesh.core.kb import files as kbfiles
    from lmesh.core.kb import syntax as syn

    card = (edited or {}).get("card")
    if not card:
        return
    for k in ("id", "syntax", "view"):
        if not card.get(k):
            raise ReviewError("review.card_incomplete")
    syn.parse(str(card["syntax"]))
    family, domain = str(card.get("family") or ""), str(card.get("domain") or "")
    if not family or not domain:
        raise ReviewError("review.card_incomplete")
    path = kbfiles.card_file(kb_root, family, domain)
    doc = kbfiles.load_card_doc(path, domain)
    if any(c.get("id") == card["id"] for c in doc["cards"]):
        raise ReviewError("review.card_exists")
    clean = {k: v for k, v in card.items() if k in kbfiles.CARD_FIELDS}
    clean["status"] = "reviewed"
    doc["cards"].append(kbfiles.to_card_map(clean))
    kbfiles.dump_rt(path, doc)
