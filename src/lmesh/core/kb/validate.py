"""知识库校验：格式、编号唯一、引用完整、继承无环、语法正确、映射的参数在语法中存在。"""

from __future__ import annotations

import contextlib

from lmesh.core.kb import KnowledgeBase, mapping
from lmesh.core.kb import syntax as syn
from lmesh.core.kb.model import DEP_KINDS, NODE_TYPES, SHOW_RULES, STATUSES, Issue


def validate(kb: KnowledgeBase) -> list[Issue]:
    issues: list[Issue] = list(kb.load_issues)

    def err(code: str, msg: str, file: str = "") -> None:
        issues.append(Issue("error", code, msg, file))

    def warn(code: str, msg: str, file: str = "") -> None:
        issues.append(Issue("warning", code, msg, file))

    # Schema 节点
    for n in kb.nodes.values():
        if n.parent and n.parent not in kb.nodes:
            err("node.parent_missing", f"{n.id} 的父节点 {n.parent} 不存在")
        if n.type not in NODE_TYPES:
            err("node.type", f"{n.id} 的类型 {n.type} 不在 {', '.join(NODE_TYPES)} 中")
        if n.type == "ref" and (not n.ref or n.ref not in kb.nodes):
            err("node.ref_missing", f"{n.id} 引用的对象类型 {n.ref} 不存在")
        if n.deprecated and n.replaced_by and n.replaced_by not in kb.nodes:
            err("node.replaced_missing", f"{n.id} 的替代节点 {n.replaced_by} 不存在")
        if not n.semantic:
            warn("node.no_semantic", f"{n.id} 没有语义说明（按语义归并，不按命令名）")
        if n.status not in STATUSES:
            err("status", f"{n.id} 的状态 {n.status} 不合法")
    # 父子成环
    for n in kb.nodes.values():
        seen, cur = set(), n.parent
        while cur:
            if cur in seen or cur == n.id:
                err("node.cycle", f"{n.id} 的父节点链成环")
                break
            seen.add(cur)
            cur = kb.nodes[cur].parent if cur in kb.nodes else None

    for d in kb.deps:
        if d.kind not in DEP_KINDS:
            err("dep.kind", f"依赖类型 {d.kind} 不合法（{', '.join(DEP_KINDS)}）")
        for end in (d.src, d.dst):
            if end not in kb.nodes:
                err("dep.node_missing", f"依赖规则引用的节点 {end} 不存在")
        if d.note.missing():
            warn(
                "dep.note_lang",
                f"依赖规则 {d.src} → {d.dst} 的说明缺少语言：{', '.join(d.note.missing())}（界面回退显示）",
                f"schema/{d.domain}.yaml" if d.domain else "",
            )

    # 平台族与视图
    for fam in kb.families.values():
        if fam.root_view not in fam.views:
            err("family.root_view", f"平台族 {fam.id} 的根视图 {fam.root_view} 没有定义")
        for v in fam.views.values():
            if v.parent and v.parent not in fam.views:
                err("view.parent_missing", f"{fam.id} 视图 {v.id} 的父视图 {v.parent} 不存在")
            for cid in v.enter:
                if cid not in kb.cards:
                    err("view.enter_missing", f"{fam.id} 视图 {v.id} 的进入命令卡 {cid} 不存在")

    # 命令卡
    for c in kb.cards.values():
        try:
            params = set(c.parsed.params())
        except syn.SyntaxErrorKB as e:
            err("card.syntax", f"{c.id}：{e}", c.file)
            continue
        cfam = kb.families.get(c.family)
        if cfam and c.view not in cfam.views:
            err("card.view_missing", f"{c.id} 所在视图 {c.view} 没有在 {c.family}/views.yaml 中定义", c.file)
        if cfam and c.enters_view and c.enters_view not in cfam.views:
            err("card.enters_missing", f"{c.id} 进入的视图 {c.enters_view} 没有定义", c.file)
        if c.undo:  # 取消语法里另有的参数（例如并入的 undo rule <rule-id> [ to <end-rule-id> ]）也算用到
            with contextlib.suppress(syn.SyntaxErrorKB):
                params |= set(syn.parse(c.undo).params())
        for pname in c.params:
            if pname not in params:
                warn("card.param_unused", f"{c.id} 定义了参数 {pname}，但语法中没有", c.file)
        for target, expr in c.maps.items():
            for t in mapping.parse_target(target):
                if t.node not in kb.nodes:
                    err("card.map_node", f"{c.id} 映射到的节点 {t.node} 不存在", c.file)
                for obj in t.fixed:
                    if obj not in kb.nodes:
                        err("card.map_node", f"{c.id} 映射路径中的对象 {obj} 不存在", c.file)
            # 一条映射规则会套到同一命令的多个变体上，参数名可能不同（$a||$b）：只要有一个存在即可
            used = mapping.params_in_expr(expr)
            if used and not used & params:
                err("card.map_param", f"{c.id} 映射表达式用到的参数 {', '.join(sorted(used))} 都不在语法中", c.file)
        if c.status not in STATUSES:
            err("status", f"{c.id} 的状态 {c.status} 不合法", c.file)
        if c.status != "rejected" and not c.maps:
            warn("card.unmapped", f"{c.id} 还没有映射到 Schema 节点", c.file)
        if c.syntax.split()[0].lower() in ("undo", "no"):
            warn("card.negative", f"{c.id} 以 undo / no 开头：一般作为 undo 字段，而不是单独的命令卡", c.file)

    # Profile
    for p in kb.profiles.values():
        if p.family and p.family not in kb.families:
            err("profile.family", f"{p.id} 的平台族 {p.family} 不存在", p.file)
        if p.inherits and p.inherits not in kb.profiles:
            err("profile.inherits_missing", f"{p.id} 继承的 {p.inherits} 不存在", p.file)
        chain: list[str] = []
        cur = p.id
        while cur in kb.profiles:
            if cur in chain:
                err("profile.cycle", f"{p.id} 的继承链成环：{' → '.join([*chain, cur])}", p.file)
                break
            chain.append(cur)
            cur = kb.profiles[cur].inherits or ""
        for node, entry in p.entries.items():
            if node not in kb.nodes:
                err("profile.node_missing", f"{p.id} 的条目 {node} 不在 Schema 中", p.file)
            if entry.show_rule not in SHOW_RULES:
                err("profile.show_rule", f"{p.id} / {node} 的显示规则 {entry.show_rule} 不合法", p.file)
            for cid in entry.cards:
                if cid not in kb.cards:
                    err("profile.card_missing", f"{p.id} / {node} 引用的命令卡 {cid} 不存在", p.file)
                elif p.family and kb.cards[cid].family != p.family:
                    err("profile.card_family", f"{p.id} / {node} 引用了其他平台族的命令卡 {cid}", p.file)
        for d in p.side_effects:
            for end in (d.src, d.dst):
                if end not in kb.nodes:
                    err("profile.side_effect_node", f"{p.id} 的副作用规则引用的节点 {end} 不存在", p.file)
            if d.note.missing():
                warn(
                    "profile.side_effect_note_lang",
                    f"{p.id} 的副作用规则 {d.src} → {d.dst} 的说明缺少语言：{', '.join(d.note.missing())}",
                    p.file,
                )

    # 配置分层（REQ-034）：新增的对象类型要在 layers.yaml 归层
    from lmesh.core import layers

    for code, msg in layers.problems(kb, layers.load(kb.root), check_nodes=(kb.root / layers.FILE).exists()):
        warn(code, msg, layers.FILE)
    return issues


def summary(issues: list[Issue]) -> dict[str, int]:
    return {"errors": sum(i.level == "error" for i in issues), "warnings": sum(i.level == "warning" for i in issues)}
