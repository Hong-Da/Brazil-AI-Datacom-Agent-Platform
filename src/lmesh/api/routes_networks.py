"""项目内的网络（M9，REQ-045）的管理接口：只挂在 /api/v1/projects/{project}/… 下（project_only）。

- /networks：列表（含文件夹、颜色组、项目概览与各网络汇总）、新建；/networks/{network}：详情、修改、删除、复制；
- /network-folders：文件夹；
- /networks/{network}/members：成员、版本策略、批量；/networks/{network}/join-rules：自动加入规则与命中预览；
- /network-suggestions：建网建议（代码计算，预览）与采纳。
按网络的业务接口（拓扑、检查、脚本……）在 /api/v1/projects/{project}/n/{network}/… 下，见 api/scoping.py。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from lmesh.api.common import db_of, ok, project_error, require_token, settings_of
from lmesh.core import analysis, kbservice, networks, projects

router = APIRouter(dependencies=[Depends(require_token)])

Policy = Literal["follow", "pin"]
Basis = Literal["components", "igp", "bgp", "name", "subnet", "ai"]


def _scope(request: Request) -> projects.Scope:
    return request.state.scope  # type: ignore[no-any-return]


def _kb(request: Request) -> Any:
    try:
        return analysis.load_kb(kbservice.runtime_root(settings_of(request)))
    except Exception:  # noqa: BLE001 - 没有知识库时管理地址与按图计算的建议不可用，其余照常
        return None


def _call(fn: Any, *args: Any, **kw: Any) -> Any:
    try:
        return fn(*args, **kw)
    except projects.ProjectError as e:
        raise project_error(e) from e


# ---------------------------------------------------------------- 网络


@router.get(
    "/networks",
    summary="本项目的网络：各网络的设备数、共用设备、固定版本、脚本、待处理 AI 建议、检查结果、最近活动；文件夹、颜色组、项目概览",
)
def list_networks(request: Request) -> dict[str, Any]:
    return ok(request, _call(networks.list_networks, db_of(request), _scope(request)))


class RuleBody(BaseModel):
    kind: Literal["name", "subnet"] = Field(..., description="name 设备名通配（* ?）/ subnet 管理网段（CIDR）")
    pattern: str = Field(..., max_length=200)
    apply_existing: bool = Field(False, description="同时把现在命中、还不在本网络（也没有被排除）的设备加进来")


class NetworkBody(BaseModel):
    name: str = Field(..., max_length=200)
    slug: str | None = Field(
        None, max_length=64, description="网址里的标识（小写字母、数字、连字符）；不给时由名称生成"
    )
    description: str | None = Field(None, max_length=4000)
    color: str | None = Field(None, description="识别色（8 色之一）；不给时按创建顺序自动分配")
    folder_id: int | None = None
    device_ids: list[int] = Field(default_factory=list, description="同时加入的设备（项目设备池里的）")
    policy: Policy = Field("follow", description="加入设备的版本策略")
    rules: list[RuleBody] = Field(default_factory=list, description="自动加入规则")


@router.post("/networks", summary="新建网络（可同时加入设备、设自动加入规则）")
def create_network(request: Request, body: NetworkBody) -> dict[str, Any]:
    data = body.model_dump()
    return ok(request, _call(networks.create_network, db_of(request), _scope(request), data, _kb(request)))


@router.get("/networks/{network}", summary="网络详情：计数、自动加入规则、复制来源、最近活动")
def get_network(request: Request, network: str) -> dict[str, Any]:
    return ok(request, _call(networks.get_network, db_of(request), _scope(request), network))


class NetworkPatch(BaseModel):
    name: str | None = Field(None, max_length=200)
    slug: str | None = Field(None, max_length=64)
    description: str | None = Field(None, max_length=4000)
    color: str | None = None
    folder_id: int | None = Field(None, description="放进文件夹；传 null 并设 move=true 时移出文件夹")
    move: bool = Field(False, description="folder_id 为 null 时是否移出文件夹")
    position: int | None = None


@router.put("/networks/{network}", summary="改名、改标识、颜色、文件夹、位置（默认网络也可以改名）")
def update_network(request: Request, network: str, body: NetworkPatch) -> dict[str, Any]:
    data = body.model_dump(exclude_none=True)
    if body.move or body.folder_id is not None:
        data["folder_id"] = body.folder_id
    data.pop("move", None)
    return ok(request, _call(networks.update_network, db_of(request), _scope(request), network, data))


@router.get("/networks/{network}/delete-preview", summary="删除网络会一起删除的工作数据（设备不删）")
def delete_preview(request: Request, network: str) -> dict[str, Any]:
    return ok(request, _call(networks.delete_preview, db_of(request), _scope(request), network))


@router.delete(
    "/networks/{network}",
    summary="删除网络与它的工作数据（不进回收站，不删设备）；confirm 必须等于网络名称；默认网络不能删除",
)
def delete_network(request: Request, network: str, confirm: str = Query(..., description="网络名称")) -> dict[str, Any]:
    return ok(request, _call(networks.delete_network, db_of(request), _scope(request), network, confirm))


class CopyBody(BaseModel):
    name: str | None = Field(None, max_length=200)
    slug: str | None = Field(None, max_length=64)
    color: str | None = None
    folder_id: int | None = None


@router.post(
    "/networks/{network}/copy",
    summary="复制网络（连同工作数据：成员与版本选择、规则、标注、忽略、规则调整、脚本与修订、已采纳的 AI 建议与采纳记录）",
)
def copy_network(request: Request, network: str, body: CopyBody) -> dict[str, Any]:
    data = body.model_dump(exclude_none=True)
    return ok(request, _call(networks.copy_network, db_of(request), _scope(request), network, data))


# ---------------------------------------------------------------- 文件夹


class FolderBody(BaseModel):
    name: str = Field(..., max_length=200)


class FolderPatch(BaseModel):
    name: str | None = Field(None, max_length=200)
    position: int | None = None


@router.post("/network-folders", summary="新建文件夹（只整理网络列表）")
def create_folder(request: Request, body: FolderBody) -> dict[str, Any]:
    return ok(request, _call(networks.create_folder, db_of(request), _scope(request), body.name))


@router.put("/network-folders/{folder_id}", summary="文件夹改名或排序")
def update_folder(request: Request, folder_id: int, body: FolderPatch) -> dict[str, Any]:
    data = body.model_dump(exclude_none=True)
    return ok(request, _call(networks.update_folder, db_of(request), _scope(request), folder_id, data))


@router.delete("/network-folders/{folder_id}", summary="删除文件夹：里面的网络移到最外层")
def delete_folder(request: Request, folder_id: int) -> dict[str, Any]:
    return ok(request, _call(networks.delete_folder, db_of(request), _scope(request), folder_id))


# ---------------------------------------------------------------- 成员


@router.get(
    "/networks/{network}/members",
    summary="网络成员：本网络用的版本（跟随最新 / 固定、是否有更新的版本）、还在哪些网络、怎么加入的、管理地址",
)
def list_members(request: Request, network: str) -> dict[str, Any]:
    return ok(request, _call(networks.list_members, db_of(request), _scope(request), network, _kb(request)))


class MembersBody(BaseModel):
    device_ids: list[int] = Field(..., min_length=1, max_length=5000)
    policy: Policy = Field("follow", description="follow 跟随最新 / pin 固定在当前最新版本")


@router.post("/networks/{network}/members", summary="从项目设备池添加设备（可批量）")
def add_members(request: Request, network: str, body: MembersBody) -> dict[str, Any]:
    return ok(
        request,
        _call(networks.add_members, db_of(request), _scope(request), network, body.device_ids, body.policy),
    )


class PolicyBody(BaseModel):
    device_ids: list[int] = Field(..., min_length=1, max_length=5000)
    policy: Policy
    version_id: int | None = Field(None, description="固定到这个版本（只能一台设备）；不给时固定在当前最新")


@router.put(
    "/networks/{network}/members", summary="改版本策略（可批量）：都跟随最新 / 都固定在当前版本 / 固定到某个版本"
)
def set_policy(request: Request, network: str, body: PolicyBody) -> dict[str, Any]:
    return ok(
        request,
        _call(
            networks.set_policy, db_of(request), _scope(request), network, body.device_ids, body.policy, body.version_id
        ),
    )


class DevicesBody(BaseModel):
    device_ids: list[int] = Field(..., min_length=1, max_length=5000)


@router.post(
    "/networks/{network}/members/remove",
    summary="移出网络（可批量）：设备与其他网络不变，记为排除（自动加入规则不再加入）；默认网络不能移出",
)
def remove_members(request: Request, network: str, body: DevicesBody) -> dict[str, Any]:
    return ok(request, _call(networks.remove_members, db_of(request), _scope(request), network, body.device_ids))


@router.post("/networks/{network}/members/unexclude", summary="撤销排除：以后的导入可以再按规则加入")
def unexclude(request: Request, network: str, body: DevicesBody) -> dict[str, Any]:
    return ok(request, _call(networks.unexclude, db_of(request), _scope(request), network, body.device_ids))


# ---------------------------------------------------------------- 自动加入规则


@router.get("/networks/{network}/join-rules", summary="自动加入规则与排除的设备（默认网络：全部新设备）")
def list_rules(request: Request, network: str) -> dict[str, Any]:
    return ok(request, _call(networks.list_rules, db_of(request), _scope(request), network))


@router.post("/networks/{network}/join-rules", summary="添加自动加入规则（可同时加入现在命中的设备）")
def add_rule(request: Request, network: str, body: RuleBody) -> dict[str, Any]:
    return ok(
        request,
        _call(
            networks.add_rule,
            db_of(request),
            _scope(request),
            network,
            body.kind,
            body.pattern,
            body.apply_existing,
            _kb(request),
        ),
    )


class RulePreview(BaseModel):
    kind: Literal["name", "subnet"]
    pattern: str = Field(..., max_length=200)


@router.post(
    "/networks/{network}/join-rules/preview", summary="规则命中预览：现在命中的设备，其中哪些不在本网络、哪些被排除"
)
def preview_rule(request: Request, network: str, body: RulePreview) -> dict[str, Any]:
    return ok(
        request,
        _call(networks.preview_rule, db_of(request), _scope(request), network, body.kind, body.pattern, _kb(request)),
    )


class RulePatch(BaseModel):
    kind: Literal["name", "subnet"] | None = None
    pattern: str | None = Field(None, max_length=200)
    enabled: bool | None = None


@router.put("/networks/{network}/join-rules/{rule_id}", summary="修改自动加入规则")
def update_rule(request: Request, network: str, rule_id: int, body: RulePatch) -> dict[str, Any]:
    data = body.model_dump(exclude_none=True)
    return ok(request, _call(networks.update_rule, db_of(request), _scope(request), network, rule_id, data))


@router.delete("/networks/{network}/join-rules/{rule_id}", summary="删除自动加入规则（已经加入的设备不受影响）")
def delete_rule(request: Request, network: str, rule_id: int) -> dict[str, Any]:
    return ok(request, _call(networks.delete_rule, db_of(request), _scope(request), network, rule_id))


# ---------------------------------------------------------------- 建网建议


@router.get(
    "/network-suggestions",
    summary="建网建议（代码计算，预览）：按连通分量 / IGP 域 / BGP AS / 设备名 / 管理网段 / AI 拓扑整理分组划分，"
    "标出设备数、和现有网络与其他建议的重叠、与现有网络相同的",
)
def suggest(
    request: Request,
    basis: Basis = Query(..., description="划分依据"),
    ignore_mgmt: bool = Query(True, description="连通分量：不算管理口链路"),
    protocol: Literal["all", "isis", "ospf"] = Query("all", description="IGP 域：协议"),
    regex: str | None = Query(None, max_length=200, description="设备名规则：取名称里的哪一段（正则，第一个括号）"),
    prefix: int = Query(24, ge=8, le=32, description="管理网段：按多长的前缀汇总"),
) -> dict[str, Any]:
    params = {"ignore_mgmt": ignore_mgmt, "protocol": protocol, "regex": regex, "prefix": prefix}
    return ok(request, _call(networks.suggest, db_of(request), _scope(request), basis, params, _kb(request)))


class AdoptBody(BaseModel):
    basis: Basis
    params: dict[str, Any] = Field(default_factory=dict, description="与预览时相同的参数")
    keys: list[str] = Field(default_factory=list, description="采纳哪些建议（key）；为空时采纳全部可采纳的")
    with_rules: bool = Field(False, description="设备名 / 管理网段依据：同时设为新网络的自动加入规则")
    folder_id: int | None = None
    names: dict[str, str] = Field(default_factory=dict, description="{key: 网络名称}，覆盖建议的名称")


@router.post("/network-suggestions/adopt", summary="采纳建网建议：每个建议建一个网络（按同样的依据重新计算后采纳）")
def adopt(request: Request, body: AdoptBody) -> dict[str, Any]:
    return ok(
        request,
        _call(
            networks.adopt,
            db_of(request),
            _scope(request),
            body.basis,
            body.params,
            body.keys,
            _kb(request),
            body.with_rules,
            body.folder_id,
            body.names,
        ),
    )
