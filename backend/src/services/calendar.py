"""时区化每周排期的纯函数模块。

规则：
- 按 IANA 时区与当地挂钟时间计算每场简报的 UTC 绝对时刻；
- 春令时跳空（不存在的当地时刻）标记为跳过，不发送；
- 秋令时重叠（同一当地时刻出现两次）只认 fold=0 的首次，重复时刻不发第二次；
- 所有计算基于 zoneinfo，不依赖系统本地时区。
"""
from datetime import datetime, timedelta, date as date_cls, time as time_cls, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']


def get_zone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f'不支持的时区：{tz_name}') from exc


def local_wall(d: date_cls, hour: int, minute: int) -> datetime:
    return datetime.combine(d, time_cls(hour, minute))


def wall_to_utc(d: date_cls, hour: int, minute: int, tz: ZoneInfo):
    """当地挂钟时间 → (UTC datetime 或 None, 是否不存在)。

    返回 (utc_dt, skipped)：
    - skipped=True：该当地时间在春令时跳空中不存在（如 02:30 在 02:00→03:00 切换日）；
    - 重叠时刻一律使用 fold=0，即重复时刻只取第一次。
    """
    naive = local_wall(d, hour, minute)
    first = naive.replace(tzinfo=tz, fold=0)
    second = naive.replace(tzinfo=tz, fold=1)
    if first.utcoffset() != second.utcoffset():
        # PEP 495：两个 fold 落在不同偏移。fold=0 偏移更小 → 春令时跳空
        # （该当地时刻不存在）；fold=0 偏移更大 → 秋令时重叠，取 fold=0
        # 即第一次出现，重复时刻不发第二次。
        if first.utcoffset() < second.utcoffset():
            return None, True
        return first.astimezone(timezone.utc), False
    return first.astimezone(timezone.utc), False


def iter_week_days(start: date_cls, end: date_cls, weekdays):
    """按日期顺序迭代 [start, end] 内命中 weekdays（ISO 1..7）的日期。"""
    days = sorted(set(weekdays))
    cur = start
    guard = 0
    while cur <= end and guard < 400:
        guard += 1
        if cur.isoweekday() in days:
            yield cur
        cur += timedelta(days=1)


def plan_occurrences(start: date_cls, end: date_cls, weekdays, hour, minute, tz_name: str):
    """生成场次计划：元素为 dict（含 local_date/local_time/scheduled_at/skipped）。

    scheduled_at 为 UTC epoch 秒；跳过场用 fold=0 映射的合成时刻作为唯一键，
    实际不会发送。按 UTC 时刻去重，重叠时刻只保留首次。
    """
    tz = get_zone(tz_name)
    out, seen = [], set()
    for d in iter_week_days(start, end, weekdays):
        utc_dt, skipped = wall_to_utc(d, hour, minute, tz)
        local_label = f'{d.isoformat()} {hour:02d}:{minute:02d}'
        if skipped:
            synthetic = local_wall(d, hour, minute).replace(tzinfo=tz, fold=0).astimezone(timezone.utc)
            ts = synthetic.timestamp()
            out.append({'local_date': d.isoformat(), 'local_time': f'{hour:02d}:{minute:02d}',
                        'timezone': tz_name, 'scheduled_at': ts, 'skipped': True})
            continue
        ts = utc_dt.timestamp()
        if ts in seen:
            # 重复时刻只发首次：跳过后续重复
            continue
        seen.add(ts)
        out.append({'local_date': d.isoformat(), 'local_time': f'{hour:02d}:{minute:02d}',
                    'timezone': tz_name, 'scheduled_at': ts, 'skipped': False})
    return out


def utc_epoch(dt: datetime) -> float:
    return dt.astimezone(timezone.utc).timestamp()


def from_epoch(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def format_local(ts: float, tz_name: str) -> str:
    tz = get_zone(tz_name)
    return datetime.fromtimestamp(ts, tz=tz).strftime('%Y-%m-%d %H:%M %Z')


def validate_weekdays(weekdays):
    days = sorted(set(int(d) for d in weekdays))
    if not days or any(d < 1 or d > 7 for d in days):
        raise ValueError('每周日期需在周一至周日中至少选择一天')
    return days
