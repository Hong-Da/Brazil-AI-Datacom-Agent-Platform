"""AI 建议框架（M8-2，REQ-041）：AI 的输出一律先作为建议，由代码校验后展示，用户逐条或批量采纳，采纳可撤销。

一次运行的流程（run → execute，API 放在后台任务里，CLI 同步执行）：
    1. 准备上下文：skill 的上下文构造函数（SkillSpec.build）在图上取事实——对象编号表（d1 设备、n1 对象、c1 差异条目、
       f1 问题……，AI 只能引用这些编号）、由代码算好的数字、配置行数，以及填进提示词的变量。配置来自数据库（导入时已脱敏），
       发送前再经 ask.sanitize_text 脱敏。
    2. 调用 skill：生效版本的提示词（skills.current），经 ask._Session → ai.complete 调用，用量按功能（skill 编号）记录；
       调用记录编号记在批次与每条建议上。
    3. 解析：回复必须是 JSON {"suggestions": [...]}；解析失败时用 skill 的 retry 模板（没有时用通用提示）重试一次，
       仍失败则本次运行记为失败（bad_reply）。
    4. 校验：每条建议先过通用检查（类别、标题、内容结构、引用的编号都在事实里），再交给该类别的校验器（代码实现）。
       结果 pass / warn / reject 及原因列表；reject 的建议也入库（只读展示原因），不能采纳。
    5. 入库：ai_suggestions（每条）与 ai_suggestion_batches（这次运行）；同时记一条 skill 调用记录（来源 suggest，
       被拦截时自动进入回归集，供 REQ-033 的进化使用）。

校验器注册表（CATEGORY → Validator：校验、采纳、撤销）：
    refs_exist    依据型建议：引用的对象、差异条目、行号都在事实里；采纳只记录结论
    script_valid  脚本：先过脚本检查（core/script_check，变更脚本在模拟图上执行），有 error 拒绝；可要求“复检问题消失”；
                  采纳 = 在项目里新建一份脚本（未改动过时撤销会删除它）
    kb_review     知识库草稿（命令卡、规则、映射……）：采纳 = 进审核队列，只有维护员与管理员可以；审核前可撤销
    view_hint     只影响显示（设备角色、分组、标签、层次）：采纳 = 写入项目级视图标注 view_annotations，撤销恢复原值
    text_only     纯文字（摘要、说明）：[[编号]] 提到的对象、<<键>> 由代码填入的数字必须在事实里；正文中直接写出的
                  接口名、地址、主机名必须是图中的对象（否则拒绝）；对不上任何事实的数字给出提醒（warn）
以后加 skill：定义 skill（knowledge/ai-skills/<编号>.yaml，带 group）→ 在这里 register_skill（上下文构造 + 允许的类别）→
选现有类别或 register_category 新写校验器 → 页面接入通用组件（frontend/src/components/ai-suggest/）。
"""

from __future__ import annotations

import contextvars
import dataclasses
import json
import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from lmesh.core import ai, config, i18n, skills, store
from lmesh.core.store.models import AISuggestion, AISuggestionBatch, ReviewItem, ViewAnnotation, iso

_log = logging.getLogger("lmesh.ai_suggest")

STATUSES = ("pending", "adopted", "dismissed", "reverted")
CHECKS = ("pass", "warn", "reject")
SOURCE = "suggest"  # skill 调用记录的来源
MAX_SUGGESTIONS = 200
MAX_TITLE = 400
MAX_TEXT = 4000
MAX_SCRIPT = 200_000
MAX_JSON = 200_000
ROLES = ("core", "aggregation", "access", "pe", "p", "ce")
HINT_KEYS = ("role", "group", "label", "layer")
REVERT_DAYS = 30  # 采纳后 30 天内可以撤销；之后请用版本历史回退（M8-1 评审推荐）
DEFAULT_RETRY = (
    "Your previous reply could not be used: {error}. Reply again with JSON only, exactly in the required format, "
    'and cite only the given ids. Format: {{"suggestions": [...]}}'
)


