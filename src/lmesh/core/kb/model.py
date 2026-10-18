"""知识库的数据结构：命令卡、视图、Schema 节点、依赖规则、Profile。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lmesh.core.kb import syntax as syn

STATUSES = ("draft", "reviewed", "verified", "rejected")
NODE_TYPES = (
    "object",
    "integer",
    "string",
    "text",
    "ipv4",
    "mask",
    "prefix",
    "boolean",
    "flag",
    "enum",
    "ref",
    "asn",
    "rd",
    "community",
    "interface",
)
DEP_KINDS = ("reference", "prerequisite", "side_effect", "mutex", "cross_device")
SHOW_RULES = ("always", "hide_when_default", "never")


@dataclass
class Card:
    """厂商相关的命令卡：一条命令的语法、所在视图、参数、缺省值，以及参数到 Schema 节点的映射。"""

    id: str
    family: str  # 平台族，例如 huawei-vrp8、cisco-iosxe
    domain: str
    syntax: str
    view: str
    file: str = ""
    undo: str | None = None
    enters_view: str | None = None
    params: dict[str, dict[str, Any]] = field(default_factory=dict)
    default: str | None = None
    maps: dict[str, Any] = field(
        default_factory=dict
    )  # Schema 节点（目标）→ 取值表达式；写法见 lmesh/core/kb/mapping.py
    depends_on: list[str] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)
    source: dict[str, Any] = field(default_factory=dict)
    status: str = "draft"
    note: str = ""
    _parsed: syn.Syntax | None = field(default=None, repr=False, compare=False)

    @property
    def parsed(self) -> syn.Syntax:
        if self._parsed is None:
            self._parsed = syn.parse(self.syntax)
        return self._parsed


@dataclass
class View:
    """配置视图：华为的 BGP 视图、Cisco 的 config-router 模式等。enter 是进入该视图的命令卡。"""

    id: str
    parent: str | None
    enter: list[str] = field(default_factory=list)
    exit: list[str] = field(default_factory=list)  # 显式退出的命令，例如 exit-address-family、quit
    title: str = ""


@dataclass
class Family:
    """平台族的书写习惯：块分隔符、结尾标记、缩进单位。"""

    id: str
    vendor: str
    separator: str  # 华为 "#"，Cisco "!"
    end: str  # 华为 "return"，Cisco "end"
    indent: int = 1
    negative: str = "undo"  # 取消命令的前缀：华为 undo，Cisco no
    views: dict[str, View] = field(default_factory=dict)
    root_view: str = "system"


@dataclass
class SchemaNode:
    id: str
    domain: str
    parent: str | None
    type: str
    semantic: dict[str, str] = field(default_factory=dict)
    key: list[str] = field(default_factory=list)
    range: list[int] | None = None
    choices: list[str] | None = None
    ordered: bool = False
    ref: str | None = None  # type=ref 时指向的对象类型
    deprecated: bool = False
    replaced_by: str | None = None
    status: str = "draft"


@dataclass
class DepRule:
    kind: str
    src: str  # Schema 节点
    dst: str
    note: str = ""
    profiles: list[str] = field(default_factory=list)  # 只在这些 Profile 中生效；空表示全部
    domain: str = ""


@dataclass
class ProfileEntry:
    node: str
    supported: bool = True
    default: Any = None
    show_rule: str = "hide_when_default"
    cards: list[str] = field(default_factory=list)
    source: str = ""
    verified: str = "doc"  # doc / device / roundtrip
    manual: bool = False  # 人工补充的条目，重新汇总时保留
    origin: str = ""  # 继承展开后：条目来自哪个 Profile


@dataclass
class Profile:
    id: str
    vendor: str
    family: str
    file: str = ""
    platform: str = ""
    software: str = ""
    inherits: str | None = None
    match: dict[str, str] = field(default_factory=dict)  # vendor / version（正则）
    title: str = ""
    entries: dict[str, ProfileEntry] = field(default_factory=dict)
    side_effects: list[DepRule] = field(default_factory=list)
    implicit: list[str] = field(default_factory=list)  # 被引用时隐式创建的对象类型（派生节点），例如 ASR 920 的桥域


@dataclass
class Issue:
    level: str  # error / warning
    code: str
    message: str
    file: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"level": self.level, "code": self.code, "message": self.message, "file": self.file}
