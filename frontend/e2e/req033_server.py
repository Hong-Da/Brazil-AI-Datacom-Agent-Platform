"""REQ-033 端到端测试用的服务：复用 scripts/e2e_server.py 的 prepare()，但用独立的数据目录（默认 tests/output/e2e-req033-root），
不与其他 e2e（共享的 tests/output/e2e-root）冲突；不要求前端已构建（页面由 Vite 开发服务提供）。

用法（在 frontend/ 下）：uv run python e2e/req033_server.py --port 9333 [--root <目录>] [--fake-ai]
--fake-ai：配置一个假的 AI（不联网，按 skill 返回固定回复），用于在浏览器里看“AI 已配置”时的页面（反馈、调用记录、进化）。
默认不配置 AI（e2e 检查“未配置 AI 时进化不可用、试运行只能回放”）。
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


def _fake_ai() -> None:
    from lmesh.core import ai, skills

    os.environ["LMESH_AI__PROVIDER"] = "openai"
    os.environ["LMESH_AI__BASE_URL"] = "http://127.0.0.1:1/v1"
    os.environ["LMESH_AI__MODEL"] = "fake-model"
    n = {"q": 0}

    def which(system: str) -> str:
        for sid in skills.list_ids():
            head = skills.current(sid).system[:60]
            if head and head in system:
                return sid
        return ""

    def hook(s: Any, m: str, system: str, prompt: str) -> Any:
        sid = which(system)
        if sid == "skill-evolve" or "You improve the prompts" in system:
            target = next((x for x in skills.list_ids() if x != "skill-evolve" and skills.current(x).system[:60] in prompt), "ask-query")
            cur = skills.current(target)
            text = json.dumps({"system": cur.system + "\nPrefer RETURN name.", "prompt": cur.prompt, "rationale": "Ask for names only; avoid unknown fields."})
        elif sid == "ask-query":
            n["q"] += 1
            good = "Prefer RETURN name." in system or n["q"] % 3 != 0
            text = '{"query": "FIND interface RETURN name, mtu"}' if good else '{"query": "FIND interface WHERE jumbo = true RETURN name"}'
        elif sid == "ask-answer":
            text = json.dumps({"statements": [{"text": "Interfaces are listed below.", "cites": [1], "facts": []}]})
        elif sid == "config-generate":
            text = "```\ninterface GigabitEthernet0/2/2.105\n vlan-type dot1q 105\n description fake-ai\n#\n```"
        elif sid == "script-review":
            text = '{"findings": []}'
        else:
            text = "{}"
        return ai.Reply(text, m or "fake-model", 10, 5)

    ai.provider_hook = hook


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9333)
    ap.add_argument("--root", default=str(ROOT / "tests" / "output" / "e2e-req033-root"))
    ap.add_argument("--fake-ai", action="store_true")
    a = ap.parse_args()
    import e2e_server  # scripts/e2e_server.py

    e2e_server.prepare(Path(a.root).resolve())
    if a.fake_ai:
        _fake_ai()
    import uvicorn

    from lmesh.api import create_app
    from lmesh.core import config

    uvicorn.run(create_app(config.load()), host="127.0.0.1", port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
