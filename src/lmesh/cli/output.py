"""CLI 输出约定：text 面向人（按语言），json 面向程序（结构固定）；错误写 stderr；退出码见 docs/cli.md。"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, NoReturn

import typer

from lmesh.core import i18n

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_CONFIG = 3
EXIT_NOT_FOUND = 4
EXIT_EXTERNAL = 5


@dataclass
class Ctx:
    lang: str = "zh-CN"
    output: str = "text"
    quiet: bool = False
    verbose: bool = False
    yes: bool = False
    config_path: str | None = None
    project: str | None = None  # --project（M6）
    as_user: str | None = None  # --as
    network: str | None = None  # --network（M9）

    def t(self, key: str, **kw: Any) -> str:
        return i18n.t(key, self.lang, **kw)


def get(ctx: typer.Context) -> Ctx:
    obj = ctx.find_root().obj
    return obj if isinstance(obj, Ctx) else Ctx()


def emit(c: Ctx, data: Any, text: str | None = None) -> None:
    """正常结果写 stdout：json 模式输出 {"ok": true, "data": ...}，text 模式输出给人看的文字。"""
    if c.output == "json":
        sys.stdout.write(json.dumps({"ok": True, "data": data}, ensure_ascii=False, indent=2, default=str) + "\n")
    elif not c.quiet and text is not None:
        sys.stdout.write(text.rstrip("\n") + "\n")


def fail(c: Ctx, code: int, message: str, data: Any = None) -> NoReturn:
    """错误：提示写 stderr；json 模式下 stdout 同时给出结构化错误，方便程序解析。"""
    if c.output == "json":
        sys.stdout.write(
            json.dumps(
                {"ok": False, "error": {"code": code, "message": message, "data": data}},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
            + "\n"
        )
    sys.stderr.write(message.rstrip("\n") + "\n")
    raise typer.Exit(code)


def table(rows: list[list[str]], header: list[str]) -> str:
    """简单的对齐表格（按显示宽度，中文算 2 列）。"""

    def width(s: str) -> int:
        return sum(2 if ord(ch) > 0x2E80 else 1 for ch in s)

    cols = [max(width(str(r[i])) for r in [header, *rows]) for i in range(len(header))]

    def fmt(r: list[str]) -> str:
        return "  ".join(str(v) + " " * (cols[i] - width(str(v))) for i, v in enumerate(r)).rstrip()

    return "\n".join([fmt(header), fmt(["-" * c for c in cols]), *[fmt(r) for r in rows]])
