"""M9-7 评审修改的接口：个人偏好随账号保存（REQ-047）、向导里测试 AI 连接（REQ-048）、系统设置（REQ-049）。

AI 一律用假的客户端（替换 ai.provider_hook），不调用外部服务。"""

from __future__ import annotations

import logging
import socket
from pathlib import Path
from typing import Any

import pytest

from lmesh.core import ai
from tests.api.test_projects_api import Client, _app, _audit, _users
from tests.conftest import TEST_TOKEN

pytestmark = pytest.mark.api
KEY = "sk-secret-for-test-0123456789"


# ---------------------------------------------------------------- REQ-047 个人偏好


def test_prefs_follow_the_account(configured_root: Path) -> None:
    _users({"liwei": "user", "zhang": "user"})
    app = _app()
    liwei = Client(app, "liwei")

    # 还没保存过：prefs 为 null（网页登录后把浏览器本地值写入账号）
    assert liwei.get("/me/prefs").json()["data"] == {"has_account": True, "prefs": None}
    r = liwei.put("/me/prefs", json={"lang": "en", "theme": "dark"})
    assert r.status_code == 200 and r.json()["data"]["prefs"] == {"lang": "en", "theme": "dark"}
    # 只改给出的项，其余保留
    r = liwei.put("/me/prefs", json={"term_style": "cisco", "icon_set": "cyl"})
    assert r.json()["data"]["prefs"] == {"lang": "en", "theme": "dark", "term_style": "cisco", "icon_set": "cyl"}

    # 换一个“浏览器”（新会话）登录：账号的值还在；别的账号互不影响
    again = Client(app, "liwei")
    assert again.get("/me/prefs").json()["data"]["prefs"]["term_style"] == "cisco"
    assert Client(app, "zhang").get("/me/prefs").json()["data"]["prefs"] is None

    # 取值与项目名校验
    assert liwei.put("/me/prefs", json={"theme": "purple"}).status_code == 422
    assert liwei.put("/me/prefs", json={"lang": "fr"}).status_code == 422

    # 个人令牌：读写令牌能保存；只读令牌能读不能写；全局令牌没有账号
    rw = liwei.post("/tokens", json={"name": "rw"}).json()["data"]["token"]
    ro = liwei.post("/tokens", json={"name": "ro", "read_only": True}).json()["data"]["token"]
    assert Client(app, token=rw).put("/me/prefs", json={"theme": "light"}).status_code == 200
    reader = Client(app, token=ro)
    assert reader.get("/me/prefs").json()["data"]["prefs"]["theme"] == "light"
    assert reader.put("/me/prefs", json={"theme": "dark"}).status_code == 403
    glob = Client(app, token=TEST_TOKEN)
    assert glob.get("/me/prefs").json()["data"] == {"has_account": False, "prefs": None}
    r = glob.put("/me/prefs", json={"theme": "dark"})
    assert r.status_code == 409 and r.json()["code"] == 1003
    assert Client(app).get("/me/prefs").status_code == 401

    # 清除：恢复为“没保存过”
    assert liwei.delete("/me/prefs").json()["data"]["prefs"] is None
    assert liwei.get("/me/prefs").json()["data"]["prefs"] is None
    assert reader.delete("/me/prefs").status_code == 403 and glob.delete("/me/prefs").status_code == 409


# ---------------------------------------------------------------- REQ-048 向导里测试 AI 连接


