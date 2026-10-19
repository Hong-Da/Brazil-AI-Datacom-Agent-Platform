"""配置检查项目（REQ-031）的存储与操作：项目、脚本、修订记录（数据库），检查 / 重排 / 对比的入口（CLI 与 API 共用）。

归属（M6）：检查项目属于某个项目（project_id），项目成员按项目权限访问；没有当前项目时（直接调用 core）沿用
M6 之前的规则——属于创建它的账号（user_id），管理员与 API 令牌（user_id 为空）能看到全部，普通账号只能看到自己的。
修订：创建脚本、手动保存（内容有变化时）、按依赖重排（重排前的内容若未保存先存一条，再存重排后的一条）、恢复到某个修订，都形成一条修订。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from lmesh.core import compare, script_check, store, textdiff
from lmesh.core.kb import KnowledgeBase
from lmesh.core.store.models import CheckProject, CheckRevision, CheckScript, ConfigVersion, Device, User, iso

SOURCES = ("create", "manual", "reorder", "restore")
MAX_TEXT = 2_000_000


class ProjectError(ValueError):
    def __init__(self, key: str, kind: str = "param", **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.fmt = key, kind, fmt


@dataclass(frozen=True)
class Actor:
    """调用者：user_id 为空表示 API 令牌或命令行（可访问全部项目）。"""

    user_id: int | None = None
    admin: bool = True
    name: str = ""

    def sees_all(self) -> bool:
        return self.user_id is None or self.admin


def _now() -> datetime:
    return datetime.now(UTC)


def _project(s: Any, actor: Actor, pid: int) -> CheckProject:
    from lmesh.core import projects

    p = s.get(CheckProject, pid)
    sc = projects.current()
    if sc is not None:
        if p is None or p.project_id != sc.project_id:
            raise ProjectError("check_project.not_found", "not_found", id=pid)
        return p
    if p is None or (not actor.sees_all() and p.user_id != actor.user_id):
        raise ProjectError("check_project.not_found", "not_found", id=pid)
    return p


def _script(s: Any, actor: Actor, pid: int, sid: int) -> tuple[CheckProject, CheckScript]:
    p = _project(s, actor, pid)
    sc = s.get(CheckScript, sid)
    if sc is None or sc.project_id != p.id:
        raise ProjectError("check_project.script_not_found", "not_found", id=sid)
    return p, sc


def _kind(kind: str | None) -> str:
    k = kind or "change"
    if k not in script_check.KINDS:
        raise ProjectError("script_check.bad_kind", allowed=", ".join(script_check.KINDS))
    return k


def _name(name: str | None) -> str:
    n = (name or "").strip()
    if not n or len(n) > 200:
        raise ProjectError("check_project.bad_name")
    return n


def _text(t: str | None) -> str:
    t = (t or "").replace("\r\n", "\n")
    if len(t) > MAX_TEXT:
        raise ProjectError("check_project.too_large", limit=MAX_TEXT)
    return t


def _check_device(s: Any, device_id: int | None, version_id: int | None) -> None:
    from lmesh.core import projects

    if device_id is None:
        if version_id is not None:
            raise ProjectError("check_project.version_without_device")
        return
    if s.get(Device, device_id) is None or not projects.visible(s, device_id):
        raise ProjectError("script_check.device_not_found", "not_found", device=device_id)
    if version_id is not None:
        v = s.get(ConfigVersion, version_id)
        if v is None or v.device_id != device_id:
            raise ProjectError("script_check.version_not_found", "not_found", version=version_id)


def _project_dict(s: Any, p: CheckProject, with_scripts: bool = False) -> dict[str, Any]:
    dev = s.get(Device, p.device_id) if p.device_id else None
    owner = s.get(User, p.user_id) if p.user_id else None
    scripts = list(
        s.scalars(
            select(CheckScript).where(CheckScript.project_id == p.id).order_by(CheckScript.position, CheckScript.id)
        )
    )
    errors = sum(int((x.last_check or {}).get("errors") or 0) for x in scripts)
    warnings = sum(int((x.last_check or {}).get("warnings") or 0) for x in scripts)
    checked = [x.last_check for x in scripts if x.last_check]
    out: dict[str, Any] = {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "device": (
            {"id": dev.id, "name": dev.name, "vendor": dev.vendor, "platform": dev.platform, "profile": dev.profile}
            if dev
            else None
        ),
        "device_id": p.device_id,
        "version_id": p.version_id,
        "profile": p.profile or None,
        "default_kind": p.default_kind,
        "order_check": p.order_check,
        "ai_check": p.ai_check,
        "ai_rules": list(p.ai_rules or []),
        "owner": {"id": owner.id, "username": owner.username} if owner else None,
        "scripts": len(scripts),
        "last_check": {
            "errors": errors,
            "warnings": warnings,
            "checked": len(checked),
            "at": max((str(c.get("at") or "") for c in checked), default=None),
        },
        "created_at": iso(p.created_at),
        "updated_at": iso(p.updated_at),
    }
    if with_scripts:
        out["script_list"] = [_script_dict(s, x, content=False) for x in scripts]
    return out


def _script_dict(s: Any, sc: CheckScript, content: bool = True) -> dict[str, Any]:
    revs = s.scalar(select(func.count()).select_from(CheckRevision).where(CheckRevision.script_id == sc.id)) or 0
    out: dict[str, Any] = {
        "id": sc.id,
        "project_id": sc.project_id,
        "name": sc.name,
        "kind": sc.kind,
        "lines": sc.content.count("\n") + (1 if sc.content and not sc.content.endswith("\n") else 0),
        "position": sc.position,
        "revisions": int(revs),
        "last_check": sc.last_check,
        "created_at": iso(sc.created_at),
        "updated_at": iso(sc.updated_at),
    }
    if content:
        out["content"] = sc.content
    return out


def _rev_dict(r: CheckRevision, content: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": r.id,
        "script_id": r.script_id,
        "seq": r.seq,
        "source": r.source,
        "note": r.note,
        "summary": r.summary,
        "author": r.author,
        "lines": r.content.count("\n") + (1 if r.content and not r.content.endswith("\n") else 0),
        "created_at": iso(r.created_at),
    }
    if content:
        out["content"] = r.content
    return out


def _add_revision(
    s: Any, actor: Actor, sc: CheckScript, content: str, source: str, note: Any = None, summary: Any = None
) -> CheckRevision:
    seq = (s.scalar(select(func.max(CheckRevision.seq)).where(CheckRevision.script_id == sc.id)) or 0) + 1
    r = CheckRevision(
        script_id=sc.id,
        seq=seq,
        content=content,
        source=source,
        note=note,
        summary=summary,
        user_id=actor.user_id,
        author=actor.name,
    )
    s.add(r)
    s.flush()
    return r


def _latest(s: Any, sid: int) -> CheckRevision | None:
    return s.scalar(
        select(CheckRevision).where(CheckRevision.script_id == sid).order_by(CheckRevision.seq.desc()).limit(1)
    )


# ---------------------------------------------------------------- 项目


def list_projects(db: str, actor: Actor) -> list[dict[str, Any]]:
    from lmesh.core import projects

    with store.session(db) as s:
        q = select(CheckProject).order_by(CheckProject.updated_at.desc(), CheckProject.id.desc())
        sc = projects.current()
        if sc is not None:
            q = q.where(CheckProject.project_id == sc.project_id)
        elif not actor.sees_all():
            q = q.where(CheckProject.user_id == actor.user_id)
        return [_project_dict(s, p) for p in s.scalars(q)]


def create_project(db: str, actor: Actor, data: dict[str, Any]) -> dict[str, Any]:
    from lmesh.core import projects

    pid = projects.target_project_id(db)
    with store.session(db) as s:
        _check_device(s, data.get("device_id"), data.get("version_id"))
        p = CheckProject(
            name=_name(data.get("name")),
            description=str(data.get("description") or ""),
            device_id=data.get("device_id"),
            version_id=data.get("version_id"),
            profile=str(data.get("profile") or ""),
            default_kind=_kind(data.get("default_kind")),
            order_check=bool(data.get("order_check", True)),
            ai_check=bool(data.get("ai_check", False)),
            ai_rules=[str(x) for x in data.get("ai_rules") or []],
            user_id=actor.user_id,
            project_id=pid,
        )
        s.add(p)
        s.flush()
        return _project_dict(s, p, with_scripts=True)


def get_project(db: str, actor: Actor, pid: int) -> dict[str, Any]:
    with store.session(db) as s:
        return _project_dict(s, _project(s, actor, pid), with_scripts=True)


def update_project(db: str, actor: Actor, pid: int, data: dict[str, Any]) -> dict[str, Any]:
    with store.session(db) as s:
        p = _project(s, actor, pid)
        if "name" in data:
            p.name = _name(data["name"])
        if "description" in data:
            p.description = str(data["description"] or "")
        if "device_id" in data or "version_id" in data:
            dev = data.get("device_id", p.device_id)
            ver = data.get("version_id") if "version_id" in data else (p.version_id if dev == p.device_id else None)
            _check_device(s, dev, ver)
            p.device_id, p.version_id = dev, ver
        if "profile" in data:
            p.profile = str(data["profile"] or "")
        if "default_kind" in data:
            p.default_kind = _kind(data["default_kind"])
        for k in ("order_check", "ai_check"):
            if k in data and data[k] is not None:
                setattr(p, k, bool(data[k]))
        if "ai_rules" in data:
            p.ai_rules = [str(x) for x in data["ai_rules"] or []]
        p.updated_at = _now()
        s.flush()
        return _project_dict(s, p, with_scripts=True)


def delete_project(db: str, actor: Actor, pid: int) -> dict[str, Any]:
    with store.session(db) as s:
        p = _project(s, actor, pid)
        s.delete(p)
    return {"deleted": pid}


# ---------------------------------------------------------------- 项目脚本一览（M6：配置检查项目并入项目）


def list_scripts(db: str, actor: Actor, kind: str | None = None, device_id: int | None = None) -> list[dict[str, Any]]:
    """当前项目全部脚本（平铺）：每份脚本带所在的检查项目（基线与检查设置）、基线设备、最近一次检查、修订数、最后修改人。"""
    out = []
    for cp in list_projects(db, actor):
        if device_id is not None and cp["device_id"] != device_id:
            continue
        with store.session(db) as s:
            rows = list(
                s.scalars(
                    select(CheckScript)
                    .where(CheckScript.project_id == cp["id"])
                    .order_by(CheckScript.position, CheckScript.id)
                )
            )
            for sc in rows:
                if kind and sc.kind != kind:
                    continue
                last = _latest(s, sc.id)
                d = _script_dict(s, sc, content=False)
                d.update(
                    group={"id": cp["id"], "name": cp["name"]},
                    baseline={
                        "device": cp["device"],
                        "version_id": cp["version_id"],
                        "follows_latest": cp["version_id"] is None,
                    },
                    order_check=cp["order_check"] if sc.kind == "change" else None,
                    ai_check=cp["ai_check"],
                    author=last.author if last else "",
                )
                out.append(d)
    out.sort(key=lambda x: x["updated_at"] or "", reverse=True)
    return out


def create_project_script(db: str, actor: Actor, data: dict[str, Any]) -> dict[str, Any]:
    """在项目里新建一份脚本：同时建一个只含这份脚本的检查项目，保存基线与检查设置（预览“新建脚本”对话框）。"""
    cp = create_project(
        db,
        actor,
        {
            "name": data.get("name"),
            "description": "",
            "device_id": data.get("device_id"),
            "version_id": data.get("version_id"),
            "profile": data.get("profile"),
            "default_kind": data.get("kind"),
            "order_check": data.get("order_check", True),
            "ai_check": data.get("ai_check", False),
            "ai_rules": data.get("ai_rules"),
        },
    )
    sc = create_script(
        db, actor, cp["id"], {"name": data.get("name"), "kind": data.get("kind"), "content": data.get("content")}
    )
    return {"group": cp, "script": sc}


# ---------------------------------------------------------------- 脚本


def create_script(db: str, actor: Actor, pid: int, data: dict[str, Any]) -> dict[str, Any]:
    with store.session(db) as s:
        p = _project(s, actor, pid)
        content = _text(data.get("content"))
        pos = (s.scalar(select(func.max(CheckScript.position)).where(CheckScript.project_id == p.id)) or 0) + 1
        sc = CheckScript(
            project_id=p.id,
            name=_name(data.get("name")),
            kind=_kind(data.get("kind") or p.default_kind),
            content=content,
            position=pos,
        )
        s.add(sc)
        s.flush()
        _add_revision(s, actor, sc, content, "create")
        p.updated_at = _now()
        return _script_dict(s, sc)


def get_script(db: str, actor: Actor, pid: int, sid: int) -> dict[str, Any]:
    with store.session(db) as s:
        return _script_dict(s, _script(s, actor, pid, sid)[1])


def update_script(db: str, actor: Actor, pid: int, sid: int, data: dict[str, Any]) -> dict[str, Any]:
    """改名、改类型、保存内容（内容变化时形成一条 manual 修订）。"""
    with store.session(db) as s:
        p, sc = _script(s, actor, pid, sid)
        if "name" in data and data["name"] is not None:
            sc.name = _name(data["name"])
        if "kind" in data and data["kind"] is not None:
            sc.kind = _kind(data["kind"])
        rev = None
        if "content" in data and data["content"] is not None:
            content = _text(data["content"])
            last = _latest(s, sc.id)
            if last is None or last.content != content:
                rev = _add_revision(s, actor, sc, content, "manual", summary=data.get("summary"))
            if content != sc.content:
                sc.content = content
                sc.last_check = None
        if "position" in data and data["position"] is not None:
            sc.position = int(data["position"])
        sc.updated_at = p.updated_at = _now()
        s.flush()
        out = _script_dict(s, sc)
        out["revision"] = _rev_dict(rev) if rev else None
        return out


def delete_script(db: str, actor: Actor, pid: int, sid: int) -> dict[str, Any]:
    with store.session(db) as s:
        p, sc = _script(s, actor, pid, sid)
        s.delete(sc)
        p.updated_at = _now()
    return {"deleted": sid}


# ---------------------------------------------------------------- 修订


def revisions(db: str, actor: Actor, pid: int, sid: int) -> list[dict[str, Any]]:
    with store.session(db) as s:
        _script(s, actor, pid, sid)
        rows = s.scalars(select(CheckRevision).where(CheckRevision.script_id == sid).order_by(CheckRevision.seq.desc()))
        return [_rev_dict(r) for r in rows]


def _revision(s: Any, actor: Actor, pid: int, sid: int, rid: int) -> tuple[CheckScript, CheckRevision]:
    _, sc = _script(s, actor, pid, sid)
    r = s.get(CheckRevision, rid)
    if r is None or r.script_id != sc.id:
        raise ProjectError("check_project.revision_not_found", "not_found", id=rid)
    return sc, r


def get_revision(db: str, actor: Actor, pid: int, sid: int, rid: int) -> dict[str, Any]:
    with store.session(db) as s:
        return _rev_dict(_revision(s, actor, pid, sid, rid)[1], content=True)


def restore(db: str, actor: Actor, pid: int, sid: int, rid: int) -> dict[str, Any]:
    """恢复到某个修订：脚本内容改为该修订的内容，并形成一条 restore 修订。"""
    with store.session(db) as s:
        sc, r = _revision(s, actor, pid, sid, rid)
        sc.content = r.content
        sc.last_check = None
        sc.updated_at = _now()
        new = _add_revision(s, actor, sc, r.content, "restore", note={"from_seq": r.seq, "from_id": r.id})
        out = _script_dict(s, sc)
        out["revision"] = _rev_dict(new)
        return out


# ---------------------------------------------------------------- 检查、重排


def baseline_of(db: str, kb: KnowledgeBase, actor: Actor, pid: int) -> script_check.Baseline | None:
    with store.session(db) as s:
        p = _project(s, actor, pid)
        dev, ver, prof = p.device_id, p.version_id, p.profile or None
    if dev is None:
        return None
    try:
        return script_check.baseline_from_db(db, kb, dev, ver, prof)
    except script_check.ScriptCheckError as e:
        raise ProjectError(e.key, e.kind, **e.fmt) from e


def settings_of(db: str, actor: Actor, pid: int) -> dict[str, Any]:
    with store.session(db) as s:
        p = _project(s, actor, pid)
        return {
            "order": p.order_check,
            "ai": p.ai_check,
            "ai_rules": list(p.ai_rules or []),
            "profile": p.profile or None,
        }


def check(
    db: str,
    kb: KnowledgeBase,
    actor: Actor,
    pid: int,
    sid: int,
    content: str | None = None,
    kind: str | None = None,
    order: bool | None = None,
    ai: dict[str, Any] | None = None,
    namer: Any = None,
    lang: str = "zh-CN",
) -> dict[str, Any]:
    """检查脚本：content 不给时检查保存的内容；检查保存的内容时把摘要记在脚本上（项目列表显示）。"""
    with store.session(db) as s:
        p, sc = _script(s, actor, pid, sid)
        text = sc.content if content is None else _text(content)
        use_kind = _kind(kind or sc.kind)
        use_order = p.order_check if order is None else order
        saved = text == sc.content
        prof = p.profile or None
    base = baseline_of(db, kb, actor, pid)
    try:
        r = script_check.check_text(text, kb, base, use_kind, use_order, profile=prof, namer=namer, lang=lang, ai=ai)
    except script_check.ScriptCheckError as e:
        raise ProjectError(e.key, e.kind, **e.fmt) from e
    out = script_check.public(r)
    if saved:
        summ = {
            "errors": out["summary"]["errors"],
            "warnings": out["summary"]["warnings"],
            "infos": out["summary"]["infos"],
            "order": use_order,
            "kind": use_kind,
            "at": iso(_now()),
        }
        with store.session(db) as s:
            sc2 = s.get(CheckScript, sid)
            if sc2 is not None:
                sc2.last_check = summ
    out["script"] = {"id": sid, "saved": saved, "kind": use_kind}
    return out


def reorder(
    db: str,
    kb: KnowledgeBase,
    actor: Actor,
    pid: int,
    sid: int,
    content: str | None = None,
    apply: bool = False,
    namer: Any = None,
    lang: str = "zh-CN",
) -> dict[str, Any]:
    """按依赖重排。apply=False 只给出结果（新脚本、移动与原因、重排前后的顺序错误数）；
    apply=True 时保存：重排前的内容（与最新修订不同时）先存一条 manual 修订，再存重排后的 reorder 修订。"""
    with store.session(db) as s:
        _, sc = _script(s, actor, pid, sid)
        text = sc.content if content is None else _text(content)
        kind = sc.kind
    if kind != "change":
        raise ProjectError("check_project.reorder_change_only")
    base = baseline_of(db, kb, actor, pid)
    if base is None:
        raise ProjectError("script_check.need_baseline")
    try:
        r = script_check.reorder_text(text, kb, base, namer=namer, lang=lang)
    except script_check.ScriptCheckError as e:
        raise ProjectError(e.key, e.kind, **e.fmt) from e
    r["original"] = text
    if apply and r["changed"]:
        with store.session(db) as s:
            _, sc = _script(s, actor, pid, sid)
            last = _latest(s, sc.id)
            before = None
            if last is None or last.content != text:
                before = _add_revision(s, actor, sc, text, "manual", summary=r.get("before", {}).get("summary"))
            note = {
                "moves": [
                    {"line": m["line"], "new_line": m["new_line"], "text": m["text"], "reasons": m["reasons"]}
                    for m in r["moves"]
                ],
                "before_seq": before.seq if before else (last.seq if last else None),
            }
            after = _add_revision(
                s, actor, sc, r["script"], "reorder", note=note, summary=r.get("after", {}).get("summary")
            )
            sc.content = r["script"]
            sc.last_check = None
            sc.updated_at = _now()
            r["revision"] = _rev_dict(after)
            r["before_revision"] = _rev_dict(before) if before else None
    r["applied"] = bool(apply and r["changed"])
    return r


# ---------------------------------------------------------------- 对比


def _side_text(s: Any, actor: Actor, db: str, kb: KnowledgeBase, side: dict[str, Any]) -> tuple[str, str, str, int]:
    """对比的一侧 → (文本, 名称, 类型 change/full/baseline, 项目编号)。"""
    t = side.get("type")
    if t == "revision":
        r = s.get(CheckRevision, int(side.get("revision_id") or 0))
        if r is None:
            raise ProjectError("check_project.revision_not_found", "not_found", id=side.get("revision_id"))
        sc = s.get(CheckScript, r.script_id)
        p = _project(s, actor, sc.project_id)
        return r.content, f"{sc.name} #{r.seq}", sc.kind, p.id
    if t == "script":
        sc = s.get(CheckScript, int(side.get("script_id") or 0))
        if sc is None:
            raise ProjectError("check_project.script_not_found", "not_found", id=side.get("script_id"))
        p = _project(s, actor, sc.project_id)
        text = sc.content if side.get("text") is None else _text(side.get("text"))
        return text, sc.name, sc.kind, p.id
    if t == "baseline":
        p = _project(s, actor, int(side.get("project_id") or 0))
        return "", "", "baseline", p.id
    if t == "text":
        return (
            _text(side.get("text")),
            str(side.get("label") or "text"),
            _kind(side.get("kind") or "full"),
            int(side.get("project_id") or 0),
        )
    raise ProjectError("check_project.bad_side", side=str(t))


def _graph_of(kb: KnowledgeBase, text: str, kind: str, base: script_check.Baseline | None, profile: str | None) -> Any:
    if kind == "baseline":
        return base.graph if base else None
    if kind == "change":
        if base is None:
            return None
        r = script_check.check_text(text, kb, base, "change", False, with_reorder=False)
        return r["_final_graph"]
    return compare.side_from_text(text, kb, profile or (base.profile if base else None), "x").graph


def diff(
    db: str,
    kb: KnowledgeBase,
    actor: Actor,
    a: dict[str, Any],
    b: dict[str, Any],
    ignore_order: bool = False,
    semantic: bool = True,
    namer: Any = None,
) -> dict[str, Any]:
    """两个对象（修订 / 脚本 / 基线配置 / 文本）的文本差异，加上语义差异（按有效值比较；变更脚本比较的是在基线上执行后的结果）。"""
    with store.session(db) as s:
        ta, la, ka, pa = _side_text(s, actor, db, kb, a)
        tb, lb, kb_, pb = _side_text(s, actor, db, kb, b)
    pid = pa or pb
    base = baseline_of(db, kb, actor, pid) if pid else None
    if ka == "baseline":
        if base is None:
            raise ProjectError("script_check.need_baseline")
        ta, la = base.text, base.label or base.device
    if kb_ == "baseline":
        if base is None:
            raise ProjectError("script_check.need_baseline")
        tb, lb = base.text, base.label or base.device
    out = textdiff.diff(ta, tb, ignore_order)
    out["unified"] = textdiff.unified(ta, tb, la, lb)
    out["a"] = {"label": la, "kind": ka}
    out["b"] = {"label": lb, "kind": kb_}
    out["semantic"] = None
    if semantic:
        try:
            ga = _graph_of(kb, ta, ka, base, None)
            gb = _graph_of(kb, tb, kb_, base, None)
        except Exception as e:  # 解析失败（脚本有错误、没有基线）时只给文本差异
            out["semantic_error"] = getattr(e, "key", type(e).__name__)
            ga = gb = None
        if ga is not None and gb is not None:
            c = compare.compare(compare.Side(ga, la or "A"), compare.Side(gb, lb or "B"), kb)
            out["semantic"] = {
                "equal": c["equal"],
                "summary": c["summary"],
                "diffs": [
                    {
                        "kind": d["kind"],
                        "node": d["node"],
                        "label": namer(d["node"]) if namer else d["node"],
                        "a": d.get("a"),
                        "b": d.get("b"),
                    }
                    for d in c["diffs"][:300]
                ],
            }
    return out
