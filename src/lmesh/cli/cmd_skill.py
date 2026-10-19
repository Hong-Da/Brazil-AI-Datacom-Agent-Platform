"""内置 AI skill 命令（REQ-033）：lmesh skill list|show|test|versions|rollback|evolve|approve。

直接读写本机的 knowledge/ai-skills/、data/ai-skills/ 与数据库（与 API 共用 core/skills、core/skill_runners）。
test 默认真实调用 AI（未配置时退出码 3），--replay 用样例记下的回复走一遍代码校验（不需要 AI）；
evolve 需要配置 AI，结果是待批准的进化，approve 批准后才发布为新版本（--reject 放弃）。
"""

from __future__ import annotations

from typing import Annotated, Any, NoReturn

import typer

from lmesh.cli import output
from lmesh.cli.cmd_configs import require_db
from lmesh.cli.cmd_graph import _kb
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import config, i18n, skill_runners, skills


def _fail(c: Ctx, e: skills.SkillError) -> NoReturn:
    code = {
        "not_found": output.EXIT_NOT_FOUND,
        "state": output.EXIT_CONFIG if e.key == "ai.not_configured" else output.EXIT_ERROR,
        "invalid": output.EXIT_USAGE,
    }.get(e.kind, output.EXIT_USAGE)
    msg = c.t(e.key, **e.fmt)
    if e.kind == "invalid" and isinstance(e.data, dict):
        msg += "".join(
            f"\n  {i['field']}: {c.t(i['key'], **(i.get('params') or {}))}" for i in e.data.get("issues", [])
        )
    fail(c, code, msg, e.data)


def _actor() -> skills.Actor:
    import getpass

    try:
        return skills.Actor(None, f"cli:{getpass.getuser()}")
    except Exception:
        return skills.Actor(None, "cli")


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def _ctx(c: Ctx) -> skill_runners.Ctx:
    require_db(c)
    return skill_runners.Ctx(config.load(), lambda: _kb(c)[0], c.lang)


def _check_text(c: Ctx, r: dict[str, Any]) -> str:
    ch = r["check"]
    lines = [c.t("skill.test.head", mode=c.t(f"skill.mode.{r['mode']}"), version=r["version"])]
    lines.append(c.t("skill.test.status", status=c.t(f"skill.status.{ch['status']}"), score=ch["score"]))
    for it in ch["items"][:30]:
        mark = "✓" if it["ok"] else "✕"
        line = f" L{it['line']}" if it.get("line") else ""
        lines.append(f"  {mark}{line} {it['reason']} {it.get('text') or ''}".rstrip())
    if r.get("reply"):
        lines.append(c.t("skill.test.reply"))
        lines.append(str(r["reply"])[:2000])
    return "\n".join(lines)


