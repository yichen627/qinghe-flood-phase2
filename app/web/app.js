/* 单机预报工作台：所有业务写入均通过受鉴权的现有服务。 */
'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names = {forecaster:'预报员',reviewer:'值班长',admin:'管理员'};
const statuses = {QUEUED:['排队中','neutral'],RUNNING:['计算中','warning'],SUCCEEDED:['计算完成','success'],FAILED:['计算失败','danger'],DRAFT:['草稿','neutral'],REVIEWED:['已复核','warning'],SIGNED:['已签发','success'],PUBLISHED:['已发布','success']};
const titles = {forecast:['预报工作台','从流域来水到预报签发，让每一次决策都有依据。'],events:['数据与质控','查看洪水输入与质量检查，保障预报数据可靠。'],products:['产品签发','复核、签发与发布，保留完整的产品操作链。'],schemes:['模型与方案','管理不可变参数与计算方案，保持预报可复现。'],operations:['调度与通知','查看自动起报计划、质控告警与值班通知。'],audit:['操作审计','查询业务操作与版本变更，追溯每一步处理。']};
const state = {key:'',role:'',view:'forecast',events:[],schemes:[],tasks:[],selected:null,routing:{},refreshing:false};
let toastTimer, actionSubmit;
const fmt = (v,n=3) => v==null ? '—' : Number(v).toLocaleString('zh-CN',{maximumFractionDigits:n,minimumFractionDigits:n});
const date = value => value ? new Date(value).toLocaleString('zh-CN',{hour12:false,month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : '—';
const eventName = id => state.events.find(e=>e.id===id)?.name || id.slice(0,8);
const badge = status => `<span class="badge ${statuses[status]?.[1] || 'neutral'}">${esc(statuses[status]?.[0] || status)}</span>`;
const canWrite = () => ['forecaster','admin'].includes(state.role);
function notify(message,error=false){$('toast').textContent=message;$('toast').classList.toggle('error',error);$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,6000);}
function errorText(value){if(Array.isArray(value))return value.map(v=>`${v.loc?.slice(1).join('.') || ''} ${v.msg || v}`).join('；');return typeof value==='string'?value:JSON.stringify(value);}
async function api(path,method='GET',body){
  const response = await fetch(path,{method,headers:{'X-API-Key':state.key,...(body!==undefined?{'Content-Type':'application/json'}:{})},...(body!==undefined?{body:JSON.stringify(body)}:{})});
  if(!response.ok){let message;try{const e=await response.json();message=errorText(e.detail || e);}catch{message=response.statusText;}throw new Error(`${response.status} · ${message}`);}
  return response.status===204?null:response.json();
}
function guarded(fn){return async event=>{try{await fn(event);}catch(error){notify(error.message,true);}};}
async function download(path,filename){
  const response=await fetch(path,{headers:{'X-API-Key':state.key}});
  if(!response.ok)throw new Error(`下载失败 ${response.status}`);
  const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function emptyRow(cols,text='暂无数据'){return `<tr><td colspan="${cols}" style="text-align:center;padding:35px;color:#9aa8bb">${esc(text)}</td></tr>`;}
function updatePermissions(){
  $('role-label').textContent=names[state.role] || '尚未连接';
  $('import-button').disabled=!canWrite();$('run-button').disabled=!canWrite();
  $('draft-button').disabled=!canWrite() || state.selected?.status!=='SUCCEEDED';
  document.querySelectorAll('.admin-action').forEach(b=>b.disabled=state.role!=='admin');
}
async function connect(){
  const previousKey=state.key;state.key=$('key-input').value;
  try{const session=await api('/workbench/session');state.role=session.role;}
  catch(error){state.key=previousKey;throw error;}
  $('auth-dialog').close();$('key-input').value='';$('connection').textContent='服务已连接';$('connection').classList.add('ok');updatePermissions();
  await refreshAll();notify(`已使用${names[state.role]}身份连接`);
}
async function refreshAll(){
  if(!state.key || state.refreshing)return;state.refreshing=true;
  try{
    [state.events,state.schemes,state.tasks,state.routing]=await Promise.all([api('/events?limit=100'),api('/schemes'),api('/forecasts?limit=100'),api('/routing')]);
    $('error-banner').hidden=true;$('connection').textContent='服务已连接';$('connection').classList.add('ok');
    renderSelectors();renderTasks();renderEvents();await runtime();await loadView();
    const candidate=state.selected?state.tasks.find(t=>t.id===state.selected.id):state.tasks.find(t=>t.status==='SUCCEEDED');
    if(candidate && (!state.selected || candidate.status!==state.selected.status))await selectTask(candidate.id);
  }catch(error){$('error-banner').textContent=error.message;$('error-banner').hidden=false;$('connection').textContent='连接异常';$('connection').classList.remove('ok');throw error;}
  finally{state.refreshing=false;}
}
function renderSelectors(){
  const current=$('event-select').value,scheme=$('scheme-select').value;
  $('event-select').innerHTML='<option value="">请选择已通过质控的数据</option>'+state.events.filter(e=>e.valid).map(e=>`<option value="${esc(e.id)}">${esc(e.name)} · ${e.row_count}时段</option>`).join('');
  if(state.events.some(e=>e.id===current&&e.valid))$('event-select').value=current;
  $('scheme-select').innerHTML='<option value="">当前活动方案 · 自动路由</option>'+state.schemes.filter(s=>!s.deleted).map(s=>`<option value="${esc(s.id)}">${esc(s.name)}</option>`).join('');
  if(state.schemes.some(s=>s.id===scheme&&!s.deleted))$('scheme-select').value=scheme;
}
function renderTasks(){
  const filter=$('task-filter').value,tasks=state.tasks.filter(t=>!filter||t.status===filter);
  $('task-count').innerHTML=`${state.tasks.length}<small>场</small>`;$('task-total').textContent=`${tasks.length} 场`;
  const running=state.tasks.filter(t=>['RUNNING','QUEUED'].includes(t.status)).length;
  $('task-note').textContent=running?`${running} 场正在计算或排队`:'最近 100 条任务';
  $('task-rows').innerHTML=tasks.map(t=>`<tr class="${state.selected?.id===t.id?'selected':''}"><td><strong>${esc(eventName(t.event_id))}</strong><small>${esc(t.id.slice(0,12))}</small></td><td>${esc(date(t.created_at))}</td><td>${badge(t.status)}</td><td>${fmt(t.metrics?.DC)}</td><td>${fmt(t.metrics?.RMSE,2)}</td><td>${t.status==='SUCCEEDED'?`<button class="text-button" data-task="${esc(t.id)}">查看曲线</button>`:''}<button class="text-button" data-task-details="${esc(t.id)}">任务详情</button></td></tr>`).join('') || emptyRow(6,'暂无预报任务，导入数据后即可起报');
}
function renderEvents(){
  $('event-rows').innerHTML=state.events.map(e=>`<tr><td><strong>${esc(e.name)}</strong><small>${esc(date(e.created_at))}</small></td><td>${e.row_count}</td><td><span class="badge ${e.valid?'success':'danger'}">${e.valid?'可用于预报':'已阻断'}</span></td><td>${e.error_count}</td><td>${e.warning_count}</td><td><button class="text-button" data-event="${esc(e.id)}">质控明细</button><button class="text-button" data-use-event="${esc(e.id)}" ${!e.valid||!canWrite()?'disabled':''}>去起报 →</button></td></tr>`).join('') || emptyRow(6,'暂无导入数据');
}
async function runtime(){
  const value=await api('/runtime');const healthy=!value.worker.stale&&!value.scheduler.stale;
  $('runtime-summary').textContent=healthy?'运行正常':'需要检查';$('runtime-summary').className='badge '+(healthy?'success':'warning');
  $('runtime-rows').innerHTML=[['worker','预报计算进程'],['scheduler','自动调度进程']].map(([key,label])=>`<div class="runtime-row"><span>${label}</span><span style="color:${value[key].stale?'#c09247':'#239a82'}">● ${value[key].stale?'心跳滞后':'在线'}</span></div>`).join('');
}
async function selectTask(id){
  const task=await api('/forecasts/'+id);state.selected=task;renderTasks();updatePermissions();
  $('chart-description').textContent=`${task.snapshot.event_name} · ${task.snapshot.source} · ${date(task.created_at)}`;
  $('download-plot').disabled=task.status!=='SUCCEEDED';
  if(task.status!=='SUCCEEDED'){
    $('chart').innerHTML=`<div class="empty"><span>${task.status==='FAILED'?'!':'◷'}</span><strong>${esc(statuses[task.status][0])}</strong><p>${esc(task.error || '后台服务正在处理，状态将自动更新')}</p></div>`;
    $('peak-value').innerHTML='—<small>m³/s</small>';$('peak-time').textContent='尚无可用结果';$('dc-value').textContent='—';$('rmse-value').innerHTML='—<small>m³/s</small>';return;
  }
  const q=task.result.simulation.Q,peak=Math.max(...q),index=q.indexOf(peak);
  $('peak-value').innerHTML=`${fmt(peak,1)}<small>m³/s</small>`;$('peak-time').textContent=`峰现时间 ${date(task.snapshot.event_rows[index].time)}`;
  $('dc-value').textContent=fmt(task.metrics.DC);$('dc-note').textContent=task.metrics.DC==null?'缺少有效实测或实测方差为零':task.metrics.DC>=.85?'达到检验目标 ≥ 0.85':'低于检验目标 0.85';
  $('rmse-value').innerHTML=`${fmt(task.metrics.RMSE,2)}<small>m³/s</small>`;drawChart(task);
}
function drawChart(task){
  const rows=task.snapshot.event_rows,q=task.result.simulation.Q,observed=rows.map(r=>r.Q_obs),n=q.length;
  const mobile=innerWidth<680;
  const W=Math.max(300,$('chart').clientWidth-36),H=mobile?260:340,L=mobile?40:58,R=22,T=28,B=43,width=W-L-R,height=H-T-B;
  const maximum=Math.max(1,...q,...observed.filter(v=>v!=null)),ymax=Math.ceil(maximum/5/Math.pow(10,Math.floor(Math.log10(maximum/5))))*Math.pow(10,Math.floor(Math.log10(maximum/5)))*5;
  const x=i=>L+i/Math.max(1,n-1)*width,y=v=>T+height*(1-v/ymax);
  const path=values=>{let result='',open=false;values.forEach((v,i)=>{if(v==null){open=false;return;}result+=`${open?'L':'M'}${x(i).toFixed(2)},${y(v).toFixed(2)} `;open=true;});return result;};
  const grid=Array.from({length:6},(_,i)=>{const yy=T+i*height/5;return `<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" stroke="#edf1f6"/><text x="${L-13}" y="${yy+4}" text-anchor="end" fill="#9aa8ba" font-size="10">${fmt(ymax*(1-i/5),0)}</text>`;}).join('');
  const tickCount=Math.min(mobile?4:7,n);
  const ticks=Array.from({length:tickCount},(_,i)=>Math.round(i*(n-1)/Math.max(1,tickCount-1))).map(i=>`<text x="${x(i)}" y="${H-17}" fill="#9aa8ba" font-size="10" text-anchor="middle">${esc(date(rows[i].time).split(' ')[0])}</text>`).join('');
  const peak=Math.max(...q),pi=q.indexOf(peak);
  $('chart').innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="洪水流量过程线，蓝色实测，橙色模拟"><defs><linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#91b4f5" stop-opacity=".17"/><stop offset="100%" stop-color="#91b4f5" stop-opacity="0"/></linearGradient></defs><text x="${L}" y="13" fill="#99a6b8" font-size="10">流量（m³/s）</text>${grid}${ticks}<path d="${path(q)}L${x(n-1)},${y(0)} L${x(0)},${y(0)} Z" fill="url(#chart-fill)"/><path d="${path(observed)}" fill="none" stroke="#367bec" stroke-width="2.4"/><path d="${path(q)}" fill="none" stroke="#ec9944" stroke-width="2" stroke-dasharray="5 3"/><circle cx="${x(pi)}" cy="${y(peak)}" r="4" fill="#fff" stroke="#ec9944" stroke-width="2"/><text x="${Math.min(W-130,x(pi)+10)}" y="${Math.max(24,y(peak)-13)}" font-size="10" fill="#bd8b45">模拟洪峰 ${fmt(peak,1)}</text><line id="hover-line" y1="${T}" y2="${H-B}" stroke="#c4cfdf" stroke-dasharray="3 3" visibility="hidden"/><rect id="chart-hover" x="${L}" y="${T}" width="${width}" height="${height}" fill="transparent"/></svg>`;
  $('chart-range').textContent=`${date(rows[0].time)} — ${date(rows[n-1].time)}`;
  const surface=$('chart-hover');surface.addEventListener('mousemove',event=>{
    const box=surface.getBoundingClientRect(),i=Math.min(n-1,Math.max(0,Math.round((event.clientX-box.left)/box.width*(n-1))));
    const line=$('hover-line');line.setAttribute('x1',x(i));line.setAttribute('x2',x(i));line.setAttribute('visibility','visible');
    $('chart-tooltip').innerHTML=`${esc(date(rows[i].time))}<br><span style="color:#367bec">实测 ${fmt(observed[i],2)}</span><br><span style="color:#c88a39">模拟 ${fmt(q[i],2)} m³/s</span>`;$('chart-tooltip').hidden=false;
  });surface.addEventListener('mouseleave',()=>{$('chart-tooltip').hidden=true;$('hover-line').setAttribute('visibility','hidden');});
}
async function setView(view){state.view=view;Object.keys(titles).forEach(key=>$('view-'+key).hidden=key!==view);document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));$('page-title').textContent=titles[view][0];$('breadcrumb').textContent=titles[view][0];$('page-description').textContent=titles[view][1];await loadView();}
async function loadView(){
  if(!state.key)return;
  if(state.view==='products')await renderProducts();
  if(state.view==='schemes')renderSchemes();
  if(state.view==='operations')await renderOperations();
  if(state.view==='audit'){
    if(!['admin','reviewer'].includes(state.role)){$('audit-rows').innerHTML=emptyRow(5,'请切换值班长或管理员身份查看审计');return;}
    const rows=await api('/audit?limit=100');$('audit-rows').innerHTML=rows.map(r=>`<tr><td>${esc(date(r.created_at))}</td><td>${esc(names[r.actor] || r.actor)}</td><td>${esc(r.action)}</td><td>${esc(r.entity_id?.slice(0,12))}</td><td><button class="text-button" data-json="${esc(JSON.stringify(r))}">查看详情</button></td></tr>`).join('') || emptyRow(5);
  }
}
async function renderProducts(){
  const products=await api('/products?limit=100');$('product-rows').innerHTML=products.map(p=>{
    const action={DRAFT:'review',REVIEWED:'sign',SIGNED:'publish'}[p.status],label={review:'复核',sign:'签发',publish:'发布'}[action];
    return `<tr><td><strong>${esc(p.title)}</strong><small>${esc(p.id.slice(0,12))}</small></td><td>${esc(date(p.created_at))}</td><td>${badge(p.status)}</td><td><button class="text-button" data-product="${esc(p.id)}">详情</button>${action?`<button class="text-button" data-product-action="${action}" data-id="${esc(p.id)}" ${state.role!=='reviewer'?'disabled':''}>${label} →</button>`:''}${['SIGNED','PUBLISHED'].includes(p.status)?`<button class="text-button" data-export-product="${esc(p.id)}">导出</button>`:''}</td></tr>`;
  }).join('') || emptyRow(4,'选择成功预报后，可在工作台生成产品草稿');
}
function renderSchemes(){
  const active=state.routing.active_scheme_id || state.routing.active,previous=state.routing.previous_scheme_id || state.routing.previous;
  $('routing-description').textContent=`方案切换只影响未来任务 · 当前活动 ${state.schemes.find(s=>s.id===active)?.name || active || '未设置'}`;
  $('scheme-rows').innerHTML=state.schemes.map(s=>`<tr><td><strong>${esc(s.name)}</strong><small>${esc(s.id.slice(0,18))}</small></td><td>${esc(s.parameter_id.slice(0,12))}</td><td><span class="badge ${s.deleted?'neutral':s.id===active?'success':'neutral'}">${s.deleted?'已归档':s.id===active?'活动方案':s.id===previous?'可回滚':'可用'}</span></td><td><button class="text-button" data-parameters="${esc(s.id)}">参数</button><button class="text-button" data-activate="${esc(s.id)}" ${state.role!=='admin'||s.deleted||s.id===active?'disabled':''}>激活</button><button class="text-button" data-rollout="${esc(s.id)}" ${state.role!=='admin'||s.deleted?'disabled':''}>灰度</button><button class="text-button" data-archive="${esc(s.id)}" ${state.role!=='admin'||s.deleted?'disabled':''}>归档</button></td></tr>`).join('') || emptyRow(4);
}
async function renderOperations(){
  const schedules=await api('/schedules?limit=100');$('schedule-rows').innerHTML=schedules.map(s=>`<tr><td><strong>${esc(s.name)}</strong><small>${esc(eventName(s.event_id))}</small></td><td>${fmt(s.interval_seconds/3600,2)} 小时</td><td>${esc(date(s.next_run_at))}</td><td><span class="badge ${s.enabled?'success':'neutral'}">${s.enabled?'已启用':'已暂停'}</span></td><td><button class="text-button" data-toggle="${esc(s.id)}" data-enabled="${!s.enabled}" ${state.role!=='admin'?'disabled':''}>${s.enabled?'暂停':'启用'}</button></td></tr>`).join('') || emptyRow(5,'暂无起报计划');
  if(!['reviewer','admin'].includes(state.role)){$('alert-list').textContent='请切换值班长或管理员身份查看告警';$('inbox-list').textContent='请切换值班长或管理员身份查看收件箱';return;}
  const [alerts,inbox]=await Promise.all([api('/alerts?limit=100'),api('/inbox?limit=100')]);
  $('alert-list').innerHTML=alerts.map(a=>`<div class="record">${!a.acknowledged_at?`<button class="text-button" data-ack="${esc(a.id)}">确认处理</button>`:'<span class="badge success" style="float:right">已确认</span>'}<strong>${esc(eventName(a.event_id))}</strong><small>${esc(date(a.created_at))}</small><p>${esc(JSON.stringify(a.detail || a.message || a.issues || '数据质量异常，请在数据与质控中查看'))}</p></div>`).join('') || '<div class="empty">暂无质控告警</div>';
  $('inbox-list').innerHTML=inbox.map(m=>`<div class="record"><strong>${esc(m.payload?.title || m.payload?.kind || m.subject || m.title || m.kind || '值班通知')}</strong><small>${esc(date(m.created_at))}</small><p>${esc(typeof m.payload==='object'?JSON.stringify(m.payload):m.body || m.message || m.payload || '')}</p></div>`).join('') || '<div class="empty">暂无值班通知</div>';
}
function showDetail(title,content){$('detail-title').textContent=title;$('detail-content').innerHTML=content;$('detail-dialog').showModal();}
function showJson(title,value){showDetail(title,`<pre>${esc(JSON.stringify(value,null,2))}</pre>`);}
function action(title,fields,submit){$('action-title').textContent=title;$('action-fields').innerHTML=fields;$('action-error').textContent='';actionSubmit=submit;$('action-dialog').showModal();}
function field(id,label,value='',type='text'){return `<label>${esc(label)}<input id="${id}" type="${type}" value="${esc(value)}" required></label>`;}
async function eventDetail(id){const e=await api('/events/'+id);showDetail(e.name+' · 质控明细',`<p class="muted">${e.row_count} 时段 · ${e.error_count} 错误 · ${e.warning_count} 告警</p><h3>该场初态</h3><pre>${esc(JSON.stringify(e.state0,null,2))}</pre><h3>逐行检查</h3><div class="table-scroll"><table><thead><tr><th>级别</th><th>原始行</th><th>字段</th><th>问题</th></tr></thead><tbody>${e.issues.map(i=>`<tr><td>${esc(i.severity)}</td><td>${i.row}</td><td>${esc(i.field)}</td><td>${esc(i.message)}</td></tr>`).join('') || emptyRow(4,'全部检查通过')}</tbody></table></div>`);}