def test_setup_ai_test_does_not_keep_the_key(
    tmp_root: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    seen: list[Any] = []

    def ok_hook(conn: Any, model: str, system: str, prompt: str) -> ai.Reply:
        seen.append((conn.provider, conn.base_url, conn.api_key(), model))
        return ai.Reply("OK", model, 7, 1)

    monkeypatch.setattr(ai, "provider_hook", ok_hook)
    app = _app()
    anon = Client(app)
    caplog.set_level(logging.DEBUG)
    r = anon.post("/setup/ai-test", json={"provider": "anthropic", "api_key": KEY, "model": "claude-x"})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["model"] == "claude-x" and d["reply"] == "OK" and d["elapsed_ms"] >= 0
    assert seen == [("anthropic", "", KEY, "claude-x")]
    assert KEY not in r.text

    # 失败：只返回异常类型与 HTTP 状态码；Key 不进日志
    class AuthErr(Exception):
        status_code = 401

    def bad_hook(conn: Any, model: str, system: str, prompt: str) -> ai.Reply:
        raise AuthErr(f"bad key {conn.api_key()}")

    monkeypatch.setattr(ai, "provider_hook", bad_hook)
    r = anon.post(
        "/setup/ai-test", json={"provider": "openai", "base_url": "http://127.0.0.1:1/v1", "api_key": KEY, "model": "m"}
    )
    assert r.status_code == 502 and r.json()["code"] == 1005
    assert r.json()["data"] == {"error_type": "AuthErr", "status": 401}
    assert KEY not in r.text and KEY not in caplog.text

    # 没有配置文件、没有数据库：测试不写任何东西
    root = tmp_root
    assert not (root / "config" / "config.toml").exists()
    assert not (root / "data" / "lmesh.db").exists()

    # 必填项：本地模型要地址
    r = anon.post("/setup/ai-test", json={"provider": "local", "model": "llama"})
    assert r.status_code == 422 and set(r.json()["data"]["errors"]) == {"ai.base_url"}


# ---------------------------------------------------------------- REQ-049 系统设置


def _field(view: dict[str, Any], key: str) -> dict[str, Any]:
    return next(f for g in view["groups"] for f in g["fields"] if f["key"] == key)


def test_settings_page_flow(configured_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LMESH_AUTH__REGISTRATION", "false")
    from lmesh.api import create_app
    from lmesh.core import config

    _users({"boss": "admin", "liwei": "user"})
    app = create_app(config.load())
    boss = Client(app, "boss")
    assert Client(app, "liwei").get("/settings").status_code == 403
    assert Client(app, "liwei").put("/settings", json={"values": {"log.level": "DEBUG"}}).status_code == 403

    view = boss.get("/settings").json()["data"]
    assert [g["id"] for g in view["groups"]] == ["ui", "network", "data", "security", "log", "ai"]
    assert _field(view, "server.port")["restart"] is True and _field(view, "history.keep")["restart"] is False
    assert _field(view, "security.api_token")["value"] is True  # 敏感值只显示是否已设置
    assert _field(view, "security.api_token")["readonly"] == "secret"
    assert _field(view, "auth.registration")["readonly"] == "env"
    assert _field(view, "ai.provider")["readonly"] == "ai"
    assert _field(view, "ai.timeout")["readonly"] is None
    assert view["restart_pending"] == [] and view["config_path"].endswith("config.toml")
    assert TEST_TOKEN not in str(view)

    # dry_run 只校验
    r = boss.put("/settings", json={"values": {"history.keep": 5}, "dry_run": True})
    assert r.json()["data"] == {"valid": True}
    assert config.load().get("history.keep") != 5

    # 保存：立即生效的项（history.keep）和要重启的项（端口、日志级别）
    running_port = int(config.load().get("server.port"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    r = boss.put("/settings", json={"values": {"history.keep": 77, "server.port": free, "log.level": "DEBUG"}})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["changed"] == ["history.keep", "log.level", "server.port"]
    assert {p["key"]: (p["running"], p["saved"]) for p in d["restart_pending"]} == {
        "server.port": (running_port, free),
        "log.level": ("INFO", "DEBUG"),
    }
    text = (configured_root / "config" / "config.toml").read_text(encoding="utf-8")
    assert f"port = {free}" in text and "keep = 77" in text and "# " in text  # 注释保留
    assert app.state.settings.get("history.keep") == 77  # 已生效
    # 重新打开页面仍能看到待重启的项
    assert len(boss.get("/settings").json()["data"]["restart_pending"]) == 2
    assert any(e["action"] == "settings.update" for e in _audit(app))

    # 不合格：逐项返回原因，什么都不写
    with socket.socket() as busy:
        busy.bind(("0.0.0.0", 0))
        busy.listen(1)
        used = busy.getsockname()[1]
        r = boss.c.put(
            "/api/v1/settings",
            json={"values": {"server.port": used, "history.keep": -1, "auth.registration": True, "nope.x": 1}},
            headers={"Accept-Language": "en"},
        )
    assert r.status_code == 422
    errs = r.json()["data"]["errors"]
    assert set(errs) == {"server.port", "history.keep", "auth.registration", "nope.x"}
    assert "use" in errs["server.port"] and errs["nope.x"] == "No such setting"
    assert config.load().get("history.keep") == 77

    # 改回正在运行的端口：不用检查占用，也不再需要重启
    r = boss.put("/settings", json={"values": {"server.port": running_port, "log.level": "INFO"}})
    assert r.status_code == 200 and r.json()["data"]["restart_pending"] == []
