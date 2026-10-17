"""数据表。SQLite 与 PostgreSQL 共用同一套定义；JSON 列在 PostgreSQL 上使用 JSONB。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Device(Base):
    """设备：名称、厂商、平台、软件版本、使用的 Profile。"""

    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    vendor: Mapped[str] = mapped_column(String(40))
    platform: Mapped[str] = mapped_column(String(80), default="")
    sw_version: Mapped[str] = mapped_column(String(80), default="")
    profile: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    versions: Mapped[list[ConfigVersion]] = relationship(back_populates="device", cascade="all, delete-orphan")


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
