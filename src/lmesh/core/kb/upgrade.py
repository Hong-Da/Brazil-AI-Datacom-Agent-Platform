"""升级时合并程序自带的知识库（REQ-046）。

运行时知识库仓库里有一个 builtin 分支，每个程序版本把自带知识库 knowledge/ 的快照提交到这个分支（提交信息含程序版本）。
升级时按三方比较合并到主线：基准 = builtin 分支最新快照，我方 = 运行时知识库工作区，对方 = 本次自带知识库。

- 只有对方改了（我方与基准相同）：直接采用新版本（新增、修改、删除）；
- 只有我方改了，或双方改成一样：保留；
- 双方都改了同一文件：不覆盖，保留用户版本，冲突送审核队列（kind=conflict，source.via=kb-upgrade），维护员选用哪一边；
- 旧安装（没有 builtin 分支，不知道上一个自带版本）：与本次自带版本不同的文件全部当作冲突；只在用户知识库里有的文件保留。

合并后提交一次并打一个发布标签（标签说明里记下升级前的提交，`rollback_last` 据此回滚）；最后把 builtin 分支推进到本次快照。
比较只看 git 历史与文件内容，不看文件时间。
"""

from __future__ import annotations

import base64
import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dulwich.objects import Blob, Commit, Tree
from dulwich.refs import Ref
from dulwich.repo import Repo

from lmesh.core.kb import repo as kbrepo

BRANCH = Ref(b"refs/heads/builtin")
VIA = "kb-upgrade"
MARK = "kb-upgrade before="  # 发布标签说明里记录升级前提交的写法


@dataclass
class Plan:
    """合并计划：各列表都是相对路径。"""

    app_version: str
    has_base: bool
    changed: bool  # 自带知识库与 builtin 分支最新快照不同
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)  # 只有用户改过（或只在用户知识库里）的文件
    before: str | None = None
    commit: str | None = None
    release: str | None = None
    review_items: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


# ---------- 文件与 git 对象 ----------


def _read_dir(root: Path) -> dict[str, bytes]:
    return {f: (root / f).read_bytes() for f in kbrepo._files(root)}


def _tree_files(r: Repo, tree_id: bytes) -> dict[str, bytes]:
    out: dict[str, bytes] = {}

    def walk(tid: bytes, prefix: str) -> None:
        tree = r[tid]
        assert isinstance(tree, Tree)
        for e in tree.items():
            name = prefix + e.path.decode("utf-8")
            obj = r[e.sha]
            if isinstance(obj, Tree):
                walk(obj.id, name + "/")
            else:
                assert isinstance(obj, Blob)
                out[name] = obj.data

    walk(tree_id, "")
    return out


def _write_tree(r: Repo, files: dict[str, bytes]) -> bytes:
    """把文件写成 git 树对象（逐层），返回根树编号。"""
    nested: dict[str, Any] = {}
    for path, data in files.items():
        node = nested
        *dirs, name = path.split("/")
        for d in dirs:
            node = node.setdefault(d, {})
        node[name] = data

    def build(node: dict[str, Any]) -> Any:
        tree = Tree()
        for name, v in node.items():
            if isinstance(v, dict):
                tree.add(name.encode("utf-8"), 0o040000, build(v))
            else:
                blob = Blob.from_string(v)
                r.object_store.add_object(blob)
                tree.add(name.encode("utf-8"), 0o100644, blob.id)
        r.object_store.add_object(tree)
        return tree.id

    return build(nested)


def builtin_tip(root: Path) -> Commit | None:
    if not (root / ".git").exists():
        return None
    with Repo(str(root)) as r:
        try:
            obj = r[r.refs[BRANCH]]
        except KeyError:
            return None
        assert isinstance(obj, Commit)
        return obj


def snapshot_builtin(root: Path, builtin: Path, app_version: str) -> str:
    """把自带知识库的快照提交到 builtin 分支（父提交为分支原来的最新快照）。返回提交编号。"""
    files = _read_dir(builtin)
    with Repo(str(root)) as r:
        tree_id = _write_tree(r, files)
        c = Commit()
        c.tree = tree_id
        try:
            c.parents = [r.refs[BRANCH]]
        except KeyError:
            c.parents = []
        c.author = c.committer = kbrepo.AUTHOR
        c.author_time = c.commit_time = int(time.time())
        c.author_timezone = c.commit_timezone = 0
        c.encoding = b"UTF-8"
        c.message = f"程序自带知识库（LucidMesh {app_version}）".encode()
        r.object_store.add_object(c)
        r.refs[BRANCH] = c.id
        return c.id.decode()


def ensure_baseline(root: Path, builtin: Path, app_version: str) -> bool:
    """首次从自带知识库复制并初始化仓库后，建立 builtin 分支作为以后升级的基准。已有分支时不动。"""
    if not builtin.exists() or builtin_tip(root) is not None:
        return False
    snapshot_builtin(root, builtin, app_version)
    return True


# ---------- 合并 ----------


