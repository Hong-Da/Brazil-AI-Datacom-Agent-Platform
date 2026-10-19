"""公共夹具：临时项目根目录、临时配置、临时数据库（SQLite 与 PostgreSQL）、测试用令牌。

PostgreSQL：从 config/test.env 或环境变量读取 LMESH_TEST_PG_URL；设置了 LMESH_TEST_PG_SSH 时自动建 SSH 隧道。
没有可用的 PostgreSQL 时，pg 相关用例跳过并在结果中注明。
并行（pytest-xdist）时：隧道由主进程建一次；PostgreSQL schema 名带 worker 名；每个 worker 有自己的共用只读知识库副本。
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
from typing import Any

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


def _pg_address() -> tuple[str, str, int] | None:
    url = os.environ.get("LMESH_TEST_PG_URL")
    if not url:
        return None
    from sqlalchemy.engine import make_url

    u = make_url(url)
    return url, u.host or "127.0.0.1", u.port or 5432


def _open_tunnel(host: str, port: int) -> subprocess.Popen[bytes] | None:
    """设置了 LMESH_TEST_PG_SSH 且端口没开时建 SSH 隧道。"""
    ssh = os.environ.get("LMESH_TEST_PG_SSH")
    if not ssh or _port_open(host, port):
        return None
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
    return proc


def _xdist_worker() -> str | None:
    """并行（pytest-xdist）时当前 worker 的名字，如 gw3；串行时 None。"""
    return os.environ.get("PYTEST_XDIST_WORKER")


def pytest_configure(config: pytest.Config) -> None:
    # 并行时由主进程建一次 SSH 隧道、所有 worker 共用（worker 各建各的会在先结束的 worker 退出时断开别人的连接）
    if hasattr(config, "workerinput") or not getattr(config.option, "numprocesses", None):
        return
    addr = _pg_address()
    if addr:
        config._lmesh_pg_tunnel = _open_tunnel(addr[1], addr[2])  # type: ignore[attr-defined]


def pytest_unconfigure(config: pytest.Config) -> None:
    proc = getattr(config, "_lmesh_pg_tunnel", None)
    if proc:
        proc.terminate()


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str | None]:
    addr = _pg_address()
    if not addr:
        yield None
        return
    url, host, port = addr
    proc = None if _xdist_worker() else _open_tunnel(host, port)
    yield url if _port_open(host, port) else None
    if proc:
        proc.terminate()


@pytest.fixture(params=["sqlite", "pg"])
def db_url(request: pytest.FixtureRequest, tmp_root: Path, pg_url: str | None) -> Iterator[str]:
    """每个数据库相关用例在 SQLite 与 PostgreSQL 上各跑一次。PostgreSQL 用独立 schema（名字带并行 worker 名与随机串），用完删除。"""
    if request.param == "sqlite":
        yield f"sqlite:///{(tmp_root / 'data' / 'test.db').as_posix()}"
        return
    if not pg_url:
        pytest.skip("没有可用的 PostgreSQL（config/test.env 中的 LMESH_TEST_PG_URL）")
    from sqlalchemy import create_engine, text

    schema = f"t_{_xdist_worker() or 'main'}_{uuid.uuid4().hex[:10]}"
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


def _skip_cards(directory: str, names: list[str]) -> set[str]:
    """复制知识库时不带抽取出的命令卡文件（几千张卡会拖慢测试，并与测试用的卡冲突）；视图、Schema、Profile 保留。"""
    if Path(directory).parent.name == "commands":
        return {n for n in names if n.endswith(".yaml") and n != "views.yaml"}
    return set()


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    """目录下每个文件与子目录的（大小，修改时间）：用来发现谁改了共用的知识库。"""
    out: dict[str, tuple[int, int]] = {}
    stack = [root]
    while stack:
        d = stack.pop()
        with os.scandir(d) as it:
            for e in it:
                st = e.stat(follow_symlinks=False)
                out[os.path.relpath(e.path, root)] = (st.st_size if e.is_file() else -1, st.st_mtime_ns)
                if e.is_dir(follow_symlinks=False):
                    stack.append(Path(e.path))
    return out


def _link_dir(link: Path, target: Path) -> bool:
    """建目录链接（Windows 用目录联接，不需要管理员权限；其他系统用符号链接）。建不了时返回 False，由调用方改为复制。"""
    try:
        if os.name == "nt":
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
    except OSError:
        return False
    return True


def _unlink_dir(link: Path) -> None:
    """只删链接本身，不碰目标目录。"""
    if os.name == "nt":
        os.rmdir(link)
    else:
        os.unlink(link)


class SharedKnowledge:
    """每个测试进程（并行时每个 worker）共用的只读知识库副本：lite 不带命令卡，full 带全部命令卡。

    用例的 tmp_root/knowledge 是指向它的链接，省去每个用例复制、删除知识库。用例结束时比对快照：
    共用副本被改动时恢复它，并让该用例报错（提示加 @pytest.mark.kb_write），不会影响后面的用例。
    """

    def __init__(self, base: Path) -> None:
        self.base = base
        self.snaps: dict[str, dict[str, tuple[int, int]]] = {}

    def path(self, kind: str) -> Path:
        p = self.base / kind
        if kind not in self.snaps:
            self._build(kind)
        return p

    def _build(self, kind: str) -> None:
        p = self.base / kind
        if p.exists():
            shutil.rmtree(p)
        shutil.copytree(ROOT / "knowledge", p, ignore=_skip_cards if kind == "lite" else None)
        self.snaps[kind] = _snapshot(p)

    def check(self, kind: str) -> list[str]:
        """返回被改动的路径（并恢复副本）；没有改动时返回空列表。"""
        now = _snapshot(self.base / kind)
        old = self.snaps[kind]
        changed = sorted(k for k in old.keys() | now.keys() if old.get(k) != now.get(k))
        if changed:
            self._build(kind)
        return changed


@pytest.fixture(scope="session")
def shared_knowledge(tmp_path_factory: pytest.TempPathFactory) -> SharedKnowledge:
    return SharedKnowledge(tmp_path_factory.mktemp("kb-shared", numbered=False))


class _KbLink:
    """当前用例的 tmp_root/knowledge：链接到哪份共用副本（None 表示用例自己的副本）。"""

    def __init__(self, root: Path, shared: SharedKnowledge | None) -> None:
        self.root, self.shared, self.kind = root, shared, None if shared is None else "lite"

    def use_full(self) -> None:
        """改为带全部命令卡的知识库（full_kb_root）。"""
        target = self.root / "knowledge"
        if self.shared is None:
            shutil.copytree(ROOT / "knowledge" / "commands", target / "commands", dirs_exist_ok=True)
            return
        _unlink_dir(target)
        self.kind = "full"
        if not _link_dir(target, self.shared.path("full")):
            self.kind = None
            shutil.copytree(ROOT / "knowledge", target)

    def release(self) -> list[str]:
        """删除链接并检查共用副本；返回被改动的路径。"""
        if self.shared is None or self.kind is None:
            return []
        _unlink_dir(self.root / "knowledge")
        return self.shared.check(self.kind)


@pytest.fixture
def tmp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> Iterator[Path]:
    """临时项目根目录：不读写开发者本机的 config/ 与 data/。

    knowledge/（程序自带的知识库）默认链接到进程内共用的只读副本；会写入它的用例加 @pytest.mark.kb_write，
    改为复制一份自己的。没加标记却写了的用例会在结束时报错。
    """
    root = tmp_path / "root"
    for d in ("config", "data", "logs"):
        (root / d).mkdir(parents=True)
    link = _KbLink(root, None)
    if (ROOT / "knowledge").exists():
        own = request.node.get_closest_marker("kb_write") is not None or os.environ.get("LMESH_TEST_KB_COPY") == "1"
        shared: SharedKnowledge | None = None if own else request.getfixturevalue("shared_knowledge")
        if shared is not None and _link_dir(root / "knowledge", shared.path("lite")):
            link = _KbLink(root, shared)
        else:
            shutil.copytree(ROOT / "knowledge", root / "knowledge", ignore=_skip_cards)
    root_links[root] = link
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
    changed = root_links.pop(root).release()
    if changed:
        pytest.fail(
            "用例写入了共用的只读知识库（已恢复）。请给它加 @pytest.mark.kb_write（CLI / API 用例在 toml 里写 kb_write = true）。"
            f"改动：{changed[:10]}",
            pytrace=False,
        )


root_links: dict[Path, _KbLink] = {}


def kb_params(cases: list[dict[str, Any]]) -> list[Any]:
    """toml 用例写了 kb_write = true 时加 kb_write 标记（用自己的知识库副本）。"""
    return [pytest.param(c, marks=[pytest.mark.kb_write] if c.get("kb_write") else []) for c in cases]


@pytest.fixture
def full_kb_root(tmp_root: Path) -> Path:
    """带上全部抽取出的命令卡（解析、建图、往返相关的用例需要）。"""
    root_links[tmp_root].use_full()
    return tmp_root


def prepare(setup: str | None, request: pytest.FixtureRequest) -> None:
    """用例的准备方式：fresh / configured / fresh-fullkb / configured-fullkb / configured-fullkb-history / configured-users /
    configured-notoken / configured-fullkb-checkproj / configured-projects / configured-samename / configured-pending /
    configured-ai。"""
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
    if setup and setup.endswith("-samename"):
        request.getfixturevalue("samename_root")
    if setup and setup.endswith("-pending"):
        request.getfixturevalue("pending_root")
    if setup and setup.endswith("-ai"):
        request.getfixturevalue("ai_root")
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
def samename_root(projects_root: Path) -> Path:
    """标识按属主唯一（M6 评审改选）：在项目用例之上，carol 也有一个 lab，bob 是两个 lab 的只读成员（只写 lab 会歧义）。"""
    from lmesh.core import config, projects

    url = config.load().database_url
    carol = projects.cli_identity(url, "carol")
    projects.create_project(url, carol, {"name": "carol 的实验局", "slug": "lab"})
    projects.set_member(url, projects.resolve(url, carol, "lab"), "bob", "read")
    return projects_root


@pytest.fixture
def pending_root(users_root: Path) -> Path:
    """自助注册（REQ-039）：在账号用例之上，dave 与 erin 自助注册后待审核。"""
    from lmesh.core import config, users

    url = config.load().database_url
    users.register(url, "dave", "Dave-pass-12", approval=True)
    users.register(url, "erin", "Erin-pass-12", approval=True)
    return users_root


@pytest.fixture
def ai_root(users_root: Path) -> Path:
    """AI 接口用例（REQ-040）：在账号用例之上加普通用户 bob；管理员接口 shared（允许公共使用）与 internal（不公开），
    地址指向本机不存在的端口（不会调用外部服务）；alice 有个人接口（Key alice-secret-key）并选用它。"""
    from lmesh.core import ai_connections, config, projects, users

    s = config.load()
    users.create_user(s.database_url, "bob", "Bob-pass-12", "user")
    base = {"provider": "openai", "base_url": "http://127.0.0.1:9/v1", "model": "fake-model"}
    ai_connections.create_connection(s, {"name": "shared", "public": True, "api_key": "shared-secret-key", **base})
    ai_connections.create_connection(s, {"name": "internal", "public": False, **base, "model": "fake-big"})
    alice = projects.cli_identity(s.database_url, "alice")
    ai_connections.save_mine(
        s, alice, {"personal": {**base, "model": "alice-model", "api_key": "alice-secret-key"}, "choice": "personal"}
    )
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
