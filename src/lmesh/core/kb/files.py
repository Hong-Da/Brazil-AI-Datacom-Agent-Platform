"""知识库文件的读写（往返模式：保留注释、顺序和引号），供抽取、审核、管理界面写回使用。"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

CARD_FIELDS = (
    "id",
    "syntax",
    "view",
    "enters_view",
    "undo",
    "params",
    "default",
    "maps",
    "depends_on",
    "side_effects",
    "source",
    "status",
    "note",
    "maps_manual",
)


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096  # 不折行，长语法保持一行
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def load_rt(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return _yaml().load(fh)


def dump_rt(path: Path, data: Any) -> None:
    """原子写入：先写临时文件再替换，同时读取的请求不会读到写了一半的文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        _yaml().dump(data, fh)
    for attempt in range(40):  # Windows 上文件正被读取时替换会失败，稍等重试
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 39:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.05)


def card_file(kb_root: Path, family: str, domain: str) -> Path:
    return kb_root / "commands" / family / f"{domain}.yaml"


def load_card_doc(path: Path, domain: str, header: str = "") -> CommentedMap:
    if path.exists():
        doc = load_rt(path)
        if doc is None:
            doc = CommentedMap()
    else:
        doc = CommentedMap()
        if header:
            doc.yaml_set_start_comment(header)
    doc.setdefault("domain", domain)
    if doc.get("cards") is None:
        doc["cards"] = CommentedSeq()
    return doc  # type: ignore[no-any-return]


def to_card_map(card: dict[str, Any]) -> CommentedMap:
    m = CommentedMap()
    for k in CARD_FIELDS:
        v = card.get(k)
        if v is None or v == {} or v == []:
            continue
        m[k] = v
    return m


def find_card(kb_root: Path, card_id: str) -> tuple[Path, CommentedMap, int] | None:
    """在所有平台族的命令卡文件中查找一张卡：返回 (文件, 文档, 下标)。"""
    for f in sorted((kb_root / "commands").glob("*/*.yaml")):
        if f.name == "views.yaml":
            continue
        doc = load_rt(f)
        for i, c in enumerate((doc or {}).get("cards") or []):
            if str(c.get("id")) == card_id:
                return f, doc, i
    return None


def comparable(card: dict[str, Any]) -> dict[str, Any]:
    """比较两张卡是否实质相同时忽略的字段：状态、来源行号。"""
    # 写文件时省略空值，读回来是 None：比较时空值一律视为没有
    out = {k: card.get(k) for k in CARD_FIELDS if k not in ("status", "note") and card.get(k) not in (None, {}, [], "")}
    src = dict(out.get("source") or {})
    src.pop("line", None)
    out["source"] = src
    return _plain(out)


def _plain(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_plain(x) for x in v]
    return v
