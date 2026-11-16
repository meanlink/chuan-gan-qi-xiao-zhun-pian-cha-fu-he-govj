import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from src.config.database import get_db
from src.config.settings import ARTIFACT_DIR
from src.models import Report, Delivery, Occurrence, ScheduleVersion
from src.schemas.report import ReportInput, RescheduleInput
from src.middlewares.auth import current_user, admin_only
from src.services import reports
from src.services.audit import record
from src.utils.serialization import (
    report_dict, delivery_dict, occurrence_dict, version_dict)
router=APIRouter()
@router.get('/reports')
def listing(db=Depends(get_db),u=Depends(current_user)):
    return [report_dict(r) for r in db.scalars(select(Report).order_by(Report.id.desc()))]
@router.post('/reports',status_code=201)
def create(data:ReportInput,db=Depends(get_db),u=Depends(admin_only)):
    r=reports.create(db,data,u.email)
    record(db,u.email,'report.schedule',{'id':r.id,'kind':r.schedule_kind,
          'version':r.current_version_id}); db.commit()
    return report_dict(r)
@router.post('/reports/{id}/toggle')
def toggle(id:int,db=Depends(get_db),u=Depends(admin_only)):
    r=db.get(Report,id)
    if not r:raise HTTPException(404,'分发计划不存在')
    r.enabled=not r.enabled;record(db,u.email,'report.toggle',{'id':id,'enabled':r.enabled});db.commit()
    return report_dict(r)
@router.post('/reports/{id}/reschedule',status_code=201)
def reschedule(id:int,data:RescheduleInput,db=Depends(get_db),u=Depends(admin_only)):
    r,version=reports.reschedule(db,id,data,u.email)
    record(db,u.email,'report.reschedule',{'id':id,'version':version.version,
          'effective_at':version.effective_at,'timezone':version.timezone})
    db.commit()
    return {'report':report_dict(r),'version':version_dict(version)}
@router.get('/reports/{id}')
def detail(id:int,db=Depends(get_db),u=Depends(current_user)):
    r=db.get(Report,id)
    if not r:raise HTTPException(404,'分发计划不存在')
    return report_dict(r)
@router.get('/reports/{id}/occurrences')
def occurrences(id:int,limit:int=100,db=Depends(get_db),u=Depends(current_user)):
    if not db.get(Report,id):raise HTTPException(404,'分发计划不存在')
    rows=db.scalars(select(Occurrence).where(Occurrence.report_id==id)
        .order_by(Occurrence.scheduled_at.asc()).limit(min(limit,500))).all()
    return [occurrence_dict(o) for o in rows]
@router.get('/reports/{id}/versions')
def versions(id:int,db=Depends(get_db),u=Depends(current_user)):
    if not db.get(Report,id):raise HTTPException(404,'分发计划不存在')
    rows=db.scalars(select(ScheduleVersion).where(ScheduleVersion.report_id==id)
        .order_by(ScheduleVersion.version.asc())).all()
    return [version_dict(v) for v in rows]
@router.post('/reports/preview')
def preview(data:ReportInput,db=Depends(get_db),u=Depends(admin_only)):
    return reports.preview(db,data)
@router.get('/deliveries')
def deliveries(db=Depends(get_db),u=Depends(current_user)):
    return [delivery_dict(d) for d in db.scalars(select(Delivery).order_by(Delivery.id.desc()).limit(100))]
@router.get('/deliveries/{id}/download')
def download(id:int,format:str='csv',db=Depends(get_db),u=Depends(current_user)):
    d=db.get(Delivery,id)
    if not d:raise HTTPException(404,'归档不存在')
    if format not in ('csv','json'):raise HTTPException(422,'支持 CSV 或 JSON')
    filename=d.filename+('.json' if format=='json' else '')
    p=os.path.join(ARTIFACT_DIR,filename)
    if not os.path.exists(p):raise HTTPException(404,'归档文件不存在，请重新安排分发')
    return FileResponse(p,filename=filename,media_type='application/json' if format=='json' else 'text/csv; charset=utf-8')
