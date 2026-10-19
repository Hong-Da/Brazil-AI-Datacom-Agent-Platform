"""生成前端显示风格的对照数据 frontend/src/terms/golden.json（REQ-026）。

前端 src/terms/terms.ts 用 TypeScript 重写了 lmesh.core.terms 的渲染逻辑；这里用 Python 版对知识库样本建图，
记下每个节点在三种风格下的命令写法与顶层对象的配置上下文（M7-5），前端测试（terms.test.ts）逐条比对，保证两边一致。
术语表或 Schema 改动后重新运行：uv run python scripts/terms_golden.py
"""

from __future__ import annotations

import json
from pathlib import Path

from lmesh.core import analysis, terms
from lmesh.core import graph as graphmod
from lmesh.core.kb import load

ROOT = Path(__file__).resolve().parent.parent
KB_ROOT = ROOT / "knowledge"
SAMPLES = [
    ("huawei-atn-v800r023/atn-access-01.cfg", "huawei-atn-v800r023"),
    ("cisco-iosxe-asr920-synthetic/pe-asr920-01.cfg", None),
    ("nokia-sros-classic-synthetic/classic-pe-services.cfg", None),
    ("nokia-sros-classic-synthetic/classic-pe-routing-mgmt.cfg", None),
    ("nokia-sros-classic-synthetic/classic-pe-basic.cfg", None),
    ("nokia-sros-md-synthetic/md-pe-services.cfg", None),
]
EXTRA_IDS = [
    "bgp.instance[65000]/bgp.af[afi=ipv4,vrf=]/peer[RR]/export_policy",
    "interface[Gi0/0/1]/ospf[_]/cost",
    "interface[GigabitEthernet0/2/1]/ospf[_]/cost",
    "device",
    "raw[12]",
]


def main() -> None:
    kb = load(KB_ROOT)
    t = terms.load(KB_ROOT, kb)
    nodes = []
    contexts = []
    for rel, profile in SAMPLES:
        text = (KB_ROOT / "samples" / rel).read_text(encoding="utf-8")
        res = analysis.parse_text(text, kb, profile) if profile else analysis.parse_text(text, kb)
        g = graphmod.build(res.parsed, kb, res.profile)
        for nid, d in g.nodes(data=True):
            if d.get("kind") in ("object", "attr"):
                nodes.append((nid, d.get("schema"), d.get("key"), d.get("kind")))
            if (
                d.get("kind") == "object"
                and "/" not in terms.split_node_id(nid)[-1][0]
                and len(terms.split_node_id(nid)) == 1
            ):
                attrs = {
                    terms.split_node_id(c)[-1][0]: g.nodes[c].get("value")
                    for c in g.successors(nid)
                    if g.nodes[c].get("kind") == "attr"
                }
                ctx = {"schema": d.get("schema"), "key": d.get("key"), "attrs": attrs}
                contexts.append({**ctx, **{s: t.context(d["schema"], d.get("key"), attrs, s) for s in terms.STYLES}})
    labels, describes = [], []
    for nid, schema, key, kind in nodes:
        describes.append({"id": nid, **{s: terms.describe(nid, kb, t, s) for s in terms.STYLES}})
        if kind == "object" and schema:
            labels.append({"schema": schema, "key": key, **{s: t.label(schema, key, s) for s in terms.STYLES}})
    for nid in EXTRA_IDS:
        describes.append({"id": nid, **{s: terms.describe(nid, kb, t, s) for s in terms.STYLES}})
    schema = {
        "ids": sorted(kb.nodes),
        "keyNames": {nid: list(n.key) for nid, n in kb.nodes.items() if n.type == "object" and len(n.key) == 1},
    }
    out = {"terms": t.as_dict(), "schema": schema, "labels": labels, "describes": describes, "contexts": contexts}
    dest = ROOT / "frontend" / "src" / "terms" / "golden.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=str) + "\n", encoding="utf-8")
    print(f"{dest}: {len(labels)} labels, {len(describes)} describes, {len(contexts)} contexts")


if __name__ == "__main__":
    main()
