"""翻译自定义规则（REQ-032）：规则集（名称映射、命名规范、端口映射）的模型、读写、匹配与在图上改名。

规则集是一个 YAML 文件：内置示例在 knowledge/translate-rules/（只读），用户的在 data/translate-rules/。

    id: atn-to-asr920
    title: {zh-CN: …, en: …, pt-BR: …}
    from: huawei-vrp8            # 适用的源平台族（可省）
    to: cisco-iosxe              # 适用的目标平台族（可省；命名规范的长度上限按实际目标 Profile 取）
    names:                       # 名称映射：按顺序，第一条命中生效；没有命中的保持原名
      - {type: vrf.instance, match: wildcard, from: "RAN-*", to: "VRF_{1}"}
      - {type: rp.policy, match: regex, from: "(.*)-(IN|OUT)", to: "RP_{1}_{2}", ignore_case: true}
    naming:                      # 命名规范：每种对象类型第一条启用的规则生效
      - {type: rp.policy, pattern: "RP_[A-Z0-9_]+", fix: true, case: upper, replace: [{from: "-", to: "_"}]}
    ports:                       # 端口映射：按顺序，第一条命中生效；子接口随主接口（.N 保留）
      - {match: exact, from: GigabitEthernet0/2/0, to: TenGigabitEthernet0/0/24}
      - {match: pattern, from: "GigabitEthernet0/2/{n}", to: "GigabitEthernet0/0/{n+1}", range: [1, 7]}
      - {match: type, from: 100GE, to: HundredGigE}

匹配：精确；通配符（* 任意串、? 一个字符，各自是一个捕获组）；正则（整串匹配，{1} / \\1 / {名字} 引用捕获组）；
{0} 是整个原名。正则与 pattern 都整串匹配。命名规范：自动整理依次做 替换 → 大小写 → 前缀 → 后缀 → 截断，
然后检查 pattern（整串匹配）与长度；长度上限取规则的 max_length，没写时取目标平台族 knowledge/render/<族>.yaml 的
name_limits（{对象类型: 最大长度}），都没有时不截断并在 gaps 中列出。

在图上改名（run）：复制源图，对象的键与编号、引用它的属性取值、复合键中引用它的字段一起改（依据 Schema 的 ref 类型
与图上的引用边），子树编号随之改；多个源名改成同一个新名、新名与未改名的同类对象重名、新名在目标设备上已存在时，
这一组改名都不执行，列在 conflicts 中。返回 (新图, 端口映射表, 报告)。
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from lmesh.core import compare as cmp
from lmesh.core.graph import DEVICE, Statement, _key_text, _short
from lmesh.core.kb import KnowledgeBase, read_yaml

NAME_MATCH = ("exact", "wildcard", "regex")
PORT_MATCH = ("exact", "pattern", "type")
CASES = ("keep", "upper", "lower")
ANY = "*"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_LANGS = ("zh-CN", "en", "pt-BR")
_GROUP = re.compile(r"\{(\w+)\}")
_N = re.compile(r"\{n\s*([+-]\s*\d+)?\}")
_SENTINEL = "987654321"
DIR_NAME = "translate-rules"


class RulesError(ValueError):
    """规则集错误（文案键 + 参数）；kind：param / not_found / invalid / readonly / exists。"""

    def __init__(self, key: str, kind: str = "param", issues: list[dict[str, Any]] | None = None, **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.issues, self.fmt = key, kind, issues or [], fmt


# ---------------------------------------------------------------- 模型


@dataclass
class NameRule:
    type: str = ANY
    match: str = "exact"
    src: str = ""
    to: str = ""
    ignore_case: bool = False
    enabled: bool = True
    note: str = ""
    rx: re.Pattern[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type, "match": self.match, "from": self.src, "to": self.to}
        d["ignore_case"], d["enabled"] = self.ignore_case, self.enabled
        if self.note:
            d["note"] = self.note
        return d


@dataclass
class NamingRule:
    type: str = ANY
    pattern: str = ""
    fix: bool = False
    case: str = "keep"
    prefix: str = ""
    suffix: str = ""
    replace: list[tuple[str, str]] = field(default_factory=list)
    truncate: bool = True
    max_length: int | None = None
    enabled: bool = True
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type, "pattern": self.pattern, "fix": self.fix, "case": self.case}
        d.update(prefix=self.prefix, suffix=self.suffix, replace=[{"from": a, "to": b} for a, b in self.replace])
        d.update(truncate=self.truncate, max_length=self.max_length, enabled=self.enabled)
        if self.note:
            d["note"] = self.note
        return d


@dataclass
class PortRule:
    match: str = "exact"
    src: str = ""
    to: str = ""
    range: tuple[int, int] | None = None
    speed: float | None = None
    enabled: bool = True
    note: str = ""
    rx: re.Pattern[str] | None = None
    ptype: str = ""

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"match": self.match, "from": self.src, "to": self.to}
        d.update(range=list(self.range) if self.range else None, speed=self.speed, enabled=self.enabled)
        if self.note:
            d["note"] = self.note
        return d


@dataclass
class RuleSet:
    id: str
    title: dict[str, str] = field(default_factory=dict)
    description: dict[str, str] = field(default_factory=dict)
    src_family: str = ""
    dst_family: str = ""
    names: list[NameRule] = field(default_factory=list)
    naming: list[NamingRule] = field(default_factory=list)
    ports: list[PortRule] = field(default_factory=list)
    builtin: bool = False
    file: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "from": self.src_family or None,
            "to": self.dst_family or None,
            "names": [r.as_dict() for r in self.names],
            "naming": [r.as_dict() for r in self.naming],
            "ports": [r.as_dict() for r in self.ports],
        }

    def info(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "from": self.src_family or None,
            "to": self.dst_family or None,
            "builtin": self.builtin,
            "file": self.file,
            "counts": {"names": len(self.names), "naming": len(self.naming), "ports": len(self.ports)},
        }


# ---------------------------------------------------------------- 解析与校验


def _texts(v: Any) -> dict[str, str]:
    if isinstance(v, dict):
        return {str(k): str(x) for k, x in v.items() if x is not None}
    return {lang: str(v) for lang in _LANGS} if v else {}


def _bool(v: Any, default: bool) -> bool:
    return default if v is None else bool(v)


def _wild_rx(pat: str, flags: int) -> re.Pattern[str]:
    out = "".join("(.*)" if ch == "*" else "(.)" if ch == "?" else re.escape(ch) for ch in pat)
    return re.compile(out, flags)


def _port_rx(pat: str) -> re.Pattern[str]:
    """端口模式：{n} 处是数字；接口类型按统一写法（GE0/2/{n} 与 GigabitEthernet0/2/{n} 相同）。"""
    canon = cmp.interface_name(pat.replace("{n}", _SENTINEL))
    return re.compile(re.escape(canon).replace(_SENTINEL, r"(\d+)"), re.IGNORECASE)


def _groups_used(tpl: str) -> list[str]:
    return _GROUP.findall(re.sub(r"\\(\d+)", r"{\1}", tpl))


def parse(data: Any, kb: KnowledgeBase | None = None, rid: str | None = None) -> RuleSet:
    """dict 或 YAML 文本 → RuleSet；有问题时抛 RulesError("naming.invalid", "invalid", issues)。"""
    if isinstance(data, str):
        from ruamel.yaml import YAML
        from ruamel.yaml.error import YAMLError

        try:
            data = YAML(typ="safe", pure=True).load(data)
        except YAMLError as e:
            raise RulesError(
                "naming.invalid",
                "invalid",
                [{"where": "", "key": "naming.issue.yaml", "args": {"error": str(e)[:200]}}],
            ) from e
    if not isinstance(data, dict):
        raise RulesError("naming.invalid", "invalid", [{"where": "", "key": "naming.issue.not_mapping", "args": {}}])
    issues: list[dict[str, Any]] = []

    def bad(where: str, key: str, **args: Any) -> None:
        issues.append({"where": where, "key": f"naming.issue.{key}", "args": args})

    sid = str(data.get("id") or rid or "")
    if not _ID.match(sid):
        bad("id", "id", id=sid)
    types = rename_types(kb) if kb is not None else None
    rs = RuleSet(
        id=sid,
        title=_texts(data.get("title")),
        description=_texts(data.get("description")),
        src_family=str(data.get("from") or ""),
        dst_family=str(data.get("to") or ""),
    )

    def check_type(where: str, t: str) -> None:
        if t != ANY and types is not None and t not in types:
            bad(where, "type", type=t)

    for sec in ("names", "naming", "ports"):
        if data.get(sec) is not None and not isinstance(data.get(sec), list):
            bad(sec, "not_list")
    for i, r in enumerate(data.get("names") or [] if isinstance(data.get("names"), list) else []):
        w = f"names[{i}]"
        if not isinstance(r, dict):
            bad(w, "not_mapping")
            continue
        nr = NameRule(
            type=str(r.get("type") or ANY),
            match=str(r.get("match") or "exact"),
            src=str(r.get("from") if r.get("from") is not None else ""),
            to=str(r.get("to") if r.get("to") is not None else ""),
            ignore_case=_bool(r.get("ignore_case"), False),
            enabled=_bool(r.get("enabled"), True),
            note=str(r.get("note") or ""),
        )
        check_type(f"{w}.type", nr.type)
        if nr.match not in NAME_MATCH:
            bad(f"{w}.match", "match", value=nr.match, choices=", ".join(NAME_MATCH))
        if not nr.src:
            bad(f"{w}.from", "empty")
        if not nr.to:
            bad(f"{w}.to", "empty")
        flags = re.IGNORECASE if nr.ignore_case else 0
        ngroups, names_ = 0, set()
        try:
            if nr.match == "regex":
                nr.rx = re.compile(nr.src, flags)
                ngroups, names_ = nr.rx.groups, set(nr.rx.groupindex)
            elif nr.match == "wildcard":
                nr.rx = _wild_rx(nr.src, flags)
                ngroups = nr.rx.groups
        except re.error as e:
            bad(f"{w}.from", "regex", error=str(e))
        for gname in _groups_used(nr.to):
            if not (gname.isdigit() and int(gname) <= ngroups) and gname not in names_:
                bad(f"{w}.to", "group", group=gname, groups=ngroups)
        rs.names.append(nr)
    for i, r in enumerate(data.get("naming") or [] if isinstance(data.get("naming"), list) else []):
        w = f"naming[{i}]"
        if not isinstance(r, dict):
            bad(w, "not_mapping")
            continue
        reps: list[tuple[str, str]] = []
        for j, x in enumerate(r.get("replace") or []):
            if not isinstance(x, dict) or not str(x.get("from") or ""):
                bad(f"{w}.replace[{j}]", "empty")
                continue
            try:
                re.compile(str(x["from"]))
            except re.error as e:
                bad(f"{w}.replace[{j}].from", "regex", error=str(e))
            reps.append((str(x["from"]), str(x.get("to") if x.get("to") is not None else "")))
        ml = r.get("max_length")
        nm = NamingRule(
            type=str(r.get("type") or ANY),
            pattern=str(r.get("pattern") or ""),
            fix=_bool(r.get("fix"), False),
            case=str(r.get("case") or "keep"),
            prefix=str(r.get("prefix") or ""),
            suffix=str(r.get("suffix") or ""),
            replace=reps,
            truncate=_bool(r.get("truncate"), True),
            max_length=None,
            enabled=_bool(r.get("enabled"), True),
            note=str(r.get("note") or ""),
        )
        check_type(f"{w}.type", nm.type)
        if ml not in (None, ""):
            try:
                nm.max_length = int(ml)
                if nm.max_length < 1:
                    raise ValueError
            except (TypeError, ValueError):
                bad(f"{w}.max_length", "max_length", value=ml)
                nm.max_length = None
        if nm.case not in CASES:
            bad(f"{w}.case", "match", value=nm.case, choices=", ".join(CASES))
        if nm.pattern:
            try:
                re.compile(nm.pattern)
            except re.error as e:
                bad(f"{w}.pattern", "regex", error=str(e))
        rs.naming.append(nm)
    for i, r in enumerate(data.get("ports") or [] if isinstance(data.get("ports"), list) else []):
        w = f"ports[{i}]"
        if not isinstance(r, dict):
            bad(w, "not_mapping")
            continue
        pr = PortRule(
            match=str(r.get("match") or "exact"),
            src=str(r.get("from") or "").strip(),
            to=str(r.get("to") or "").strip(),
            enabled=_bool(r.get("enabled"), True),
            note=str(r.get("note") or ""),
        )
        if pr.match not in PORT_MATCH:
            bad(f"{w}.match", "match", value=pr.match, choices=", ".join(PORT_MATCH))
        if not pr.src:
            bad(f"{w}.from", "empty")
        if not pr.to:
            bad(f"{w}.to", "empty")
        rg = r.get("range")
        if rg not in (None, "", []):
            try:
                a, b = (int(rg[0]), int(rg[1])) if isinstance(rg, list | tuple) else (int(rg), int(rg))
                if a > b:
                    raise ValueError
                pr.range = (a, b)
            except (TypeError, ValueError, IndexError):
                bad(f"{w}.range", "range", value=str(rg))
        if r.get("speed") not in (None, ""):
            try:
                pr.speed = float(r["speed"])
            except (TypeError, ValueError):
                bad(f"{w}.speed", "speed", value=str(r["speed"]))
        if pr.match == "pattern":
            if "{n}" not in pr.src:
                bad(f"{w}.from", "pattern_n")
            elif pr.src:
                pr.rx = _port_rx(pr.src)
        elif pr.match == "type" and pr.src:
            from lmesh.core.migration import parse_port

            pr.ptype = parse_port(pr.src + "0").type
        rs.ports.append(pr)
    if issues:
        raise RulesError("naming.invalid", "invalid", issues, n=len(issues))
    return rs


# ---------------------------------------------------------------- 存放


def builtin_dir(kb_root: Path | None = None) -> Path:
    """内置规则集：运行时知识库有 translate-rules/ 时用它，否则用程序自带的。"""
    if kb_root is not None and (Path(kb_root) / DIR_NAME).is_dir():
        return Path(kb_root) / DIR_NAME
    from lmesh import paths

    return paths.builtin_knowledge_dir() / DIR_NAME


def user_dir() -> Path:
    from lmesh import paths

    return paths.data_dir() / DIR_NAME


def _files(kb_root: Path | None) -> list[tuple[Path, bool]]:
    out: list[tuple[Path, bool]] = []
    for d, builtin in ((builtin_dir(kb_root), True), (user_dir(), False)):
        if d.is_dir():
            out += [(f, builtin) for f in sorted(d.glob("*.yaml"))]
    return out


def _load_file(f: Path, builtin: bool, kb: KnowledgeBase | None) -> RuleSet:
    rs = parse(f.read_text(encoding="utf-8"), kb, f.stem)
    rs.builtin, rs.file = builtin, f.name
    return rs


def list_sets(kb_root: Path | None, kb: KnowledgeBase | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f, builtin in _files(kb_root):
        try:
            info = _load_file(f, builtin, kb).info()
            info.update(valid=True, issues=[])
        except RulesError as e:
            info = {"id": f.stem, "file": f.name, "builtin": builtin, "valid": False, "issues": e.issues}
        info["updated"] = f.stat().st_mtime
        out.append(info)
    return out


def find_file(kb_root: Path | None, rid: str) -> tuple[Path, bool] | None:
    if not _ID.match(rid):
        return None
    for d, builtin in ((user_dir(), False), (builtin_dir(kb_root), True)):
        f = d / f"{rid}.yaml"
        if f.is_file():
            return f, builtin
    return None


def load(kb_root: Path | None, ref: str, kb: KnowledgeBase | None = None) -> RuleSet:
    """规则集编号，或规则集文件路径（CLI 用）。"""
    p = Path(ref)
    if p.suffix.lower() in (".yaml", ".yml") and p.is_file():
        rs = parse(p.read_text(encoding="utf-8"), kb, p.stem)
        rs.file = p.name
        return rs
    hit = find_file(kb_root, ref)
    if hit is None:
        raise RulesError("naming.not_found", "not_found", id=ref)
    return _load_file(hit[0], hit[1], kb)


def source(kb_root: Path | None, rid: str) -> tuple[str, bool]:
    hit = find_file(kb_root, rid)
    if hit is None:
        raise RulesError("naming.not_found", "not_found", id=rid)
    return hit[0].read_text(encoding="utf-8"), hit[1]


def _merge_rt(dst: Any, src: Any) -> Any:
    """把新内容合并进往返模式读出的文档：相同的键保留位置与注释，列表按序号逐项合并。"""
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    if isinstance(dst, CommentedMap) and isinstance(src, dict):
        for k in [k for k in dst if k not in src]:
            del dst[k]
        for k, v in src.items():
            dst[k] = _merge_rt(dst[k], v) if k in dst else v
        return dst
    if isinstance(dst, CommentedSeq) and isinstance(src, list):
        for i, v in enumerate(src):
            if i < len(dst):
                dst[i] = _merge_rt(dst[i], v)
            else:
                dst.append(v)
        del dst[len(src) :]
        return dst
    return src


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    """写回文件时省略取默认值的字段，文件保持简短。"""
    defaults = {"ignore_case": False, "enabled": True, "fix": False, "case": "keep", "prefix": "", "suffix": ""}
    defaults.update(replace=[], truncate=True, max_length=None, range=None, speed=None, note="", pattern="")
    return {k: v for k, v in d.items() if not (k in defaults and v == defaults[k] and k != "type")}


def save(
    kb_root: Path | None, rid: str, data: dict[str, Any] | str, kb: KnowledgeBase | None = None, overwrite: bool = True
) -> RuleSet:
    """校验后写入 data/translate-rules/<编号>.yaml。data 为 YAML 文本时原样写入；为 dict 时合并进已有文件（保留注释与顺序）。
    内置规则集的编号不能用（另存为新编号）。"""
    from lmesh.core.kb import repo
    from lmesh.core.kb.files import dump_rt, load_rt

    if not _ID.match(rid):
        raise RulesError("naming.bad_id", id=rid)
    if isinstance(data, dict):
        data = {**data, "id": rid}
    rs = parse(data, kb, rid)
    if rs.id != rid:
        raise RulesError("naming.id_mismatch", id=rid, got=rs.id)
    if (builtin_dir(kb_root) / f"{rid}.yaml").is_file():
        raise RulesError("naming.builtin_readonly", "readonly", id=rid)
    path = user_dir() / f"{rid}.yaml"
    if path.exists() and not overwrite:
        raise RulesError("naming.exists", "exists", id=rid)
    with repo.WRITE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            tmp = path.with_suffix(".yaml.tmp")
            tmp.write_text(data if data.endswith("\n") else data + "\n", encoding="utf-8", newline="\n")
            tmp.replace(path)
        else:
            plain = rs.as_dict()
            plain = {k: v for k, v in plain.items() if v not in (None, {}, "")}
            for sec in ("names", "naming", "ports"):
                plain[sec] = [_clean(x) for x in plain.get(sec) or []]
            doc = load_rt(path) if path.exists() else None
            dump_rt(path, _merge_rt(doc, plain) if doc is not None else plain)
    rs.file, rs.builtin = path.name, False
    return rs


def delete(kb_root: Path | None, rid: str) -> None:
    hit = find_file(kb_root, rid)
    if hit is None:
        raise RulesError("naming.not_found", "not_found", id=rid)
    if hit[1]:
        raise RulesError("naming.builtin_readonly", "readonly", id=rid)
    hit[0].unlink()


# ---------------------------------------------------------------- 知识：可改名的对象类型、名称长度上限


def rename_types(kb: KnowledgeBase) -> list[str]:
    """被引用的、单键的对象类型（接口由端口映射处理，不在其中）。"""
    out = set()
    for n in kb.nodes.values():
        if n.type == "ref" and n.ref and n.ref != "interface":
            t = kb.nodes.get(n.ref)
            if t is not None and t.type == "object" and len(t.key) <= 1:
                out.add(t.id)
    return sorted(out)


def type_infos(kb: KnowledgeBase) -> list[dict[str, Any]]:
    return [{"id": t, "domain": kb.nodes[t].domain, "title": kb.nodes[t].semantic} for t in rename_types(kb)]


def name_limits(kb: KnowledgeBase, family: str) -> dict[str, int]:
    """目标平台族的名称长度上限：knowledge/render/<族>.yaml 的 name_limits。"""
    if not family:
        return {}
    f = Path(kb.root) / "render" / f"{family}.yaml"
    if not f.exists():
        from lmesh import paths

        f = paths.builtin_knowledge_dir() / "render" / f"{family}.yaml"
    data = (read_yaml(f) or {}) if f.exists() else {}
    out: dict[str, int] = {}
    for k, v in (data.get("name_limits") or {}).items() if isinstance(data, dict) else []:
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out


# ---------------------------------------------------------------- 匹配


def _expand(tpl: str, m: re.Match[str] | None, whole: str) -> str:
    def sub(x: re.Match[str]) -> str:
        g = x.group(1)
        if g == "0":
            return whole
        if m is None:
            return x.group(0)
        try:
            return m.group(int(g) if g.isdigit() else g) or ""
        except (IndexError, KeyError):
            return ""

    return _GROUP.sub(sub, re.sub(r"\\(\d+)", r"{\1}", tpl))


def map_name(rs: RuleSet, otype: str, name: str) -> tuple[str, int | None]:
    """名称映射：(新名称, 命中的规则序号)；没有命中时 (原名, None)。otype 为 * 时（测试框不选类型）不按类型过滤。"""
    for i, r in enumerate(rs.names):
        if not r.enabled or (otype != ANY and r.type not in (ANY, otype)):
            continue
        if r.match == "exact":
            hit = name.casefold() == r.src.casefold() if r.ignore_case else name == r.src
            if hit:
                return _expand(r.to, None, name), i
        elif r.rx is not None:
            m = r.rx.fullmatch(name)
            if m:
                return _expand(r.to, m, name), i
    return name, None


def _naming_rule(rs: RuleSet, otype: str) -> tuple[int, NamingRule] | None:
    for i, r in enumerate(rs.naming):
        if r.enabled and (otype == ANY or r.type in (ANY, otype)):
            return i, r
    return None


def resolve_name(rs: RuleSet, otype: str, name: str, limits: dict[str, int] | None = None) -> dict[str, Any]:
    """一个名称经过名称映射与命名规范后的结果（试运行、编辑器测试框共用）。"""
    mapped, ri = map_name(rs, otype, name)
    out: dict[str, Any] = {"type": otype, "from": name, "mapped": mapped, "rule": ri, "naming_rule": None}
    fixes: list[str] = []
    problems: list[dict[str, Any]] = []
    final = mapped
    nr = _naming_rule(rs, otype)
    max_len: int | None = None
    limit_source = None
    if nr is not None:
        ni, rule = nr
        out["naming_rule"] = ni
        if rule.max_length:
            max_len, limit_source = rule.max_length, "rule"
        elif limits and otype in limits:
            max_len, limit_source = limits[otype], "knowledge"
        if rule.fix:
            for a, b in rule.replace:
                new = re.sub(a, b, final)
                if new != final:
                    final = new
                    if "replace" not in fixes:
                        fixes.append("replace")
            if rule.case == "upper" and final != final.upper():
                final = final.upper()
                fixes.append("upper")
            elif rule.case == "lower" and final != final.lower():
                final = final.lower()
                fixes.append("lower")
            if rule.prefix and not final.startswith(rule.prefix):
                final = rule.prefix + final
                fixes.append("prefix")
            if rule.suffix and not final.endswith(rule.suffix):
                final = final + rule.suffix
                fixes.append("suffix")
            if rule.truncate and max_len and len(final) > max_len:
                keep = rule.suffix if rule.suffix and final.endswith(rule.suffix) and len(rule.suffix) < max_len else ""
                final = final[: max_len - len(keep)] + keep
                fixes.append("truncate")
        if rule.pattern and not re.fullmatch(rule.pattern, final):
            problems.append({"problem": "pattern", "pattern": rule.pattern})
        if max_len and len(final) > max_len:
            problems.append({"problem": "length", "length": len(final), "max_length": max_len})
    out.update(
        result=final,
        fixes=fixes,
        problems=problems,
        max_length=max_len,
        limit_source=limit_source,
        changed=final != name,
    )
    return out


def _n_expr(tpl: str, n: int) -> str:
    return _N.sub(lambda m: str(n + int(m.group(1).replace(" ", "")) if m.group(1) else n), tpl)


def map_port(rs: RuleSet, name: str) -> tuple[str, int | None]:
    """端口映射（主接口名，按统一写法匹配）：(新名称, 规则序号)；没有命中时 (原名, None)。"""
    from lmesh.core.migration import parse_port

    canon_name = cmp.interface_name(name)
    port = parse_port(canon_name)
    nums = port.numbers
    for i, r in enumerate(rs.ports):
        if not r.enabled:
            continue
        if r.speed is not None and port.speed != r.speed:
            continue
        if r.match == "exact":
            if cmp.interface_name(r.src).lower() == canon_name.lower():
                return r.to, i
        elif r.match == "pattern" and r.rx is not None:
            m = r.rx.fullmatch(canon_name)
            if not m:
                continue
            n = int(m.group(1))
            if r.range and not r.range[0] <= n <= r.range[1]:
                continue
            return _n_expr(r.to, n), i
        elif r.match == "type" and r.ptype and port.type.lower() == r.ptype.lower():
            n = nums[-1] if nums else 0
            if r.range and not r.range[0] <= n <= r.range[1]:
                continue
            if "{" in r.to:
                return _n_expr(r.to.replace("{rest}", port.rest), n), i
            return r.to + port.rest, i
    return name, None


def test_input(
    rs: RuleSet, kind: str, value: str, otype: str = ANY, kb: KnowledgeBase | None = None, family: str = ""
) -> dict[str, Any]:
    """编辑器测试框：一个名称或接口名的映射结果。"""
    if kind == "port":
        base, dot, sub = value.strip().partition(".")
        new, ri = map_port(rs, base)
        result = f"{new}.{sub}" if dot and ri is not None else (value.strip() if ri is None else new)
        return {"kind": "port", "from": value.strip(), "result": result, "rule": ri, "changed": ri is not None}
    limits = name_limits(kb, family or rs.dst_family) if kb is not None else {}
    return {"kind": "name", **resolve_name(rs, otype, value.strip(), limits)}


# ---------------------------------------------------------------- 在图上改名


def _contains_parent(g: nx.MultiDiGraph, nid: str) -> str | None:
    return next((a for a, _, d in g.in_edges(nid, data=True) if d.get("kind") == "contains"), None)


def _ports(g: nx.MultiDiGraph, rs: RuleSet) -> tuple[dict[str, str], list[dict[str, Any]], list[dict[str, Any]]]:
    """端口映射表 {源主接口: 目标主接口}、逐条结果、冲突（多对一、与不改名的源接口重名）。"""
    bases: dict[str, str] = {}  # 统一写法 → 原写法
    subs: dict[str, int] = defaultdict(int)
    lines: dict[str, list[int]] = defaultdict(list)
    for _, d in g.nodes(data=True):
        if d.get("kind") != "object" or d.get("schema") != "interface":
            continue
        key = str(d.get("key") or "")
        b, dot, _ = key.partition(".")
        cb = cmp.interface_name(b)
        bases.setdefault(cb, b)
        if dot:
            subs[cb] += 1
        lines[cb] += list(d.get("lines") or [])
    rows: list[dict[str, Any]] = []
    for cb, raw in sorted(bases.items()):
        new, ri = map_port(rs, raw)
        if ri is None:
            continue
        rows.append(
            {
                "from": raw,
                "to": new,
                "rule": {"section": "ports", "index": ri},
                "subinterfaces": subs.get(cb, 0),
                "applied": True,
                "lines": sorted(set(lines[cb]))[:20],
            }
        )
    conflicts: list[dict[str, Any]] = []
    by_dst: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_dst[cmp.interface_name(r["to"]).lower()].append(r)
    mapped = {cmp.interface_name(r["from"]).lower() for r in rows}
    for dst, group in by_dst.items():
        keep = [raw for cb, raw in bases.items() if cb.lower() == dst and cb.lower() not in mapped]
        if len(group) > 1 or keep:
            for r in group:
                r["applied"] = False
            conflicts.append(
                {
                    "kind": "port_many_to_one" if len(group) > 1 else "port_exists",
                    "type": "interface",
                    "to": group[0]["to"],
                    "from": [r["from"] for r in group] + keep,
                }
            )
    pmap = {r["from"]: r["to"] for r in rows if r["applied"]}
    return pmap, rows, conflicts


def port_map(g: nx.MultiDiGraph, rs: RuleSet) -> dict[str, str]:
    """只要端口映射表 {源主接口: 目标主接口}（冲突的不在其中）。"""
    return _ports(g, rs)[0]


def _ref_attrs(kb: KnowledgeBase) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for n in kb.nodes.values():
        if n.type == "ref" and n.ref:
            out[n.ref].add(n.id)
    return out


def _replace_value(v: Any, old: str, new: str) -> tuple[Any, bool]:
    if isinstance(v, list):
        out = [new if str(x) == old else x for x in v]
        return out, out != v
    if v is not None and str(v) == old:
        return new, True
    return v, False


def run(
    g_src: nx.MultiDiGraph,
    kb: KnowledgeBase,
    rs: RuleSet,
    dst_profile: str | None = None,
    target_graph: nx.MultiDiGraph | None = None,
) -> tuple[nx.MultiDiGraph, dict[str, str], dict[str, Any]]:
    """按规则集改名：返回 (改名后的图副本, 端口映射表 {源主接口: 目标主接口}, 报告)。源图不变。"""
    g = g_src.copy()
    family = kb.profiles[dst_profile].family if dst_profile and dst_profile in kb.profiles else rs.dst_family
    limits = name_limits(kb, family)
    types = set(rename_types(kb))
    sch = cmp._Schema(kb)
    # 1. 可改名的对象：(类型, 名称) → 节点
    objs: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for nid, d in g.nodes(data=True):
        if d.get("kind") == "object" and d.get("schema") in types and not isinstance(d.get("key"), dict):
            key = d.get("key")
            if key not in (None, "", "_"):
                objs[str(d["schema"])][str(key)].append(nid)
    # 2. 每个名称的结果
    decisions: dict[tuple[str, str], dict[str, Any]] = {}
    naming_warn: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    gap_seen: set[str] = set()
    for t in sorted(objs):
        for old in sorted(objs[t]):
            r = resolve_name(rs, t, old, limits)
            nids = objs[t][old]
            if r["naming_rule"] is not None and r["max_length"] is None and t not in gap_seen:
                gap_seen.add(t)
                gaps.append({"kind": "name_limit_unknown", "type": t, "family": family or None})
            for p in r["problems"]:
                naming_warn.append(
                    {
                        "type": t,
                        "name": r["result"],
                        "source": old,
                        "node": nids[0],
                        "rule": {"section": "naming", "index": r["naming_rule"]},
                        "fixed": bool(r["fixes"]),
                        **p,
                    }
                )
            if r["changed"]:
                decisions[(t, old)] = {**r, "nodes": nids, "applied": True, "conflict": None}
    # 3. 冲突：多对一、与未改名的同类对象重名、与目标设备已有名称重名
    conflicts: list[dict[str, Any]] = []
    target_names: dict[str, set[str]] = defaultdict(set)
    if target_graph is not None:
        for _, d in target_graph.nodes(data=True):
            if d.get("kind") == "object" and d.get("schema") in types and not isinstance(d.get("key"), dict):
                target_names[str(d["schema"])].add(str(d.get("key")))
    for (t, old), dec in sorted(decisions.items()):
        if dec["result"] in target_names.get(t, set()) and dec["result"] not in objs[t]:
            dec["applied"], dec["conflict"] = False, "target_exists"
            conflicts.append({"kind": "target_exists", "type": t, "to": dec["result"], "from": [old]})
    changed = True
    while changed:
        changed = False
        for t in objs:
            final: dict[str, list[str]] = defaultdict(list)
            for old in objs[t]:
                cur = decisions.get((t, old))
                final[cur["result"] if cur and cur["applied"] else old].append(old)
            for new, olds in final.items():
                movers = [o for o in olds if (t, o) in decisions and decisions[(t, o)]["applied"]]
                if len(olds) < 2 or not movers:
                    continue
                kind = "many_to_one" if len(movers) > 1 else "exists"
                for o in movers:
                    decisions[(t, o)]["applied"], decisions[(t, o)]["conflict"] = False, kind
                conflicts.append({"kind": kind, "type": t, "to": new, "from": sorted(olds)})
                changed = True
    # 4. 改：对象的键、引用它的属性、复合键里引用它的字段
    ref_attrs = _ref_attrs(kb)
    key_changed: set[str] = set()
    renames: list[dict[str, Any]] = []
    key_ref_fields: dict[str, list[tuple[str, str]]] = defaultdict(list)  # 被引用类型 → [(对象类型, 键字段)]
    for sn in kb.nodes.values():
        if sn.type == "object" and len(sn.key) > 1:
            for f in sn.key:
                ft, ref = sch.field_type(sn, f)
                if ft == "ref" and ref:
                    key_ref_fields[ref].append((sn.id, f))
    by_schema: dict[str, list[str]] = defaultdict(list)
    for nid, d in g.nodes(data=True):
        if d.get("schema"):
            by_schema[str(d["schema"])].append(nid)
    for (t, old), dec in sorted(decisions.items()):
        new = dec["result"]
        refs: list[dict[str, Any]] = []
        if dec["applied"]:
            for nid in dec["nodes"]:
                g.nodes[nid]["key"] = new
                g.nodes[nid]["raw"] = new
                key_changed.add(nid)
            candidates = {n for s in ref_attrs.get(t, ()) for n in by_schema.get(s, [])}
            for nid in dec["nodes"]:
                candidates |= {a for a, _, ed in g.in_edges(nid, data=True) if ed.get("kind") == "reference"}
            for a in sorted(candidates):
                d = g.nodes[a]
                if d.get("kind") != "attr":
                    continue
                v, hit = _replace_value(d.get("value"), old, new)
                if hit:
                    d["value"] = v
                    d["raw"] = _replace_value(d.get("raw"), old, new)[0]
                    refs.append({"node": a, "schema": d.get("schema"), "lines": list(d.get("lines") or [])})
            for st, f in key_ref_fields.get(t, []):
                for nid in by_schema.get(st, []):
                    key = g.nodes[nid].get("key")
                    if isinstance(key, dict) and str(key.get(f)) == old:
                        g.nodes[nid]["key"] = {**key, f: new}
                        g.nodes[nid]["raw"] = g.nodes[nid]["key"]
                        key_changed.add(nid)
                        refs.append({"node": nid, "schema": st, "lines": list(g.nodes[nid].get("lines") or [])})
        lines = sorted({ln for n in dec["nodes"] for ln in (g.nodes[n].get("lines") or [])})
        renames.append(
            {
                "type": t,
                "node": dec["nodes"][0],
                "nodes": dec["nodes"],
                "from": old,
                "to": new,
                "mapped": dec["mapped"],
                "rule": {"section": "names", "index": dec["rule"]} if dec["rule"] is not None else None,
                "naming_rule": dec["naming_rule"],
                "fixes": dec["fixes"],
                "refs": len(refs),
                "ref_nodes": refs,
                "applied": dec["applied"],
                "conflict": dec["conflict"],
                "lines": lines,
            }
        )
    # 5. 编号随键改（子树一起）；语句里的节点编号同步
    ren = _relabel(g, key_changed)
    for r in renames:
        r["new_node"] = ren.get(r["node"], r["node"]) if r["applied"] else None
        for x in r["ref_nodes"]:
            x["node"] = ren.get(x["node"], x["node"])
    # 6. 原文行（未映射命令、功能域外原文、未识别行）里出现的旧名不会被改：列出，人工处理
    text_refs: list[dict[str, Any]] = []
    applied_names = {r["from"]: r["to"] for r in renames if r["applied"]}
    if applied_names:
        words = re.compile(
            r"(?<![\w.-])(" + "|".join(map(re.escape, sorted(applied_names, key=len)[::-1])) + r")(?![\w.-])"
        )
        stmts = {st.line.no: st for st in g.graph.get("statements", [])}
        for nid, d in g.nodes(data=True):
            if d.get("kind") not in ("ext", "raw", "unknown"):
                continue
            for no in d.get("lines") or []:
                stmt = stmts.get(no)
                text = stmt.line.text if stmt else str(d.get("text") or "")
                m = words.search(text)
                if m:
                    text_refs.append(
                        {
                            "node": nid,
                            "name": m.group(1),
                            "to": applied_names[m.group(1)],
                            "line": no,
                            "text": text.strip(),
                        }
                    )
    pmap, port_rows, port_conflicts = _ports(g_src, rs)
    conflicts += port_conflicts
    report = {
        "rule_set": rs.id,
        "family": family or None,
        "renames": renames,
        "ports": port_rows,
        "conflicts": conflicts,
        "naming": naming_warn,
        "text_refs": text_refs,
        "gaps": gaps,
        "summary": {
            "renamed": sum(1 for r in renames if r["applied"]),
            "refs": sum(r["refs"] for r in renames if r["applied"]),
            "ports": len(pmap),
            "subinterfaces": sum(r["subinterfaces"] for r in port_rows if r["applied"]),
            "conflicts": len(conflicts),
            "naming": len(naming_warn),
            "text_refs": len(text_refs),
            "gaps": len(gaps),
        },
    }
    return g, pmap, report


def _relabel(g: nx.MultiDiGraph, changed: set[str]) -> dict[str, str]:
    """键改过的对象重新算编号的最后一段，子树编号随父节点改；返回 {旧编号: 新编号}。"""
    if not changed:
        return {}
    kids: dict[str, list[str]] = defaultdict(list)
    for a, b, d in g.edges(data=True):
        if d.get("kind") == "contains":
            kids[a].append(b)
    ren: dict[str, str] = {}
    stack = [(DEVICE, DEVICE)]
    while stack:
        old_parent, new_parent = stack.pop()
        for c in kids.get(old_parent, []):
            seg = c[len(old_parent) + 1 :] if old_parent != DEVICE else c
            if c in changed:
                d = g.nodes[c]
                seg = f"{_short(str(d['schema']), g.nodes[old_parent].get('schema'))}[{_key_text(d.get('key'))}]"
            new = seg if new_parent == DEVICE else f"{new_parent}/{seg}"
            if new != c:
                ren[c] = new
            stack.append((c, new))
    if ren:
        nx.relabel_nodes(g, ren, copy=False)
        g.graph.pop("_stmt_index", None)
        g.graph["statements"] = [
            Statement(st.line, [ren.get(n, n) for n in st.nodes], {k: ren.get(v, v) for k, v in st.sources.items()})
            for st in g.graph.get("statements", [])
        ]
    return ren
