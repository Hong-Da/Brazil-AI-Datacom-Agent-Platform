"""端到端测试用的服务：在 tests/output/e2e-root 建一个全新的临时项目（全量知识库、导入几个样本），然后启动 Web 服务。

由 frontend/playwright.config.ts 的 webServer 调用，不读写开发者本机的 config/ 与 data/。
用法：uv run python scripts/e2e_server.py [--port 9310]
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "e2e-token"
ACCOUNTS = {"e2e-admin": ("E2e-admin-pass", "admin"), "e2e-user": ("E2e-user-pass", "user")}
SAMPLES = [
    "huawei-atn-v800r023/atn-access-01.cfg",
    "cisco-iosxe-asr920-synthetic/pe-asr920-01.cfg",
]
# 含一行功能域内的未识别行，用来测试未识别行页面
BAD = b"sysname LAB-ATN-09\n#\ninterface GigabitEthernet0/2/1\n mtu notanumber\n description lab\n#\nreturn\n"


def prepare(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)
    for d in ("config", "data", "logs"):
        (root / d).mkdir(parents=True)
    shutil.copytree(ROOT / "knowledge", root / "knowledge")
    os.environ["LMESH_ROOT"] = str(root)
    for k in [k for k in os.environ if k.startswith("LMESH_") and "__" in k]:
        del os.environ[k]
    from lmesh import paths
    from lmesh.core import config, importer, kbservice, setup

    paths.project_root.cache_clear()
    setup.apply({"security.api_token": TOKEN}, "zh-CN", check_port=False)
    settings = config.load()
    kb_root = kbservice.runtime_root(settings)
    sources = [(Path(s).name, (ROOT / "knowledge" / "samples" / s).read_bytes()) for s in SAMPLES]
    sources.append(("lab-atn-09.cfg", BAD))
    importer.import_sources(sources, settings.database_url, "basic", kb_root)
    # 同一台设备的第二个版本（变更后的配置），供“同一设备两个版本”的对比使用
    v2 = (ROOT / "knowledge" / "samples" / "compare" / "asr920-modified.cfg").read_bytes()
    importer.import_sources([("pe-asr920-01-v2.cfg", v2)], settings.database_url, "basic", kb_root)
    # 登录账号（REQ-030）：e2e/helpers.ts 的 ADMIN 与 USER
    from lmesh.core import users

    for name, (password, role) in ACCOUNTS.items():
        users.create_user(settings.database_url, name, password, role)
    # M6：样本导入在管理员的默认项目里（第一个管理员接管）；普通用户设为它的可编辑成员并以它为默认项目，
    # 现有用例（旧的无项目路径落到默认项目）看到的设备与 M6 之前相同
    from lmesh.core import projects

    url = settings.database_url
    scope = projects.default_scope(url, projects.cli_identity(url, "e2e-admin"))
    projects.set_member(url, scope, "e2e-user", "edit")
    projects.set_default(url, projects.cli_identity(url, "e2e-user"), scope.slug)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9310)
    a = ap.parse_args()
    if not (ROOT / "src" / "lmesh" / "web" / "static" / "index.html").exists():
        print("前端尚未构建：先运行 scripts/build_frontend.py", file=sys.stderr)
        return 1
    prepare(ROOT / "tests" / "output" / "e2e-root")
    import uvicorn

    from lmesh.api import create_app
    from lmesh.core import config

    uvicorn.run(create_app(config.load()), host="127.0.0.1", port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
