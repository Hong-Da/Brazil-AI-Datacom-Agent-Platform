"""数据表。SQLite 与 PostgreSQL 共用同一套定义；JSON 列在 PostgreSQL 上使用 JSONB。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None) -> str | None:
    """时间统一按 UTC 输出带时区的 ISO 文本（SQLite 读回来不带时区，按 UTC 补上）。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


class Base(DeclarativeBase):
    pass


class Device(Base):
    """设备：名称、厂商、平台、软件版本、使用的 Profile。

    归属（M6，REQ-035）：project_id 是所属项目（项目私有设备）；为空表示公共设备库（管理员维护，项目只能引用或复制）。
    名称在同一项目内唯一（公共设备库内的唯一由代码保证）；origin：import 导入 / copy 复制 / migrated 升级时移入。"""

    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    vendor: Mapped[str] = mapped_column(String(40))
    platform: Mapped[str] = mapped_column(String(80), default="")
    sw_version: Mapped[str] = mapped_column(String(80), default="")
    profile: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    origin: Mapped[str] = mapped_column(String(20), default="import")
    origin_note: Mapped[Any] = mapped_column(JSONType, nullable=True)  # 复制来源：项目、设备、版本序号
    # Profile 来源（REQ-044）：auto 版本规则命中 / fallback 厂商默认 / rule 型号规则 / manual 手工选择 / none 不解析
    # （认不出厂商只存原文，或没有可用的 Profile）。fallback、rule、manual 属于“近似”，界面与下发前提示核对。
    profile_source: Mapped[str] = mapped_column(String(10), default="auto")
    profile_rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_rules.id", ondelete="SET NULL"), nullable=True
    )
    versions: Mapped[list[ConfigVersion]] = relationship(back_populates="device", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_devices_project_name"),)


class ConfigVersion(Base):
    """一次导入的配置：脱敏后的原文、结构化 JSON、采集时间、建图所用的知识库版本。"""

    __tablename__ = "config_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    source_name: Mapped[str] = mapped_column(String(400), default="")
    raw_text: Mapped[str] = mapped_column(Text)
    structured: Mapped[Any] = mapped_column(JSONType, nullable=True)
    sanitized: Mapped[bool] = mapped_column(default=True)
    kb_version: Mapped[str] = mapped_column(String(40), default="")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # 版本历史（M5-2）：一个配置版本就是一个快照——原文 + 当时的图（gzip 压缩的 JSON）+ 解析用的知识库版本
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    graph_gz: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    tag: Mapped[str | None] = mapped_column(String(200), nullable=True)  # 贴了标签的快照永久保留
    change_summary: Mapped[Any] = mapped_column(JSONType, nullable=True)  # 相对上一个快照的变化计数
    device: Mapped[Device] = relationship(back_populates="versions")


class Node(Base):
    """图节点：Schema 类型、键、值、来源标记（explicit/default/inherited/derived/raw）、原始行号。"""

    __tablename__ = "nodes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("config_versions.id", ondelete="CASCADE"))
    node_key: Mapped[str] = mapped_column(String(600))  # 图内唯一键，例如 bgp/peer[10.0.0.1]/timers.keepalive
    schema_type: Mapped[str] = mapped_column(String(200))
    value: Mapped[Any] = mapped_column(JSONType, nullable=True)
    origin: Mapped[str] = mapped_column(String(20), default="explicit")
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_key: Mapped[str | None] = mapped_column(String(600), nullable=True)
    __table_args__ = (
        Index("ix_nodes_version_key", "version_id", "node_key"),
        Index("ix_nodes_version_type", "version_id", "schema_type"),
    )


class Edge(Base):
    """图的边：contains 包含，以及 reference / prerequisite / side_effect / mutex / cross_device 五类依赖。"""

    __tablename__ = "edges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("config_versions.id", ondelete="CASCADE"))
    src_key: Mapped[str] = mapped_column(String(600))
    dst_key: Mapped[str] = mapped_column(String(600))
    kind: Mapped[str] = mapped_column(String(20))
    attrs: Mapped[Any] = mapped_column(JSONType, nullable=True)
    __table_args__ = (
        Index("ix_edges_version_src", "version_id", "src_key"),
        Index("ix_edges_version_dst", "version_id", "dst_key"),
    )


class ReviewItem(Base):
    """审核队列：命令卡、新节点建议、未识别行映射建议、导入冲突。"""

    __tablename__ = "review_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)  # card / schema_node / mapping / conflict / profile_entry
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending / approved / rejected
    title: Mapped[str] = mapped_column(String(400), default="")
    target: Mapped[str] = mapped_column(String(400), default="")  # 对应的知识库文件或节点
    payload: Mapped[Any] = mapped_column(JSONType)
    source: Mapped[Any] = mapped_column(JSONType, nullable=True)  # 来源文档、页码、抽取方式（rule / ai）
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UnknownLine(Base):
    """解析时不认识的配置行。"""

    __tablename__ = "unknown_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("config_versions.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    view: Mapped[str] = mapped_column(String(200), default="")
    pattern: Mapped[str] = mapped_column(String(400), default="")  # 归一化后的形态，用于按频率汇总


class Task(Base):
    """耗时任务：文档抽取、批量往返测试等。"""

    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued / running / done / failed
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[Any] = mapped_column(JSONType, nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), default="")  # 发起人（REQ-040：AI 按发起人的选择）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AICall(Base):
    """AI 调用记录：任务、模型、token 用量，与审核结论关联以评估准确率。"""

    __tablename__ = "ai_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    error: Mapped[str] = mapped_column(Text, default="")
    review_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("review_items.id", ondelete="SET NULL"), nullable=True
    )
    # REQ-040：谁发起（账号；全局令牌与命令行为空）、用的哪个接口（名称留存，接口删除后仍可读）
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(200), default="")
    connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_connections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    connection_name: Mapped[str] = mapped_column(String(64), default="")
    source: Mapped[str] = mapped_column(String(16), default="")  # connection / personal
    feature: Mapped[str] = mapped_column(String(60), default="")  # 功能：skill 编号；不经 skill 时为空（统计时用 task）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIConnection(Base):
    """AI 接口（REQ-040）：owner_id 为空是管理员接口（可多个，public 决定普通账号能否选用）；
    不为空是该账号的个人接口（每人最多一个，只有本人可见）。API Key 用 config.encrypt_secret 加密保存。"""

    __tablename__ = "ai_connections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(20))  # anthropic / openai / local
    base_url: Mapped[str] = mapped_column(String(500), default="")
    api_key: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    model_extract: Mapped[str] = mapped_column(String(120), default="")
    model_merge: Mapped[str] = mapped_column(String(120), default="")
    model_ask: Mapped[str] = mapped_column(String(120), default="")
    model_generate: Mapped[str] = mapped_column(String(120), default="")
    public: Mapped[bool] = mapped_column(default=False)
    enabled: Mapped[bool] = mapped_column(default=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (
        UniqueConstraint("owner_id", name="uq_ai_connections_owner"),
        Index(
            "uq_ai_connections_admin_name",
            "name",
            unique=True,
            sqlite_where=sql_text("owner_id IS NULL"),
            postgresql_where=sql_text("owner_id IS NULL"),
        ),
    )


class AIChoice(Base):
    """账号的 AI 来源选择（REQ-040）：auto（默认）/ connection（某个管理员接口）/ personal / none。"""

    __tablename__ = "ai_choices"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    choice: Mapped[str] = mapped_column(String(16), default="auto")
    connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_connections.id", ondelete="SET NULL"), nullable=True
    )
    # 个人偏好：不提示大请求（M8-2；优先于全局 ai.warn_tokens）
    no_token_warn: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AppMeta(Base):
    """少量系统标记（键值）：例如 ai.seeded（[ai] 配置已导入为第一个管理员接口）。"""

    __tablename__ = "app_meta"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class CheckIgnore(Base):
    """忽略的检查发现：按 (设备, 规则, 节点规范编号) 唯一，必须写明原因；设备删除时一并删除。"""

    __tablename__ = "check_ignores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    # 按项目（M6）：同一台公共设备在不同项目里的忽略互不影响
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # 所属网络（M9，REQ-045）：工作数据按网络独立；为空只出现在没有当前项目时直接调用 core 写入的数据
    network_id: Mapped[int | None] = mapped_column(
        ForeignKey("networks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    rule: Mapped[str] = mapped_column(String(120))
    node: Mapped[str] = mapped_column(String(600))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("network_id", "device_id", "rule", "node", name="uq_check_ignores_network_device_rule_node"),
    )


class ConfigImport(Base):
    """导入记录（M5-2）：每次导入一条；内容与最新快照相同的重复导入只记这里，不存新快照。"""

    __tablename__ = "config_imports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("config_versions.id", ondelete="CASCADE"), index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source_kind: Mapped[str] = mapped_column(String(20), default="file")  # file / dir / zip / api / migrate
    source_name: Mapped[str] = mapped_column(String(400), default="")
    actor: Mapped[str] = mapped_column(String(200), default="")  # 导入人或令牌说明（不记录令牌本身）
    duplicate: Mapped[bool] = mapped_column(default=False)


class User(Base):
    """网页登录账号（REQ-030）：只保存密码的 scrypt 哈希；角色 admin / user；连续登录失败时暂时锁定。"""

    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(20), default="user")  # admin / maintainer（知识库维护员）/ user
    disabled: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active / pending 待审核（REQ-039 自助注册）
    origin: Mapped[str] = mapped_column(String(16), default="admin")  # admin 管理员建 / register 自助注册
    password_hash: Mapped[str] = mapped_column(String(255))
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # 个人偏好（REQ-047）：{"lang", "theme", "term_style", "icon_set"}；为空表示还没保存过
    prefs: Mapped[Any] = mapped_column(JSONType, nullable=True)
    # 单独授权创建项目（M9-8，REQ-050）：总开关“普通用户可以创建项目”关闭时，管理员可以给个别账号打开
    can_create_projects: Mapped[bool] = mapped_column(default=False)


