"""AI 查询会话的下载（REQ-054）。

- 会话报告：HTML（自包含、可打印，浏览器“打印为 PDF”）与 Markdown，中文与 English 各一份；复用 core/report.py 的排版。
- 结果表：某一轮（当前版本）的结果导出为 CSV 或 Excel，带设备、对象、配置行号。
- AI 报告（skill ask-report）：AI 只写句子，数字写 <<键>>、对象写 [[编号]]，由代码从会话结果填入；
  句子里有 AI 自己写的数字或引用了不存在的键 / 编号时标为“未经核对”。
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from typing import Any

from lmesh.core import report
from lmesh.core.report import Report, _Doc

TEXTS: dict[str, dict[str, str]] = {
    "zh-CN": {
        "title": "AI 查询会话报告",
        "owner": "提问人",
        "network": "网络",
        "scope": "范围",
        "all_devices": "网络中全部可查询设备",
        "devices_n": "{n} 台设备",
        "created": "创建时间",
        "updated": "最近更新",
        "turns": "轮次",
        "attachments": "附件",
        "att_config": "配置（临时设备）",
        "att_doc": "文档（参考资料）",
        "att_image": "图片（参考）",
        "turn": "第 {n} 轮",
        "versions": "这一轮共有 {n} 个版本，报告中是当前显示的第 {cur} 版。",
        "context": "追问：AI 看到了前 {n} 轮的问题与图查询（已脱敏）。",
        "question": "问题",
        "query": "代码执行的图查询",
        "query_invalid": "AI 没能写出有效的图查询，这一轮没有结果。",
        "result": "代码执行的结果（{n} 行）",
        "result_more": "（另有 {n} 行未列出，可下载这一轮的结果表）",
        "object": "对象",
        "device": "设备",
        "lines": "配置行",
        "answer": "回答（逐句由代码核对）",
        "st_passed": "已核对",
        "st_corrected": "已更正",
        "st_unverifiable": "无法校验",
        "corrected_to": "代码更正为：{text}",
        "note": "结论由代码在配置图上计算与核对；AI 只负责理解问题与组织文字。发给 AI 的内容已脱敏。",
        "ai_title": "AI 报告",
        "ai_note": "由 AI 撰写（skill ask-report）；数字与对象名由代码从会话结果填入并核对，标“未经核对”的句子请自行确认。",
        "unverified": "（未经核对）",
    },
    "en": {
        "title": "AI Query Session Report",
        "owner": "Asked by",
        "network": "Network",
        "scope": "Scope",
        "all_devices": "All queryable devices in the network",
        "devices_n": "{n} devices",
        "created": "Created",
        "updated": "Last updated",
        "turns": "Turns",
        "attachments": "Attachments",
        "att_config": "Config (temporary device)",
        "att_doc": "Document (reference)",
        "att_image": "Image (reference)",
        "turn": "Turn {n}",
        "versions": "This turn has {n} versions; the report shows version {cur}, the one currently displayed.",
        "context": "Follow-up: the AI saw the previous {n} question(s) and queries (sanitised).",
        "question": "Question",
        "query": "Graph query run by code",
        "query_invalid": "The AI could not write a valid graph query; this turn has no result.",
        "result": "Result computed by code ({n} rows)",
        "result_more": "({n} more rows not shown; download this turn's result table)",
        "object": "Object",
        "device": "Device",
        "lines": "Config lines",
        "answer": "Answer (each statement checked by code)",
        "st_passed": "Verified",
        "st_corrected": "Corrected",
        "st_unverifiable": "Unverifiable",
        "corrected_to": "Corrected by code to: {text}",
        "note": "Conclusions are computed and checked by code on the configuration graph; the AI only understands the question and writes the text. Everything sent to the AI was sanitised.",
        "ai_title": "AI report",
        "ai_note": "Written by the AI (skill ask-report); numbers and object names were filled in and checked by code from the session results — confirm sentences marked “unverified” yourself.",
        "unverified": "(unverified)",
    },
}
MAX_ROWS = 50


class _AskDoc(_Doc):
    def t(self, key: str, **kw: Any) -> str:
        text = TEXTS[self.lang].get(key) or report.TEXTS[self.lang].get(key, key)
        return text.format(**kw) if kw else text


def current_version(turn: dict[str, Any]) -> dict[str, Any]:
    vs = turn.get("versions") or [{}]
    return dict(vs[min(int(turn.get("current") or 0), len(vs) - 1)])


def _cell_text(c: Any) -> str:
    if not isinstance(c, dict):
        return "" if c is None else str(c)
    if c.get("secret"):
        return "(secret)"
    v = c.get("value")
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return "" if v is None else str(v)


def session_report(
    sess: dict[str, Any], lang: str, fmt: str, now: datetime | None = None, ai: dict[str, Any] | None = None
) -> Report:
    """sess 是 ask_sessions.get 的结果；ai 是已生成的 AI 报告（可选，放在开头）。"""
    report._check_args(lang, fmt)
    doc = _AskDoc(fmt, lang)
    title = sess.get("title") or doc.t("title")
    doc.h(1, f"{doc.t('title')} · {title}")
    doc.p(f"{doc.t('generated')}: {report._now(now)}", "note")
    devs = sess.get("devices")
    scope = doc.t("all_devices") if not devs else doc.t("devices_n", n=len(devs))
    meta = [
        (doc.t("owner"), sess.get("owner") or "-"),
        (doc.t("network"), sess.get("network") or "-"),
        (doc.t("scope"), scope),
        (doc.t("created"), (sess.get("created_at") or "")[:19].replace("T", " ")),
        (doc.t("updated"), (sess.get("updated_at") or "")[:19].replace("T", " ")),
        (doc.t("turns"), str(len(sess.get("turn_list") or []))),
    ]
    doc.table(["", ""], [[doc.esc(k), doc.esc(v)] for k, v in meta], "meta")
    doc.p(doc.t("note"), "note")
    atts = sess.get("attachment_list") or []
    if atts:
        doc.section("attachments")
        doc.h(2, doc.t("attachments"))
        doc.table(
            ["", ""],
            [[doc.esc(a["name"]), doc.esc(doc.t(f"att_{a['kind']}"))] for a in atts],
        )
        doc.end()
    if ai and ai.get("markdown"):
        doc.section("ai")
        doc.h(2, doc.t("ai_title"))
        doc.p(doc.t("ai_note"), "note")
        doc.pre(str(ai["markdown"]))
        doc.end()
    for i, turn in enumerate(sess.get("turn_list") or [], 1):
        v = current_version(turn)
        res = v.get("result") or {}
        doc.section(f"turn-{i}")
        doc.h(2, doc.t("turn", n=i))
        nv = len(turn.get("versions") or [])
        if nv > 1:
            doc.p(doc.t("versions", n=nv, cur=int(turn.get("current") or 0) + 1), "note")
        if v.get("context"):
            doc.p(doc.t("context", n=v["context"]), "note")
        doc.h(3, doc.t("question"))
        doc.p(str(v.get("question") or ""))
        if not res.get("query_text"):
            doc.p(doc.t("query_invalid"), "note")
            doc.end()
            continue
        doc.h(3, doc.t("query"))
        doc.pre(str(res["query_text"]))
        table = res.get("result") or {}
        rows = table.get("rows") or []
        cols = [c["field"] for c in table.get("columns") or []]
        doc.h(3, doc.t("result", n=table.get("count", len(rows))))
        trs = []
        for r in rows[:MAX_ROWS]:
            cells = r.get("cells") or {}
            trs.append(
                [str(r.get("n", ""))]
                + [doc.code(r.get("label") or "")]
                + [doc.esc(_cell_text(cells.get(c))) for c in cols]
                + [doc.esc(r.get("device") or ""), doc.esc(",".join(str(x) for x in (r.get("lines") or [])[:8]))]
            )
        doc.table(["#", doc.t("object"), *cols, doc.t("device"), doc.t("lines")], trs)
        if len(rows) > MAX_ROWS:
            doc.p(doc.t("result_more", n=len(rows) - MAX_ROWS), "note")
        ans = res.get("answer") or {}
        sts = ans.get("statements") or []
        if sts:
            doc.h(3, doc.t("answer"))
            out = []
            for s in sts:
                st = str(s.get("status") or "unverifiable")
                label = doc.t(f"st_{st}") if f"st_{st}" in TEXTS[lang] else st
                line = str(s.get("text", ""))
                if s.get("corrected_text"):
                    line += " — " + doc.t("corrected_to", text=s["corrected_text"])
                out.append([doc.esc(label), doc.esc(line)])
            doc.table(["", ""], out)
        doc.end()
    content = doc.render(f"{doc.t('title')} · {title}")
    name = f"ask-session-{sess.get('id')}.{lang}.{fmt}"
    return Report(name, content, report._media(fmt))


# ---------------------------------------------------------------- 结果表


def _table_rows(res: dict[str, Any]) -> tuple[list[str], list[list[Any]]]:
    table = (res or {}).get("result") or {}
    cols = [c["field"] for c in table.get("columns") or []]
    head = ["#", "object", "node", *cols, "device", "lines"]
    rows = []
    for r in table.get("rows") or []:
        cells = r.get("cells") or {}
        rows.append(
            [r.get("n"), r.get("label") or "", r.get("node") or ""]
            + [_cell_text(cells.get(c)) for c in cols]
            + [r.get("device") or "", " ".join(str(x) for x in r.get("lines") or [])]
        )
    return head, rows


def table_csv(res: dict[str, Any]) -> bytes:
    head, rows = _table_rows(res)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(head)
    w.writerows(rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")  # 带 BOM：Excel 直接打开不乱码


def table_xlsx(res: dict[str, Any], title: str = "result") -> bytes:
    import openpyxl
    from openpyxl.styles import Font

    head, rows = _table_rows(res)
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = re.sub(r"[\[\]:*?/\\]", "_", title)[:31] or "result"
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append(r)
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- AI 报告（skill ask-report）

_PH_NUM = re.compile(r"<<([A-Za-z0-9_.\-]+)>>")
_PH_OBJ = re.compile(r"\[\[([A-Za-z]+\d+)\]\]")
_DIGIT = re.compile(r"\d")
_SENT = re.compile(r"(?<=[。！？!?；;])\s*|(?<=\.)\s+")
MAX_OBJECTS = 80


def facts_of(sess: dict[str, Any]) -> dict[str, Any]:
    """AI 报告的事实：数字（键 = 值）与对象（编号 | 类型 | 名称）。只来自代码的结果与核对状态。"""
    numbers: dict[str, Any] = {}
    objects: dict[str, dict[str, str]] = {}
    turns = sess.get("turn_list") or []
    numbers["turns"] = len(turns)
    numbers["attachments"] = len(sess.get("attachment_list") or [])
    if sess.get("devices"):
        numbers["scope.devices"] = len(sess["devices"])
    devices: dict[str, str] = {}
    n_obj = 0
    for i, turn in enumerate(turns, 1):
        v = current_version(turn)
        res = v.get("result") or {}
        objects[f"q{i}"] = {"type": "question", "label": str(v.get("question") or "")[:200]}
        table = res.get("result") or {}
        rows = table.get("rows") or []
        numbers[f"t{i}.rows"] = table.get("count", len(rows))
        sts = (res.get("answer") or {}).get("statements") or []
        for st in ("passed", "corrected", "unverifiable"):
            numbers[f"t{i}.{st}"] = sum(1 for s in sts if s.get("status") == st)
        per_dev: dict[str, int] = {}
        for r in rows:
            dv = str(r.get("device") or "")
            if dv:
                per_dev[dv] = per_dev.get(dv, 0) + 1
                if dv not in devices:
                    devices[dv] = f"d{len(devices) + 1}"
                    objects[devices[dv]] = {"type": "device", "label": dv}
            if n_obj < MAX_OBJECTS and r.get("label"):
                n_obj += 1
                objects[f"o{n_obj}"] = {"type": "object", "label": f"{r['label']} @ {dv}"}
        numbers[f"t{i}.devices"] = len(per_dev)
        for dv, n in per_dev.items():
            numbers[f"t{i}.{devices[dv]}.rows"] = n
        for s in sts:
            if s.get("status") == "corrected" and s.get("corrected_text"):
                n_obj += 1
                objects[f"o{n_obj}"] = {"type": "corrected", "label": str(s["corrected_text"])[:200]}
    numbers["devices"] = len(devices)
    return {"numbers": numbers, "objects": objects}


def facts_text(facts: dict[str, Any]) -> tuple[str, str]:
    nums = "\n".join(f"{k} = {v}" for k, v in facts["numbers"].items())
    objs = "\n".join(f"{k} | {o['type']} | {o['label']}" for k, o in facts["objects"].items())
    return nums, objs


def _fill(text: str, facts: dict[str, Any]) -> tuple[str, bool]:
    """填入占位符；返回 (文字, 是否全部核对通过)。"""
    ok = True
    raw = _PH_OBJ.sub("", _PH_NUM.sub("", text))
    if _DIGIT.search(raw):
        ok = False  # AI 自己写了数字

    def num(m: re.Match[str]) -> str:
        nonlocal ok
        k = m.group(1)
        if k not in facts["numbers"]:
            ok = False
            return m.group(0)
        return str(facts["numbers"][k])

    def obj(m: re.Match[str]) -> str:
        nonlocal ok
        o = facts["objects"].get(m.group(1))
        if o is None:
            ok = False
            return m.group(0)
        return o["label"]

    return _PH_OBJ.sub(obj, _PH_NUM.sub(num, text)), ok


def check_report(reply: str, facts: dict[str, Any], lang: str) -> dict[str, Any]:
    """AI 回复（Markdown，带占位符）→ {markdown, blocks, verified, unverified}。blocks 给界面高亮用。"""
    text = reply.strip()
    m = re.match(r"^```(?:markdown|md)?\s*\n(.*)\n```\s*$", text, re.S)
    if m:
        text = m.group(1)
    mark = TEXTS["zh-CN" if lang == "zh-CN" else "en"]["unverified"]
    blocks: list[dict[str, Any]] = []
    md_lines: list[str] = []
    verified = unverified = 0
    for line in text.splitlines():
        s = line.rstrip()
        if not s.strip():
            md_lines.append("")
            continue
        hm = re.match(r"^(#{1,4})\s+(.*)$", s)
        lm = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*)$", s)
        kind, body, prefix = (
            ("h", hm.group(2), hm.group(1) + " ") if hm else ("li", lm.group(1), "- ") if lm else ("p", s, "")
        )
        segs = []
        out = []
        for part in [p for p in _SENT.split(body) if p and p.strip()]:
            filled, ok = _fill(part, facts)
            if kind != "h":
                verified += ok
                unverified += not ok
            segs.append({"text": filled, "ok": ok})
            out.append(filled if ok else f"{filled}{mark}")
        sep = "" if lang == "zh-CN" else " "
        blocks.append({"type": kind, "level": len(hm.group(1)) if hm else 0, "segments": segs})
        md_lines.append(prefix + sep.join(out))
    return {
        "markdown": "\n".join(md_lines).strip() + "\n",
        "blocks": blocks,
        "verified": verified,
        "unverified": unverified,
    }


def report_messages(skill: Any, facts: dict[str, Any], lang: str, title: str) -> tuple[str, str]:
    from lmesh.core.ask import LANG_NAMES

    nums, objs = facts_text(facts)
    system = skill.system_text(lang=LANG_NAMES.get(lang, "English"))
    prompt = skill.prompt_text(title=title, facts=nums, objects=objs)
    return system, prompt


def ai_report(settings: Any, sess: dict[str, Any], lang: str, actor: Any = None) -> dict[str, Any]:
    """调用 ask-report 写 Markdown 报告并由代码核对。lang 为 pt-BR 时用英文（报告只有中英文）。"""
    from lmesh.core import ask, skills

    lang = "zh-CN" if lang == "zh-CN" else "en"
    ask._require(settings)
    if not sess.get("turn_list"):
        raise ask.AskError("ask_report.empty", "state")
    sk = ask.skill_or_error("ask-report")
    facts = facts_of(sess)
    system, prompt = report_messages(sk, facts, lang, str(sess.get("title") or ""))
    sess_ai = ask._Session(settings, "ask")
    inp = {"facts": facts, "lang": lang, "title": sess.get("title") or ""}
    reply = ask.call_logged(sess_ai, sk, "report", system, prompt, "ask", inp, actor)
    checked = check_report(reply, facts, lang)
    st = "passed" if checked["unverified"] == 0 else "corrected"
    det = {"summary": {"verified": checked["verified"], "unverified": checked["unverified"]}}
    skills.log_run(settings, sk, "ask", st, inp, reply, det, ask.last_info(sess_ai), actor)
    return {**checked, "lang": lang, "ai": sess_ai.info(), "sent": sess_ai.sent}


def replay_check(reply: str, inp: dict[str, Any]) -> dict[str, Any]:
    """skill 测试与回放：按调用时记下的事实核对。"""
    facts = inp.get("facts") or {"numbers": {}, "objects": {}}
    return check_report(reply, facts, str(inp.get("lang") or "en"))


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)
