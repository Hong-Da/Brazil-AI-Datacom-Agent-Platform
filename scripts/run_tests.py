"""一键测试的实际逻辑（test.bat / test.sh 调用它）。

用法：test [--unit] [--cli] [--api] [--docs] [--roundtrip] [--frontend] [--e2e] [--live --base-url URL --token TOKEN]
不带分类参数时运行全部离线测试（后端各类 + 前端单元）；--e2e 需要浏览器，单独运行。
结束时输出每类通过 / 失败 / 跳过数量；有失败时退出码 1。报告：tests/output/report.html、tests/output/junit.xml。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "output"
BACKEND = ["unit", "cli", "api", "docs", "roundtrip"]


def run_pytest(markers: list[str], extra_env: dict[str, str]) -> Counter[tuple[str, str]]:
    OUT.mkdir(parents=True, exist_ok=True)
    junit = OUT / "junit.xml"
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-m",
        " or ".join(markers),
        f"--junitxml={junit}",
        f"--html={OUT / 'report.html'}",
        "--self-contained-html",
        "-q",
    ]
    subprocess.run(cmd, cwd=ROOT, env={**os.environ, **extra_env})
    counts: Counter[tuple[str, str]] = Counter()
    if not junit.exists():
        counts[("pytest", "failed")] += 1
        return counts
    for tc in ET.parse(junit).getroot().iter("testcase"):
        parts = (tc.get("classname") or "").split(".")
        cat = parts[1] if len(parts) > 1 and parts[0] == "tests" else "other"
        if tc.find("failure") is not None or tc.find("error") is not None:
            state = "failed"
        elif tc.find("skipped") is not None:
            state = "skipped"
        else:
            state = "passed"
        counts[(cat, state)] += 1
    return counts


def node_env() -> dict[str, str]:
    node_dir = ROOT / ".toolchain" / "runtime" / "node"
    bin_dir = node_dir if os.name == "nt" else node_dir / "bin"
    env = {**os.environ, "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0"}
    if bin_dir.exists():
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    return env


def pnpm() -> list[str] | None:
    node = ROOT / ".toolchain" / "runtime" / "node"
    corepack = node / ("corepack.cmd" if os.name == "nt" else "bin/corepack")
    if corepack.exists():
        return [str(corepack), "pnpm"]
    from shutil import which

    p = which("pnpm")
    return [p] if p else None


def run_frontend(script: str) -> tuple[str, int]:
    cmd = pnpm()
    if not cmd:
        return "skipped", 0
    if not (ROOT / "frontend" / "node_modules").exists():
        subprocess.run([*cmd, "install", "--frozen-lockfile"], cwd=ROOT / "frontend", env=node_env())
    r = subprocess.run(
        [*cmd, script], cwd=ROOT / "frontend", env={**os.environ, "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0"}
    )
    return ("passed" if r.returncode == 0 else "failed"), r.returncode


def main() -> int:
    ap = argparse.ArgumentParser(prog="test")
    for c in [*BACKEND, "frontend", "e2e"]:
        ap.add_argument(f"--{c}", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--base-url")
    ap.add_argument("--token", default="")
    a = ap.parse_args()

    env: dict[str, str] = {}
    picked = [c for c in BACKEND if getattr(a, c)]
    if a.live:
        if not a.base_url:
            print("--live 需要 --base-url，例如 --base-url http://127.0.0.1:9000 --token <令牌>")
            return 2
        env = {"LMESH_LIVE_BASE_URL": a.base_url, "LMESH_LIVE_TOKEN": a.token}
        picked = ["live"]
    run_all = not (picked or a.frontend or a.e2e)
    if run_all:
        picked = list(BACKEND)

    rows: list[tuple[str, int, int, int]] = []
    failed = False
    if picked:
        counts = run_pytest(picked, env)
        for cat in sorted({c for c, _ in counts}):
            p, f, s = counts[(cat, "passed")], counts[(cat, "failed")], counts[(cat, "skipped")]
            rows.append((cat, p, f, s))
            failed |= f > 0
    if run_all or a.frontend:
        state, _ = run_frontend("test")
        rows.append(("frontend", int(state == "passed"), int(state == "failed"), int(state == "skipped")))
        failed |= state == "failed"
    if a.e2e:
        state, _ = run_frontend("e2e")
        rows.append(("e2e", int(state == "passed"), int(state == "failed"), int(state == "skipped")))
        failed |= state == "failed"

    print("\n分类         通过   失败   跳过")
    for cat, p, f, s in rows:
        print(f"{cat:<12} {p:>4} {f:>6} {s:>6}")
    print(f"\n报告：{OUT / 'report.html'}")
    print("结果：" + ("有失败" if failed else "全部通过"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