def plan(root: Path, builtin: Path, app_version: str) -> tuple[Plan, dict[str, bytes], dict[str, bytes]]:
    """计算合并计划；返回（计划、我方文件、对方文件）。不写入。"""
    theirs = _read_dir(builtin)
    ours = _read_dir(root)
    tip = builtin_tip(root)
    base: dict[str, bytes] | None = None
    if tip is not None:
        with Repo(str(root)) as r:
            base = _tree_files(r, tip.tree)
    p = Plan(app_version=app_version, has_base=base is not None, changed=base != theirs)
    if not p.changed:
        return p, ours, theirs
    for f in sorted(set(ours) | set(theirs) | set(base or {})):
        o, t = ours.get(f), theirs.get(f)
        if o == t:
            continue
        if base is None:
            # 旧安装：不知道上一个自带版本，保守处理
            (p.kept if t is None else p.conflicts).append(f)
            continue
        b = base.get(f)
        if o == b:
            (p.removed if t is None else p.added if o is None else p.updated).append(f)
        elif t == b:
            p.kept.append(f)
        else:
            p.conflicts.append(f)
    return p, ours, theirs


def _next_release(root: Path) -> str:
    """升级合并的发布号：在最新发布号（没有时用 kb.yaml 的 kb_version）上加一个修订号。"""
    rels = kbrepo.releases(root)
    have = {r.version for r in rels}
    base = rels[0].version if rels else ""
    if not base:
        kb_yaml = root / "kb.yaml"
        text = kb_yaml.read_text(encoding="utf-8") if kb_yaml.exists() else ""
        m = re.search(r"kb_version:\s*['\"]?([0-9][^'\"\s]*)", text)
        base = m.group(1) if m else "0.0.0"
    nums = [int(x) for x in re.findall(r"\d+", base)[:3]] + [0, 0, 0]
    major, minor, patch = nums[:3]
    while True:
        patch += 1
        v = f"{major}.{minor}.{patch}"
        if v not in have:
            return v


def _queue_conflict(db_url: str, f: str, ours: bytes | None, theirs: bytes | None, app_version: str) -> int:
    """冲突送审核队列。同一文件已有待审的升级冲突时更新那一条（以最新的自带版本为准）。"""
    from lmesh.core import review, store

    deleted = theirs is None
    data = theirs or b""
    payload = {
        "theirs_b64": base64.b64encode(data).decode(),
        "theirs_sha256": "" if deleted else hashlib.sha256(data).hexdigest(),
        "ours_sha256": hashlib.sha256(ours).hexdigest() if ours is not None else "",
        "theirs_preview": data[:4000].decode("utf-8", "replace"),
        "theirs_deleted": deleted,
        "ours_missing": ours is None,
    }
    source = {"via": VIA, "app_version": app_version}
    title = f"升级冲突（新版本已删除）：{f}" if deleted else f"升级冲突：{f}"
    store.upgrade(db_url)
    with store.session(db_url) as s:
        for item in review.list_items_raw(s, kind="conflict", status="pending"):
            if item.target == f and (item.source or {}).get("via") == VIA:
                item.payload, item.source, item.title = payload, source, title
                return int(item.id)
    return review.add(db_url, "conflict", title, f, payload, source)


@kbrepo.locked
def upgrade(root: Path, builtin: Path, app_version: str, db_url: str | None, dry_run: bool = False) -> Plan:
    """把自带知识库合并进运行时知识库。dry_run 只返回计划。冲突需要 db_url（送审核队列）。"""
    p, ours, theirs = plan(root, builtin, app_version)
    if dry_run or not p.changed:
        return p
    if p.conflicts and not db_url:
        raise ValueError("kb upgrade needs a database for conflicts")
    kbrepo.commit_all(root, "升级前保存工作区")
    with Repo(str(root)) as r:
        try:
            p.before = r.head().decode()
        except KeyError:
            p.before = None
    for f in p.added + p.updated:
        target = root / f
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(theirs[f])
    for f in p.removed:
        (root / f).unlink(missing_ok=True)
    for d in sorted(
        (x for x in root.rglob("*") if x.is_dir() and ".git" not in x.relative_to(root).parts), reverse=True
    ):
        if not any(d.iterdir()):
            d.rmdir()
    adopted = len(p.added) + len(p.updated) + len(p.removed)
    summary = f"采用 {adopted} 个文件，{len(p.conflicts)} 个冲突待审核"
    p.commit = kbrepo.commit_all(root, f"合并程序自带知识库（LucidMesh {app_version}）：{summary}")
    if p.commit and p.before:
        version = _next_release(root)
        p.release = kbrepo.tag(
            root, version, f"升级合并程序自带知识库（LucidMesh {app_version}）：{summary}。{MARK}{p.before}"
        )
    for f in p.conflicts:
        p.review_items.append(_queue_conflict(str(db_url), f, ours.get(f), theirs.get(f), app_version))
    snapshot_builtin(root, builtin, app_version)
    return p


def last_upgrade(root: Path) -> dict[str, Any] | None:
    """最近一次升级合并的发布记录（含升级前的提交）。"""
    for rel in kbrepo.releases(root):
        if MARK in rel.message:
            return {**rel.__dict__, "before": rel.message.split(MARK, 1)[1].strip()}
    return None


@kbrepo.locked
def rollback_last(root: Path) -> dict[str, Any] | None:
    """回滚最近一次升级合并：工作区恢复成升级前的提交再提交一次。builtin 分支不回退，所以不会再次自动合并。"""
    last = last_upgrade(root)
    if last is None:
        return None
    sha = kbrepo.rollback(root, last["before"])
    return {"release": last["tag"], "before": last["before"], "commit": sha}
