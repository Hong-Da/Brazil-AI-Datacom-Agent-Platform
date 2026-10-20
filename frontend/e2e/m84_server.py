"""M8-4（变更与割接组 AI skill）端到端测试用的服务：复用 scripts/e2e_server.py 的 prepare()，独立的数据目录
（LMESH_E2E_ROOT，默认 tests/output/e2e-m84-root），配置一个假的 AI（不联网），按提示词里代码给出的编号回复：
变更意图转脚本——改第一个物理接口的描述（通过）与改一个编造的对象 n999（被拒绝）；割接方案——概述（中英双语，通过）与
一节直接写出命令的回退（被拒绝）；翻译未支持项——第一项“无对应”（通过）与编造的 u999（被拒绝）；命名映射与模板提取各一条。
用法（frontend/ 下）：uv run python e2e/m84_server.py --port 9484
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def _rows(prompt: str, prefix: str) -> list[list[str]]:
    return [[x.strip() for x in ln.split("|")] for ln in prompt.splitlines() if ln.startswith(prefix) and " | " in ln]


def _intent(prompt: str) -> dict[str, Any]:
    ifs = [
        r for r in _rows(prompt, "n") if len(r) > 2 and r[1] == "interface" and "." not in r[2] and "Loop" not in r[2]
    ]
    n = ifs[0][0] if ifs else "n1"
    ok = {"op": "set", "target": n, "attr": "interface.description", "value": "AI-E2E-DESC"}
    bad = {"op": "set", "target": "n999", "attr": "interface.mtu", "value": 1500}
    return {
        "suggestions": [
            {
                "category": "graph_edit",
                "kind": "edit",
                "title": f"Describe [[{n}]]",
                "content": {"edits": [ok]},
                "refs": [{"id": n}],
            },
            {
                "category": "graph_edit",
                "kind": "edit",
                "title": "MTU",
                "content": {"edits": [bad]},
                "refs": [{"id": n}],
            },
        ]
    }


def _cutover(prompt: str) -> dict[str, Any]:
    sec = {
        "section": "overview",
        "zh": "本次割接把 [[d1]] 换成 [[d2]]，共 <<steps>> 步。",
        "en": "Replace [[d1]] with [[d2]] in <<steps>> steps.",
    }
    bad = {"section": "rollback", "zh": "回退时执行 reset bgp all。", "en": "Run reset bgp all."}
    return {
        "suggestions": [
            {
                "category": "plan_section",
                "kind": "overview",
                "title": "Overview",
                "content": sec,
                "refs": [{"id": "d1"}],
            },
            {
                "category": "plan_section",
                "kind": "rollback",
                "title": "Rollback",
                "content": bad,
                "refs": [{"id": "d1"}],
            },
        ]
    }


def _gap(prompt: str) -> dict[str, Any]:
    items = _rows(prompt, "u")
    raw = [r for r in items if len(r) > 2 and r[2] in ("raw", "ext", "unknown")] or items
    u = raw[0][0] if raw else "u1"
    return {
        "suggestions": [
            {
                "category": "translate_eq",
                "kind": "none",
                "title": "No equivalent",
                "content": {"item": u, "config": "", "reason": "Not needed on [[d1]]'s replacement."},
                "refs": [{"id": u}],
            },
            {
                "category": "translate_eq",
                "kind": "equivalent",
                "title": "Invented",
                "content": {"item": "u999", "config": "end"},
                "refs": [{"id": "u999"}],
            },
        ]
    }


def _naming(prompt: str) -> dict[str, Any]:
    rule = {"type": "vrf.instance", "match": "wildcard", "from": "*", "to": "VRF_{1}"}
    c = {"names": [rule], "ports": [], "naming": [], "explain": "Prefix VRF names of [[d1]]."}
    return {
        "suggestions": [
            {"category": "naming_rules", "kind": "rules", "title": "VRF prefix", "content": c, "refs": [{"id": "d1"}]}
        ]
    }


def _template(prompt: str) -> dict[str, Any]:
    draft = prompt.split("Template draft from code:\n", 1)[-1].split("\n\nCandidate variables", 1)[0]
    c = {"template": draft, "explain": "The draft from code as is."}
    return {
        "suggestions": [
            {
                "category": "template_draft",
                "kind": "template",
                "title": "Template",
                "content": c,
                "refs": [{"id": "d1"}],
            }
        ]
    }


def _fake_ai() -> None:
    from lmesh.core import ai

    os.environ["LMESH_AI__PROVIDER"] = "openai"
    os.environ["LMESH_AI__BASE_URL"] = "http://127.0.0.1:1/v1"
    os.environ["LMESH_AI__MODEL"] = "fake-model"

    def hook(conn: Any, m: str, system: str, prompt: str) -> Any:
        if "change request for ONE router" in system:
            data = _intent(prompt)
        elif "cutover plan" in system:
            data = _cutover(prompt)
        elif "translate router configuration lines" in system:
            data = _gap(prompt)
        elif "naming rules" in system:
            data = _naming(prompt)
        elif "template draft extracted by code" in system:
            data = _template(prompt)
        else:
            data = {"suggestions": []}
        return ai.Reply(json.dumps(data), m or "fake-model", 1200, 80)

    ai.provider_hook = hook


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9484)
    a = ap.parse_args()
    import e2e_server  # scripts/e2e_server.py

    e2e_server.prepare(Path(os.environ.get("LMESH_E2E_ROOT") or ROOT / "tests" / "output" / "e2e-m84-root").resolve())
    _fake_ai()
    import uvicorn

    from lmesh.api import create_app
    from lmesh.core import config

    uvicorn.run(create_app(config.load()), host="127.0.0.1", port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
