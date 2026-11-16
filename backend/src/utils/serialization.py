import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at}
def job_dict(j):
    return {k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at']}
def version_dict(v):
    return {'id':v.id, 'report_id':v.report_id, 'version':v.version, 'timezone':v.timezone,
            'weekdays':v.weekdays, 'hour':v.hour, 'minute':v.minute,
            'effective_at':v.effective_at, 'created_at':v.created_at, 'created_by':v.created_by}
def occurrence_dict(o):
    return {'id':o.id, 'report_id':o.report_id, 'version_id':o.version_id,
            'scheduled_at':o.scheduled_at, 'local_date':o.local_date, 'local_time':o.local_time,
            'timezone':o.timezone, 'status':o.status, 'attempts':o.attempts,
            'claimed_at':o.claimed_at, 'claimed_by':o.claimed_by,
            'delivered_at':o.delivered_at, 'delivery_id':o.delivery_id, 'note':o.note,
            'scheduled_local':f'{o.local_date} {o.local_time} {o.timezone}'}
def report_dict(r):
    data = {k:getattr(r,k) for k in ['id','name','job_id','destination','schedule_kind',
                                     'interval_seconds','next_run','enabled','current_version_id']}
    data['version'] = version_dict(r.current_version) if r.current_version else None
    return data
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','occurrence_id','created_at',
            'scheduled_local','scheduled_at','schedule_version','checksum','filename','destination']}
