"""内置 AI skill（REQ-033）：内置 AI 的每项能力 = 一个 skill（提示词、提示模板、示例、工具、输出格式、代码校验）。

存放（D-0147）：
    内置定义   knowledge/ai-skills/<编号>.yaml（只读，随版本发布）
    管理员版本 data/ai-skills/<编号>/versions/0001.yaml …（每次保存一个版本，只存可编辑的字段与保存信息）
    生效状态   data/ai-skills/<编号>/state.yaml：active（builtin 或版本号）、enabled（启用开关，覆盖定义中的 enabled）
回滚 = 把生效版本指向任一历史版本；恢复内置 = 指向 builtin；版本文件不删除。

提示词中的 {变量} 由代码填入（只替换定义里登记过的变量名，其余花括号原样保留），{{ 与 }} 表示字面的花括号；
示例（few-shot）不为空时附在系统提示词之后，为空时提示词与内置文字完全相同。
调用记录、反馈、回归集与候选示例在数据库中（表 skill_runs、skill_cases、skill_evolutions），记录的内容一律先脱敏，
按 ai.skill_log_days 天清理（D-0149）；进化见 core/skill_runners.py，AI 提出的候选版本要管理员批准才发布（D-0148）。
"""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select

from lmesh import paths
from lmesh.core import ai, config, store
from lmesh.core.store.models import SkillCase, SkillEvolution, SkillRun, iso, utcnow

_log = logging.getLogger("lmesh.skills")
DIR_NAME = "ai-skills"
ORDER = ("card-extract", "ask-query", "ask-answer", "config-generate", "script-review", "skill-evolve")
EDITABLE = ("system", "prompt", "templates", "examples", "tools", "output")
TEXT_FIELDS = ("system", "prompt")
STATUSES = ("passed", "corrected", "rejected", "unverifiable", "error")
LIVE_SOURCES = ("ask", "generate", "ingest", "script_check")  # 计入统计的来源；test / regression / evolve 不计
SCORES = {"passed": 1.0, "unverifiable": 0.5, "corrected": 0.0, "rejected": 0.0, "error": 0.0}
OUTPUT_FORMATS = ("json", "text", "config")
MAX_TEXT = 50000
MAX_EXAMPLES = 20
MAX_CASES = 200  # 每个 skill 回归集与候选示例各自的上限（超出时不再自动加入）


def _t(zh: str, en: str, pt: str) -> dict[str, str]:
    return {"zh-CN": zh, "en": en, "pt-BR": pt}


TOOLS = {
    "gquery": _t("图查询（只读）", "Graph query (read only)", "Consulta ao grafo (somente leitura)"),
    "schema": _t("Schema 目录", "Schema catalogue", "Catálogo do Schema"),
    "guard": _t("配置护栏", "Config guardrail", "Barreira de configuração"),
    "rules": _t("检查规则", "Check rules", "Regras de verificação"),
    "syntax": _t("命令语法解析", "Command syntax parser", "Analisador de sintaxe"),
    "sanitize": _t("脱敏", "Sanitiser", "Anonimizador"),
}
CHECKS = {
    "syntax.parse": _t(
        "回复必须能被命令语法解析器解析", "The reply must parse as command syntax", "A resposta deve ser sintaxe válida"
    ),
    "gquery.validate": _t(
        "查询的语法、对象类型、字段路径与设备名都合法",
        "Query syntax, object type, field paths and device names are valid",
        "Sintaxe, tipo de objeto, campos e dispositivos da consulta são válidos",
    ),
    "answer.facts": _t(
        "每句话引用的行、字段与取值和查询结果一致",
        "Every statement's rows, fields and values match the query result",
        "Linhas, campos e valores de cada frase conferem com o resultado",
    ),
    "guard": _t(
        "配置通过护栏：解析、入图、依赖、冲突",
        "The configuration passes the guardrail: parse, graph, dependencies, conflicts",
        "A configuração passa pela barreira: análise, grafo, dependências, conflitos",
    ),
    "review.verify": _t(
        "发现的规则、行、入图、适用对象、代码断言与证据都经代码确认",
        "Each finding's rule, line, graph node, target, code assertion and evidence are confirmed by code",
        "Regra, linha, nó, alvo, asserção e evidência de cada achado são confirmados pelo código",
    ),
    "evolve.placeholders": _t(
        "候选版本保留全部变量，回复是规定的 JSON",
        "The candidate keeps every placeholder and the reply is the required JSON",
        "O candidato mantém todas as variáveis e a resposta é o JSON exigido",
    ),
}
_ID = re.compile(r"^[a-z][a-z0-9-]{1,59}$")
_VAR = re.compile(r"\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}")
_LOCK = threading.RLock()