class UserSession(Base):
    """网页会话：Cookie 里是随机令牌，这里只存它的 SHA-256；登出、停用、重置密码时删除。"""

    __tablename__ = "user_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CheckProject(Base):
    """配置检查项目（REQ-031）：一台设备（或它的某个配置版本）作为基线 + 多份脚本；属于创建它的账号（API 令牌创建的为空）。"""

    __tablename__ = "check_projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    version_id: Mapped[int | None] = mapped_column(  # 为空表示跟随设备最新版本
        ForeignKey("config_versions.id", ondelete="SET NULL"), nullable=True
    )
    profile: Mapped[str] = mapped_column(String(120), default="")  # 没有基线设备时完整配置用的 Profile（可空）
    default_kind: Mapped[str] = mapped_column(String(20), default="change")  # change / full
    order_check: Mapped[bool] = mapped_column(default=True)
    ai_check: Mapped[bool] = mapped_column(default=False)
    ai_rules: Mapped[Any] = mapped_column(JSONType, nullable=True)  # 勾选交给 AI 的规则编号
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # 所属项目（M6）：配置检查项目并入项目后，一个检查项目就是项目里的一组脚本（共用基线与检查设置）
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # 所属网络（M9，REQ-045）：工作数据按网络独立；为空只出现在没有当前项目时直接调用 core 写入的数据
    network_id: Mapped[int | None] = mapped_column(
        ForeignKey("networks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CheckScript(Base):
    """项目中的一份脚本（变更脚本或完整配置）；content 是当前内容，last_check 是最近一次检查的摘要。"""

    __tablename__ = "check_scripts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("check_projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="change")
    content: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    last_check: Mapped[Any] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CheckRevision(Base):
    """脚本的修订记录：创建、手动保存、按依赖重排（重排前后各一条）、恢复都形成一条；seq 是脚本内的序号。"""

    __tablename__ = "check_revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    script_id: Mapped[int] = mapped_column(ForeignKey("check_scripts.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # create / manual / reorder / restore
    note: Mapped[Any] = mapped_column(JSONType, nullable=True)  # 重排的移动与原因、恢复自哪个修订
    summary: Mapped[Any] = mapped_column(JSONType, nullable=True)  # 保存时的检查摘要（错误 / 警告数）
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("script_id", "seq", name="uq_check_revisions_script_seq"),)


