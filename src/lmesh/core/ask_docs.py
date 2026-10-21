"""AI 查询附件的文字提取（REQ-053）：Excel、PDF、Word、CSV、文本由代码处理，不经过 AI。

- Excel（xlsx）：每张工作表转成带表头的表格文字，保留工作表名与行号，方便 AI 引用某一行。
- PDF：按页提取文字，标出页码。
- Word（docx）：正文段落与表格（标准库解析，不需要额外依赖）。
- CSV、Markdown、文本：原样（统一换行）。
返回的文字还没有脱敏，由调用方脱敏后保存。
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree

from lmesh.core import importer

DOC_SUFFIXES = (".txt", ".md", ".csv", ".log", ".pdf", ".docx", ".xlsx")
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
MAX_ROWS = 2000  # 每张工作表最多取多少行


class DocError(ValueError):
    def __init__(self, key: str, **fmt: Any):
        super().__init__(key)
        self.key, self.fmt = key, fmt


@dataclass
class Extracted:
    text: str
    meta: dict[str, Any] = field(default_factory=dict)


def suffix(name: str) -> str:
    m = re.search(r"\.[A-Za-z0-9]+$", name)
    return m.group(0).lower() if m else ""


def image_type(name: str, data: bytes) -> str | None:
    """图片的媒体类型；按文件头核对，扩展名对不上时不当作图片。"""
    t = IMAGE_TYPES.get(suffix(name))
    if t == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return t
    if t == "image/jpeg" and data.startswith(b"\xff\xd8\xff"):
        return t
    if t == "image/webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return t
    return None


def _cell(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).replace("\n", " ").strip()
    return s.replace("|", "/")


def _xlsx(data: bytes) -> Extracted:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # 损坏或加密的文件
        raise DocError("ask.attach_unreadable") from e
    parts: list[str] = []
    sheets = rows_total = 0
    for ws in wb.worksheets:
        sheets += 1
        parts.append(f"## Sheet: {ws.title}")
        n = 0
        for i, row in enumerate(ws.iter_rows(values_only=True), 1):
            cells = [_cell(v) for v in row]
            if not any(cells):
                continue
            while cells and not cells[-1]:
                cells.pop()
            parts.append(f"{i}| " + " | ".join(cells))
            n += 1
            if n >= MAX_ROWS:
                parts.append(f"(more rows after row {i} not included)")
                break
        rows_total += n
    wb.close()
    return Extracted("\n".join(parts), {"format": "xlsx", "sheets": sheets, "rows": rows_total})


def _pdf(data: bytes) -> Extracted:
    import pdfplumber

    parts: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                parts.append(f"--- page {i} ---")
                parts.append((page.extract_text() or "").strip())
            pages = len(pdf.pages)
    except Exception as e:
        raise DocError("ask.attach_unreadable") from e
    return Extracted("\n".join(parts), {"format": "pdf", "pages": pages})


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx(data: bytes) -> Extracted:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            root = ElementTree.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as e:
        raise DocError("ask.attach_unreadable") from e
    body = root.find(f"{_W}body")
    parts: list[str] = []
    tables = 0
    for el in list(body) if body is not None else []:
        if el.tag == f"{_W}p":
            t = "".join(x.text or "" for x in el.iter(f"{_W}t")).strip()
            if t:
                parts.append(t)
        elif el.tag == f"{_W}tbl":
            tables += 1
            parts.append(f"## Table {tables}")
            for tr in el.iter(f"{_W}tr"):
                cells = ["".join(x.text or "" for x in tc.iter(f"{_W}t")).strip() for tc in tr.iter(f"{_W}tc")]
                parts.append("| " + " | ".join(_cell(c) for c in cells))
    return Extracted("\n".join(parts), {"format": "docx", "tables": tables})


def _csv(text: str) -> Extracted:
    rows = list(csv.reader(io.StringIO(text)))[:MAX_ROWS]
    lines = [f"{i}| " + " | ".join(_cell(c) for c in r) for i, r in enumerate(rows, 1) if any(r)]
    return Extracted("\n".join(lines), {"format": "csv", "rows": len(lines)})


def extract(name: str, data: bytes) -> Extracted:
    """文档 → 文字（未脱敏）。不认识的类型抛出 DocError（ask.attach_type）。"""
    sfx = suffix(name)
    if sfx == ".xlsx":
        return _xlsx(data)
    if sfx == ".pdf":
        return _pdf(data)
    if sfx == ".docx":
        return _docx(data)
    if sfx == ".csv":
        return _csv(importer.decode(data))
    if sfx in (".txt", ".md", ".log", ""):
        if b"\x00" in data[:4096]:
            raise DocError("ask.attach_type", name=name)
        return Extracted(importer.decode(data), {"format": sfx.lstrip(".") or "txt"})
    raise DocError("ask.attach_type", name=name)
