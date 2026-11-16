/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean}} AnalysisJob */
/** @typedef {{id:number,version:number,timezone:string,weekdays:number[],hour:number,minute:number,effective_at:number}} ScheduleVersion */
/** @typedef {{id:number,name:string,job_id:number,destination:string,schedule_kind:string,interval_seconds:?number,next_run:?number,enabled:boolean,current_version_id:?number,version:?ScheduleVersion}} ReportSchedule */
/** @typedef {{id:number,report_id:number,version_id:number,scheduled_at:number,scheduled_local:string,local_date:string,local_time:string,timezone:string,status:string,attempts:number,delivered_at:?number,delivery_id:?number,note:string}} Occurrence */
/** @typedef {{id:number,report_id:number,occurrence_id:?number,created_at:number,scheduled_local:?string,scheduled_at:?number,schedule_version:?number,checksum:string,filename:string,destination:string}} Delivery */
export {};
