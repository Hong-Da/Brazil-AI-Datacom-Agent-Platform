"""配置接口：脱敏、导入、设备列表。都需要令牌。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, Field

from lmesh.api.common import E_PARAM, ApiError, lang_of, ok, require_token, settings_of
from lmesh.core import i18n, importer, store
from lmesh.core.sanitize import SanitizeLeak, Sanitizer, local_key

router = APIRouter(dependencies=[Depends(require_token)])


class SanitizeBody(BaseModel):
    text: str = Field(..., max_length=importer.MAX_BYTES)
    level: Literal["basic", "strict"] = "basic"


@router.post("/sanitize", summary="配置脱敏（返回脱敏后的文本与不含原值的替换报告）")
def sanitize(request: Request, body: SanitizeBody) -> dict[str, Any]:
    try:
        result = Sanitizer(body.level, local_key()).sanitize(body.text.replace("\r\n", "\n"))
    except SanitizeLeak as e:
        raise ApiError(E_PARAM, 422, data={"detail": str(e)}) from e
    return ok(
        request,
        {"text": result.text, "vendor": result.vendor, "summary": result.summary(), "report": result.public_report()},
    )


@router.post("/configs", summary="导入配置（可多个文件或 zip；识别厂商 → 脱敏 → 入库）")
async def import_configs(
    request: Request, files: list[UploadFile] = File(...), level: Literal["basic", "strict"] = Form("basic")
) -> dict[str, Any]:
    if not files:
        raise ApiError(E_PARAM, 422)
    sources: list[tuple[str, bytes]] = []
    for f in files:
        data = await f.read()
        sources.extend(importer.iter_bytes(f.filename or "upload.txt", data))
    url = settings_of(request).database_url
    store.upgrade(url)
    lang = lang_of(request)
    results = []
    from lmesh.core import kbservice

    kb_root = kbservice.runtime_root(settings_of(request))
    keep = int(settings_of(request).get("history.keep"))
    for r in importer.import_sources(sources, url, level, kb_root, source_kind="api", actor="api", keep=keep):
        d = r.as_dict()
        if not r.ok:
            d["error"] = i18n.t(r.error, lang)
        results.append(d)
    return ok(request, {"files": results})


@router.get("/devices", summary="已导入的设备与最新配置版本")
def devices(request: Request) -> dict[str, Any]:
    url = settings_of(request).database_url
    store.upgrade(url)
    from lmesh.core import analysis, kbservice, workbench

    kb = analysis.load_kb(kbservice.runtime_root(settings_of(request)))
    return ok(request, {"devices": workbench.device_rows(url, kb.version), "kb_version": kb.version})
