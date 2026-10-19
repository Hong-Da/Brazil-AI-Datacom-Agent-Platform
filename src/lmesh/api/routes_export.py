"""审计表格导出接口（M5-3）：预置模板、可选的对象与字段、生成表格（JSON 或直接返回 CSV / XLSX 文件）。都需要令牌。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from lmesh.api.common import E_NOT_FOUND, E_PARAM, E_STATE, ApiError, ok, require_token, settings_of
from lmesh.api.routes_topology import ConfigText
from lmesh.core import analysis, export_tables, gquery, history, kbservice, store, topology
from lmesh.core.kb import KnowledgeBase
from lmesh.core.objtable import TableError, fields_of, object_types, resolve_type
from lmesh.core.report import Report

router = APIRouter(dependencies=[Depends(require_token)])
MAX_CONFIGS = 200


def _kb(request: Request) -> tuple[KnowledgeBase, Any]:
    root = kbservice.runtime_root(settings_of(request))
    return analysis.load_kb(root), root


def load_devices(
    request: Request, kb: KnowledgeBase, configs: list[ConfigText], targets: list[str] | None
) -> list[Any]:
    """上传的配置 + 已导入设备的最新快照；targets 为 None 表示全部已导入设备，[] 表示不取数据库中的设备。"""
    try:
        devices = topology.from_texts([c.model_dump() for c in configs], kb)
    except analysis.AnalysisError as e:
        raise ApiError(E_PARAM, 422, str(e), data={"source": getattr(e, "source", "")}, profile="") from e
    if targets is None or targets:
        db = settings_of(request).database_url
        store.upgrade(db)
        found, missing = history.devices_from_db(db, kb, targets)
        if missing:
            raise ApiError(E_NOT_FOUND, 404, "graph.target_not_found", target=", ".join(missing))
        devices += found
    if not devices:
        raise ApiError(E_STATE, 409, "topology.no_devices")
    for d, n in zip(devices, topology.unique_names([d.name for d in devices]), strict=True):
        d.name = n
    return devices


def targets_of(configs: list[ConfigText], devices: list[str | int] | str | None) -> list[str] | None:
    if devices == "all" or (devices is None and not configs):
        return None
    if isinstance(devices, str):
        return [x for x in devices.split(",") if x.strip()]
    return [str(x) for x in devices or []]


@router.get("/export/presets", summary="审计表格的预置模板：对象类型、列（三语表头、Schema 路径）、命名筛选条件")
def get_presets(request: Request, style: Literal["huawei", "cisco", "nokia"] = Query("huawei")) -> dict[str, Any]:
    kb, root = _kb(request)
    try:
        return ok(
            request, {"presets": export_tables.presets(root, kb, style), "derives": sorted(export_tables.DERIVES)}
        )
    except export_tables.ExportError as e:
        raise ApiError(E_STATE, 409, e.key, **e.fmt) from e


@router.get("/export/fields", summary="自定义表格：对象类型列表，或一个对象类型可用的字段（键字段、属性、子对象属性）")
def get_fields(
    request: Request, object: str | None = Query(None, description="对象类型；不给时列出全部对象类型")
) -> dict[str, Any]:
    kb, _ = _kb(request)
    if not object:
        return ok(request, {"objects": object_types(kb)})
    try:
        sn = resolve_type(kb, object)
    except TableError as e:
        raise ApiError(E_NOT_FOUND, 404, "export.bad_object", object=object) from e
    derives = [k for k, (o, _) in export_tables.DERIVES.items() if o == sn.id]
    return ok(request, {"object": sn.id, "fields": fields_of(kb, sn), "derives": derives})


class TableBody(BaseModel):
    """表格：preset（预置模板）或 object（对象类型）至少给一个；设备来自 devices（名称或编号，"all" 为全部）与 configs（上传的配置）。"""

    preset: str | None = Field(
        None,
        description="预置模板编号或别名：ip-address、bridge-domain、bgp-peer、interface-description、vrf、static-route",
    )
    object: str | None = Field(None, description="对象类型（Schema 编号）")
    columns: list[str | dict[str, Any]] | None = Field(
        None, description="列：Schema 路径或 derive:名称，也可以是 {field|derive, label}；不给时用模板的列"
    )
    fields: list[str] | None = Field(None, description="columns 的别名（只给路径）")
    where: list[str] | None = Field(None, description="命名筛选条件；不给时用模板自带的")
    filters: list[dict[str, Any]] = Field(default_factory=list, description="临时筛选条件 [{field, op, value}]")
    devices: list[str | int] | str | None = Field(
        None, description='设备名或编号，"all" 为全部；configs 为空且不给时取全部'
    )
    configs: list[ConfigText] = Field(default_factory=list, max_length=MAX_CONFIGS)
    defaults: bool = Field(True, description="填 Profile 默认值（格子来源标为 default）")
    canonical_names: bool = Field(False, description="接口名统一写成全称")
    style: Literal["huawei", "cisco", "nokia"] = "huawei"
    format: Literal["json", "csv", "xlsx"] = "json"
    lang: Literal["zh-CN", "en", "pt-BR"] = Field("zh-CN", description="表头语言（CSV / XLSX）")
    sheets: Literal["per-device", "single"] = Field("per-device", description="XLSX：每台设备一个工作表或全部一张表")


@router.post(
    "/export/table",
    summary="生成审计表格：format=json 返回表格（每格带来源、节点、行号）；csv / xlsx 直接返回文件",
    response_model=None,
)
def post_table(request: Request, body: TableBody) -> dict[str, Any] | Response:
    kb, root = _kb(request)
    if not body.preset and not body.object:
        raise ApiError(E_PARAM, 422, "export.need_object")
    devices = load_devices(request, kb, body.configs, targets_of(body.configs, body.devices))
    try:
        t = export_tables.build(
            devices,
            kb,
            root,
            preset=body.preset,
            obj=body.object,
            columns=body.columns or body.fields,  # type: ignore[arg-type]
            where=body.where,
            filters=body.filters,
            defaults=body.defaults,
            canonical_names=body.canonical_names,
            style=body.style,
        )
        if body.format == "json":
            return ok(request, t)
        if body.format == "csv":
            name, data = export_tables.to_csv(t, body.lang)
        else:
            name, data = export_tables.to_xlsx(t, body.lang, body.sheets)
    except (export_tables.ExportError, gquery.QueryError) as e:
        kind = getattr(e, "kind", "param")
        if kind == "not_found":
            raise ApiError(E_NOT_FOUND, 404, e.key, **e.fmt) from e
        raise ApiError(E_PARAM, 422, e.key, **e.fmt) from e
    disp = Report(name, "", "").disposition()
    return Response(content=data, media_type=export_tables.MEDIA[body.format], headers={"Content-Disposition": disp})
