"""M8-5（规范与合规、知识库构建、报告）端到端测试用的服务：复用 scripts/e2e_server.py 的 prepare()，独立的数据目录
（LMESH_E2E_ROOT，默认 tests/output/e2e-m85-root），配置一个假的本地模型（provider local，不联网），按 skill 的系统提示词回复：
规范转规则给一条能试跑的规则与一条用了 Schema 中没有的节点的规则（被拒绝）；基线例外说明两段文字；脱敏复核标出提示里第一条描述的取值；
命令卡审核助手一条标注；报告摘要中英文两段（数字用 <<键>>）和一条写了数字的（被拒绝）。
用法（frontend/ 下）：uv run python e2e/m85_server.py --port 9485
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

RULE = """id: std.interface_l3_description
target: interface
when: {exists: ipv4}
assert: {exists: description}
severity: warning
title: {zh-CN: 三层接口没有描述, en: Layer 3 interface without description, pt-BR: Interface L3 sem descrição}
message: {zh-CN: "接口 {key} 没有描述", en: "Interface {key} has no description", pt-BR: "A interface {key} não tem descrição"}
suggestion: {zh-CN: 写明对端设备与端口, en: Name the peer device and port, pt-BR: Cite o dispositivo e a porta do par}
"""


def _rules(prompt: str) -> dict[str, Any]:
    sid = (re.search(r"^(s\d+) \|", prompt, re.M) or ["", "s1"])[1]
    bad = RULE.replace("std.interface_l3_description", "std.storm_control").replace("description}", "storm_control}")
    return {
        "suggestions": [
            {
                "category": "kb_review",
                "kind": "rule",
                "title": "4.2.1 → Layer 3 interfaces need a description",
                "content": {"review_kind": "rule", "target": "std.interface_l3_description", "payload": {"yaml": RULE}},
                "refs": [{"id": sid}],
            },
            {
                "category": "kb_review",
                "kind": "rule",
                "title": "4.4 → Storm control",
                "content": {"review_kind": "rule", "target": "std.storm_control", "payload": {"yaml": bad}},
                "refs": [{"id": sid}],
            },
        ]
    }


def _sanitize(prompt: str) -> dict[str, Any]:
    m = re.search(r"^\s*(\d+)\s+.*?description (\S+)", prompt, re.M)
    if not m:
        return {"suggestions": []}
    n, text = int(m.group(1)), m.group(2)
    return {
        "suggestions": [
            {
                "category": "sanitize_rule",
                "kind": "site",
                "title": f"L{n}: site name",
                "content": {"line": n, "text": text, "kind": "site", "explain": "A site name in a description."},
                "refs": [{"line": n, "of": "d1"}],
            },
            {
                "category": "sanitize_rule",
                "kind": "customer",
                "title": f"L{n}: customer",
                "content": {"line": n, "text": "ACME-Bank", "kind": "customer"},
                "refs": [{"line": n, "of": "d1"}],
            },
        ]
    }


SUMMARY = {
    "suggestions": [
        {
            "category": "text_only",
            "kind": "zh-CN",
            "title": "摘要",
            "content": {"text": "[[d1]] 共有 <<findings.total>> 个问题。"},
            "refs": [{"id": "d1"}],
        },
        {
            "category": "text_only",
            "kind": "en",
            "title": "Summary",
            "content": {"text": "[[d1]] has <<findings.total>> issues."},
            "refs": [{"id": "d1"}],
        },
        {
            "category": "text_only",
            "kind": "en",
            "title": "Conclusion",
            "content": {"text": "[[d1]] is 96% compliant."},
            "refs": [{"id": "d1"}],
        },
    ]
}
WAIVER = {
    "suggestions": [
        {
            "category": "text_only",
            "kind": "reason",
            "title": "Reason",
            "content": {"text": "[[d1]] cannot meet [[r1]] until the migration window."},
            "refs": [{"id": "r1"}],
        },
        {
            "category": "text_only",
            "kind": "compensating",
            "title": "Controls",
            "content": {"text": "Restrict management access to [[d1]] and review the waiver after the migration."},
            "refs": [{"id": "r1"}],
        },
    ]
}
CARD = {
    "suggestions": [
        {
            "category": "text_only",
            "kind": "default",
            "title": "Check the default",
            "content": {"text": "[[f1]] needs a check against the document."},
            "refs": [{"id": "f1"}],
        },
    ]
}


def _fake_ai() -> None:
    from lmesh.core import ai

    os.environ["LMESH_AI__PROVIDER"] = "local"
    os.environ["LMESH_AI__BASE_URL"] = "http://127.0.0.1:1/v1"
    os.environ["LMESH_AI__MODEL"] = "fake-local"

    def hook(conn: Any, m: str, system: str, prompt: str) -> Any:
        if "configuration standards into check rules" in system:
            data: Any = _rules(prompt)
        elif "waiver request" in system:
            data = WAIVER
        elif "already sanitized by rules" in system:
            data = _sanitize(prompt)
        elif "review ONE router command card" in system:
            data = CARD
        elif "summary at the top of a network" in system:
            data = SUMMARY
        else:
            data = {"suggestions": []}
        return ai.Reply(json.dumps(data), m or "fake-local", 900, 60)

    ai.provider_hook = hook


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9485)
    a = ap.parse_args()
    import e2e_server  # scripts/e2e_server.py

    e2e_server.prepare(Path(os.environ.get("LMESH_E2E_ROOT") or ROOT / "tests" / "output" / "e2e-m85-root").resolve())
    _fake_ai()
    import uvicorn

    from lmesh.api import create_app
    from lmesh.core import config

    uvicorn.run(create_app(config.load()), host="127.0.0.1", port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
