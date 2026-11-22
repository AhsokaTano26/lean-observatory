const $=id=>document.getElementById(id), esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const hours=x=>Number(x).toFixed(2)+' 小时',date=x=>x==null?'尚未配置':new Date(x*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
const money=x=>x==null?'—':'$'+Number(x).toFixed(2), num=x=>Number.isFinite(Number(x))?Number(x).toLocaleString('en-US'):'—';
const stageNames={source:'源码校验',dependencies:'锁定依赖',compile:'全量编译',audit:'定理审计',kernel:'内核重放',independent:'独立验证',persist:'结果落盘'};
const statuses={QUEUED:'排队中',STARTING:'准备启动',RUNNING:'验证中',PAUSED:'已暂停',FAILED:'失败',COMPLETED:'检查完成',CHECKS_COMPLETED:'检查完成',PENDING:'未执行',PASSED:'通过',BLOCKED:'待处理'};
const reasons={waiting_rh:'等待 RH 全部必要检查成功',budget:'剩余时限不足，禁止启动 NS',budget_deadline:'服务器总时限已到，NS 已暂停',rh_evidence:'RH 完整证据尚未持久化',rh_unreachable:'暂时无法确认 RH 状态',rh_other_active_run:'其他验证仍在运行',rh_result_artifact:'等待 RH 最终报告落盘',rh_failed:'RH 失败，NS 已暂停',rh_interrupted:'RH 异常中断，NS 已暂停',rh_resource_exhausted:'RH 资源不足，NS 已暂停',rh_replay_overlap:'已授权在 RH 内核重放期间并行启动',memory:'可用内存不足',disk:'可用磁盘不足',cpu:'CPU 资源不足',ready:'启动门禁通过',running:'按真实日志推进'};
let rows=new Map(),lastData=null,connected=false;
function setTheme(theme){document.documentElement.dataset.theme=theme;localStorage.setItem('ns-theme',theme);$('theme').setAttribute('aria-label',theme==='dark'?'切换浅色主题':'切换深色主题');}
setTheme(localStorage.getItem('ns-theme')||'light');$('theme').onclick=()=>setTheme(document.documentElement.dataset.theme==='dark'?'light':'dark');
function renderLogs(){const query=$('filter').value.toLowerCase();const list=[...rows.values()].filter(r=>(r.stage+' '+r.message).toLowerCase().includes(query));$('log-count').textContent=rows.size+' 条';$('logs').innerHTML=list.length?list.map(r=>`<div class="log-row" data-level="${esc(r.level)}"><time>${new Date(r.at*1000).toLocaleTimeString('zh-CN',{hour12:false})}</time><span class="log-stage">${esc(r.stage)}</span><span>${esc(r.message)}</span></div>`).join(''):'NS 尚未启动，或当前窗口没有匹配日志。';}
$('filter').oninput=renderLogs;
function render(data){lastData=data;const s=data.queue,c=s.compile,b=s.budget,r=data.rh||{},rc=r.compile||{};
 const parallel=s.schedulingMode==='parallel_replay',rhPersisted=s.rhEvidence?.persisted===true,rhPending=parallel&&!rhPersisted,rhReplaying=r.phase==='kernel';
 const active=['STARTING','RUNNING'].includes(s.status),nsStatus=(rhPending&&active?'并行':'')+(statuses[s.status]||s.status);
 $('status').textContent=nsStatus;$('reason').textContent=reasons[s.reason]||s.reason;$('ns-chain').textContent=parallel?nsStatus:s.status;
 $('queue-mode').textContent=parallel?'并行验证队列':'串行验证队列';
 $('queue-description').textContent='固定源码复现、公理审计与独立内核核验。'+(parallel?'RH 内核重放期间准入 NS，分别记录验证结果。':'RH 优先，验证任务严格串行。');
 $('dependency-title').textContent=parallel?'并行准入':'严格串行';
 $('dependency-rule').textContent=parallel?'RH 重放快照准入 · 最终成功另行归档':'↓ 全部必要检查成功 + 完整证据持久化';
 $('ns-policy').textContent=parallel?'已授权在 RH 内核重放期间并行启动；RH 失败仍会暂停 NS。':'RH 必要检查成功归档后自动启动；时限和资源预检只告警';
 $('rh-evidence').textContent=rhPersisted?'RH 最终检查成功证据已归档。':parallel?'并行准入快照已留存；RH 最终成功证据尚未归档。':'RH 最终成功证据尚未归档。';
 const total=c.total||s.spec.expectedFileCount||2659,percentage=c.total?100*c.succeeded/c.total:0;
 $('progress').textContent=percentage.toFixed(1)+'%';$('files').textContent=`${num(c.succeeded)} / ${num(total)} ${c.total?'已扫描 Lean 文件':'计划 Lean 文件'}`;
 $('cost').textContent=money(data.nsEstimatedUsd);$('server-cost').textContent=money(data.serverEstimatedUsd);
 $('budget').innerHTML=Number(b.capHours).toFixed(2)+' <span class="unit">小时</span>';$('remaining').innerHTML=Number(b.remainingHours).toFixed(2)+' <span class="unit">小时</span>';
 $('usage').textContent='服务器已用 '+hours(b.usedHours);$('deadline').textContent=b.deadlineAt?'截止（北京时间）'+date(b.deadlineAt):'等待配置租用起点';$('rental-start').textContent=date(b.rentalStartedAt);
 $('banner').dataset.warning=String(s.status==='PAUSED'||b.remainingHours===0);
 $('banner').textContent=parallel?(rhPending?(rhReplaying?'RH 内核重放尚未最终完成':'RH 最终检查尚未完成')+'；NS '+nsStatus+'。':'RH 全部必要检查已成功归档；NS '+nsStatus+'。')+(['PAUSED','FAILED'].includes(s.status)?(reasons[s.reason]||s.reason)+'。':'')+'未执行的检查不会提前标记成功。':s.status==='QUEUED'?(b.scope==='server'?'RH 优先 · NS 已排队。服务器共用 '+hours(b.capHours)+'，剩余 '+hours(b.remainingHours)+'；RH 全部必要检查成功并归档后自动启动 NS。'+(b.enforcement==='notify_only'?'计时与资源预检只告警，由管理员决定停止。':''):'RH 优先 · NS 已排队。时长额度为 '+hours(b.capHours)+'；配置服务器租用起点和总时限后生效。'):(reasons[s.reason]||s.reason)+'。未执行的检查不会提前标记成功。';
 $('phase').textContent=stageNames[s.phase]||s.phase;
 $('stages').innerHTML=s.stages.map((stage,i)=>`<li data-state="${esc(stage.status)}"><span class="step">${String(i+1).padStart(2,'0')} ${stage.status==='PASSED'?'✓':''}</span><b>${esc(stageNames[stage.id]||stage.id)}</b><small>${esc(statuses[stage.status]||stage.status)}</small><small>${stage.exitCode===null||stage.exitCode===undefined?'退出码 —':'退出码 '+esc(stage.exitCode)}</small></li>`).join('');
 $('rh-status').textContent=rhPending&&['running','starting','verifying'].includes(String(r.status).toLowerCase())?(rhReplaying?'内核重放待完成':'最终检查待完成'):r.status||'等待采集';$('rh-progress').textContent=rc.total?(100*rc.succeeded/rc.total).toFixed(1)+'%':'—';$('rh-bar').value=rc.total?100*rc.succeeded/rc.total:0;
 $('rh-detail').textContent=r.id?`${r.id} · ${r.phase||''} · ${num(rc.succeeded)} / ${num(rc.total)}`:'保持现有 RH 环境运行';$('rh-cost').textContent='RH 任务时段估算：'+money(data.rhEstimatedUsd);
 const host=data.hostMetrics,ns=data.nsResources;$('resource-state').textContent=ns.source==='not_started'?'NS 未启动':ns.source==='docker_stats'?'NS 实际采样':'NS 采样暂不可用';
 $('ns-cpu').textContent=ns.cpuPercent==null?'—':Number(ns.cpuPercent).toFixed(1)+'%';$('ns-memory').textContent=ns.memoryBytes==null?'—':(ns.memoryBytes/1024**3).toFixed(2)+' GiB';
 $('host-cpu').textContent=!host||host.stale?'数据待更新':Number(host.cpuPercent||0).toFixed(1)+'%';$('host-memory').textContent=!host||host.stale?'—':Number(host.memoryPercent||0).toFixed(1)+'%';
 const profile=s.resourceProfile||(parallel?{}:{cpus:60,memoryBytes:250000000000});
 $('resource-limit').textContent='共享宿主机包含 RH 占用，不计为 NS 使用。NS 当前限额：'+(Number.isFinite(profile.cpus)&&Number.isFinite(profile.memoryBytes)?num(profile.cpus)+' vCPU / '+num(profile.memoryBytes/1e9)+' GB（约 '+(profile.memoryBytes/1024**3).toFixed(2)+' GiB）。':'等待调度器采集。');
 $('commit').textContent=s.spec.commit;$('repo').href='https://github.com/openai/NavierStokesAndEuler/tree/'+encodeURIComponent(s.spec.commit);$('toolchain').textContent=s.spec.toolchain||'Lean 4.34.0-rc2';
 $('result-state').textContent=['COMPLETED','CHECKS_COMPLETED'].includes(s.status)?'所列机器检查完成':'待验证';$('artifacts').innerHTML=s.artifacts.length?s.artifacts.map(a=>`<div class="evidence-row"><a href="api/artifacts/${encodeURIComponent(a.name)}">${esc(a.name)}</a><code>${esc((a.sha256||'').slice(0,16))}…</code></div>`).join(''):'尚无 NS 验证产物。真实类型、公理、fresh 内核和 Comparator 检查均未执行。';
 for(const row of data.logs||[])rows.set(row.id,row);while(rows.size>1000)rows.delete(rows.keys().next().value);renderLogs();
 if(connected)$('connection').textContent=data.controllerOnline?'● SSE 已连接':'● SSE 已连接 · 调度器心跳待更新';
}
async function alerts(){try{const res=await fetch('api/alerts');if(!res.ok)return;const list=await res.json();$('alerts').innerHTML=list.length?list.map(a=>`<div class="alert-row"><b>${esc(a.title)}</b><span>${esc(a.message)}</span><br><small>${esc({sent:'Webhook 发送已确认',accepted:'Webhook 已排队，等待投递',queued:'等待发送',retry:'发送失败，待重试'}[a.status]||a.status)} · 尝试 ${esc(a.attempts)} 次</small></div>`).join(''):'尚无告警。RH 异常、资源或预算不足时将在这里留存通知。';}catch{}}
const stream=new EventSource('api/events');stream.addEventListener('snapshot',event=>{connected=true;$('connection').dataset.online='true';render(JSON.parse(event.data));});
stream.onerror=()=>{connected=false;$('connection').dataset.online='false';$('connection').textContent='○ 连接中断，自动重连';};
setInterval(async()=>{alerts();if(!connected){try{const res=await fetch('api/state');if(res.ok)render(await res.json());}catch{}}},10000);alerts();
