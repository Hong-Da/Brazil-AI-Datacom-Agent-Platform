"""报告导出：配置对比报告与配置检查报告，中文与 English，HTML（自包含、内联样式、可打印）与 Markdown（贴进工单）。

报告只排版 core 已经算好的结果（compare.compare / checks.check / cleanup.cleanup），不重新计算结论。
报告正文只有中文与英文：其他界面语言（pt-BR）用英文。文案在本模块的 TEXTS 表里。
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

import networkx as nx

from lmesh.core import checks, cleanup, i18n
from lmesh.core import rules as rulesmod
from lmesh.core.kb import KnowledgeBase

LANGS = ("zh-CN", "en")
FORMATS = ("html", "md")
KINDS = ("compare", "check")

TEXTS: dict[str, dict[str, str]] = {
    "zh-CN": {
        "compare.title": "配置对比报告",
        "check.title": "配置检查报告",
        "generated": "生成时间",
        "options": "选项",
        "item": "项目",
        "device": "设备",
        "version": "配置版本",
        "sw_version": "软件版本",
        "collected_at": "采集时间",
        "profile": "Profile",
        "kb_version": "知识库版本",
        "summary": "概要",
        "diffs": "差异",
        "diff_total": "差异总数",
        "kind": "类型",
        "kind.added": "新增",
        "kind.removed": "删除",
        "kind.changed": "修改",
        "kind.renamed": "改名",
        "domain": "功能域",
        "node": "节点",
        "lines": "行",
        "origin.explicit": "显式",
        "origin.default": "默认",
        "origin.derived": "派生",
        "children": "含 {n} 个子节点",
        "related": "关联",
        "renames": "改名",
        "schema": "对象类型",
        "from": "原名（A）",
        "to": "新名（B）",
        "similarity": "相似度",
        "default_only": "不可比（只有一侧 Profile 有默认值）",
        "default_only_note": "这些属性只有一侧的 Profile 定义了默认值，另一侧既没有配置也没有默认值，不算差异。",
        "side": "所在侧",
        "value": "有效值",
        "unknown": "未识别行",
        "unknown_note": "知识库还不认识的行，不参与对比。",
        "line": "行号",
        "text": "原文",
        "equal": "两份配置在比较范围内等价，没有差异。",
        "none": "无",
        "hidden_identity": "已隐藏的身份差异：{n} 处（Router ID、接口地址、对等体地址、主机名等）。",
        "opt.domain": "功能域",
        "opt.include_raw": "比较功能域外的原文行",
        "opt.interface_map": "接口映射条数",
        "opt.rename_threshold": "改名相似度阈值",
        "opt.hide_identity": "隐藏身份差异",
        "opt.compare_ext": "比较未映射命令（同平台族）",
        "opt.severity": "最低级别",
        "all": "全部",
        "yes": "是",
        "no": "否",
        "findings": "发现",
        "finding_total": "发现总数",
        "ignored_total": "已忽略",
        "severity": "级别",
        "severity.error": "错误",
        "severity.warning": "警告",
        "severity.info": "提示",
        "rule": "规则",
        "message": "说明",
        "suggestion": "建议",
        "ignored": "已忽略的发现",
        "ignore_reason": "忽略原因",
        "no_findings": "没有发现问题。",
        "cleanup": "清理脚本",
        "cleanup_note": "为孤儿对象生成的删除命令（先删引用方再删被引用方），执行前请人工确认；标注 FALLBACK 的命令是兜底写法。",
        "verify_ok": "验证通过：删除后没有新的悬空引用。",
        "verify_failed": "验证未通过：删除后会产生新的悬空引用，请勿直接执行。",
        "footer": "由透网 LucidMesh 生成。结论由代码在配置图上计算。",
    },
    "en": {
        "compare.title": "Configuration Comparison Report",
        "check.title": "Configuration Check Report",
        "generated": "Generated",
        "options": "Options",
        "item": "Item",
        "device": "Device",
        "version": "Config version",
        "sw_version": "Software version",
        "collected_at": "Collected",
        "profile": "Profile",
        "kb_version": "Knowledge base version",
        "summary": "Summary",
        "diffs": "Differences",
        "diff_total": "Total differences",
        "kind": "Kind",
        "kind.added": "Added",
        "kind.removed": "Removed",
        "kind.changed": "Changed",
        "kind.renamed": "Renamed",
        "domain": "Domain",
        "node": "Node",
        "lines": "line",
        "origin.explicit": "explicit",
        "origin.default": "default",
        "origin.derived": "derived",
        "children": "{n} child node(s)",
        "related": "Related",
        "renames": "Renames",
        "schema": "Object type",
        "from": "Old name (A)",
        "to": "New name (B)",
        "similarity": "Similarity",
        "default_only": "Not comparable (default on one side only)",
        "default_only_note": "Only one side's Profile defines a default for these attributes and the other side neither "
        "configures them nor has a default; they are not counted as differences.",
        "side": "Side",
        "value": "Effective value",
        "unknown": "Unrecognized lines",
        "unknown_note": "Lines the knowledge base does not recognize yet; they are not compared.",
        "line": "Line",
        "text": "Text",
        "equal": "The two configurations are equivalent within the compared scope; no differences.",
        "none": "None",
        "hidden_identity": "Hidden identity differences: {n} (router ID, interface addresses, peer addresses, "
        "host name, etc.).",
        "opt.domain": "Domain",
        "opt.include_raw": "Compare raw lines outside the domains",
        "opt.interface_map": "Interface map entries",
        "opt.rename_threshold": "Rename similarity threshold",
        "opt.hide_identity": "Hide identity differences",
        "opt.compare_ext": "Compare unmapped commands (same family)",
        "opt.severity": "Minimum severity",
        "all": "All",
        "yes": "Yes",
        "no": "No",
        "findings": "Findings",
        "finding_total": "Total findings",
        "ignored_total": "Ignored",
        "severity": "Severity",
        "severity.error": "Error",
        "severity.warning": "Warning",
        "severity.info": "Info",
        "rule": "Rule",
        "message": "Description",
        "suggestion": "Suggestion",
        "ignored": "Ignored findings",
        "ignore_reason": "Reason",
        "no_findings": "No issues found.",
        "cleanup": "Cleanup script",
        "cleanup_note": "Removal commands for orphan objects (referrers first). Review before running; commands "
        "marked FALLBACK use the generic undo form.",
        "verify_ok": "Verified: the removal leaves no new dangling references.",
        "verify_failed": "Verification failed: the removal would leave dangling references; do not run it as is.",
        "footer": "Generated by LucidMesh. Conclusions are computed by code on the configuration graph.",
    },
}


class ReportError(ValueError):
    def __init__(self, key: str, **fmt: Any):
        super().__init__(key)
        self.key, self.fmt = key, fmt


@dataclass
class Report:
    filename: str
    content: str
    media_type: str

    def disposition(self) -> str:
        """Content-Disposition：ASCII 文件名兜底，filename* 给出 UTF-8 原名。"""
        ascii_name = re.sub(r"[^A-Za-z0-9._@-]", "_", self.filename)
        return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(self.filename)}"


def report_lang(lang: str | None) -> str:
    """报告语言：中文或英文；其他语言（pt-BR）用英文。"""
    return "zh-CN" if (lang or "").lower().startswith("zh") else "en"


def _check_args(lang: str, fmt: str) -> None:
    if lang not in LANGS:
        raise ReportError("report.bad_lang", allowed=", ".join(LANGS))
    if fmt not in FORMATS:
        raise ReportError("report.bad_format", allowed=", ".join(FORMATS))


def _safe(name: Any) -> str:
    s = re.sub(r"[^\w.@-]+", "_", str(name or "config")).strip("._")
    return s[:80] or "config"


def _now(now: datetime | None) -> str:
    return (now or datetime.now().astimezone()).strftime("%Y-%m-%d %H:%M:%S %z")


def version_meta(db_url: str, version_id: int | None) -> dict[str, Any]:
    """配置版本的软件版本与采集时间（报告头用）；没有版本时为空。"""
    if version_id is None:
        return {}
    from lmesh.core import projects, store
    from lmesh.core.store.models import ConfigVersion, Device, iso

    with store.session(db_url) as s:
        ver = s.get(ConfigVersion, version_id)
        if ver is None or not projects.visible(s, ver.device_id):
            return {}
        dev = s.get(Device, ver.device_id)
        return {
            "version_id": ver.id,
            "sw_version": dev.sw_version if dev else "",
            "collected_at": iso(ver.collected_at),
        }


# ---------------------------------------------------------------- 文本片段


def _value_text(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, dict | list):
        return json.dumps(v, ensure_ascii=False, default=str)
    return str(v)


def _lines_text(lines: list[int] | None, limit: int = 8) -> str:
    if not lines:
        return ""
    shown = ", ".join(map(str, lines[:limit]))
    return shown + (" …" if len(lines) > limit else "")


Namer = Callable[[str], str]  # 规范编号 → 显示用的命令路径（见 core/terms.describe）


class _Doc:
    """HTML 与 Markdown 共用的一组排版操作。"""

    def __init__(self, fmt: str, lang: str, namer: Namer | None = None):
        self.fmt, self.lang, self.namer = fmt, lang, namer
        self.parts: list[str] = []

    def name(self, node_id: str) -> str:
        """节点按显示风格写成命令路径（没有给出显示方式时用规范编号）。"""
        return self.namer(node_id) if self.namer else node_id

    def node(self, node_id: str) -> str:
        """表格里的节点：命令路径在前，规范编号附在后面便于追溯。"""
        label = self.name(node_id)
        if label == node_id:
            return self.code(node_id)
        sep = " " if self.fmt == "md" else "<br>"
        return (
            self.code(label)
            + sep
            + (f"`{node_id}`" if self.fmt == "md" else f'<span class="note">{html.escape(node_id)}</span>')
        )

    def t(self, key: str, **kw: Any) -> str:
        text = TEXTS[self.lang].get(key, key)
        return text.format(**i18n.localize(kw, self.lang)) if kw else text

    # -- 行内
    def esc(self, s: Any) -> str:
        s = "" if s is None else str(s)
        if self.fmt == "html":
            return html.escape(s)
        return s.replace("\\", "\\\\").replace("|", "\\|").replace("\r", "").replace("\n", " ")

    def code(self, s: Any) -> str:
        if self.fmt == "html":
            return f"<code>{html.escape(str(s))}</code>"
        text = str(s).replace("|", "\\|").replace("\n", " ")
        return f"``{text}``" if "`" in text else f"`{text}`"

    def side(self, sv: dict[str, Any] | None, count: int | None = None) -> str:
        """一侧的有效值：值、来源、原文行号（对象附子节点数）。"""
        if not sv:
            return "—"
        bits = [self.code(_value_text(sv.get("value")))]
        origin = sv.get("origin") or "explicit"
        ln = _lines_text(sv.get("lines"))
        tail = [self.t(f"origin.{origin}")]
        if count:
            tail.append(self.t("children", n=count))
        if ln:
            tail.append(f"{self.t('lines')} {ln}")
        if self.fmt == "html":
            cls = f"origin o-{html.escape(origin)}"
            return f'{bits[0]}<br><span class="{cls}">{html.escape(" · ".join(tail))}</span>'
        return f"{bits[0]} · {' · '.join(tail)}"

    # -- 块
    def h(self, level: int, text: str, anchor: str = "") -> None:
        if self.fmt == "html":
            aid = f' id="{anchor}"' if anchor else ""
            self.parts.append(f"<h{level}{aid}>{html.escape(text)}</h{level}>")
        else:
            self.parts.append(f"{'#' * level} {text}\n")

    def p(self, text: str, cls: str = "") -> None:
        if self.fmt == "html":
            c = f' class="{cls}"' if cls else ""
            self.parts.append(f"<p{c}>{html.escape(text)}</p>")
        else:
            self.parts.append(f"{'> ' if cls == 'note' else ''}{text}\n")

    def table(self, header: list[str], rows: list[list[str]], cls: str = "", row_cls: list[str] | None = None) -> None:
        """单元格已经是转义后的内容（esc / code / side）。"""
        if self.fmt == "html":
            out = [f'<table class="{cls}">' if cls else "<table>", "<thead><tr>"]
            out += [f"<th>{html.escape(h)}</th>" for h in header]
            out.append("</tr></thead><tbody>")
            for i, r in enumerate(rows):
                rc = f' class="{row_cls[i]}"' if row_cls and row_cls[i] else ""
                out.append(f"<tr{rc}>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>")
            out.append("</tbody></table>")
            self.parts.append("".join(out))
        else:
            out = ["| " + " | ".join(self.esc(h) for h in header) + " |", "|" + "---|" * len(header)]
            out += ["| " + " | ".join(c if c else " " for c in r) + " |" for r in rows]
            self.parts.append("\n".join(out) + "\n")

    def pre(self, text: str) -> None:
        if self.fmt == "html":
            self.parts.append(f"<pre>{html.escape(text)}</pre>")
        else:
            self.parts.append(f"```text\n{text.rstrip()}\n```\n")

    def section(self, name: str) -> None:
        if self.fmt == "html":
            self.parts.append(f'<section class="{name}">')

    def end(self) -> None:
        if self.fmt == "html":
            self.parts.append("</section>")

    def render(self, title: str) -> str:
        if self.fmt == "md":
            return "\n".join(self.parts).rstrip() + "\n"
        body = "\n".join(self.parts)
        return (
            f'<!doctype html>\n<html lang="{self.lang}">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<meta name="generator" content="LucidMesh">\n<title>{html.escape(title)}</title>\n'
            f'<style>{_CSS}</style>\n</head>\n<body>\n<main class="report">\n{body}\n'
            f"<footer>{html.escape(self.t('footer'))}</footer>\n</main>\n</body>\n</html>\n"
        )


_CSS = """
:root{--ink:#1d2433;--muted:#5b6475;--line:#d9dee7;--soft:#f5f7fa;--accent:#1f5fbf;
--add:#e7f6ec;--add-ink:#17663a;--del:#fdecec;--del-ink:#a32020;--chg:#fff6e0;--chg-ink:#8a5a00;
--ren:#ece9fb;--ren-ink:#4b3a9e;--err:#a32020;--warn:#8a5a00;--info:#1f5fbf}
*{box-sizing:border-box}
html{color-scheme:light}
body{margin:0;background:#fff;color:var(--ink);font:14px/1.55 "Segoe UI","PingFang SC","Microsoft YaHei",
"Noto Sans CJK SC",system-ui,sans-serif}
.report{max-width:1180px;margin:0 auto;padding:32px 28px 48px}
h1{font-size:24px;margin:0 0 4px;letter-spacing:.01em}
h2{font-size:18px;margin:28px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--ink)}
h3{font-size:15px;margin:20px 0 8px;color:var(--accent)}
p{margin:6px 0}
p.note{color:var(--muted);font-size:13px}
p.ok{color:var(--add-ink);font-weight:600}
p.bad{color:var(--del-ink);font-weight:600}
table{width:100%;border-collapse:collapse;margin:6px 0 14px;font-size:13px}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top;word-break:break-word}
thead th{background:var(--soft);font-weight:600}
table.meta{width:auto;min-width:60%}
table.meta th{width:12em;background:var(--soft)}
code{font:12.5px/1.45 "Cascadia Mono",Consolas,"SFMono-Regular",monospace;background:var(--soft);
padding:1px 4px;border-radius:3px}
pre{font:12.5px/1.5 "Cascadia Mono",Consolas,monospace;background:var(--soft);border:1px solid var(--line);
padding:10px 12px;white-space:pre-wrap;word-break:break-word}
.origin{color:var(--muted);font-size:12px}
.o-default,.o-derived{font-style:italic}
.badge{display:inline-block;padding:0 7px;border-radius:9px;font-size:12px;font-weight:600;white-space:nowrap}
tr.k-added .badge{background:var(--add);color:var(--add-ink)}
tr.k-removed .badge{background:var(--del);color:var(--del-ink)}
tr.k-changed .badge{background:var(--chg);color:var(--chg-ink)}
tr.k-renamed .badge{background:var(--ren);color:var(--ren-ink)}
tr.s-error .badge{background:var(--del);color:var(--err)}
tr.s-warning .badge{background:var(--chg);color:var(--warn)}
tr.s-info .badge{background:#e8f0fc;color:var(--info)}
tr.ignored td{color:var(--muted)}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0 4px;padding:0;list-style:none}
.stats li{border:1px solid var(--line);border-radius:6px;padding:6px 12px;min-width:7em}
.stats b{display:block;font-size:20px}
footer{margin-top:36px;padding-top:10px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}
@page{size:A4;margin:14mm 12mm}
@media print{
  body{font-size:11.5px}
  .report{max-width:none;padding:0}
  h2{break-after:avoid}
  h3{break-after:avoid}
  thead{display:table-header-group}
  tr,pre{break-inside:avoid}
  *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
}
"""


def _stats(doc: _Doc, items: list[tuple[str, Any]]) -> None:
    if doc.fmt == "html":
        lis = "".join(f"<li><b>{html.escape(str(v))}</b>{html.escape(k)}</li>" for k, v in items)
        doc.parts.append(f'<ul class="stats">{lis}</ul>')
    else:
        doc.parts.append(" · ".join(f"{k}: **{v}**" for k, v in items) + "\n")


def _yes(doc: _Doc, v: Any) -> str:
    return doc.t("yes") if v else doc.t("no")


# ---------------------------------------------------------------- 对比报告


def compare_report(
    result: dict[str, Any],
    lang: str,
    fmt: str,
    meta: dict[str, dict[str, Any]] | None = None,
    now: datetime | None = None,
    namer: Namer | None = None,
) -> Report:
    """result 是 compare.compare 的结果；meta 是 {"a": version_meta, "b": version_meta}（可省）。"""
    _check_args(lang, fmt)
    meta = meta or {}
    doc = _Doc(fmt, lang, namer)
    a, b, s, opts = result["a"], result["b"], result["summary"], result["options"]
    title = doc.t("compare.title")
    doc.h(1, title)
    doc.p(f"{doc.t('generated')}: {_now(now)}", "note")

    def side_rows(key: str, getter: Any) -> list[str]:
        return [doc.esc(doc.t(key)), doc.esc(getter(a, meta.get("a", {}))), doc.esc(getter(b, meta.get("b", {})))]

    rows = [
        side_rows("device", lambda x, m: x.get("device") or x.get("label")),
        side_rows("version", lambda x, m: _ver(x, m)),
        side_rows("sw_version", lambda x, m: m.get("sw_version") or "—"),
        side_rows("profile", lambda x, m: x.get("profile") or "—"),
        side_rows("kb_version", lambda x, m: x.get("kb_version") or "—"),
    ]
    doc.table([doc.t("item"), "A", "B"], rows, "meta")

    doc.h(2, doc.t("options"))
    opt_rows = [
        [doc.esc(doc.t("opt.domain")), doc.esc(opts.get("domain") or doc.t("all"))],
        [doc.esc(doc.t("opt.include_raw")), doc.esc(_yes(doc, opts.get("include_raw")))],
        [doc.esc(doc.t("opt.hide_identity")), doc.esc(_yes(doc, opts.get("hide_identity")))],
        [doc.esc(doc.t("opt.interface_map")), doc.esc(opts.get("interface_map", 0))],
        [doc.esc(doc.t("opt.rename_threshold")), doc.esc(opts.get("rename_threshold"))],
        [doc.esc(doc.t("opt.compare_ext")), doc.esc(_yes(doc, opts.get("compare_ext")))],
    ]
    doc.table([doc.t("item"), doc.t("value")], opt_rows, "meta")

    doc.section("summary")
    doc.h(2, doc.t("summary"))
    _stats(
        doc,
        [(doc.t("diff_total"), s["total"])]
        + [(doc.t(f"kind.{k}"), s["by_kind"].get(k, 0)) for k in ("added", "removed", "changed", "renamed")]
        + [(doc.t("default_only"), s.get("default_only", 0))]
        + [(doc.t("unknown") + " A / B", f"{s['unknown']['a']} / {s['unknown']['b']}")],
    )
    if s.get("hidden_identity"):
        doc.p(doc.t("hidden_identity", n=s["hidden_identity"]), "note")
    if s["by_domain"]:
        doc.table(
            [doc.t("domain"), *[doc.t(f"kind.{k}") for k in ("added", "removed", "changed", "renamed")], "Σ"],
            [
                [
                    doc.esc(dm),
                    *[doc.esc(v.get(k, 0)) for k in ("added", "removed", "changed", "renamed")],
                    doc.esc(v["total"]),
                ]
                for dm, v in s["by_domain"].items()
            ],
        )
    doc.end()

    doc.section("diffs")
    doc.h(2, doc.t("diffs"))
    if not result["diffs"]:
        doc.p(doc.t("equal"), "ok")
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for d in result["diffs"]:
        by_domain.setdefault(d["domain"] or "-", []).append(d)
    for dm, items in by_domain.items():
        doc.h(3, f"{dm} ({len(items)})")
        rows, classes = [], []
        for d in items:
            badge = doc.t(f"kind.{d['kind']}")
            kind_cell = f'<span class="badge">{html.escape(badge)}</span>' if fmt == "html" else badge
            node = doc.node(d["node"])
            if d.get("related"):
                related = ", ".join(doc.name(r) for r in d["related"])
                node += (" " if fmt == "md" else "<br>") + doc.esc(f"{doc.t('related')}: {related}")
            count = d.get("count")
            rows.append(
                [
                    kind_cell,
                    node,
                    doc.side(d["a"], count if d["a"] else None),
                    doc.side(d["b"], count if d["b"] else None),
                ]
            )
            classes.append(f"k-{d['kind']}")
        doc.table([doc.t("kind"), doc.t("node"), "A", "B"], rows, "diffs", classes)
    doc.end()

    doc.section("renames")
    doc.h(2, doc.t("renames"))
    if result["renames"]:
        doc.table(
            [doc.t("schema"), doc.t("from"), doc.t("to"), doc.t("similarity")],
            [
                [doc.code(r["schema"]), doc.code(r["from"]), doc.code(r["to"]), doc.esc(r["similarity"])]
                for r in result["renames"]
            ],
        )
    else:
        doc.p(doc.t("none"), "note")
    doc.end()

    doc.section("default-only")
    doc.h(2, doc.t("default_only"))
    if result["default_only"]:
        doc.p(doc.t("default_only_note"), "note")
        doc.table(
            [doc.t("domain"), doc.t("node"), doc.t("side"), doc.t("value")],
            [
                [
                    doc.esc(x["domain"]),
                    doc.node(x["node"]),
                    doc.esc(x["side"].upper()),
                    doc.code(_value_text(x["value"])),
                ]
                for x in result["default_only"]
            ],
        )
    else:
        doc.p(doc.t("none"), "note")
    doc.end()

    doc.section("unknown")
    doc.h(2, doc.t("unknown"))
    unknown = [("A", u) for u in result["unknown"]["a"]] + [("B", u) for u in result["unknown"]["b"]]
    if unknown:
        doc.p(doc.t("unknown_note"), "note")
        doc.table(
            [doc.t("side"), doc.t("line"), doc.t("text")],
            [[side, doc.esc(u["line"]), doc.code(u["text"])] for side, u in unknown],
        )
    else:
        doc.p(doc.t("none"), "note")
    doc.end()

    name = f"compare-{_safe(a.get('label'))}-{_safe(b.get('label'))}.{lang}.{fmt}"
    return Report(name, doc.render(title), _media(fmt))


def _ver(side: dict[str, Any], m: dict[str, Any]) -> str:
    vid = side.get("version_id") or m.get("version_id")
    if not vid:
        return "—"
    return f"#{vid}" + (f" ({m['collected_at']})" if m.get("collected_at") else "")


def _media(fmt: str) -> str:
    return "text/html; charset=utf-8" if fmt == "html" else "text/markdown; charset=utf-8"


# ---------------------------------------------------------------- 检查报告


def check_report(
    result: dict[str, Any],
    lang: str,
    fmt: str,
    clean: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    now: datetime | None = None,
    namer: Namer | None = None,
) -> Report:
    """result 是 checks.check 的结果；clean 是 cleanup.cleanup 的结果（有孤儿时附清理脚本）。"""
    _check_args(lang, fmt)
    meta = meta or {}
    doc = _Doc(fmt, lang, namer)
    s = result["summary"]
    title = doc.t("check.title")
    doc.h(1, title)
    doc.p(f"{doc.t('generated')}: {_now(now)}", "note")
    filters = result.get("filters") or {}
    doc.table(
        [doc.t("item"), doc.t("value")],
        [
            [doc.esc(doc.t("device")), doc.esc(result.get("device"))],
            [doc.esc(doc.t("version")), doc.esc(_ver({}, meta))],
            [doc.esc(doc.t("sw_version")), doc.esc(meta.get("sw_version") or "—")],
            [doc.esc(doc.t("profile")), doc.esc(result.get("profile") or "—")],
            [doc.esc(doc.t("kb_version")), doc.esc(result.get("kb_version") or "—")],
            [doc.esc(doc.t("opt.severity")), doc.esc(doc.t(f"severity.{filters.get('severity') or 'info'}"))],
            [doc.esc(doc.t("opt.domain")), doc.esc(filters.get("domain") or doc.t("all"))],
        ],
        "meta",
    )

    doc.section("summary")
    doc.h(2, doc.t("summary"))
    _stats(
        doc,
        [(doc.t("finding_total"), s["total"])]
        + [(doc.t(f"severity.{k}"), s["by_severity"].get(k, 0)) for k in rulesmod.SEVERITIES]
        + [(doc.t("ignored_total"), s.get("ignored", 0))],
    )
    doc.end()

    texts = result.get("texts") or {}
    active = [f for f in result["findings"] if not f.get("ignored")]
    ignored = [f for f in result["findings"] if f.get("ignored")]

    def finding_rows(items: list[dict[str, Any]], with_reason: bool = False) -> tuple[list[list[str]], list[str]]:
        rows, classes = [], []
        for f in items:
            badge = doc.t(f"severity.{f['severity']}")
            sev = f'<span class="badge">{html.escape(badge)}</span>' if fmt == "html" else badge
            row = [
                sev,
                doc.code(f["rule"]),
                doc.esc(f["domain"] or "-"),
                doc.node(f["node"]),
                doc.esc(_lines_text(f["lines"], 12)),
                doc.esc(checks.render_text(f["message"], lang, texts)),
                doc.esc(checks.render_text(f["suggestion"], lang, texts)),
            ]
            if with_reason:
                row.append(doc.esc(f.get("ignore_reason") or ""))
            rows.append(row)
            classes.append(f"s-{f['severity']}" + (" ignored" if with_reason else ""))
        return rows, classes

    header = [
        doc.t("severity"),
        doc.t("rule"),
        doc.t("domain"),
        doc.t("node"),
        doc.t("line"),
        doc.t("message"),
        doc.t("suggestion"),
    ]
    doc.section("findings")
    doc.h(2, doc.t("findings"))
    if not active:
        doc.p(doc.t("no_findings"), "ok")
    for sev in rulesmod.SEVERITIES:
        items = [f for f in active if f["severity"] == sev]
        if not items:
            continue
        doc.h(3, f"{doc.t(f'severity.{sev}')} ({len(items)})")
        rows, classes = finding_rows(items)
        doc.table(header, rows, "findings", classes)
    doc.end()

    if ignored:
        doc.section("ignored")
        doc.h(2, f"{doc.t('ignored')} ({len(ignored)})")
        rows, classes = finding_rows(ignored, True)
        doc.table([*header, doc.t("ignore_reason")], rows, "findings", classes)
        doc.end()

    if clean and clean.get("commands"):
        doc.section("cleanup")
        doc.h(2, doc.t("cleanup"))
        doc.p(doc.t("cleanup_note"), "note")
        doc.pre(clean["script"])
        ok = (clean.get("verify") or {}).get("ok", True)
        doc.p(doc.t("verify_ok") if ok else doc.t("verify_failed"), "ok" if ok else "bad")
        doc.end()

    name = f"check-{_safe(result.get('device'))}.{lang}.{fmt}"
    return Report(name, doc.render(title), _media(fmt))


ORPHAN_RULES = ("ref.orphan", "ref.orphan_cascade")


def build_check_report(
    g: nx.MultiDiGraph,
    kb: KnowledgeBase,
    result: dict[str, Any],
    lang: str,
    fmt: str,
    meta: dict[str, Any] | None = None,
    now: datetime | None = None,
    namer: Namer | None = None,
) -> Report:
    """检查报告：有没被忽略的孤儿发现时附上清理脚本（cleanup.cleanup 在同一张图上生成并验证）。"""
    _check_args(lang, fmt)
    orphan = any(f["rule"] in ORPHAN_RULES and not f.get("ignored") for f in result["findings"])
    clean = cleanup.cleanup(g, kb) if orphan else None
    return check_report(result, lang, fmt, clean, meta, now, namer)
