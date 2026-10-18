"""通用命令卡抽取器：按 knowledge/extractors/<名称>.yaml 中的规则，从 Markdown 产品文档抽取命令卡（draft）。

接入新厂商时一般只需新增一份规则文件。规则文件的字段：
    family            平台族（对应 commands/<族>/）
    doc_root_hint     文档目录下命令参考所在的子目录（存在时以它为根）
    sections          各字段对应的小节标题：syntax / params / views / default / function / usage / example
    default_regex     没有单独的缺省值小节时，在 function 小节中查找缺省值的正则
    negative_prefix   取消命令的前缀（undo / no），这类格式行作为对应命令卡的 undo
    exclude_titles    排除的命令（display、show、reset 等非配置命令）
    views_split       视图小节中多个视图之间的分隔符（正则）
    views_map         视图名（正则）→ views.yaml 中的视图编号；映射不上的视图丢弃
    enters            进入子视图的命令：{view, syntax（正则）, enters}
    param_types       参数类型推断：{name（参数名正则）, value（取值说明正则）, type, range_groups}，按顺序第一条命中生效
    domains           功能域 → 文件列表 {path（相对文档根的 glob）, sections（只取这些章节，可选）}
    syntax_rewrites   对所有语法统一改写：{pattern（正则）, replace, params（新参数的类型）}，例如把
                      <interface-type> <interface-number> 合成一个 <interface>（配置里接口名是一个词）
同目录的 <名称>.patches.yaml 记录逐条的文档错误修正：{id, reason, set: {syntax / params / undo …}}，每次抽取都会应用，
被修正的卡在来源中注明 patched。
"""

from __future__ import annotations

import fnmatch
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lmesh.core.ingest import markdown as md
from lmesh.core.kb import read_yaml
from lmesh.core.kb import syntax as syn


@dataclass
class Rules:
    name: str
    family: str
    raw: dict[str, Any]

    def sec(self, key: str) -> list[str]:
        return list((self.raw.get("sections") or {}).get(key, []) or [])

    @property
    def negative(self) -> str:
        return str(self.raw.get("negative_prefix", "undo"))


def load_rules(path: Path) -> Rules:
    raw = read_yaml(path) or {}
    patches_file = path.with_name(path.stem + ".patches.yaml")
    raw["_patches"] = (read_yaml(patches_file) or {}).get("patches", []) if patches_file.exists() else []
    return Rules(name=str(raw.get("name", path.stem)), family=str(raw["family"]), raw=raw)


def _rewrite(syntax: str, rules: Rules) -> tuple[str, dict[str, dict[str, Any]]]:
    added: dict[str, dict[str, Any]] = {}
    for r in rules.raw.get("syntax_rewrites") or []:
        new = re.sub(str(r["pattern"]), str(r["replace"]), syntax)
        if new != syntax:
            syntax = new
            added.update({str(k): dict(v) for k, v in (r.get("params") or {}).items()})
    return syntax, added


def apply_patches(cards: list[dict[str, Any]], rules: Rules) -> int:
    """按修正文件改写命令卡；返回修正的张数。"""
    by_id = {c["id"]: c for c in cards}
    n = 0
    for p in rules.raw.get("_patches") or []:
        if p.get("add"):  # 文档没有覆盖的命令：按修正文件新增
            new = dict(p["add"])
            new.setdefault("status", "draft")
            new["source"] = {
                **dict(new.get("source") or {}),
                "patched": str(p.get("reason", "")),
                "added_by_patch": True,
            }
            if new["id"] not in by_id:
                cards.append(new)
                by_id[new["id"]] = new
                n += 1
            continue
        c = by_id.get(str(p.get("id")))
        if c is None:
            continue
        for k, v in (p.get("set") or {}).items():
            c[k] = v
        c.setdefault("source", {})["patched"] = str(p.get("reason", ""))
        n += 1
    return n


@dataclass
class ExtractResult:
    cards: list[dict[str, Any]] = field(default_factory=list)
    files: int = 0
    commands: int = 0
    skipped: Counter[str] = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)  # 规则抽取失败的命令（可交给 AI 通道）
    patched: int = 0

    def summary(self) -> dict[str, Any]:
        per = Counter(c["domain"] for c in self.cards)
        return {
            "files": self.files,
            "commands": self.commands,
            "cards": len(self.cards),
            "per_domain": dict(per),
            "patched": self.patched,
            "skipped": dict(self.skipped),
            "errors": self.errors[:50],
        }


