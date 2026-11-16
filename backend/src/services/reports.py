import time, os, csv, io, hashlib, json
from datetime import datetime, date as date_cls, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import select, update, delete
from src.models import Job, Report, Delivery, ScheduleVersion, Occurrence
from src.config.settings import ARTIFACT_DIR
from src.services import calendar

# 预生成场次的时间窗（天）。到期场次在 worker 每轮自动向后续期。
HORIZON_DAYS = 180
# 领取后多久仍未归档视为崩溃，允许重新领取
CLAIM_STALE_SECONDS = 300
# 单轮最多补发场次，避免长时间停机后一轮压垮
BACKFILL_BATCH = 200


def _today_in_zone(tz_name: str) -> date_cls:
    return datetime.now(calendar.get_zone(tz_name)).date()


def _parse_iso_local(text: str, tz):
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(422, '时间格式需为 ISO 日期时间，如 2026-12-01T09:00') from exc
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=tz).astimezone(timezone.utc)


def _validate_job(db, job_id):
    j = db.get(Job, job_id)
    if not j or j.status != 'completed' or not j.approved:
        raise HTTPException(409, '请先选择已完成且获批准的分析结果')
    return j


def create(db, data, actor='admin'):
    _validate_job(db, data.job_id)
    r = Report(name=data.name, job_id=data.job_id, destination=data.destination,
               schedule_kind=data.schedule_kind, enabled=True)
    if data.schedule_kind == 'interval':
        # 旧固定秒数计划，逻辑保持不变
        r.interval_seconds = data.interval_seconds
        r.next_run = time.time() + data.delay_seconds
        db.add(r); db.flush()
        return r
    if not data.weekly:
        raise HTTPException(422, '每周排期需要提供时区、每周日期与当地时刻')
    w = data.weekly
    try:
        calendar.get_zone(w.timezone)  # 提前拒绝非法时区
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    start = date_cls.fromisoformat(w.first_date) if w.first_date else _today_in_zone(w.timezone)
    db.add(r); db.flush()
    version = ScheduleVersion(report_id=r.id, version=1, timezone=w.timezone,
                              weekdays=w.weekdays, hour=w.hour, minute=w.minute,
                              effective_at=time.time(), created_at=time.time(),
                              created_by=actor)
    db.add(version); db.flush()
    r.current_version_id = version.id
    _generate(db, r, version, start, note='')
    db.flush()
    return r


def _generate(db, report, version, start_date, note=''):
    """按版本生成 [start_date, +HORIZON_DAYS] 的场次；与已有同刻场次去重。

    不存在时刻写 skipped 场次留痕；重复 UTC 时刻（重叠）只保留首次。
    """
    end_date = start_date + timedelta(days=HORIZON_DAYS)
    plan = calendar.plan_occurrences(start_date, end_date, version.weekdays,
                                     version.hour, version.minute, version.timezone)
    existing = {row[0] for row in db.execute(
        select(Occurrence.scheduled_at).where(Occurrence.report_id == report.id)).all()}
    added = 0
    for item in plan:
        if item['scheduled_at'] in existing:
            continue
        existing.add(item['scheduled_at'])
        db.add(Occurrence(
            report_id=report.id, version_id=version.id,
            scheduled_at=item['scheduled_at'], local_date=item['local_date'],
            local_time=item['local_time'], timezone=item['timezone'],
            status='skipped' if item['skipped'] else 'pending',
            note='当地时刻在夏令时切换中不存在，自动跳过' if item['skipped'] else note))
        added += 1
    return added


