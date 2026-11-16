import time, json
from sqlalchemy import select, func
from src.config.database import Session
from migrations.initial import migrate
from src.models import User, Dataset, Job, Report, Delivery, Audit, ScheduleVersion, Occurrence
from src.services.business import metadata, seed_records, analyze
from src.services.reports import deliver_legacy, deliver_occurrence, claim_due
from src.schemas.report import ReportInput, WeeklySchedule
from src.services import reports
from src.utils.security import hash_password
from src.utils.serialization import checksum
def seed():
    migrate()
    with Session() as db:
        for role,name in [('admin','林知 · 业务负责人'),('analyst','陈舟 · 分析员'),('viewer','周禾 · 观察员')]:
            email=role+'@demo.local'
            if not db.scalar(select(User).where(User.email==email)):
                db.add(User(email=email,name=name,role=role,password=hash_password('Demo123!')))
        db.flush()
        m=metadata()
        d=db.scalar(select(Dataset).where(Dataset.name==m['dataset_name']))
        if not d:
            rows=seed_records()
            d=Dataset(name=m['dataset_name'],source=m['short']+'-202611.csv',records=rows,checksum=checksum(rows),created_at=time.time())
            db.add(d); db.flush()
        if not db.scalar(select(Job).where(Job.name=='基线复核 · '+m['name'])):
            params={p['key']:p['default'] for p in m.get('parameters',[])}
            result=analyze(d.records,params)
            json.dumps(result,ensure_ascii=False,allow_nan=False)
            admin=db.scalar(select(User).where(User.role=='admin'))
            j=Job(name='基线复核 · '+m['name'],dataset_id=d.id,params=params,status='completed',result=result,created_by=admin.id,created_at=time.time()-3600,finished_at=time.time()-3595,approved=True)
            db.add(j);db.flush()
            # 旧固定秒数计划：保持原逻辑照常运行
            legacy=Report(name='每日业务复核简报（固定秒数）',job_id=j.id,destination='业务复核组 · 本地收件箱',
                          schedule_kind='interval',interval_seconds=86400,next_run=time.time()+86400,enabled=True)
            db.add(legacy);db.flush();deliver_legacy(db,legacy)
            # 新时区化每周计划：纽约实验室，周一/三/五 当地 09:00，自动处理夏令时
            weekly_input=ReportInput(
                name='海外实验室校准简报（纽约当地 周一三五 09:00）',job_id=j.id,
                destination='北美校准实验室 · 本地收件箱',schedule_kind='weekly',
                weekly=WeeklySchedule(timezone='America/New_York',weekdays=[1,3,5],hour=9,minute=0))
            wr=reports.create(db,weekly_input,actor='seed')
            # 立即补发最早的一场，作为收件箱与欠发补发样例
            ids=claim_due(db,time.time()+7*24*3600,'seed',limit=1)
            if ids:
                delivery=deliver_occurrence(db,ids[0],'seed')
                db.add(Audit(actor='seed',action='demo.weekly.delivery',
                             detail={'report':wr.id,'occurrence':ids[0],'delivery':delivery.id if delivery else None},
                             at=time.time()))
            db.add(Audit(actor='seed',action='demo.baseline',detail={'dataset':d.id},at=time.time()))
        db.commit()
        counts={model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in [User,Dataset,Job,Report,Delivery,Audit,ScheduleVersion,Occurrence]}
        print(json.dumps(counts,ensure_ascii=False))
        return counts
if __name__=='__main__':seed()
