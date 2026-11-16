import {jobs,reports} from '../api/entities.js';
import {download} from '../api/client.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {OccurrenceStatus,Weekdays,CommonTimezones} from '../constants/enums.js';

let selectedId=null;
let previewRows=null;

const weekdayText=d=>d.map(n=>Weekdays[n]).join('、');
const hhmm=(h,m)=>String(h).padStart(2,'0')+':'+String(m).padStart(2,'0');
const isAdmin=()=>session.user.role==='admin';

function scheduleSummary(r){
 if(r.schedule_kind==='interval')return '固定秒数 · 每 '+r.interval_seconds+' 秒';
 const v=r.version;
 if(!v)return '每周排期';
 return esc(v.timezone)+' · '+weekdayText(v.weekdays)+' · 当地 '+hhmm(v.hour,v.minute)+' · v'+v.version;
}

function weekdayCheckboxes(name,prefix){
 return '<div class="weekday-row">'+[1,2,3,4,5,6,7].map(n=>
  '<label class="weekday"><input type="checkbox" name="'+name+'" value="'+n+'" '+(n<=5?'checked':'')+'><span>'+esc(Weekdays[n].slice(1))+'</span></label>').join('')+'</div>';
}

function createForm(approved){
 return '<section class="panel"><div class="section-title"><h2>创建分发计划</h2></div><form id="report-form">'
 +'<label>简报名称<input name="name" required minlength="2" value="海外实验室校准简报"></label>'
 +'<label>已批准分析<select name="job_id" required>'+approved.map(j=>'<option value="'+j.id+'">'+esc(j.name)+'</option>').join('')+'</select></label>'
 +'<label>业务接收组<input name="destination" value="北美校准实验室 · 本地收件箱" required></label>'
 +'<label>排期方式<select name="schedule_kind" id="schedule-kind"><option value="weekly">时区化每周当地时刻（推荐）</option><option value="interval">固定秒数（旧计划）</option></select></label>'
 +'<div id="weekly-fields"><label>实验室时区<input name="timezone" list="tz-list" value="America/New_York" required><datalist id="tz-list">'+CommonTimezones.map(t=>'<option value="'+t+'">').join('')+'</datalist></label>'
 +'<label>每周日期'+weekdayCheckboxes('weekdays','w')+'</label>'
 +'<div class="parameter-grid"><label>当地小时<input type="number" name="hour" min="0" max="23" value="9" required></label><label>当地分钟<input type="number" name="minute" min="0" max="59" value="0" required></label></div>'
 +'<label>首场日期（可选，默认时区今天）<input type="date" name="first_date"></label></div>'
 +'<div id="interval-fields" hidden><div class="parameter-grid"><label>分发周期<select name="interval_seconds"><option value="86400">每日</option><option value="604800">每周</option><option value="60">每分钟（验收）</option></select></label><label>首次执行<select name="delay_seconds"><option value="0">立即</option><option value="60">1 分钟后</option><option value="3600">1 小时后</option></select></label></div></div>'
 +'<div class="form-actions"><button type="submit" class="primary" '+(isAdmin()&&approved.length?'':'disabled')+'>保存分发计划</button><button type="button" class="button" id="preview-btn" '+(isAdmin()&&approved.length?'':'disabled')+'>预览后续场次</button></div>'
 +'</form><div id="preview-box" class="preview-box"></div>'
 +'<p class="hint">按 IANA 时区与当地挂钟时间排期：春令时不存在的时刻自动跳过，秋令时重叠时刻只发首次。改期以生效点为界，历史欠发沿用原版本。</p></section>';
}

function reportCard(r){
 const active=selectedId===r.id;
 return '<article class="'+(active?'selected':'')+'"><div><strong>'+esc(r.name)+'</strong><p>'+esc(r.destination)+'</p><small>'+scheduleSummary(r)+(r.enabled?'':' · 已暂停')+'</small></div>'
 +'<div class="card-actions"><button class="button small" data-inspect="'+r.id+'">核对</button><button class="button small" data-toggle="'+r.id+'" '+(isAdmin()?'':'disabled')+'>'+(r.enabled?'暂停':'启用')+'</button></div></article>';
}

