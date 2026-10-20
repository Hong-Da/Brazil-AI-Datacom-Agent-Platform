"""生成可部署的发布包（REQ-046），产物只放在本机 dist/。

用法：uv run --no-project python scripts/build_release.py [版本号] [--targets 目标,…] [--skip-frontend]
  版本号    默认取 pyproject.toml 的版本；可以加后缀，例如 0.5.0-rc（必须以 pyproject.toml 的版本开头）
  --targets 默认按平台：Windows 为 win-zip,win-exe；Linux 为 linux,docker
            win-zip  Windows 离线包（zip，解压后双击 start.bat）
            win-exe  Windows 安装程序（NSIS，自带的 makensis 放在 .toolchain/nsis/）
            linux    Linux 离线安装包（tar.gz，含 install.sh / uninstall.sh）
            docker   Docker 镜像 lmesh:<版本>，导出为 tar.gz（docker load），另附 compose 文件
  --skip-frontend  不检查前端是否需要重新构建（docker 目标总是在镜像里构建前端）

离线包的内容：uv 管理的 Python 运行时（python-build-standalone）+ 装进运行时的全部依赖 + src/（含已构建的前端）
+ knowledge/ + 启动与安装脚本。src/ 通过运行时 site-packages 里的 lmesh-src.pth 加入导入路径，
不需要 PYTHONPATH，也不需要联网。只用标准库与 uv。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
WORK = ROOT / "tmp" / "os" / "release"  # 可用 --work 改到更短的目录（Windows 路径不能超过 260 个字符）
LONG_PATH = 160  # 包内相对路径超过这个长度的 .pyc 不打包（运行时在内存中编译），避免装到较深目录时超过 260 个字符
PKG = ROOT / "packaging"
TOOLCHAIN = ROOT / ".toolchain"
IS_WIN = os.name == "nt"

# 第三方工具：固定版本与 SHA256，下载到项目内的 .toolchain/（不安装到系统）
NSIS_VERSION = "3.11"
NSIS_URL = f"https://downloads.sourceforge.net/project/nsis/NSIS%203/{NSIS_VERSION}/nsis-{NSIS_VERSION}.zip"
NSIS_SHA256 = "c7d27f780ddb6cffb4730138cd1591e841f4b7edb155856901cdf5f214394fa1"
WINSW_URL = "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW.NET461.exe"
WINSW_SHA256 = "b5066b7bbdfba1293e5d15cda3caaea88fbeab35bd5b38c41c913d492aadfc4f"
WINSW_LICENSE_URL = "https://raw.githubusercontent.com/winsw/winsw/v2.12.0/LICENSE.txt"
WINSW_LICENSE_SHA256 = "1cdf703c10a70e5973bf3acf2a5eeabe7746237155b92db2034aeae26fdf7802"

SKIP_NAMES = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
    log("$ " + " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], text=True, **kw)  # type: ignore[call-overload]
    if r.returncode != 0:
        sys.exit(f"命令失败（退出码 {r.returncode}）：{' '.join(str(c) for c in cmd)}")
    return r


def pyproject_version() -> str:
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    if not m:
        sys.exit("pyproject.toml 中没有 version")
    return m.group(1)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, target: Path, digest: str) -> Path:
    """下载到项目内并核对 SHA256；已存在且校验通过时不重复下载。"""
    if target.exists() and sha256(target) == digest:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    log(f"下载 {url}")
    with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310  固定的 https 地址
        target.write_bytes(resp.read())
    if sha256(target) != digest:
        target.unlink()
        sys.exit(f"SHA256 不符：{url}")
    return target


def ignore(_dir: str, names: list[str]) -> set[str]:
    return {n for n in names if n in SKIP_NAMES or n.endswith((".pyc", ".pyo"))}


# ---------- 公共：前端、Python 运行时、依赖 ----------


def build_frontend() -> None:
    py = sys.executable
    if subprocess.run([py, str(ROOT / "scripts" / "build_frontend.py"), "--check"]).returncode == 0:
        return
    run([py, str(ROOT / "scripts" / "ensure_node.py")])
    run([py, str(ROOT / "scripts" / "build_frontend.py")])


def managed_python() -> Path:
    """uv 管理的 Python 3.12（项目内 .toolchain/runtime/python/），返回安装目录。"""
    base = Path(os.environ.get("UV_PYTHON_INSTALL_DIR", TOOLCHAIN / "runtime" / "python"))

    def found() -> list[Path]:
        pat = re.compile(r"cpython-3\.12\.(\d+)-")
        dirs = [d for d in base.glob("cpython-3.12.*") if d.is_dir() and not d.is_symlink() and pat.match(d.name)]
        return sorted(dirs, key=lambda d: int(pat.match(d.name).group(1)))  # type: ignore[union-attr]

    if not found():
        run(["uv", "python", "install", "3.12"])
    dirs = found()
    if not dirs:
        sys.exit(f"找不到 uv 管理的 Python 3.12：{base}")
    return dirs[-1]


def prune_runtime(rt: Path) -> None:
    """去掉运行时里用不到的部分：Tk 图形界面、IDLE、海龟演示、ensurepip 自带的 wheel。"""
    lib = rt / "Lib" if IS_WIN else next((rt / "lib").glob("python3.*"))
    for p in [lib / "tkinter", lib / "idlelib", lib / "turtledemo", lib / "ensurepip", rt / "tcl"]:
        shutil.rmtree(p, ignore_errors=True)
    for pat in ("tcl8*", "tk8*", "itcl*", "thread2*"):
        for p in (rt / "lib").glob(pat):
            shutil.rmtree(p, ignore_errors=True)
    for pat in ("DLLs/_tkinter*", "DLLs/tcl*.dll", "DLLs/tk*.dll", "lib/python3.*/lib-dynload/_tkinter*"):
        for p in rt.glob(pat):
            p.unlink()


def runtime_python(stage: Path) -> Path:
    return stage / "runtime" / "python" / ("python.exe" if IS_WIN else "bin/python3")


def stage_common(stage: Path, version: str) -> None:
    """离线包的公共部分：运行时、依赖、程序、知识库。"""
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    src_py = managed_python()
    log(f"Python 运行时：{src_py.name}")
    shutil.copytree(src_py, stage / "runtime" / "python", symlinks=True, ignore=ignore)
    prune_runtime(stage / "runtime" / "python")
    py = runtime_python(stage)

    req = WORK / "requirements.txt"
    run(
        [
            "uv",
            "export",
            "--quiet",
            "--frozen",
            "--no-dev",
            "--no-hashes",
            "--no-emit-project",
            "--no-header",
            "-o",
            str(req),
        ],
        cwd=ROOT,
    )
    run(
        [
            "uv", "pip", "install", "--python", str(py), "--break-system-packages", "--no-deps",
            "--link-mode", "copy", "--compile-bytecode", "-r", str(req),
            # Linux 依赖按 manylinux_2_28 选 wheel：构建机较新时也能装到 glibc 2.28 的老系统
            *([] if IS_WIN else ["--python-platform", "x86_64-manylinux_2_28"]),
        ],
        cwd=ROOT,
    )  # fmt: skip

    shutil.copytree(ROOT / "src" / "lmesh", stage / "src" / "lmesh", ignore=ignore)
    if not (stage / "src" / "lmesh" / "web" / "static" / "index.html").exists():
        sys.exit("src/lmesh/web/static 没有构建产物：先构建前端")
    shutil.copytree(ROOT / "knowledge", stage / "knowledge", ignore=ignore)
    shutil.copytree(ROOT / "assets" / "brand", stage / "assets" / "brand", ignore=ignore)
    (stage / "config").mkdir()
    shutil.copy2(ROOT / "config" / "config.example.toml", stage / "config" / "config.example.toml")
    (stage / "docs").mkdir()
    for doc in ("deploy.md", "cli.md", "api.md"):
        if (ROOT / "docs" / doc).exists():
            shutil.copy2(ROOT / "docs" / doc, stage / "docs" / doc)
    shutil.copy2(ROOT / "pyproject.toml", stage / "pyproject.toml")  # 版本号来源；也让程序认出这里是根目录
    (stage / "VERSION").write_text(version + "\n", encoding="utf-8")

    # src/ 加入运行时的导入路径（.pth 里的相对路径相对于 site-packages）
    purelib = Path(
        subprocess.run(
            [str(py), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    )  # fmt: skip
    rel = os.path.relpath(stage / "src", purelib)
    (purelib / "lmesh-src.pth").write_text(rel.replace("\\", "/") + "\n", encoding="utf-8")
    run([str(py), "-m", "compileall", "-q", "-j", "0", str(stage / "src")])
    dropped = 0
    for pyc in stage.rglob("*.pyc") if IS_WIN else []:
        if len(str(Path(stage.name) / pyc.relative_to(stage))) > LONG_PATH:
            pyc.unlink()
            dropped += 1
    longest = max(len(str(Path(stage.name) / p.relative_to(stage))) for p in stage.rglob("*"))
    if IS_WIN:
        log(f"去掉 {dropped} 个路径过长的 .pyc；包内最长相对路径 {longest} 个字符")


def smoke(stage: Path, version: str) -> None:
    """在干净环境里确认包内 Python 能导入程序（不依赖开发环境的 .venv、PYTHONPATH）。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LMESH_", "PYTHON", "VIRTUAL_ENV", "UV_"))}
    env["PYTHONUTF8"] = "1"
    out = subprocess.run(
        [str(runtime_python(stage)), "-m", "lmesh", "--version"],
        cwd=str(WORK), env=env, capture_output=True, text=True,
    )  # fmt: skip
    if out.returncode != 0 or version.split("-")[0] not in out.stdout:
        sys.exit(f"包内程序无法启动：{out.stdout}{out.stderr}")
    log(f"自检通过：{out.stdout.strip()}")


