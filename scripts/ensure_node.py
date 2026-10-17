"""准备项目内的 Node（只用于构建前端）：按 frontend/.nvmrc 下载到 .toolchain/runtime/node/ 并核对 SHA256。

只用标准库，在依赖安装之前也能运行：uv run --no-project python scripts/ensure_node.py
已存在且主版本一致时直接跳过。镜像源可用环境变量 LMESH_NODE_MIRROR 指定（默认 https://nodejs.org/dist）。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / ".toolchain" / "runtime" / "node"
MIRROR = os.environ.get("LMESH_NODE_MIRROR", "https://nodejs.org/dist").rstrip("/")


def node_exe() -> Path:
    return TARGET / ("node.exe" if os.name == "nt" else "bin/node")


def current_major() -> str | None:
    exe = node_exe()
    if not exe.exists():
        return None
    try:
        out = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
    except OSError:
        return None
    return out.lstrip("v").split(".")[0] if out else None


def platform_id() -> tuple[str, str]:
    machine = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    if not arch:
        sys.exit(f"不支持的 CPU 架构：{machine}")
    if os.name == "nt":
        return f"win-{arch}", "zip"
    return f"linux-{arch}", "tar.xz"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 - 固定的官方地址或用户指定的镜像
        return bytes(r.read())


def main() -> None:
    want = (ROOT / "frontend" / ".nvmrc").read_text(encoding="utf-8").strip().lstrip("v")
    major = want.split(".")[0]
    if current_major() == major:
        print(f"Node {major} 已就绪：{node_exe()}")
        return
    index = json.loads(fetch(f"{MIRROR}/index.json"))
    version = next(v["version"] for v in index if v["version"].lstrip("v").split(".")[0] == major)
    plat, ext = platform_id()
    name = f"node-{version}-{plat}"
    print(f"下载 Node {version}（{plat}）……")
    archive = fetch(f"{MIRROR}/{version}/{name}.{ext}")
    sums = fetch(f"{MIRROR}/{version}/SHASUMS256.txt").decode()
    expected = next((ln.split()[0] for ln in sums.splitlines() if ln.endswith(f"{name}.{ext}")), None)
    actual = hashlib.sha256(archive).hexdigest()
    if expected != actual:
        sys.exit(f"Node 压缩包校验失败：期望 {expected}，实际 {actual}")
    with tempfile.TemporaryDirectory(dir=ROOT / ".toolchain") as tmp:
        tmpdir = Path(tmp)
        path = tmpdir / f"{name}.{ext}"
        path.write_bytes(archive)
        if ext == "zip":
            with zipfile.ZipFile(path) as z:
                z.extractall(tmpdir)
        else:
            with tarfile.open(path) as t:
                t.extractall(tmpdir, filter="data")
        if TARGET.exists():
            shutil.rmtree(TARGET)
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmpdir / name), str(TARGET))
    print(f"Node {version} 已安装到 {TARGET}")


if __name__ == "__main__":
    (ROOT / ".toolchain").mkdir(exist_ok=True)
    main()
