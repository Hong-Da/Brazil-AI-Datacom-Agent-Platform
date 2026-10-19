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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CheckIgnore(Base):
    """忽略的检查发现：按 (设备, 规则, 节点规范编号) 唯一，必须写明原因；设备删除时一并删除。"""

    __tablename__ = "check_ignores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    # 按项目（M6）：同一台公共设备在不同项目里的忽略互不影响
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    rule: Mapped[str] = mapped_column(String(120))
    node: Mapped[str] = mapped_column(String(600))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("project_id", "device_id", "rule", "node", name="uq_check_ignores_project_device_rule_node"),
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectMember(Base):
    """项目成员：role 为 edit（可编辑）或 read（只读）；属主不在这里。"""

    __tablename__ = "project_members"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10), default="read")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),)


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
    """项目级规则调整：关闭（enabled=false）或改级别，只影响该项目；reason 必填。"""

    __tablename__ = "project_rule_overrides"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    rule: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(default=True)
    severity: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("project_id", "rule", name="uq_project_rule_overrides_project_rule"),)


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
