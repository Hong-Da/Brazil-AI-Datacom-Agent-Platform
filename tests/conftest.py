"""公共夹具：临时项目根目录、临时配置、临时数据库（SQLite 与 PostgreSQL）、测试用令牌。

PostgreSQL：从 config/test.env 或环境变量读取 LMESH_TEST_PG_URL；设置了 LMESH_TEST_PG_SSH 时自动建 SSH 隧道。
没有可用的 PostgreSQL 时，pg 相关用例跳过并在结果中注明。
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "tests" / "output"
INPUTS = ROOT / "tests" / "inputs"
SAMPLES = ROOT / "knowledge" / "samples"
CASES = ROOT / "tests" / "cases"
TEST_TOKEN = "test-token-0123456789"


def _load_test_env() -> None:
    env_file = ROOT / "config" / "test.env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_test_env()


def _port_open(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str | None]:
    url = os.environ.get("LMESH_TEST_PG_URL")
    if not url:
        yield None
        return
    from sqlalchemy.engine import make_url

    u = make_url(url)
    host, port = u.host or "127.0.0.1", u.port or 5432
    proc = None
    ssh = os.environ.get("LMESH_TEST_PG_SSH")
    if ssh and not _port_open(host, port):
        key = os.path.expanduser(os.environ.get("LMESH_TEST_PG_SSH_KEY", "~/.ssh/lmesh_dev_ed25519"))
        proc = subprocess.Popen(
            [
                "ssh",
                "-N",
                "-o",
                "BatchMode=yes",
                "-o",
                "ExitOnForwardFailure=yes",
                "-i",
                key,
                "-L",
                f"{port}:127.0.0.1:{port}",
                ssh,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(50):
            if _port_open(host, port):
                break
            time.sleep(0.2)
    yield url if _port_open(host, port) else None
    if proc:
        proc.terminate()


@pytest.fixture(params=["sqlite", "pg"])
def db_url(request: pytest.FixtureRequest, tmp_root: Path, pg_url: str | None) -> Iterator[str]:
    """每个数据库相关用例在 SQLite 与 PostgreSQL 上各跑一次。PostgreSQL 用独立 schema，用完删除。"""
    if request.param == "sqlite":
        yield f"sqlite:///{(tmp_root / 'data' / 'test.db').as_posix()}"
        return
    if not pg_url:
        pytest.skip("没有可用的 PostgreSQL（config/test.env 中的 LMESH_TEST_PG_URL）")
    from sqlalchemy import create_engine, text

    schema = f"t_{uuid.uuid4().hex[:10]}"
    admin = create_engine(pg_url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    sep = "&" if "?" in pg_url else "?"
    yield f"{pg_url}{sep}options=-csearch_path%3D{schema}"
    from lmesh.core import store

    store.dispose_all()
    with admin.begin() as conn:
        conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


@pytest.fixture
def tmp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """临时项目根目录：不读写开发者本机的 config/ 与 data/。"""
    root = tmp_path / "root"
    for d in ("config", "data", "logs"):
        (root / d).mkdir(parents=True)
    if (ROOT / "knowledge").exists():
        # 复制知识库时不带抽取出的命令卡文件（几千张卡会拖慢测试，并与测试用的卡冲突）；视图、Schema、Profile 保留
        def _skip_cards(directory: str, names: list[str]) -> set[str]:
            if Path(directory).parent.name == "commands":
                return {n for n in names if n.endswith(".yaml") and n != "views.yaml"}
            return set()

        shutil.copytree(ROOT / "knowledge", root / "knowledge", ignore=_skip_cards)
    monkeypatch.setenv("LMESH_ROOT", str(root))
    for k in list(os.environ):
        if k.startswith("LMESH_") and "__" in k:
            monkeypatch.delenv(k)
    monkeypatch.delenv("LMESH_CONFIG_FILE", raising=False)
    from lmesh import paths

    paths.project_root.cache_clear()
    yield root
    paths.project_root.cache_clear()
    from lmesh.core import store

    store.dispose_all()


@pytest.fixture
def full_kb_root(tmp_root: Path) -> Path:
    """带上全部抽取出的命令卡（解析、建图、往返相关的用例需要）。"""
    shutil.copytree(ROOT / "knowledge" / "commands", tmp_root / "knowledge" / "commands", dirs_exist_ok=True)
    return tmp_root


def prepare(setup: str | None, request: pytest.FixtureRequest) -> None:
    """用例的准备方式：fresh / configured / fresh-fullkb / configured-fullkb / configured-fullkb-history / configured-users /
    configured-notoken / configured-fullkb-checkproj / configured-projects。"""
    if setup and "fullkb" in setup:
        request.getfixturevalue("full_kb_root")
    if setup and setup.startswith("configured"):
        request.getfixturevalue("configured_root")
    if setup and setup.endswith("-history"):
        request.getfixturevalue("history_root")
    if setup and setup.endswith("-users"):
        request.getfixturevalue("users_root")
    if setup and setup.endswith("-checkproj"):
        request.getfixturevalue("checkproj_root")
    if setup and setup.endswith("-projects"):
        request.getfixturevalue("projects_root")
    if setup and setup.endswith("-notoken"):  # 实例没有设置 API 令牌（环境变量覆盖为空）
        request.getfixturevalue("monkeypatch").setenv("LMESH_SECURITY__API_TOKEN", "")


HISTORY_DEVICE = "ATN-CHANGE-01"


@pytest.fixture
def history_root(configured_root: Path) -> Path:
    """版本历史用例：设备 ATN-CHANGE-01 导入三次——基准、内容相同的重复导入（不存新快照）、改了描述与 MTU 的版本。"""
    from lmesh.core import config, importer, kbservice, store

    settings = config.load()
    store.upgrade(settings.database_url)
    base = (SAMPLES / "change" / "atn-base.cfg").read_text(encoding="utf-8")
    changed = base.replace("UPLINK-TO-AGG", "UPLINK-TO-AGG-01").replace(" mtu 9000", " mtu 9216")
    kb_root = kbservice.runtime_root(settings)
    for name, text in (("v1.cfg", base), ("v1-again.cfg", base), ("v2.cfg", changed)):
        importer.import_sources([(name, text.encode())], settings.database_url, "basic", kb_root, actor="tester")
    return configured_root


@pytest.fixture
def checkproj_root(history_root: Path) -> Path:
    """配置检查项目用例（REQ-031）：在版本历史的准备之上建项目 1（基线 ATN-CHANGE-01，跟随最新版本），
    脚本 1 是有顺序错误的变更脚本、脚本 2 是完整配置（各有一条创建时的修订）。"""
    from lmesh.core import checkproj, config

    url = config.load().database_url
    me = checkproj.Actor(None, True, "tester")
    p = checkproj.create_project(url, me, {"name": "割接前检查", "device_id": 1})
    scripts = INPUTS / "scripts"
    for name, kind, f in (("绑定 VPN", "change", "atn-change-order.txt"), ("完整配置", "full", "atn-full.cfg")):
        content = (scripts / f).read_text(encoding="utf-8")
        checkproj.create_script(url, me, p["id"], {"name": name, "kind": kind, "content": content})
    return history_root


# 账号用例（REQ-030）：管理员 admin 与普通用户 alice
TEST_USERS = {"admin": ("Admin-pass-1", "admin"), "alice": ("Alice-pass-1", "user")}


@pytest.fixture
def users_root(configured_root: Path) -> Path:
    from lmesh.core import config, store, users

    url = config.load().database_url
    store.upgrade(url)
    for name, (pw, role) in TEST_USERS.items():
        users.create_user(url, name, pw, role)
    return configured_root


@pytest.fixture
def projects_root(users_root: Path) -> Path:
    """项目用例（M6）：在账号用例之上加普通用户 bob、carol（不是任何项目的成员）；alice 的项目 lab（导入 ATN-CHANGE-01，bob 为只读成员）；
    公共设备库里一台 ASR920-BASE（管理员导入），lab 引用它并跟随最新版本。"""
    from lmesh.core import config, importer, kbservice, projects, users

    url = config.load().database_url
    users.create_user(url, "bob", "Bob-pass-12", "user")
    users.create_user(url, "carol", "Carol-pass-1", "user")
    alice = projects.cli_identity(url, "alice")
    projects.create_project(url, alice, {"name": "实验局", "slug": "lab", "description": "实验室设备"})
    scope = projects.resolve(url, alice, "lab")
    projects.set_member(url, scope, "bob", "read")
    kb_root = kbservice.runtime_root(config.load())
    base = (SAMPLES / "change" / "atn-base.cfg").read_bytes()
    other = (SAMPLES / "change" / "asr920-base.cfg").read_bytes()
    with projects.use(scope, alice):
        importer.import_sources([("atn.cfg", base)], url, "basic", kb_root, actor="alice")
    importer.import_sources([("asr.cfg", other)], url, "basic", kb_root, actor="admin", public=True)
    pub = projects.list_public(url)[0]["id"]
    projects.add_ref(url, scope, pub)
    return users_root


@pytest.fixture
def configured_root(tmp_root: Path) -> Path:
    """已完成首次配置的临时项目（SQLite、固定令牌）。"""
    from lmesh.core import setup

    setup.apply({"security.api_token": TEST_TOKEN, "server.port": 9090}, "zh-CN", check_port=False)
    return tmp_root


def run_cli(
    args: list[str], root: Path, env: dict[str, str] | None = None, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    """以子进程执行真实命令（与用户调用方式一致）。"""
    e = {**os.environ, "LMESH_ROOT": str(root), "PYTHONUTF8": "1", **(env or {})}
    return subprocess.run(
        [sys.executable, "-m", "lmesh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=e,
        input=input_text,
        timeout=120,
        cwd=str(root),
    )
