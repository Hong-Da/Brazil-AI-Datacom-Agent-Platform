"""后端文案：src/lmesh/locales/<语言>.json，代码中只引用键名；缺少翻译时回退到中文。"""

from __future__ import annotations

import json
import logging
from functools import cache
from typing import Any

from lmesh import paths

LANGS = ("zh-CN", "en", "pt-BR")
DEFAULT = "zh-CN"
_log = logging.getLogger("lmesh.i18n")


@cache
def catalog(lang: str) -> dict[str, str]:
    p = paths.PACKAGE_DIR / "locales" / f"{lang}.json"
    if not p.exists():
        return {}
    return dict(json.loads(p.read_text(encoding="utf-8")))


def normalize(lang: str | None) -> str:
    """把 zh / zh-TW / en-US / pt / pt-PT 之类的写法归到支持的三种语言。"""
    if not lang:
        return DEFAULT
    low = lang.strip().lower()
    if low.startswith("zh"):
        return "zh-CN"
    if low.startswith("en"):
        return "en"
    if low.startswith("pt"):
        return "pt-BR"
    return DEFAULT


def from_accept_language(header: str | None) -> str:
    if not header:
        return DEFAULT
    for part in header.split(","):
        tag = part.split(";")[0].strip().lower()
        if tag.startswith(("zh", "en", "pt")):
            return normalize(tag)
    return DEFAULT


def t(key: str, lang: str | None = None, **kwargs: Any) -> str:
    lang = normalize(lang)
    text = catalog(lang).get(key)
    if text is None:
        _log.debug("缺少翻译 %s [%s]", key, lang)
        text = catalog(DEFAULT).get(key, key)
    return text.format(**kwargs) if kwargs else text