function statusBadge(o){
 const cls=o.status==='delivered'?'ok':o.status==='skipped'?'muted':o.status==='claimed'?'warn':'';
 return '<span class="status-pill '+cls+'">'+esc(OccurrenceStatus[o.status]||o.status)+'</span>';
}

function inspectPanel(r,occs,versions){
 const now=Date.now()/1000;
 const overdue=occs.filter(o=>o.status==='pending'&&o.scheduled_at<=now).length;
 const delivered=occs.filter(o=>o.status==='delivered').length;
 const skipped=occs.filter(o=>o.status==='skipped').length;
 const v=r.version;
 const rows=occs.slice(0,60).map(o=>'<tr><td>'+esc(o.scheduled_local)+'</td><td>'+statusBadge(o)+'</td><td>'+(o.delivered_at?date(o.delivered_at):'—')+'</td><td>v'+esc(versions.find(x=>x.id===o.version_id)?.version??'?')+'</td><td>'+o.attempts+'</td></tr>').join('');
 return '<section class="panel inspect"><div class="section-title"><h2>场次核对 · '+esc(r.name)+'</h2><span>'+overdue+' 欠发 / '+delivered+' 已归档 / '+skipped+' 跳过</span></div>'
 +(r.schedule_kind==='weekly'
   ? '<p class="hint">当前版本 v'+v.version+'：'+esc(v.timezone)+' '+weekdayText(v.weekdays)+' '+hhmm(v.hour,v.minute)+'，生效点 '+date(v.effective_at)+'</p>'
   : '<p class="hint">固定秒数旧计划，不参与版本化改期。</p>')
 +'<div class="table-wrap"><table><thead><tr><th>原定当地时间</th><th>状态</th><th>实际归档时间</th><th>排期版本</th><th>领取次数</th></tr></thead><tbody>'+rows+'</tbody></table></div>'
 +(r.schedule_kind==='weekly'&&isAdmin()?rescheduleForm(r):'')+'</section>';
}

function rescheduleForm(r){
 return '<form id="reschedule-form" class="reschedule"><h3>改期（仅影响生效点之后的场次）</h3>'
 +'<div class="parameter-grid"><label>新时区<input name="timezone" list="tz-list" value="'+esc(r.version.timezone)+'" required></label>'
 +'<label>生效点（当地 ISO 日期时间，留空=立即）<input name="effective_at" placeholder="2027-01-15T09:00"></label></div>'
 +'<label>每周日期'+weekdayCheckboxes('r_weekdays','r')+'</label>'
 +'<div class="parameter-grid"><label>当地小时<input type="number" name="hour" min="0" max="23" value="'+r.version.hour+'" required></label><label>当地分钟<input type="number" name="minute" min="0" max="59" value="'+r.version.minute+'" required></label></div>'
 +'<button type="submit" class="primary small">提交改期并生成新版本</button></form>';
}

function inbox(deliveries){
 return '<section class="panel inbox"><div class="section-title"><h2>本地收件箱</h2><span>'+deliveries.length+' 份归档</span></div>'
 +deliveries.map(d=>'<div class="delivery"><div><strong>'+esc(d.filename)+'</strong><p>'+esc(d.destination)+' · 实际 '+date(d.created_at)+'</p><small>'+(d.scheduled_local?('原定 '+esc(d.scheduled_local)+' · v'+esc(d.schedule_version)):'固定秒数旧计划')+' · SHA256 '+esc(d.checksum.slice(0,20))+'…</small></div><div><button class="text-button" data-download="'+d.id+'" data-format="csv">CSV ↓</button><button class="text-button" data-download="'+d.id+'" data-format="json">JSON ↓</button></div></div>').join('')
 +(!deliveries.length?'<p class="empty">计划执行后，文件会出现在此处。</p>':'')+'</section>';
}

