"""知识库的版本管理：运行时知识库是一个独立的 Git 仓库（dulwich，不依赖系统 git）。

- 每次修改提交一次；发布时更新 kb.yaml 的 kb_version 并打标签 kb-v<版本>。
- 读取任意版本：把该版本的文件树导出到临时目录再加载。
- 回滚：把工作区恢复成某个发布版本的文件，再提交一次（历史不丢）。
"""

from __future__ import annotations

import functools
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import ParamSpec, TypeVar

from dulwich import porcelain
from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo

AUTHOR = b"LucidMesh <lmesh@localhost>"
TAG_PREFIX = "kb-v"


@dataclass
class Release:
    version: str
    tag: str
    commit: str
    time: int
    message: str


P = ParamSpec("P")
T = TypeVar("T")

# 同一进程内修改知识库（写文件 + 提交）的操作串行执行；Web 服务的多个请求线程共用
WRITE_LOCK = threading.RLock()


def locked[**P, T](fn: Callable[P, T]) -> Callable[P, T]:
    """装饰器：在知识库写锁内执行。"""

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        with WRITE_LOCK:
            return fn(*args, **kwargs)

    return wrapper


def ensure_repo(root: Path) -> Repo:
    if (root / ".git").exists():
        return Repo(str(root))
    repo = Repo.init(str(root))
    commit_all(root, "知识库初始版本")
    return repo


def _files(root: Path) -> list[str]:
    return [
        p.relative_to(root).as_posix()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(root).parts
    ]


def commit_all(root: Path, message: str) -> str | None:
    """提交工作区的全部改动（新增、修改、删除）；没有改动时返回 None。"""
    repo = Repo(str(root))
    with repo:
        tracked = set()
        try:
            head_tree = repo[repo[b"HEAD"].tree]  # type: ignore[attr-defined]
            assert isinstance(head_tree, Tree)
            tracked = {p.decode() for p in _walk(repo, head_tree)}
        except KeyError:
            pass
        current = set(_files(root))
        removed = sorted(tracked - current)
        if removed:
            porcelain.remove(repo, paths=[str(root / r) for r in removed], cached=True)
        porcelain.add(repo, paths=[str(root / f) for f in sorted(current)])
        status = porcelain.status(repo)
        staged = status.staged
        if not (staged["add"] or staged["modify"] or staged["delete"]):
            return None
        sha = porcelain.commit(repo, message=message.encode("utf-8"), author=AUTHOR, committer=AUTHOR)
        return sha.decode() if isinstance(sha, bytes) else str(sha)


def _walk(repo: Repo, tree: Tree, prefix: bytes = b"") -> Iterator[bytes]:
    for entry in tree.items():
        path = prefix + entry.path
        obj = repo[entry.sha]
        if isinstance(obj, Tree):
            yield from _walk(repo, obj, path + b"/")
        else:
            yield path


def tag(root: Path, version: str, message: str) -> str:
    repo = Repo(str(root))
    with repo:
        name = f"{TAG_PREFIX}{version}"
        porcelain.tag_create(repo, name.encode(), author=AUTHOR, message=message.encode("utf-8"), annotated=True)
        return name


def releases(root: Path) -> list[Release]:
    if not (root / ".git").exists():
        return []
    repo = Repo(str(root))
    out: list[Release] = []
    with repo:
        for ref, sha in repo.get_refs().items():
            name = ref.decode()
            if not name.startswith(f"refs/tags/{TAG_PREFIX}"):
                continue
            obj = repo[sha]
            msg = ""
            if not isinstance(obj, Commit):  # 附注标签
                msg = obj.message.decode("utf-8", "replace").strip()  # type: ignore[attr-defined]
                obj = repo[obj.object[1]]  # type: ignore[attr-defined]
            assert isinstance(obj, Commit)
            tagname = name.removeprefix("refs/tags/")
            out.append(Release(tagname.removeprefix(TAG_PREFIX), tagname, obj.id.decode(), obj.commit_time, msg))
    return sorted(out, key=lambda r: (r.time, r.version), reverse=True)


def history(root: Path, limit: int = 50) -> list[dict[str, object]]:
    if not (root / ".git").exists():
        return []
    repo = Repo(str(root))
    with repo:
        out = []
        for entry in repo.get_walker(max_entries=limit):
            c = entry.commit
            out.append(
                {
                    "commit": c.id.decode()[:12],
                    "time": c.commit_time,
                    "message": c.message.decode("utf-8", "replace").strip(),
                }
            )
        return out


def _resolve(repo: Repo, ref: str) -> Commit:
    for cand in (f"refs/tags/{ref}", f"refs/tags/{TAG_PREFIX}{ref}", ref):
        try:
            obj = repo[cand.encode()]
        except KeyError:
            continue
        while not isinstance(obj, Commit):
            obj = repo[obj.object[1]]  # type: ignore[attr-defined]
        return obj
    raise KeyError(ref)


@contextmanager
def checkout_to_temp(root: Path, ref: str) -> Iterator[Path]:
    """把某个版本的文件导出到临时目录（只读用途）。"""
    repo = Repo(str(root))
    tmp = Path(tempfile.mkdtemp(prefix="lmesh-kb-", dir=_tmp_base(root)))
    try:
        with repo:
            commit = _resolve(repo, ref)
            tree = repo[commit.tree]
            assert isinstance(tree, Tree)
            for path in _walk(repo, tree):
                blob = _blob_at(repo, tree, path)
                target = tmp / path.decode()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob.data)
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _blob_at(repo: Repo, tree: Tree, path: bytes) -> Blob:
    obj: object = tree
    for part in path.split(b"/"):
        assert isinstance(obj, Tree)
        obj = repo[obj[part][1]]
    assert isinstance(obj, Blob)
    return obj


def _tmp_base(root: Path) -> str:
    # 临时文件放在项目内的 tmp/（与知识库同一个项目根目录下）
    from lmesh import paths

    base = paths.root_path("tmp")
    base.mkdir(parents=True, exist_ok=True)
    return str(base)


def rollback(root: Path, ref: str) -> str | None:
    """工作区恢复成 ref 的文件并提交一次。"""
    with checkout_to_temp(root, ref) as snap:
        for f in _files(root):
            (root / f).unlink()
        for f in _files(snap):
            target = root / f
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(snap / f, target)
    for d in sorted((p for p in root.rglob("*") if p.is_dir() and ".git" not in p.parts), reverse=True):
        if not any(d.iterdir()):
            d.rmdir()
    return commit_all(root, f"回滚到 {ref}（{time.strftime('%Y-%m-%d %H:%M')}）")


def dirty(root: Path) -> bool:
    repo = Repo(str(root))
    with repo:
        st = porcelain.status(repo)
        return bool(st.unstaged or st.untracked or any(st.staged.values()))
