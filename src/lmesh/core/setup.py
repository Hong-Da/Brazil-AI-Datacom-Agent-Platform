"""首次运行向导的核心逻辑：Web 向导与命令行向导共用。"""

from __future__ import annotations

import os
import shutil
import socket
from typing import Any

from lmesh import paths
from lmesh.core import ai_connections, config, store, users
from lmesh.core.config import FIELDS, GROUP_TITLES, ConfigError


def _field_def(f: config.Field, lang: str) -> dict[str, Any]:
    return {
        "key": f.key,
        "kind": f.kind,
        # 开关（bool）在向导里按两个选项给出：true / false
        "default": ("true" if f.default else "false") if f.kind == "bool" else f.default,
        "choices": ["true", "false"] if f.kind == "bool" else list(f.choices),
        "min": f.minimum,
        "max": f.maximum,
        "secret": f.secret,
        "desc": f.desc.get(lang, f.desc["zh-CN"]),
    }


def _grouped(fields: list[config.Field], lang: str, extra: Any = None) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for f in fields:
        g = groups.setdefault(f.group, {"id": f.group, "title": GROUP_TITLES[f.group].get(lang, f.group), "fields": []})
        g["fields"].append({**_field_def(f, lang), **(extra(f) if extra else {})})
    return list(groups.values())


def wizard_schema(lang: str) -> list[dict[str, Any]]:
    """按“界面 → 网络 → 数据 → 安全 → 日志 → AI”分组列出向导要问的参数。"""
    return _grouped([f for f in FIELDS if f.wizard], lang)


# ---------- 系统设置（REQ-049）：与向导同一份参数定义 ----------

# 改了要重启服务才生效的项（启动时读取：监听地址、数据库连接、知识库目录、日志）
RESTART_KEYS = frozenset({"server.host", "server.port", "database.url", "knowledge.dir", "log.level", "log.keep_days"})
# [ai] 的接口项只是第一个管理员 AI 接口的初始值，之后在 AI 接口页管理：系统设置里只读
AI_SEED_KEYS = frozenset(
    {"ai.provider", "ai.base_url", "ai.api_key", "ai.model"} | {f"ai.{k}" for k in ai_connections.MODEL_FIELDS}
)


def readonly_reason(key: str, settings: config.Settings) -> str | None:
    """系统设置里不能改的原因：secret 敏感值（只能改配置文件或环境变量）/ env 由环境变量指定 / ai 在 AI 接口页管理。"""
    if settings.sources.get(key) == "env":
        return "env"
    if key in AI_SEED_KEYS:
        return "ai"
    if config.FIELD_MAP[key].secret:
        return "secret"
    return None


def _shown(value: Any, f: config.Field) -> Any:
    if f.secret:
        return bool(value)
    if f.kind == "bool":
        return "true" if value else "false"
    return value


def restart_pending(running: config.Settings, saved: config.Settings) -> list[dict[str, Any]]:
    """配置文件里已改、但当前进程还在用旧值的项（需要重启）。敏感值只给出是否已设置。"""
    out = []
    for k in sorted(RESTART_KEYS, key=lambda x: [f.key for f in FIELDS].index(x)):
        if running.get(k) != saved.get(k):
            f = config.FIELD_MAP[k]
            out.append({"key": k, "running": _shown(running.get(k), f), "saved": _shown(saved.get(k), f)})
    return out


def settings_view(lang: str, current: config.Settings, running: config.Settings) -> dict[str, Any]:
    """系统设置页的数据：全部配置项按向导的分组，带当前值、来源、是否需重启、只读原因。"""

    def extra(f: config.Field) -> dict[str, Any]:
        return {
            "value": _shown(current.get(f.key), f),
            "source": current.sources.get(f.key, "default"),
            "restart": f.key in RESTART_KEYS,
            "readonly": readonly_reason(f.key, current),
        }

    return {
        "groups": _grouped(list(FIELDS), lang, extra),
        "config_path": str(config.config_path()),
        "restart_pending": restart_pending(running, current),
        "running": {"server.host": running.get("server.host"), "server.port": running.get("server.port")},
    }


def save_settings(
    updates: dict[str, Any], lang: str, current: config.Settings, running: config.Settings, check_port: bool = True
) -> config.Settings:
    """校验并写入系统设置（只改给出的项，其余保持配置文件里的值）。不合格时抛 SetupError；返回重新读取的配置。"""
    check_settings(updates, current, running, check_port)
    return config.update_file(dict(updates), lang)


def check_settings(
    updates: dict[str, Any], current: config.Settings, running: config.Settings, check_port: bool = True
) -> None:
    """系统设置的校验（不写入）：未知项、只读项、取值；端口与正在运行的不同时才检查是否被占用。"""
    errors: dict[str, str] = {}
    for k in updates:
        if k not in config.FIELD_MAP:
            errors[k] = "config.invalid.unknown"
        elif readonly_reason(k, current):
            errors[k] = f"config.invalid.readonly_{readonly_reason(k, current)}"
    answers = {k: v for k, v in updates.items() if k not in errors}
    if "server.port" in answers or "server.host" in answers:
        answers.setdefault("server.host", current.get("server.host"))
        answers.setdefault("server.port", current.get("server.port"))
    errors.update(validate_answers(answers, check_port=check_port, current_port=int(running.get("server.port"))))
    if errors:
        raise SetupError(errors)