def reschedule(db, report_id, data, actor='admin'):
    r = db.get(Report, report_id)
    if not r:
        raise HTTPException(404, '分发计划不存在')
    if r.schedule_kind != 'weekly':
        raise HTTPException(409, '固定秒数旧计划不支持时区化改期，请新建每周计划')
    try:
        tz = calendar.get_zone(data.timezone)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    eff_utc = _parse_iso_local(data.effective_at, tz) if data.effective_at else datetime.now(timezone.utc)
    last = db.scalar(select(ScheduleVersion).where(
        ScheduleVersion.report_id == r.id).order_by(ScheduleVersion.version.desc()))
    new_no = (last.version if last else 0) + 1
    version = ScheduleVersion(report_id=r.id, version=new_no, timezone=data.timezone,
                              weekdays=data.weekdays, hour=data.hour, minute=data.minute,
                              effective_at=eff_utc.timestamp(), created_at=time.time(),
                              created_by=actor)
    db.add(version); db.flush()
    # 界线：删除生效点之后尚未落地的场次；已归档/已领取（含旧版本欠发）一律保留。
    # 旧版本待领场次留在原版本上继续补发，晚到也不串入新排期。
    db.execute(delete(Occurrence).where(
        Occurrence.report_id == r.id,
        Occurrence.scheduled_at >= eff_utc.timestamp(),
        Occurrence.status.in_(('pending', 'skipped'))))
    db.flush()
    eff_local_date = eff_utc.astimezone(tz).date()
    _generate(db, r, version, eff_local_date, note='')
    r.current_version_id = version.id
    db.flush()
    return r, version


def ensure_horizon(db, now_ts):
    """对所有启用中的每周计划续期场次窗，覆盖长期运行后的未来场次需求。"""
    reports = db.scalars(select(Report).where(
        Report.schedule_kind == 'weekly', Report.enabled == True)).all()
    extended = 0
    for r in reports:
        version = db.get(ScheduleVersion, r.current_version_id)
        if not version:
            continue
        tz = calendar.get_zone(version.timezone)
        today = datetime.now(tz).date()
        furthest = db.scalar(select(Occurrence.scheduled_at).where(
            Occurrence.report_id == r.id).order_by(Occurrence.scheduled_at.desc()))
        if furthest is not None:
            # 已覆盖到最远场次之后 HORIZON_DAYS 之内则无需续期
            if (datetime.fromtimestamp(furthest, tz).date() - today).days > HORIZON_DAYS - 30:
                continue
            # 从最远场次的次日继续生成，避免起点当日重复
            start_date = datetime.fromtimestamp(furthest, tz).date() + timedelta(days=1)
        else:
            start_date = today
        extended += _generate(db, r, version, start_date)
    return extended


def recover_stale_claims(db, now_ts):
    """进程崩溃后恢复：claimed 超时场次回到 pending，保留 attempts 供核对。"""
    rows = db.execute(update(Occurrence).where(
        Occurrence.status == 'claimed',
        Occurrence.claimed_at < now_ts - CLAIM_STALE_SECONDS
    ).values(status='pending', claimed_at=None, claimed_by=None)).rowcount
    return rows


def claim_due(db, now_ts, worker_id, limit=BACKFILL_BATCH):
    """原子领取一批到期场次。条件更新保证多执行者争领只有一方成功。

    仅领取已启用计划的场次；暂停计划的欠发保留待恢复启用后补发。
    """
    ids = list(db.scalars(select(Occurrence.id).join(
        Report, Report.id == Occurrence.report_id).where(
        Occurrence.status == 'pending', Occurrence.scheduled_at <= now_ts,
        Report.enabled == True)
        .order_by(Occurrence.scheduled_at.asc()).limit(limit)).all())
    claimed = []
    for oid in ids:
        result = db.execute(update(Occurrence).where(
            Occurrence.id == oid, Occurrence.status == 'pending'
        ).values(status='claimed', claimed_at=now_ts, claimed_by=worker_id,
                 attempts=Occurrence.attempts + 1))
        db.commit()
        if result.rowcount == 1:
            claimed.append(oid)
    return claimed


