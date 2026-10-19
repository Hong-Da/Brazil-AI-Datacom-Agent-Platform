"""日志：同时输出到控制台和 logs/lmesh.log，按日期轮转，保留天数来自配置；过滤敏感信息。
访问审计（lmesh.audit，M6）另写 logs/audit.log（同样按日期轮转与保留）。"""

from __future__ import annotations

import logging
import re
import sys
from logging.handlers import TimedRotatingFileHandler

from lmesh import paths

_SECRET_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+"),
    re.compile(r"((?:api[_-]?key|token|password|passwd|secret)\s*[=:]\s*)\S+", re.IGNORECASE),
    re.compile(r"(%\^%#).*?(%\^%#)"),  # 华为 cipher 密文
    re.compile(r"(postgresql(?:\+\w+)?://[^:/@]+:)[^@]+(@)"),
    re.compile(r"\b(lmp_[A-Za-z0-9]{4})[A-Za-z0-9]{28}\b"),  # 个人令牌只留前 8 个字符
]


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for p in _SECRET_PATTERNS:
            msg = p.sub(lambda m: m.group(1) + "***" + (m.group(2) if m.lastindex and m.lastindex >= 2 else ""), msg)
        record.msg, record.args = msg, ()
        return True


_configured = False


def setup(level: str = "INFO", keep_days: int = 14, console: bool = True) -> None:
    global _configured
    root = logging.getLogger("lmesh")
    root.setLevel(level)
    if _configured:
        for h in root.handlers:
            if isinstance(h, TimedRotatingFileHandler):
                h.backupCount = keep_days
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    paths.logs_dir().mkdir(parents=True, exist_ok=True)
    fh = TimedRotatingFileHandler(
        paths.logs_dir() / "lmesh.log", when="midnight", backupCount=keep_days, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    fh.addFilter(RedactFilter())
    root.addHandler(fh)
    ah = TimedRotatingFileHandler(
        paths.logs_dir() / "audit.log", when="midnight", backupCount=keep_days, encoding="utf-8"
    )
    ah.setFormatter(fmt)
    ah.addFilter(RedactFilter())
    logging.getLogger("lmesh.audit").addHandler(ah)
    if console:
        ch = logging.StreamHandler(sys.stderr)
        ch.setFormatter(fmt)
        ch.addFilter(RedactFilter())
        root.addHandler(ch)
    root.propagate = False
    _configured = True


def get(name: str) -> logging.Logger:
    return logging.getLogger(f"lmesh.{name}")