class SkillRun(Base):
    """AI skill 的一次调用（REQ-033）：输入与回复都是脱敏后的；status 是代码校验的结论；评价与更正来自用户反馈。
    按 ai.skill_log_days 天清理；试运行（test）与回归运行（regression）不计入统计。"""

    __tablename__ = "skill_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[str] = mapped_column(String(20), default="builtin")  # builtin / 版本号 / candidate
    task: Mapped[str] = mapped_column(String(40), default="")
    # ask / generate / ingest / script_check / test / regression / evolve
    source: Mapped[str] = mapped_column(String(20), default="")
    # passed / corrected / rejected / unverifiable / error
    status: Mapped[str] = mapped_column(String(20), default="passed")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor: Mapped[str] = mapped_column(String(200), default="")
    input: Mapped[Any] = mapped_column(JSONType, nullable=True)
    reply: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[Any] = mapped_column(JSONType, nullable=True)
    model: Mapped[str] = mapped_column(String(120), default="")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    ms: Mapped[int] = mapped_column(Integer, default=0)
    rating: Mapped[str | None] = mapped_column(String(10), nullable=True)  # up / down
    correction: Mapped[str] = mapped_column(Text, default="")
    feedback_by: Mapped[str] = mapped_column(String(200), default="")
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SkillCase(Base):
    """skill 的案例：regression 回归集（失败案例自动入集）/ candidate 候选示例（校验通过且用户认可）。"""

    __tablename__ = "skill_cases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill: Mapped[str] = mapped_column(String(60), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # regression / candidate
    # rejected / corrected / down / correction / up / manual
    reason: Mapped[str] = mapped_column(String(20), default="manual")
    run_id: Mapped[int | None] = mapped_column(ForeignKey("skill_runs.id", ondelete="SET NULL"), nullable=True)
    input: Mapped[Any] = mapped_column(JSONType, nullable=True)
    reply: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[Any] = mapped_column(JSONType, nullable=True)
    expect: Mapped[str] = mapped_column(Text, default="")  # 用户写的更正
    input_hash: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("skill", "kind", "input_hash", name="uq_skill_cases_skill_kind_hash"),)


