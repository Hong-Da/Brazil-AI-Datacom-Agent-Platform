"""M8-2（AI 建议框架）端到端测试用的服务：复用 scripts/e2e_server.py 的 prepare()，独立的数据目录
（LMESH_E2E_ROOT，默认 tests/output/e2e-m82-root），配置一个假的 AI（不联网）：
设备摘要只用代码给出的编号与数字；拓扑角色给出 d1、d2 两条合法建议和一条编造设备 d9 的建议（被代码拒绝）。
用法（frontend/ 下）：uv run python e2e/m82_server.py --port 9382
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

SUMMARY = {
    "suggestions": [
        {
            "category": "text_only",
            "kind": "summary",
            "title": "Device summary",
            "content": {"text": "[[d1]] has <<count.interface>> interfaces; the first object is [[n1]]."},
            "refs": [{"id": "n1"}],
        }
    ]
}
ROLES = {
    "suggestions": [
        {
            "category": "view_hint",
            "kind": "role",
            "title": f"{t}: {v}",
            "content": {"target": t, "key": "role", "value": v, "reason": f"[[{t}]] fits the {v} role."},
            "refs": [{"id": t}],
        }
        for t, v in (("d1", "access"), ("d2", "pe"), ("d9", "core"))
    ]
}


def _fake_ai() -> None:
    from lmesh.core import ai

    os.environ["LMESH_AI__PROVIDER"] = "openai"
    os.environ["LMESH_AI__BASE_URL"] = "http://127.0.0.1:1/v1"
    os.environ["LMESH_AI__MODEL"] = "fake-model"

    def hook(conn: Any, m: str, system: str, prompt: str) -> Any:
        if "handover summary" in system:
            text = json.dumps(SUMMARY)
        elif "topology" in system:
            text = json.dumps(ROLES)
        else:
            text = "{}"
        return ai.Reply(text, m or "fake-model", 1200, 80)

    ai.provider_hook = hook


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9382)
    a = ap.parse_args()
    import e2e_server  # scripts/e2e_server.py

    e2e_server.prepare(Path(os.environ.get("LMESH_E2E_ROOT") or ROOT / "tests" / "output" / "e2e-m82-root").resolve())
    _fake_ai()
    import uvicorn

    from lmesh.api import create_app
    from lmesh.core import config

    uvicorn.run(create_app(config.load()), host="127.0.0.1", port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
