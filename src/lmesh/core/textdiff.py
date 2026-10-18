"""配置 / 脚本的文本差异（REQ-031 文本差异对比）：逐行对比、行内字符级标记、移动识别、忽略顺序、统一 diff 与中英 HTML 报告。

行对比用 difflib.SequenceMatcher；删除与新增中文本相同（去掉首尾空白后比较）的行配成“移动”（a 第几行 → b 第几行），
不算删除加新增；同一改动块中剩下的行按位置配对为“修改”，并给出两侧改动的字符区间。
忽略顺序：每行带上它所在的视图路径（按缩进找到的上级行），按多重集合比较，只列出内容差异。
语义差异（按有效值比较）由调用方用 core/compare.py 计算后放进报告。
"""

from __future__ import annotations

import difflib
import html
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from lmesh.core.report import _CSS, Report

ROW_TYPES = ("equal", "change", "add", "del", "move_from", "move_to")
_SKIP = {"", "#", "!"}
# 结构行（进出视图、会话命令、分隔符）：不参与移动配对，不计入新增 / 删除统计，忽略顺序时也不比较
_STRUCT = _SKIP | {
    "quit",
    "exit",
    "exit-address-family",
    "return",
    "end",
    "commit",
    "system-view",
    "configure terminal",
}


def _norm(s: str) -> str:
    return " ".join(s.split())


