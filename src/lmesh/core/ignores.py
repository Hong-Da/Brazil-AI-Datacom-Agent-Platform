"""忽略的检查发现：按 (项目, 设备, 规则, 节点规范编号) 记录，必须写明原因；检查结果据此标出 ignored（checks.check 的 ignores）。

按项目（M6）：同一台公共设备在不同项目里的忽略互不影响；没有当前项目时（直接调用 core）按设备所属项目。

同一设备、规则、节点再次忽略时更新原因（不新增记录）。设备删除时记录一并删除（外键级联）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from lmesh.core import store
from lmesh.core.store.models import CheckIgnore, Device, iso


class IgnoreError(ValueError):
    """key 是文案键；kind 为 param（参数错误）或 not_found（资源不存在）。"""

    def __init__(self, key: str, kind: str = "param", **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.fmt = key, kind, fmt


def _row(r: CheckIgnore) -> dict[str, Any]:
    return {
        "id": r.id,
        "device_id": r.device_id,
        "rule": r.rule,
        "node": r.node,
        "reason": r.reason,
        "created_at": iso(r.created_at),
    }


def _device(s: Any, device_id: int) -> Device:
    from lmesh.core import projects

    dev = s.get(Device, device_id)
    if dev is None or not projects.visible(s, device_id):
        raise IgnoreError("compare.device_not_found", "not_found", target=str(device_id))
    return dev


def _project_of(dev: Device | None) -> int | None:
    from lmesh.core import projects

    sc = projects.current()
    if sc is not None:
        return sc.project_id
    return dev.project_id if dev is not None else None


def _in_project(q: Any, pid: int | None) -> Any:
    return q.where(CheckIgnore.project_id.is_(None) if pid is None else CheckIgnore.project_id == pid)


def list_ignores(db_url: str, device_id: int | None = None) -> list[dict[str, Any]]:
    from lmesh.core import projects

    with store.session(db_url) as s:
        if device_id is not None:
            _device(s, device_id)
        q = select(CheckIgnore).order_by(CheckIgnore.id)
        sc = projects.current()
        if sc is not None:
            q = q.where(CheckIgnore.project_id == sc.project_id)
        if device_id is not None:
            q = q.where(CheckIgnore.device_id == device_id)
        return [_row(r) for r in s.scalars(q)]


def add_ignore(
    db_url: str, device_id: int, rule: str, node: str, reason: str, known_rules: set[str] | None = None
) -> dict[str, Any]:
    """known_rules 给出时校验规则编号存在（内置检查与知识库规则）。返回记录，created 表示是否新增。"""
    rule, node, reason = rule.strip(), node.strip(), reason.strip()
    if not reason:
        raise IgnoreError("check.ignore_reason_required")
    if not rule or not node:
        raise IgnoreError("check.ignore_target_required")
    if known_rules is not None and rule not in known_rules:
        raise IgnoreError("rules.not_found", "not_found", rule=rule)
    with store.session(db_url) as s:
        pid = _project_of(_device(s, device_id))
        row = s.scalar(
            _in_project(
                select(CheckIgnore).where(
                    CheckIgnore.device_id == device_id, CheckIgnore.rule == rule, CheckIgnore.node == node
                ),
                pid,
            )
        )
        created = row is None
        if row is None:
            row = CheckIgnore(project_id=pid, device_id=device_id, rule=rule, node=node, reason=reason)
            s.add(row)
        else:
            row.reason = reason
        s.flush()
        return {**_row(row), "created": created}


def remove_ignore(db_url: str, ignore_id: int) -> dict[str, Any]:
    from lmesh.core import projects

    with store.session(db_url) as s:
        row = s.get(CheckIgnore, ignore_id)
        sc = projects.current()
        if row is None or (sc is not None and row.project_id != sc.project_id):
            raise IgnoreError("check.ignore_not_found", "not_found", id=ignore_id)
        out = _row(row)
        s.delete(row)
    return {**out, "deleted": True}


def index(db_url: str, device_id: int) -> dict[tuple[str, str], dict[str, Any]]:
    """检查时用的索引：{(规则, 节点): {id, reason}}。"""
    with store.session(db_url) as s:
        pid = _project_of(s.get(Device, device_id))
        rows = s.scalars(_in_project(select(CheckIgnore).where(CheckIgnore.device_id == device_id), pid))
        return {(r.rule, r.node): {"id": r.id, "reason": r.reason} for r in rows}
