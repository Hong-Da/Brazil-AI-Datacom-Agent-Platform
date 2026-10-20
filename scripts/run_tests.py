"""一键测试的实际逻辑（test.bat / test.sh 调用它）。

用法：test [--unit] [--cli] [--api] [--docs] [--roundtrip] [--frontend] [--e2e] [--live --base-url URL --token TOKEN]
          [--changed [REF]] [-n N | --serial] [--max-workers N]
不带分类参数时运行全部离线测试（后端各类 + 前端单元）；--e2e 需要浏览器，单独运行。
后端测试默认用 pytest-xdist 并行（进程数 = CPU 核数，不超过 --max-workers / LMESH_TEST_MAX_WORKERS，默认 16）；
--serial（或 -n 0）串行。--changed 按改动的文件挑选测试类别（见 CHANGE_RULES），开发中用它做增量测试。
结束时输出每类通过 / 失败 / 跳过数量；有失败时退出码 1。报告：tests/output/report.html、tests/output/junit.xml。
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "output"
BACKEND = ["unit", "cli", "api", "docs", "roundtrip"]
ALL = [*BACKEND, "frontend"]
DEFAULT_MAX_WORKERS = 16

# 增量测试（--changed）：改动的文件路径（相对项目根目录、用 /）→ 要跑的测试类别。按顺序取第一条匹配的规则；
# 规则宁宽勿窄，没有匹配的文件跑全部离线测试。新增或删除文件时另加 docs（README 目录结构检查）。
_CORE_RT = "parser|graph|canon|translate|change"  # 解析、建图、规范渲染、翻译、变更：往返与翻译、变更回归
_CORE_RT_MORE = (
    "kbservice|renderer|roundtrip|graphstore|analysis|compare|migration|topology|sanitize|features|layers|kb/"
)
CHANGE_RULES: list[tuple[str, list[str]]] = [
    (r"^frontend/src/i18n/", ["frontend", "docs"]),
    (r"^frontend/", ["frontend"]),
    (r"^src/lmesh/api/", ["api", "cli", "docs"]),
    (r"^src/lmesh/cli/", ["cli", "docs"]),
    (rf"^src/lmesh/core/({_CORE_RT})(\.py|_|/)", ["unit", "roundtrip"]),
    (rf"^src/lmesh/core/({_CORE_RT_MORE})", ["unit", "roundtrip", "cli", "api"]),
    (r"^src/lmesh/core/", ["unit", "cli", "api"]),  # CLI 与 API 共用 core
    (r"^src/lmesh/locales/", ["unit", "docs"]),
    (r"^knowledge/", ["unit", "roundtrip"]),
    (r"^tests/cases/", ["cli", "api", "docs"]),
    (r"^tests/(unit|cli|api|docs|roundtrip)/", []),  # 规则的类别为空时取括号里匹配到的：改了哪类测试就跑哪类
    (r"^scripts/gen_docs\.py$", ["docs"]),
    (r"^(docs/|.*\.md$)", ["docs"]),
]


def changed_files(ref: str) -> tuple[list[str], bool]:
    """相对 ref（与 HEAD 的分叉点）改动过的文件（含未提交、未跟踪的），以及其中是否有新增或删除。"""

    def git(*args: str) -> list[str]:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            raise SystemExit(f"git {' '.join(args)} 失败：{r.stderr.strip()}")
        return [s for s in r.stdout.splitlines() if s.strip()]

    base = git("merge-base", ref, "HEAD")[0]
    status = git("diff", "--name-status", "--no-renames", base)
    untracked = git("ls-files", "--others", "--exclude-standard")
    files = sorted({line.split("\t", 1)[1] for line in status} | set(untracked))
    added_or_removed = bool(untracked) or any(line[0] in "AD" for line in status)
    return files, added_or_removed


def pick_changed(files: list[str], added_or_removed: bool) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """按 CHANGE_RULES 选类别；返回（类别，每个文件的去向）。"""
    picked: set[str] = set()
    detail: list[tuple[str, list[str]]] = []
    for f in files:
        cats: list[str] | None = None
        for pattern, rule_cats in CHANGE_RULES:
            m = re.match(pattern, f)
            if m:
                cats = rule_cats or list(m.groups())
                break
        if cats is None:  # 未登记的路径（测试夹具、依赖、脚本、包根目录等）：跑全部
            cats = list(ALL)
        picked.update(cats)
        detail.append((f, cats))
    if added_or_removed:
        picked.add("docs")
    return [c for c in ALL if c in picked], detail


def worker_count(arg: str | None, max_workers: int | None) -> int:
    """并行进程数：-n 指定时用它（0 = 串行）；否则 CPU 核数，不超过上限。没装 pytest-xdist 时串行。"""
    if importlib.util.find_spec("xdist") is None:
        return 0
    if arg not in (None, "auto"):
        return max(0, int(arg))
    cap = max_workers or int(os.environ.get("LMESH_TEST_MAX_WORKERS") or DEFAULT_MAX_WORKERS)
    return max(1, min(os.cpu_count() or 1, cap))


def run_pytest(markers: list[str], extra_env: dict[str, str], workers: int) -> Counter[tuple[str, str]]:
    OUT.mkdir(parents=True, exist_ok=True)
    junit = OUT / "junit.xml"
    junit.unlink(missing_ok=True)
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
    if workers:
        # worksteal：用例耗时差别大（CLI 子进程、全量往返），空闲的 worker 从忙的 worker 那里拿用例
        cmd += ["-n", str(workers), "--dist", "worksteal"]
    print(f"后端测试：{' / '.join(markers)}，" + (f"{workers} 个进程并行" if workers else "串行"), flush=True)
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


def run_frontend_args(args: list[str]) -> tuple[str, int]:
    """在 frontend/ 下运行 pnpm 的任意参数（例如 exec playwright test -c 某配置）。"""
    cmd = pnpm()
    if not cmd:
        return "skipped", 0
    r = subprocess.run([*cmd, *args], cwd=ROOT / "frontend", env={**os.environ, "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0"})
    return ("passed" if r.returncode == 0 else "failed"), r.returncode


def main() -> int:
    ap = argparse.ArgumentParser(prog="test")
    for c in [*BACKEND, "frontend", "e2e"]:
        ap.add_argument(f"--{c}", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--base-url")
    ap.add_argument("--token", default="")
    ap.add_argument(
        "--changed",
        nargs="?",
        const="HEAD",
        metavar="REF",
        help="增量测试：只跑与改动相关的类别。默认对比 HEAD（未提交的改动）；给出分支或提交时对比它与 HEAD 的分叉点",
    )
    ap.add_argument("-n", "--workers", metavar="N", help="后端测试的并行进程数（auto = CPU 核数，0 = 串行）")
    ap.add_argument("--serial", action="store_true", help="串行运行后端测试（同 -n 0）")
    ap.add_argument("--max-workers", type=int, help=f"auto 时的进程数上限（默认 {DEFAULT_MAX_WORKERS}）")
    a = ap.parse_args()

    env: dict[str, str] = {}
    picked = [c for c in BACKEND if getattr(a, c)]
    want_frontend = a.frontend
    if a.changed is not None:
        files, added = changed_files(a.changed)
        if not files:
            print(f"相对 {a.changed} 没有改动，不需要测试")
            return 0
        cats, detail = pick_changed(files, added)
        print(f"增量测试（相对 {a.changed}）：{len(files)} 个文件改动")
        for f, fc in detail:
            print(f"  {f} → {', '.join(fc) or '（无）'}")
        if added:
            print("  有新增或删除的文件 → docs（README 目录结构）")
        print(f"选中：{', '.join(cats)}\n", flush=True)
        picked = sorted({*picked, *(c for c in cats if c in BACKEND)}, key=BACKEND.index)
        want_frontend = want_frontend or "frontend" in cats
    if a.live:
        if not a.base_url:
            print("--live 需要 --base-url，例如 --base-url http://127.0.0.1:9090 --token <令牌>")
            return 2
        env = {"LMESH_LIVE_BASE_URL": a.base_url, "LMESH_LIVE_TOKEN": a.token}
        picked = ["live"]
    run_all = a.changed is None and not (picked or a.frontend or a.e2e)
    if run_all:
        picked = list(BACKEND)
    workers = 0 if a.serial or a.live else worker_count(a.workers, a.max_workers)

    rows: list[tuple[str, int, int, int]] = []
    failed = False
    if picked:
        counts = run_pytest(picked, env, workers)
        for cat in sorted({c for c, _ in counts}):
            p, f, s = counts[(cat, "passed")], counts[(cat, "failed")], counts[(cat, "skipped")]
            rows.append((cat, p, f, s))
            failed |= f > 0
    if run_all or want_frontend:
        state, _ = run_frontend("test")
        rows.append(("frontend", int(state == "passed"), int(state == "failed"), int(state == "skipped")))
        failed |= state == "failed"
    if a.e2e:
        # 端到端测试用构建好的前端（由 Python 服务提供），先按需构建
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_frontend.py")], cwd=ROOT, env=node_env())
        state, _ = run_frontend("e2e")
        rows.append(("e2e", int(state == "passed"), int(state == "failed"), int(state == "skipped")))
        failed |= state == "failed"
        # 接假 AI 服务的 e2e（M8 各组 skill）：各自独立端口与数据目录，依次运行
        for cfg in sorted((ROOT / "frontend").glob("playwright.m8*.config.ts")):
            state, _ = run_frontend_args(["exec", "playwright", "test", "-c", cfg.name])
            rows.append(
                (
                    f"e2e-{cfg.name.split('.')[1]}",
                    int(state == "passed"),
                    int(state == "failed"),
                    int(state == "skipped"),
                )
            )
            failed |= state == "failed"

    print("\n分类         通过   失败   跳过")
    for cat, p, f, s in rows:
        print(f"{cat:<12} {p:>4} {f:>6} {s:>6}")
    print(f"\n报告：{OUT / 'report.html'}")
    print("结果：" + ("有失败" if failed else "全部通过"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
