"""规范与合规、知识库构建两组 AI skill（M8-5，REQ-041）；报告摘要在 ai_report_summary.py（由本模块导入注册）。

所有事实由代码给出并编号（s 规范条款、d 设备、r 基线规则、n 对象、u 未识别行组、k 已有命令卡、c 待映射命令卡、f 命令卡字段），
AI 只能引用编号；每个 skill 除类别校验器外还有自己的额外校验（SkillSpec.check，代码实现）：

    rule-draft       kb_review（review_kind rule）：草稿 YAML 能被规则引擎加载（与知识库现有规则一起校验，编号不能重复），
                     在 knowledge/samples 的样本上试跑并列出命中；语法错误直接拒绝，零命中给提醒，全部实例都命中给提醒
    baseline-waiver  text_only：起草基线例外理由（kind reason）与补偿措施（kind compensating）；该设备该规则必须确实不符合
    sanitize-review  sanitize_rule（本模块注册的新类别）：只允许本地模型（当前生效的 AI 接口 provider 不是 local 时拒绝运行）；
                     标出的文字必须原样出现在该行（库里已脱敏的配置），用它补一条脱敏规则重新脱敏后不再出现；
                     采纳 = 写进项目的脱敏补充（项目设置 sanitize_redact），之后导入与发给 AI 的配置都按它替换
    unknown-triage   kb_review（review_kind unknown_card）：归因（缺命令卡 / 版本差异 / 写法变体）并起草命令卡；用草稿重新解析
                     这组未识别行所在的配置，这些行必须真的变成已识别，否则拒绝；改已有卡时样本往返不能变差
    card-review      text_only / refs_exist：对照文档原文（维护员粘贴或上传）标注参数类型、默认值、取消写法可疑的地方，只标注不改卡；
                     引用的字段与文档行号必须存在，给出的原文摘录必须真的在所引的行里
    mapping-suggest  kb_review（review_kind card_maps）：为命令卡建议映射到哪个 Schema 节点；目标节点存在、表达式里的参数都在
                     卡的语法里，换上映射后知识库校验不新增错误、该平台族样本往返不变差、翻译回归（该平台族的用例）不变差

审核队列新增的动作（review.register_action）：rule（规则写进 rules/standards.yaml）、unknown_card（新增或修改命令卡）、
card_maps（写命令卡的 maps 并标 maps_manual）。只有维护员与管理员能通过（审核接口本来的权限）。
"""

from __future__ import annotations

import copy
import dataclasses
import io
import re
import threading
import time
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import networkx as nx
from ruamel.yaml import YAML
from sqlalchemy import select

from lmesh.core import ai, ai_suggest, analysis, kbservice, review, store
from lmesh.core import rules as rulesmod
from lmesh.core.ai_suggest import (
    Context,
    Env,
    SkillSpec,
    SuggestError,
    Validator,
    reason,
    register_category,
    register_skill,
)
from lmesh.core.ai_suggest_skills import LANG_NAMES, MAX_NAMES, _device_row, _prepare_device, _short
from lmesh.core.kb import KnowledgeBase
from lmesh.core.kb.model import Card
from lmesh.core.store.models import AISuggestion, ConfigVersion, Device, Project, ReviewItem, UnknownLine

MAX_CLAUSES = 80
MAX_STANDARD = 60_000  # 规范文字的上限（字符）
MAX_DOC = 20_000  # 命令卡审核助手的文档原文上限（字符）
MAX_GROUPS = 30  # 未识别行归因一次最多几组
MAX_CARDS = 15  # 映射建议一次最多几张卡（每张都要跑往返与翻译回归）
MAX_SAN_LINES = 400  # 脱敏复核一次最多发几行
TRANSLATE_BUDGET = 20.0  # 映射建议的翻译回归最多用几秒（超时的用例跳过并提醒）
RULES_FILE = "standards.yaml"  # 审核通过的规范规则写进运行时知识库 rules/ 下的这个文件
RULES_HEADER = (
    "公司规范与安全要求转成的检查规则（M8-5，AI 起草、经代码校验与样本试跑、审核通过后写入）。"
    "格式见 src/lmesh/core/rules.py 开头的说明；可以手工修改，修改后运行 lmesh kb validate。"
)
CAUSES = ("missing", "version", "variant")
CARD_ISSUES = ("type", "default", "undo")
SAN_KINDS = ("person", "phone", "email", "customer", "site", "address", "other")
LOCAL_ONLY = {"sanitize-review"}  # 只允许本地模型的 skill
# 库里脱敏后的占位符（这些已经替换过，不需要再处理）
_PLACEHOLDER = re.compile(r"LMESH-|DESC-[0-9A-F]{6}|ORG-[0-9A-F]{6}|DEVICE-[0-9A-F]{6}|ID-[0-9A-F]{6}|user-[0-9A-F]{6}")


def _lang(env: Env) -> str:
    return LANG_NAMES.get(env.lang, "English")


def _root(env: Env) -> Path:
    return kbservice.runtime_root(env.settings)


def _content(d: dict[str, Any]) -> dict[str, Any]:
    c = d.get("content")
    return c if isinstance(c, dict) else {}


def _payload(d: dict[str, Any]) -> dict[str, Any]:
    p = _content(d).get("payload")
    return p if isinstance(p, dict) else {}


def _yaml_safe() -> YAML:
    return YAML(typ="safe")


def _load_yaml_text(text: str) -> Any:
    return _yaml_safe().load(io.StringIO(text))


_WORD = re.compile(r"[^\s{}\[\]()<>|,;:：，。、“”\"']+")


def tokens(*texts: Any) -> set[str]:
    """文字里的词（规范条款、命令语法、文档原文）：AI 照抄这些词时不当成“图中没有的对象”。"""
    out: set[str] = set()
    for t in texts:
        out.update(w.strip(".") for w in _WORD.findall(str(t or "")) if len(w.strip(".")) >= 2)
    return out


# ================================================================ 文档文字（规范转规则的上传）


def extract_text(name: str, data: bytes) -> dict[str, Any]:
    """上传的规范文件 → 文字：txt / md 按 UTF-8（失败时 GB18030）解码；docx 用标准库读 word/document.xml 的段落。"""
    low = name.lower()
    if low.endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read("word/document.xml")
        except (zipfile.BadZipFile, KeyError) as e:
            raise SuggestError("ai_kb.bad_doc", "param", name=name) from e
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        root = ET.fromstring(xml)
        paras = []
        for p in root.iter(f"{ns}p"):
            t = "".join(
                (x.text or "") if x.tag == f"{ns}t" else ("\t" if x.tag == f"{ns}tab" else "") for x in p.iter()
            )
            paras.append(t)
        text = "\n".join(paras)
    elif low.endswith((".txt", ".md", ".markdown", ".text")):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("gb18030", errors="replace")
    else:
        raise SuggestError("ai_kb.bad_doc_type", "param", name=name, allowed="txt, md, docx")
    text = text.replace("\r\n", "\n").strip()
    if not text:
        raise SuggestError("ai_kb.empty_doc", "param", name=name)
    return {"name": name, "text": text[:MAX_STANDARD], "chars": len(text), "truncated": len(text) > MAX_STANDARD}


# ================================================================ 样本（规则试跑、往返回归）

_SAMPLE_LOCK = threading.Lock()
_SAMPLES: dict[tuple[str, int], list[tuple[str, str, str, nx.MultiDiGraph]]] = {}