class SuggestError(ValueError):
    """kind：param 参数（422 / 退出码 2）、not_found（404 / 4）、state 状态不允许（409 / 1）、forbidden（403 / 1）、
    external AI 调用失败（502 / 5）。"""

    def __init__(self, key: str, kind: str = "param", data: Any = None, **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.data, self.fmt = key, kind, data, fmt


# ---------------------------------------------------------------- 运行环境与上下文


@dataclass
class Env:
    """一次调用的环境：配置（绑定发起人，AI 按发起人的选择）、数据库、知识库、当前项目、调用者。"""

    settings: config.Settings
    kb_loader: Callable[[], Any]
    project_id: int | None = None
    user_id: int | None = None
    actor: str = ""
    kb_editor: bool = True  # 管理员与知识库维护员（命令行等同管理员）
    admin: bool = True
    lang: str = "zh-CN"
    _kb: Any = field(default=None, repr=False)
    out: dict[str, Any] = field(default_factory=dict, repr=False)  # 校验器写给界面的附加结果（display / result）
    network_id: int | None = None  # 当前网络（M9）：建议、采纳记录与视图标注按网络独立

    def __post_init__(self) -> None:
        # 只给了项目（直接调用 core、旧数据）时用项目的默认网络
        if self.network_id is None and self.project_id is not None:
            from lmesh.core import networks

            self.network_id = networks.default_network_id(self.db, self.project_id)

    @property
    def db(self) -> str:
        return self.settings.database_url

    @property
    def kb(self) -> Any:
        if self._kb is None:
            self._kb = self.kb_loader()
        return self._kb


@dataclass
class Context:
    """skill 的上下文：vars 填进提示词；facts 是代码给出的事实（校验与界面跳转都用它）。

    facts = {
        "objects": {"d1": {"type": "device", "label": "ATN-1", "device_id": 3}, "n1": {"type": "interface",
                    "label": "GigabitEthernet0/2/0", "device": "d1", "node": "interface[GigabitEthernet0/2/0]",
                    "line": 23}, "c1": {"type": "diff", ...}, ...},
        "numbers": {"count.interface": 12, ...},   # <<键>> 由代码填入
        "lines": {"d1": 99},                         # 引用行号 {"line": n, "of": "d1"} 的上限
        "names": ["UPLINK-TO-AGG", ...],             # 正文中可以直接出现的名称（对象标签与属性取值）
    }
    """

    vars: dict[str, str]
    facts: dict[str, Any]
    scope_key: str
    device_id: int | None = None


@dataclass
class SkillSpec:
    id: str
    build: Callable[[Env, dict[str, Any]], Context]
    categories: tuple[str, ...]
    default_category: str
    scope: str = "device"  # device：需要 device_id；project：整个项目
    prepare: Callable[[Env, dict[str, Any]], None] | None = None  # 提交前的快速检查（设备是否存在等）
    # skill 自己的额外校验（在类别校验之后，例如“每个意图必须挂上差异条目”）；返回原因列表（M8-3）
    check: Callable[[dict[str, Any], dict[str, Any], Env], list[dict[str, Any]]] | None = None


@dataclass
class Validator:
    check: Callable[[dict[str, Any], dict[str, Any], Env], list[dict[str, Any]]]
    adopt: Callable[[Env, AISuggestion, dict[str, Any]], dict[str, Any]]
    revert: Callable[[Env, AISuggestion], dict[str, Any]]
    kb: bool = False  # 采纳需要知识库权限（维护员与管理员）
    batch: bool = True  # 是否允许批量采纳


CATEGORIES: dict[str, Validator] = {}
SKILLS: dict[str, SkillSpec] = {}
KB_CHECKS: dict[str, Callable[[dict[str, Any], Env], list[dict[str, Any]]]] = {}  # kb_review 按草稿类型的额外校验


def register_category(name: str, validator: Validator) -> None:
    CATEGORIES[name] = validator


def register_skill(spec: SkillSpec) -> None:
    for c in spec.categories:
        if c not in CATEGORIES:
            raise ValueError(f"unknown category {c}")
    SKILLS[spec.id] = spec


def spec_of(skill_id: str) -> SkillSpec:
    _load_skills()
    spec = SKILLS.get(skill_id)
    if spec is None:
        raise SuggestError("ai_suggest.skill_unknown", "not_found", id=skill_id)
    return spec


def _load_skills() -> None:
    """示范与后续 skill 的上下文构造分散在各自模块里注册，用到前先导入。"""
    from lmesh.core import (
        ai_suggest_analysis,  # noqa: F401  （M8-3 日常分析）
        ai_suggest_change,  # noqa: F401  （M8-4 变更与割接）
        ai_suggest_kb,  # noqa: F401  （M8-5 规范与合规、知识库构建、报告）
        ai_suggest_skills,  # noqa: F401
    )


# ---------------------------------------------------------------- 校验结果


def reason(code: str, level: str = "reject", **extra: Any) -> dict[str, Any]:
    return {"code": code, "level": level, **{k: v for k, v in extra.items() if v is not None}}


def _status(reasons: list[dict[str, Any]]) -> str:
    if any(r["level"] == "reject" for r in reasons):
        return "reject"
    if any(r["level"] == "warn" for r in reasons):
        return "warn"
    return "pass"


def _ref_ids(refs: Any) -> list[dict[str, Any]]:
    return [r for r in refs if isinstance(r, dict)] if isinstance(refs, list) else []


def check_refs(refs: Any, facts: dict[str, Any]) -> list[dict[str, Any]]:
    """引用必须在事实里：{"id": "n3"}（对象、差异条目、问题……）或 {"line": 12, "of": "d1"}（配置行号）。"""
    out: list[dict[str, Any]] = []
    if refs is None:
        return out
    if not isinstance(refs, list):
        return [reason("bad_refs")]
    objs = facts.get("objects") or {}
    lines = facts.get("lines") or {}
    for r in refs[:200]:
        if not isinstance(r, dict):
            out.append(reason("bad_refs"))
            continue
        if "line" in r:
            of = str(r.get("of") or (next(iter(lines)) if len(lines) == 1 else ""))
            n = r.get("line")
            top = lines.get(of)
            if not isinstance(n, int) or isinstance(n, bool) or top is None or not 1 <= n <= int(top):
                out.append(reason("line_not_found", ref=f"{of}:{n}"))
        else:
            rid = str(r.get("id") or "")
            if rid not in objs:
                out.append(reason("ref_not_found", ref=rid))
    return out


def validate(skill_id: str, draft: dict[str, Any], facts: dict[str, Any], env: Env) -> dict[str, Any]:
    """一条建议的代码校验：通用检查 + 该类别的校验器。返回 {status, reasons, display?}。"""
    spec = spec_of(skill_id)
    cat = draft.get("category")
    reasons: list[dict[str, Any]] = []
    if cat not in CATEGORIES or cat not in spec.categories:
        return {"status": "reject", "reasons": [reason("bad_category", ref=str(cat))]}
    if not isinstance(draft.get("content"), dict):
        return {"status": "reject", "reasons": [reason("bad_content")]}
    if len(json.dumps(draft["content"], ensure_ascii=False, default=str)) > MAX_JSON:
        return {"status": "reject", "reasons": [reason("too_large")]}
    if not str(draft.get("title") or "").strip():
        reasons.append(reason("no_title", "warn"))
    else:  # 标题里也不能出现图中没有的对象（数字不查）
        reasons += [r for r in check_text(str(draft["title"]), facts) if r["level"] == "reject"]
    reasons += check_refs(draft.get("refs"), facts)
    extra: dict[str, Any] = {}
    env2 = dataclasses.replace(env, out=extra)
    try:
        reasons += CATEGORIES[cat].check(draft, facts, env2)
        if spec.check is not None:
            reasons += spec.check(draft, facts, env2)
    except SuggestError as e:
        reasons.append(reason(e.key.rsplit(".", 1)[-1]))
    seen: set[tuple[Any, ...]] = set()
    uniq = []
    for r in reasons:  # 同一原因（例如引用与目标指向同一个不存在的编号）只列一次
        key = (r["code"], r.get("ref"), r.get("line"), r.get("detail"))
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    out: dict[str, Any] = {"status": _status(uniq), "reasons": uniq}
    if str(draft.get("title") or "").strip():
        out["title_display"] = render_title(str(draft["title"]), facts)
    for k in ("display", "segments", "result"):
        if extra.get(k):
            out[k] = extra[k]
    return out


def _out(env: Env) -> dict[str, Any]:
    return env.out


# ---------------------------------------------------------------- 类别：refs_exist


def _check_refs_only(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    return [] if _ref_ids(d.get("refs")) else [reason("no_refs")]


def _adopt_record(env: Env, row: AISuggestion, facts: dict[str, Any]) -> dict[str, Any]:
    return {"action": "record"}


def _revert_record(env: Env, row: AISuggestion) -> dict[str, Any]:
    return {"action": "record"}


register_category("refs_exist", Validator(_check_refs_only, _adopt_record, _revert_record))


# ---------------------------------------------------------------- 类别：text_only

_MENTION = re.compile(r"\[\[([A-Za-z][A-Za-z0-9_.:-]{0,40})\]\]")
_PLACE = re.compile(r"<<([A-Za-z0-9_.:\-]{1,80})>>")
_IFNAME = re.compile(r"\b[A-Za-z][A-Za-z-]{1,30}\d+(?:/\d+)+(?:[.:]\d+)?\b")
_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?\b")
_HOST = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+\b")
_NUM = re.compile(r"(?<![\w.:/-])\d+(?:\.\d+)?(?![\w.:/-])")


def _names(facts: dict[str, Any]) -> set[str]:
    out = {str(n).lower() for n in facts.get("names") or []}
    for o in (facts.get("objects") or {}).values():
        if o.get("label") is not None:
            out.add(str(o["label"]).lower())
    return out


def _fmt_num(v: Any) -> str:
    return str(v)


def render_text(text: str, facts: dict[str, Any]) -> str:
    """[[编号]] 换成对象名，<<键>> 换成代码给出的数字（界面显示用；编号与键不存在时原样保留）。"""
    objs, nums = facts.get("objects") or {}, facts.get("numbers") or {}
    t = _MENTION.sub(lambda m: str(objs[m.group(1)]["label"]) if m.group(1) in objs else m.group(0), text)
    return _PLACE.sub(lambda m: _fmt_num(nums[m.group(1)]) if m.group(1) in nums else m.group(0), t)


_TOKEN = re.compile(r"\[\[([A-Za-z][A-Za-z0-9_.:-]{0,40})\]\]|<<([A-Za-z0-9_.:\-]{1,80})>>")


def text_segments(text: str, facts: dict[str, Any]) -> list[dict[str, Any]]:
    """正文切成片段给界面：t=text 是 AI 写的文字（紫色虚线），t=ref 是代码填入的对象名（可跳转），t=num 是代码填入的数字
    （ref / num 用实线显示）。编号或键不存在时 found 为 false（界面打删除线）。"""
    objs, nums = facts.get("objects") or {}, facts.get("numbers") or {}
    out: list[dict[str, Any]] = []
    pos = 0
    for m in _TOKEN.finditer(text):
        if m.start() > pos:
            out.append({"t": "text", "v": text[pos : m.start()]})
        if m.group(1) is not None:
            o = objs.get(m.group(1))
            out.append(
                {"t": "ref", "id": m.group(1), "v": str(o["label"]) if o else m.group(1), "found": o is not None}
            )
        else:
            k = m.group(2)
            out.append({"t": "num", "key": k, "v": _fmt_num(nums[k]) if k in nums else k, "found": k in nums})
        pos = m.end()
    if pos < len(text):
        out.append({"t": "text", "v": text[pos:]})
    return out


_BARE_ID = re.compile(r"\b([a-z]\d{1,4})\b")


def render_title(title: str, facts: dict[str, Any]) -> str:
    """标题里的 [[编号]] 与直接写出的编号（d1、n3）换成对象名（界面显示用）。"""
    objs = facts.get("objects") or {}
    t = render_text(title, facts)
    return _BARE_ID.sub(lambda m: str(objs[m.group(1)]["label"]) if m.group(1) in objs else m.group(0), t)


def check_text(text: str, facts: dict[str, Any]) -> list[dict[str, Any]]:
    """文字里提到的对象与数字是否与事实一致（text_only 与其他类别的说明文字共用）。"""
    out: list[dict[str, Any]] = []
    objs, nums = facts.get("objects") or {}, facts.get("numbers") or {}
    for m in _MENTION.finditer(text):
        if m.group(1) not in objs:
            out.append(reason("ref_not_found", ref=m.group(1)))
    for m in _PLACE.finditer(text):
        if m.group(1) not in nums:
            out.append(reason("fact_not_found", ref=m.group(1)))
    rest = _PLACE.sub(" ", _MENTION.sub(" ", text))
    names = _names(facts)
    seen: set[str] = set()
    spans: list[tuple[int, int]] = []
    for rx, code in ((_IFNAME, "unknown_object"), (_IPV4, "unknown_object"), (_HOST, "unknown_object")):
        for m in rx.finditer(rest):
            tok = m.group(0)
            if any(a <= m.start() < b for a, b in spans):
                continue
            spans.append((m.start(), m.end()))
            if rx is _HOST and (not any(ch.isdigit() for ch in tok) or len(tok) < 6):
                continue  # 只把带数字的“主机名样”词当成对象（BGP、IS-IS 之类的术语不算）
            low = tok.lower()
            bare = low.split("/")[0] if rx is _IPV4 else low
            if low in names or bare in names or low in seen:
                continue
            seen.add(low)
            out.append(reason(code, ref=tok))
    allowed = {_fmt_num(v) for v in nums.values() if isinstance(v, int | float) and not isinstance(v, bool)}
    for m in _NUM.finditer(rest):
        if any(a <= m.start() < b for a, b in spans):
            continue
        tok = m.group(0)
        if tok not in allowed and tok not in seen:
            seen.add(tok)
            out.append(reason("number_unverified", "warn", ref=tok))
    return out


def _check_text_only(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    text = d["content"].get("text")
    if not isinstance(text, str) or not text.strip():
        return [reason("no_text")]
    if len(text) > MAX_TEXT:
        return [reason("too_large")]
    _out(env)["display"] = render_text(text, facts)
    _out(env)["segments"] = text_segments(text, facts)
    return check_text(text, facts)


register_category("text_only", Validator(_check_text_only, _adopt_record, _revert_record))


# ---------------------------------------------------------------- 类别：view_hint


def _hint_value(key: str, value: Any) -> Any:
    """取值的规范化；不合格返回 None。"""
    if key == "role":
        v = str(value or "").strip().lower()
        return v if v in ROLES else None
    if key in ("group", "label"):
        v = str(value or "").strip()
        return v if 0 < len(v) <= (60 if key == "group" else 120) else None
    if key == "layer":
        return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 9 else None
    return None


def _hint_target(c: dict[str, Any], facts: dict[str, Any]) -> tuple[str, str] | None:
    o = (facts.get("objects") or {}).get(str(c.get("target") or ""))
    if not o or o.get("type") != "device" or o.get("device_id") is None:
        return None
    return "device", str(o["device_id"])


def scope_conds(env: Env, model: Any) -> list[Any]:
    """按当前项目与网络过滤建议、批次（M9：有网络时按网络）。"""
    if env.network_id is not None:
        return [model.network_id == env.network_id]
    if env.project_id is not None:
        return [model.project_id == env.project_id]
    return []


def _owned(env: Env, row: Any) -> bool:
    if env.network_id is not None:
        return bool(row.network_id == env.network_id)
    return env.project_id is None or row.project_id == env.project_id


def _annotation(
    s: Any, project_id: int, ttype: str, target: str, key: str, network_id: int | None = None
) -> ViewAnnotation | None:
    net = [ViewAnnotation.network_id == network_id] if network_id is not None else []
    return s.scalar(
        select(ViewAnnotation).where(
            *net,
            ViewAnnotation.project_id == project_id,
            ViewAnnotation.target_type == ttype,
            ViewAnnotation.target == target,
            ViewAnnotation.key == key,
        )
    )


def _check_view_hint(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    c = d["content"]
    key = str(c.get("key") or "")
    if key not in HINT_KEYS:
        return [reason("bad_hint_key", ref=key)]
    if c.get("reason"):
        _out(env)["segments"] = text_segments(str(c["reason"]), facts)
        _out(env)["display"] = render_text(str(c["reason"]), facts)
    tgt = _hint_target(c, facts)
    if tgt is None:
        return [reason("ref_not_found", ref=str(c.get("target") or ""))]
    if _hint_value(key, c.get("value")) is None:
        return [reason("bad_hint_value", ref=str(c.get("value")))]
    out: list[dict[str, Any]] = []
    if c.get("reason"):
        out += [r for r in check_text(str(c["reason"]), facts) if r["level"] == "reject"]
    if env.project_id is not None:
        with store.session(env.db) as s:
            cur = _annotation(s, env.project_id, tgt[0], tgt[1], key, env.network_id)
            if cur is not None and cur.source == "user" and cur.value != _hint_value(key, c.get("value")):
                out.append(reason("overrides_manual", "warn", ref=str(cur.value)))
    return out


def _adopt_view_hint(env: Env, row: AISuggestion, facts: dict[str, Any]) -> dict[str, Any]:
    if env.project_id is None:
        raise SuggestError("ai_suggest.need_project", "state")
    c = row.content or {}
    tgt = _hint_target(c, facts)
    if tgt is None:
        raise SuggestError("ai_suggest.check_failed", "state")
    key, value = str(c["key"]), _hint_value(str(c["key"]), c.get("value"))
    with store.session(env.db) as s:
        cur = _annotation(s, env.project_id, tgt[0], tgt[1], key, env.network_id)
        prior = None
        if cur is None:
            cur = ViewAnnotation(
                project_id=env.project_id, network_id=env.network_id, target_type=tgt[0], target=tgt[1], key=key
            )
            s.add(cur)
        else:
            prior = {"value": cur.value, "source": cur.source, "suggestion_id": cur.suggestion_id}
        cur.value, cur.source, cur.suggestion_id = value, "ai", row.id
        cur.updated_by, cur.updated_at = env.actor, datetime.now(UTC)
        s.flush()
        return {
            "action": "annotate",
            "annotation_id": cur.id,
            "target_type": tgt[0],
            "target": tgt[1],
            "key": key,
            "value": value,
            "prior": prior,
        }


def _revert_view_hint(env: Env, row: AISuggestion) -> dict[str, Any]:
    info = row.adopt_info or {}
    with store.session(env.db) as s:
        cur = _annotation(s, int(row.project_id or 0), info["target_type"], info["target"], info["key"], row.network_id)
        if cur is None or cur.suggestion_id != row.id:
            raise SuggestError("ai_suggest.superseded", "state", id=row.id)
        prior = info.get("prior")
        if prior:
            cur.value, cur.source, cur.suggestion_id = prior["value"], prior["source"], prior.get("suggestion_id")
            cur.updated_by, cur.updated_at = env.actor, datetime.now(UTC)
            return {"action": "restore", "value": prior["value"]}
        s.delete(cur)
        return {"action": "remove"}


register_category("view_hint", Validator(_check_view_hint, _adopt_view_hint, _revert_view_hint))


def list_annotations(
    db_url: str, project_id: int, target_type: str | None = None, network_id: int | None = None
) -> list[dict[str, Any]]:
    """视图标注（拓扑角色、分组、标签……）；network_id 给出时只看这个网络的（M9 起按网络）。"""
    with store.session(db_url) as s:
        q = select(ViewAnnotation).where(ViewAnnotation.project_id == project_id)
        if network_id is not None:
            q = q.where(ViewAnnotation.network_id == network_id)
        if target_type:
            q = q.where(ViewAnnotation.target_type == target_type)
        return [
            {
                "id": a.id,
                "target_type": a.target_type,
                "target": a.target,
                "key": a.key,
                "value": a.value,
                "source": a.source,
                "suggestion_id": a.suggestion_id,
                "updated_by": a.updated_by,
                "updated_at": iso(a.updated_at),
            }
            for a in s.scalars(q.order_by(ViewAnnotation.target_type, ViewAnnotation.target, ViewAnnotation.key))
        ]


# ---------------------------------------------------------------- 类别：kb_review


def _review_kinds() -> set[str]:
    from lmesh.core import review

    review._load_actions()
    return set(review.KINDS) | set(review._ACTIONS)


def _check_kb_review(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    c = d["content"]
    kind = str(c.get("review_kind") or "suggestion")
    if kind not in _review_kinds():
        return [reason("bad_review_kind", ref=kind)]
    if not isinstance(c.get("payload"), dict):
        return [reason("bad_content")]
    if len(str(c.get("target") or "")) > 400:
        return [reason("too_large")]
    extra = KB_CHECKS.get(kind)
    return extra(c, env) if extra else []


def _adopt_kb_review(env: Env, row: AISuggestion, facts: dict[str, Any]) -> dict[str, Any]:
    from lmesh.core import review

    c = row.content or {}
    kind = str(c.get("review_kind") or "suggestion")
    rid = review.add(
        env.db,
        kind,
        (row.title or f"AI #{row.id}")[:400],
        str(c.get("target") or ""),
        {**dict(c.get("payload") or {}), "ai_suggestion": row.id},
        {"method": "ai", "skill": row.skill, "suggestion_id": row.id, "user": env.actor, "project": row.project_id},
    )
    return {"action": "review", "review_item_id": rid, "review_kind": kind}


def _revert_kb_review(env: Env, row: AISuggestion) -> dict[str, Any]:
    rid = (row.adopt_info or {}).get("review_item_id")
    with store.session(env.db) as s:
        item = s.get(ReviewItem, rid) if rid else None
        if item is None:
            return {"action": "none"}
        if item.status != "pending":
            raise SuggestError("ai_suggest.review_decided", "state", id=rid)
        item.status, item.note, item.decided_at = "rejected", f"AI #{row.id} reverted", datetime.now(UTC)
    return {"action": "review_withdrawn", "review_item_id": rid}


register_category("kb_review", Validator(_check_kb_review, _adopt_kb_review, _revert_kb_review, kb=True))


# ---------------------------------------------------------------- 类别：script_valid


def _script_device(c: dict[str, Any], facts: dict[str, Any]) -> int | None:
    o = (facts.get("objects") or {}).get(str(c.get("device") or ""))
    return int(o["device_id"]) if o and o.get("type") == "device" and o.get("device_id") is not None else None


def _check_script(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    from lmesh.core import script_check

    c = d["content"]
    text = c.get("script")
    if not isinstance(text, str) or not text.strip():
        return [reason("no_script")]
    if len(text) > MAX_SCRIPT:
        return [reason("too_large")]
    dev = _script_device(c, facts)
    if dev is None:
        return [reason("ref_not_found", ref=str(c.get("device") or ""))]
    try:
        base = script_check.baseline_from_db(env.db, env.kb, dev)
        res = script_check.check_text(text, env.kb, base, "change", True, lang=env.lang, with_reorder=False)
    except script_check.ScriptCheckError as e:
        return [reason("script_invalid", detail=i18n.t(e.key, env.lang, **e.fmt))]
    out: list[dict[str, Any]] = []
    issues = res.get("issues") or []
    for i in issues[:20]:
        if i.get("severity") == "error":
            out.append(reason("script_error", line=i.get("line"), detail=i.get("text") or i.get("code")))
    if not out and any(i.get("severity") == "warning" for i in issues):
        out.append(reason("script_warning", "warn", detail=str(res["summary"].get("by_severity"))))
    unver = [i.get("line") for i in issues if i.get("category") == "parse" and i.get("severity") != "error"]
    if unver:  # 功能域外 / 无法识别但不算错误的行：代码无法确认
        out.append(reason("script_unverifiable", "warn", detail=", ".join(f"L{n}" for n in unver[:10])))
    fixed = {(f.get("rule"), f.get("node")) for f in (res.get("result") or {}).get("findings_fixed") or []}
    for fx in c.get("fixes") or []:
        if isinstance(fx, dict) and fx.get("rule") and (fx.get("rule"), fx.get("node")) not in fixed:
            out.append(reason("problem_not_fixed", ref=f"{fx.get('rule')}@{fx.get('node')}"))
    _out(env)["result"] = {
        "summary": res.get("summary"),
        "result": {
            k: v
            for k, v in res["result"].items()
            if k in ("lines_added", "lines_removed", "lines_overridden", "side_effect_removed", "unknown")
        },
    }
    if c.get("explain"):
        out += [r for r in check_text(str(c["explain"]), facts) if r["level"] == "reject"]
    return out


def _adopt_script(env: Env, row: AISuggestion, facts: dict[str, Any]) -> dict[str, Any]:
    from lmesh.core import checkproj

    c = row.content or {}
    dev = _script_device(c, facts)
    actor = checkproj.Actor(env.user_id, env.admin, env.actor)
    r = checkproj.create_project_script(
        env.db,
        actor,
        {"name": f"AI · {row.title or row.id}"[:200], "kind": "change", "device_id": dev, "content": c["script"]},
    )
    return {"action": "script", "group_id": r["group"]["id"], "script_id": r["script"]["id"], "device_id": dev}


def _revert_script(env: Env, row: AISuggestion) -> dict[str, Any]:
    from lmesh.core import checkproj

    info = row.adopt_info or {}
    actor = checkproj.Actor(env.user_id, env.admin, env.actor)
    try:
        revs = checkproj.revisions(env.db, actor, info["group_id"], info["script_id"])
    except checkproj.ProjectError:
        return {"action": "none"}
    if len(revs) > 1:
        raise SuggestError("ai_suggest.script_modified", "state", id=info["script_id"])
    checkproj.delete_project(env.db, actor, info["group_id"])
    return {"action": "script_deleted", "script_id": info["script_id"]}


register_category("script_valid", Validator(_check_script, _adopt_script, _revert_script))


# ---------------------------------------------------------------- 解析回复


def _json_of(text: str) -> dict[str, Any]:
    from lmesh.core import ask

    return ask._json_reply(text)


def parse_reply(text: str, spec: SkillSpec) -> list[dict[str, Any]]:
    """回复 → 建议草稿列表。不合格抛出 ValueError（说明写进重试提示）。"""
    try:
        data = _json_of(text)
    except (ValueError, json.JSONDecodeError) as e:
        raise ValueError("the reply is not a JSON object") from e
    items = data.get("suggestions")
    if not isinstance(items, list):
        raise ValueError('missing the "suggestions" list')
    out: list[dict[str, Any]] = []
    for raw in items[:MAX_SUGGESTIONS]:
        if not isinstance(raw, dict):
            out.append({"category": None, "kind": "", "title": "", "content": None, "refs": []})
            continue
        out.append(
            {
                "category": str(raw.get("category") or spec.default_category),
                "kind": str(raw.get("kind") or "")[:40],
                "title": str(raw.get("title") or "")[:MAX_TITLE],
                "content": raw.get("content"),
                "refs": raw.get("refs") if isinstance(raw.get("refs"), list) else [],
            }
        )
    return out


# ---------------------------------------------------------------- 运行


def _now() -> datetime:
    return datetime.now(UTC)


def skill_list(settings: config.Settings) -> dict[str, Any]:
    """可以用来生成建议的 skill：名称、分组、类别、是否启用，以及 AI 是否可用（不可用时给出原因）。"""
    _load_skills()
    res = ai.resolve(settings)
    out = []
    for sid, spec in SKILLS.items():
        try:
            s = skills.current(sid)
        except skills.SkillError:
            continue
        out.append(
            {
                "id": sid,
                "title": s.title,
                "description": s.description,
                "group": skills.group_of(s),
                "enabled": s.enabled,
                "scope": spec.scope,
                "categories": list(spec.categories),
            }
        )
    from lmesh.core import ai_connections

    limit = ai_connections.token_warn_limit(settings, settings.actor)
    return {"ai": {"configured": res.configured, "reason": res.reason, "warn_tokens": limit}, "skills": out}


TOKEN_WARN = 50_000  # ai.warn_tokens 的默认值：预计输入超过这个量时界面提示条变黄


def estimate_tokens(text: str) -> int:
    """粗略估计 token 数：ASCII 约 4 个字符一个 token，其他字符（中文等）约 1 个一个。"""
    ascii_n = sum(1 for ch in text if ord(ch) < 128)
    return ascii_n // 4 + (len(text) - ascii_n)


def estimate(env: Env, skill_id: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """运行前估计发给 AI 的量（按当前上下文渲染提示词，不调用 AI）：tokens、是否超过提醒线。"""
    spec = spec_of(skill_id)
    params = dict(params or {})
    if spec.scope == "device" and params.get("device_id") is None:
        raise SuggestError("ai_suggest.need_device", "param")
    if spec.prepare:
        spec.prepare(env, params)
    sk = skills.current(skill_id)
    ctx = spec.build(env, params)
    n = estimate_tokens(sk.system_text(**ctx.vars) + sk.prompt_text(**ctx.vars))
    limit = warn_limit(env)
    return {"skill": skill_id, "tokens": n, "warn": bool(limit) and n > limit, "threshold": limit}


def warn_limit(env: Env) -> int:
    """大请求提示线：全局 ai.warn_tokens（0 = 不提示），本人在“我的 AI”里关闭提示时为 0。"""
    from lmesh.core import ai_connections

    actor = env.settings.actor
    if actor is None and env.user_id is not None:
        actor = type("A", (), {"user_id": env.user_id})()
    return ai_connections.token_warn_limit(env.settings, actor)


def start(env: Env, skill_id: str, params: dict[str, Any] | None = None, replay: bool = False) -> int:
    """提交前的检查（skill 存在且启用、AI 可用、参数）并建一条批次记录，返回批次编号；随后调用 execute。
    replay=True：用给出的回复代替真实 AI（命令行 --replay、测试；同样经过代码校验，批次标明 replay）。"""
    spec = spec_of(skill_id)
    try:
        sk = skills.require_enabled(skill_id)
    except skills.SkillError as e:
        raise SuggestError(e.key, e.kind if e.kind in ("state", "not_found") else "param", e.data, **e.fmt) from e
    if not replay and not ai.is_configured(env.settings):
        raise SuggestError("ai.not_configured", "state", data=ai.not_configured_data(env.settings))
    params = dict(params or {})
    if spec.scope == "device" and params.get("device_id") is None:
        raise SuggestError("ai_suggest.need_device", "param")
    if spec.prepare:
        spec.prepare(env, params)
    with store.session(env.db) as s:
        b = AISuggestionBatch(
            project_id=env.project_id,
            network_id=env.network_id,
            device_id=params.get("device_id"),
            skill=skill_id,
            skill_version=sk.active,
            mode="replay" if replay else "ai",
            status="queued",
            user_id=env.user_id,
            created_by=env.actor[:200],
            params=params,
        )
        s.add(b)
        s.flush()
        return int(b.id)


def set_task(db_url: str, batch_id: int, task_id: str) -> None:
    with store.session(db_url) as s:
        b = s.get(AISuggestionBatch, batch_id)
        if b is not None:
            b.task_id = task_id


def _cancelled(db_url: str, batch_id: int) -> bool:
    with store.session(db_url) as s:
        b = s.get(AISuggestionBatch, batch_id)
        return b is None or b.status == "cancelled"


def cancel(env: Env, batch_id: int) -> dict[str, Any]:
    """取消一次运行：还没入库时，AI 的回复到达后丢弃（已发出的 AI 调用无法中途停止，照常计入用量）。"""
    with store.session(env.db) as s:
        b = _batch(s, env, batch_id)
        if b.status not in ("queued", "running"):
            raise SuggestError("ai_suggest.not_running", "state", id=batch_id)
        b.status, b.finished_at = "cancelled", _now()
        return batch_dict(b)


def _update_batch(db_url: str, batch_id: int, force: bool = False, **fields: Any) -> None:
    """更新批次；已取消的批次只在 force 时更新（记下已经发生的 AI 调用与用量）。"""
    with store.session(db_url) as s:
        b = s.get(AISuggestionBatch, batch_id)
        if b is not None and (force or b.status != "cancelled"):
            for k, v in fields.items():
                setattr(b, k, v)


def _skill_status(counts: dict[str, int], parsed: bool) -> str:
    if not parsed or counts.get("reject"):
        return "rejected"
    if counts.get("warn") and not counts.get("pass"):
        return "unverifiable"
    return "passed"


def execute(
    env: Env,
    batch_id: int,
    progress: Callable[[int, str], None] | None = None,
    reply: str | None = None,
) -> dict[str, Any]:
    """运行一次：上下文 → 调用 skill（或回放给出的回复）→ 解析（失败重试一次）→ 逐条校验 → 入库。
    返回批次（含计数）；AI 调用失败或回复无法解析时批次记为 failed（error 给出原因）而不是抛出。"""
    from lmesh.core import ask

    tick = progress or (lambda p, m: None)
    with store.session(env.db) as s:
        b = s.get(AISuggestionBatch, batch_id)
        if b is None:
            raise SuggestError("ai_suggest.batch_not_found", "not_found", id=batch_id)
        skill_id, params, mode = b.skill, dict(b.params or {}), b.mode
    spec = spec_of(skill_id)
    sk = skills.current(skill_id)
    _update_batch(env.db, batch_id, status="running")
    tick(5, "sanitize")  # 界面的四步进度：本地脱敏 → 发送 → 生成 → 代码校验
    try:
        ctx = spec.build(env, params)
    except SuggestError as e:
        _update_batch(env.db, batch_id, status="failed", finished_at=_now(), error={"key": e.key, **e.fmt})
        raise
    _update_batch(env.db, batch_id, scope_key=ctx.scope_key, device_id=ctx.device_id, context=ctx.facts)
    system, prompt = sk.system_text(**ctx.vars), sk.prompt_text(**ctx.vars)
    sess = ask._Session(env.settings, sk.task)
    actor = skills.Actor(env.user_id, env.actor)
    log_input = {"vars": ctx.vars, "facts": ctx.facts}
    replies: list[str] = []
    drafts: list[dict[str, Any]] | None = None
    error: dict[str, Any] | None = None
    res0 = ai.resolve(env.settings) if mode == "ai" else None
    conn0 = res0.conn if res0 else None
    _update_batch(  # 运行中就让界面显示接口、模型与预计的输入量
        env.db,
        batch_id,
        connection_name=conn0.name if conn0 else "",
        ai_source=(res0.source or "") if res0 else "",
        model=conn0.model_for(sk.task) if conn0 else "",
        params={**params, "estimate": estimate_tokens(system + prompt)},
    )
    tick(15, "send")
    with ai.collect_call_ids() as call_ids:
        for attempt in range(2):
            try:
                if mode == "replay":
                    text = reply or ""
                    sess.sent.append({"step": "replay", "system": system, "prompt": prompt, "reply": text})
                else:
                    p2 = prompt
                    if attempt:
                        tpl = sk.templates.get("retry") or DEFAULT_RETRY
                        p2 = prompt + "\n\n" + skills.render(tpl, {"error": str(error and error.get("detail") or "")})
                    tick(25 if not attempt else 45, "generate")
                    text = sess.call("suggest" if not attempt else "retry", system, p2, sk.id)
            except ask.AskError as e:
                error = {"key": e.key, "status": "ai_error"}
                break
            replies.append(text)
            try:
                drafts = parse_reply(text, spec)
                error = None
                break
            except ValueError as e:
                error = {"key": "ai_suggest.bad_reply", "detail": str(e)}
                if mode == "replay":
                    break
            tick(40, "send")
    info = sess.info()
    res = ai.resolve(env.settings) if mode == "ai" else None
    conn = res.conn if res else None
    batch_fields: dict[str, Any] = {
        "ai_call_ids": list(call_ids),
        "connection_name": conn.name if conn else "",
        "ai_source": (res.source or "") if res else "",
        "model": info.get("model") or "",
        "tokens_in": int(info.get("tokens_in") or 0),
        "tokens_out": int(info.get("tokens_out") or 0),
    }
    if _cancelled(env.db, batch_id):
        _update_batch(env.db, batch_id, force=True, **batch_fields)
        return get_batch(env, batch_id)
    if drafts is None:
        err = error or {"key": "ai_suggest.bad_reply"}
        run_id = None
        if mode == "ai" and replies:
            fail = {"summary": {"status": "rejected", "error": err}}
            run_id = skills.log_run(env.settings, sk, SOURCE, "rejected", log_input, replies[-1], fail, info, actor)
        elif mode == "ai":
            skills.log_run(env.settings, sk, SOURCE, "error", log_input, "", {"error": err}, info, actor)
        _update_batch(
            env.db, batch_id, status="failed", finished_at=_now(), error=err, skill_run_id=run_id, **batch_fields
        )
        return get_batch(env, batch_id)
    tick(60, "check")
    checked = [(d, validate(skill_id, d, ctx.facts, env)) for d in drafts]
    counts = {k: sum(1 for _, c in checked if c["status"] == k) for k in CHECKS}
    counts["total"] = len(checked)
    run_id = None
    if mode == "ai":
        det: dict[str, Any] = {
            "summary": {"status": _skill_status(counts, True), **counts},
            "items": [{"ok": c["status"] != "reject", "reason": c["status"], "text": d["title"]} for d, c in checked][
                :50
            ],
        }
        run_id = skills.log_run(
            env.settings, sk, SOURCE, _skill_status(counts, True), log_input, replies[-1], det, info, actor
        )
    if _cancelled(env.db, batch_id):
        return get_batch(env, batch_id)
    tick(85, "check")
    first_call = call_ids[-1] if call_ids else None
    with store.session(env.db) as s:
        for d, c in checked:
            s.add(
                AISuggestion(
                    batch_id=batch_id,
                    project_id=env.project_id,
                    network_id=env.network_id,
                    device_id=ctx.device_id,
                    scope_key=ctx.scope_key,
                    skill=skill_id,
                    category=str(d.get("category") or "")[:30],
                    kind=d["kind"],
                    title=d["title"],
                    content=d.get("content") if isinstance(d.get("content"), dict) else None,
                    refs=_ref_ids(d.get("refs")),
                    check=c,
                    check_status=c["status"],
                    ai_call_id=first_call,
                    connection_name=batch_fields["connection_name"],
                    user_id=env.user_id,
                    created_by=env.actor[:200],
                )
            )
        b = s.get(AISuggestionBatch, batch_id)
        if b is not None and b.status != "cancelled":
            b.status, b.finished_at, b.counts, b.skill_run_id = "done", _now(), counts, run_id
            for k, v in batch_fields.items():
                setattr(b, k, v)
    return get_batch(env, batch_id)


def run(
    env: Env,
    skill_id: str,
    params: dict[str, Any] | None = None,
    reply: str | None = None,
    background: bool = False,
) -> dict[str, Any]:
    """提交并运行。background=True 时放进后台任务（返回 task_id 与 batch_id，GET /tasks/{id} 看进度）；
    否则同步运行并返回批次。reply 不为 None 时回放（不调用 AI）。"""
    from lmesh.core import tasks

    bid = start(env, skill_id, params, replay=reply is not None)
    if not background:
        return execute(env, bid, None, reply)
    ctx = contextvars.copy_context()  # 后台线程里保持当前项目与调用者（设备可见性按项目）

    def job(progress: Callable[[int, str], None]) -> dict[str, Any]:
        return ctx.run(execute, env, bid, progress, reply)

    tid = tasks.submit(env.db, "ai_suggest", job, created_by=env.actor)
    set_task(env.db, bid, tid)
    return {"task_id": tid, "batch_id": bid}


# ---------------------------------------------------------------- 查询


def _batch(s: Any, env: Env, batch_id: int) -> AISuggestionBatch:
    b = s.get(AISuggestionBatch, batch_id)
    if b is None or not _owned(env, b):
        raise SuggestError("ai_suggest.batch_not_found", "not_found", id=batch_id)
    return b


def batch_dict(b: AISuggestionBatch) -> dict[str, Any]:
    return {
        "id": b.id,
        "project_id": b.project_id,
        "network_id": b.network_id,
        "device_id": b.device_id,
        "scope_key": b.scope_key,
        "skill": b.skill,
        "skill_version": b.skill_version,
        "mode": b.mode,
        "status": b.status,
        "task_id": b.task_id,
        "skill_run_id": b.skill_run_id,
        "ai_call_ids": b.ai_call_ids or [],
        "connection": b.connection_name,
        "ai_source": b.ai_source,
        "model": b.model,
        "tokens_in": b.tokens_in,
        "tokens_out": b.tokens_out,
        "created_by": b.created_by,
        "params": b.params or {},
        "counts": b.counts or {"total": 0, "pass": 0, "warn": 0, "reject": 0},
        "error": b.error,
        "created_at": iso(b.created_at),
        "finished_at": iso(b.finished_at),
    }


def get_batch(env: Env, batch_id: int) -> dict[str, Any]:
    with store.session(env.db) as s:
        return batch_dict(_batch(s, env, batch_id))


def _resolve_refs(refs: list[dict[str, Any]], facts: dict[str, Any]) -> list[dict[str, Any]]:
    """引用 → 界面跳转需要的信息（对象名、类型、设备编号、图节点、行号）。"""
    objs = facts.get("objects") or {}
    out = []
    for r in refs:
        if "line" in r:
            of = str(r.get("of") or "")
            dev: dict[str, Any] = objs.get(of) or next((o for o in objs.values() if o.get("type") == "device"), {})
            out.append({"line": r.get("line"), "of": of, "device_id": dev.get("device_id"), "found": True})
            continue
        rid = str(r.get("id") or "")
        o = objs.get(rid)
        if o is None:
            out.append({"id": rid, "found": False})
            continue
        dev = objs.get(str(o.get("device") or "")) or (o if o.get("type") == "device" else {})
        out.append(
            {
                "id": rid,
                "found": True,
                "type": o.get("type"),
                "label": o.get("label"),
                "node": o.get("node"),
                "line": o.get("line"),
                "device_id": dev.get("device_id"),
                "device": dev.get("label"),
            }
        )
    return out


def suggestion_dict(r: AISuggestion, facts: dict[str, Any] | None = None) -> dict[str, Any]:
    v = CATEGORIES.get(r.category)
    return {
        "id": r.id,
        "batch_id": r.batch_id,
        "project_id": r.project_id,
        "network_id": r.network_id,
        "device_id": r.device_id,
        "scope_key": r.scope_key,
        "skill": r.skill,
        "category": r.category,
        "kind": r.kind,
        "title": r.title,
        "content": r.content,
        "original": r.original,
        "edited": r.original is not None,
        "refs": _resolve_refs(r.refs or [], facts or {}),
        "check": r.check or {},
        "check_status": r.check_status,
        "status": r.status,
        "kb": bool(v and v.kb),
        "ai_call_id": r.ai_call_id,
        "connection": r.connection_name,
        "created_by": r.created_by,
        "created_at": iso(r.created_at),
        "decided_by": r.decided_by,
        "decided_at": iso(r.decided_at),
        "adopt_info": r.adopt_info,
        "note": r.note,
        "reverted_by": r.reverted_by,
        "reverted_at": iso(r.reverted_at),
        "revert_info": r.revert_info,
    }


def _facts_of(s: Any, batch_ids: set[int]) -> dict[int, dict[str, Any]]:
    if not batch_ids:
        return {}
    rows = s.execute(select(AISuggestionBatch.id, AISuggestionBatch.context).where(AISuggestionBatch.id.in_(batch_ids)))
    return {int(i): (c or {}) for i, c in rows}


def list_suggestions(
    env: Env,
    skill: str | None = None,
    status: str | None = None,
    check: str | None = None,
    category: str | None = None,
    device_id: int | None = None,
    batch_id: int | None = None,
    scope_key: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    conds: list[Any] = []
    conds += scope_conds(env, AISuggestion)
    for col, val in (
        (AISuggestion.skill, skill),
        (AISuggestion.check_status, check),
        (AISuggestion.category, category),
        (AISuggestion.device_id, device_id),
        (AISuggestion.batch_id, batch_id),
        (AISuggestion.scope_key, scope_key),
    ):
        if val is not None and val != "":
            conds.append(col == val)
    base = list(conds)  # counts 按状态分组时不带状态过滤（界面的状态页签）
    if status:
        conds.append(AISuggestion.status == status)
    with store.session(env.db) as s:
        total = s.scalar(select(func.count(AISuggestion.id)).where(*conds)) or 0
        rows = list(
            s.scalars(
                select(AISuggestion)
                .where(*conds)
                .order_by(AISuggestion.id.desc())
                .offset(max(0, offset))
                .limit(max(1, min(limit, 1000)))
            )
        )
        facts = _facts_of(s, {r.batch_id for r in rows})
        by_status = dict(
            s.execute(
                select(AISuggestion.status, func.count(AISuggestion.id)).where(*base).group_by(AISuggestion.status)
            ).all()
        )
        return {
            "total": int(total),
            "counts": {k: int(by_status.get(k, 0)) for k in STATUSES},
            "items": [suggestion_dict(r, facts.get(r.batch_id)) for r in rows],
        }


def _row(s: Any, env: Env, sid: int) -> AISuggestion:
    r = s.get(AISuggestion, sid)
    if r is None or not _owned(env, r):
        raise SuggestError("ai_suggest.not_found", "not_found", id=sid)
    return r


def get(env: Env, sid: int) -> dict[str, Any]:
    with store.session(env.db) as s:
        r = _row(s, env, sid)
        return suggestion_dict(r, _facts_of(s, {r.batch_id}).get(r.batch_id))


def adoptions(env: Env, limit: int = 200) -> list[dict[str, Any]]:
    """采纳记录：已采纳与已撤销的建议（按采纳时间，新的在前）。"""
    conds: list[Any] = [AISuggestion.status.in_(("adopted", "reverted"))]
    conds += scope_conds(env, AISuggestion)
    with store.session(env.db) as s:
        rows = list(s.scalars(select(AISuggestion).where(*conds).order_by(AISuggestion.decided_at.desc()).limit(limit)))
        facts = _facts_of(s, {r.batch_id for r in rows})
        return [suggestion_dict(r, facts.get(r.batch_id)) for r in rows]


# ---------------------------------------------------------------- 采纳、忽略、撤销


def _require_kb(env: Env, cat: str) -> None:
    v = CATEGORIES.get(cat)
    if v is not None and v.kb and not env.kb_editor:
        raise SuggestError("api.error.kb_editor_only", "forbidden")


_DECIDE_LOCK = threading.RLock()  # 采纳与撤销串行：类别动作在自己的会话里写库（SQLite 不能嵌套写事务）


def adopt(
    env: Env,
    sid: int,
    content: dict[str, Any] | None = None,
    title: str | None = None,
    note: str = "",
    refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """采纳一条建议。给出 content / title / refs（编辑后采纳）时先用同一份事实重新校验；被拒绝（reject）的不能采纳
    （409，data.check 给出原因）。warn 的可以逐条采纳（批量采纳只取 pass）。"""
    with _DECIDE_LOCK:
        with store.session(env.db) as s:  # 1. 读取与校验（不写库）
            r = _row(s, env, sid)
            if r.status == "adopted":
                raise SuggestError("ai_suggest.already_adopted", "state", id=sid)
            _require_kb(env, r.category)
            facts = _facts_of(s, {r.batch_id}).get(r.batch_id) or {}
            edited = content is not None or title is not None or refs is not None
            if edited:
                draft = {
                    "category": r.category,
                    "kind": r.kind,
                    "title": title if title is not None else r.title,
                    "content": content if content is not None else r.content,
                    "refs": refs if refs is not None else (r.refs or []),
                }
                chk = validate(r.skill, draft, facts, env)
                if chk["status"] == "reject":
                    raise SuggestError("ai_suggest.check_failed", "state", data={"check": chk}, id=sid)
                original = r.original or {"title": r.title, "content": r.content, "refs": r.refs, "check": r.check}
                r.title, r.content, r.refs = str(draft["title"])[:MAX_TITLE], draft["content"], _ref_ids(draft["refs"])
                r.check, r.check_status = chk, chk["status"]
            elif r.check_status == "reject":
                raise SuggestError("ai_suggest.check_failed", "state", data={"check": r.check}, id=sid)
            s.expunge(r)
        info = CATEGORIES[r.category].adopt(env, r, facts)  # 2. 类别动作（自己的会话）
        with store.session(env.db) as s:  # 3. 记下结论
            row = _row(s, env, sid)
            if edited:
                row.original = original
                row.title, row.content, row.refs, row.check, row.check_status = (
                    r.title,
                    r.content,
                    r.refs,
                    r.check,
                    r.check_status,
                )
            row.status, row.decided_by, row.decided_at, row.adopt_info = "adopted", env.actor[:200], _now(), info
            row.note, row.reverted_by, row.reverted_at, row.revert_info = note, "", None, None
            return suggestion_dict(row, facts)


def dismiss(env: Env, sid: int, note: str = "") -> dict[str, Any]:
    with store.session(env.db) as s:
        r = _row(s, env, sid)
        if r.status != "pending":
            raise SuggestError("ai_suggest.not_pending", "state", id=sid)
        r.status, r.decided_by, r.decided_at, r.note = "dismissed", env.actor[:200], _now(), note
        return suggestion_dict(r, _facts_of(s, {r.batch_id}).get(r.batch_id))


def restore(env: Env, sid: int) -> dict[str, Any]:
    """把忽略的建议恢复为待处理。"""
    with store.session(env.db) as s:
        r = _row(s, env, sid)
        if r.status != "dismissed":
            raise SuggestError("ai_suggest.not_dismissed", "state", id=sid)
        r.status, r.decided_by, r.decided_at = "pending", "", None
        return suggestion_dict(r, _facts_of(s, {r.batch_id}).get(r.batch_id))


def revert(env: Env, sid: int, note: str = "") -> dict[str, Any]:
    """撤销已采纳的建议：按类别恢复原状（视图标注恢复原值、审核项撤回、未改动的脚本删除）。
    采纳之后又被别的操作改动过时不能撤销（409）。"""
    with _DECIDE_LOCK:
        with store.session(env.db) as s:
            r = _row(s, env, sid)
            if r.status != "adopted":
                raise SuggestError("ai_suggest.not_adopted", "state", id=sid)
            _require_kb(env, r.category)
            at = r.decided_at if r.decided_at is None or r.decided_at.tzinfo else r.decided_at.replace(tzinfo=UTC)
            if at is not None and (_now() - at).days >= REVERT_DAYS:
                raise SuggestError("ai_suggest.revert_expired", "state", id=sid, days=REVERT_DAYS)
            s.expunge(r)
        info = CATEGORIES[r.category].revert(env, r)
        with store.session(env.db) as s:
            row = _row(s, env, sid)
            row.status, row.reverted_by, row.reverted_at, row.revert_info = "reverted", env.actor[:200], _now(), info
            if note:
                row.note = note
            return suggestion_dict(row, _facts_of(s, {row.batch_id}).get(row.batch_id))


def adopt_batch(
    env: Env,
    category: str,
    skill: str | None = None,
    batch_id: int | None = None,
    ids: list[int] | None = None,
) -> dict[str, Any]:
    """按类别批量采纳：只采纳校验通过（pass）且待处理的；warn / reject 的跳过（逐条处理）。"""
    v = CATEGORIES.get(category)
    if v is None:
        raise SuggestError("ai_suggest.bad_category", "param", category=category)
    if not v.batch:
        raise SuggestError("ai_suggest.no_batch", "state", category=category)
    _require_kb(env, category)
    conds: list[Any] = [AISuggestion.category == category, AISuggestion.status == "pending"]
    conds += scope_conds(env, AISuggestion)
    if skill:
        conds.append(AISuggestion.skill == skill)
    if batch_id is not None:
        conds.append(AISuggestion.batch_id == batch_id)
    if ids:
        conds.append(AISuggestion.id.in_(ids))
    with store.session(env.db) as s:
        rows = list(
            s.execute(select(AISuggestion.id, AISuggestion.check_status).where(*conds).order_by(AISuggestion.id))
        )
    adopted, skipped, failed = [], [], []
    for rid, chk in rows:
        if chk != "pass":
            skipped.append({"id": rid, "check_status": chk})
            continue
        try:
            adopt(env, int(rid))
            adopted.append(int(rid))
        except SuggestError as e:
            failed.append({"id": rid, "key": e.key})
    return {"adopted": adopted, "skipped": skipped, "failed": failed}


# ---------------------------------------------------------------- 回归与试运行（REQ-033 的 skill 管理页面用）


def replay_check(skill_id: str, reply: str, facts: dict[str, Any], env: Env) -> dict[str, Any]:
    """按记下的事实校验一次回复（试运行、回归运行、进化打分）：返回 skill_runners 的 _result 结构所需的字段。"""
    spec = spec_of(skill_id)
    try:
        drafts = parse_reply(reply, spec)
    except ValueError as e:
        return {"status": "rejected", "items": [{"ok": False, "reason": "bad_reply", "text": str(e)}], "counts": {}}
    checked = [(d, validate(skill_id, d, facts, env)) for d in drafts]
    counts = {k: sum(1 for _, c in checked if c["status"] == k) for k in CHECKS}
    items = []
    for d, c in checked:
        codes = ", ".join(sorted({x["code"] for x in c["reasons"]}))
        items.append(
            {"ok": c["status"] != "reject", "reason": c["status"], "text": d["title"] or codes, "codes": codes}
        )
    return {"status": _skill_status(counts, True) if checked else "unverifiable", "items": items, "counts": counts}


def is_suggest_skill(skill_id: str) -> bool:
    _load_skills()
    return skill_id in SKILLS