def _slug(text: str) -> str:
    t = re.sub(r"\s*\(.*?\)\s*", " ", text)
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-") or "cmd"


def _doc_root(doc_dir: Path, rules: Rules) -> Path:
    hint = rules.raw.get("doc_root_hint")
    if hint and (doc_dir / hint).exists():
        return doc_dir / hint
    return doc_dir


def _files_for(root: Path, rules: Rules, domains: list[str] | None) -> list[tuple[str, Path, list[str]]]:
    out: list[tuple[str, Path, list[str]]] = []
    all_md = [p for p in sorted(root.rglob("*.md"))]
    for domain, specs in (rules.raw.get("domains") or {}).items():
        if domains and domain not in domains:
            continue
        for spec in specs or []:
            pat = str(spec["path"])
            for p in all_md:
                rel = p.relative_to(root).as_posix()
                if fnmatch.fnmatch(rel, pat) or rel == pat:
                    out.append((str(domain), p, list(spec.get("sections") or [])))
    return out


def _map_views(text: str, rules: Rules) -> list[str]:
    split = rules.raw.get("views_split", r",\s*|;\s*|\s+and\s+|/")
    found: list[str] = []
    # 先按行拆（Cisco 每行一个模式），再按分隔符拆
    parts = [p for ln in text.splitlines() for p in re.split(split, md.clean(ln))]
    for part in parts:
        name = part.strip().rstrip(".")
        if not name:
            continue
        for vm in rules.raw.get("views_map") or []:
            if re.search(str(vm["match"]), name, re.I):
                v = str(vm["view"])
                if v not in found:
                    found.append(v)
                break
    return found


def _param_spec(name: str, value: str, rules: Rules) -> dict[str, Any]:
    # 枚举类型：“The value is an enumerated type: - deny: … - permit: …”
    em = rules.raw.get("enum_marker")
    if em and re.search(str(em), value, re.I):
        items = re.findall(str(rules.raw.get("enum_item", r"(?:^|\s)-\s*([\w\-]+)\s*:")), value)
        if items:
            return {"type": "enum", "choices": list(dict.fromkeys(items))}
    for r in rules.raw.get("param_types") or []:
        if r.get("name") and not re.search(str(r["name"]), name, re.I):
            continue
        m = None
        if r.get("value"):
            m = re.search(str(r["value"]), value, re.I)
            if not m:
                continue
        spec: dict[str, Any] = {"type": str(r["type"])}
        groups = r.get("range_groups")
        if m and groups:
            try:
                lo, hi = (m.group(int(g)) for g in groups)
                spec["range"] = [int(lo), int(hi)]
            except (IndexError, TypeError, ValueError):
                pass
        return spec
    return {"type": "word"}


def _default_text(cmd: md.Section, rules: Rules) -> str | None:
    sec = cmd.child(rules.sec("default"))
    if sec and sec.text():
        return md.clean(sec.text())
    fn = cmd.child(rules.sec("function"))
    rx = rules.raw.get("default_regex")
    if fn and rx:
        m = re.search(str(rx), md.clean(fn.text()), re.I)
        if m:
            return m.group(0).strip()
    return None


def _enters(view: str, syntax: str, rules: Rules) -> str | None:
    for e in rules.raw.get("enters") or []:
        if str(e.get("view", view)) == view and re.search(str(e["syntax"]), syntax):
            return str(e["enters"])
    return None


def _is_command(sec: md.Section, rules: Rules) -> bool:
    return sec.child(rules.sec("syntax")) is not None