def sample_graphs(root: Path, kb: KnowledgeBase) -> list[tuple[str, str, str, nx.MultiDiGraph]]:
    """knowledge/samples 清单里的样本建图（文件、Profile、平台族、图），按知识库对象缓存。"""
    from lmesh.core import graph as graphmod
    from lmesh.core import roundtrip
    from lmesh.core.importer import decode

    key = (str(root.resolve()), id(kb))
    with _SAMPLE_LOCK:
        hit = _SAMPLES.get(key)
    if hit is not None:
        return hit
    out = []
    for item in roundtrip.manifest(root):
        path = root / "samples" / str(item["file"])
        if not path.is_file():
            continue
        try:
            res = analysis.parse_text(decode(path.read_bytes()), kb, item.get("profile"))
            g = graphmod.build(res.parsed, kb, res.profile, path.stem)
        except Exception:  # 样本解析失败不影响试跑其他样本
            continue
        out.append((str(item["file"]), res.profile, res.family, g))
    with _SAMPLE_LOCK:
        _SAMPLES.clear()  # 只留当前知识库的一份
        _SAMPLES[key] = out
    return out


def _with_cards(kb: KnowledgeBase, cards: dict[str, Card]) -> KnowledgeBase:
    """换上（或加上）几张命令卡后的知识库副本（浅拷贝，不改缓存里的知识库对象）。"""
    return dataclasses.replace(kb, cards={**kb.cards, **cards})


def _sample_regression(root: Path, kb: KnowledgeBase, family: str) -> dict[str, bool]:
    """该平台族的门槛样本：文件 → 往返一致且功能域内没有未识别行。"""
    from lmesh.core import roundtrip
    from lmesh.core.importer import decode

    out: dict[str, bool] = {}
    for item in roundtrip.manifest(root):
        prof = kb.profiles.get(str(item.get("profile") or ""))
        if prof is None or prof.family != family or not item.get("gate", True):
            continue
        path = root / "samples" / str(item["file"])
        if not path.is_file():
            continue
        try:
            r = roundtrip.run(decode(path.read_bytes()), kb, prof.id, path.stem, diff_limit=1)
            out[str(item["file"])] = bool(r["ok"] and r["unknown"] == 0)
        except Exception:
            out[str(item["file"])] = False
    return out


_BEFORE: dict[tuple[str, int, str], Any] = {}


def _before(kind: str, kb: KnowledgeBase, family: str, fn: Any) -> Any:
    """未改动的知识库上的基准结果（样本往返、翻译回归、校验错误），按知识库对象缓存：一批建议只算一次。"""
    key = (kind, id(kb), family)
    with _SAMPLE_LOCK:
        if key in _BEFORE:
            return _BEFORE[key]
    val = fn()
    with _SAMPLE_LOCK:
        if len(_BEFORE) > 32:
            _BEFORE.clear()
        _BEFORE[key] = val
    return val


def _regressed(before: dict[str, bool], after: dict[str, bool]) -> list[str]:
    return sorted(f for f, ok in before.items() if ok and not after.get(f, False))


# ================================================================ 规范转规则（rule-draft）


_CLAUSE_NO = re.compile(
    r"^\s*(?:§\s*)?((?:\d+(?:\.\d+){0,4})|(?:第[一二三四五六七八九十百零〇\d]+条)|(?:[A-Z]{1,4}-\d{1,4}))[\s.、:：)）]"
)


def split_clauses(text: str) -> list[tuple[str, str]]:
    """规范文字 → 条款（编号, 文字）：有编号的行开始一条新条款；没有编号时按空行分段。"""
    out: list[tuple[str, list[str]]] = []
    blank = True
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip().lstrip("#").strip()
        if not line:
            blank = True
            continue
        m = _CLAUSE_NO.match(line)
        if m or blank or not out:
            out.append((m.group(1) if m else "", [line]))
        else:
            out[-1][1].append(line)
        blank = False
    clauses = []
    for i, (no, lines) in enumerate(out, 1):
        body = " ".join(lines)
        clauses.append((no or f"¶{i}", body))
    return clauses


def _schema_catalogue(kb: KnowledgeBase) -> tuple[list[str], set[str]]:
    """规则可用的对象（target）与子节点（路径的一段），每个对象一行。"""
    rows, names = [], set()
    objs = sorted((n for n in kb.nodes.values() if n.type == "object"), key=lambda n: n.id)
    for o in objs:
        kids = [c for c in kb.children(o.id)]
        parts = []
        for c in kids[:40]:
            tail = c.id[len(o.id) + 1 :] if c.id.startswith(o.id + ".") else c.id
            parts.append(f"{tail}({c.type})")
            names.add(c.id)
        rows.append(f"{o.id} | {', '.join(parts) or '-'}")
        names.add(o.id)
    return rows, names


def _rule_prepare(env: Env, params: dict[str, Any]) -> None:
    text = str(params.get("text") or "").strip()
    sentence = str(params.get("sentence") or "").strip()
    if not text and not sentence:
        raise SuggestError("ai_kb.need_standard", "param")
    if len(text) > MAX_STANDARD or len(sentence) > 2000:
        raise SuggestError("ai_kb.too_long", "param", n=MAX_STANDARD)


def _rule_build(env: Env, params: dict[str, Any]) -> Context:
    text = str(params.get("text") or "").strip()
    sentence = str(params.get("sentence") or "").strip()
    clauses = split_clauses(text)[:MAX_CLAUSES] if text else []
    if sentence:
        clauses.append((str(params.get("sentence_label") or "*"), sentence))
    objects: dict[str, dict[str, Any]] = {}
    rows = []
    for i, (no, body) in enumerate(clauses, 1):
        sid = f"s{i}"
        objects[sid] = {"type": "clause", "label": no, "text": _short(body, 400)}
        rows.append(f"{sid} | {no} | {_short(body, 600)}")
    cat, names = _schema_catalogue(env.kb)
    vars_ = {
        "doc": str(params.get("doc_name") or "-")[:200],
        "clauses": "\n".join(rows),
        "schema": "\n".join(cat),
        "severities": ", ".join(rulesmod.SEVERITIES),
        "lang": _lang(env),
    }
    facts = {
        "objects": objects,
        "numbers": {"clauses": len(clauses)},
        "lines": {},
        "names": sorted(names | {o["label"] for o in objects.values()} | tokens(*(b for _, b in clauses)))[:MAX_NAMES],
    }
    return Context(vars_, facts, "rules:standard", None)


def _rule_from_yaml(text: Any) -> tuple[dict[str, Any] | None, str]:
    """草稿 YAML → 一条规则（字典）；接受单条规则、规则列表或 {rules: [...]}。返回 (规则, 错误说明)。"""
    if not isinstance(text, str) or not text.strip():
        return None, "empty"
    try:
        doc = _load_yaml_text(text)
    except Exception as e:  # YAML 语法错误
        return None, (str(e).splitlines() or ["yaml"])[0][:300]
    if isinstance(doc, dict) and isinstance(doc.get("rules"), list):
        doc = doc["rules"]
    if isinstance(doc, list):
        if len(doc) != 1:
            return None, "one rule per suggestion"
        doc = doc[0]
    if not isinstance(doc, dict):
        return None, "not a mapping"
    return doc, ""


def _existing_check_docs(root: Path) -> list[tuple[str, Any]]:
    from lmesh.core import checks

    try:
        return rulesmod.read_docs(checks.rules_dir(root), "check")
    except rulesmod.RuleError:
        return []


