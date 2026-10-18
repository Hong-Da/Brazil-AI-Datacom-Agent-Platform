"""单元测试：配置加载与优先级、校验、密钥加密、多语言、数据库迁移（SQLite 与 PostgreSQL）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lmesh import paths
from lmesh.core import config, i18n, setup, store

pytestmark = pytest.mark.unit


def test_defaults_without_file(tmp_root: Path) -> None:
    s = config.load()
    assert s.get("server.host") == "0.0.0.0"
    assert s.get("server.port") == 9090
    assert s.sources["server.port"] == "default"
    assert s.database_url.endswith("/data/lmesh.db")


def test_priority_env_over_file(tmp_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config.write({"server.port": 9100, "log.keep_days": 30})
    assert config.load().get("server.port") == 9100
    monkeypatch.setenv("LMESH_SERVER__PORT", "9200")
    s = config.load()
    assert s.get("server.port") == 9200 and s.sources["server.port"] == "env"
    assert s.get("log.keep_days") == 30 and s.sources["log.keep_days"] == "file"


def test_invalid_file_value_falls_back(tmp_root: Path) -> None:
    config.config_path().write_text('[server]\nport = "abc"\n', encoding="utf-8")
    s = config.load()
    assert s.get("server.port") == 9090 and s.sources["server.port"] == "default(invalid)"


@pytest.mark.parametrize(
    ("key", "value", "err"),
    [
        ("server.port", 0, "range"),
        ("server.port", "x", "int"),
        ("server.host", "localhost", "host"),
        ("ui.language", "fr", "choice"),
        ("database.url", "mysql://x", "dburl"),
        ("log.keep_days", 400, "range"),
    ],
)
def test_validate_rejects(key: str, value: object, err: str) -> None:
    with pytest.raises(config.ConfigError) as e:
        config.validate(key, value)
    assert e.value.args[0] == err


def test_path_outside_project_rejected(tmp_root: Path, tmp_path: Path) -> None:
    with pytest.raises(config.ConfigError):
        config.validate("knowledge.dir", str(tmp_path / "elsewhere"))
    assert config.validate("knowledge.dir", "data/kb") == "data/kb"


def test_secret_roundtrip_and_key_inside_project(tmp_root: Path) -> None:
    enc = config.encrypt_secret("sk-test-áéçã")
    assert enc.startswith("enc:") and "sk-test" not in enc
    assert config.decrypt_secret(enc) == "sk-test-áéçã"
    assert (paths.config_dir() / "secret.key").exists()


def test_written_file_has_comments_in_language(tmp_root: Path) -> None:
    config.write({}, lang="pt-BR")
    text = config.config_path().read_text(encoding="utf-8")
    assert "Endereço de escuta" in text and "[server]" in text
    assert config.load().get("server.port") == 9090


def test_example_is_up_to_date() -> None:
    example = paths.PACKAGE_DIR.parent.parent / "config" / "config.example.toml"
    assert example.read_text(encoding="utf-8") == config.example_text(), "运行 lmesh config example 重新生成"


def test_locale_keys_identical() -> None:
    keys = {
        lang: set(json.loads((paths.PACKAGE_DIR / "locales" / f"{lang}.json").read_text(encoding="utf-8")))
        for lang in i18n.LANGS
    }
    assert keys["zh-CN"] == keys["en"] == keys["pt-BR"]


@pytest.mark.parametrize(
    ("header", "lang"),
    [
        ("pt-PT,pt;q=0.9", "pt-BR"),
        ("en-US,en;q=0.9", "en"),
        ("fr-FR,de;q=0.8", "zh-CN"),
        (None, "zh-CN"),
        ("fr,en;q=0.5", "en"),
    ],
)
def test_accept_language(header: str | None, lang: str) -> None:
    assert i18n.from_accept_language(header) == lang


def test_t_falls_back_to_chinese() -> None:
    assert i18n.t("common.yes", "pt-BR") == "sim"
    assert i18n.t("no.such.key", "en") == "no.such.key"


def test_migrations(db_url: str) -> None:
    store.upgrade(db_url)
    store.upgrade(db_url)  # 幂等
    names = store.table_names(db_url)
    for t in ("devices", "config_versions", "nodes", "edges", "review_items", "unknown_lines", "tasks", "ai_calls"):
        assert t in names


def test_json_column_roundtrip(db_url: str) -> None:
    from lmesh.core.store.models import ConfigVersion, Device

    store.upgrade(db_url)
    with store.session(db_url) as s:
        d = Device(name="PE-AÇÃO-01", vendor="huawei")
        s.add(d)
        s.flush()
        s.add(ConfigVersion(device_id=d.id, raw_text="sysname PE\n", structured={"lines": [1, 2], "名称": "ação"}))
    with store.session(db_url) as s:
        v = s.query(ConfigVersion).one()
        assert v.structured["名称"] == "ação"


def test_setup_apply_generates_token(tmp_root: Path) -> None:
    result = setup.apply({}, "en", check_port=False)
    assert result["token_generated"] and len(result["api_token"]) >= 32
    assert config.is_configured()
    s = config.load()
    assert s.get("security.api_token") == result["api_token"]


def test_setup_rejects_and_encrypts(tmp_root: Path) -> None:
    with pytest.raises(setup.SetupError) as e:
        setup.apply({"server.port": 0, "ai.provider": "openai"}, "zh-CN", check_port=False)
    assert set(e.value.errors) == {"server.port", "ai.base_url"}
    setup.apply({"ai.provider": "anthropic", "ai.api_key": "sk-secret"}, "zh-CN", check_port=False)
    raw = config.config_path().read_text(encoding="utf-8")
    assert "sk-secret" not in raw and config.load().ai_api_key() == "sk-secret"
