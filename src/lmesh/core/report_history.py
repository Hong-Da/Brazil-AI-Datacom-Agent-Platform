"""版本差异报告（M5-2）：排版 core/history.py 的两个快照之间的变化。

复用 core/report.py 的排版（_Doc：HTML 自包含可打印 / Markdown 贴进工单），只有中文与 English（其他语言用英文）。
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from lmesh.core import report
from lmesh.core.report import Namer, Report, _Doc

TEXTS: dict[str, dict[str, str]] = {
    "zh-CN": {
        "title": "配置版本差异报告",
        "snapshot": "快照",
        "imported": "导入时间",
        "source": "来源",
        "kb": "解析用的知识库",
        "fingerprint": "内容指纹",
        "tag": "标签",
        "added": "新增",
        "modified": "修改",
        "removed": "删除",
        "renamed": "改名",
        "noneff": "只是写法不同（不计入）",
        "fmt": "只是格式不同的行（不计入）",
        "kb_note": "两个快照解析时用的知识库版本不同（A：{a}，B：{b}），部分差异可能来自知识库升级。",
        "kb_rebuilt": "两侧都已按当前知识库 {kb} 重新解析后比较（临时结果，快照本身不变）。",
        "equal": "两个快照按有效值一致，没有配置变化。",
        "items": "变化的对象",
        "object": "对象",
        "kind": "变化",
        "changes": "明细",
        "text": "配置原文差异",
        "text_note": "统一差异格式：- 为 A 中的行，+ 为 B 中的行；只列出变化处前后 3 行。",
        "rename": "{a} → {b}",
        "more": "（另有 {n} 行未列出）",
    },
    "en": {
        "title": "Configuration Version Diff Report",
        "snapshot": "Snapshot",
        "imported": "Imported",
        "source": "Source",
        "kb": "Parsed with KB",
        "fingerprint": "Fingerprint",
        "tag": "Tag",
        "added": "Added",
        "modified": "Modified",
        "removed": "Removed",
        "renamed": "Renamed",
        "noneff": "Same value, different wording (not counted)",
        "fmt": "Format-only lines (not counted)",
        "kb_note": "The two snapshots were parsed with different KB versions (A: {a}, B: {b}); some differences may come from the KB upgrade.",
        "kb_rebuilt": "Both sides were re-parsed with the current KB {kb} before comparing (temporary; the snapshots are unchanged).",
        "equal": "The two snapshots have the same effective values; no configuration change.",
        "items": "Changed objects",
        "object": "Object",
        "kind": "Change",
        "changes": "Details",
        "text": "Config text diff",
        "text_note": "Unified diff: - lines are in A, + lines are in B; 3 lines of context around each change.",
        "rename": "{a} → {b}",
        "more": "({n} more lines not shown)",
    },
}

_MAX_TEXT_LINES = 2000


class _HistDoc(_Doc):
    def t(self, key: str, **kw: Any) -> str:
        text = TEXTS[self.lang].get(key) or report.TEXTS[self.lang].get(key, key)
        return text.format(**kw) if kw else text


def _snap(doc: _Doc, s: dict[str, Any]) -> list[str]:
    im = (s.get("imports") or [{}])[0]
    return [
        doc.esc(f"#{s['seq']} (v{s['id']})"),
        doc.esc(im.get("imported_at") or s.get("collected_at") or ""),
        doc.esc(f"{im.get('source_kind', '')} · {im.get('source_name', '')}"),
        doc.esc(s.get("kb_version") or "—"),
        doc.code(str(s.get("fingerprint") or "")[:16]),
        doc.esc(s.get("tag") or "—"),
    ]


def _value(v: dict[str, Any] | None) -> str:
    if not v:
        return "—"
    return report._value_text(v.get("value"))


def history_report(
    result: dict[str, Any], lang: str, fmt: str, now: datetime | None = None, namer: Namer | None = None
) -> Report:
    """result 是 history.diff 的结果（含 text 时附原文差异）。"""
    report._check_args(lang, fmt)
    doc = _HistDoc(fmt, lang, namer)
    dev, a, b, s = result["device"], result["a"], result["b"], result["summary"]
    title = doc.t("title")
    doc.h(1, f"{title} · {dev['name']}")
    doc.p(f"{doc.t('generated')}: {report._now(now)}", "note")
    rows = list(zip(*[_snap(doc, a), _snap(doc, b)], strict=True))
    labels = [doc.t(k) for k in ("snapshot", "imported", "source", "kb", "fingerprint", "tag")]
    doc.table(["", "A", "B"], [[doc.esc(lb), ra, rb] for lb, (ra, rb) in zip(labels, rows, strict=True)], "meta")
    kb = result["kb"]
    if kb.get("rebuilt"):
        doc.p(doc.t("kb_rebuilt", kb=kb.get("current")), "note")
    elif kb.get("differs"):
        doc.p(doc.t("kb_note", a=kb.get("a"), b=kb.get("b")), "note")

    doc.section("summary")
    doc.h(2, doc.t("summary"))
    report._stats(
        doc,
        [(doc.t(k), s[k]) for k in ("added", "modified", "removed", "renamed")]
        + [(doc.t("noneff"), s["noneff"]), (doc.t("fmt"), s["fmt"])],
    )
    if result.get("equal"):
        doc.p(doc.t("equal"), "ok")
    doc.end()

    if result["items"]:
        doc.section("items")
        doc.h(2, doc.t("items"))
        by_domain: dict[str, list[dict[str, Any]]] = {}
        for it in result["items"]:
            by_domain.setdefault(it["domain"] or "other", []).append(it)
        for dm, items in by_domain.items():
            doc.h(3, dm)
            trs, classes = [], []
            for it in items:
                kind = doc.t(it["kind"])
                badge = f'<span class="badge">{html.escape(kind)}</span>' if fmt == "html" else kind
                if it["kind"] == "renamed":
                    detail = doc.esc(doc.t("rename", a=it.get("from"), b=it.get("to")))
                else:
                    parts = [
                        f"{c['field']}: {_value(c.get('a'))} → {_value(c.get('b'))}" for c in it.get("changes", [])[:12]
                    ]
                    detail = doc.esc("; ".join(parts))
                trs.append([badge, doc.node(it["object"]), detail])
                classes.append({"modified": "k-changed"}.get(it["kind"], f"k-{it['kind']}"))
            doc.table([doc.t("kind"), doc.t("object"), doc.t("changes")], trs, row_cls=classes)
        doc.end()

    text = result.get("text")
    if text and text.get("hunks"):
        doc.section("text")
        doc.h(2, doc.t("text"))
        doc.p(doc.t("text_note"), "note")
        out: list[str] = []
        for h in text["hunks"]:
            out.append(f"@@ -{h['a_start']},{h['a_len']} +{h['b_start']},{h['b_len']} @@")
            for ln in h["lines"]:
                mark = {"equal": " ", "del": "-", "add": "+"}[ln["op"]]
                out.append(mark + ln["text"])
        extra = max(0, len(out) - _MAX_TEXT_LINES)
        doc.pre("\n".join(out[:_MAX_TEXT_LINES]) + ("\n" + doc.t("more", n=extra) if extra else ""))
        doc.end()
    content = doc.render(f"{title} · {dev['name']}")
    name = f"history-{report._safe(dev['name'])}-{a['seq']}-{b['seq']}.{lang}.{fmt}"
    return Report(name, content, report._media(fmt))
