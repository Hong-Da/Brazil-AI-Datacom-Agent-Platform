"""后端文案：src/lmesh/locales/<语言>.json，代码中只引用键名；缺少翻译时回退到中文。"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
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


def pick(m: Any, lang: str | None) -> str:
    """多语言文本 {zh-CN, en, pt-BR}（例如知识库依赖说明 Note）按语言取值：缺失时回退英文、中文；字符串原样返回。"""
    if m is None:
        return ""
    if not isinstance(m, Mapping):
        return str(m)
    lang = normalize(lang)
    return str(m.get(lang) or m.get("en") or m.get(DEFAULT) or next(iter(m.values()), "") or "")


def is_text_map(v: Any) -> bool:
    return isinstance(v, Mapping) and all(k in LANGS for k in v)


def localize(params: Mapping[str, Any], lang: str | None) -> dict[str, Any]:
    """文案参数中的多语言文本换成对应语言的字符串。"""
    return {k: pick(v, lang) if is_text_map(v) else v for k, v in params.items()}


def t(key: str, lang: str | None = None, **kwargs: Any) -> str:
    lang = normalize(lang)
    text = catalog(lang).get(key)
    if text is None:
        _log.debug("缺少翻译 %s [%s]", key, lang)
        text = catalog(DEFAULT).get(key, key)
    return text.format(**localize(kwargs, lang)) if kwargs else text