def _spans(a: str, b: str) -> tuple[list[list[int]], list[list[int]]]:
    sa: list[list[int]] = []
    sb: list[list[int]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("replace", "delete") and i2 > i1:
            sa.append([i1, i2])
        if tag in ("replace", "insert") and j2 > j1:
            sb.append([j1, j2])
    return sa, sb


def diff(a_text: str, b_text: str, ignore_order: bool = False) -> dict[str, Any]:
    """两段文本的逐行差异。rows 是并排视图的行（上下视图由同一组行渲染）。"""
    a = a_text.replace("\r\n", "\n").rstrip("\n").split("\n") if a_text else []
    b = b_text.replace("\r\n", "\n").rstrip("\n").split("\n") if b_text else []
    sm = difflib.SequenceMatcher(None, [x.rstrip() for x in a], [x.rstrip() for x in b], autojunk=False)
    ops = sm.get_opcodes()
    deleted: list[int] = []  # a 的下标
    inserted: list[int] = []  # b 的下标
    for tag, i1, i2, j1, j2 in ops:
        if tag in ("delete", "replace"):
            deleted += [i for i in range(i1, i2) if _norm(a[i]) not in _STRUCT]
        if tag in ("insert", "replace"):
            inserted += [j for j in range(j1, j2) if _norm(b[j]) not in _STRUCT]
    pool: dict[str, list[int]] = defaultdict(list)
    for j in inserted:
        pool[_norm(b[j])].append(j)
    move_a: dict[int, int] = {}
    for i in deleted:
        cands = pool.get(_norm(a[i]))
        if cands:
            j = min(cands, key=lambda x: abs(x - i))
            cands.remove(j)
            move_a[i] = j
    move_b = {j: i for i, j in move_a.items()}

    rows: list[dict[str, Any]] = []
    stats = Counter({k: 0 for k in ("equal", "change", "add", "del", "move")})

    def row(t: str, ai: int | None, bj: int | None, **kw: Any) -> None:
        r: dict[str, Any] = {
            "t": t,
            "a": None if ai is None else ai + 1,
            "b": None if bj is None else bj + 1,
            "at": None if ai is None else a[ai],
            "bt": None if bj is None else b[bj],
        }
        r.update(kw)
        rows.append(r)

    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            for k in range(i2 - i1):
                row("equal", i1 + k, j1 + k)
                stats["equal"] += 1
            continue
        da = [i for i in range(i1, i2) if i not in move_a]
        db = [j for j in range(j1, j2) if j not in move_b]
        pairs = list(zip(da, db, strict=False)) if tag == "replace" else []
        paired_a = {i for i, _ in pairs}
        paired_b = {j for _, j in pairs}
        pair_of_a = dict(pairs)
        # 先按 a 的顺序输出删除侧（修改行在这里成对输出），再输出 b 侧剩下的新增 / 移入
        for i in range(i1, i2):
            if i in move_a:
                row("move_from", i, None, to=move_a[i] + 1)
                stats["move"] += 1
            elif i in paired_a:
                j = pair_of_a[i]
                sa, sb = _spans(a[i], b[j])
                row("change", i, j, sa=sa, sb=sb)
                stats["change"] += 1
            else:
                row("del", i, None)
                if _norm(a[i]) not in _STRUCT:
                    stats["del"] += 1
        for j in range(j1, j2):
            if j in move_b:
                row("move_to", None, j, **{"from": move_b[j] + 1})
            elif j not in paired_b:
                row("add", None, j)
                if _norm(b[j]) not in _STRUCT:
                    stats["add"] += 1
    out: dict[str, Any] = {
        "stats": {**dict(stats), "lines_a": len(a), "lines_b": len(b)},
        "equal": all(r["t"] == "equal" for r in rows),
        "rows": rows,
        "moves": [{"from": i + 1, "to": j + 1, "text": a[i].strip()} for i, j in sorted(move_a.items())],
        "unified": unified(a_text, b_text),
    }
    if ignore_order:
        out["unordered"] = unordered(a, b)
    return out


def _paths(lines: list[str]) -> list[tuple[str, int]]:
    """每行（跳过空行、分隔符）带上按缩进找到的上级行，作为忽略顺序时的比较键。"""
    out: list[tuple[str, int]] = []
    stack: list[tuple[int, str]] = []
    for no, ln in enumerate(lines, start=1):
        s = _norm(ln)
        if s.lower() in _STRUCT:
            if s in _SKIP and s and len(ln) - len(ln.lstrip()) == 0:
                stack.clear()
            continue
        ind = len(ln) - len(ln.lstrip())
        while stack and stack[-1][0] >= ind:
            stack.pop()
        out.append((" > ".join([*(t for _, t in stack), s]), no))
        stack.append((ind, s))
    return out


def unordered(a: list[str], b: list[str]) -> dict[str, Any]:
    pa, pb = _paths(a), _paths(b)
    ca, cb = Counter(k for k, _ in pa), Counter(k for k, _ in pb)
    la: dict[str, list[int]] = defaultdict(list)
    lb: dict[str, list[int]] = defaultdict(list)
    for k, n in pa:
        la[k].append(n)
    for k, n in pb:
        lb[k].append(n)
    only_a: list[dict[str, Any]] = [
        {"text": k, "count": ca[k] - cb.get(k, 0), "lines": la[k]} for k in ca if ca[k] > cb.get(k, 0)
    ]
    only_b: list[dict[str, Any]] = [
        {"text": k, "count": cb[k] - ca.get(k, 0), "lines": lb[k]} for k in cb if cb[k] > ca.get(k, 0)
    ]
    only_a.sort(key=lambda x: x["lines"][0])
    only_b.sort(key=lambda x: x["lines"][0])
    return {"equal": not only_a and not only_b, "only_a": only_a, "only_b": only_b}


def unified(a_text: str, b_text: str, a_name: str = "a", b_name: str = "b", context: int = 3) -> str:
    a = a_text.replace("\r\n", "\n").splitlines()
    b = b_text.replace("\r\n", "\n").splitlines()
    return "".join(x + "\n" for x in difflib.unified_diff(a, b, a_name, b_name, n=context, lineterm=""))


# ---------------------------------------------------------------- 报告

TEXTS = {
    "zh-CN": {
        "title": "配置文本差异报告",
        "a": "A（旧）",
        "b": "B（新）",
        "generated": "生成时间",
        "stats": "统计",
        "add": "新增",
        "del": "删除",
        "change": "修改",
        "move": "移动",
        "equal": "相同",
        "same": "两侧文本相同。",
        "lines": "行差异（并排，相同的行只保留上下文）",
        "moves": "移动的行",
        "from": "原行号",
        "to": "新行号",
        "text": "内容",
        "semantic": "语义差异（按有效值比较）",
        "semantic_equal": "按有效值比较没有差异（只是写法或顺序不同）。",
        "kind": "类型",
        "node": "对象",
        "value_a": "A 的取值",
        "value_b": "B 的取值",
        "unordered": "忽略顺序后的内容差异",
        "only_a": "只在 A 中",
        "only_b": "只在 B 中",
        "footer": "由透网 LucidMesh 生成",
        "skipped": "… 省略 {n} 行相同内容 …",
    },
    "en": {
        "title": "Configuration text diff report",
        "a": "A (old)",
        "b": "B (new)",
        "generated": "Generated",
        "stats": "Statistics",
        "add": "Added",
        "del": "Removed",
        "change": "Changed",
        "move": "Moved",
        "equal": "Same",
        "same": "Both texts are identical.",
        "lines": "Line differences (side by side; identical lines kept only as context)",
        "moves": "Moved lines",
        "from": "From line",
        "to": "To line",
        "text": "Text",
        "semantic": "Semantic differences (by effective value)",
        "semantic_equal": "No difference by effective value (only spelling or order differ).",
        "kind": "Kind",
        "node": "Object",
        "value_a": "Value in A",
        "value_b": "Value in B",
        "unordered": "Content differences ignoring order",
        "only_a": "Only in A",
        "only_b": "Only in B",
        "footer": "Generated by LucidMesh",
        "skipped": "… {n} identical lines skipped …",
    },
}

_EXTRA_CSS = """
table.diff{table-layout:fixed;font:12.5px/1.5 "Cascadia Mono",Consolas,monospace}
table.diff td{padding:1px 6px;border:none;border-bottom:1px solid #eef1f5;white-space:pre-wrap}
table.diff td.n{width:4.5em;color:var(--muted);text-align:right;user-select:none}
tr.d-add td.b,tr.d-move_to td.b{background:var(--add)}
tr.d-del td.a,tr.d-move_from td.a{background:var(--del)}
tr.d-change td.a{background:#fff3f0}tr.d-change td.b{background:#f0fbf3}
tr.d-move_from td.a,tr.d-move_to td.b{background:var(--ren)}
tr.skip td{color:var(--muted);text-align:center;background:var(--soft)}
mark.ca{background:#f7c6c6}mark.cb{background:#bfe8cb}
.mv{color:var(--ren-ink);font-size:11px;margin-left:6px}
"""


def _mark(text: str | None, spans: list[list[int]] | None, cls: str) -> str:
    if text is None:
        return ""
    if not spans:
        return html.escape(text)
    out, pos = [], 0
    for s, e in spans:
        out.append(html.escape(text[pos:s]))
        out.append(f'<mark class="{cls}">{html.escape(text[s:e])}</mark>')
        pos = e
    out.append(html.escape(text[pos:]))
    return "".join(out)


def _collapse(rows: list[dict[str, Any]], context: int = 3) -> list[dict[str, Any] | int]:
    keep = [False] * len(rows)
    for i, r in enumerate(rows):
        if r["t"] != "equal":
            for k in range(max(0, i - context), min(len(rows), i + context + 1)):
                keep[k] = True
    out: list[dict[str, Any] | int] = []
    skipped = 0
    for r, k in zip(rows, keep, strict=True):
        if k:
            if skipped:
                out.append(skipped)
                skipped = 0
            out.append(r)
        else:
            skipped += 1
    if skipped:
        out.append(skipped)
    return out


def report(
    result: dict[str, Any],
    a_label: str,
    b_label: str,
    lang: str = "zh-CN",
    fmt: str = "html",
    semantic: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> Report:
    """fmt=html：中文 / 英文自包含报告；fmt=unified：统一 diff 文本（.diff）。"""
    if fmt == "unified":
        body = unified_from(result, a_label, b_label)
        return Report("diff.diff", body, "text/x-diff; charset=utf-8")
    t = TEXTS["zh-CN" if lang.lower().startswith("zh") else "en"]
    st = result["stats"]
    when = (now or datetime.now().astimezone()).strftime("%Y-%m-%d %H:%M:%S %z")
    parts = [
        f"<h1>{html.escape(t['title'])}</h1>",
        '<table class="meta"><tbody>',
        f"<tr><th>{t['a']}</th><td>{html.escape(a_label)}</td></tr>",
        f"<tr><th>{t['b']}</th><td>{html.escape(b_label)}</td></tr>",
        f"<tr><th>{t['generated']}</th><td>{html.escape(when)}</td></tr>",
        "</tbody></table>",
        f"<h2>{t['stats']}</h2>",
        '<ul class="stats">'
        + "".join(
            f"<li><b>{st.get(k, 0)}</b>{html.escape(t[k])}</li>" for k in ("add", "del", "change", "move", "equal")
        )
        + "</ul>",
    ]
    if result["equal"]:
        parts.append(f'<p class="ok">{html.escape(t["same"])}</p>')
    else:
        parts.append(f"<h2>{t['lines']}</h2>")
        parts.append('<table class="diff"><tbody>')
        for r in _collapse(result["rows"]):
            if isinstance(r, int):
                parts.append(f'<tr class="skip"><td colspan="4">{html.escape(t["skipped"].format(n=r))}</td></tr>')
                continue
            mv = ""
            if r["t"] == "move_from":
                mv = f'<span class="mv">→ {r["to"]}</span>'
            elif r["t"] == "move_to":
                mv = f'<span class="mv">← {r["from"]}</span>'
            parts.append(
                f'<tr class="d-{r["t"]}"><td class="n">{r["a"] or ""}</td>'
                f'<td class="a">{_mark(r["at"], r.get("sa"), "ca")}{mv if r["t"] == "move_from" else ""}</td>'
                f'<td class="n">{r["b"] or ""}</td>'
                f'<td class="b">{_mark(r["bt"], r.get("sb"), "cb")}{mv if r["t"] == "move_to" else ""}</td></tr>'
            )
        parts.append("</tbody></table>")
        if result["moves"]:
            parts.append(f"<h2>{t['moves']}</h2><table><thead><tr>")
            parts.append(f"<th>{t['from']}</th><th>{t['to']}</th><th>{t['text']}</th></tr></thead><tbody>")
            for m in result["moves"]:
                parts.append(
                    f"<tr><td>{m['from']}</td><td>{m['to']}</td><td><code>{html.escape(m['text'])}</code></td></tr>"
                )
            parts.append("</tbody></table>")
    uo = result.get("unordered")
    if uo is not None:
        parts.append(f"<h2>{t['unordered']}</h2>")
        if uo["equal"]:
            parts.append(f'<p class="ok">{html.escape(t["same"])}</p>')
        for key in ("only_a", "only_b"):
            if uo[key]:
                parts.append(f"<h3>{t[key]}</h3><table><tbody>")
                for x in uo[key]:
                    parts.append(
                        f"<tr><td>{', '.join(map(str, x['lines'][:6]))}</td><td><code>{html.escape(x['text'])}</code></td></tr>"
                    )
                parts.append("</tbody></table>")
    if semantic is not None:
        parts.append(f"<h2>{t['semantic']}</h2>")
        if semantic.get("equal"):
            parts.append(f'<p class="ok">{html.escape(t["semantic_equal"])}</p>')
        else:
            parts.append(
                f"<table><thead><tr><th>{t['kind']}</th><th>{t['node']}</th><th>{t['value_a']}</th>"
                f"<th>{t['value_b']}</th></tr></thead><tbody>"
            )
            for d in semantic.get("diffs", []):
                parts.append(
                    f'<tr class="k-{html.escape(str(d["kind"]))}"><td><span class="badge">{html.escape(str(d["kind"]))}</span></td>'
                    f"<td><code>{html.escape(str(d.get('label') or d['node']))}</code></td>"
                    f"<td>{html.escape(_val(d.get('a')))}</td><td>{html.escape(_val(d.get('b')))}</td></tr>"
                )
            parts.append("</tbody></table>")
    page_lang = "zh-CN" if lang.lower().startswith("zh") else "en"
    doc = (
        f'<!doctype html>\n<html lang="{page_lang}">\n<head>\n<meta charset="utf-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(t['title'])}</title>\n<style>{_CSS}{_EXTRA_CSS}</style>\n</head>\n<body>\n"
        f'<main class="report">\n{"".join(parts)}\n<footer>{html.escape(t["footer"])}</footer>\n</main>\n</body>\n</html>\n'
    )
    return Report(f"diff-{page_lang}.html", doc, "text/html; charset=utf-8")


def _val(side: Any) -> str:
    if side is None:
        return "—"
    if isinstance(side, dict):
        v = side.get("value")
        return "—" if v is None else str(v)
    return str(side)


def unified_from(result: dict[str, Any], a_label: str, b_label: str) -> str:
    """统一 diff 的文件头用对比对象的名称。"""
    body = result.get("unified") or ""
    lines = body.split("\n")
    if len(lines) >= 2 and lines[0].startswith("--- ") and lines[1].startswith("+++ "):
        lines[0], lines[1] = f"--- {a_label}", f"+++ {b_label}"
    return "\n".join(lines)