def copy_tree_files(src: Path, dst: Path, crlf: bool = False) -> None:
    for f in src.iterdir():
        if f.is_file():
            data = f.read_bytes()
            if crlf and f.suffix.lower() in (".bat", ".cmd"):
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            (dst / f.name).write_bytes(data)


# ---------- Windows ----------


def stage_windows(stage: Path, version: str) -> None:
    stage_common(stage, version)
    copy_tree_files(PKG / "windows", stage, crlf=True)
    (stage / "installer.nsi").unlink(missing_ok=True)  # 只用于生成安装程序
    svc = stage / "service"
    svc.mkdir()
    shutil.copy2(fetch(WINSW_URL, TOOLCHAIN / "winsw" / "WinSW.NET461.exe", WINSW_SHA256), svc / "lmesh-service.exe")
    shutil.copy2(
        fetch(WINSW_LICENSE_URL, TOOLCHAIN / "winsw" / "WinSW-LICENSE.txt", WINSW_LICENSE_SHA256),
        svc / "WinSW-LICENSE.txt",
    )
    for name in ("lmesh-service.xml",):
        shutil.move(stage / name, svc / name)
    smoke(stage, version)


def make_zip(stage: Path, out: Path) -> None:
    log(f"打包 {out.name}")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(stage.rglob("*")):
            if p.is_file():
                z.write(p, Path(stage.name) / p.relative_to(stage))


