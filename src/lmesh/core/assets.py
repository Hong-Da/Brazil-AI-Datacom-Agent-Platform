"""工作空间里的私有内容（REQ-035 / REQ-036）：我的翻译规则集、我的模板的归属。CLI 与 API 共用。

文件仍放在原处（规则集 data/translate-rules/，私有模板 data/user-templates/），归属记在数据库 user_assets 表。
- 内置规则集 / 内置与共享模板：所有人可用；共享模板只有管理员与知识库维护员可以修改。
- 有属主的规则集与私有模板：只有属主（与管理员）能看到和修改。
- 没有属主的规则集（M6 之前保存的、全局令牌或命令行保存的）：作为共享规则集，所有人可用，管理员与维护员可以修改。
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import delete, select

from lmesh.core import store
from lmesh.core.projects import Identity, ProjectError
from lmesh.core.store.models import User, UserAsset

KINDS = ("template", "ruleset")
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def owners(db_url: str, kind: str) -> dict[str, tuple[int, str]]:
    """{编号: (属主编号, 属主账号)}。"""
    with store.session(db_url) as s:
        rows = s.execute(
            select(UserAsset.asset_id, User.id, User.username)
            .join(User, User.id == UserAsset.user_id)
            .where(UserAsset.kind == kind)
        ).all()
        return {a: (int(uid), str(name)) for a, uid, name in rows}


def owner_of(db_url: str, kind: str, asset_id: str) -> tuple[int, str] | None:
    return owners(db_url, kind).get(asset_id)


def claim(db_url: str, kind: str, asset_id: str, user_id: int) -> None:
    with store.session(db_url) as s:
        row = s.scalar(select(UserAsset).where(UserAsset.kind == kind, UserAsset.asset_id == asset_id))
        if row is None:
            s.add(UserAsset(kind=kind, asset_id=asset_id, user_id=user_id))
        else:
            row.user_id = user_id


def release(db_url: str, kind: str, asset_id: str) -> None:
    with store.session(db_url) as s:
        s.execute(delete(UserAsset).where(UserAsset.kind == kind, UserAsset.asset_id == asset_id))


def scope_of(db_url: str, kind: str, asset_id: str, builtin: bool, ident: Identity | None) -> str:
    """builtin 内置 / shared 共享 / mine 我的 / user 别人的（只有管理员能看到）/ hidden 无权查看。"""
    if builtin:
        return "builtin"
    own = owner_of(db_url, kind, asset_id)
    if own is None:
        return "shared"
    if ident is None or (ident.user_id is not None and own[0] == ident.user_id):
        return "mine"
    return "user" if ident.is_admin else "hidden"


def can_write(scope: str, ident: Identity | None) -> bool:
    if scope == "builtin":
        return False
    if scope == "mine":
        return True
    return ident is None or (ident.is_kb_editor if scope == "shared" else ident.is_admin)


def ensure_readable(db_url: str, kind: str, asset_id: str, builtin: bool, ident: Identity | None) -> str:
    sc = scope_of(db_url, kind, asset_id, builtin, ident)
    if sc == "hidden":
        raise ProjectError(f"assets.{kind}_not_found", "not_found", id=asset_id)
    return sc


def ensure_writable(db_url: str, kind: str, asset_id: str, builtin: bool, ident: Identity | None) -> str:
    sc = ensure_readable(db_url, kind, asset_id, builtin, ident)
    if not can_write(sc, ident):
        raise ProjectError("assets.shared_readonly", "forbidden", id=asset_id)
    return sc


def copy_ruleset_for(db_url: str, rid: str, old_owner: int, new_owner: int, new_name: str) -> str | None:
    """项目转交时：项目用到的、原属主私有的规则集复制一份给新属主，返回新编号（规则集不是原属主私有的返回 None）。"""
    own = owner_of(db_url, "ruleset", rid)
    if own is None or own[0] != old_owner:
        return None
    from lmesh.core import naming

    hit = naming.find_file(None, rid)
    if hit is None or hit[1]:
        return None
    base = _SAFE.sub("-", f"{rid}-{new_name}")[:60]
    cand, n = base, 2
    while naming.find_file(None, cand) is not None:
        cand, n = f"{base}-{n}"[:64], n + 1
    data = naming.parse(hit[0].read_text(encoding="utf-8"), None, rid).as_dict()
    naming.save(None, cand, {**data, "id": cand}, None, overwrite=False)
    claim(db_url, "ruleset", cand, new_owner)
    return cand


def dispose_user(db_url: str, user_id: int, transfer_to: int | None) -> dict[str, Any]:
    """删除账号时：私有规则集与模板转交给 transfer_to，或删除文件。"""
    from lmesh.core import naming
    from lmesh.core import template as tmod

    moved, removed = [], []
    with store.session(db_url) as s:
        rows = list(s.scalars(select(UserAsset).where(UserAsset.user_id == user_id)))
        for r in rows:
            if transfer_to is not None:
                r.user_id = transfer_to
                moved.append(f"{r.kind}:{r.asset_id}")
            else:
                if r.kind == "ruleset":
                    hit = naming.find_file(None, r.asset_id)
                    if hit is not None and not hit[1]:
                        hit[0].unlink()
                else:
                    f = tmod.private_dir() / f"{r.asset_id}.yaml"
                    if f.is_file():
                        f.unlink()
                s.delete(r)
                removed.append(f"{r.kind}:{r.asset_id}")
    return {"moved": moved, "removed": removed}
