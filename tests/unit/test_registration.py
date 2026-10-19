"""用户自助注册（REQ-039）：注册（需审核 / 直接可用）、待审核不能登录、批准后建好默认项目、拒绝即删除、
频率限制、开关配置项；SQLite 与 PostgreSQL 各一次（频率限制与配置不涉及数据库）。"""

from __future__ import annotations

import pytest

from lmesh.core import config, projects, store, users

pytestmark = pytest.mark.unit
PW = "Pass-word-123"


@pytest.fixture
def url(db_url: str) -> str:
    store.upgrade(db_url)
    users.create_user(db_url, "boss", PW, "admin")
    return db_url


def test_register_pending_then_approve(url: str) -> None:
    u = users.register(url, "newbie", PW, approval=True)
    assert u["status"] == "pending" and u["origin"] == "register" and u["role"] == "user"
    with pytest.raises(users.AuthError) as e:
        users.authenticate(url, "newbie", PW)
    assert e.value.reason == "pending"
    with pytest.raises(users.AuthError) as e:  # 密码不对时不提示待审核
        users.authenticate(url, "newbie", "wrong-password")
    assert e.value.reason == "invalid"
    assert [x["username"] for x in users.list_users(url, "pending")] == ["newbie"]
    assert users.count_pending(url) == 1
    # 批准：可以登录，默认项目已建好
    users.approve(url, "newbie")
    assert users.authenticate(url, "newbie", PW)["status"] == "active"
    ident = projects.cli_identity(url, "newbie")
    lists = projects.list_projects(url, ident)
    assert [p["slug"] for p in lists["mine"]] == ["default"] and lists["default_project"] == "default"
    with pytest.raises(users.UserError) as ue:
        users.approve(url, "newbie")
    assert ue.value.key == "users.not_pending"


def test_register_without_approval_and_reject(url: str) -> None:
    u = users.register(url, "quick", PW, approval=False)
    assert u["status"] == "active"
    assert projects.list_projects(url, projects.cli_identity(url, "quick"))["mine"][0]["slug"] == "default"
    # 用户名规则与重名沿用账号管理
    with pytest.raises(users.UserError):
        users.register(url, "Quick", PW, approval=True)
    with pytest.raises(users.UserError):
        users.register(url, "x", PW, approval=True)
    with pytest.raises(users.UserError):
        users.register(url, "shortpw", "1234", approval=True)
    # 拒绝：只限待审核账号；拒绝后删除，用户名可以再注册
    with pytest.raises(users.UserError):
        users.reject(url, "quick")
    users.register(url, "later", PW, approval=True)
    assert users.reject(url, "later")["deleted"] is True
    assert users.register(url, "later", PW, approval=True)["status"] == "pending"


def test_rate_limiter() -> None:
    rl = users.RateLimiter(window=3600)
    assert all(rl.allow("1.2.3.4", 3) for _ in range(3))
    assert not rl.allow("1.2.3.4", 3)
    assert rl.allow("5.6.7.8", 3)  # 按来源地址分开计
    rl.window = 0  # 窗口过去后重新计数
    assert rl.allow("1.2.3.4", 3)


def test_registration_config_fields() -> None:
    assert config.FIELD_MAP["auth.registration"].default is False
    assert config.FIELD_MAP["auth.registration_approval"].default is True
    assert config.FIELD_MAP["auth.registration_rate_per_hour"].default == 5
    assert config.validate("auth.registration", "true") is True
    assert config.validate("auth.registration", "off") is False
    with pytest.raises(config.ConfigError):
        config.validate("auth.registration", "maybe")
    with pytest.raises(config.ConfigError):
        config.validate("auth.registration_rate_per_hour", 0)
    assert "[auth]" in config.example_text() and "registration = false" in config.example_text()