def register(app: typer.Typer) -> None:
    sapp = typer.Typer(no_args_is_help=True, help="内置 AI skill：查看、试运行、版本、回滚、进化 / built-in AI skills")
    app.add_typer(sapp, name="skill")

    @sapp.command("list", help="skill 列表（按功能分组）与近 N 天统计 / list skills by group with statistics")
    def s_list(
        ctx: typer.Context,
        days: Annotated[int, typer.Option("--days", min=1, max=3650)] = 30,
        group: Annotated[
            str | None, typer.Option("--group", help="只列这个功能分组（qa、generate、analysis …）")
        ] = None,
    ) -> None:
        c = output.get(ctx)
        url = require_db(c)
        settings = config.load()
        st = skills.stats(url, days)
        groups = skills.groups()
        if group and group not in {g["id"] for g in groups}:
            fail(c, output.EXIT_USAGE, c.t("skill.bad_group", groups=", ".join(g["id"] for g in groups)))
        items = [{**skills.info(skills.current(i), settings), "stats": st.get(i)} for i in skills.list_ids()]
        order = [g["id"] for g in groups]
        items.sort(key=lambda it: order.index(it["group"]))  # 稳定排序：组内保持原顺序
        if group:
            items = [it for it in items if it["group"] == group]
        names = {g["id"]: i18n.pick(g["title"], c.lang) for g in groups}
        rows = []
        for it in items:
            s = it["stats"] or {}
            rows.append(
                [
                    names[it["group"]],
                    it["id"],
                    i18n.pick(it["title"], c.lang),
                    c.t("common.yes") if it["enabled"] else c.t("common.no"),
                    "builtin" if it["active"] == "builtin" else f"v{it['active']}",
                    str(s.get("calls", 0)),
                    _pct(s.get("pass_rate")),
                    _pct(s.get("reject_rate")),
                    f"+{s.get('up', 0)} / -{s.get('down', 0)}",
                    str(s.get("regression_cases", 0)),
                ]
            )
        header = [
            c.t(f"skill.col.{k}")
            for k in ("group", "id", "title", "enabled", "version", "calls", "pass", "reject", "rating", "cases")
        ]
        counted = [{**g, "count": sum(1 for it in items if it["group"] == g["id"])} for g in groups]
        emit(c, {"days": days, "groups": counted, "skills": items}, output.table(rows, header))

    @sapp.command("show", help="显示 skill 的生效定义（提示词、示例、工具、校验）/ show a skill")
    def s_show(
        ctx: typer.Context,
        skill: Annotated[str, typer.Argument(help="skill 编号")],
        version: Annotated[str | None, typer.Option("--version", help="builtin 或版本号；默认生效版本")] = None,
    ) -> None:
        c = output.get(ctx)
        try:
            d = skills.detail(skill, config.load() if config.is_configured() else None)
            if version:
                s = skills.load_version(skill, version)
                d["definition"], d["shown_version"] = s.definition(), s.active
        except skills.SkillError as e:
            _fail(c, e)
        df = d["definition"]
        text = "\n".join(
            [
                f"{d['id']}  {i18n.pick(d['title'], c.lang)}  ({d.get('shown_version') or d['active']})",
                i18n.pick(d["description"], c.lang),
                f"task: {d['task']}  model_key: {d['model_key'] or '-'}  tools: {', '.join(df['tools'])}",
                f"checks: {', '.join(d['checks'])}",
                "",
                "[system]",
                df["system"],
                "",
                "[prompt]",
                df["prompt"],
                *(x for k, v in df["templates"].items() for x in ("", f"[templates.{k}]", v)),
                "",
                c.t("skill.examples", n=len(df["examples"])),
            ]
        )
        emit(c, d, text)

    @sapp.command("test", help="试运行：样例或回归案例 → AI（或 --replay 回放）→ 代码校验 / dry-run a skill")
    def s_test(
        ctx: typer.Context,
        skill: Annotated[str, typer.Argument(help="skill 编号")],
        sample: Annotated[int, typer.Option("--sample", help="内置样例序号（从 0 开始）")] = 0,
        case: Annotated[int | None, typer.Option("--case", help="回归案例编号（代替样例）")] = None,
        replay: Annotated[bool, typer.Option("--replay", help="不调用 AI，用样例 / 案例记下的回复或 --reply")] = False,
        reply: Annotated[str | None, typer.Option("--reply", help="回放用的回复")] = None,
        version: Annotated[str | None, typer.Option("--version", help="builtin 或版本号；默认生效版本")] = None,
    ) -> None:
        c = output.get(ctx)
        sc = _ctx(c)
        try:
            r = skill_runners.test(
                sc,
                skill,
                None if case is not None else sample,
                case,
                None,
                None,
                version,
                "replay" if replay else "ai",
                reply,
                _actor(),
            )
        except skills.SkillError as e:
            _fail(c, e)
        emit(c, r, _check_text(c, r))

    @sapp.command("versions", help="版本历史 / version history")
    def s_versions(ctx: typer.Context, skill: Annotated[str, typer.Argument(help="skill 编号")]) -> None:
        c = output.get(ctx)
        try:
            vs = skills.versions(skill)
        except skills.SkillError as e:
            _fail(c, e)
        rows = [
            [
                ("* " if v["active"] else "  ") + v["label"],
                c.t(f"skill.source.{v['source']}"),
                v["author"] or "-",
                (v["saved_at"] or "-")[:19],
                v["note"] or "",
            ]
            for v in vs
        ]
        header = [c.t(f"skill.col.{k}") for k in ("version", "source", "author", "time", "note")]
        emit(c, {"skill": skill, "versions": vs}, output.table(rows, header))

    @sapp.command("rollback", help="回滚到某个版本（builtin 为恢复内置）/ roll back to a version")
    def s_rollback(
        ctx: typer.Context,
        skill: Annotated[str, typer.Argument(help="skill 编号")],
        version: Annotated[str, typer.Argument(help="版本号或 builtin")],
    ) -> None:
        c = output.get(ctx)
        try:
            r = (
                skills.restore(skill, _actor().name)
                if version == "builtin"
                else skills.rollback(skill, version, _actor().name)
            )
        except skills.SkillError as e:
            _fail(c, e)
        emit(c, {"skill": skill, **r}, c.t("skill.rolled_back", skill=skill, version=r["active"]))

    @sapp.command("evolve", help="发起进化：AI 提出候选版本，回归集新旧对比打分，待批准（需要 AI）/ evolve a skill")
    def s_evolve(
        ctx: typer.Context,
        skill: Annotated[str, typer.Argument(help="skill 编号")],
        limit: Annotated[int, typer.Option("--limit", min=1, max=100, help="最多用多少条回归案例")] = 20,
    ) -> None:
        c = output.get(ctx)
        sc = _ctx(c)
        try:
            skills.builtin(skill)
            ev = skill_runners.evolve(sc, skill, _actor(), limit)
        except skills.SkillError as e:
            _fail(c, e)
        if ev["status"] == "failed":
            fail(c, output.EXIT_ERROR, c.t("skill.evolve_failed", id=ev["id"]), ev)
        s = ev["summary"] or {}
        text = c.t(
            "skill.evolved",
            id=ev["id"],
            old=s.get("old"),
            new=s.get("new"),
            better=s.get("better"),
            worse=s.get("worse"),
        )
        emit(c, ev, text)

    @sapp.command("approve", help="批准进化的候选版本并发布（--reject 放弃）/ approve or reject an evolution")
    def s_approve(
        ctx: typer.Context,
        skill: Annotated[str, typer.Argument(help="skill 编号")],
        evolution: Annotated[int, typer.Argument(help="进化编号")],
        reject: Annotated[bool, typer.Option("--reject", help="放弃，不发布")] = False,
        note: Annotated[str, typer.Option("--note", help="说明")] = "",
    ) -> None:
        c = output.get(ctx)
        url = require_db(c)
        try:
            ev = skills.decide(url, skill, evolution, not reject, _actor().name, note)
        except skills.SkillError as e:
            _fail(c, e)
        key = "skill.rejected" if reject else "skill.approved"
        emit(c, ev, c.t(key, id=evolution, version=ev.get("published_version") or "-"))
