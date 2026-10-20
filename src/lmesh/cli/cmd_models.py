"""未支持型号的处理（M8-7，REQ-044）：lmesh device profiles / set-profile / request-support、lmesh model-rule …、
lmesh model-support show / derive / retarget。

命令行在本机运行，视为维护员（可以管理全局型号规则、处理申请）；当前项目由全局参数 --project / --as 决定。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from lmesh.cli import output
from lmesh.cli.cmd_configs import _actor, require_db
from lmesh.cli.cmd_device import device_app
from lmesh.cli.cmd_history import _device
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import analysis, config, kbservice, model_support, projects

rule_app = typer.Typer(no_args_is_help=True, help="型号规则：导入时按设备名、版本、特征命令选 Profile / model rules")
support_app = typer.Typer(no_args_is_help=True, help="型号支持申请：派生 Profile、规则改指向 / model support requests")

NameOpt = Annotated[str | None, typer.Option("--match-name", help="设备名模式（* ? 通配，不分大小写）")]
VerOpt = Annotated[str | None, typer.Option("--match-version", help="软件版本（正则）")]
FeatOpt = Annotated[str | None, typer.Option("--match-feature", help="特征命令（正则，按行匹配）")]
ScopeOpt = Annotated[str, typer.Option("--scope", help="project 本项目 / global 全局")]


def _root() -> Path:
    return kbservice.runtime_root(config.load())


def _kb() -> Any:
    return analysis.load_kb(_root())


def _fail(c: Ctx, e: model_support.ModelError) -> NoReturn:
    code = {"not_found": output.EXIT_NOT_FOUND, "param": output.EXIT_USAGE}.get(e.kind, output.EXIT_ERROR)
    fail(c, code, c.t(e.key, **e.fmt), e.data)


def _cond(name: str | None, version: str | None, feature: str | None) -> dict[str, str]:
    return {k: v for k, v in (("name_pattern", name), ("version", version), ("feature", feature)) if v is not None}


def _pct(x: Any) -> str:
    return "-" if x is None else f"{float(x) * 100:.1f}%"


# ---------------------------------------------------------------- 设备


@device_app.command("profiles", help="候选 Profile 与试解析结果（按识别出的命令行比例排序）/ candidate Profiles")
def cmd_profiles(ctx: typer.Context, device: Annotated[str, typer.Argument(help="设备名或编号")]) -> None:
    c = output.get(ctx)
    db = require_db(c)
    try:
        r = model_support.device_candidates(db, _kb(), _device(c, db, device))
    except model_support.ModelError as e:
        _fail(c, e)
    rows = [
        [
            ("* " if x["profile"] == r["profile"] else "  ") + x["profile"],
            _pct(x["ratio"]),
            str(x["command"]),
            str(x["unknown"]),
            "exact" if x["exact"] else "fallback" if x["fallback"] else "",
        ]
        for x in r["candidates"]
    ]
    head = c.t(
        "model.current",
        profile=r["profile"] or "-",
        source=r["profile_source"],
        level=r["match_level"],
        unknown=_pct(r["unknown_ratio"]),
    )
    text = head + "\n" + output.table(rows, ["Profile", c.t("model.ratio"), "command", "unknown", ""])
    emit(c, r, text)


@device_app.command("set-profile", help="更换 Profile 并重新解析（--auto 改回自动选择）/ change a device's Profile")
def cmd_set_profile(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="设备名或编号")],
    profile: Annotated[str | None, typer.Argument(help="Profile 编号（同厂商 / 同平台族）")] = None,
    auto: Annotated[bool, typer.Option("--auto", help="改回自动选择（型号规则 → 版本规则 → 厂商默认）")] = False,
    remember: Annotated[str | None, typer.Option("--remember", help="同时记住为型号规则：project / global")] = None,
    match_name: NameOpt = None,
    match_version: VerOpt = None,
    match_feature: FeatOpt = None,
) -> None:
    c = output.get(ctx)
    if bool(profile) == auto:
        fail(c, output.EXIT_USAGE, c.t("model.profile_or_auto"))
    db = require_db(c)
    rem = {"scope": remember, **_cond(match_name, match_version, match_feature)} if remember and profile else None
    try:
        dev_id = _device(c, db, device)
        if rem is not None and not any(rem.get(k) for k in ("name_pattern", "version", "feature")):
            cand = model_support.device_candidates(db, _kb(), dev_id)
            rem.update(cand["suggested_rule"])
        r = model_support.set_device_profile(
            db, _root(), _kb(), dev_id, profile, _actor(), rem, can_global=True, is_admin=True
        )
    except model_support.ModelError as e:
        _fail(c, e)
    res = r["result"]
    text = c.t(
        "model.set_done",
        profile=r["profile"] or "-",
        source=r["profile_source"],
        unknown=_pct(r["unknown_ratio"]),
        rule=r["rule_created"] or "-",
    )
    emit(c, r, text)
    if not res.get("parsed"):
        raise typer.Exit(output.EXIT_ERROR)


@device_app.command("request-support", help="申请支持此型号：进审核队列（建议）/ request support for the model")
def cmd_request(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="设备名或编号")],
    model: Annotated[str, typer.Option("--model", help="型号，例如 NE8000 X8")],
    reason: Annotated[str, typer.Option("--reason", help="说明")] = "",
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    sc = projects.current()
    try:
        r = model_support.request_support(db, _device(c, db, device), _actor(), model, reason, sc.label if sc else None)
    except model_support.ModelError as e:
        _fail(c, e)
    emit(c, r, c.t("model.requested", id=r["id"]))


# ---------------------------------------------------------------- 型号规则


def _rule_rows(c: Ctx, rules: list[dict[str, Any]]) -> list[list[str]]:
    return [
        [
            f"#{r['id']}",
            r["scope"],
            r["name_pattern"] or "-",
            r["version"] or "-",
            r["feature"] or "-",
            r["profile"],
            str(r.get("devices", "")),
            "on" if r["enabled"] else "off",
        ]
        for r in rules
    ]


@rule_app.command("list", help="列出型号规则（按生效顺序：本项目在前、全局在后）/ list")
def cmd_rule_list(
    ctx: typer.Context, scope: Annotated[str, typer.Option("--scope", help="all / project / global")] = "all"
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    data = model_support.list_rules(db, projects.target_project_id(db), scope)
    rules = data.get("project", []) + data.get("global", [])
    head = [
        "#",
        c.t("model.scope"),
        c.t("model.name"),
        c.t("import.version"),
        c.t("model.feature"),
        "Profile",
        c.t("model.devices"),
        "",
    ]
    emit(c, data, output.table(_rule_rows(c, rules), head) if rules else c.t("model.no_rules"))


@rule_app.command("add", help="新建型号规则 / add")
def cmd_rule_add(
    ctx: typer.Context,
    profile: Annotated[str, typer.Option("--profile", help="指向的 Profile")],
    match_name: NameOpt = None,
    match_version: VerOpt = None,
    match_feature: FeatOpt = None,
    vendor: Annotated[str, typer.Option("--vendor", help="厂商（默认按 Profile 的厂商）")] = "",
    scope: ScopeOpt = "project",
    note: Annotated[str, typer.Option("--note")] = "",
    disabled: Annotated[bool, typer.Option("--disabled", help="先不启用")] = False,
) -> None:
    c = output.get(ctx)
    if scope not in model_support.SCOPES:
        fail(c, output.EXIT_USAGE, c.t("model.scope_invalid", scope=scope))
    db = require_db(c)
    body = {
        "profile": profile,
        "vendor": vendor,
        "note": note,
        "enabled": not disabled,
        **_cond(match_name, match_version, match_feature),
    }
    try:
        r = model_support.create_rule(
            db, _kb(), None if scope == "global" else projects.target_project_id(db), body, _actor()
        )
    except model_support.ModelError as e:
        _fail(c, e)
    emit(c, r, c.t("model.rule_saved", id=r["id"], profile=r["profile"]))


@rule_app.command("update", help="修改型号规则 / update")
def cmd_rule_update(
    ctx: typer.Context,
    rule_id: Annotated[int, typer.Argument(help="规则编号")],
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    match_name: NameOpt = None,
    match_version: VerOpt = None,
    match_feature: FeatOpt = None,
    note: Annotated[str | None, typer.Option("--note")] = None,
    enable: Annotated[bool | None, typer.Option("--enable/--disable", help="启用 / 停用")] = None,
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    body: dict[str, Any] = {
        "profile": profile,
        "note": note,
        "enabled": enable,
        **_cond(match_name, match_version, match_feature),
    }
    try:
        r = model_support.update_rule(db, _kb(), rule_id, projects.target_project_id(db), body, True)
    except model_support.ModelError as e:
        _fail(c, e)
    emit(c, r, c.t("model.rule_saved", id=r["id"], profile=r["profile"]))


@rule_app.command("remove", help="删除型号规则 / remove")
def cmd_rule_remove(ctx: typer.Context, rule_id: Annotated[int, typer.Argument(help="规则编号")]) -> None:
    c = output.get(ctx)
    db = require_db(c)
    try:
        r = model_support.delete_rule(db, rule_id, projects.target_project_id(db), True)
    except model_support.ModelError as e:
        _fail(c, e)
    emit(c, r, c.t("model.rule_removed", id=rule_id))


@rule_app.command("test", help="试匹配：规则条件在本项目设备上的命中情况（不保存）/ test")
def cmd_rule_test(
    ctx: typer.Context,
    profile: Annotated[str, typer.Option("--profile")],
    match_name: NameOpt = None,
    match_version: VerOpt = None,
    match_feature: FeatOpt = None,
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    try:
        r = model_support.test_rules(
            db,
            _kb(),
            projects.target_project_id(db),
            {"profile": profile, **_cond(match_name, match_version, match_feature)},
        )
    except model_support.ModelError as e:
        _fail(c, e)
    rows = [
        [d["name"], d["profile"] or "-", d["source"], f"#{d['taken_by']}" if d["taken_by"] else ""]
        for d in r["devices"]
    ]
    emit(
        c,
        r,
        c.t("model.test_hits", n=r["count"])
        + (
            "\n" + output.table(rows, [c.t("import.device"), "Profile", c.t("model.source"), c.t("model.taken_by")])
            if rows
            else ""
        ),
    )


# ---------------------------------------------------------------- 型号支持申请（维护员）


@support_app.command("show", help="申请的处理状态与改指向预演 / show")
def cmd_support_show(ctx: typer.Context, item: Annotated[int, typer.Argument(help="审核条目编号")]) -> None:
    c = output.get(ctx)
    db = require_db(c)
    try:
        r = model_support.support_status(db, _root(), _kb(), item)
    except model_support.ModelError as e:
        _fail(c, e)
    p = (r["item"] or {}).get("payload") or {}
    lines = [
        f"#{item} {p.get('model')} · {p.get('device')} · {p.get('vendor')} {p.get('version')} · {p.get('profile')} ({p.get('profile_source')})",
        c.t("model.derived", profile=(r.get("derived") or {}).get("profile") or "-", released=r.get("released")),
    ]
    emit(c, r, "\n".join(lines))


@support_app.command("derive", help="从现有 Profile 派生（继承，只写差异）/ derive a Profile")
def cmd_support_derive(
    ctx: typer.Context,
    item: Annotated[int, typer.Argument(help="审核条目编号")],
    profile_id: Annotated[str, typer.Option("--id", help="新 Profile 编号")],
    base: Annotated[str, typer.Option("--base", help="基础 Profile")],
    title: Annotated[str, typer.Option("--title")] = "",
    platform: Annotated[str, typer.Option("--platform")] = "",
    software: Annotated[str, typer.Option("--software")] = "",
    version: Annotated[str, typer.Option("--version-rule", help="版本规则（正则）")] = "",
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    body = {
        "id": profile_id,
        "base": base,
        "title": title,
        "platform": platform,
        "software": software,
        "version": version,
    }
    try:
        r = model_support.derive(db, _root(), item, body, _actor())
    except model_support.ModelError as e:
        _fail(c, e)
    emit(c, r, c.t("model.derive_done", profile=r["profile"], base=r["base"]))


@support_app.command("retarget", help="型号规则改指向派生的 Profile，相关设备重新解析 / retarget rules")
def cmd_support_retarget(
    ctx: typer.Context,
    item: Annotated[int, typer.Argument(help="审核条目编号")],
    note: Annotated[str, typer.Option("--note")] = "",
) -> None:
    c = output.get(ctx)
    db = require_db(c)
    try:
        r = model_support.retarget(db, _root(), _kb(), item, _actor(), note)
    except model_support.ModelError as e:
        _fail(c, e)
    emit(
        c,
        r,
        c.t(
            "model.retarget_done",
            profile=r["profile"],
            rules=len(r["rules_changed"]) + (1 if r["rule_created"] else 0),
            devices=len(r["devices"]),
            released=r["released"],
        ),
    )


def register(app: typer.Typer) -> None:
    app.add_typer(rule_app, name="model-rule")
    app.add_typer(support_app, name="model-support")
