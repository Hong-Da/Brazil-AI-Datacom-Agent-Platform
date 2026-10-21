"""AI 查询会话（REQ-052）与附件（REQ-053）。

- 会话属于当前项目，只有本人可见；shared 时同项目成员可以只读查看（不能追问、修改、加附件）。
- 一轮（turn）有多个版本：改问题重新回答时追加版本，current 指向正在显示的版本；之后的轮次不受影响。
- 追问时把本会话前几轮（当前版本）的问题与图查询交给 AI（ask.history_text，发送前整体脱敏）。
- 附件：配置文件作为本会话的临时设备（导入时同样脱敏，不进设备库）；文档提取文字并脱敏作参考资料；
  图片原样保存，只有开启 ai.ask_images 且发送时确认才交给 AI。
AI 调用与图查询由调用方（API / CLI）完成，这里只管存取与权限。
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from lmesh.core import ask_docs, importer, projects, store
from lmesh.core.sanitize import SanitizeLeak, Sanitizer, local_key
from lmesh.core.store.models import AskAttachment, AskSession, AskTurn, User

MAX_ATTACHMENTS = 10
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_DOC_CHARS = 30000
TITLE_LEN = 60


class SessionError(ValueError):
    """kind：param（422）、not_found（404）、state（409）、forbidden（403）。"""

    def __init__(self, key: str, kind: str = "param", **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.fmt = key, kind, fmt


def _now() -> datetime:
    return datetime.now(UTC)


def _me() -> tuple[int | None, str]:
    ident = projects.identity()
    if ident is None:
        return None, "cli"
    return ident.user_id, ident.username or ""


def _project_id() -> int:
    sc = projects.current()
    if sc is None:
        raise SessionError("projects.no_project", "state")
    return sc.project_id


def _mine(row: AskSession, uid: int | None, owner: str) -> bool:
    return row.user_id == uid if uid is not None else (row.user_id is None and row.owner == owner)


def _get(s: Any, sid: int, write: bool) -> tuple[AskSession, bool]:
    """(会话, 是否本人)。别人的会话：分享了且同项目时只读，否则按不存在处理。"""
    row = s.get(AskSession, sid)
    pid = _project_id()
    if row is None or row.project_id != pid:
        raise SessionError("ask_session.not_found", "not_found", id=sid)
    uid, owner = _me()
    mine = _mine(row, uid, owner)
    if not mine and not row.shared:
        raise SessionError("ask_session.not_found", "not_found", id=sid)
    if write and not mine:
        raise SessionError("ask_session.read_only", "forbidden")
    return row, mine


def _brief(row: AskSession, turns: int, attachments: int, mine: bool, owner_name: str = "") -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "owner": owner_name or row.owner,
        "mine": mine,
        "network": row.network_slug or None,
        "devices": row.devices,
        "archived": row.archived,
        "shared": row.shared,
        "turns": turns,
        "attachments": attachments,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _counts(s: Any, ids: list[int]) -> tuple[dict[int, int], dict[int, int]]:
    if not ids:
        return {}, {}
    t = dict(
        s.execute(
            select(AskTurn.session_id, func.count()).where(AskTurn.session_id.in_(ids)).group_by(AskTurn.session_id)
        ).all()
    )
    a = dict(
        s.execute(
            select(AskAttachment.session_id, func.count())
            .where(AskAttachment.session_id.in_(ids))
            .group_by(AskAttachment.session_id)
        ).all()
    )
    return t, a


def list_sessions(db_url: str, which: str = "active", q: str = "") -> list[dict[str, Any]]:
    """which：active 进行中 / archived 已归档（本人的）/ shared 别人分享给我的（同项目）。最近更新的在前。"""
    pid = _project_id()
    uid, owner = _me()
    with store.session(db_url) as s:
        stmt = select(AskSession).where(AskSession.project_id == pid)
        if which == "shared":
            stmt = stmt.where(AskSession.shared.is_(True))
            rows = [r for r in s.scalars(stmt.order_by(AskSession.updated_at.desc())) if not _mine(r, uid, owner)]
        else:
            stmt = stmt.where(AskSession.archived.is_(which == "archived"))
            rows = [r for r in s.scalars(stmt.order_by(AskSession.updated_at.desc())) if _mine(r, uid, owner)]
        if q.strip():
            k = q.strip().lower()
            rows = [r for r in rows if k in r.title.lower()]
        t, a = _counts(s, [r.id for r in rows])
        names = _owner_names(s, rows)
        return [_brief(r, t.get(r.id, 0), a.get(r.id, 0), which != "shared", names.get(r.id, "")) for r in rows]


def _owner_names(s: Any, rows: list[AskSession]) -> dict[int, str]:
    ids = {r.user_id for r in rows if r.user_id is not None}
    if not ids:
        return {}
    users = {u.id: u.username for u in s.scalars(select(User).where(User.id.in_(ids)))}
    return {r.id: users.get(r.user_id, r.owner) for r in rows if r.user_id is not None}


def counts(db_url: str) -> dict[str, int]:
    pid = _project_id()
    uid, owner = _me()
    with store.session(db_url) as s:
        rows = list(s.scalars(select(AskSession).where(AskSession.project_id == pid)))
    mine = [r for r in rows if _mine(r, uid, owner)]
    return {
        "active": sum(1 for r in mine if not r.archived),
        "archived": sum(1 for r in mine if r.archived),
        "shared": sum(1 for r in rows if r.shared and not _mine(r, uid, owner)),
    }


def create(db_url: str, title: str = "", devices: list[str] | None = None) -> dict[str, Any]:
    """新会话：记下当前网络与范围。"""
    sc = projects.current()
    pid = _project_id()
    uid, owner = _me()
    with store.session(db_url) as s:
        row = AskSession(
            project_id=pid,
            user_id=uid,
            owner=owner,
            title=title.strip()[:200],
            network_id=sc.network_id if sc else None,
            network_slug=sc.network_slug if sc else "",
            devices=devices,
        )
        s.add(row)
        s.flush()
        return _brief(row, 0, 0, True)


def update(db_url: str, sid: int, changes: dict[str, Any]) -> dict[str, Any]:
    """改标题、归档 / 恢复、分享 / 取消分享、范围（之后的提问生效；网络取当前网络）。"""
    sc = projects.current()
    with store.session(db_url) as s:
        row, _ = _get(s, sid, write=True)
        if "title" in changes and changes["title"] is not None:
            row.title = str(changes["title"]).strip()[:200]
        if changes.get("archived") is not None:
            row.archived = bool(changes["archived"])
        if changes.get("shared") is not None:
            row.shared = bool(changes["shared"])
        if "devices" in changes:
            row.devices = changes["devices"]
            if sc is not None:
                row.network_id, row.network_slug = sc.network_id, sc.network_slug
        row.updated_at = _now()
        s.flush()
        t, a = _counts(s, [row.id])
        return _brief(row, t.get(row.id, 0), a.get(row.id, 0), True)


def delete(db_url: str, sid: int) -> None:
    with store.session(db_url) as s:
        row, _ = _get(s, sid, write=True)
        s.delete(row)


def _turn_dict(t: AskTurn) -> dict[str, Any]:
    versions = list(t.versions or [])
    return {
        "id": t.id,
        "position": t.position,
        "current": t.current,
        "versions": versions,
    }


def get(db_url: str, sid: int) -> dict[str, Any]:
    """会话全文：轮次（各版本的问题与结果）、附件（不含内容）。"""
    with store.session(db_url) as s:
        row, mine = _get(s, sid, write=False)
        turns = list(s.scalars(select(AskTurn).where(AskTurn.session_id == sid).order_by(AskTurn.position, AskTurn.id)))
        atts = list(s.scalars(select(AskAttachment).where(AskAttachment.session_id == sid).order_by(AskAttachment.id)))
        names = _owner_names(s, [row])
        out = _brief(row, len(turns), len(atts), mine, names.get(row.id, ""))
        out["turn_list"] = [_turn_dict(t) for t in turns]
        out["attachment_list"] = [attachment_brief(a) for a in atts]
        return out


def history(db_url: str, sid: int, before: int | None = None) -> list[dict[str, Any]]:
    """追问的上下文：本会话 before 之前各轮当前版本的 {question, query}（before 为空时取全部）。"""
    with store.session(db_url) as s:
        _get(s, sid, write=False)
        stmt = select(AskTurn).where(AskTurn.session_id == sid)
        if before is not None:
            stmt = stmt.where(AskTurn.position < before)
        out = []
        for t in s.scalars(stmt.order_by(AskTurn.position, AskTurn.id)):
            vs = list(t.versions or [])
            if not vs:
                continue
            v = vs[min(t.current, len(vs) - 1)]
            res = v.get("result") or {}
            out.append({"question": v.get("question", ""), "query": res.get("query_text") or ""})
        return out


def _version(question: str, result: dict[str, Any], context: int, attachments: list[int]) -> dict[str, Any]:
    return {
        "question": question,
        "result": result,
        "context": context,
        "attachments": attachments,
        "at": _now().isoformat(),
    }


def add_turn(
    db_url: str, sid: int, question: str, result: dict[str, Any], context: int, attachments: list[int]
) -> dict[str, Any]:
    """追加一轮；会话还没有标题时用第一个问题作标题。"""
    with store.session(db_url) as s:
        row, _ = _get(s, sid, write=True)
        if row.archived:
            raise SessionError("ask_session.archived", "state")
        pos = (s.scalar(select(func.max(AskTurn.position)).where(AskTurn.session_id == sid)) or 0) + 1
        t = AskTurn(
            session_id=sid, position=pos, versions=[_version(question, result, context, attachments)], current=0
        )
        s.add(t)
        if not row.title:
            row.title = question.strip().replace("\n", " ")[:TITLE_LEN]
        row.updated_at = _now()
        s.flush()
        return _turn_dict(t)


def turn_position(db_url: str, sid: int, tid: int) -> int:
    with store.session(db_url) as s:
        _get(s, sid, write=False)
        t = s.get(AskTurn, tid)
        if t is None or t.session_id != sid:
            raise SessionError("ask_session.turn_not_found", "not_found", id=tid)
        return t.position


def add_version(
    db_url: str, sid: int, tid: int, question: str, result: dict[str, Any], context: int, attachments: list[int]
) -> dict[str, Any]:
    """改问题重新回答：追加一个版本并切到它。"""
    with store.session(db_url) as s:
        row, _ = _get(s, sid, write=True)
        if row.archived:
            raise SessionError("ask_session.archived", "state")
        t = s.get(AskTurn, tid)
        if t is None or t.session_id != sid:
            raise SessionError("ask_session.turn_not_found", "not_found", id=tid)
        vs = list(t.versions or [])
        vs.append(_version(question, result, context, attachments))
        t.versions, t.current = vs, len(vs) - 1
        row.updated_at = _now()
        s.flush()
        return _turn_dict(t)


def set_current(db_url: str, sid: int, tid: int, current: int) -> dict[str, Any]:
    """切换这一轮显示的版本（之后追问的上下文用它）。"""
    with store.session(db_url) as s:
        _get(s, sid, write=True)
        t = s.get(AskTurn, tid)
        if t is None or t.session_id != sid:
            raise SessionError("ask_session.turn_not_found", "not_found", id=tid)
        if not 0 <= current < len(t.versions or []):
            raise SessionError("ask_session.bad_version", "param", n=current)
        t.current = current
        s.flush()
        return _turn_dict(t)


# ---------------------------------------------------------------- 附件（REQ-053）


def attachment_brief(a: AskAttachment) -> dict[str, Any]:
    return {
        "id": a.id,
        "name": a.name,
        "kind": a.kind,
        "size": a.size,
        "meta": a.meta or {},
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _sanitizer() -> Sanitizer:
    sc = projects.current()
    return Sanitizer("basic", local_key(), redact=list(sc.redact) if sc else None)


def _classify(name: str, data: bytes, images_on: bool, kb: Any) -> list[dict[str, Any]]:
    """一个上传 → 若干附件记录 [{name, kind, size, text, data, meta}]（zip 展开为其中的配置与文档）。"""
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise SessionError("ask.attach_too_large", "param", name=name, mb=MAX_ATTACHMENT_BYTES // (1024 * 1024))
    mime = ask_docs.image_type(name, data)
    if mime:
        if not images_on:
            raise SessionError("ask.images_off", "state")
        return [{"name": name, "kind": "image", "size": len(data), "text": "", "data": data, "meta": {"mime": mime}}]
    if ask_docs.suffix(name) == ".zip":
        out: list[dict[str, Any]] = []
        for inner, raw in importer.iter_bytes(name, data):
            out += _classify(inner, raw, images_on, kb)
        return out
    sfx = ask_docs.suffix(name)
    if sfx not in (".pdf", ".docx", ".xlsx", ".csv", ".md") and b"\x00" not in data[:4096]:
        text = importer.decode(data)
        if importer.detect_vendor(text):
            res, clean = importer.sanitize_one(name, data, _sanitizer(), kb)
            if not res.ok:
                err = SessionError(res.error or "ask.attach_unreadable", "param", name=name)
                err.data = {"lines": res.error_lines}  # type: ignore[attr-defined]
                raise err
            meta = {"vendor": res.vendor, "profile": res.profile, "device": res.device, "lines": res.lines}
            return [{"name": name, "kind": "config", "size": len(data), "text": clean, "data": None, "meta": meta}]
    try:
        ex = ask_docs.extract(name, data)
    except ask_docs.DocError as e:
        raise SessionError(e.key, "param", **{"name": name, **e.fmt}) from e
    try:
        clean = _sanitizer().sanitize(ex.text).text
    except SanitizeLeak as e:
        raise SessionError("import.sanitize_leak", "param", name=name) from e
    meta = {**ex.meta, "chars": min(len(clean), MAX_DOC_CHARS), "truncated": len(clean) > MAX_DOC_CHARS}
    return [{"name": name, "kind": "doc", "size": len(data), "text": clean[:MAX_DOC_CHARS], "data": None, "meta": meta}]


def add_attachments(
    db_url: str, sid: int, files: list[tuple[str, bytes]], images_on: bool, kb: Any
) -> list[dict[str, Any]]:
    """保存上传的附件（全部检查通过才保存）。"""
    items: list[dict[str, Any]] = []
    for name, data in files:
        items += _classify(name, data, images_on, kb)
    with store.session(db_url) as s:
        row, _ = _get(s, sid, write=True)
        if row.archived:
            raise SessionError("ask_session.archived", "state")
        have = s.scalar(select(func.count()).select_from(AskAttachment).where(AskAttachment.session_id == sid)) or 0
        if have + len(items) > MAX_ATTACHMENTS:
            raise SessionError("ask.attach_too_many", "param", n=MAX_ATTACHMENTS)
        rows = [AskAttachment(session_id=sid, **it) for it in items]
        s.add_all(rows)
        row.updated_at = _now()
        s.flush()
        return [attachment_brief(a) for a in rows]


def delete_attachment(db_url: str, sid: int, aid: int) -> None:
    with store.session(db_url) as s:
        _get(s, sid, write=True)
        a = s.get(AskAttachment, aid)
        if a is None or a.session_id != sid:
            raise SessionError("ask_session.attachment_not_found", "not_found", id=aid)
        s.delete(a)


def materials(db_url: str, sid: int) -> dict[str, Any]:
    """提问时要用的附件：configs [{name, text, profile}]（临时设备）、references（文档文字）、images [(mime, b64)]、ids。"""
    with store.session(db_url) as s:
        _get(s, sid, write=False)
        atts = list(s.scalars(select(AskAttachment).where(AskAttachment.session_id == sid).order_by(AskAttachment.id)))
        configs = [
            {"name": a.name, "text": a.text, "profile": (a.meta or {}).get("profile") or None}
            for a in atts
            if a.kind == "config"
        ]
        refs = [f"### {a.name}\n{a.text}" for a in atts if a.kind == "doc" and a.text.strip()]
        images = [
            (str((a.meta or {}).get("mime") or "image/png"), base64.b64encode(a.data).decode("ascii"))
            for a in atts
            if a.kind == "image" and a.data
        ]
        return {
            "configs": configs,
            "references": "\n\n".join(refs)[:MAX_DOC_CHARS],
            "images": images,
            "ids": [a.id for a in atts],
            "image_ids": [a.id for a in atts if a.kind == "image"],
        }


# ---------------------------------------------------------------- 执行一次提问（API 与 CLI 共用）


def scope_devices(db_url: str, kb: Any, devices: list[str] | None, configs: list[dict[str, Any]]) -> list[Any]:
    """范围：已导入设备（当前网络；devices 为空时全部可查询设备，只存原文的跳过）+ 附件里的临时设备。"""
    from lmesh.core import history, topology

    temp = topology.from_texts(configs, kb) if configs else []
    found, missing = history.devices_from_db(db_url, kb, devices if devices else None)
    if missing:
        raise SessionError("graph.target_not_found", "not_found", target=", ".join(missing))
    out = temp + found
    for d, n in zip(out, topology.unique_names([d.name for d in out]), strict=True):
        d.name = n
    return out


def run(
    db_url: str,
    sid: int,
    question: str,
    kb: Any,
    settings: Any,
    lang: str,
    actor: Any = None,
    confirm_images: bool = False,
    before: int | None = None,
) -> tuple[dict[str, Any], int, list[int]]:
    """提问（追问或改问重答）：返回 (结果, 带了几轮上下文, 用到的附件编号)。不保存，由调用方 add_turn / add_version。
    图片：ai.ask_images 关闭时 ask.images_off；没有确认时 ask.images_confirm（data 带图片附件编号）。"""
    from lmesh.core import ask

    sess = get(db_url, sid)
    if not sess["mine"]:
        raise SessionError("ask_session.read_only", "forbidden")
    if sess["archived"]:
        raise SessionError("ask_session.archived", "state")
    mat = materials(db_url, sid)
    hist = history(db_url, sid, before)
    if mat["images"]:
        if not bool(settings.get("ai.ask_images")):
            raise SessionError("ask.images_off", "state")
        if not confirm_images:
            err = SessionError("ask.images_confirm", "state")
            err.data = {"images": mat["image_ids"]}  # type: ignore[attr-defined]
            raise err
    devices = scope_devices(db_url, kb, sess["devices"], mat["configs"])
    result = ask.ask(
        question,
        devices,
        kb,
        settings,
        lang,
        actor=actor,
        history=hist,
        references=mat["references"],
        images=mat["images"] or None,
    )
    return result, min(len(hist), ask.HISTORY_TURNS), mat["ids"]