class SkillEvolution(Base):
    """一次进化：AI 提出的候选版本、回归集上新旧版本的得分；管理员批准后才发布为新版本。"""

    __tablename__ = "skill_evolutions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill: Mapped[str] = mapped_column(String(60), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending / approved / rejected / failed
    base_version: Mapped[str] = mapped_column(String(20), default="builtin")
    candidate: Mapped[Any] = mapped_column(JSONType, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, default="")
    scores: Mapped[Any] = mapped_column(JSONType, nullable=True)
    error: Mapped[Any] = mapped_column(JSONType, nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_by: Mapped[str] = mapped_column(String(200), default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_version: Mapped[str] = mapped_column(String(20), default="")


# ---------------------------------------------------------------- 用户工作空间与项目（M6，REQ-035 / REQ-036）


class Project(Base):
    """项目：设备（私有设备与对公共设备的引用）、脚本、检查忽略项、规则调整、项目设置。标识（slug）在同一属主内唯一
    （用户 2026-10-19 评审改选；跨属主写成“属主/标识”）。

    owner_id 为空只出现在没有任何账号的旧安装（升级时的默认项目），第一个管理员创建后由他接管；属主为空的项目之间
    标识也不能重复（部分唯一索引）。"""

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("owner_id", "slug", name="uq_projects_owner_slug"),
        Index(
            "uq_projects_ownerless_slug",
            "slug",
            unique=True,
            sqlite_where=sql_text("owner_id IS NULL"),
            postgresql_where=sql_text("owner_id IS NULL"),
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    settings: Mapped[Any] = mapped_column(JSONType, nullable=True)  # 显示风格、规则集、安全基线
    migrated_from: Mapped[Any] = mapped_column(JSONType, nullable=True)  # 升级生成：{type: upgrade|check_project, …}
    last_activity: Mapped[Any] = mapped_column(JSONType, nullable=True)  # {actor, action, at}
    # 可被搜索（M9-8，REQ-050）：所有登录用户能在“发现项目”里看到名称、简介、属主、设备数并申请加入
    discoverable: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectMember(Base):
    """项目成员：role 为 manage（管理：可编辑 + 审批、增减成员、邀请链接，M9-8）、edit（可编辑）或 read（只读）；
    属主不在这里。"""

    __tablename__ = "project_members"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10), default="read")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),)