def trial_rule(root: Path, kb: KnowledgeBase, rule: rulesmod.Rule, limit: int = 30) -> dict[str, Any]:
    """在样本上试跑一条规则：命中（违反规则的实例）列表、适用的实例数、命中的样本数。"""
    hits: list[dict[str, Any]] = []
    applicable = hit_count = hit_samples = with_target = 0
    samples = sample_graphs(root, kb)
    for file, _profile, _family, g in samples:
        ev = rulesmod.Evaluator(g)
        inst = rulesmod.instances(g).get(rule.target, [])
        n_app = 0
        n_hit = 0
        for n in inst:
            if rule.when is not None and not ev.test(rule, n, rule.when):
                continue
            n_app += 1
            if rule.assert_ is not None and not ev.test(rule, n, rule.assert_):
                n_hit += 1
                if len(hits) < limit:
                    d = g.nodes[n]
                    hits.append(
                        {
                            "sample": file,
                            "node": n,
                            "key": rulesmod.key_text(d.get("key")),
                            "line": (sorted(d.get("lines") or []) or [None])[0],
                        }
                    )
        applicable += n_app
        hit_count += n_hit
        with_target += 1 if n_app else 0
        hit_samples += 1 if n_hit else 0
    return {
        "samples": len(samples),
        "applicable": applicable,
        "samples_applicable": with_target,
        "hits": hit_count,
        "samples_hit": hit_samples,
        "items": hits,
    }