def makensis() -> Path:
    exe = TOOLCHAIN / "nsis" / f"nsis-{NSIS_VERSION}" / "makensis.exe"
    if not exe.exists():
        z = fetch(NSIS_URL, TOOLCHAIN / "cache" / "dl" / f"nsis-{NSIS_VERSION}.zip", NSIS_SHA256)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(TOOLCHAIN / "nsis")
    return exe


def make_exe(stage: Path, version: str, out: Path) -> None:
    nums = [int(x) for x in re.findall(r"\d+", version.split("-")[0])[:3]] + [0, 0, 0]
    vinum = ".".join(str(n) for n in nums[:3]) + ".0"
    run(
        [
            makensis(), "/V2", "/INPUTCHARSET", "UTF8",
            f"/DVERSION={version}", f"/DVINUM={vinum}", f"/DSTAGE={stage}", f"/DOUTFILE={out}",
            f"/DICON={ROOT / 'assets' / 'brand' / 'app.ico'}",
            str(PKG / "windows" / "installer.nsi"),
        ]
    )  # fmt: skip


# ---------- Linux ----------


def stage_linux(stage: Path, version: str) -> None:
    stage_common(stage, version)
    copy_tree_files(PKG / "linux", stage)
    (stage / "bin").mkdir()
    shutil.move(stage / "lmesh", stage / "bin" / "lmesh")
    for f in [stage / "bin" / "lmesh", *stage.glob("*.sh")]:
        f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    smoke(stage, version)


def make_tar(stage: Path, out: Path) -> None:
    log(f"打包 {out.name}")
    with tarfile.open(out, "w:gz", compresslevel=6) as t:
        t.add(stage, arcname=stage.name)


# ---------- Docker ----------


