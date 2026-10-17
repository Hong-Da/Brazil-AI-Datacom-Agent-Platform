"""Markdown 文档切分：标题树，以及把命令格式行（**关键字** *参数*）转换成命令卡语法。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_ANCHOR = re.compile(r"<a id=\"[^\"]*\"></a>")


@dataclass
class Section:
    title: str
    level: int
    line: int  # 标题所在行号（1 开始）
    body: list[str] = field(default_factory=list)  # 到下一个标题之前的正文
    children: list[Section] = field(default_factory=list)
    parent: Section | None = field(default=None, repr=False)

    def child(self, titles: list[str]) -> Section | None:
        low = {t.lower() for t in titles}
        return next((c for c in self.children if c.title.lower() in low), None)

    def text(self) -> str:
        return "\n".join(self.body).strip()

    def path(self) -> list[str]:
        out: list[str] = []
        cur: Section | None = self
        while cur is not None and cur.level > 0:
            out.append(cur.title)
            cur = cur.parent
        return list(reversed(out))

    def walk(self):  # type: ignore[no-untyped-def]
        yield self
        for c in self.children:
            yield from c.walk()


def parse(text: str) -> Section:
    root = Section("", 0, 0)
    stack = [root]
    for i, raw in enumerate(text.splitlines(), start=1):
        line = _ANCHOR.sub("", raw)
        m = _HEADING.match(line)
        if m:
            level = len(m.group(1))
            while stack[-1].level >= level:
                stack.pop()
            sec = Section(m.group(2).strip(), level, i, parent=stack[-1])
            stack[-1].children.append(sec)
            stack.append(sec)
        else:
            stack[-1].body.append(line)
    return root


def parse_file(path: Path) -> Section:
    return parse(path.read_text(encoding="utf-8", errors="replace"))


# ---------- 命令格式行 → 命令卡语法 ----------

_FMT_TOKEN = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*|([\[\]{}|])|([^\s*\[\]{}|]+)")


def format_to_syntax(line: str) -> str:
    """'**peer** *ipv4-address* **timer** [ **hold** *t* ]' → 'peer <ipv4-address> timer [ hold <t> ]'。

    粗体是关键字，斜体是参数（斜体中有空格时拆成多个参数），[ ] { } | 原样保留。处理粗斜体紧贴的写法。
    """
    out: list[str] = []
    for m in _FMT_TOKEN.finditer(line.replace("\\|", "|").replace("&#124;", "|")):
        bold, ital, sym, plain = m.groups()
        if bold is not None:
            inner = bold.strip()
            # 粗体里偶尔夹着斜体（***x***）：按参数处理
            if inner.startswith("*") and inner.endswith("*"):
                out += [f"<{w}>" for w in inner.strip("*").split() if w and w != "..."]
            else:
                out += [w for w in inner.replace("*", "").split() if w]
        elif ital is not None:
            out += [f"<{w.strip('.')}>" for w in ital.split() if w.strip(".")]
        elif sym is not None:
            out.append(sym)
        elif plain is not None and plain not in ("...", "…"):
            out.append(plain)
    return " ".join(out)


def table_rows(body: list[str]) -> list[list[str]]:
    """Markdown 表格 → 行（不含表头与分隔行）。"""
    rows = [ln.strip() for ln in body if ln.strip().startswith("|")]
    out = []
    for i, r in enumerate(rows):
        cells = [c.strip() for c in r.strip("|").split("|")]
        if i == 0 or set("".join(cells)) <= set("-: "):
            continue
        out.append(cells)
    return out


def params_in_cell(cell: str) -> list[str]:
    """参数表第一列中的斜体参数名：'**keepalive** *keepalive-time*' → ['keepalive-time']。"""
    names: list[str] = []
    for m in _FMT_TOKEN.finditer(cell):
        bold, ital = m.group(1), m.group(2)
        if ital:
            names += [w.strip(".") for w in ital.split() if w.strip(".")]
        elif bold and bold.strip().startswith("*"):
            names += [w for w in bold.strip("*").split() if w]
    return names


def clean(text: str) -> str:
    """去掉 Markdown 记号与 <br>，压缩空白。"""
    t = re.sub(r"<br\s*/?>", " ", text)
    t = re.sub(r"\*\*|\*|`", "", t)
    return re.sub(r"\s+", " ", t).strip()
