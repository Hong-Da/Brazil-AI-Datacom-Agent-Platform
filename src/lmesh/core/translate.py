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
       密码类取值（Schema 节点名为 password / secret，或节点标了 secret: true，例如 SNMP 团体字）跨平台族时不写 → unsupported[]（reason=secret），人工重新设置；
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

# 密码类属性（按 Schema 节点名）：跨平台族时不翻译取值；名称看不出来的（团体字、共享密钥）在 Schema 上标 secret: true
_SECRET = re.compile(r"(^|_)(password|secret)$")


def is_secret(sn: SchemaNode) -> bool:
    return sn.secret or bool(_SECRET.search(sn.id.rsplit(".", 1)[-1]))


def _contains_parent(g: nx.MultiDiGraph, nid: str) -> str | None:
    return next((a for a, _, d in g.in_edges(nid, data=True) if d.get("kind") == "contains"), None)


def _move(g: nx.MultiDiGraph, old: str, new: str, new_parent: str, ren: dict[str, str]) -> None:
    """把节点 old 及其子树改挂到 new_parent 下、编号改为 new（依赖边随节点一起改名）。"""
    sub = [n for n in g.nodes if n == old or n.startswith(old + "/")]
    mapping_ = {n: new + n[len(old) :] for n in sub}
    parent = _contains_parent(g, old)
    nx.relabel_nodes(g, mapping_, copy=False)
    if parent is not None:
        for k, d in list(g.get_edge_data(parent, new, default={}).items()):
            if d.get("kind") == "contains":
                g.remove_edge(parent, new, key=k)
    g.add_edge(new_parent, new, kind="contains")
    for a, b in mapping_.items():
        ren[a] = b


def _attr(g: nx.MultiDiGraph, nid: str) -> dict[str, Any] | None:
    d = g.nodes.get(nid)
    return d if d is not None and d.get("kind") == "attr" else None


def _add(g: nx.MultiDiGraph, parent: str, nid: str, kind: str, schema: str, lines: list[int], **attrs: Any) -> None:
    g.add_node(nid, kind=kind, schema=schema, origin="explicit", cards=[], lines=list(lines), **attrs)
    g.add_edge(parent, nid, kind="contains")


def _set_attr(g: nx.MultiDiGraph, owner: str, name: str, schema: str, value: Any, lines: list[int], src: str) -> str:
    """新建属性节点（reshaped_from 记来源节点的原编号）。"""
    nid = f"{owner}/{name}"
    if nid not in g:
        _add(g, owner, nid, "attr", schema, lines, value=value, raw=value, negated=False, reshaped_from=src)
    return nid


def _drop_if_empty(g: nx.MultiDiGraph, nid: str, ren: dict[str, str], to: str) -> None:
    """接入点移走后只剩默认值（或未映射命令、原文）的接口一并去掉：只为承载接入点而存在的子接口 / 父接口。"""
    rest = [c for _, c, d in g.out_edges(nid, data=True) if d.get("kind") == "contains"]
    if all(g.nodes[c].get("origin") == "default" or g.nodes[c].get("kind") in ("ext", "raw", "unknown") for c in rest):
        ren[nid] = to
        g.remove_nodes_from([n for n in list(g.nodes) if n == nid or n.startswith(nid + "/")])