class ProjectJoinRequest(Base):
    """加入项目的申请（M9-8，REQ-050）：来自“发现项目”（via=search）或需要审批的邀请链接（via=invite）。
    status：pending 待审批 / approved 已通过 / declined 已拒绝 / cancelled 申请人撤回。"""

    __tablename__ = "project_join_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10), default="read")  # 申请的角色
    reason: Mapped[str] = mapped_column(Text, default="")
    via: Mapped[str] = mapped_column(String(10), default="search")
    invite_id: Mapped[int | None] = mapped_column(ForeignKey("project_invites.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    decided_by: Mapped[str] = mapped_column(String(200), default="")
    decided_role: Mapped[str] = mapped_column(String(10), default="")  # 通过时实际给的角色
    note: Mapped[str] = mapped_column(Text, default="")  # 拒绝的说明
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectInvite(Base):
    """项目邀请链接（M9-8，REQ-050）：链接里的令牌只在生成时返回一次，这里只存它的 SHA-256 与前 6 个字符（列表里辨认用）。"""

    __tablename__ = "project_invites"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(12), default="")
    role: Mapped[str] = mapped_column(String(10), default="read")
    requires_approval: Mapped[bool] = mapped_column(default=False)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[str] = mapped_column(String(200), default="")
    uses: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectCreateRequest(Base):
    """申请创建项目的权限（M9-8，REQ-050）：没有项目也不能创建的账号一键申请，管理员在账号管理里授权或拒绝。"""

    __tablename__ = "project_create_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    decided_by: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Workspace(Base):
    """用户工作空间：每个账号一个；记录默认项目（命令行不带 --project、旧的无项目接口都落到这里）。"""

    __tablename__ = "workspaces"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    default_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectDeviceRef(Base):
    """项目对公共设备的引用：version_id 为空表示跟随公共库最新版本，否则固定在该版本。"""

    __tablename__ = "project_device_refs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[int | None] = mapped_column(ForeignKey("config_versions.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("project_id", "device_id", name="uq_project_device_refs_project_device"),)


class ProjectRuleOverride(Base):
    """规则调整：关闭（enabled=false）或改级别，只影响该项目的这个网络（M9 起按网络）；reason 必填。"""

    __tablename__ = "project_rule_overrides"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    # 所属网络（M9，REQ-045）：工作数据按网络独立；为空只出现在没有当前项目时直接调用 core 写入的数据
    network_id: Mapped[int | None] = mapped_column(
        ForeignKey("networks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    rule: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(default=True)
    severity: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("network_id", "rule", name="uq_project_rule_overrides_network_rule"),)


class ApiToken(Base):
    """个人 API 令牌：只存 SHA-256；prefix 是令牌的前 8 个字符（lmp_ 开头），用于列表与日志。"""

    __tablename__ = "api_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    prefix: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    read_only: Mapped[bool] = mapped_column(default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 为空表示不过期
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_ip: Mapped[str] = mapped_column(String(64), default="")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    """审计记录：管理员访问他人项目、项目转交与删除等（同时写 lmesh.audit 日志）；不含请求内容。"""

    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(200), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_slug: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(40))  # enter / write / transfer / delete / …
    detail: Mapped[Any] = mapped_column(JSONType, nullable=True)


class UserAsset(Base):
    """工作空间里的私有内容归属：kind 为 template（我的模板）或 ruleset（我的翻译规则集），asset_id 是其编号。"""

    __tablename__ = "user_assets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    asset_id: Mapped[str] = mapped_column(String(120))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("kind", "asset_id", name="uq_user_assets_kind_asset"),)


# ---------------------------------------------------------------- AI 建议（M8-2，REQ-041）


