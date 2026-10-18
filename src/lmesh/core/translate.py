"""配置翻译（M3-3，REQ-012）：一张配置图 → 另一个 Profile（平台族）的配置文本，按有效值翻译并给出告警。

流程：
    1. 换目标：复制源图的语义节点（对象、显式属性、目标 Profile 不隐式创建的派生对象），接口名按映射表改写
       （对象键与接口类型的取值；子接口按父接口映射；没给映射表时同名）。
    2. 默认值差异（目标默认值按目标 Profile 计算，含 when 条件）：
       - 源设备依赖默认值、目标默认值不同     → 显式写出，告警 default_differs；
       - 源设备依赖默认值、目标没有登记默认值 → 不写，提示 default_unknown（请人工确认）；
       - 两边默认值相同                       → 不写；
       - 源设备显式值等于目标默认值           → 省略，在 defaults[] 说明（explicit_equals_default）。
    3. 目标 Profile 标为不支持的节点 → unsupported[]（reason=profile_unsupported，附原文行号），不写；
       写不出命令的节点（目标平台族没有对应的命令卡或映射）→ unsupported[]（reason=no_render）；
       密码类取值（Schema 节点名为 password / secret）跨平台族时不写 → unsupported[]（reason=secret），人工重新设置；
       未映射命令（ext）、功能域外原文（raw）、未识别行（unknown）不翻译 → unsupported[]（kind=ext / raw / unknown），人工处理。
    4. 用规范渲染器（canon）生成目标配置。
    5. 校验：译文用目标 Profile 解析建图，与源图按有效值对比（跨厂商 + 接口映射）；
       上面列出的项之外还有差异时，每条差异记为告警 verify_diff（不应出现，出现说明知识库的映射两边不一致）。

所有告警都带文案键（key）与参数（params），界面与 CLI 按语言显示；字段名与取值不随语言变化。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

import networkx as nx

from lmesh.core import canon
from lmesh.core import compare as cmp
from lmesh.core.graph import DEVICE, Builder, _key_text, _short
from lmesh.core.kb import KnowledgeBase, mapping
from lmesh.core.kb.model import NODE_TYPES, SchemaNode

# 密码类属性（按 Schema 节点名）：跨平台族时不翻译取值
_SECRET = re.compile(r"(^|_)(password|secret)$")


class TranslateError(ValueError):
    """翻译参数错误（文案键 + 参数）。"""

    def __init__(self, key: str, kind: str = "param", **fmt: Any):
        super().__init__(key)
        self.key, self.kind, self.fmt = key, kind, fmt


def _item(kind: str, key: str, node: str | None = None, **params: Any) -> dict[str, Any]:
    """告警 / 不支持 / 省略项：kind 与文案键 key 固定，params 是文案参数（含 node、schema，取值不随语言变化）。"""
    lines = params.pop("lines", [])
    params = {"node": node, **params}
    return {"kind": kind, "key": key, "node": node, "schema": params.get("schema"), "lines": lines, "params": params}


class _Translator:
    def __init__(
        self,
        g_src: nx.MultiDiGraph,
        kb: KnowledgeBase,
        src_profile: str,
        dst_profile: str,
        interface_map: dict[str, str] | None,
    ):
        for pid in (src_profile, dst_profile):
            if pid not in kb.profiles:
                raise TranslateError("parse.profile_unknown", profile=pid)
        self.g, self.kb = g_src, kb
        self.src, self.dst = src_profile, dst_profile
        self.sch = cmp._Schema(kb)
        self.raw_map = dict(interface_map or {})
        # 键按统一写法（GE0/2/1 与 GigabitEthernet0/2/1 是同一个口），值保留映射表里的写法
        self.ifmap = {cmp.interface_name(k).lower(): str(v).strip() for k, v in self.raw_map.items()}
        self.dst_res = kb.resolve_profile(dst_profile)
        self.cross_family = kb.profiles[src_profile].family != kb.profiles[dst_profile].family
        self.children: dict[str, list[str]] = defaultdict(list)
        for a, b, d in g_src.edges(data=True):
            if d.get("kind") == "contains":
                self.children[a].append(b)
        self.warnings: list[dict[str, Any]] = []
        self.unsupported: list[dict[str, Any]] = []
        self.defaults: list[dict[str, Any]] = []
        self.unmapped: set[str] = set()  # 映射表中没有的接口（保持原名）

    # ----- 接口名 -----

    def rename(self, name: Any) -> Any:
        if isinstance(name, list):
            return [self.rename(x) for x in name]
        if not isinstance(name, str) or not name or not self.ifmap:
            return name
        canon_name = cmp.interface_name(name)
        if canon_name.lower() in self.ifmap:
            return self.ifmap[canon_name.lower()]
        base, dot, sub = canon_name.partition(".")
        if dot and base.lower() in self.ifmap:
            return f"{self.ifmap[base.lower()]}.{sub}"  # 子接口按父接口映射
        self.unmapped.add(base)
        return name

    def is_if_field(self, sn: SchemaNode, f: str) -> bool:
        t, ref = self.sch.field_type(sn, f)
        return t == "interface" or ref == "interface" or f == "interface"

    def new_key(self, sn: SchemaNode, key: Any) -> Any:
        if isinstance(key, dict):
            return {f: (self.rename(v) if self.is_if_field(sn, f) else v) for f, v in key.items()}
        f = sn.key[0] if sn.key else "name"
        if (len(sn.key) <= 1 and sn.id in NODE_TYPES and sn.id == "interface") or self.is_if_field(sn, f):
            return self.rename(key)
        return key

    # ----- 1. 换目标 -----

    def retarget(self) -> nx.MultiDiGraph:
        prof = self.kb.profiles[self.dst]
        gt = nx.MultiDiGraph(
            device=self.g.graph.get("device"), profile=self.dst, family=prof.family, kb_version=self.kb.version
        )
        gt.add_node(
            DEVICE, kind="device", schema=None, value=self.g.graph.get("device"), origin="explicit", lines=[], cards=[]
        )
        self.to_new: dict[str, str] = {DEVICE: DEVICE}
        self.to_src: dict[str, str] = {DEVICE: DEVICE}
        self.src_defaults: list[tuple[str, str, Any]] = []  # (目标图中的属主, 源默认节点, 值)
        implicit = set(self.dst_res.implicit)
        stack = [DEVICE]
        while stack:
            pid = stack.pop()
            new_parent = self.to_new[pid]
            parent_schema = gt.nodes[new_parent].get("schema")
            for c in self.children.get(pid, []):
                d = self.g.nodes[c]
                kind = d.get("kind")
                sn = self.kb.nodes.get(str(d.get("schema")))
                if kind not in ("object", "attr") or sn is None:
                    continue
                if kind == "attr" and d.get("origin") == "default":
                    self.src_defaults.append((new_parent, c, d.get("value")))
                    continue
                if kind == "object":
                    if d.get("origin") == "derived" and sn.id in implicit:
                        continue
                    key = self.new_key(sn, d.get("key"))
                    seg = f"{_short(sn.id, parent_schema)}[{_key_text(key)}]"
                    attrs = {"key": key, "raw": key}
                else:
                    seg = c[len(pid) + 1 :] if pid != DEVICE else c
                    value = d.get("value")
                    if sn.type == "interface" or (sn.type == "ref" and sn.ref == "interface"):
                        value = self.rename(value)
                    attrs = {"value": value, "raw": value, "negated": d.get("negated", False)}
                nid = seg if new_parent == DEVICE else f"{new_parent}/{seg}"
                gt.add_node(
                    nid,
                    kind=kind,
                    schema=sn.id,
                    origin=d.get("origin", "explicit"),
                    lines=list(d.get("lines") or []),
                    cards=[],
                    **attrs,
                )
                gt.add_edge(new_parent, nid, kind="contains")
                self.to_new[c] = nid
                self.to_src[nid] = c
                if kind == "object":
                    stack.append(c)
        for a, b, d in self.g.edges(data=True):
            if d.get("kind") in ("reference", "prerequisite") and a in self.to_new and b in self.to_new:
                gt.add_edge(self.to_new[a], self.to_new[b], kind=d.get("kind"), note=d.get("note", ""))
        self.builder = Builder(self.kb, prof, str(self.g.graph.get("device") or "device"))
        self.builder.g = gt
        return gt

    def dst_default(self, gt: nx.MultiDiGraph, sn: SchemaNode, owner: str) -> Any:
        e = self.dst_res.entries.get(sn.id)
        if e is None or not e.supported or e.default is None:
            return None
        if not self.builder._when(owner, gt.nodes[owner], e.when):
            return None
        return mapping.normalize(sn.type, sn.id, e.default)

    # ----- 2、3. 默认值与支持情况 -----

    def classify(self, gt: nx.MultiDiGraph) -> set[str]:
        facts: set[str] = set()
        dead: set[str] = set()  # 目标不支持的对象（子树都不写）
        implicit = set(self.dst_res.implicit)
        kids: dict[str, list[str]] = defaultdict(list)
        parent: dict[str, str] = {}
        for a, b, ed in gt.edges(data=True):
            if ed.get("kind") == "contains":
                kids[a].append(b)
                parent[b] = a
        order: list[str] = []
        stack = [DEVICE]
        while stack:
            x = stack.pop()
            order.append(x)
            stack.extend(reversed(kids.get(x, [])))
        for nid in order:
            if nid == DEVICE:
                continue
            if parent.get(nid) in dead:
                dead.add(nid)
                continue
            d = gt.nodes[nid]
            sn = self.kb.nodes[str(d["schema"])]
            src = self.to_src.get(nid, nid)
            e = self.dst_res.entries.get(sn.id)
            if e is not None and not e.supported:
                self.unsupported.append(
                    _item(
                        "node",
                        "translate.unsupported.profile",
                        src,
                        reason="profile_unsupported",
                        schema=sn.id,
                        value=d.get("key") if d.get("kind") == "object" else d.get("value"),
                        profile=self.dst,
                        lines=list(d.get("lines") or []),
                    )
                )
                if d.get("kind") == "object":
                    dead.add(nid)
                continue
            if d.get("kind") == "object":
                if sn.id in implicit and not any(True for _ in kids.get(nid, [])):
                    # 目标平台被引用即隐式存在的对象（ASR 920 的桥域）：不单独写；没有被引用时提示
                    if not any(ed.get("kind") == "reference" for _, _, ed in gt.in_edges(nid, data=True)):
                        self.warnings.append(
                            _item(
                                "implicit_object",
                                "translate.warn.implicit_object",
                                src,
                                level="info",
                                schema=sn.id,
                                value=d.get("key"),
                                profile=self.dst,
                                lines=list(d.get("lines") or []),
                            )
                        )
                    continue
                if canon.negated_object(self.g, src):
                    continue  # 只由取消形式产生的对象：作为原文列出，不翻译
                facts.add(nid)
                continue
            if not canon.valued(d) or d.get("value") is None:
                continue
            if self.cross_family and _SECRET.search(sn.id.rsplit(".", 1)[-1]):
                # 密码类取值是源平台的密文（或脱敏后的占位），换平台后不能直接用：不写，人工重新设置
                self.unsupported.append(
                    _item(
                        "node",
                        "translate.unsupported.secret",
                        src,
                        reason="secret",
                        schema=sn.id,
                        profile=self.dst,
                        lines=list(d.get("lines") or []),
                    )
                )
                continue
            dd = self.dst_default(gt, sn, parent[nid])
            if dd is not None and canon._same(d.get("value"), dd, sn.type):
                self.defaults.append(
                    _item(
                        "explicit_equals_default",
                        "translate.default.omitted",
                        src,
                        schema=sn.id,
                        value=d.get("value"),
                        profile=self.dst,
                        lines=list(d.get("lines") or []),
                    )
                )
                continue
            facts.add(nid)
        self.dead = dead
        # 源设备依赖默认值的节点
        self.default_counts: Counter[str] = Counter()
        for owner, src_nid, value in self.src_defaults:
            if owner not in gt or owner in dead:
                continue
            sd = self.g.nodes[src_nid]
            sn = self.kb.nodes[str(sd["schema"])]
            e = self.dst_res.entries.get(sn.id)
            if e is not None and not e.supported:
                continue
            dd = self.dst_default(gt, sn, owner)
            if dd is not None and canon._same(value, dd, sn.type):
                self.default_counts["same"] += 1
                continue
            if dd is None:
                self.default_counts["unknown"] += 1
                self.warnings.append(
                    _item(
                        "default_unknown",
                        "translate.warn.default_unknown",
                        src_nid,
                        level="info",
                        schema=sn.id,
                        src_default=value,
                        profile=self.dst,
                    )
                )
                continue
            nid = f"{owner}/{_short(sn.id, gt.nodes[owner].get('schema'))}"
            gt.add_node(
                nid,
                kind="attr",
                schema=sn.id,
                value=value,
                raw=value,
                origin="explicit",
                lines=[],
                cards=[],
                negated=False,
            )
            gt.add_edge(owner, nid, kind="contains")
            self.to_src[nid] = src_nid
            facts.add(nid)
            self.default_counts["differs"] += 1
            self.warnings.append(
                _item(
                    "default_differs",
                    "translate.warn.default_differs",
                    src_nid,
                    level="warning",
                    schema=sn.id,
                    src_default=value,
                    dst_default=dd,
                    profile=self.dst,
                )
            )
        # 目标 Profile 的默认节点（渲染时判断顺带写出的取值是否等于默认值）
        self.builder._defaults()
        return facts

    def extras(self) -> None:
        """源图中不翻译的行：未映射命令、功能域外原文、未识别行（原文块只列块的第一行，附整块的行号）。"""
        stmts = {st.line.no: st for st in self.g.graph.get("statements", [])}
        for nid, d in self.g.nodes(data=True):
            kind = d.get("kind")
            if kind == "object" and canon.negated_object(self.g, nid):
                kind = "negated"
            elif kind not in ("ext", "raw", "unknown"):
                continue
            parent = next((a for a, _, ed in self.g.in_edges(nid, data=True) if ed.get("kind") == "contains"), DEVICE)
            if kind in ("raw", "unknown") and self.g.nodes[parent].get("kind") in ("raw", "unknown"):
                continue
            lines = sorted(d.get("lines") or [])
            block = list(lines)
            stack = list(self.children.get(nid, []))
            while stack:
                x = stack.pop()
                if self.g.nodes[x].get("kind") in ("raw", "unknown"):
                    block += self.g.nodes[x].get("lines") or []
                    stack.extend(self.children.get(x, []))
            st = stmts.get(lines[0]) if lines else None
            text = st.line.text if st else str(d.get("text") or "").strip()
            if kind == "raw" and text in ("#", "!"):
                continue
            self.unsupported.append(
                _item(
                    kind,
                    f"translate.unsupported.{kind}",
                    nid,
                    reason="not_translated",
                    text=text,
                    line=lines[0] if lines else None,
                    owner=parent if parent != DEVICE else None,
                    lines=sorted(set(block)),
                )
            )

    # ----- 5. 校验 -----

    def verify(self, text: str, explained: set[str]) -> dict[str, Any]:
        a = cmp.Side(self.g, "source")
        try:
            b = cmp.side_from_text(text, self.kb, self.dst, "translated")
        except cmp.CompareError as e:  # 译文解析失败（不应出现）
            self.warnings.append(
                _item("verify_failed", "translate.warn.verify_failed", None, level="error", error=e.key)
            )
            return {"checked": False, "equal": False, "diffs": 0, "unexplained": 0}
        r = cmp.compare(a, b, self.kb, interface_map=self.raw_map or None)

        def covered(node: str | None) -> bool:
            if not node:
                return False
            return any(node == x or node.startswith(x + "/") for x in explained)

        unexplained = 0
        for d in r["diffs"]:
            node_a = (d.get("a") or {}).get("node")
            node_b = (d.get("b") or {}).get("node")
            if covered(node_a) or (node_a is None and covered(node_b)):
                continue
            unexplained += 1
            self.warnings.append(
                _item(
                    "verify_diff",
                    "translate.warn.verify_diff",
                    node_a or (d.get("b") or {}).get("node"),
                    level="warning",
                    schema=d.get("schema"),
                    diff=d["kind"],
                    cid=d["node"],
                    src_value=(d.get("a") or {}).get("value"),
                    dst_value=(d.get("b") or {}).get("value"),
                    lines=(d.get("a") or {}).get("lines") or [],
                )
            )
        for u in r["unknown"]["b"]:
            unexplained += 1
            self.warnings.append(
                _item(
                    "verify_unknown",
                    "translate.warn.verify_unknown",
                    None,
                    level="warning",
                    line=u["line"],
                    text=u["text"],
                )
            )
        return {"checked": True, "equal": r["equal"], "diffs": r["summary"]["total"], "unexplained": unexplained}

    def interface_types(self, gt: nx.MultiDiGraph) -> None:
        """接口名的类型不属于目标平台族（knowledge/render 的 interface_types）、又没有映射时告警。"""
        _, style = canon._index(self.kb, self.kb.profiles[self.dst].family)
        types = {t.lower() for t in style["interface_types"]}
        if not types:
            return
        seen: set[str] = set()
        for nid, d in gt.nodes(data=True):
            if d.get("kind") != "object" or d.get("schema") != "interface":
                continue
            name = str(d.get("key") or "")
            m = re.match(r"^(\d+GE|[A-Za-z][A-Za-z\-]*)", name)
            kind = m.group(1) if m else name
            if kind.lower() in types or kind.lower() in seen:
                continue
            seen.add(kind.lower())
            self.warnings.append(
                _item(
                    "interface_type",
                    "translate.warn.interface_type",
                    self.to_src.get(nid, nid),
                    level="warning",
                    name=name,
                    type=kind,
                    family=self.kb.profiles[self.dst].family,
                    lines=list(d.get("lines") or []),
                )
            )

    # ----- 主流程 -----

    def run(self, verify: bool = True) -> dict[str, Any]:
        gt = self.retarget()
        facts = self.classify(gt)
        rendered = canon.render_full(gt, self.kb, self.dst, facts=facts, extras=False)
        uncovered = set(rendered.uncovered)
        parent = {b: a for a, b, d in gt.edges(data=True) if d.get("kind") == "contains"}
        for nid in rendered.uncovered:
            if parent.get(nid) in uncovered:
                continue  # 所属对象已经报了
            d = gt.nodes[nid]
            sub = sum(1 for x in uncovered if x.startswith(nid + "/"))
            self.unsupported.append(
                _item(
                    "node",
                    "translate.unsupported.no_render",
                    self.to_src.get(nid, nid),
                    reason="no_render",
                    schema=d.get("schema"),
                    value=d.get("key") if d.get("kind") == "object" else d.get("value"),
                    profile=self.dst,
                    count=sub,
                    lines=list(d.get("lines") or []),
                )
            )
        self.extras()
        for inf in rendered.inferred:
            self.warnings.append(
                _item(
                    "inferred_value",
                    "translate.warn.inferred_value",
                    inf["node"],
                    level="warning",
                    schema=inf["schema"],
                    value=inf["value"],
                    profile=self.dst,
                )
            )
        self.interface_types(gt)
        text = rendered.text
        explained = {u["node"] for u in self.unsupported if u["node"]}
        explained |= {w["node"] for w in self.warnings if w["node"]}
        check = self.verify(text, explained) if verify else {"checked": False}
        src_family = self.kb.profiles[self.src].family
        stats = {
            "facts": len(facts),
            "rendered": len(rendered.covered),
            "lines": sum(1 for ln in rendered.lines if ln.kind == "command"),
            "unsupported": sum(1 for u in self.unsupported if u["kind"] == "node"),
            "not_translated": sum(1 for u in self.unsupported if u["kind"] != "node"),
            "defaults_omitted": len(self.defaults),
            "default_differs": self.default_counts["differs"],
            "default_unknown": self.default_counts["unknown"],
            "defaults_same": self.default_counts["same"],
            "warnings": len(self.warnings),
        }
        return {
            "source": {
                "device": self.g.graph.get("device"),
                "profile": self.src,
                "family": src_family,
            },
            "target": {"profile": self.dst, "family": self.kb.profiles[self.dst].family},
            "interface_map": self.raw_map,
            "text": text,
            "lines": rendered.line_dicts(),
            "warnings": self.warnings,
            "unsupported": self.unsupported,
            "defaults": self.defaults,
            "stats": stats,
            "verify": check,
        }


def translate(
    g_src: nx.MultiDiGraph,
    kb: KnowledgeBase,
    src_profile: str,
    dst_profile: str,
    interface_map: dict[str, str] | None = None,
    verify: bool = True,
) -> dict[str, Any]:
    """翻译：返回 {text, lines, warnings[], unsupported[], defaults[], stats, verify, source, target}。"""
    return _Translator(g_src, kb, src_profile, dst_profile, interface_map).run(verify)


def translate_text(
    text: str,
    kb: KnowledgeBase,
    dst_profile: str,
    src_profile: str | None = None,
    interface_map: dict[str, str] | None = None,
    device: str = "device",
    verify: bool = True,
) -> dict[str, Any]:
    """配置文本 → 解析建图 → 翻译（CLI、API 共用）。"""
    from lmesh.core import analysis
    from lmesh.core import graph as graphmod

    if dst_profile not in kb.profiles:
        raise TranslateError("parse.profile_unknown", profile=dst_profile)
    try:
        res = analysis.parse_text(text, kb, src_profile)
    except analysis.AnalysisError as e:
        raise TranslateError(str(e), profile=src_profile or "") from e
    g = graphmod.build(res.parsed, kb, res.profile, device)
    return translate(g, kb, res.profile, dst_profile, interface_map, verify)
