import time, json, logging, os, uuid
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report
from src.services.business import analyze
from src.services.reports import (
    deliver_legacy, ensure_horizon, recover_stale_claims, claim_due, deliver_occurrence)
from src.services.audit import record
logging.basicConfig(level=logging.INFO)
# 多执行者各持稳定标识，便于核对领取轨迹
WORKER_ID = os.getenv('WORKER_ID') or f'{os.getenv("HOSTNAME", "worker")}-{uuid.uuid4().hex[:8]}'

def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        j.status='running'; db.commit()
        try:
            d=db.get(Dataset,j.dataset_id)
            result=analyze(d.records,j.params)
            json.dumps(result,allow_nan=False)
            j.result=result;j.status='completed';j.finished_at=time.time()
            record(db,'worker','job.completed',{'id':j.id})
        except Exception as e:
            logging.exception('Analysis failed')
            j.status='failed';j.error=str(e)[:990];j.finished_at=time.time()
            record(db,'worker','job.failed',{'id':j.id,'error':j.error})
        db.commit()

def dispatch_weekly(db, now_ts):
    # 1) 崩溃恢复：超时领取的场次退回待领
    recover_stale_claims(db, now_ts)
    # 2) 续期未来场次窗（DST 规则随当前版本重新计算）
    ensure_horizon(db, now_ts)
    # 3) 原子领取到期场次：停机欠发逐场补齐，并发争领只有一方成功
    ids = claim_due(db, now_ts, WORKER_ID)
    db.commit()
    delivered = 0
    for oid in ids:
        # 每场独立事务，单场失败不影响其余欠发场次
        with Session() as sub:
            try:
                d = deliver_occurrence(sub, oid, WORKER_ID)
                if d:
                    record(sub, WORKER_ID, 'report.delivered',
                           {'delivery': d.id, 'occurrence': oid, 'report': d.report_id,
                            'version': d.schedule_version})
                    delivered += 1
                sub.commit()
            except Exception:
                logging.exception('Occurrence delivery failed: %s', oid)
                sub.rollback()
    return delivered

def tick():
    with Session() as db:
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
    for job_id in queued:execute(job_id)
    now_ts=time.time()
    with Session() as db:
        # 旧固定秒数计划逻辑保持不变
        for r in db.scalars(select(Report).where(
                Report.enabled==True, Report.schedule_kind=='interval',
                Report.next_run<=now_ts)):
            d=deliver_legacy(db,r)
            if d:record(db,WORKER_ID,'report.delivered',{'id':r.id,'delivery':d.id,'mode':'legacy'})
        db.commit()
    with Session() as db:
        enabled_weekly = db.scalar(select(Report.id).where(
            Report.enabled==True, Report.schedule_kind=='weekly').limit(1))
        if enabled_weekly:
            dispatch_weekly(db, now_ts)

def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            j.status='queued';record(db,'worker','job.recovered',{'id':j.id})
        # 崩溃前已领取但未归档的场次恢复为待领
        recovered = recover_stale_claims(db, time.time())
        if recovered:record(db,'worker','occurrence.recovered',{'count':recovered})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('analysis:queue',timeout=1)
            if item:execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
if __name__=='__main__':main()