class AISuggestionBatch(Base):
    """一次 AI 建议运行：项目、设备 / 范围、skill 与版本、AI 接口与调用记录、发起人、状态与计数。
    context 保存代码给出的事实（对象编号表、数字、行数，已脱敏），编辑后重新校验时用同一份事实。"""

    __tablename__ = "ai_suggestion_batches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # 所属网络（M9，REQ-045）：工作数据按网络独立；为空只出现在没有当前项目时直接调用 core 写入的数据
    network_id: Mapped[int | None] = mapped_column(
        ForeignKey("networks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    scope_key: Mapped[str] = mapped_column(String(200), default="")  # device:<编号> / topology / project …
    skill: Mapped[str] = mapped_column(String(60), index=True)
    skill_version: Mapped[str] = mapped_column(String(20), default="builtin")
    mode: Mapped[str] = mapped_column(String(10), default="ai")  # ai / replay
    # queued / running / done / failed / cancelled
    status: Mapped[str] = mapped_column(String(20), default="queued")
    task_id: Mapped[str] = mapped_column(String(40), default="")
    skill_run_id: Mapped[int | None] = mapped_column(ForeignKey("skill_runs.id", ondelete="SET NULL"), nullable=True)
    ai_call_ids: Mapped[Any] = mapped_column(JSONType, nullable=True)  # ai_calls 的编号（含重试）
    connection_name: Mapped[str] = mapped_column(String(64), default="")
    ai_source: Mapped[str] = mapped_column(String(16), default="")  # connection / personal
    model: Mapped[str] = mapped_column(String(120), default="")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), default="")
    params: Mapped[Any] = mapped_column(JSONType, nullable=True)
    context: Mapped[Any] = mapped_column(JSONType, nullable=True)
    counts: Mapped[Any] = mapped_column(JSONType, nullable=True)  # total / pass / warn / reject
    error: Mapped[Any] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AISuggestion(Base):
    """一条 AI 建议：类别（决定校验器、采纳与撤销方式）、内容、依据与引用、代码校验结果、状态与采纳 / 撤销信息。
    status：pending 待处理 / adopted 已采纳 / dismissed 已忽略 / reverted 已撤销；check_status：pass / warn / reject。"""

    __tablename__ = "ai_suggestions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("ai_suggestion_batches.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # 所属网络（M9，REQ-045）：工作数据按网络独立；为空只出现在没有当前项目时直接调用 core 写入的数据
    network_id: Mapped[int | None] = mapped_column(
        ForeignKey("networks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    scope_key: Mapped[str] = mapped_column(String(200), default="")
    skill: Mapped[str] = mapped_column(String(60), index=True)
    category: Mapped[str] = mapped_column(String(30))
    kind: Mapped[str] = mapped_column(String(40), default="")
    title: Mapped[str] = mapped_column(String(400), default="")
    content: Mapped[Any] = mapped_column(JSONType, nullable=True)
    original: Mapped[Any] = mapped_column(JSONType, nullable=True)  # 编辑后采纳时保留 AI 的原内容
    refs: Mapped[Any] = mapped_column(JSONType, nullable=True)
    check: Mapped[Any] = mapped_column(JSONType, nullable=True)  # {status, reasons: [{code, ref?, detail?}]}
    check_status: Mapped[str] = mapped_column(String(10), default="reject", index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    ai_call_id: Mapped[int | None] = mapped_column(ForeignKey("ai_calls.id", ondelete="SET NULL"), nullable=True)
    connection_name: Mapped[str] = mapped_column(String(64), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), default="")
    decided_by: Mapped[str] = mapped_column(String(200), default="")  # 采纳 / 忽略的人
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    adopt_info: Mapped[Any] = mapped_column(JSONType, nullable=True)  # 采纳时做了什么、原来的值（撤销用）
    note: Mapped[str] = mapped_column(Text, default="")
    reverted_by: Mapped[str] = mapped_column(String(200), default="")
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revert_info: Mapped[Any] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ViewAnnotation(Base):
    """项目级视图标注（只影响显示）：设备角色、分组、标签……source 为 user（手工）或 ai（采纳的 AI 建议）。
    角色的取值顺序：手工标注优先，其次采纳的 AI 建议，最后按平台默认（REQ-042）。"""

    __tablename__ = "view_annotations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    # 所属网络（M9，REQ-045）：工作数据按网络独立；为空只出现在没有当前项目时直接调用 core 写入的数据
    network_id: Mapped[int | None] = mapped_column(
        ForeignKey("networks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    target_type: Mapped[str] = mapped_column(String(20))  # device / link / group
    target: Mapped[str] = mapped_column(String(200))  # 设备编号（文本）等
    key: Mapped[str] = mapped_column(String(40))  # role / group / label / layer
    value: Mapped[Any] = mapped_column(JSONType, nullable=True)
    source: Mapped[str] = mapped_column(String(10), default="user")
    suggestion_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_suggestions.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("network_id", "target_type", "target", "key", name="uq_view_annotations_network_target_key"),
    )


class ModelRule(Base):
    """型号规则（REQ-044）：条件全部满足时导入用指定的 Profile。project_id 为空是全局规则（知识库维护员与管理员管理）。

    条件：name_pattern 设备名（* ? 通配，不分大小写）、version 软件版本正则、feature 特征命令正则（按行匹配，配置里有这一行
    才算命中）、vendor 厂商（空表示任意）；至少要有一个条件。优先级：本项目规则 > 全局规则；同一范围内条件多的优先，
    一样多时编号小（先建）的优先。"""

    __tablename__ = "model_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    vendor: Mapped[str] = mapped_column(String(40), default="")
    name_pattern: Mapped[str] = mapped_column(String(200), default="")
    version: Mapped[str] = mapped_column(String(200), default="")
    feature: Mapped[str] = mapped_column(String(400), default="")
    profile: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(default=True)
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------- 项目内的网络（M9，REQ-045）


class NetworkFolder(Base):
    """网络列表的文件夹：只用来整理列表，不包含设备、不继承数据。"""

    __tablename__ = "network_folders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Network(Base):
    """项目内的网络：平铺的独立工作区（拓扑标注、检查忽略、规则调整、脚本、AI 建议……按网络独立）。
    标识（slug）在项目内唯一；color 是 8 色中的一个键（按创建顺序自动分配，可以改）；is_default 的默认网络每个项目一个，
    包含全部设备、自动加入新设备，可以改名、不能删除。copied_from：复制来源 {network_id, slug, name, at}；
    stats：按设备记下的最近一次检查结果（汇总页用）；last_activity：{actor, action, at}。"""

    __tablename__ = "networks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(16), default="slate")
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("network_folders.id", ondelete="SET NULL"), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_default: Mapped[bool] = mapped_column(default=False)
    copied_from: Mapped[Any] = mapped_column(JSONType, nullable=True)
    stats: Mapped[Any] = mapped_column(JSONType, nullable=True)
    last_activity: Mapped[Any] = mapped_column(JSONType, nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("project_id", "slug", name="uq_networks_project_slug"),)


class NetworkRule(Base):
    """自动加入规则：kind 为 name（设备名通配，* ?，不分大小写）或 subnet（管理地址所在网段，CIDR）；
    导入设备时命中就直接加入。默认网络的“全部新设备”是隐含的，不存这里。"""

    __tablename__ = "network_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    network_id: Mapped[int] = mapped_column(ForeignKey("networks.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    pattern: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(default=True)
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NetworkMember(Base):
    """网络成员：网络引用项目设备池里的设备。version_id 为空表示跟随最新（项目里的当前版本），否则固定在该版本；
    join_source：upgrade 升级时移入 / default 默认网络自动加入 / manual 手工 / rule 自动加入规则 / suggestion 建网建议采纳 /
    copy 复制网络 / import 在本网络导入。excluded：手工移出的设备记为排除（不算成员，自动加入规则不再加入）。"""

    __tablename__ = "network_members"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    network_id: Mapped[int] = mapped_column(ForeignKey("networks.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[int | None] = mapped_column(ForeignKey("config_versions.id", ondelete="SET NULL"), nullable=True)
    join_source: Mapped[str] = mapped_column(String(16), default="manual")
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("network_rules.id", ondelete="SET NULL"), nullable=True)
    excluded: Mapped[bool] = mapped_column(default=False)
    joined_by: Mapped[str] = mapped_column(String(200), default="")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("network_id", "device_id", name="uq_network_members_network_device"),)


class AskSession(Base):
    """AI 查询会话（REQ-052）：属于项目，只有本人可见；shared 时同项目成员可以只读查看。
    network_id / network_slug：创建或最近更改范围时的网络；devices：范围（设备名列表，None 为网络全部可查询设备）。
    全局 API 令牌与没有账号的命令行 user_id 为空（按 owner 名称区分）。"""

    __tablename__ = "ask_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    owner: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    network_id: Mapped[int | None] = mapped_column(ForeignKey("networks.id", ondelete="SET NULL"), nullable=True)
    network_slug: Mapped[str] = mapped_column(String(64), default="")
    devices: Mapped[Any] = mapped_column(JSONType, nullable=True)
    archived: Mapped[bool] = mapped_column(default=False)
    shared: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AskTurn(Base):
    """会话中的一轮（REQ-052）：versions 是这一轮的各个版本 [{question, result, at}]（改问重答时追加），
    current 是正在显示的版本下标；context 是提问时交给 AI 的前几轮轮数。"""

    __tablename__ = "ask_turns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("ask_sessions.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    versions: Mapped[Any] = mapped_column(JSONType, default=list)
    current: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AskAttachment(Base):
    """会话附件（REQ-053）：kind 为 config（临时设备，content 是脱敏后的配置原文）、doc（text 是提取并脱敏的文字）、
    image（data 是图片原样，发给 AI 前需要确认）。meta：{vendor, profile, device, chars, truncated, mime}。"""

    __tablename__ = "ask_attachments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("ask_sessions.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(10))
    size: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    meta: Mapped[Any] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
