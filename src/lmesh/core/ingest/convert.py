"""把 HTML / PDF / CHM 产品文档转换成抽取器使用的 Markdown（标题用 #，关键字粗体 **，参数斜体 *，表格用 |）。

- HTML：标准库解析；h1–h6 → 标题，b/strong → 粗体，i/em/var → 斜体，table → Markdown 表格。
- PDF：pdfplumber 按字体名判断粗体、斜体，按字号推断标题层级（最大的几种字号依次为 #、##、###）。
- CHM：用 7-Zip 解包成 HTML 再转换（需要系统装有 7z；没有时报告不支持）。
转换结果写到 tmp/ 下的临时目录，原文件不动。
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

SUPPORTED = (".md", ".html", ".htm", ".pdf", ".chm")


class _HtmlToMd(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.buf: list[str] = []
        self.heading: int | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.rows: list[list[str]] = []
        self.skip = 0

    def _target(self) -> list[str]:
        return self.cell if self.cell is not None else self.buf

    def _flush(self) -> None:
        text = re.sub(r"[ \t]+", " ", "".join(self.buf)).strip()
        if text:
            self.out.append(("#" * self.heading + " " + text) if self.heading else text)
            self.out.append("")
        self.buf = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.skip += 1
        elif re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self.heading = int(tag[1])
        elif tag in ("p", "div", "li", "br", "pre"):
            if self.cell is not None:
                self.cell.append(" ")
            else:
                self._flush()
        elif tag in ("b", "strong"):
            self._target().append("**")
        elif tag in ("i", "em", "var"):
            self._target().append("*")
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self.heading = None
        elif tag in ("b", "strong"):
            self._target().append("**")
        elif tag in ("i", "em", "var"):
            self._target().append("*")
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip().replace("|", "\\|"))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == "table" and self.rows:
            self._flush()
            width = max(len(r) for r in self.rows)
            rows = [r + [""] * (width - len(r)) for r in self.rows]
            self.out.append("| " + " | ".join(rows[0]) + " |")
            self.out.append("|" + "---|" * width)
            self.out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
            self.out.append("")
            self.rows = []
        elif tag in ("p", "div", "li", "pre") and self.cell is None:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self._target().append(data.replace("\n", " "))


def html_to_md(text: str) -> str:
    p = _HtmlToMd()
    p.feed(text)
    p.close()
    p._flush()
    md = "\n".join(p.out)
    md = re.sub(r"\*\*\s*\*\*", "", md)  # 空粗体
    return html.unescape(md)


def pdf_to_md(path: Path) -> str:
    """按字体推断粗体 / 斜体 / 标题。效果取决于 PDF 的排版，转换后建议先跑一次抽取看命中率。"""
    import pdfplumber

    lines_out: list[tuple[float, str]] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(extra_attrs=["fontname", "size"], keep_blank_chars=False, use_text_flow=True)
            current_top: float | None = None
            parts: list[str] = []
            size = 0.0
            for w in words:
                if current_top is not None and abs(w["top"] - current_top) > 2:
                    lines_out.append((size, " ".join(parts)))
                    parts, size = [], 0.0
                current_top = w["top"]
                font = str(w.get("fontname", "")).lower()
                txt = w["text"]
                if "bold" in font:
                    txt = f"**{txt}**"
                elif "italic" in font or "oblique" in font:
                    txt = f"*{txt}*"
                parts.append(txt)
                size = max(size, float(w.get("size", 0)))
            if parts:
                lines_out.append((size, " ".join(parts)))
    sizes = sorted({round(s, 1) for s, _ in lines_out}, reverse=True)
    body = (
        max(set(round(s, 1) for s, _ in lines_out), key=[round(s, 1) for s, _ in lines_out].count) if lines_out else 0
    )
    heads = [s for s in sizes if s > body][:3]
    out: list[str] = []
    for s, text in lines_out:
        text = re.sub(r"\*\*\s+\*\*", " ", text)
        lvl = heads.index(round(s, 1)) + 1 if round(s, 1) in heads else 0
        out.append(("#" * lvl + " " + re.sub(r"\*+", "", text)) if lvl else text)
        out.append("")
    return "\n".join(out)


class ConvertError(RuntimeError):
    pass


def prepare(doc: Path, work: Path) -> Path:
    """返回可以交给抽取器的目录：Markdown 目录原样返回；HTML / PDF / CHM 转换到 work 下。"""
    if doc.is_dir():
        # 已经有 Markdown 的文档集直接使用（其中夹带的 PDF、HTML 附件不转换）
        if next(doc.rglob("*.md"), None) is not None:
            return doc
        others = [p for p in doc.rglob("*") if p.suffix.lower() in (".html", ".htm", ".pdf", ".chm")]
        if not others:
            return doc
        files = others
    else:
        files = [doc]
    work.mkdir(parents=True, exist_ok=True)
    base = doc if doc.is_dir() else doc.parent
    for f in files:
        rel = f.relative_to(base)
        suffix = f.suffix.lower()
        target = (work / rel).with_suffix(".md")
        target.parent.mkdir(parents=True, exist_ok=True)
        if suffix in (".html", ".htm"):
            target.write_text(html_to_md(f.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
        elif suffix == ".pdf":
            target.write_text(pdf_to_md(f), encoding="utf-8")
        elif suffix == ".chm":
            seven = shutil.which("7z") or shutil.which("7za")
            if not seven:
                raise ConvertError("ingest.chm_needs_7z")
            unpack = work / (rel.stem + "_chm")
            subprocess.run([seven, "x", "-y", f"-o{unpack}", str(f)], check=True, capture_output=True)
            for h in unpack.rglob("*.htm*"):
                t = h.with_suffix(".md")
                t.write_text(html_to_md(h.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
        elif suffix == ".md":
            shutil.copyfile(f, target)
    return work
