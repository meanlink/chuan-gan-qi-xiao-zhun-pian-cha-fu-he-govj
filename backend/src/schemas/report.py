from datetime import date as date_cls
from pydantic import BaseModel, Field, field_validator

class WeeklySchedule(BaseModel):
    timezone: str = Field(min_length=1, max_length=64)
    weekdays: list[int]
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    first_date: str | None = None  # ISO 当地日期，默认今天（时区口径）

    @field_validator('weekdays')
    @classmethod
    def _check_days(cls, v):
        days = sorted(set(v))
        if not days or any(d < 1 or d > 7 for d in days):
            raise ValueError('每周日期需在周一(1)至周日(7)中至少选择一天')
        return days

    @field_validator('first_date')
    @classmethod
    def _check_date(cls, v):
        if v is None:
            return v
        try:
            date_cls.fromisoformat(v)
        except ValueError as exc:
            raise ValueError('首次日期需为 ISO 格式，如 2026-12-01') from exc
        return v

class ReportInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    job_id: int
    destination: str = Field(default='业务复核组', min_length=2, max_length=120)
    # 旧秒数计划字段，保留并照常生效
    interval_seconds: int = Field(default=86400, ge=60, le=2592000)
    delay_seconds: int = Field(default=0, ge=0, le=2592000)
    # weekly 走时区化排期；interval 沿用固定秒数
    schedule_kind: str = Field(default='weekly', pattern='^(weekly|interval)$')
    weekly: WeeklySchedule | None = None

class RescheduleInput(BaseModel):
    timezone: str = Field(min_length=1, max_length=64)
    weekdays: list[int]
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    # 生效点：ISO 当地日期时间（按新时区解释）；默认当前时刻
    effective_at: str | None = None

    @field_validator('weekdays')
    @classmethod
    def _check_days(cls, v):
        days = sorted(set(v))
        if not days or any(d < 1 or d > 7 for d in days):
            raise ValueError('每周日期需在周一(1)至周日(7)中至少选择一天')
        return days