def deliver_occurrence(db, occurrence_id, worker_id='worker'):
    """归档单个场次。每场仅一份归档，重试复用不新增。

    只有领取该场次的执行者可以归档；归属不符时跳过，
    由领取者或崩溃恢复后的新领取者处理，避免跨执行者串场。
    """
    occ = db.get(Occurrence, occurrence_id)
    if not occ or occ.status != 'claimed' or occ.claimed_by != worker_id:
        return None
    r = db.get(Report, occ.report_id)
    j = db.get(Job, r.job_id) if r else None
    now_ts = time.time()
    if not r or not j or not j.approved:
        # 数据不再可发：退回待领，下轮重试，不产生伪造归档
        occ.status = 'pending'; occ.claimed_at = None; occ.claimed_by = None
        db.flush()
        return None
    # 已存在归档（崩溃恢复场景）：只回写状态，不新增文件
    existing = db.scalar(select(Delivery).where(Delivery.occurrence_id == occ.id))
    if existing:
        occ.status = 'delivered'; occ.delivered_at = existing.created_at
        occ.delivery_id = existing.id
        db.flush()
        return existing
    version = db.get(ScheduleVersion, occ.version_id)
    payload, checksum = _render_csv(j)
    delivery = Delivery(
        report_id=r.id, occurrence_id=occ.id, created_at=now_ts,
        scheduled_local=f'{occ.local_date} {occ.local_time} {occ.timezone}',
        scheduled_at=occ.scheduled_at, schedule_version=version.version if version else None,
        checksum=checksum, filename='', destination=r.destination)
    db.add(delivery); db.flush()
    delivery.filename = f'report-{r.id}-v{version.version if version else 0}-occ{occ.id}.csv'
    _write_artifacts(delivery, j, payload, checksum)
    occ.status = 'delivered'; occ.delivered_at = now_ts; occ.delivery_id = delivery.id
    db.flush()
    return delivery


def _render_csv(j):
    out = io.StringIO()
    out.write('﻿')
    table = j.result.get('table', {})
    cols = table.get('columns', [])
    writer = csv.writer(out)

    def safe(v):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
        text = str(v)
        return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r')) else text

    writer.writerow([safe(c['label']) for c in cols])
    for row in table.get('rows', []):
        writer.writerow([safe(row.get(c['key'], '')) for c in cols])
    data = out.getvalue().encode('utf-8')
    return data, hashlib.sha256(data).hexdigest()


def _write_artifacts(delivery, j, data, checksum):
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    with open(os.path.join(ARTIFACT_DIR, delivery.filename), 'wb') as f:
        f.write(data)
    with open(os.path.join(ARTIFACT_DIR, delivery.filename + '.json'), 'w') as f:
        json.dump({'job': j.name, 'params': j.params, 'result': j.result,
                   'checksum': checksum,
                   'scheduled_local': delivery.scheduled_local,
                   'scheduled_at': delivery.scheduled_at,
                   'schedule_version': delivery.schedule_version},
                  f, ensure_ascii=False, allow_nan=False)


# ---- 旧固定秒数计划：保持原逻辑照常运行 ----
def deliver_legacy(db, report):
    j = db.get(Job, report.job_id)
    if not j or not j.approved:
        return None
    data, checksum = _render_csv(j)
    delivery = Delivery(report_id=report.id, created_at=time.time(),
                        checksum=checksum, filename='', destination=report.destination)
    db.add(delivery); db.flush()
    delivery.filename = f'report-{report.id}-delivery-{delivery.id}.csv'
    _write_artifacts(delivery, j, data, checksum)
    report.next_run = time.time() + report.interval_seconds
    return delivery


# 向后兼容：seed 脚本仍引用 deliver 名称
def deliver(db, report):
    return deliver_legacy(db, report)


def preview(db, data):
    """创建前预览后续场次（不落库）。"""
    if not data.weekly:
        raise HTTPException(422, '预览需要每周排期参数')
    w = data.weekly
    tz = calendar.get_zone(w.timezone)
    start = date_cls.fromisoformat(w.first_date) if w.first_date else _today_in_zone(w.timezone)
    end = start + timedelta(days=60)
    return calendar.plan_occurrences(start, end, w.weekdays, w.hour, w.minute, w.timezone)


def preview_report(db, report_id, limit=20):
    r = db.get(Report, report_id)
    if not r:
        raise HTTPException(404, '分发计划不存在')
    rows = db.scalars(select(Occurrence).where(
        Occurrence.report_id == r.id).order_by(Occurrence.scheduled_at.asc()).limit(limit)).all()
    return rows
