"""按需构建前端：frontend/ 有变化或没有构建产物时才构建。只用标准库。

用法：uv run --no-project python scripts/build_frontend.py [--force] [--check]
--check：只报告是否需要构建，需要时退出码 1。
构建产物 src/lmesh/web/static/ 里记录了源码指纹 .build-hash，指纹不变就跳过。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FE = ROOT / "frontend"
OUT = ROOT / "src" / "lmesh" / "web" / "static"
STAMP = OUT / ".build-hash"
SKIP = {"node_modules", "dist", ".vite"}


def fingerprint() -> str:
    h = hashlib.sha256()
    for p in sorted(FE.rglob("*")):
        rel = p.relative_to(FE)
        if p.is_file() and not (set(rel.parts) & SKIP) and not p.name.endswith(".test.ts"):
            h.update(str(rel).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def node_env() -> dict[str, str]:
    """子进程环境：项目内的 Node 放在 PATH 最前（corepack 脚本靠 PATH 找 node）。"""
    node_dir = ROOT / ".toolchain" / "runtime" / "node"
    bin_dir = node_dir if os.name == "nt" else node_dir / "bin"
    env = {**os.environ, "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0"}
    if bin_dir.exists():
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    return env


def pnpm_cmd() -> list[str]:
    node_dir = ROOT / ".toolchain" / "runtime" / "node"
    corepack = node_dir / ("corepack.cmd" if os.name == "nt" else "bin/corepack")
    if corepack.exists():
        return [str(corepack), "pnpm"]
    found = shutil.which("pnpm")
    if found:
        return [found]
    sys.exit("找不到 pnpm：先运行 scripts/ensure_node.py 准备项目内的 Node")


def main() -> None:
    fp = fingerprint()
    up_to_date = STAMP.exists() and STAMP.read_text(encoding="utf-8").strip() == fp and (OUT / "index.html").exists()
    if "--check" in sys.argv:
        print("前端已是最新" if up_to_date else "前端需要构建")
        sys.exit(0 if up_to_date else 1)
    if up_to_date and "--force" not in sys.argv:
        print("前端已是最新，跳过构建")
        return
    pnpm = pnpm_cmd()
    env = node_env()
    for args in (["install", "--frozen-lockfile"], ["build"]):
        print("pnpm " + " ".join(args))
        r = subprocess.run([*pnpm, *args], cwd=FE, env=env, shell=False)
        if r.returncode != 0:
            sys.exit(f"pnpm {' '.join(args)} 失败（退出码 {r.returncode}）")
    STAMP.write_text(fp, encoding="utf-8")
    print(f"前端已构建：{OUT}")


if __name__ == "__main__":
    main()