def local_addresses() -> list[str]:
    addrs = {"127.0.0.1", "0.0.0.0"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addrs.add(str(info[4][0]))
    except OSError:
        pass
    return sorted(addrs)


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def validate_answers(
    answers: dict[str, Any], check_port: bool = True, current_port: int | None = None
) -> dict[str, str]:
    """返回 {配置键: 错误文案键}；空字典表示全部合格。"""
    errors: dict[str, str] = {}
    clean: dict[str, Any] = {}
    for f in FIELDS:
        if f.key not in answers:
            continue
        try:
            clean[f.key] = config.validate(f.key, answers[f.key])
        except ConfigError as e:
            errors[f.key] = f"config.invalid.{e.args[0]}"
    if (
        check_port
        and "server.port" in clean
        and "server.host" in clean
        and clean["server.port"] != current_port
        and not port_free(clean["server.host"], clean["server.port"])
    ):
        errors["server.port"] = "config.invalid.port_busy"
    if clean.get("ai.provider") in ("openai", "local") and not str(answers.get("ai.base_url") or "").strip():
        errors["ai.base_url"] = "config.invalid.required"
    return errors


def validate_ai_test(provider: str, base_url: str, model: str) -> dict[str, str]:
    """向导“测试连接”前的检查：接口类型必须选、OpenAI 兼容与本地模型要地址、模型名必填。返回 {配置键: 文案键}。"""
    errors: dict[str, str] = {}
    if provider not in ("anthropic", "openai", "local"):
        errors["ai.provider"] = "config.invalid.choice"
    elif provider in ("openai", "local") and not base_url.strip():
        errors["ai.base_url"] = "config.invalid.required"
    if not model.strip():
        errors["ai.model"] = "config.invalid.required"
    return errors


def validate_admin(admin: dict[str, Any] | None) -> dict[str, str]:
    """向导中“管理员账号”一步：返回 {admin.username / admin.password: 文案键}。"""
    if not admin:
        return {}
    errors: dict[str, str] = {}
    try:
        users.validate_username(str(admin.get("username") or ""))
    except users.UserError as e:
        errors["admin.username"] = e.key
    try:
        users.validate_password(str(admin.get("password") or ""))
    except users.UserError as e:
        errors["admin.password"] = e.key
    return errors


def ensure_runtime_knowledge(settings: config.Settings) -> bool:
    """首次启动时把程序自带的知识库复制到运行时目录；已存在时不动。返回是否复制了。"""
    target = settings.knowledge_dir
    src = paths.builtin_knowledge_dir()
    if target.exists() or not src.exists():
        return False
    # 自带目录里可能有开发时留下的 .git（例如 kb map 直接在 knowledge/ 中提交），不复制：运行时知识库自己建仓
    shutil.copytree(src, target, ignore=shutil.ignore_patterns(".git"))
    return True


def apply(
    answers: dict[str, Any],
    lang: str,
    check_port: bool = True,
    current_port: int | None = None,
    admin: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """校验并写入配置，初始化数据库与运行时知识库；给了 admin（username、password）时创建第一个管理员。

    返回汇总（令牌只在这里显示一次；密码不出现在返回值里）。
    """
    errors = validate_answers(answers, check_port=check_port, current_port=current_port)
    errors.update(validate_admin(admin))
    if errors:
        raise SetupError(errors)
    values = {f.key: answers.get(f.key, f.default) for f in FIELDS}
    # 数据库连接串由环境变量提供（例如 Docker 的 PostgreSQL 版）时不写进配置文件：里面有密码，环境变量照样优先生效
    env_url = os.environ.get(config.env_name("database.url"), "")
    if env_url and values["database.url"] == env_url:
        values["database.url"] = ""
    generated_token = False
    if not str(values["security.api_token"] or "").strip():
        values["security.api_token"] = config.new_token()
        generated_token = True
    values["ai.api_key"] = config.encrypt_secret(str(values.get("ai.api_key") or ""))
    paths.ensure_runtime_dirs()
    path = config.write(values, lang=lang)
    settings = config.load(path)
    store.upgrade(settings.database_url)
    copied = ensure_runtime_knowledge(settings)
    admin_user = None
    if admin and users.count(settings.database_url) == 0:
        admin_user = users.create_user(settings.database_url, str(admin["username"]), str(admin["password"]), "admin")
    changed = [
        f.key for f in FIELDS if values[f.key] != f.default and f.key not in ("security.api_token", "ai.api_key")
    ]
    return {
        "config_path": str(path),
        "api_token": values["security.api_token"],
        "token_generated": generated_token,
        "changed": changed,
        "knowledge_copied": copied,
        "admin": admin_user,
        "url": f"http://{_display_host(settings.get('server.host'))}:{settings.get('server.port')}",
    }


def _display_host(host: str) -> str:
    return "127.0.0.1" if host in ("0.0.0.0", "::") else host


class SetupError(ValueError):
    def __init__(self, errors: dict[str, str]):
        super().__init__("setup")
        self.errors = errors
