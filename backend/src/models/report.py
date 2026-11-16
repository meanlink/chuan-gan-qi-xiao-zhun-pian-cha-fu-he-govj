from sqlalchemy import String, Double, ForeignKey, Boolean, Integer, JSON, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.config.database import Base

class Report(Base):
    __tablename__ = 'reports'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'))
    destination: Mapped[str] = mapped_column(String(120))
    # 排期类型：weekly=时区化每周当地时刻（新）；interval=固定秒数（旧计划照常运行）
    schedule_kind: Mapped[str] = mapped_column(String(10), default='weekly')
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 仅 interval 旧计划使用，保持可空
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_run: Mapped[float | None] = mapped_column(Double, nullable=True)
    # 当前生效版本指针
    current_version_id: Mapped[int | None] = mapped_column(ForeignKey('schedule_versions.id'), nullable=True)
    current_version: Mapped['ScheduleVersion | None'] = relationship(
        foreign_keys=[current_version_id], lazy='joined')

class ScheduleVersion(Base):
    """不可变排期版本。改期即新增版本，生效点划清新旧场次界线。"""
    __tablename__ = 'schedule_versions'
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey('reports.id'))
    version: Mapped[int] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(64))
    # ISO 星期几，1=周一 ... 7=周日
    weekdays: Mapped[list] = mapped_column(JSON, default=list)
    hour: Mapped[int] = mapped_column(Integer)
    minute: Mapped[int] = mapped_column(Integer)
    # 生效点（UTC 秒）：仅该点之后的场次按本版本生成，之前场次（含欠发）沿用旧版本
    effective_at: Mapped[float] = mapped_column(Double)
    created_at: Mapped[float] = mapped_column(Double)
    created_by: Mapped[str] = mapped_column(String(150), default='system')
    __table_args__ = (UniqueConstraint('report_id', 'version', name='uq_schedule_version_no'),)

class Occurrence(Base):
    """一场具体简报：原定 UTC 时刻 + 当地挂钟时间 + 所属排期版本。"""
    __tablename__ = 'occurrences'
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey('reports.id'))
    version_id: Mapped[int] = mapped_column(ForeignKey('schedule_versions.id'))
    # 原定绝对时刻（UTC 秒）；夏令时跳过场使用 fold=0 映射的合成时刻，仅作唯一键
    scheduled_at: Mapped[float] = mapped_column(Double)
    local_date: Mapped[str] = mapped_column(String(10))
    local_time: Mapped[str] = mapped_column(String(5))
    timezone: Mapped[str] = mapped_column(String(64))
    # pending 待发（含欠发）/ claimed 已被执行者领取 / delivered 已归档 / skipped 不存在时刻
    status: Mapped[str] = mapped_column(String(12), default='pending', index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    claimed_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    delivered_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    delivery_id: Mapped[int | None] = mapped_column(ForeignKey('deliveries.id'), nullable=True)
    note: Mapped[str] = mapped_column(String(200), default='')
    __table_args__ = (
        UniqueConstraint('report_id', 'scheduled_at', name='uq_occurrence_report_time'),
        Index('ix_occurrence_due', 'status', 'scheduled_at'),
    )

class Delivery(Base):
    __tablename__ = 'deliveries'
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey('reports.id'))
    # 旧秒数计划的归档为空；每周场次归档锁定唯一场次，重试不新增
    occurrence_id: Mapped[int | None] = mapped_column(ForeignKey('occurrences.id'), nullable=True)
    # 实际归档时间（UTC 秒）
    created_at: Mapped[float] = mapped_column(Double)
    # 原定当地时间标签，如 2026-11-18 09:00 America/New_York
    scheduled_local: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # 原定 UTC 时刻与排期版本号
    scheduled_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    schedule_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(160))
    destination: Mapped[str] = mapped_column(String(120))
    __table_args__ = (UniqueConstraint('occurrence_id', name='uq_delivery_occurrence'),)
