"""知识库与审核队列命令：lmesh kb …、lmesh review …。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from lmesh.cli import output
from lmesh.cli.cmd_configs import require_db
from lmesh.cli.output import Ctx, emit, fail
from lmesh.core import config, kbservice, review
from lmesh.core.kb import repo


def _root(c: Ctx) -> Path:
    if not config.is_configured():
        fail(c, output.EXIT_CONFIG, c.t("config.not_configured"))
    return kbservice.runtime_root(config.load())


def register(app: typer.Typer) -> None:
    kb_app = typer.Typer(no_args_is_help=True, help="知识库：校验、导入导出、发布、对比、回滚 / knowledge base")
    review_app = typer.Typer(no_args_is_help=True, help="审核队列 / review queue")
    app.add_typer(kb_app, name="kb")
    app.add_typer(review_app, name="review")

    @kb_app.command("validate", help="校验知识库：格式、引用完整性、语法、继承 / validate")
    def kb_validate(ctx: typer.Context) -> None:
        c = output.get(ctx)
        rep = kbservice.validate_report(_root(c))
        lines = [
            c.t(
                "kb.validate_summary",
                version=rep["kb_version"],
                errors=rep["errors"],
                warnings=rep["warnings"],
                **rep["counts"],
            )
        ]
        lines += [
            f"  [{i['level']}] {i['code']}: {i['message']}" + (f" ({i['file']})" if i["file"] else "")
            for i in rep["issues"]
        ]
        emit(c, rep, "\n".join(lines))
        if rep["errors"]:
            raise typer.Exit(output.EXIT_ERROR)

    @kb_app.command("export", help="导出知识库包（zip）/ export a package")
    def kb_export(
        ctx: typer.Context, out: Annotated[Path, typer.Option("--out", "-o", help="输出的 zip 文件")]
    ) -> None:
        c = output.get(ctx)
        from lmesh.core.kb import package

        data = package.export(_root(c), out)
        emit(c, {"path": str(out), "bytes": len(data)}, c.t("kb.exported", path=out))

    @kb_app.command("import", help="导入知识库包：新文件直接加入，冲突送审核队列 / import a package")
    def kb_import(
        ctx: typer.Context,
        pkg: Annotated[Path, typer.Argument(help="知识库包 zip")],
        dry_run: Annotated[bool, typer.Option("--dry-run", help="只检查，不写入")] = False,
    ) -> None:
        c = output.get(ctx)
        if not pkg.exists():
            fail(c, output.EXIT_NOT_FOUND, c.t("common.not_found", path=pkg))
        from lmesh.core.kb.package import PackageError

        try:
            res = kbservice.import_package(_root(c), pkg.read_bytes(), require_db(c), dry_run=dry_run)
        except PackageError as e:
            fail(c, output.EXIT_USAGE, str(e))
        text = c.t(
            "kb.import_summary",
            added=len(res["added"]),
            unchanged=len(res["unchanged"]),
            conflicts=len(res["conflicts"]),
        )
        if res["issues"]:
            text += (
                "\n"
                + c.t("kb.import_invalid")
                + "\n"
                + "\n".join(f"  {i['code']}: {i['message']}" for i in res["issues"])
            )
        emit(c, res, text)
        if res["issues"]:
            raise typer.Exit(output.EXIT_ERROR)

    @kb_app.command("release", help="发布知识库版本：校验 → 回归测试 → 打标签 / publish a release")
    def kb_release(
        ctx: typer.Context,
        version: Annotated[str | None, typer.Option(help="版本号；不填时按差异自动建议")] = None,
        message: Annotated[str, typer.Option("--message", "-m", help="发布说明")] = "",
    ) -> None:
        c = output.get(ctx)
        from lmesh.core import roundtrip_hook

        try:
            res = kbservice.release(_root(c), version, message, roundtrip_hook.regression)
        except kbservice.ReleaseError as e:
            fail(c, output.EXIT_ERROR, c.t(e.key, version=e.data if isinstance(e.data, str) else ""), e.data)
        emit(c, res, c.t("kb.released", version=res["version"], bump=res["diff"]["suggested_bump"]))

    @kb_app.command("releases", help="已发布的知识库版本 / list releases")
    def kb_releases(ctx: typer.Context) -> None:
        c = output.get(ctx)
        rels = kbservice.releases(_root(c))
        rows = [[r["version"], r["commit"][:10], r["message"]] for r in rels]
        emit(
            c,
            {"releases": rels},
            output.table(rows, [c.t("kb.version"), "commit", c.t("kb.message")]) if rels else c.t("kb.no_releases"),
        )

    @kb_app.command("diff", help="对比两个知识库版本（只给一个时与工作区对比）/ diff versions")
    def kb_diff(
        ctx: typer.Context,
        ref_from: Annotated[str, typer.Argument(help="版本号或标签")],
        ref_to: Annotated[str | None, typer.Argument(help="版本号或标签；省略为当前工作区")] = None,
    ) -> None:
        c = output.get(ctx)
        try:
            d = kbservice.diff(_root(c), ref_from, ref_to)
        except KeyError:
            fail(
                c,
                output.EXIT_NOT_FOUND,
                c.t("kb.ref_not_found", ref=ref_from if ref_to is None else f"{ref_from} / {ref_to}"),
            )
        lines = [f"{k}: {len(v)}" for k, v in d.items() if isinstance(v, list) and v] or [c.t("kb.no_diff")]
        lines.append(c.t("kb.suggested_bump", bump=d["suggested_bump"]))
        emit(c, d, "\n".join(lines))

    @kb_app.command("rollback", help="回滚到某个已发布版本（工作区恢复后再提交一次，历史保留）/ rollback")
    def kb_rollback(ctx: typer.Context, ref: Annotated[str, typer.Argument(help="版本号或标签")]) -> None:
        c = output.get(ctx)
        root = _root(c)
        if not c.yes and not typer.confirm(c.t("kb.rollback_confirm", ref=ref), default=False):
            raise typer.Exit(output.EXIT_ERROR)
        try:
            sha = repo.rollback(root, ref)
        except KeyError:
            fail(c, output.EXIT_NOT_FOUND, c.t("kb.ref_not_found", ref=ref))
        emit(c, {"ref": ref, "commit": sha}, c.t("kb.rolled_back", ref=ref))

    @kb_app.command("history", help="知识库的提交历史 / commit history")
    def kb_history(ctx: typer.Context, limit: Annotated[int, typer.Option(help="条数")] = 20) -> None:
        c = output.get(ctx)
        h = repo.history(_root(c), limit)
        emit(
            c,
            {"history": h},
            output.table(
                [[str(x["commit"]), str(x["message"]).splitlines()[0]] for x in h], ["commit", c.t("kb.message")]
            ),
        )

    @kb_app.command("coverage", help="覆盖矩阵：各 Profile 对 Schema 节点的支持情况 / coverage")
    def kb_coverage(
        ctx: typer.Context, profile: Annotated[str | None, typer.Option(help="只看一个 Profile")] = None
    ) -> None:
        c = output.get(ctx)
        try:
            cov = kbservice.coverage(_root(c), profile)
        except KeyError:
            fail(c, output.EXIT_NOT_FOUND, c.t("kb.profile_not_found", profile=profile))
        rows = [[p, str(t["supported"]), str(t["unsupported"]), str(t["unfilled"])] for p, t in cov["totals"].items()]
        emit(c, cov, output.table(rows, ["Profile", c.t("kb.supported"), c.t("kb.unsupported"), c.t("kb.unfilled")]))

    # ---------- 审核队列 ----------

    @review_app.command("list", help="列出待审核的条目 / list items")
    def review_list(
        ctx: typer.Context,
        kind: Annotated[
            str | None, typer.Option(help="card / schema_node / mapping / conflict / profile_entry")
        ] = None,
        status: Annotated[str, typer.Option(help="pending / approved / rejected / all")] = "pending",
    ) -> None:
        c = output.get(ctx)
        res = review.list_items(require_db(c), None if status == "all" else status, kind)
        rows = [[str(i["id"]), i["kind"], i["status"], i["title"]] for i in res["items"]]
        emit(
            c,
            res,
            output.table(rows, ["#", c.t("review.kind"), c.t("review.status"), c.t("review.title")])
            if rows
            else c.t("review.empty"),
        )

    @review_app.command("show", help="查看一个条目的完整内容 / show item")
    def review_show(ctx: typer.Context, item_id: Annotated[int, typer.Argument()]) -> None:
        c = output.get(ctx)
        item = review.get(require_db(c), item_id)
        if not item:
            fail(c, output.EXIT_NOT_FOUND, c.t("review.not_found"))
        import json

        emit(c, item, json.dumps(item, ensure_ascii=False, indent=2, default=str))

    def _decide(ctx: typer.Context, ids: list[int], approve: bool, note: str) -> None:
        c = output.get(ctx)
        url, root = require_db(c), _root(c)
        done, failed = [], []
        for i in ids:
            try:
                done.append(review.decide(url, root, i, approve, note))
            except review.ReviewError as e:
                failed.append({"id": i, "error": c.t(str(e))})
        problems = "\n".join(f"#{f['id']}: {f['error']}" for f in failed)
        if failed and not done:
            fail(c, output.EXIT_ERROR, problems, {"done": done, "failed": failed})
        if failed:
            typer.echo(problems, err=True)
        emit(c, {"done": done, "failed": failed}, c.t("review.decided", n=len(done)))

    @review_app.command("approve", help="通过（可一次多个）/ approve")
    def review_approve(
        ctx: typer.Context, ids: Annotated[list[int], typer.Argument()], note: Annotated[str, typer.Option()] = ""
    ) -> None:
        _decide(ctx, ids, True, note)

    @review_app.command("reject", help="驳回（可一次多个）/ reject")
    def review_reject(
        ctx: typer.Context, ids: Annotated[list[int], typer.Argument()], note: Annotated[str, typer.Option()] = ""
    ) -> None:
        _decide(ctx, ids, False, note)