def _rule_check(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    c, p = _content(d), _payload(d)
    if str(c.get("review_kind") or "") != "rule":
        return [reason("bad_review_kind", ref=str(c.get("review_kind")))]
    raw, err = _rule_from_yaml(p.get("yaml"))
    if raw is None:
        return [reason("rule_yaml", detail=err)]
    if str(c.get("target") or "") != str(raw.get("id") or ""):
        return [reason("rule_target_mismatch", ref=str(c.get("target") or ""))]
    out: list[dict[str, Any]] = []
    if not any(str(r.get("id") or "").startswith("s") for r in ai_suggest._ref_ids(d.get("refs"))):
        out.append(reason("no_clause_ref", "warn"))
    root = _root(env)
    docs = [*_existing_check_docs(root), ("ai-draft.yaml", {"rules": [raw]})]
    try:
        parsed = rulesmod.parse_rules(env.kb, docs)
    except rulesmod.RuleError as e:
        mine = [i for i in e.issues if i.get("file") == "ai-draft.yaml" or i.get("code") == "rules.err.duplicate_id"]
        mine = mine or e.issues
        for i in mine[:8]:
            out.append(
                reason("rule_invalid", ref=str(i.get("field") or i.get("rule") or ""), detail=str(i.get("code")))
            )
        return out
    rule = next(r for r in parsed if r.file == "ai-draft.yaml")
    if rule.assert_ is None:
        out.append(reason("rule_ai_only", "warn"))
        return out
    trial = trial_rule(root, env.kb, rule)
    env.out["result"] = {"trial": trial}
    if trial["hits"] == 0:
        out.append(reason("rule_no_hits", "warn"))
    elif trial["applicable"] >= 3 and trial["hits"] == trial["applicable"]:
        out.append(reason("rule_all_hit", "warn", detail=f"{trial['hits']}/{trial['applicable']}"))
    return out


register_skill(
    SkillSpec(
        id="rule-draft",
        build=_rule_build,
        categories=("kb_review",),
        default_category="kb_review",
        scope="project",
        prepare=_rule_prepare,
        check=_rule_check,
    )
)


@review.register_action("rule")
def _approve_rule(kb_root: Path, item: ReviewItem, edited: dict[str, Any] | None) -> None:
    """通过规则草稿：追加到 rules/standards.yaml（ruamel 往返写回，保留注释与顺序）；写入后重新加载全部检查规则，
    出错时恢复原文件并拒绝（知识库不会处在半坏的状态）。审核时可以改 YAML（edited.yaml）。"""
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    from lmesh.core import checks, rule_edit
    from lmesh.core.kb import files as kbfiles

    text = (edited or {}).get("yaml") or (item.payload or {}).get("yaml")
    raw, err = _rule_from_yaml(text)
    if raw is None:
        raise review.ReviewError("review.rule_invalid")
    directory = rule_edit.ensure_rules_dir(kb_root)
    path = directory / RULES_FILE
    before = path.read_bytes() if path.exists() else None
    doc = kbfiles.load_rt(path) if path.exists() else None
    if not isinstance(doc, CommentedMap):
        doc = CommentedMap()
        doc.yaml_set_start_comment(RULES_HEADER)
    if not isinstance(doc.get("rules"), list):
        doc["rules"] = CommentedSeq()
    rt = kbfiles._yaml().load(io.StringIO(str(text)))
    if isinstance(rt, dict) and isinstance(rt.get("rules"), list):
        rt = rt["rules"]
    if isinstance(rt, list):
        rt = rt[0]
    doc["rules"].append(rt)
    kbfiles.dump_rt(path, doc)
    try:
        rulesmod.load_dir(analysis.load_kb(kb_root), directory)
        checks.load_overrides(directory)
    except rulesmod.RuleError as e:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(before)
        raise review.ReviewError("review.rule_invalid") from e


# ================================================================ 基线例外说明（baseline-waiver）


def _waiver_prepare(env: Env, params: dict[str, Any]) -> None:
    _prepare_device(env, params)
    if not str(params.get("rule") or "").strip():
        raise SuggestError("ai_kb.need_rule", "param")


def _waiver_build(env: Env, params: dict[str, Any]) -> Context:
    from lmesh.core import baseline as blmod

    g, ver, dev = _device_row(env, int(params["device_id"]))
    root = _root(env)
    try:
        bl = blmod.load(env.kb, blmod.baseline_dir(root))
    except rulesmod.RuleError as e:
        raise SuggestError("rules.invalid", "state", n=len(e.issues)) from e
    profile = str(params.get("baseline") or blmod.DEFAULT_PROFILE)
    if profile not in bl.profiles:
        raise SuggestError("baseline.unknown_profile", "param", profile=profile, allowed=", ".join(bl.profiles))
    rules, overrides = blmod.select(bl, profile)
    rid = str(params["rule"])
    rule = next((r for r in rules if r.id == rid), None)
    if rule is None:
        raise SuggestError("ai_kb.rule_not_found", "not_found", rule=rid)
    res = blmod.audit_device(g, [rule], overrides)
    if res["results"].get(rid) != "fail":
        raise SuggestError("ai_kb.rule_not_failed", "state", rule=rid)
    lang = env.lang if env.lang in rule.title else "en"
    objects: dict[str, dict[str, Any]] = {
        "d1": {"type": "device", "label": dev.name, "device_id": dev.id, "version_id": ver.id},
        "r1": {"type": "rule", "label": rid},
    }
    names = {dev.name, rid}
    rows, lines_shown = [], set()
    text_lines = ver.raw_text.split("\n")
    for i, f in enumerate(res["failures"][:30], 1):
        nid = f"n{i}"
        d = g.nodes[f["node"]]
        label = d.get("key") if d.get("key") is not None else f["node"]
        objects[nid] = {
            "type": f.get("schema"),
            "label": rulesmod.key_text(label) if isinstance(label, dict) else label,
            "device": "d1",
            "node": f["node"],
            "line": (f["lines"] or [None])[0],
        }
        names.add(str(objects[nid]["label"]))
        rows.append(f"{nid} | {f.get('schema')} | {_short(objects[nid]['label'])} | lines {f['lines'][:6]}")
        lines_shown.update(f["lines"][:6])
    evidence = "\n".join(f"{n:>5}  {text_lines[n - 1]}" for n in sorted(lines_shown)[:60] if 0 < n <= len(text_lines))
    numbers = {"failures": len(res["failures"]), "lines": len(text_lines)}
    vars_ = {
        "device": f"d1 | {dev.name} | platform={dev.platform or '-'} | profile={g.graph.get('profile') or '-'}",
        "rule": f"r1 | {rid} | severity={rule.severity} | {rule.title.get(lang, '')}",
        "message": rule.message.get(lang, ""),
        "suggestion": rule.suggestion.get(lang, ""),
        "remedy": "\n".join(blmod.remedy_for(rule, g.graph.get("family"))) or "-",
        "failures": "\n".join(rows),
        "evidence": evidence or "-",
        "facts": "\n".join(f"{k} = {v}" for k, v in numbers.items()),
        "lang": _lang(env),
    }
    names |= tokens(*rule.title.values(), *rule.message.values(), *rule.suggestion.values())
    facts = {"objects": objects, "numbers": numbers, "lines": {"d1": len(text_lines)}, "names": sorted(names)}
    return Context(vars_, facts, f"waiver:{dev.id}:{profile}:{rid}", dev.id)


def _waiver_check(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    if d.get("kind") not in ("reason", "compensating"):
        return [reason("bad_kind", "warn", ref=str(d.get("kind")))]
    return []


register_skill(
    SkillSpec(
        id="baseline-waiver",
        build=_waiver_build,
        categories=("text_only",),
        default_category="text_only",
        scope="device",
        prepare=_waiver_prepare,
        check=_waiver_check,
    )
)


# ================================================================ 脱敏复核（sanitize-review，只允许本地模型）


def local_gate(env: Env, skill_id: str) -> dict[str, Any]:
    """只允许本地模型的 skill：当前生效的 AI 接口（按发起人的选择）不是 local 时不允许运行。"""
    res = ai.resolve(env.settings)
    provider = res.conn.provider if res.conn else None
    if skill_id not in LOCAL_ONLY:
        return {"skill": skill_id, "allowed": True, "local_only": False, "provider": provider, "reason": None}
    allowed = provider is None or provider == "local"  # 没有配置 AI 时由“未配置”的提示处理（回放不发送任何内容）
    return {
        "skill": skill_id,
        "allowed": allowed,
        "local_only": True,
        "provider": provider,
        "connection": res.conn.name if res.conn else None,
        "reason": None if allowed else "local_only",
    }


def _require_local(env: Env) -> None:
    gate = local_gate(env, "sanitize-review")
    if not gate["allowed"]:
        raise SuggestError("ai_kb.local_only", "state", data=gate, provider=str(gate["provider"]))


def _san_prepare(env: Env, params: dict[str, Any]) -> None:
    _prepare_device(env, params)
    _require_local(env)


_FREE_TEXT = re.compile(
    r"\b(description|desc|name|alias|contact|location|remark|comment|banner|header|motd|info|sysname|hostname|"
    r"text|label|owner|customer|site|address|e-?mail|phone|tel)\b|@|\d{7,}",
    re.I,
)


def _san_candidates(lines: list[str]) -> list[int]:
    """代码先挑出可能含自由文本的行（描述、名称、联系人、位置、横幅、邮箱、长数字……），只把这些行发给本地模型。"""
    out = []
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if s and _FREE_TEXT.search(s):
            out.append(i)
    return out


def _san_build(env: Env, params: dict[str, Any]) -> Context:
    _require_local(env)  # 后台任务运行时再确认一次（提交后用户可能改了 AI 选择）
    g, ver, dev = _device_row(env, int(params["device_id"]))
    lines = ver.raw_text.split("\n")
    picked = _san_candidates(lines)[:MAX_SAN_LINES]
    rows = [f"{n:>5}  {lines[n - 1]}" for n in picked]
    objects = {"d1": {"type": "device", "label": dev.name, "device_id": dev.id, "version_id": ver.id}}
    vars_ = {
        "device": f"d1 | {dev.name} | vendor={dev.vendor}",
        "lines": "\n".join(rows) or "(none)",
        "kinds": ", ".join(SAN_KINDS),
        "lang": _lang(env),
    }
    facts = {
        "objects": objects,
        "numbers": {"lines": len(lines), "picked": len(picked)},
        "lines": {"d1": len(lines)},
        "names": [dev.name],
        "version_id": ver.id,
        "san_lines": {str(n): lines[n - 1] for n in picked},  # 发给 AI 的行（AI 只能标这些行）
    }
    return Context(vars_, facts, f"device:{dev.id}", dev.id)


def _stored_text(env: Env, facts: dict[str, Any]) -> str:
    with store.session(env.db) as s:
        ver = s.get(ConfigVersion, int(facts.get("version_id") or 0))
        return ver.raw_text if ver is not None else ""


def redact_pattern(c: dict[str, Any]) -> str:
    """建议对应的脱敏规则（正则）：给了 pattern 用它，否则用标出的文字（按字面匹配）。"""
    pat = str(c.get("pattern") or "").strip()
    return pat or re.escape(str(c.get("text") or ""))


def _check_san(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    from lmesh.core.sanitize import Sanitizer, local_key

    c = _content(d)
    text = str(c.get("text") or "")
    n = c.get("line")
    top = int((facts.get("lines") or {}).get("d1") or 0)
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= top:
        return [reason("line_not_found", ref=str(n))]
    if len(text.strip()) < 3:
        return [reason("san_too_short", ref=text)]
    if c.get("kind") not in SAN_KINDS:
        return [reason("bad_kind", "warn", ref=str(c.get("kind")))]
    shown = (facts.get("san_lines") or {}).get(str(n))
    if shown is None:
        return [reason("line_not_found", ref=str(n))]  # 不是发给 AI 的行
    if text not in shown:
        return [reason("san_not_in_line", ref=text, line=n)]  # AI 编造了这一行没有的内容
    stored = _stored_text(env, facts) or "\n".join((facts.get("san_lines") or {}).values())
    lines = stored.split("\n")
    if _PLACEHOLDER.search(text):
        return [reason("san_already", ref=text, line=n)]
    pat = redact_pattern(c)
    try:
        rx = re.compile(pat, re.I)
    except re.error:
        return [reason("san_bad_pattern", ref=pat)]
    if not rx.search(text):
        return [reason("san_pattern_miss", ref=pat)]
    out: list[dict[str, Any]] = []
    matched = sum(1 for ln in lines if rx.search(ln))
    if matched > max(20, len(lines) // 10):
        out.append(reason("san_too_broad", "warn", detail=f"{matched}"))
    try:
        res = Sanitizer("basic", local_key(), redact=[pat]).sanitize(stored)
    except Exception as e:  # 自检发现残留秘密等
        return [reason("san_failed", detail=type(e).__name__)]
    if text.lower() in res.text.lower():
        return [reason("san_still_there", ref=text)]
    env.out["result"] = {"occurrences": stored.count(text), "lines_matched": matched, "pattern": pat}
    if c.get("explain"):
        out += [r for r in ai_suggest.check_text(str(c["explain"]), facts) if r["level"] == "reject"]
    return out


def project_redact(db_url: str, project_id: int | None) -> list[str]:
    """项目的脱敏补充（采纳的脱敏复核建议）：正则列表。"""
    if project_id is None:
        return []
    with store.session(db_url) as s:
        p = s.get(Project, project_id)
        return [str(x) for x in ((p.settings or {}).get("sanitize_redact") or [])] if p else []


def _adopt_san(env: Env, row: AISuggestion, facts: dict[str, Any]) -> dict[str, Any]:
    if env.project_id is None:
        raise SuggestError("ai_suggest.need_project", "state")
    pat = redact_pattern(row.content or {})
    with store.session(env.db) as s:
        p = s.get(Project, env.project_id)
        if p is None:
            raise SuggestError("ai_suggest.need_project", "state")
        cur = list((p.settings or {}).get("sanitize_redact") or [])
        existed = pat in cur
        if not existed:
            cur.append(pat)
        p.settings = {**(p.settings or {}), "sanitize_redact": cur}
    return {"action": "redact", "pattern": pat, "existed": existed, "project_id": env.project_id}


def _revert_san(env: Env, row: AISuggestion) -> dict[str, Any]:
    info = row.adopt_info or {}
    if info.get("existed"):
        return {"action": "none"}
    with store.session(env.db) as s:
        p = s.get(Project, int(info.get("project_id") or row.project_id or 0))
        if p is None:
            return {"action": "none"}
        cur = [x for x in (p.settings or {}).get("sanitize_redact") or [] if x != info.get("pattern")]
        p.settings = {**(p.settings or {}), "sanitize_redact": cur}
    return {"action": "redact_removed", "pattern": info.get("pattern")}


register_category("sanitize_rule", Validator(_check_san, _adopt_san, _revert_san))

register_skill(
    SkillSpec(
        id="sanitize-review",
        build=_san_build,
        categories=("sanitize_rule",),
        default_category="sanitize_rule",
        scope="device",
        prepare=_san_prepare,
    )
)


# ================================================================ 命令卡（草稿 → Card）


def _card_obj(raw: dict[str, Any], family: str, domain: str, file: str = "") -> Card:
    return Card(
        id=str(raw["id"]),
        family=family,
        domain=domain,
        syntax=str(raw["syntax"]),
        view=str(raw.get("view") or ""),
        file=file,
        undo=raw.get("undo"),
        enters_view=raw.get("enters_view"),
        params={str(k): dict(v or {}) for k, v in (raw.get("params") or {}).items()},
        default=None if raw.get("default") is None else str(raw.get("default")),
        maps={str(k): (dict(v) if isinstance(v, dict) else str(v)) for k, v in (raw.get("maps") or {}).items()},
        depends_on=list(raw.get("depends_on") or []),
        side_effects=list(raw.get("side_effects") or []),
        source=dict(raw.get("source") or {}),
        status="reviewed",
    )


def _card_dict(c: Card) -> dict[str, Any]:
    out: dict[str, Any] = {"id": c.id, "syntax": c.syntax, "view": c.view}
    for k in ("undo", "enters_view", "default"):
        if getattr(c, k):
            out[k] = getattr(c, k)
    for k in ("params", "maps", "depends_on", "side_effects"):
        if getattr(c, k):
            out[k] = copy.deepcopy(getattr(c, k))
    return out


def _card_problems(raw: Any, kb: KnowledgeBase, family: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """草稿卡的字段检查：编号、语法能解析、视图属于该平台族、参数只能是语法里的。"""
    from lmesh.core.kb import syntax as syn

    if not isinstance(raw, dict):
        return [reason("card_bad")], {}
    out: list[dict[str, Any]] = []
    for k in ("id", "syntax", "view"):
        if not str(raw.get(k) or "").strip():
            out.append(reason("card_incomplete", ref=k))
    if out:
        return out, {}
    fam = kb.families.get(family)
    if fam is None:
        return [reason("card_bad", ref=family)], {}
    try:
        parsed = syn.parse(str(raw["syntax"]))
    except syn.SyntaxErrorKB as e:
        return [reason("card_syntax", detail=str(e)[:200])], {}
    if raw.get("undo"):
        try:
            syn.parse(str(raw["undo"]))
        except syn.SyntaxErrorKB as e:
            out.append(reason("card_syntax", ref="undo", detail=str(e)[:200]))
    if str(raw["view"]) not in fam.views and str(raw["view"]) != fam.root_view:
        out.append(reason("card_view", ref=str(raw["view"])))
    have = set(parsed.params())
    for p in raw.get("params") or {}:
        if str(p) not in have:
            out.append(reason("card_param", ref=str(p)))
    return out, {"params": sorted(have)}


# ================================================================ 未识别行归因（unknown-triage）


def _unknown_groups(env: Env, patterns: list[str] | None) -> list[dict[str, Any]]:
    """当前项目的未识别行，按（视图, 模式）分组：次数、平台族、示例（设备、版本、行号）。"""
    from lmesh.core import projects

    with store.session(env.db) as s:
        q = (
            select(
                UnknownLine.view,
                UnknownLine.pattern,
                UnknownLine.text,
                UnknownLine.line_no,
                UnknownLine.version_id,
                Device.name,
                Device.profile,
            )
            .join(ConfigVersion, ConfigVersion.id == UnknownLine.version_id)
            .join(Device, Device.id == ConfigVersion.device_id)
        )
        q = projects.scoped_devices(q)
        if patterns:
            q = q.where(UnknownLine.pattern.in_(patterns))
        rows = s.execute(q).all()
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for view, pattern, text, line_no, vid, dev, prof in rows:
        p = env.kb.profiles.get(str(prof or ""))
        fam = p.family if p else ""
        g = groups.setdefault(
            (fam, view, pattern),
            {"family": fam, "view": view, "pattern": pattern, "count": 0, "devices": set(), "examples": []},
        )
        g["count"] += 1
        g["devices"].add(dev)
        if len(g["examples"]) < 6:
            g["examples"].append({"text": text, "line": line_no, "version_id": vid, "device": dev, "profile": prof})
    out = sorted(groups.values(), key=lambda x: (-x["count"], x["pattern"]))
    vids = {e["version_id"] for g in out[:MAX_GROUPS] for e in g["examples"]}
    with store.session(env.db) as s:
        vers = {v: s.get(ConfigVersion, v) for v in vids}
        texts = {v: (cv.raw_text or "").split("\n") for v, cv in vers.items() if cv is not None}
    for gr in out:
        gr["devices"] = sorted(gr["devices"])
        for e in gr["examples"]:
            e["context"] = _ancestors(texts.get(e["version_id"]) or [], int(e["line"]))
    return [g for g in out if g["family"]]


def _ancestors(lines: list[str], no: int) -> list[str]:
    """这一行与它所在的各级视图的开头行（按缩进向上找），用于没有整份配置时单独重新解析。"""
    if not 1 <= no <= len(lines):
        return []
    out = [lines[no - 1]]
    indent = len(lines[no - 1]) - len(lines[no - 1].lstrip())
    for i in range(no - 2, -1, -1):
        ln = lines[i]
        if not ln.strip():
            continue
        ind = len(ln) - len(ln.lstrip())
        if ind < indent:
            out.append(ln)
            indent = ind
            if ind == 0:
                break
    return list(reversed(out))


def _triage_prepare(env: Env, params: dict[str, Any]) -> None:
    pats = params.get("patterns")
    if pats is not None and (not isinstance(pats, list) or not all(isinstance(x, str) for x in pats)):
        raise SuggestError("ai_kb.bad_patterns", "param")


def _triage_build(env: Env, params: dict[str, Any]) -> Context:
    groups = _unknown_groups(env, params.get("patterns") or None)[:MAX_GROUPS]
    if not groups:
        raise SuggestError("ai_kb.no_unknown", "state")
    objects: dict[str, dict[str, Any]] = {}
    rows, cand_rows = [], []
    names: set[str] = set()
    numbers: dict[str, Any] = {"groups": len(groups)}
    cand: dict[str, str] = {}  # 卡编号 → k 编号
    for i, gr in enumerate(groups, 1):
        uid = f"u{i}"
        objects[uid] = {
            "type": "unknown",
            "label": gr["pattern"],
            "family": gr["family"],
            "view": gr["view"],
            "count": gr["count"],
            "examples": gr["examples"],
        }
        numbers[f"count.{uid}"] = gr["count"]
        ex = "; ".join(f"{e['device']} L{e['line']}: {e['text'].strip()}" for e in gr["examples"][:3])
        rows.append(
            f"{uid} | family={gr['family']} | view={gr['view']} | lines={gr['count']} | {gr['pattern']} | e.g. {ex}"
        )
        first = (gr["examples"][0]["text"].split() or [""])[0].lower() if gr["examples"] else ""
        if first in (env.kb.families[gr["family"]].negative,):
            first = (gr["examples"][0]["text"].split()[1:2] or [""])[0].lower()
        for c in env.kb.cards_of(gr["family"]):
            if len(cand) >= 120:
                break
            lead = c.syntax.split()[0].lower() if c.syntax.split() else ""
            if lead == first and c.id not in cand:
                kid = f"k{len(cand) + 1}"
                cand[c.id] = kid
                objects[kid] = {"type": "card", "label": c.id, "family": c.family, "domain": c.domain}
                names.add(c.id)
                vers = c.source.get("version") or "-"
                cand_rows.append(f"{kid} | {c.id} | view={c.view} | domain={c.domain} | version={vers} | {c.syntax}")
    for f in {g["family"] for g in groups}:
        names.update(env.kb.families[f].views)
    vars_ = {
        "groups": "\n".join(rows),
        "cards": "\n".join(cand_rows) or "(none)",
        "domains": ", ".join(env.kb.domains),
        "views": "; ".join(
            f"{f}: {', '.join(sorted(env.kb.families[f].views))}" for f in sorted({g["family"] for g in groups})
        ),
        "causes": ", ".join(CAUSES),
        "lang": _lang(env),
    }
    names |= tokens(*(g["pattern"] for g in groups), *(e["text"] for g in groups for e in g["examples"]))
    names |= tokens(*(env.kb.cards[c].syntax for c in cand))
    facts = {"objects": objects, "numbers": numbers, "lines": {}, "names": sorted(names)[:MAX_NAMES]}
    return Context(vars_, facts, "unknown-lines", None)


def _reparse(env: Env, kb2: KnowledgeBase, examples: list[dict[str, Any]], family: str) -> tuple[int, int]:
    """用换过卡的知识库重新解析这些示例所在的配置：返回（示例行数, 变成已识别的行数）。"""
    from lmesh.core import parser

    by_ver: dict[int, list[dict[str, Any]]] = {}
    for e in examples:
        by_ver.setdefault(int(e.get("version_id") or 0), []).append(e)
    total = done = 0
    with store.session(env.db) as s:
        texts: dict[int, str] = {}
        for v in by_ver:
            cv = s.get(ConfigVersion, v) if v else None
            texts[v] = cv.raw_text if cv is not None else ""
    for vid, exs in by_ver.items():
        text = texts.get(vid) or ""
        if text:  # 整份配置重新解析
            parsed = parser.parse(text.replace("\r\n", "\n"), kb2, family)
            kinds = {ln.no: ln.kind for ln in parsed.lines}
            for e in exs:
                total += 1
                done += 1 if kinds.get(int(e["line"])) == "command" else 0
            continue
        for e in exs:  # 没有配置版本时（skill 管理页的样例回放）：按这一行与各级视图的开头行单独解析
            ctx = [str(x) for x in e.get("context") or []] or [str(e.get("text") or "")]
            parsed = parser.parse("\n".join(ctx), kb2, family)
            total += 1
            done += 1 if parsed.lines and parsed.lines[len(ctx) - 1].kind == "command" else 0
    return total, done


def _triage_check(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    c, p = _content(d), _payload(d)
    if str(c.get("review_kind") or "") != "unknown_card":
        return [reason("bad_review_kind", ref=str(c.get("review_kind")))]
    objs = facts.get("objects") or {}
    gid = str(p.get("group") or "")
    grp = objs.get(gid)
    if not grp or grp.get("type") != "unknown":
        return [reason("ref_not_found", ref=gid)]
    cause = str(p.get("cause") or d.get("kind") or "")
    if cause not in CAUSES:
        return [reason("bad_cause", ref=cause)]
    family = str(grp["family"])
    raw = p.get("card")
    base_id = ""
    if cause != "missing":
        base = objs.get(str(p.get("base") or ""))
        if not base or base.get("type") != "card":
            return [reason("ref_not_found", ref=str(p.get("base") or ""))]
        base_id = str(base["label"])
        if isinstance(raw, dict) and str(raw.get("id") or base_id) != base_id:
            return [reason("card_id_changed", ref=str(raw.get("id")))]
        if isinstance(raw, dict):
            raw = {**_card_dict(env.kb.cards[base_id]), **raw, "id": base_id}
    problems, _info = _card_problems(raw, env.kb, family)
    if problems:
        return problems
    assert isinstance(raw, dict)
    cid = str(raw["id"])
    if cause == "missing":
        if cid in env.kb.cards:
            return [reason("card_exists", ref=cid)]
        if not cid.startswith(family + "."):
            return [reason("card_bad_id", ref=cid)]
        domain = str(p.get("domain") or "")
        if domain not in env.kb.domains:
            return [reason("bad_domain", ref=domain)]
    else:
        domain = env.kb.cards[base_id].domain
    if str(c.get("target") or "") != cid:
        return [reason("card_target_mismatch", ref=str(c.get("target") or ""))]
    card = _card_obj(raw, family, domain)
    kb2 = _with_cards(env.kb, {cid: card})
    total, done = _reparse(env, kb2, list(grp.get("examples") or []), family)
    env.out["result"] = {"reparse": {"lines": total, "recognized": done, "group": gid, "count": grp.get("count")}}
    if total == 0 or done == 0:
        return [reason("still_unknown", detail=f"{done}/{total}")]
    out: list[dict[str, Any]] = []
    if done < total:
        out.append(reason("partly_unknown", "warn", detail=f"{done}/{total}"))
    if cause != "missing":  # 改已有的卡：该平台族的样本往返不能变差
        root = _root(env)
        base = _before("samples", env.kb, family, lambda: _sample_regression(root, env.kb, family))
        bad = _regressed(base, _sample_regression(root, kb2, family))
        if bad:
            out.append(reason("breaks_samples", detail=", ".join(bad[:5])))
    return out


register_skill(
    SkillSpec(
        id="unknown-triage",
        build=_triage_build,
        categories=("kb_review",),
        default_category="kb_review",
        scope="project",
        prepare=_triage_prepare,
        check=_triage_check,
    )
)


def _family_of_card_id(kb_root: Path, cid: str) -> str:
    fams = sorted((p.name for p in (kb_root / "commands").iterdir() if p.is_dir()), key=len, reverse=True)
    return next((f for f in fams if cid.startswith(f + ".")), "")


@review.register_action("unknown_card")
def _approve_unknown_card(kb_root: Path, item: ReviewItem, edited: dict[str, Any] | None) -> None:
    """未识别行归因的命令卡：缺命令卡时追加到该平台族、该功能域的卡文件；版本差异 / 写法变体时修改已有的卡
    （草稿给出的字段覆盖原值）。审核时可以改字段（edited.card）。写入的卡状态为 reviewed。"""
    from lmesh.core.kb import files as kbfiles
    from lmesh.core.kb import syntax as syn

    payload = item.payload or {}
    card = {**dict(payload.get("card") or {}), **dict((edited or {}).get("card") or {})}
    cause = str(payload.get("cause") or "missing")
    if cause == "missing":
        for k in ("id", "syntax", "view"):
            if not card.get(k):
                raise review.ReviewError("review.card_incomplete")
        syn.parse(str(card["syntax"]))
        family = _family_of_card_id(kb_root, str(card["id"]))
        domain = str(payload.get("domain") or "")
        if not family or not domain:
            raise review.ReviewError("review.card_incomplete")
        path = kbfiles.card_file(kb_root, family, domain)
        from lmesh.core.ingest.service import HEADER

        doc = kbfiles.load_card_doc(path, domain, HEADER)
        if any(str(c.get("id")) == str(card["id"]) for c in doc["cards"]):
            raise review.ReviewError("review.card_exists")
        clean = {k: v for k, v in card.items() if k in kbfiles.CARD_FIELDS}
        clean["status"] = "reviewed"
        clean.setdefault("source", {"via": "ai", "suggestion": payload.get("ai_suggestion")})
        doc["cards"].append(kbfiles.to_card_map(clean))
        kbfiles.dump_rt(path, doc)
        return
    found = kbfiles.find_card(kb_root, str(payload.get("base") or item.target))
    if found is None:
        raise review.ReviewError("review.card_missing")
    path, doc, idx = found
    target = doc["cards"][idx]
    for k, v in card.items():
        if k in kbfiles.CARD_FIELDS and k not in ("id", "status"):
            target[k] = v
    syn.parse(str(target["syntax"]))
    target["status"] = "reviewed"
    kbfiles.dump_rt(path, doc)


# ================================================================ 命令卡审核助手（card-review）


def _card_review_prepare(env: Env, params: dict[str, Any]) -> None:
    cid = str(params.get("card_id") or "").strip()
    if not cid and params.get("review_id") is not None:
        with store.session(env.db) as s:
            it = s.get(ReviewItem, int(params["review_id"]))
            cid = str(it.target) if it is not None and it.kind in ("card", "unknown_card") else ""
    if not cid:
        raise SuggestError("ai_kb.need_card", "param")
    if cid not in env.kb.cards:
        raise SuggestError("ai_kb.card_not_found", "not_found", id=cid)
    params["card_id"] = cid
    if len(str(params.get("doc_text") or "")) > MAX_DOC:
        raise SuggestError("ai_kb.too_long", "param", n=MAX_DOC)


_DOC_NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")


def _card_review_build(env: Env, params: dict[str, Any]) -> Context:
    card = env.kb.cards[str(params["card_id"])]
    objects: dict[str, dict[str, Any]] = {}
    rows = []
    numbers: dict[str, Any] = {}
    fields: list[tuple[str, Any]] = [("id", card.id), ("view", card.view), ("syntax", card.syntax)]
    fields += [("undo", card.undo), ("enters_view", card.enters_view), ("default", card.default)]
    for name, spec in card.params.items():
        fields.append((f"param.{name}", ", ".join(f"{k}: {v}" for k, v in spec.items())))
        rng = spec.get("range")
        if isinstance(rng, list):
            for j, v in enumerate(rng):
                numbers[f"param.{name}.range.{j}"] = v
    if card.maps:
        fields.append(("maps", ", ".join(f"{k} = {v}" for k, v in card.maps.items())))
    names = {card.id, card.view}
    i = 0
    for name, value in fields:
        if value in (None, ""):
            continue
        i += 1
        fid = f"f{i}"
        objects[fid] = {"type": "field", "label": name, "value": str(value)}
        names.add(name)
        rows.append(f"{fid} | {name}: {value}")
    doc = str(params.get("doc_text") or "").replace("\r\n", "\n").strip()
    doc_lines = doc.split("\n") if doc else []
    for k, tok in enumerate(sorted({x.group(0) for x in _DOC_NUM.finditer(doc)})[:200]):
        numbers[f"doc.n{k}"] = float(tok) if "." in tok else int(tok)
    for m in _DOC_NUM.finditer(" ".join(str(v) for _, v in fields if v)):
        numbers.setdefault(f"card.{m.group(0)}", float(m.group(0)) if "." in m.group(0) else int(m.group(0)))
    src = card.source or {}
    vars_ = {
        "card": "\n".join(rows),
        "source": " | ".join(f"{k}={src[k]}" for k in ("doc", "file", "title", "version", "line") if src.get(k)) or "-",
        "doc": "\n".join(f"{n:>4}  {ln}" for n, ln in enumerate(doc_lines, 1)) or "(no document text given)",
        "issues": ", ".join(CARD_ISSUES),
        "lang": _lang(env),
    }
    facts = {
        "objects": objects,
        "numbers": numbers,
        "lines": {"doc": len(doc_lines)} if doc_lines else {},
        "names": sorted(names | tokens(*(v for _, v in fields), doc)),
        "doc_lines": doc_lines,
    }
    return Context(vars_, facts, f"card:{card.id}", None)


def _card_review_check(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    refs = ai_suggest._ref_ids(d.get("refs"))
    if not any(str(r.get("id") or "").startswith("f") for r in refs):
        out.append(reason("no_field_ref"))
    if d.get("kind") not in CARD_ISSUES:
        out.append(reason("bad_kind", "warn", ref=str(d.get("kind"))))
    doc_lines = facts.get("doc_lines") or []
    cited = [int(r["line"]) for r in refs if "line" in r and isinstance(r.get("line"), int)]
    if doc_lines and not cited:
        out.append(reason("no_doc_ref", "warn"))
    quote = str(_content(d).get("quote") or "").strip()
    if quote:
        norm = " ".join(quote.split()).lower()
        if not any(1 <= n <= len(doc_lines) and norm in " ".join(doc_lines[n - 1].split()).lower() for n in cited):
            out.append(reason("quote_not_in_doc", ref=_short(quote, 80)))
    return out


register_skill(
    SkillSpec(
        id="card-review",
        build=_card_review_build,
        categories=("text_only", "refs_exist"),
        default_category="text_only",
        scope="project",
        prepare=_card_review_prepare,
        check=_card_review_check,
    )
)


# ================================================================ 映射建议（mapping-suggest）


def _unmapped(kb: KnowledgeBase, family: str) -> list[Card]:
    return [c for c in kb.cards_of(family) if not c.maps and c.status != "rejected"]


def _map_prepare(env: Env, params: dict[str, Any]) -> None:
    fam = str(params.get("family") or "")
    if fam not in env.kb.families:
        raise SuggestError("ai_kb.bad_family", "param", family=fam, allowed=", ".join(sorted(env.kb.families)))
    ids = params.get("card_ids")
    if ids is not None:
        if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
            raise SuggestError("ai_kb.bad_cards", "param")
        missing = [x for x in ids if x not in env.kb.cards or env.kb.cards[x].family != fam]
        if missing:
            raise SuggestError("ai_kb.card_not_found", "not_found", id=", ".join(missing[:5]))


def _map_build(env: Env, params: dict[str, Any]) -> Context:
    fam = str(params["family"])
    ids = params.get("card_ids") or []
    cards = [env.kb.cards[x] for x in ids] if ids else _unmapped(env.kb, fam)
    if params.get("domain") and not ids:
        cards = [c for c in cards if c.domain == str(params["domain"])]
    cards = cards[: int(params.get("limit") or MAX_CARDS)][:MAX_CARDS]
    if not cards:
        raise SuggestError("ai_kb.no_unmapped", "state", family=fam)
    objects: dict[str, dict[str, Any]] = {}
    rows, names = [], set()
    domains = {c.domain for c in cards}
    for i, c in enumerate(cards, 1):
        cid = f"c{i}"
        objects[cid] = {"type": "card", "label": c.id, "domain": c.domain}
        names.add(c.id)
        try:
            prm = ", ".join(c.parsed.params()) or "-"
        except Exception:
            prm = "?"
        rows.append(f"{cid} | {c.id} | view={c.view} | domain={c.domain} | params: {prm} | {c.syntax}")
    nodes = []
    for n in sorted(env.kb.nodes.values(), key=lambda x: x.id):
        if n.domain in domains:
            names.add(n.id)
            nodes.append(f"{n.id} | {n.type} | key={','.join(n.key) or '-'} | {(n.semantic or {}).get('en', '')[:80]}")
    vars_ = {
        "family": fam,
        "cards": "\n".join(rows),
        "schema": "\n".join(nodes),
        "lang": _lang(env),
    }
    names |= tokens(*(c.syntax for c in cards))
    facts = {"objects": objects, "numbers": {"cards": len(cards)}, "lines": {}, "names": sorted(names)[:MAX_NAMES]}
    return Context(vars_, facts, f"mapping:{fam}", None)


def _kb_errors(kb: KnowledgeBase) -> set[tuple[str, str]]:
    from lmesh.core.kb.validate import validate

    return {(i.code, i.message) for i in validate(kb) if i.level == "error"}


def translate_regression(
    root: Path, kb: KnowledgeBase, family: str, budget: float = TRANSLATE_BUDGET
) -> dict[str, Any]:
    """该平台族作为源或目标的翻译用例（knowledge/samples/translate/manifest.yaml）：每个用例译文的未识别行数与
    没有解释的差异数。超出时间预算的用例跳过（skipped）。"""
    from lmesh.core import compare, translate
    from lmesh.core.kb import read_yaml

    base = root / "samples" / "translate"
    mf = base / "manifest.yaml"
    out: dict[str, Any] = {"cases": {}, "skipped": []}
    if not mf.is_file():
        return out
    t0 = time.monotonic()
    for case in (read_yaml(mf) or {}).get("cases") or []:
        fams = {kb.profiles[p].family for p in (case.get("src_profile"), case.get("dst_profile")) if p in kb.profiles}
        if family not in fams:
            continue
        if time.monotonic() - t0 > budget:
            out["skipped"].append(case["id"])
            continue
        try:
            src = (base / case["src"]).read_text(encoding="utf-8")
            m = case.get("interface_map")
            ifmap = (
                {str(k): str(v) for k, v in m.items()}
                if isinstance(m, dict)
                else (compare.load_interface_map(base / str(m)) if m else None)
            )
            r = translate.translate_text(src, kb, case["dst_profile"], case["src_profile"], ifmap, device=case["id"])
            unk = analysis.parse_text(r["text"], kb, case["dst_profile"]).parsed.counts().get("unknown", 0)
            out["cases"][case["id"]] = {"unexplained": int(r["verify"].get("unexplained") or 0), "unknown": int(unk)}
        except Exception as e:
            out["cases"][case["id"]] = {"error": type(e).__name__}
    return out


def _map_check(d: dict[str, Any], facts: dict[str, Any], env: Env) -> list[dict[str, Any]]:
    from lmesh.core.kb import mapping

    c, p = _content(d), _payload(d)
    if str(c.get("review_kind") or "") != "card_maps":
        return [reason("bad_review_kind", ref=str(c.get("review_kind")))]
    objs = facts.get("objects") or {}
    ref = objs.get(str(p.get("card") or ""))
    if not ref or ref.get("type") != "card":
        return [reason("ref_not_found", ref=str(p.get("card") or ""))]
    cid = str(ref["label"])
    if str(c.get("target") or "") != cid:
        return [reason("card_target_mismatch", ref=str(c.get("target") or ""))]
    card = env.kb.cards.get(cid)
    if card is None:
        return [reason("ref_not_found", ref=cid)]
    maps = p.get("maps")
    if not isinstance(maps, dict) or not maps:
        return [reason("maps_empty")]
    out: list[dict[str, Any]] = []
    have = set(card.parsed.params())
    for tgt, expr in maps.items():
        if mapping.is_directive(str(tgt)):
            continue
        try:
            targets = mapping.parse_target(str(tgt))
        except Exception:
            out.append(reason("maps_bad_target", ref=str(tgt)))
            continue
        for t in targets:
            if t.node not in env.kb.nodes:
                out.append(reason("maps_unknown_node", ref=t.node))
        need = mapping.params_in_expr(expr) - {"auto"}
        if need and not (need & have):
            out.append(reason("maps_bad_param", ref=f"{tgt}: {expr}"))
    if out:
        return out
    card2 = dataclasses.replace(
        card, maps={str(k): (dict(v) if isinstance(v, dict) else str(v)) for k, v in maps.items()}
    )
    kb2 = _with_cards(env.kb, {cid: card2})
    checks: dict[str, str] = {}
    new_err = sorted(_kb_errors(kb2) - _before("kb", env.kb, "", lambda: _kb_errors(env.kb)))
    checks["kb"] = "fail" if new_err else "pass"
    if new_err:
        out.append(reason("maps_kb_invalid", detail="; ".join(m for _, m in new_err[:3])[:300]))
    root = _root(env)
    fam = card.family
    bad = _regressed(
        _before("samples", env.kb, fam, lambda: _sample_regression(root, env.kb, fam)),
        _sample_regression(root, kb2, fam),
    )
    checks["roundtrip"] = "fail" if bad else "pass"
    if bad:
        out.append(reason("breaks_samples", detail=", ".join(bad[:5])))
    if not out:  # 前两项通过才跑翻译回归（较慢）
        before = _before("translate", env.kb, fam, lambda: translate_regression(root, env.kb, fam, 600.0))
        after = translate_regression(root, kb2, card.family, TRANSLATE_BUDGET)
        worse = [
            k
            for k, v in after["cases"].items()
            if k in before["cases"]
            and (
                "error" in v
                and "error" not in before["cases"][k]
                or any(v.get(x, 0) > before["cases"][k].get(x, 0) for x in ("unexplained", "unknown"))
            )
        ]
        checks["translate"] = "fail" if worse else ("skip" if after["skipped"] or not after["cases"] else "pass")
        if worse:
            out.append(reason("translate_regressed", detail=", ".join(worse[:5])))
        elif after["skipped"]:
            out.append(reason("translate_skipped", "warn", detail=", ".join(after["skipped"][:5])))
    env.out["result"] = {"checks": checks}
    return out


register_skill(
    SkillSpec(
        id="mapping-suggest",
        build=_map_build,
        categories=("kb_review",),
        default_category="kb_review",
        scope="project",
        prepare=_map_prepare,
        check=_map_check,
    )
)


@review.register_action("card_maps")
def _approve_card_maps(kb_root: Path, item: ReviewItem, edited: dict[str, Any] | None) -> None:
    """映射建议：把 maps 写进命令卡并标 maps_manual（重新套用映射规则时不覆盖）。审核时可以改（edited.maps）。"""
    from lmesh.core.kb import files as kbfiles

    payload = item.payload or {}
    maps = (edited or {}).get("maps") or payload.get("maps")
    if not isinstance(maps, dict) or not maps:
        raise review.ReviewError("review.maps_invalid")
    found = kbfiles.find_card(kb_root, str(item.target))
    if found is None:
        raise review.ReviewError("review.card_missing")
    path, doc, idx = found
    doc["cards"][idx]["maps"] = {str(k): v for k, v in maps.items()}
    doc["cards"][idx]["maps_manual"] = True
    kbfiles.dump_rt(path, doc)


# ================================================================ 报告摘要（另一个模块，导入即注册）

from lmesh.core import ai_report_summary  # noqa: E402,F401
