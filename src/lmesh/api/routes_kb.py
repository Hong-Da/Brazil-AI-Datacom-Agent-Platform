"""知识库与审核队列接口。都需要令牌。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from lmesh.api.common import E_NOT_FOUND, E_PARAM, E_STATE, ApiError, lang_of, ok, require_token, settings_of
from lmesh.core import i18n, kbservice, review, store
from lmesh.core.kb import package, repo

router = APIRouter(dependencies=[Depends(require_token)])


def _root(request: Request):  # type: ignore[no-untyped-def]
    return kbservice.runtime_root(settings_of(request))


def _db(request: Request) -> str:
    url = settings_of(request).database_url
    store.upgrade(url)
    return url


@router.post("/kb/validate", summary="校验知识库")
def kb_validate(request: Request) -> dict[str, Any]:
    return ok(request, kbservice.validate_report(_root(request)))


@router.get("/kb/export", summary="导出知识库包（zip）", response_class=Response)
def kb_export(request: Request) -> Response:
    root = _root(request)
    data = package.export(root)
    version = package.kb_version(root)
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="lmesh-kb-{version}.zip"'},
    )


@router.post("/kb/import", summary="导入知识库包：新文件直接加入，冲突送审核队列")
async def kb_import(request: Request, file: UploadFile = File(...), dry_run: bool = Query(False)) -> dict[str, Any]:
    try:
        res = kbservice.import_package(_root(request), await file.read(), _db(request), dry_run=dry_run)
    except (package.PackageError, ValueError) as e:
        raise ApiError(E_PARAM, 422, data={"detail": str(e)}) from e
    if res["issues"]:
        raise ApiError(E_PARAM, 422, "kb.import_invalid", data=res)
    return ok(request, res)


@router.get("/kb/releases", summary="已发布的知识库版本与提交历史")
def kb_releases(request: Request) -> dict[str, Any]:
    root = _root(request)
    return ok(
        request,
        {
            "releases": kbservice.releases(root),
            "history": repo.history(root, 30),
            "kb_version": kbservice.load(root).version,
        },
    )


class ReleaseBody(BaseModel):
    version: str | None = None
    message: str = ""


@router.post("/kb/releases", summary="发布知识库版本：校验 → 回归测试 → 打标签")
def kb_release(request: Request, body: ReleaseBody) -> dict[str, Any]:
    from lmesh.core import roundtrip_hook

    try:
        res = kbservice.release(_root(request), body.version, body.message, roundtrip_hook.regression)
    except kbservice.ReleaseError as e:
        raise ApiError(E_STATE, 409, e.key, data=e.data, version=e.data if isinstance(e.data, str) else "") from e
    return ok(request, res)


@router.get("/kb/diff", summary="对比两个知识库版本（只给 from 时与工作区对比）")
def kb_diff(
    request: Request, ref_from: str = Query(..., alias="from"), ref_to: str | None = Query(None, alias="to")
) -> dict[str, Any]:
    try:
        return ok(request, kbservice.diff(_root(request), ref_from, ref_to))
    except KeyError as e:
        raise ApiError(E_NOT_FOUND, 404) from e


class RollbackBody(BaseModel):
    ref: str


@router.post("/kb/rollback", summary="回滚到某个已发布版本（历史保留）")
def kb_rollback(request: Request, body: RollbackBody) -> dict[str, Any]:
    try:
        sha = repo.rollback(_root(request), body.ref)
    except KeyError as e:
        raise ApiError(E_NOT_FOUND, 404) from e
    return ok(request, {"ref": body.ref, "commit": sha})


@router.get("/kb/coverage", summary="覆盖矩阵")
def kb_coverage(request: Request, profile: str | None = None) -> dict[str, Any]:
    try:
        return ok(request, kbservice.coverage(_root(request), profile))
    except KeyError as e:
        raise ApiError(E_NOT_FOUND, 404) from e


# ---------- 审核队列 ----------


@router.get("/review", summary="审核队列")
def review_list(
    request: Request,
    status: str = "pending",
    kind: str | None = None,
    limit: int = Query(200, le=1000),
    offset: int = 0,
) -> dict[str, Any]:
    db = _db(request)
    data = review.list_items(db, None if status == "all" else status, kind, limit, offset)
    data["counts"] = review.counts(db)
    return ok(request, data)


@router.get("/review/{item_id}", summary="审核条目详情")
def review_get(request: Request, item_id: int) -> dict[str, Any]:
    item = review.get(_db(request), item_id)
    if not item:
        raise ApiError(E_NOT_FOUND, 404)
    root = _root(request)
    if item["kind"] == "card":
        # 附上知识库中这张卡的当前内容（视图、参数、缺省值、映射），详情页与“修改后通过”要用
        from lmesh.core.kb import files as kbfiles

        found = kbfiles.find_card(root, str(item["target"]))
        item["current"] = kbfiles._plain(found[1]["cards"][found[2]]) if found else None
    elif item["kind"] == "conflict" and item.get("target"):
        target = (root / str(item["target"])).resolve()
        if target.is_relative_to(root.resolve()) and target.is_file():
            item["current_preview"] = target.read_text(encoding="utf-8", errors="replace")[:4000]
    return ok(request, item)


class DecideBody(BaseModel):
    action: Literal["approve", "reject"]
    note: str = ""
    edited: dict[str, Any] | None = None


@router.post("/review/{item_id}", summary="通过（可带修改）或驳回")
def review_decide(request: Request, item_id: int, body: DecideBody) -> dict[str, Any]:
    try:
        res = review.decide(_db(request), _root(request), item_id, body.action == "approve", body.note, body.edited)
    except review.ReviewError as e:
        code, status = (E_NOT_FOUND, 404) if str(e) == "review.not_found" else (E_STATE, 409)
        raise ApiError(code, status, str(e)) from e
    return ok(request, res)


def _msg(request: Request, key: str) -> str:
    return i18n.t(key, lang_of(request))