class SkillError(ValueError):
    def __init__(self, key: str, kind: str = "param", data: Any = None, **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.data, self.fmt = key, kind, data, fmt


@dataclass
class Skill:
    id: str
    title: dict[str, str]
    description: dict[str, str]
    task: str
    used_by: str
    enabled: bool
    builtin_version: int
    system: str
    prompt: str
    templates: dict[str, str] = field(default_factory=dict)
    variables: list[dict[str, Any]] = field(default_factory=list)
    examples: list[dict[str, str]] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    output: dict[str, str] = field(default_factory=dict)
    checks: list[str] = field(default_factory=list)
    samples: list[dict[str, Any]] = field(default_factory=list)
    active: str = "builtin"  # 生效版本：builtin 或版本号（文本）

    def definition(self) -> dict[str, Any]:
        """可编辑的部分（保存、对比、进化都用它）。"""
        return {
            "system": self.system,
            "prompt": self.prompt,
            "templates": dict(self.templates),
            "examples": [dict(x) for x in self.examples],
            "tools": list(self.tools),
            "output": dict(self.output),
        }

    def with_definition(self, d: dict[str, Any], active: str | None = None) -> Skill:
        s = copy.deepcopy(self)
        for k in EDITABLE:
            if k in d:
                setattr(s, k, copy.deepcopy(d[k]))
        if active is not None:
            s.active = active
        return s

    def model_key(self) -> str | None:
        return ai.TASK_MODEL_KEYS.get(self.task)

    # ------------------------------------------------------------ 提示词

    def system_text(self, **values: Any) -> str:
        text = render(self.system, values)
        if self.examples:
            text += "\n\n" + examples_block(self.examples)
        return text

    def prompt_text(self, name: str = "prompt", **values: Any) -> str:
        tpl = self.prompt if name == "prompt" else self.templates.get(name, "")
        return render(tpl, values)


def render(template: str, values: dict[str, Any]) -> str:
    """{变量} 换成取值（只换给出的变量；取值中的花括号不再展开），{{ / }} 换成字面的花括号。"""

    def sub(m: re.Match[str]) -> str:
        tok = m.group(0)
        if tok == "{{":
            return "{"
        if tok == "}}":
            return "}"
        name = m.group(1)
        return str(values[name]) if name in values else tok

    return _VAR.sub(sub, template)


def placeholders(template: str) -> set[str]:
    return {m.group(1) for m in _VAR.finditer(template) if m.group(1)}


def examples_block(examples: list[dict[str, str]]) -> str:
    parts = ["Examples:"]
    for x in examples:
        item = f"Input:\n{x.get('input', '')}\nOutput:\n{x.get('output', '')}"
        if x.get("note"):
            item = f"Note: {x['note']}\n" + item
        parts.append(item)
    return "\n\n".join(parts)


# ---------------------------------------------------------------- 文件


def builtin_dir() -> Path:
    return paths.builtin_knowledge_dir() / DIR_NAME


def user_dir() -> Path:
    return paths.data_dir() / DIR_NAME


_parsed: dict[str, tuple[float, Skill]] = {}


def _texts(v: Any) -> dict[str, str]:
    if isinstance(v, dict):
        return {k: str(v.get(k) or "") for k in ("zh-CN", "en", "pt-BR")}
    return {k: str(v or "") for k in ("zh-CN", "en", "pt-BR")}


def _plain(v: Any) -> Any:
    """ruamel 读出的对象转成普通 dict / list / str。"""
    return json.loads(json.dumps(v, ensure_ascii=False, default=str))


def _parse_builtin(path: Path) -> Skill:
    from ruamel.yaml import YAML

    data = _plain(YAML(typ="safe", pure=True).load(path.read_text(encoding="utf-8")))
    if not isinstance(data, dict) or data.get("id") != path.stem:
        raise SkillError("skills.bad_file", "invalid", file=path.name)
    return Skill(
        id=data["id"],
        title=_texts(data.get("title")),
        description=_texts(data.get("description")),
        task=str(data.get("task") or data["id"]),
        used_by=str(data.get("used_by") or ""),
        enabled=bool(data.get("enabled", True)),
        builtin_version=int(data.get("version") or 1),
        system=str(data.get("system") or ""),
        prompt=str(data.get("prompt") or ""),
        templates={str(k): str(v) for k, v in (data.get("templates") or {}).items()},
        variables=list(data.get("variables") or []),
        examples=list(data.get("examples") or []),
        tools=[str(x) for x in data.get("tools") or []],
        output={str(k): str(v) for k, v in (data.get("output") or {}).items()},
        checks=[str(x) for x in data.get("checks") or []],
        samples=list(data.get("samples") or []),
    )


def list_ids() -> list[str]:
    d = builtin_dir()
    ids = [f.stem for f in d.glob("*.yaml")] if d.is_dir() else []
    return sorted(ids, key=lambda x: (ORDER.index(x) if x in ORDER else len(ORDER), x))


def builtin(sid: str) -> Skill:
    if not _ID.match(sid):
        raise SkillError("skills.not_found", "not_found", id=sid)
    path = builtin_dir() / f"{sid}.yaml"
    if not path.is_file():
        raise SkillError("skills.not_found", "not_found", id=sid)
    mt = path.stat().st_mtime
    with _LOCK:
        hit = _parsed.get(str(path))
        if hit is None or hit[0] != mt:
            hit = (mt, _parse_builtin(path))
            _parsed[str(path)] = hit
    return copy.deepcopy(hit[1])


def _skill_dir(sid: str) -> Path:
    return user_dir() / sid


def _read_yaml(path: Path) -> Any:
    from lmesh.core.kb.files import load_rt

    return _plain(load_rt(path)) if path.is_file() else None


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    from ruamel.yaml.scalarstring import LiteralScalarString

    from lmesh.core.kb.files import dump_rt

    def lit(v: Any) -> Any:
        if isinstance(v, str) and "\n" in v:
            return LiteralScalarString(v)
        if isinstance(v, dict):
            return {k: lit(x) for k, x in v.items()}
        if isinstance(v, list):
            return [lit(x) for x in v]
        return v

    dump_rt(path, lit(data))


def state(sid: str) -> dict[str, Any]:
    st = _read_yaml(_skill_dir(sid) / "state.yaml") or {}
    active = st.get("active", "builtin")
    return {"active": "builtin" if active in (None, "builtin") else str(int(active)), "enabled": st.get("enabled")}


def _save_state(sid: str, **changes: Any) -> None:
    st = _read_yaml(_skill_dir(sid) / "state.yaml") or {}
    st.update(changes)
    if st.get("active") not in (None, "builtin"):
        st["active"] = int(st["active"])
    _write_yaml(_skill_dir(sid) / "state.yaml", st)


def _version_files(sid: str) -> list[Path]:
    d = _skill_dir(sid) / "versions"
    return sorted(d.glob("[0-9][0-9][0-9][0-9].yaml")) if d.is_dir() else []


def versions(sid: str) -> list[dict[str, Any]]:
    """版本历史：内置 + 管理员保存的每个版本（新的在后）。"""
    b = builtin(sid)
    st = state(sid)
    out = [
        {
            "version": "builtin",
            "label": f"builtin v{b.builtin_version}",
            "source": "builtin",
            "saved_at": None,
            "author": "",
            "note": "",
            "based_on": None,
            "active": st["active"] == "builtin",
        }
    ]
    for f in _version_files(sid):
        meta = (_read_yaml(f) or {}).get("meta") or {}
        v = str(int(f.stem))
        out.append(
            {
                "version": v,
                "label": f"v{v}",
                "source": meta.get("source", "edit"),
                "saved_at": meta.get("saved_at"),
                "author": meta.get("author", ""),
                "note": meta.get("note", ""),
                "based_on": meta.get("based_on"),
                "evolution": meta.get("evolution"),
                "active": st["active"] == v,
            }
        )
    return out


def load_version(sid: str, version: str | int) -> Skill:
    b = builtin(sid)
    v = str(version)
    if v in ("builtin", "", "0"):
        return b
    if v == "current":
        return current(sid)
    if not v.isdigit():
        raise SkillError("skills.version_not_found", "not_found", id=sid, version=v)
    path = _skill_dir(sid) / "versions" / f"{int(v):04d}.yaml"
    data = _read_yaml(path)
    if not data:
        raise SkillError("skills.version_not_found", "not_found", id=sid, version=v)
    return b.with_definition(data.get("definition") or {}, active=str(int(v)))


def current(sid: str) -> Skill:
    """当前生效的版本（启用开关以 state.yaml 为准）。生效的版本文件丢失时退回内置版本。"""
    st = state(sid)
    try:
        s = load_version(sid, st["active"])
    except SkillError as e:
        if e.key != "skills.version_not_found":
            raise
        _log.warning("skill %s 的生效版本 %s 不存在，使用内置版本", sid, st["active"])
        s = builtin(sid)
    if st["enabled"] is not None:
        s.enabled = bool(st["enabled"])
    return s


def require_enabled(sid: str) -> Skill:
    s = current(sid)
    if not s.enabled:
        raise SkillError("skills.disabled", "state", data={"status": "skill_disabled", "skill": sid}, id=sid)
    return s


# ---------------------------------------------------------------- 校验与保存


def validate(base: Skill, d: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """校验可编辑的字段，返回 (规范化后的定义, 提醒)。不合格时抛出 SkillError（kind=invalid，data.issues）。"""
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    out = base.definition()
    for k in EDITABLE:
        if k in d and d[k] is not None:
            out[k] = copy.deepcopy(d[k])
    known = {str(v.get("name")) for v in base.variables}
    for k in TEXT_FIELDS:
        v = out.get(k)
        if not isinstance(v, str) or not v.strip():
            issues.append({"field": k, "key": "skills.issue.empty"})
        elif len(v) > MAX_TEXT:
            issues.append({"field": k, "key": "skills.issue.too_long", "params": {"max": MAX_TEXT}})
    if not isinstance(out.get("templates"), dict):
        issues.append({"field": "templates", "key": "skills.issue.type"})
        out["templates"] = base.definition()["templates"]
    else:
        out["templates"] = {str(k): str(v) for k, v in out["templates"].items()}
        extra = sorted(set(out["templates"]) - set(base.templates))
        missing = sorted(set(base.templates) - set(out["templates"]))
        for name in extra:
            issues.append(
                {"field": f"templates.{name}", "key": "skills.issue.template_unknown", "params": {"name": name}}
            )
        for name in missing:
            issues.append(
                {"field": f"templates.{name}", "key": "skills.issue.template_missing", "params": {"name": name}}
            )
    texts = {"system": out.get("system") or "", "prompt": out.get("prompt") or ""}
    texts.update({f"templates.{k}": v for k, v in out["templates"].items()})
    base_texts = {"system": base.system, "prompt": base.prompt}
    base_texts.update({f"templates.{k}": v for k, v in base.templates.items()})
    for where, text in texts.items():
        if not isinstance(text, str):
            continue
        for name in sorted(placeholders(text) - known):
            issues.append({"field": where, "key": "skills.issue.unknown_var", "params": {"name": name}})
        for name in sorted(placeholders(base_texts.get(where, "")) - placeholders(text)):
            warnings.append({"field": where, "key": "skills.warn.var_dropped", "params": {"name": name}})
    ex = out.get("examples")
    if not isinstance(ex, list):
        issues.append({"field": "examples", "key": "skills.issue.type"})
        out["examples"] = []
    else:
        if len(ex) > MAX_EXAMPLES:
            issues.append({"field": "examples", "key": "skills.issue.too_many", "params": {"max": MAX_EXAMPLES}})
        clean = []
        for i, x in enumerate(ex):
            if (
                not isinstance(x, dict)
                or not str(x.get("input") or "").strip()
                or not str(x.get("output") or "").strip()
            ):
                issues.append({"field": f"examples.{i}", "key": "skills.issue.example"})
                continue
            item = {"input": str(x["input"]), "output": str(x["output"])}
            if str(x.get("note") or "").strip():
                item["note"] = str(x["note"]).strip()
            clean.append(item)
        out["examples"] = clean
    tools = out.get("tools")
    if not isinstance(tools, list) or any(str(t) not in TOOLS for t in tools):
        issues.append({"field": "tools", "key": "skills.issue.tools", "params": {"choices": ", ".join(TOOLS)}})
        out["tools"] = list(base.tools)
    else:
        out["tools"] = list(dict.fromkeys(str(t) for t in tools))
    o = out.get("output")
    if not isinstance(o, dict) or str(o.get("format") or "") not in OUTPUT_FORMATS:
        issues.append(
            {"field": "output", "key": "skills.issue.output", "params": {"choices": ", ".join(OUTPUT_FORMATS)}}
        )
        out["output"] = dict(base.output)
    else:
        out["output"] = {"format": str(o["format"]), "schema": str(o.get("schema") or "")}
    if issues:
        raise SkillError("skills.invalid", "invalid", data={"issues": issues, "warnings": warnings}, n=len(issues))
    return out, warnings


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def save(
    sid: str,
    d: dict[str, Any],
    author: str = "",
    note: str = "",
    source: str = "edit",
    evolution: int | None = None,
    activate: bool = True,
) -> dict[str, Any]:
    """校验后保存为新版本（并设为生效）。内容与生效版本完全相同时不新建版本，返回 unchanged。"""
    base = current(sid)
    clean, warnings = validate(builtin(sid), {**base.definition(), **d})
    if clean == base.definition() and source == "edit":
        return {"version": base.active, "unchanged": True, "warnings": warnings}
    with _LOCK:
        files = _version_files(sid)
        n = int(files[-1].stem) + 1 if files else 1
        meta: dict[str, Any] = {
            "version": n,
            "saved_at": _now(),
            "author": author,
            "source": source,
            "note": note.strip()[:2000],
            "based_on": base.active,
        }
        if evolution is not None:
            meta["evolution"] = evolution
        _write_yaml(_skill_dir(sid) / "versions" / f"{n:04d}.yaml", {"meta": meta, "definition": clean})
        if activate:
            _save_state(sid, active=n)
    _log.info("skill %s 保存为版本 %s（%s，%s）", sid, n, source, author or "-")
    return {"version": str(n), "unchanged": False, "warnings": warnings}


def rollback(sid: str, version: str | int, author: str = "") -> dict[str, Any]:
    s = load_version(sid, version)  # 不存在时抛出
    _save_state(sid, active=s.active)
    _log.info("skill %s 回滚到 %s（%s）", sid, s.active, author or "-")
    return {"active": s.active}


def restore(sid: str, author: str = "") -> dict[str, Any]:
    builtin(sid)
    _save_state(sid, active="builtin")
    _log.info("skill %s 恢复为内置版本（%s）", sid, author or "-")
    return {"active": "builtin"}


def set_enabled(sid: str, enabled: bool, author: str = "") -> dict[str, Any]:
    builtin(sid)
    _save_state(sid, enabled=bool(enabled))
    _log.info("skill %s %s（%s）", sid, "启用" if enabled else "停用", author or "-")
    return {"enabled": bool(enabled)}


def _line_diff(a: str, b: str) -> list[dict[str, Any]]:
    al, bl = a.split("\n"), b.split("\n")
    rows: list[dict[str, Any]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=al, b=bl, autojunk=False).get_opcodes():
        if op == "equal":
            rows += [{"op": "same", "a": i1 + k + 1, "b": j1 + k + 1, "text": al[i1 + k]} for k in range(i2 - i1)]
            continue
        rows += [{"op": "del", "a": i + 1, "b": None, "text": al[i]} for i in range(i1, i2)]
        rows += [{"op": "add", "a": None, "b": j + 1, "text": bl[j]} for j in range(j1, j2)]
    return rows


def diff_definitions(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    """逐字段对比两个定义；文本字段给出逐行差异。"""
    out = []
    keys = ["system", "prompt", *sorted(set(a.get("templates", {})) | set(b.get("templates", {})))]
    for k in keys:
        if k in ("system", "prompt"):
            ta, tb, name = a.get(k, ""), b.get(k, ""), k
        else:
            ta, tb, name = a.get("templates", {}).get(k, ""), b.get("templates", {}).get(k, ""), f"templates.{k}"
        out.append({"field": name, "changed": ta != tb, "lines": _line_diff(ta, tb) if ta != tb else []})
    for k in ("examples", "tools", "output"):
        va, vb = a.get(k), b.get(k)
        item: dict[str, Any] = {"field": k, "changed": va != vb, "a": va, "b": vb}
        if k == "examples" and va != vb:
            ja = json.dumps(va, ensure_ascii=False, indent=2)
            jb = json.dumps(vb, ensure_ascii=False, indent=2)
            item["lines"] = _line_diff(ja, jb)
        out.append(item)
    return out


def diff(sid: str, a: str, b: str) -> dict[str, Any]:
    sa, sb = load_version(sid, a), load_version(sid, b)
    fields = diff_definitions(sa.definition(), sb.definition())
    return {
        "skill": sid,
        "a": sa.active,
        "b": sb.active,
        "fields": fields,
        "changed": sum(1 for f in fields if f["changed"]),
    }


# ---------------------------------------------------------------- 展示


def variables_of(s: Skill) -> list[dict[str, Any]]:
    return [{"name": v.get("name"), "in": v.get("in"), "desc": _texts(v.get("desc"))} for v in s.variables]


def info(s: Skill, settings: config.Settings | None = None) -> dict[str, Any]:
    st = state(s.id)
    n_versions = len(_version_files(s.id))
    key = s.model_key()
    on = settings is not None and ai.is_configured(settings)
    return {
        "id": s.id,
        "title": s.title,
        "description": s.description,
        "task": s.task,
        "used_by": s.used_by,
        "model_key": key,
        "model": ai.model_for(settings, s.task) if on and settings is not None else None,
        "enabled": s.enabled,
        "active": st["active"],
        "builtin_version": s.builtin_version,
        "versions": n_versions,
        "modified": st["active"] != "builtin",
        "tools": s.tools,
        "checks": s.checks,
        "examples": len(s.examples),
    }


def detail(sid: str, settings: config.Settings | None = None) -> dict[str, Any]:
    s = current(sid)
    b = builtin(sid)
    return {
        **info(s, settings),
        "definition": s.definition(),
        "builtin": b.definition(),
        "variables": variables_of(b),
        "samples": [
            {"index": i, "title": _texts(x.get("title")), "input": x.get("input") or {}, "reply": x.get("reply") or ""}
            for i, x in enumerate(b.samples)
        ],
        "tool_choices": [{"id": k, "title": v} for k, v in TOOLS.items()],
        "check_titles": {k: CHECKS.get(k, _t(k, k, k)) for k in b.checks},
        "output_formats": list(OUTPUT_FORMATS),
    }


# ---------------------------------------------------------------- 调用记录（数据库）


def _sanitize(v: Any) -> Any:
    from lmesh.core.ask import sanitize_text

    if isinstance(v, str):
        return sanitize_text(v) if v.strip() else v
    if isinstance(v, dict):
        return {k: _sanitize(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_sanitize(x) for x in v]
    return v


def input_hash(skill: str, data: Any) -> str:
    return hashlib.sha256((skill + "\n" + json.dumps(data, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()


_last_cleanup: dict[str, float] = {}


def cleanup(db_url: str, days: int, force: bool = False) -> int:
    """删除超过保留天数的调用记录（回归集与候选示例保存了自己的副本，不受影响）。每个数据库每小时最多做一次。"""
    now = time.monotonic()
    if not force and now - _last_cleanup.get(db_url, -1e9) < 3600:
        return 0
    _last_cleanup[db_url] = now
    cutoff = utcnow() - timedelta(days=max(1, int(days)))
    with store.session(db_url) as s:
        res = s.execute(delete(SkillRun).where(SkillRun.created_at < cutoff))
        n = int(getattr(res, "rowcount", 0) or 0)
    if n:
        _log.info("清理了 %s 条超过 %s 天的 skill 调用记录", n, days)
    return n


@dataclass
class Actor:
    """调用者：网页账号（user_id）或令牌 / 命令行（user_id 为空）。"""

    user_id: int | None = None
    name: str = ""


def log_run(
    settings: config.Settings,
    skill: Skill,
    source: str,
    status: str,
    input: dict[str, Any],
    reply: str,
    detail: dict[str, Any] | None = None,
    ai_info: dict[str, Any] | None = None,
    actor: Actor | None = None,
) -> int | None:
    """记录一次调用（内容先脱敏）；被拦截 / 被更正的线上调用自动进入回归集。记录失败不影响调用结果，返回 None。"""
    try:
        url = settings.database_url
        store.upgrade(url)
        info_ = ai_info or {}
        row = SkillRun(
            skill=skill.id,
            version=skill.active,
            task=skill.task,
            source=source,
            status=status if status in STATUSES else "error",
            user_id=actor.user_id if actor else None,
            actor=(actor.name if actor else "")[:200],
            input=_sanitize(input),
            reply=_sanitize(reply or "")[:200000],
            detail=detail or {},
            model=str(info_.get("model") or "")[:120],
            tokens_in=int(info_.get("tokens_in") or 0),
            tokens_out=int(info_.get("tokens_out") or 0),
            ms=int(info_.get("ms") or 0),
        )
        with store.session(url) as s:
            s.add(row)
            s.flush()
            run_id = int(row.id)
        if source in LIVE_SOURCES and row.status in ("rejected", "corrected"):
            _add_case(url, skill.id, "regression", row.status, run_id, row.input, row.reply, row.detail, "", "system")
        cleanup(url, int(settings.get("ai.skill_log_days") or 90))
        return run_id
    except Exception:  # 记录失败不影响业务结果
        _log.warning("skill 调用记录写入失败（%s）", skill.id, exc_info=True)
        return None


def _run_dict(r: SkillRun, full: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": r.id,
        "skill": r.skill,
        "version": r.version,
        "source": r.source,
        "status": r.status,
        "actor": r.actor,
        "model": r.model,
        "tokens_in": r.tokens_in,
        "tokens_out": r.tokens_out,
        "ms": r.ms,
        "rating": r.rating,
        "correction": r.correction,
        "feedback_by": r.feedback_by,
        "feedback_at": iso(r.feedback_at),
        "created_at": iso(r.created_at),
        "summary": (r.detail or {}).get("summary"),
    }
    if full:
        d.update(input=r.input, reply=r.reply, detail=r.detail)
    return d


def get_run(db_url: str, run_id: int) -> dict[str, Any]:
    with store.session(db_url) as s:
        r = s.get(SkillRun, run_id)
        if r is None:
            raise SkillError("skills.run_not_found", "not_found", id=run_id)
        return _run_dict(r, full=True)


def runs(
    db_url: str, sid: str, limit: int = 50, status: str | None = None, source: str | None = None
) -> list[dict[str, Any]]:
    with store.session(db_url) as s:
        q = select(SkillRun).where(SkillRun.skill == sid)
        if status:
            q = q.where(SkillRun.status == status)
        if source:
            q = q.where(SkillRun.source == source)
        return [_run_dict(r) for r in s.scalars(q.order_by(SkillRun.id.desc()).limit(max(1, min(limit, 500))))]


def _empty_counts() -> dict[str, int]:
    return {"calls": 0, **{k: 0 for k in STATUSES}, "up": 0, "down": 0, "corrections": 0}


def _rates(c: dict[str, Any]) -> dict[str, Any]:
    n = c["calls"]
    c["pass_rate"] = round(c["passed"] / n, 4) if n else None
    c["reject_rate"] = round(c["rejected"] / n, 4) if n else None
    return c


def stats(db_url: str, days: int = 30, sid: str | None = None) -> dict[str, dict[str, Any]]:
    """每个 skill 近 days 天的线上调用统计（不含试运行与回归运行）。"""
    since = utcnow() - timedelta(days=max(1, days))
    out: dict[str, dict[str, Any]] = {}
    with store.session(db_url) as s:
        q = (
            select(
                SkillRun.skill,
                SkillRun.status,
                SkillRun.rating,
                func.count(),
                func.sum(func.length(SkillRun.correction)),
            )
            .where(SkillRun.created_at >= since, SkillRun.source.in_(LIVE_SOURCES))
            .group_by(SkillRun.skill, SkillRun.status, SkillRun.rating)
        )
        if sid:
            q = q.where(SkillRun.skill == sid)
        for skill, st, rating, n, _ in s.execute(q):
            c = out.setdefault(skill, _empty_counts())
            c["calls"] += n
            c[st if st in STATUSES else "error"] += n
            if rating in ("up", "down"):
                c[rating] += n
        qc = (
            select(SkillRun.skill, func.count())
            .where(SkillRun.created_at >= since, SkillRun.source.in_(LIVE_SOURCES), SkillRun.correction != "")
            .group_by(SkillRun.skill)
        )
        if sid:
            qc = qc.where(SkillRun.skill == sid)
        for skill, n in s.execute(qc):
            out.setdefault(skill, _empty_counts())["corrections"] = n
        qk = select(SkillCase.skill, SkillCase.kind, func.count()).group_by(SkillCase.skill, SkillCase.kind)
        qe = (
            select(SkillEvolution.skill, func.count())
            .where(SkillEvolution.status == "pending")
            .group_by(SkillEvolution.skill)
        )
        cases = {(a, b): n for a, b, n in s.execute(qk)}
        pend = {k: n for k, n in s.execute(qe)}
    ids = [sid] if sid else list_ids()
    res = {}
    for i in ids:
        c = _rates(out.get(i, _empty_counts()))
        c["regression_cases"] = cases.get((i, "regression"), 0)
        c["candidates"] = cases.get((i, "candidate"), 0)
        c["pending_evolutions"] = int(pend.get(i, 0))
        c["days"] = days
        res[i] = c
    return res


def daily(db_url: str, sid: str, days: int = 30) -> list[dict[str, Any]]:
    since = (utcnow() - timedelta(days=max(1, days) - 1)).date()
    rows: dict[str, dict[str, Any]] = {}
    for k in range(max(1, days)):
        d = (since + timedelta(days=k)).isoformat()
        rows[d] = {"date": d, **_empty_counts()}
    with store.session(db_url) as s:
        q = select(SkillRun.created_at, SkillRun.status, SkillRun.rating).where(
            SkillRun.skill == sid,
            SkillRun.source.in_(LIVE_SOURCES),
            SkillRun.created_at >= datetime.combine(since, datetime.min.time(), UTC),
        )
        for created, st, rating in s.execute(q):
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            r = rows.get(created.date().isoformat())
            if r is None:
                continue
            r["calls"] += 1
            r[st if st in STATUSES else "error"] += 1
            if rating in ("up", "down"):
                r[rating] += 1
    return list(rows.values())


def stats_detail(db_url: str, sid: str, days: int = 30) -> dict[str, Any]:
    builtin(sid)
    return {
        "skill": sid,
        "days": days,
        "totals": stats(db_url, days, sid)[sid],
        "daily": daily(db_url, sid, days),
        "runs": runs(db_url, sid, 50),
        "by_version": _by_version(db_url, sid, days),
    }


def _by_version(db_url: str, sid: str, days: int) -> list[dict[str, Any]]:
    since = utcnow() - timedelta(days=max(1, days))
    out: dict[str, dict[str, Any]] = {}
    with store.session(db_url) as s:
        q = (
            select(SkillRun.version, SkillRun.status, func.count())
            .where(SkillRun.skill == sid, SkillRun.created_at >= since, SkillRun.source.in_(LIVE_SOURCES))
            .group_by(SkillRun.version, SkillRun.status)
        )
        for v, st, n in s.execute(q):
            c = out.setdefault(v, {"version": v, **_empty_counts()})
            c["calls"] += n
            c[st if st in STATUSES else "error"] += n
    return [_rates(c) for c in out.values()]


# ---------------------------------------------------------------- 反馈、回归集与候选示例


def feedback(
    db_url: str,
    run_id: int,
    rating: str | None,
    correction: str = "",
    actor: Actor | None = None,
    is_admin: bool = True,
) -> dict[str, Any]:
    """用户反馈：点赞 / 点踩 / 更正（rating 为 None 且没有更正时撤销评价）。
    点踩或更正 → 进入回归集；校验通过且点赞 → 成为候选示例。普通账号只能评价自己发起的调用。"""
    if rating not in (None, "up", "down"):
        raise SkillError("skills.bad_rating", rating=str(rating))
    correction = _sanitize((correction or "").strip())[:20000]
    who = actor.name if actor else ""
    with store.session(db_url) as s:
        r = s.get(SkillRun, run_id)
        if r is None:
            raise SkillError("skills.run_not_found", "not_found", id=run_id)
        if not is_admin and r.user_id is not None and (actor is None or actor.user_id != r.user_id):
            raise SkillError("skills.run_not_found", "not_found", id=run_id)
        r.rating, r.correction = rating, correction
        r.feedback_by, r.feedback_at = who[:200], utcnow()
        skill, status, inp, reply, det = r.skill, r.status, r.input, r.reply, r.detail
    case = None
    if correction or rating == "down":
        reason = "correction" if correction else "down"
        case = _add_case(db_url, skill, "regression", reason, run_id, inp, reply, det, correction, who)
    elif rating == "up" and status == "passed":
        case = _add_case(db_url, skill, "candidate", "up", run_id, inp, reply, det, "", who)
    _log.info("skill %s 调用 %s 收到反馈：%s%s", skill, run_id, rating or "-", "（更正）" if correction else "")
    return {"run_id": run_id, "skill": skill, "rating": rating, "correction": correction, "case": case}


def _case_dict(c: SkillCase) -> dict[str, Any]:
    return {
        "id": c.id,
        "skill": c.skill,
        "kind": c.kind,
        "reason": c.reason,
        "run_id": c.run_id,
        "input": c.input,
        "reply": c.reply,
        "detail": c.detail,
        "expect": c.expect,
        "note": c.note,
        "created_by": c.created_by,
        "created_at": iso(c.created_at),
    }


def _add_case(
    db_url: str,
    skill: str,
    kind: str,
    reason: str,
    run_id: int | None,
    inp: Any,
    reply: str,
    det: Any,
    expect: str,
    who: str,
) -> dict[str, Any] | None:
    h = input_hash(skill, inp)
    with store.session(db_url) as s:
        hit = s.scalars(
            select(SkillCase).where(SkillCase.skill == skill, SkillCase.kind == kind, SkillCase.input_hash == h)
        ).first()
        if hit is not None:  # 同样的输入只留一条；更正写到已有的案例上
            if expect:
                hit.expect, hit.reason = expect, reason
            return {"id": hit.id, "kind": kind, "reason": hit.reason, "existing": True}
        n = s.scalar(
            select(func.count()).select_from(SkillCase).where(SkillCase.skill == skill, SkillCase.kind == kind)
        )
        if (n or 0) >= MAX_CASES:
            return None
        c = SkillCase(
            skill=skill,
            kind=kind,
            reason=reason,
            run_id=run_id,
            input=inp,
            reply=reply or "",
            detail=det or {},
            expect=expect,
            input_hash=h,
            created_by=who[:200],
        )
        s.add(c)
        s.flush()
        return {"id": c.id, "kind": kind, "reason": reason, "existing": False}


def cases(db_url: str, sid: str, kind: str | None = None) -> dict[str, list[dict[str, Any]]]:
    builtin(sid)
    with store.session(db_url) as s:
        q = select(SkillCase).where(SkillCase.skill == sid)
        if kind:
            q = q.where(SkillCase.kind == kind)
        rows = [_case_dict(c) for c in s.scalars(q.order_by(SkillCase.id.desc()))]
    return {
        "regression": [c for c in rows if c["kind"] == "regression"],
        "candidates": [c for c in rows if c["kind"] == "candidate"],
    }


def get_case(db_url: str, sid: str, cid: int) -> dict[str, Any]:
    with store.session(db_url) as s:
        c = s.get(SkillCase, cid)
        if c is None or c.skill != sid:
            raise SkillError("skills.case_not_found", "not_found", id=cid)
        return _case_dict(c)


def add_case(
    db_url: str, sid: str, run_id: int, kind: str, actor: Actor | None = None, note: str = ""
) -> dict[str, Any]:
    if kind not in ("regression", "candidate"):
        raise SkillError("skills.bad_kind", kind=kind)
    r = get_run(db_url, run_id)
    if r["skill"] != sid:
        raise SkillError("skills.run_not_found", "not_found", id=run_id)
    res = _add_case(
        db_url,
        sid,
        kind,
        "manual",
        run_id,
        r["input"],
        r["reply"],
        r["detail"],
        r["correction"],
        actor.name if actor else "",
    )
    if res is None:
        raise SkillError("skills.cases_full", "state", max=MAX_CASES)
    if note:
        with store.session(db_url) as s:
            c = s.get(SkillCase, res["id"])
            if c is not None:
                c.note = note[:2000]
    return get_case(db_url, sid, res["id"])


def delete_case(db_url: str, sid: str, cid: int) -> None:
    with store.session(db_url) as s:
        c = s.get(SkillCase, cid)
        if c is None or c.skill != sid:
            raise SkillError("skills.case_not_found", "not_found", id=cid)
        s.delete(c)


def case_to_example(db_url: str, sid: str, cid: int, author: str = "", builder: Any = None) -> dict[str, Any]:
    """把案例（候选示例，或带更正的回归案例）加入示例，形成新版本。builder(skill, input) -> 发给 AI 的正文。"""
    c = get_case(db_url, sid, cid)
    s = current(sid)
    output = c["expect"] or c["reply"]
    if not str(output).strip():
        raise SkillError("skills.case_no_output", "state", id=cid)
    text_in = builder(s, c["input"] or {}) if builder else json.dumps(c["input"], ensure_ascii=False)
    examples = [*s.examples, {"input": text_in, "output": str(output), "note": f"case {cid}"}]
    res = save(sid, {"examples": examples}, author, note=f"case {cid}", source="example")
    return {**res, "case": cid}


# ---------------------------------------------------------------- 进化记录


def _evo_dict(e: SkillEvolution, full: bool = True) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": e.id,
        "skill": e.skill,
        "status": e.status,
        "base_version": e.base_version,
        "rationale": e.rationale,
        "created_by": e.created_by,
        "created_at": iso(e.created_at),
        "decided_by": e.decided_by,
        "decided_at": iso(e.decided_at),
        "published_version": e.published_version or None,
        "error": e.error,
        "summary": (e.scores or {}).get("summary"),
    }
    if full:
        d["candidate"] = e.candidate
        d["scores"] = e.scores
    return d


def add_evolution(db_url: str, sid: str, **fields: Any) -> dict[str, Any]:
    with store.session(db_url) as s:
        e = SkillEvolution(skill=sid, **fields)
        s.add(e)
        s.flush()
        return _evo_dict(e)


def evolutions(db_url: str, sid: str) -> list[dict[str, Any]]:
    with store.session(db_url) as s:
        rows = s.scalars(select(SkillEvolution).where(SkillEvolution.skill == sid).order_by(SkillEvolution.id.desc()))
        return [_evo_dict(e, full=False) for e in rows]


def get_evolution(db_url: str, sid: str, eid: int) -> dict[str, Any]:
    with store.session(db_url) as s:
        e = s.get(SkillEvolution, eid)
        if e is None or e.skill != sid:
            raise SkillError("skills.evolution_not_found", "not_found", id=eid)
        d = _evo_dict(e)
    if d["candidate"]:
        try:
            base = load_version(sid, d["base_version"]).definition()
        except SkillError:
            base = builtin(sid).definition()
        d["diff"] = diff_definitions(base, d["candidate"])
    return d


def decide(db_url: str, sid: str, eid: int, approve: bool, author: str = "", note: str = "") -> dict[str, Any]:
    """批准：候选版本保存为新版本并生效；放弃：只改状态。只有待批准的进化可以决定。"""
    with store.session(db_url) as s:
        e = s.get(SkillEvolution, eid)
        if e is None or e.skill != sid:
            raise SkillError("skills.evolution_not_found", "not_found", id=eid)
        if e.status != "pending":
            raise SkillError("skills.evolution_decided", "state", id=eid, status=e.status)
        candidate = e.candidate
    published = ""
    if approve:
        res = save(sid, candidate or {}, author, note or f"evolution {eid}", source="evolution", evolution=eid)
        published = res["version"]
    with store.session(db_url) as s:
        e2 = s.get(SkillEvolution, eid)
        assert e2 is not None
        e2.status = "approved" if approve else "rejected"
        e2.decided_by, e2.decided_at, e2.published_version = author[:200], utcnow(), published
    _log.info(
        "skill %s 进化 %s %s（%s）", sid, eid, "批准发布为版本 " + published if approve else "放弃", author or "-"
    )
    return get_evolution(db_url, sid, eid)
