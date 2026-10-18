"""单元测试：用户账号（REQ-030）——密码哈希、账号增删改、最后一个管理员保护、登录锁定、会话（SQLite 与 PostgreSQL）。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from lmesh.core import setup, store, users
from lmesh.core.store.models import User, UserSession

pytestmark = pytest.mark.unit

PW = "Correct-horse-1"


@pytest.fixture
def db(db_url: str) -> str:
    store.upgrade(db_url)
    return db_url


def test_hash_is_salted_scrypt() -> None:
    a, b = users.hash_password(PW), users.hash_password(PW)
    assert a != b and a.startswith("scrypt$16384$8$1$")
    assert PW not in a
    assert users.verify_password(PW, a) and not users.verify_password("wrong-pass", a)
    assert not users.verify_password(PW, "garbage") and not users.verify_password(PW, "md5$x$y$z$a$b")


@pytest.mark.parametrize("name", ["a", "-bad", "has space", "x" * 65, "名字", ""])
def test_invalid_names(name: str) -> None:
    with pytest.raises(users.UserError) as e:
        users.validate_username(name)
    assert e.value.key == "users.invalid_name" and e.value.kind == "param"


def test_password_rules() -> None:
    with pytest.raises(users.UserError, match="users.password_short"):
        users.validate_password("short")
    with pytest.raises(users.UserError, match="users.password_long"):
        users.validate_password("x" * 257)
    assert users.validate_password("12345678") == "12345678"


def test_crud_and_last_admin(db: str) -> None:
    admin = users.create_user(db, "admin", PW, "admin")
    assert admin["role"] == "admin" and not admin["disabled"] and admin["last_login_at"] is None
    assert "password_hash" not in admin
    with pytest.raises(users.UserError) as e:
        users.create_user(db, "ADMIN", PW)
    assert e.value.key == "users.exists" and e.value.kind == "state"
    users.create_user(db, "alice", PW)
    assert [u["username"] for u in users.list_users(db)] == ["admin", "alice"]
    assert users.count(db) == 2
    # 最后一个启用的管理员：不能停用、降级、删除
    for action in (
        lambda: users.update_user(db, "admin", disabled=True),
        lambda: users.update_user(db, "admin", role="user"),
        lambda: users.delete_user(db, "admin"),
    ):
        with pytest.raises(users.UserError) as e:
            action()
        assert e.value.key == "users.last_admin"
    # 有了第二个管理员就可以
    users.update_user(db, "alice", role="admin")
    assert users.update_user(db, "admin", disabled=True)["disabled"] is True
    # 已停用的管理员不算：alice 现在是唯一启用的管理员
    with pytest.raises(users.UserError, match="users.last_admin"):
        users.update_user(db, "alice", role="user")
    assert users.delete_user(db, "admin") == {"deleted": "admin"}
    with pytest.raises(users.UserError) as e:
        users.get_user(db, "admin")
    assert e.value.kind == "not_found"
    with pytest.raises(users.UserError, match="users.invalid_role"):
        users.update_user(db, "alice", role="root")


def test_lockout_and_unlock(db: str, caplog: pytest.LogCaptureFixture) -> None:
    users.create_user(db, "bob", PW)
    caplog.set_level(logging.INFO, logger="lmesh.auth")
    for _ in range(2):
        with pytest.raises(users.AuthError) as e:
            users.authenticate(db, "bob", "wrong-password", max_failures=3, lock_minutes=10)
        assert e.value.reason == "invalid"
    with pytest.raises(users.AuthError) as e:
        users.authenticate(db, "bob", "wrong-password", max_failures=3, lock_minutes=10)
    assert e.value.reason == "locked" and e.value.locked_until is not None
    # 锁定期间连正确的密码也不行
    with pytest.raises(users.AuthError, match="locked"):
        users.authenticate(db, "bob", PW, max_failures=3, lock_minutes=10)
    u = users.get_user(db, "bob")
    assert u["locked"] and u["locked_until"]
    assert users.update_user(db, "bob", unlock=True)["locked"] is False
    assert users.authenticate(db, "bob", PW)["last_login_at"]
    # 日志里有失败与锁定，但没有密码
    text = caplog.text
    assert "bob" in text and "wrong-password" not in text and PW not in text


def test_lock_expires(db: str) -> None:
    users.create_user(db, "carol", PW)
    with store.session(db) as s:
        u = s.scalar(select(User).where(User.username == "carol"))
        assert u is not None
        u.locked_until = datetime.now(UTC) - timedelta(minutes=1)
    assert users.authenticate(db, "carol", PW)["locked"] is False


def test_unknown_and_disabled(db: str) -> None:
    with pytest.raises(users.AuthError, match="invalid"):
        users.authenticate(db, "nobody", PW)
    users.create_user(db, "dave", PW)
    users.create_user(db, "root", PW, "admin")
    users.update_user(db, "dave", disabled=True)
    with pytest.raises(users.AuthError, match="disabled"):
        users.authenticate(db, "dave", PW)
    # 停用账号时密码错误仍按“用户名或密码错误”处理
    with pytest.raises(users.AuthError, match="invalid"):
        users.authenticate(db, "dave", "nope-nope")


def test_sessions(db: str) -> None:
    u = users.create_user(db, "erin", PW, "admin")
    users.create_user(db, "frank", PW, "admin")
    token, expires = users.create_session(db, u["id"], 12)
    assert expires > datetime.now(UTC) + timedelta(hours=11)
    with store.session(db) as s:
        hashes = list(s.scalars(select(UserSession.token_hash)))
    assert token not in hashes and users.token_hash(token) in hashes  # 只存哈希
    me = users.session_user(db, token)
    assert me is not None and me["username"] == "erin" and me["session_expires_at"]
    assert users.session_user(db, "not-a-token") is None
    # 改密码：当前会话保留，其他会话失效
    other, _ = users.create_session(db, u["id"], 12)
    r = users.change_password(db, u["id"], PW, "New-password-2", keep_token=token)
    assert r == {"changed": True, "sessions_closed": 1}
    assert users.session_user(db, token) and users.session_user(db, other) is None
    with pytest.raises(users.UserError, match="auth.wrong_password"):
        users.change_password(db, u["id"], PW, "Another-pass-3")
    with pytest.raises(users.UserError, match="users.password_same"):
        users.change_password(db, u["id"], "New-password-2", "New-password-2")
    # 重置密码、停用：会话全部失效
    assert users.reset_password(db, "erin", "Reset-pass-4")["sessions_closed"] == 1
    assert users.session_user(db, token) is None
    t2, _ = users.create_session(db, u["id"], 12)
    users.update_user(db, "erin", disabled=True)
    assert users.session_user(db, t2) is None
    # 登出
    t3, _ = users.create_session(db, users.get_user(db, "frank")["id"], 12)
    assert users.end_session(db, t3) == "frank" and users.end_session(db, t3) is None


def test_expired_session(db: str) -> None:
    u = users.create_user(db, "gina", PW)
    token, _ = users.create_session(db, u["id"], 1)
    with store.session(db) as s:
        row = s.scalar(select(UserSession))
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert users.session_user(db, token) is None


def test_setup_creates_admin(tmp_root: Path) -> None:
    errors = setup.validate_admin({"username": "x", "password": "short"})
    assert errors == {"admin.username": "users.invalid_name", "admin.password": "users.password_short"}
    r = setup.apply({}, "zh-CN", check_port=False, admin={"username": "admin", "password": PW})
    assert r["admin"]["username"] == "admin" and r["admin"]["role"] == "admin"
    assert PW not in str(r)
    from lmesh.core import config

    url = config.load().database_url
    assert users.count(url) == 1
    # 配置文件里没有密码
    assert PW not in config.config_path().read_text(encoding="utf-8")