document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',guarded(()=>setView(button.dataset.view))));
$('account-button').onclick=()=>$('auth-dialog').showModal();
document.querySelectorAll('.close-dialog').forEach(button=>button.onclick=()=>button.closest('dialog').close());
document.querySelectorAll('[data-demo]').forEach(button=>button.onclick=()=>{$('key-input').value={forecaster:'qinghe-local-demo',reviewer:'qinghe-reviewer-demo',admin:'qinghe-admin-demo'}[button.dataset.demo];});
$('auth-form').addEventListener('submit',async e=>{e.preventDefault();$('auth-error').textContent='';const b=e.submitter;b.disabled=true;try{await connect();}catch(error){$('auth-error').textContent=error.message;if(!$('auth-dialog').open)notify(error.message,true);}finally{b.disabled=false;}});
$('refresh').onclick=guarded(async()=>{if(!state.key){$('auth-dialog').showModal();return;}await refreshAll();notify('数据已刷新');});
$('task-filter').onchange=renderTasks;
$('event-select').onchange=()=>{const e=state.events.find(e=>e.id===$('event-select').value);$('event-hint').textContent=e?`${e.row_count}时段 · ${e.warning_count}条告警 · 已通过起报质控`:'每场洪水使用各自独立的初始状态';};
$('import-button').onclick=()=>$('import-dialog').showModal();
$('sample-select').onchange=guarded(async()=>{if(!$('sample-select').value)return;const e=await api('/workbench/examples/'+$('sample-select').value);$('import-name').value=e.name;$('csv-input').value=e.csv_text;$('state-input').value=JSON.stringify(e.state0,null,2);});
$('csv-file').onchange=guarded(async()=>{const file=$('csv-file').files[0];if(!file)return;if(file.size>1048576)throw new Error('CSV不能超过1MB');$('csv-input').value=await file.text();$('import-name').value=file.name.replace(/\.csv$/i,'');$('state-input').value='';$('sample-select').value='';notify('CSV已加载，请填写该场专属初态');});
$('import-form').addEventListener('submit',guarded(async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;try{let initial;try{initial=JSON.parse($('state-input').value);}catch{throw new Error('初始状态必须是合法JSON');}const result=await api('/events','POST',{name:$('import-name').value,csv_text:$('csv-input').value,state0:initial});$('import-dialog').close();await refreshAll();if(result.valid){$('event-select').value=result.id;await setView('forecast');notify(`${result.duplicate?'该场已存在':'导入成功'} · ${result.warning_count}条告警`);}else{await setView('events');await eventDetail(result.id);notify('数据已归档，存在错误，禁止起报',true);}}finally{b.disabled=false;}}));
$('forecast-form').addEventListener('submit',guarded(async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;try{const body={event_id:$('event-select').value};if($('scheme-select').value)body.scheme_id=$('scheme-select').value;const t=await api('/forecasts','POST',body);await refreshAll();await selectTask(t.id);notify('预报任务已提交，等待后台计算');}finally{b.disabled=!canWrite();}}));
$('download-plot').onclick=guarded(()=>download('/forecasts/'+state.selected.id+'/plot.png',state.selected.snapshot.event_name+'-预报过程线.png'));
$('draft-button').onclick=()=>{if(!state.selected)return;action('生成预报产品草稿',field('product-title','产品标题',state.selected.snapshot.event_name+' 洪水预报'),async()=>{await api('/products','POST',{forecast_id:state.selected.id,title:$('product-title').value});await setView('products');notify('产品草稿已生成，请切换值班长进行复核');});};
$('rollback').onclick=()=>action('回滚上一活动方案','<p class="muted" style="margin-bottom:20px">将后续自动路由起报切换至上一方案，既有任务保持原快照。</p>',async()=>{await api('/schemes/rollback','POST');await refreshAll();notify('方案已回滚');});
$('new-scheme').onclick=()=>{
  const base=state.schemes.find(s=>!s.deleted);if(!base){notify('没有可复制的方案',true);return;}
  action('创建参数版本与预报方案',field('scheme-name','新方案名称')+`<label>参数 JSON<textarea id="scheme-params" rows="10" required>${esc(JSON.stringify(base.params,null,2))}</textarea></label><p class="field-hint">创建新的不可变参数版本，沿用当前已部署模型，不覆盖原方案。</p>`,async()=>{
    let params;try{params=JSON.parse($('scheme-params').value);}catch{throw new Error('参数必须是合法JSON');}const name=$('scheme-name').value;
    const p=await api('/parameter-sets','POST',{name:name+' 参数',params});await api('/schemes','POST',{name,parameter_id:p.id,model_version:base.model_version});await refreshAll();notify('新参数版本与方案已创建');
  });
};
$('new-schedule').onclick=()=>{
  action('创建定时起报计划',field('schedule-name','计划名称')+`<label>洪水数据<select id="schedule-event" required>${state.events.filter(e=>e.valid).map(e=>`<option value="${esc(e.id)}">${esc(e.name)}</option>`).join('')}</select></label>`+field('schedule-hours','起报间隔（小时）','6','number')+'<p class="field-hint">首次在一个间隔后起报，使用当前活动方案；不会自动签发产品。</p>',async()=>{
    const seconds=Number($('schedule-hours').value)*3600;if(!Number.isInteger(seconds)||seconds<5)throw new Error('间隔至少5秒，且应为整数秒');
    await api('/schedules','POST',{name:$('schedule-name').value,event_id:$('schedule-event').value,interval_seconds:seconds,next_run_at:new Date(Date.now()+seconds*1000).toISOString()});await renderOperations();notify('起报计划已创建');
  });
};
$('action-form').addEventListener('submit',async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;$('action-error').textContent='';try{await actionSubmit();$('action-dialog').close();}catch(error){$('action-error').textContent=error.message;}finally{b.disabled=false;}});
document.addEventListener('click',guarded(async event=>{
  const b=event.target.closest('button');if(!b||b.disabled)return;const d=b.dataset;
  if(d.task){
    await selectTask(d.task);
    document.querySelector('.hydrograph').scrollIntoView({behavior:'smooth',block:'start'});
  }
  if(d.taskDetails){
    const task=await api('/forecasts/'+d.taskDetails),metrics=task.metrics || {};
    const rows=[['确定性系数 DC',fmt(metrics.DC,6)],['均方根误差 RMSE',fmt(metrics.RMSE,3)+' m³/s'],['洪峰相对误差',fmt(metrics.peak_relative_error_pct,3)+' %'],['峰现时间误差',fmt(metrics.peak_time_error_h,1)+' h'],['有效实测时段',metrics.observed_count ?? '—']];
    showDetail('任务详情',`<p class="muted">${esc(task.snapshot.event_name)} · ${esc(date(task.created_at))} ${badge(task.status)}</p>${task.error?`<p class="error-text">${esc(task.error)}</p>`:''}${task.status==='SUCCEEDED'?`<div class="card-bottom"><button class="secondary" data-analysis="${esc(task.id)}">导出误差分析</button><button class="secondary" data-replay="${esc(task.id)}" ${!canWrite()?'disabled':''}>原快照回放</button></div><h3>预报评价指标</h3><table><tbody>${rows.map(([key,value])=>`<tr><td>${esc(key)}</td><td>${esc(value)}</td></tr>`).join('')}</tbody></table>`:''}<h3>该场初始状态</h3><table><tbody>${Object.entries(task.snapshot.model_request.state0).map(([key,value])=>`<tr><td>${esc(key)}</td><td>${esc(value)}</td></tr>`).join('')}</tbody></table><details style="margin-top:20px"><summary>查看版本与快照信息</summary><pre>${esc(JSON.stringify({任务编号:task.id,参数摘要:task.snapshot.params_sha256,模型版本:task.snapshot.model_request.model_version,回放比较:task.result?.replay_comparison},null,2))}</pre></details>`);
  }
  if(d.event)await eventDetail(d.event);
  if(d.useEvent){$('event-select').value=d.useEvent;await setView('forecast');}
  if(d.json)showJson('操作详情',JSON.parse(d.json));
  if(d.product)showJson('产品详细信息',await api('/products/'+d.product));
  if(d.parameters)showJson('方案参数',state.schemes.find(s=>s.id===d.parameters));
  if(d.analysis)await download('/forecasts/'+d.analysis+'/analysis.md','洪水误差分析.md');
  if(d.exportProduct)await download('/products/'+d.exportProduct+'/export.json','洪水预报产品.json');
  if(d.replay){const t=await api('/forecasts/'+d.replay+'/replay','POST');$('detail-dialog').close();await setView('forecast');await refreshAll();await selectTask(t.id);notify('已使用原始快照提交回放任务');}
  if(d.productAction){action({review:'复核预报产品',sign:'签发预报产品',publish:'发布预报产品'}[d.productAction],d.productAction==='review'?'<label>复核意见<textarea id="review-note" rows="3" required placeholder="请填写复核意见"></textarea></label>':'<p class="muted" style="margin-bottom:20px">确认执行本次操作，系统将记录当前身份、时间和产品内容摘要。</p>',async()=>{await api('/products/'+d.id+'/'+d.productAction,'POST',d.productAction==='review'?{note:$('review-note').value}:undefined);await renderProducts();notify('产品状态已更新');});}
  if(d.activate)action('激活预报方案','<p class="muted" style="margin-bottom:20px">确认切换后续自动路由任务的计算方案，原预报结果和快照不受影响。</p>',async()=>{await api('/schemes/'+d.activate+'/activate','POST');await refreshAll();notify('新方案已激活');});
  if(d.rollout)action('配置方案灰度',field('rollout-percent','灰度百分比 0至100','10','number'),async()=>{const value=Number($('rollout-percent').value);if(!Number.isInteger(value)||value<0||value>100)throw new Error('灰度比例需为0至100的整数');await api('/rollouts','POST',{scheme_id:d.rollout,percentage:value});await refreshAll();notify('灰度配置已更新');});
  if(d.archive)action('归档方案','<p class="muted" style="margin-bottom:20px">归档后不再用于新起报，历史记录保留。活动或被计划引用的方案将被服务端拒绝归档。</p>',async()=>{await api('/schemes/'+d.archive,'DELETE');await refreshAll();notify('方案已归档');});
  if(d.toggle){await api('/schedules/'+d.toggle,'PATCH',{enabled:d.enabled==='true'});await renderOperations();notify('计划状态已更新');}
  if(d.ack){await api('/alerts/'+d.ack+'/acknowledge','POST');await renderOperations();notify('告警已确认');}
}));
setInterval(async()=>{if(!state.key||state.refreshing||document.hidden||document.querySelector('dialog[open]'))return;try{await refreshAll();}catch{/* 保留错误横幅，下一轮继续检查 */}},5000);
function clock(){ $('clock').textContent=new Date().toLocaleDateString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit'}); }clock();setInterval(clock,60000);
let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(state.selected?.status==='SUCCEEDED'&&state.view==='forecast')drawChart(state.selected);},100);});
updatePermissions();$('auth-dialog').showModal();