def extract(doc_dir: Path, rules: Rules, domains: list[str] | None = None, source_version: str = "") -> ExtractResult:
    root = _doc_root(doc_dir, rules)
    res = ExtractResult()
    exclude = re.compile(str(rules.raw.get("exclude_titles", r"^$")), re.I)
    seen: dict[tuple[str, str], str] = {}  # (语法, 视图) → 卡片编号，去重
    ids: Counter[str] = Counter()
    for domain, path, only_sections in _files_for(root, rules, domains):
        res.files += 1
        try:
            tree = md.parse_file(path)
        except OSError as e:
            res.errors.append(f"{path.name}: {e}")
            continue
        for sec in tree.walk():
            if sec.level == 0 or not _is_command(sec, rules):
                continue
            if only_sections and not set(only_sections) & set(sec.path()):
                continue
            res.commands += 1
            title = md.clean(sec.title)
            if exclude.search(title):
                res.skipped["excluded"] += 1
                continue
            vsec = sec.child(rules.sec("views"))
            views = _map_views("\n".join(vsec.body), rules) if vsec else []
            # 视图别名：文档只列了一个视图、实际在另一个视图中也有效（如 Cisco BGP neighbor 命令在地址族模式下）
            for v in list(views):
                for alias in (rules.raw.get("view_aliases") or {}).get(v, []):
                    if alias not in views:
                        views.append(str(alias))
            if not views:
                res.skipped["view_unmapped"] += 1
                continue
            fmt = sec.child(rules.sec("syntax"))
            assert fmt is not None
            lines = [ln.strip() for ln in fmt.body if ln.strip() and "*" in ln]
            syntaxes: list[str] = []
            undos: list[str] = []
            for ln in lines:
                s = md.format_to_syntax(ln)
                if not s:
                    continue
                (undos if s.split()[0].lower() == rules.negative else syntaxes).append(s)
            if not syntaxes:
                res.skipped["no_positive_form"] += 1
                continue
            # 参数类型
            params: dict[str, dict[str, Any]] = {}
            psec = sec.child(rules.sec("params"))
            if psec:
                for row in md.table_rows(psec.body):
                    names = md.params_in_cell(row[0])
                    value = md.clean(" ".join(row[1:]))
                    for n in names:
                        params[n] = _param_spec(n, value, rules)
            default = _default_text(sec, rules)
            rel = path.relative_to(root).as_posix()
            for vi, s0 in enumerate(syntaxes):
                s, extra_params = _rewrite(s0, rules)
                try:
                    parsed = syn.parse(s)
                except syn.SyntaxErrorKB as e:
                    res.skipped["syntax_error"] += 1
                    res.errors.append(f"{title}: {e}")
                    res.failed.append(
                        {
                            "title": title,
                            "domain": domain,
                            "views": views,
                            "format": lines[vi] if vi < len(lines) else s,
                            "converted": s,
                            "params": params,
                            "file": path.relative_to(root).as_posix(),
                            "line": sec.line,
                        }
                    )
                    continue
                pnames = parsed.params()
                card_params = {
                    n: extra_params.get(n) or params.get(n) or _param_spec(n, "", rules) for n in dict.fromkeys(pnames)
                }
                undo = _match_undo(s, [_rewrite(u, rules)[0] for u in undos], rules.negative)
                for view in views:
                    key = (s, view)
                    if key in seen:
                        res.skipped["duplicate"] += 1
                        continue
                    base = (
                        f"{rules.family}.{_slug(title)}"
                        + (f".{vi + 1}" if len(syntaxes) > 1 else "")
                        + (f"@{view}" if len(views) > 1 else "")
                    )
                    ids[base] += 1
                    cid = base if ids[base] == 1 else f"{base}~{ids[base]}"
                    seen[key] = cid
                    card: dict[str, Any] = {
                        "id": cid,
                        "syntax": s,
                        "view": view,
                        "params": card_params,
                        "domain": domain,
                        "status": "draft",
                        "source": {
                            "doc": rules.name,
                            "file": rel,
                            "title": title,
                            "line": sec.line,
                            **({"version": source_version} if source_version else {}),
                        },
                    }
                    ev = _enters(view, s, rules)
                    if ev:
                        card["enters_view"] = ev
                    if undo:
                        card["undo"] = undo
                    if default:
                        card["default"] = default
                    res.cards.append(card)
    res.patched = apply_patches(res.cards, rules)
    return res


def _match_undo(syntax: str, undos: list[str], neg: str) -> str | None:
    """为一个格式选取最相近的取消命令：关键字前缀重合最多的那一条。"""
    if not undos:
        return None
    words = [w for w in syntax.split() if not w.startswith("<") and w not in "[]{}|"]

    def score(u: str) -> int:
        uw = [w for w in u.split()[1:] if not w.startswith("<") and w not in "[]{}|"]
        n = 0
        for a, b in zip(words, uw, strict=False):
            if a != b:
                break
            n += 1
        return n

    best = max(undos, key=score)
    return best if score(best) > 0 else None
