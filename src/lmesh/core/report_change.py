"""变更报告（M4-3）：排版 core/change.py 的结果——下发脚本、逐条说明与依赖原因、风险、影响的业务对象、回滚脚本与验证结果。

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
        "title": "配置变更报告",
        "current": "当前配置",
        "target": "目标配置",
        "family": "平台族",
        "ops": "命令数",
        "risk": "风险",
        "risk.low": "低",
        "risk.medium": "中",
        "risk.high": "高",
        "action.add": "新增",
        "action.modify": "修改",
        "action.delete": "删除",
        "action.side_effect": "副作用补发",
        "action.mutex": "互斥（先撤旧）",
        "commands": "下发命令",
        "seq": "序号",
        "action": "动作",
        "view": "视图",
        "command": "命令",
        "object": "对象",
        "after": "排在其后（依赖）",
        "script": "下发脚本",
        "script_note": "按视图分块；以注释符开头的行是说明。执行前请人工确认，标注兜底的命令需要特别检查。",
        "rollback": "回滚脚本",
        "rollback_note": "把目标配置恢复为当前配置的脚本，同样按依赖排序。",
        "verify_ok": "验证通过：在当前配置上模拟执行后，与目标按有效值一致，没有新的悬空引用，执行顺序没有问题。",
        "verify_bad": "验证未通过：模拟执行后与目标不一致、出现悬空引用或顺序问题，请勿直接执行。",
        "impact": "影响的业务对象",
        "impact_none": "没有影响到业务对象（VPN 实例、对等体、接口等）。",
        "type": "类别",
        "path": "影响路径",
        "unsupported": "没能生成命令的节点",
        "equal": "当前配置与目标配置按有效值一致，不需要变更。",
        "fallback": "兜底",
        "item": "项目",
        "value": "值",
    },
    "en": {
        "title": "Configuration Change Report",
        "current": "Current",
        "target": "Target",
        "family": "Platform family",
        "ops": "Commands",
        "risk": "Risk",
        "risk.low": "Low",
        "risk.medium": "Medium",
        "risk.high": "High",
        "action.add": "Add",
        "action.modify": "Modify",
        "action.delete": "Delete",
        "action.side_effect": "Side-effect restore",
        "action.mutex": "Mutex (remove first)",
        "commands": "Commands",
        "seq": "#",
        "action": "Action",
        "view": "View",
        "command": "Command",
        "object": "Object",
        "after": "After (dependencies)",
        "script": "Change script",
        "script_note": "Grouped by view; lines starting with the comment mark are explanations. Review before "
        "running; check the fallback commands carefully.",
        "rollback": "Rollback script",
        "rollback_note": "Restores the target configuration to the current one, ordered by dependencies as well.",
        "verify_ok": "Verified: simulating the script on the current configuration yields the target (effective "
        "values), with no new dangling references and no ordering problems.",
        "verify_bad": "Verification failed: the simulated result differs from the target, leaves dangling "
        "references or has ordering problems; do not run it as is.",
        "impact": "Affected business objects",
        "impact_none": "No business objects (VPN instances, peers, interfaces, ...) are affected.",
        "type": "Category",
        "path": "Impact path",
        "unsupported": "Nodes without a generated command",
        "equal": "The current and target configurations are equal by effective values; nothing to change.",
        "fallback": "fallback",
        "item": "Item",
        "value": "Value",
    },
}

_DEP = {
    "zh-CN": {
        "contains": "所在对象",
        "reference": "引用",
        "prerequisite": "前置",
        "key": "键引用",
        "alias": "引用",
        "referenced_by": "先撤引用方",
        "side_effect": "副作用",
        "side_effect_cleanup": "副作用前删除",
        "mutex": "互斥",
        "replace": "先删旧",
        "undo_first": "先删后建",
        "rewrite": "取消后补写",
    },
    "en": {
        "contains": "parent",
        "reference": "references",
        "prerequisite": "requires",
        "key": "key ref",
        "alias": "references",
        "referenced_by": "referrer first",
        "side_effect": "side effect",
        "side_effect_cleanup": "before side effect",
        "mutex": "mutex",
        "replace": "remove old first",
        "undo_first": "remove then recreate",
        "rewrite": "rewrite after undo",
    },
}


class _ChangeDoc(_Doc):
    def t(self, key: str, **kw: Any) -> str:
        text = TEXTS[self.lang].get(key) or report.TEXTS[self.lang].get(key, key)
        return text.format(**kw) if kw else text


def _ops_table(doc: _Doc, items: list[dict[str, Any]], fmt: str) -> None:
    rows, classes = [], []
    for d in items:
        act = doc.t(f"action.{d['action']}")
        badge = f'<span class="badge">{html.escape(act)}</span>' if fmt == "html" else act
        deps = "; ".join(
            f"[{a['seq']}] {_DEP[doc.lang].get(a['kind'], a['kind'])} {a['label']}" for a in d.get("after") or []
        )
        cmd = doc.code(d["text"]) + (f" ({doc.t('fallback')})" if d.get("fallback") else "")
        rows.append(
            [
                doc.esc(d["seq"]),
                badge,
                doc.esc(doc.t(f"risk.{d['risk']}")),
                doc.esc(" › ".join(d["context"]) or "—"),
                cmd,
                doc.node(d["object"]) if d.get("object") else "—",
                doc.esc(deps or "—"),
            ]
        )
        classes.append({"add": "k-added", "delete": "k-removed", "mutex": "k-removed"}.get(d["action"], "k-changed"))
    doc.table(
        [
            doc.t("seq"),
            doc.t("action"),
            doc.t("risk"),
            doc.t("view"),
            doc.t("command"),
            doc.t("object"),
            doc.t("after"),
        ],
        rows,
        "diffs",
        classes,
    )


def change_report(
    result: dict[str, Any],
    lang: str,
    fmt: str,
    now: datetime | None = None,
    namer: Namer | None = None,
) -> Report:
    """result 是 change.change 的结果。"""
    report._check_args(lang, fmt)
    doc = _ChangeDoc(fmt, lang, namer)
    cur, tgt, s = result["current"], result["target"], result["summary"]
    title = doc.t("title")
    doc.h(1, title)
    doc.p(f"{doc.t('generated')}: {report._now(now)}", "note")
    doc.table(
        [doc.t("item"), doc.t("current"), doc.t("target")],
        [
            [doc.esc(doc.t("device")), doc.esc(cur.get("label")), doc.esc(tgt.get("label"))],
            [doc.esc(doc.t("profile")), doc.esc(cur.get("profile")), doc.esc(tgt.get("profile"))],
            [doc.esc(doc.t("family")), doc.esc(result.get("family")), doc.esc(result.get("family"))],
        ],
        "meta",
    )
    doc.section("summary")
    doc.h(2, doc.t("summary"))
    report._stats(
        doc,
        [(doc.t("ops"), s["ops"]), (doc.t("risk"), doc.t(f"risk.{result['risk']['level']}"))]
        + [(doc.t(f"action.{k}"), v) for k, v in s["by_action"].items() if v],
    )
    if result.get("equal"):
        doc.p(doc.t("equal"), "ok")
    doc.end()

    for key, part in (("script", result), ("rollback", result.get("rollback"))):
        if not part or not part.get("ops"):
            continue
        doc.section(key)
        doc.h(2, doc.t(key))
        doc.p(doc.t(f"{key}_note"), "note")
        if key == "script":
            doc.h(3, doc.t("commands"))
            _ops_table(doc, part["ops"], fmt)
        doc.pre(part["script"])
        v = part.get("verify")
        if v is not None:
            doc.p(doc.t("verify_ok") if v.get("ok") else doc.t("verify_bad"), "ok" if v.get("ok") else "bad")
        doc.end()

    imp = result.get("impact")
    if imp is not None:
        doc.section("impact")
        doc.h(2, doc.t("impact"))
        if not imp.get("business"):
            doc.p(doc.t("impact_none"), "note")
        else:
            doc.table(
                [doc.t("type"), doc.t("object"), doc.t("path")],
                [
                    [doc.esc(b["type"]), doc.node(b["node"]), doc.esc(" → ".join(doc.name(x) for x in b["path"]))]
                    for b in imp["business"]
                ],
            )
        doc.end()

    if result.get("unsupported"):
        doc.section("unsupported")
        doc.h(2, doc.t("unsupported"))
        doc.table(
            [doc.t("node"), doc.t("value")],
            [[doc.node(u["node"]), doc.esc(u.get("reason"))] for u in result["unsupported"]],
        )
        doc.end()
    name = f"change-{report._safe(cur.get('label'))}-{report._safe(tgt.get('label'))}.{lang}.{fmt}"
    return Report(name, doc.render(title), report._media(fmt))
