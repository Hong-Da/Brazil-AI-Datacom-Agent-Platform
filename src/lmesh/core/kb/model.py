"""知识库的数据结构：命令卡、视图、Schema 节点、依赖规则、Profile。"""

from __future__ import annotations

from collections.abc import Mapping
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
NOTE_LANGS = ("zh-CN", "en", "pt-BR")


class Note(dict[str, str]):
    """依赖 / 副作用的三语说明 {zh-CN, en, pt-BR}。

    知识库里可写成纯字符串（视为 zh-CN）或三语字典；统一成三个键齐全的字典，缺的语言回退
    （en 缺用 zh-CN，pt-BR 缺用 en），given 记录文件里实际写了哪些语言（校验与写回用）。
    JSON 输出为字典；可哈希；str() 得到中文，旧的按字符串使用的代码照常可用。
    """

    given: tuple[str, ...]

    def __init__(self, m: Mapping[str, str] | None = None, given: tuple[str, ...] | None = None) -> None:
        super().__init__(m or {})
        self.given = tuple(self) if given is None else given

    @classmethod
    def of(cls, raw: Any) -> Note:
        if isinstance(raw, Note):
            return raw
        if isinstance(raw, Mapping):
            src = {str(k): str(v) for k, v in raw.items() if v not in (None, "")}
        else:
            src = {} if raw in (None, "") else {"zh-CN": str(raw)}
        if not src:
            return cls()
        zh = src.get("zh-CN") or src.get("en") or next(iter(src.values()))
        en = src.get("en") or zh
        return cls(
            {"zh-CN": zh, "en": en, "pt-BR": src.get("pt-BR") or en},
            tuple(k for k in NOTE_LANGS if k in src),
        )

    def missing(self) -> list[str]:
        """非空说明中文件里没写的语言。"""
        return [k for k in NOTE_LANGS if k not in self.given] if self else []

    def text(self, lang: str | None) -> str:
        return self.get(lang or "zh-CN") or self.get("en") or self.get("zh-CN") or ""

    def raw(self) -> str | dict[str, str]:
        """写回知识库的形式：只有中文时为字符串，否则只写文件里给出的语言。"""
        if self.given in ((), ("zh-CN",)):
            return self.get("zh-CN", "")
        return {k: self[k] for k in self.given}

    def __str__(self) -> str:
        return self.get("zh-CN", "")

    def __format__(self, spec: str) -> str:
        return format(str(self), spec)

    def __hash__(self) -> int:  # type: ignore[override]
        return hash(tuple(sorted(self.items())))


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
    # 取值（对象节点为键）是密码、密钥、团体字等敏感内容：跨平台族翻译时不写（源平台的密文不能在另一平台使用）
    secret: bool = False
    # 属性取值也是所属对象的另一个键（华为 acl name X number N 的 N）：按它引用时也能找到这个对象
    alias: bool = False


@dataclass
class DepRule:
    kind: str
    src: str  # Schema 节点
    dst: str
    note: Note = field(default_factory=Note)
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
    # 缺省值的适用条件（可省）：{key: 正则}——所属对象的编号匹配时才补默认节点（例如只对物理口）；
    # {attr: {兄弟属性: 取值}}——同一对象上该属性的有效值相等时才补（例如按网络类型取不同的 hello 间隔）
    when: dict[str, Any] = field(default_factory=dict)
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