export async function reportPage(){
 const [list,deliveries,allJobs]=await Promise.all([reports.list(),reports.deliveries(),jobs.list()]);
 workspace.reports=list;
 const approved=allJobs.filter(j=>j.approved&&j.status==='completed');
 let extra='';
 if(selectedId){
  const r=list.find(x=>x.id===selectedId);
  if(r&&r.schedule_kind==='weekly'){
   const [occs,vers]=await Promise.all([reports.occurrences(r.id,200),reports.versions(r.id)]);
   extra=inspectPanel(r,occs,vers);
  }
 }
 const previewHtml=previewRows?('<div class="section-title"><h2>后续场次预览（60 天）</h2><span>'+previewRows.length+' 场</span></div>'
  +'<div class="table-wrap"><table><thead><tr><th>当地日期</th><th>当地时刻</th><th>时区</th><th>处理</th></tr></thead><tbody>'
  +previewRows.slice(0,20).map(p=>'<tr class="'+(p.skipped?'row-skip':'')+'"><td>'+esc(p.local_date)+'</td><td>'+esc(p.local_time)+'</td><td>'+esc(p.timezone)+'</td><td>'+(p.skipped?'不存在，跳过':'排期发送')+'</td></tr>').join('')+'</tbody></table></div>'):'';
 return heading('05 / DISTRIBUTION','定时分发与归档','按实验室当地日历交付校准简报：时区、每周日期与当地时刻驱动，自动处理夏令时；改期留版本，欠发可核对、可逐场补发。','<button class="button" id="refresh-reports">刷新收件箱 ↻</button>')
 +'<div class="report-grid">'+createForm(approved)
 +'<div><div class="section-title"><h2>运行中的计划</h2><span>'+list.filter(r=>r.enabled).length+' 条已启用</span></div><div class="schedule-list">'+list.map(reportCard).join('')+'</div>'
 +extra+inbox(deliveries)+'</div></div>'
 +(previewRows?'<section class="panel">'+previewHtml+'</section>':'');
}

function formPayload(f){
 const kind=f.get('schedule_kind');
 if(kind==='interval')return {name:f.get('name'),job_id:Number(f.get('job_id')),destination:f.get('destination'),schedule_kind:'interval',interval_seconds:Number(f.get('interval_seconds')),delay_seconds:Number(f.get('delay_seconds'))};
 const first=f.get('first_date');
 return {name:f.get('name'),job_id:Number(f.get('job_id')),destination:f.get('destination'),schedule_kind:'weekly',
  weekly:{timezone:f.get('timezone'),weekdays:f.getAll('weekdays').map(Number),hour:Number(f.get('hour')),minute:Number(f.get('minute')),...(first?{first_date:first}:{})}};
}

export function bindReports(refresh){
 document.querySelector('#refresh-reports').onclick=refresh;
 const kindSel=document.querySelector('#schedule-kind');
 kindSel.onchange=()=>{
  const weekly=kindSel.value==='weekly';
  document.querySelector('#weekly-fields').hidden=!weekly;
  document.querySelector('#interval-fields').hidden=weekly;
 };
 document.querySelector('#preview-btn').onclick=async()=>{
  const f=new FormData(document.querySelector('#report-form'));
  try{previewRows=await reports.preview(formPayload(f));await refresh();notify('已生成后续场次预览');}
  catch(e){notify(e.message,true);}
 };
 submit(document.querySelector('#report-form'),async f=>{
  await reports.create(formPayload(f));previewRows=null;notify('计划已保存，后台将按当地时刻归档');await refresh();
 });
 document.querySelectorAll('[data-toggle]').forEach(b=>b.onclick=async()=>{try{await reports.toggle(b.dataset.toggle);await refresh();}catch(e){notify(e.message,true);}});
 document.querySelectorAll('[data-inspect]').forEach(b=>b.onclick=async()=>{selectedId=Number(b.dataset.inspect);await refresh();});
 const rf=document.querySelector('#reschedule-form');
 if(rf)submit(rf,async f=>{
  const eff=f.get('effective_at');
  await reports.reschedule(selectedId,{timezone:f.get('timezone'),weekdays:f.getAll('r_weekdays').map(Number),hour:Number(f.get('hour')),minute:Number(f.get('minute')),...(eff?{effective_at:eff}:{})});
  notify('改期已生效，新版本只约束生效点之后的场次');await refresh();
 });
 document.querySelectorAll('[data-download]').forEach(b=>b.onclick=()=>download(b.dataset.download,b.dataset.format).catch(e=>notify(e.message,true)));
}