def build_docker(version: str, image_out: Path, compose_out: Path) -> None:
    if not shutil.which("docker"):
        sys.exit("没有找到 docker")
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        sys.exit("Docker 服务没有运行")
    tag = f"lmesh:{version}"
    t0 = time.time()
    args = ["docker", "build", "-t", tag, "--build-arg", f"LMESH_VERSION={version}"]
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "UV_INDEX_URL", "NPM_CONFIG_REGISTRY"):
        if os.environ.get(k):  # 代理与镜像源从环境变量透传，不写死
            args += ["--build-arg", f"{k}={os.environ[k]}"]
    run([*args, "."], cwd=ROOT)
    size = subprocess.run(
        ["docker", "image", "inspect", tag, "--format", "{{.Size}}"], capture_output=True, text=True
    ).stdout.strip()
    log(f"镜像 {tag} 构建完成，用时 {time.time() - t0:.0f} 秒，大小 {int(size or 0) / 1e6:.0f} MB")
    log(f"导出 {image_out.name}")
    with image_out.open("wb") as f:
        save = subprocess.Popen(["docker", "save", tag], stdout=subprocess.PIPE)
        gz = subprocess.run(["gzip", "-6"], stdin=save.stdout, stdout=f)
        if save.wait() != 0 or gz.returncode != 0:
            sys.exit("docker save 失败")
    stage = WORK / f"lmesh-{version}-docker"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    for name in ("compose.yaml", "compose.postgres.yaml"):
        shutil.copy2(PKG / "docker" / name, stage / name)
    env = (PKG / "docker" / "env.example").read_text(encoding="utf-8")
    (stage / ".env.example").write_text(env.replace("@VERSION@", version), encoding="utf-8")
    shutil.copy2(ROOT / "docs" / "deploy.md", stage / "deploy.md")
    make_tar(stage, compose_out)


# ---------- 入口 ----------


def main() -> None:
    ap = argparse.ArgumentParser(description="生成发布包到 dist/")
    ap.add_argument("version", nargs="?", default=None)
    ap.add_argument("--targets", default="win-zip,win-exe" if IS_WIN else "linux,docker")
    ap.add_argument("--skip-frontend", action="store_true")
    ap.add_argument("--work", type=Path, default=None, help="中间文件目录（默认 tmp/os/release）")
    a = ap.parse_args()
    global WORK
    if a.work:
        WORK = a.work.resolve()
    base = pyproject_version()
    version = a.version or base
    if not re.fullmatch(re.escape(base) + r"(-[0-9A-Za-z.]+)?", version):
        sys.exit(f"版本号 {version} 必须是 pyproject.toml 的 {base}，或加后缀（例如 {base}-rc）")
    targets = [t.strip() for t in a.targets.split(",") if t.strip()]
    bad = set(targets) - {"win-zip", "win-exe", "linux", "docker"}
    if bad:
        sys.exit(f"未知目标：{', '.join(sorted(bad))}")
    if ({"win-zip", "win-exe"} & set(targets)) and not IS_WIN:
        sys.exit("win-zip / win-exe 只能在 Windows 上生成")
    if ({"linux", "docker"} & set(targets)) and IS_WIN:
        sys.exit("linux / docker 只能在 Linux 上生成")
    DIST.mkdir(exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    if not a.skip_frontend and set(targets) - {"docker"}:
        build_frontend()
    if {"win-zip", "win-exe"} & set(targets):
        stage = WORK / f"lmesh-{version}"
        stage_windows(stage, version)
        if "win-zip" in targets:
            made.append(DIST / f"lmesh_{version}_windows-x64.zip")
            make_zip(stage, made[-1])
        if "win-exe" in targets:
            made.append(DIST / f"lmesh_{version}_windows-x64_setup.exe")
            make_exe(stage, version, made[-1])
    if "linux" in targets:
        stage = WORK / f"lmesh-{version}"
        stage_linux(stage, version)
        made.append(DIST / f"lmesh_{version}_linux-x86_64.tar.gz")
        make_tar(stage, made[-1])
    if "docker" in targets:
        made += [DIST / f"lmesh_{version}_docker-image.tar.gz", DIST / f"lmesh_{version}_docker-compose.tar.gz"]
        build_docker(version, made[-2], made[-1])
    sums = DIST / f"lmesh_{version}_SHA256SUMS.txt"
    lines = {}
    if sums.exists():
        for line in sums.read_text(encoding="utf-8").splitlines():
            if "  " in line:
                d, n = line.split("  ", 1)
                lines[n] = d
    for p in made:
        lines[p.name] = sha256(p)
    # 固定 LF 换行：Windows 默认写 CRLF，Linux 上 sha256sum -c 会把 \r 当成文件名的一部分
    sums.write_text("".join(f"{d}  {n}\n" for n, d in sorted(lines.items())), encoding="utf-8", newline="\n")
    print("\n生成的文件：")
    for p in made:
        print(f"  {p}  {p.stat().st_size / 1e6:.1f} MB")
    print(f"  {sums}")


if __name__ == "__main__":
    main()