def reshape_access(g: nx.MultiDiGraph, to_form: str) -> dict[str, str]:
    """业务接入点在两种形态间换结构（就地修改图，返回 {旧编号: 新编号}；新建的节点带 reshaped_from = 来源节点的原编号）：

    subinterface（华为）：接入点是子接口 interface[P.N]/access[N]——二层子接口（interface.l2 = true，封装、
                          rewrite、桥域在接入点上），或终结 VLAN 的子接口（vlan-type dot1q V）上的伪线；描述在子接口上；
    instance（Cisco）：   接入点是父接口下的业务实例 interface[P]/access[N]，封装与描述都在接入点上。
    接入点编号两边相同（子接口编号 = 实例编号）；主接口上的接入点（编号 "_"，端口模式）两边一样，不换。
    """
    ren: dict[str, str] = {}
    accesses = [n for n, d in g.nodes(data=True) if d.get("schema") == "interface.access" and d.get("kind") == "object"]
    for acc in accesses:
        key = str(g.nodes[acc].get("key"))
        parent = _contains_parent(g, acc)
        if parent is None or key in ("_", "") or g.nodes[parent].get("schema") != "interface":
            continue
        pkey = str(g.nodes[parent].get("key"))
        base, dot, sub = pkey.rpartition(".")
        lines = list(g.nodes[acc].get("lines") or [])
        if to_form == "instance" and dot and sub == key:
            l2 = _attr(g, f"{parent}/l2")
            is_l2 = bool(l2 and l2.get("value") is True and not l2.get("negated"))
            vlan = _attr(g, f"{parent}/dot1q_termination")
            top = f"interface[{base}]"
            new = f"{top}/access[{key}]"
            if not (is_l2 or vlan) or new in g:
                continue
            if top not in g:
                _add(
                    g, _contains_parent(g, parent) or DEVICE, top, "object", "interface",
                    list(g.nodes[parent].get("lines") or []), key=base, raw=base, reshaped_from=parent,
                )  # fmt: skip
            _move(g, acc, new, top, ren)
            desc = f"{parent}/description"
            if _attr(g, desc) and f"{new}/description" not in g:
                _move(g, desc, f"{new}/description", new, ren)
                g.nodes[f"{new}/description"]["schema"] = "interface.access.description"
            if vlan is not None and f"{new}/encapsulation" not in g:
                # 终结 VLAN 的子接口 → 业务实例匹配这个 VLAN（encapsulation dot1q V）
                vid, vlines = vlan.get("value"), list(vlan.get("lines") or [])
                old = f"{parent}/dot1q_termination"
                ren[old] = _set_attr(g, new, "vlan", "interface.access.vlan", vid, vlines, old)
                _set_attr(g, new, "encapsulation", "interface.access.encapsulation", "dot1q", vlines, old)
                g.remove_node(f"{parent}/dot1q_termination")
            if is_l2:
                ren[f"{parent}/l2"] = new
                g.remove_node(f"{parent}/l2")
            _drop_if_empty(g, parent, ren, new)
        elif to_form == "subinterface" and not dot:
            name = f"{pkey}.{key}"
            subif = f"interface[{name}]"
            new = f"{subif}/access[{key}]"
            if new in g:
                continue
            if subif not in g:  # 排在原来业务实例的位置
                _add(
                    g, _contains_parent(g, parent) or DEVICE, subif, "object", "interface", lines,
                    key=name, raw=name, reshaped_from=acc,
                )  # fmt: skip
            _set_attr(g, subif, "l2", "interface.l2", True, [], acc)
            _move(g, acc, new, subif, ren)
            desc = f"{new}/description"
            if _attr(g, desc) and f"{subif}/description" not in g:
                _move(g, desc, f"{subif}/description", subif, ren)
                g.nodes[f"{subif}/description"]["schema"] = "interface.description"
            _drop_if_empty(g, parent, ren, subif)
    return ren


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
        self.secret_shells: set[str] = set()  # 只装着敏感对象的占位对象（源图编号）：不写，校验时视为已说明

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

    def secret_item(self, src: str, sn: SchemaNode, d: dict[str, Any]) -> dict[str, Any]:
        """敏感取值不写（参数里不带取值本身）。"""
        return _item(
            "node",
            "translate.unsupported.secret",
            src,
            reason="secret",
            schema=sn.id,
            profile=self.dst,
            lines=list(d.get("lines") or []),
        )

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
                if self.cross_family and sn.secret:
                    # 键本身是敏感内容（SNMP 团体字）：对象整棵子树都不写，人工重新设置
                    self.unsupported.append(self.secret_item(src, sn, d))
                    dead.add(nid)
                    continue
                facts.add(nid)
                continue
            if not canon.valued(d) or d.get("value") is None:
                continue
            if self.cross_family and is_secret(sn):
                # 密码类取值是源平台的密文（或脱敏后的占位），换平台后不能直接用：不写，人工重新设置
                self.unsupported.append(self.secret_item(src, sn, d))
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
        # 敏感对象（团体字）不写之后，只剩空壳的占位父对象（mgmt.snmp[_]）也不写，免得为了写出它编造别的命令
        for nid in [
            n for n in dead if gt.nodes[n].get("kind") == "object" and self.kb.nodes[str(gt.nodes[n]["schema"])].secret
        ]:
            p = parent.get(nid)
            if p in facts and gt.nodes[p].get("key") in ("_", "") and not any(c in facts for c in kids.get(p, [])):
                facts.discard(p)
                self.secret_shells.add(self.to_src.get(p, p))
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
        back: dict[str, str] = {}  # 换结构后的编号 → 源图中的编号
        src_form, dst_form = self.forms()
        if src_form and dst_form and src_form != dst_form:
            # 源图按目标平台族的接入点形态换结构后再对比（单向换，不要求两种形态互逆）
            ga = self.g.copy()
            ren = reshape_access(ga, dst_form)
            back = {new: old for old, new in ren.items() if new in ga}
            back.update({n: d["reshaped_from"] for n, d in ga.nodes(data=True) if d.get("reshaped_from")})
            a = cmp.Side(ga, "source")
        r = cmp.compare(a, b, self.kb, interface_map=self.raw_map or None)

        def covered(node: str | None) -> bool:
            if not node:
                return False
            node = back.get(node, node)
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

    def forms(self) -> tuple[str, str]:
        """源、目标平台族的接入点形态（knowledge/render 的 access_form）。"""
        fam = self.kb.profiles
        src = canon._index(self.kb, fam[self.src].family)[1]["access_form"]
        dst = canon._index(self.kb, fam[self.dst].family)[1]["access_form"]
        return src, dst

    def reshape(self, gt: nx.MultiDiGraph) -> None:
        """源、目标平台族的接入点形态不同时换结构（华为二层子接口 ↔ Cisco 业务实例）。"""
        src_form, dst_form = self.forms()
        if not (src_form and dst_form and src_form != dst_form):
            return
        ren = reshape_access(gt, dst_form)
        old_src = dict(self.to_src)
        for old, new in ren.items():
            self.to_src.pop(old, None)
            if old in old_src and new not in self.to_src:
                self.to_src[new] = old_src[old]
        for n, d in gt.nodes(data=True):
            if d.get("reshaped_from") in old_src:
                self.to_src[n] = old_src[d["reshaped_from"]]
        self.src_defaults = [(ren.get(o, o), s, v) for o, s, v in self.src_defaults]

    def run(self, verify: bool = True) -> dict[str, Any]:
        gt = self.retarget()
        self.reshape(gt)
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
        explained = {u["node"] for u in self.unsupported if u["node"]} | self.secret_shells
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
