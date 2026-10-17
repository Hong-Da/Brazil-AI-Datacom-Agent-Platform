"""首次运行向导的核心逻辑：Web 向导与命令行向导共用。"""

from __future__ import annotations

import shutil
import socket
from typing import Any

from lmesh import paths
from lmesh.core import config, store
from lmesh.core.config import FIELDS, GROUP_TITLES, ConfigError


def wizard_schema(lang: str) -> list[dict[str, Any]]:
    """按“界面 → 网络 → 数据 → 安全 → 日志 → AI”分组列出向导要问的参数。"""
    groups: dict[str, dict[str, Any]] = {}
    for f in FIELDS:
        if not f.wizard:
            continue
        g = groups.setdefault(f.group, {"id": f.group, "title": GROUP_TITLES[f.group].get(lang, f.group), "fields": []})
        g["fields"].append(
            {
                "key": f.key,
                "kind": f.kind,
                "default": f.default,
                "choices": list(f.choices),
                "min": f.minimum,
                "max": f.maximum,
                "secret": f.secret,
                "desc": f.desc.get(lang, f.desc["zh-CN"]),
            }
        )
    return list(groups.values())


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


def ensure_runtime_knowledge(settings: config.Settings) -> bool:
    """首次启动时把程序自带的知识库复制到运行时目录；已存在时不动。返回是否复制了。"""
    target = settings.knowledge_dir
    src = paths.builtin_knowledge_dir()
    if target.exists() or not src.exists():
        return False
    shutil.copytree(src, target)
    return True


def apply(
    answers: dict[str, Any], lang: str, check_port: bool = True, current_port: int | None = None
) -> dict[str, Any]:
    """校验并写入配置，初始化数据库与运行时知识库。返回汇总（令牌只在这里显示一次）。"""
    errors = validate_answers(answers, check_port=check_port, current_port=current_port)
    if errors:
        raise SetupError(errors)
    values = {f.key: answers.get(f.key, f.default) for f in FIELDS}
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
    changed = [
        f.key for f in FIELDS if values[f.key] != f.default and f.key not in ("security.api_token", "ai.api_key")
    ]
    return {
        "config_path": str(path),
        "api_token": values["security.api_token"],
        "token_generated": generated_token,
        "changed": changed,
        "knowledge_copied": copied,
        "url": f"http://{_display_host(settings.get('server.host'))}:{settings.get('server.port')}",
    }


def _display_host(host: str) -> str:
    return "127.0.0.1" if host in ("0.0.0.0", "::") else host


class SetupError(ValueError):
    def __init__(self, errors: dict[str, str]):
        super().__init__("setup")
        self.errors = errors
