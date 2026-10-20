"""M8-3（日常分析组的 AI skill、REQ-042 设备图标）端到端测试用的服务：复用 scripts/e2e_server.py 的 prepare()，
另外导入拓扑样本网络的 5 台设备；独立的数据目录（LMESH_E2E_ROOT，默认 tests/output/e2e-m83-root），配置一个假的 AI（不联网）。
假 AI 按 skill 的系统提示词回复：每个 skill 都有能通过代码校验的建议和编造对象（被拒绝）的建议。
用法（frontend/ 下）：uv run python e2e/m83_server.py --port 9483
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


def _sug(category: str, kind: str, title: str, content: dict[str, Any], refs: list[str]) -> dict[str, Any]:
    return {"category": category, "kind": kind, "title": title, "content": content, "refs": [{"id": r} for r in refs]}


REPLIES: list[tuple[str, dict[str, Any]]] = [
    (
        "handover summary",
        {"suggestions": [_sug("text_only", "summary", "Device summary", {"text": "[[d1]] has <<count.interface>> interfaces."}, ["d1"])]},
    ),
    (
        "tidy up the topology view",
        {
            "suggestions": [
                _sug("view_hint", "role", "d1: access", {"target": "d1", "key": "role", "value": "access", "reason": "[[d1]] is a leaf."}, ["d1"]),
                _sug("view_hint", "group", "d2: Central", {"target": "d2", "key": "group", "value": "Central", "reason": "[[d2]] is central."}, ["d2"]),
                _sug("view_hint", "role", "d9: core", {"target": "d9", "key": "role", "value": "core"}, ["d9"]),
                _sug("peer_link", "peer", "d1 ~ d2", {"a": "d1", "b": "d2", "reason": "[[d1]] and [[d2]] look related."}, ["d1", "d2"]),
            ]
        },
    ),
    (
        "as change intents",
        {
            "suggestions": [
                _sug("refs_exist", "intent", "First change", {"text": "[[c1]] changes the service.", "risk": "medium"}, ["c1"]),
                _sug("refs_exist", "intent", "Test VLAN", {"text": "[[c99]] removes a test VLAN.", "risk": "low"}, ["c99"]),
            ]
        },
    ),
    (
        "fix configuration findings",
        {
            "suggestions": [
                _sug("refs_exist", "explain", "Explain f1", {"text": "[[f1]] needs a look.", "priority": "medium"}, ["f1"]),
                _sug("refs_exist", "explain", "Invented", {"text": "[[f42]] breaks routing.", "priority": "high"}, ["f42"]),
            ]
        },
    ),
    (
        "what a planned change affects",
        {"suggestions": [_sug("text_only", "impact", "Impact", {"text": "Services on [[n1]] are affected; watch [[n1]]."}, ["n1"])]},
    ),
    (
        "differ on one configuration feature",
        {
            "suggestions": [
                _sug("text_only", "feature", "Same command", {"text": "[[p1]] uses [[k1]].", "commands": [{"card": "k1", "text": "no such command 1"}]}, ["k1"]),
            ]
        },
    ),
]


def _fake_ai() -> None:
    from lmesh.core import ai

    os.environ["LMESH_AI__PROVIDER"] = "openai"
    os.environ["LMESH_AI__BASE_URL"] = "http://127.0.0.1:1/v1"
    os.environ["LMESH_AI__MODEL"] = "fake-model"

    def hook(conn: Any, m: str, system: str, prompt: str) -> Any:
        text = next((json.dumps(r) for k, r in REPLIES if k in system), "{}")
        return ai.Reply(text, m or "fake-model", 1200, 80)

    ai.provider_hook = hook


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9483)
    a = ap.parse_args()
    import e2e_server  # scripts/e2e_server.py

    root = Path(os.environ.get("LMESH_E2E_ROOT") or ROOT / "tests" / "output" / "e2e-m83-root").resolve()
    e2e_server.prepare(root)
    from lmesh.core import config, importer, kbservice, projects
    from lmesh.core.kb import read_yaml

    s = config.load()
    url = s.database_url
    topo = ROOT / "knowledge" / "samples" / "topology"
    files = [m["file"] for m in read_yaml(topo / "manifest.yaml")["samples"]]
    admin = projects.cli_identity(url, "e2e-admin")
    with projects.use(projects.default_scope(url, admin), admin):
        importer.import_sources([(f, (topo / f).read_bytes()) for f in files], url, "basic", kbservice.runtime_root(s))
    _fake_ai()
    import uvicorn

    from lmesh.api import create_app

    uvicorn.run(create_app(config.load()), host="127.0.0.1", port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
