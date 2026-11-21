const $=id=>document.getElementById(id), esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=x=>x==null?'—':'$'+Number(x).toFixed(2), num=x=>Number.isFinite(Number(x))?Number(x).toLocaleString('en-US'):'—';
const stageNames={source:'源码校验',dependencies:'锁定依赖',compile:'全量编译',audit:'定理审计',kernel:'内核重放',independent:'独立验证',persist:'结果落盘'};
const statuses={QUEUED:'排队中',STARTING:'准备启动',RUNNING:'验证中',PAUSED:'已暂停',FAILED:'失败',COMPLETED:'检查完成',CHECKS_COMPLETED:'检查完成',PENDING:'未执行',PASSED:'通过',BLOCKED:'待处理'};
const reasons={waiting_rh:'等待 RH 全部必要检查成功',budget:'预算不足，禁止启动 NS',rh_evidence:'RH 完整证据尚未持久化',rh_unreachable:'暂时无法确认 RH 状态',rh_other_active_run:'其他验证仍在运行',rh_result_artifact:'等待 RH 最终报告落盘',rh_failed:'RH 失败，NS 已暂停',rh_interrupted:'RH 异常中断，NS 已暂停',rh_resource_exhausted:'RH 资源不足，NS 已暂停',memory:'可用内存不足',disk:'可用磁盘不足',cpu:'CPU 资源不足',ready:'启动门禁通过',running:'按真实日志推进'};
let rows=new Map(),lastData=null,connected=false;
function setTheme(theme){document.documentElement.dataset.theme=theme;localStorage.setItem('ns-theme',theme);$('theme').setAttribute('aria-label',theme==='dark'?'切换浅色主题':'切换深色主题');}
setTheme(localStorage.getItem('ns-theme')||'light');$('theme').onclick=()=>setTheme(document.documentElement.dataset.theme==='dark'?'light':'dark');
function renderLogs(){const query=$('filter').value.toLowerCase();const list=[...rows.values()].filter(r=>(r.stage+' '+r.message).toLowerCase().includes(query));$('log-count').textContent=rows.size+' 条';$('logs').innerHTML=list.length?list.map(r=>`<div class="log-row" data-level="${esc(r.level)}"><time>${new Date(r.at*1000).toLocaleTimeString('zh-CN',{hour12:false})}</time><span class="log-stage">${esc(r.stage)}</span><span>${esc(r.message)}</span></div>`).join(''):'NS 尚未启动，或当前窗口没有匹配日志。';}
$('filter').oninput=renderLogs;
function render(data){lastData=data;const s=data.queue,c=s.compile,b=s.budget,r=data.rh||{},rc=r.compile||{};
 $('status').textContent=statuses[s.status]||s.status;$('reason').textContent=reasons[s.reason]||s.reason;$('ns-chain').textContent=s.status;
 const total=c.total||s.spec.expectedFileCount||2659,percentage=c.total?100*c.succeeded/c.total:0;
 $('progress').textContent=percentage.toFixed(1)+'%';$('files').textContent=`${num(c.succeeded)} / ${num(total)} ${c.total?'已扫描 Lean 文件':'计划 Lean 文件'}`;
 $('cost').textContent=money(data.nsEstimatedUsd);$('budget').textContent=money(b.capUsd);
 $('banner').dataset.warning=String(s.status==='PAUSED'||b.capUsd===0);
 $('banner').textContent=s.status==='QUEUED'?'RH 优先 · NS 已排队。额外预算为 '+money(b.capUsd)+'；若 RH 完成后预算仍不足，NS 将暂停并通知管理员。':(reasons[s.reason]||s.reason)+'。未执行的检查不会提前标记成功。';
 $('phase').textContent=stageNames[s.phase]||s.phase;
 $('stages').innerHTML=s.stages.map((stage,i)=>`<li data-state="${esc(stage.status)}"><span class="step">${String(i+1).padStart(2,'0')} ${stage.status==='PASSED'?'✓':''}</span><b>${esc(stageNames[stage.id]||stage.id)}</b><small>${esc(statuses[stage.status]||stage.status)}</small><small>${stage.exitCode===null||stage.exitCode===undefined?'退出码 —':'退出码 '+esc(stage.exitCode)}</small></li>`).join('');
 $('rh-status').textContent=r.status||'等待采集';$('rh-progress').textContent=rc.total?(100*rc.succeeded/rc.total).toFixed(1)+'%':'—';$('rh-bar').value=rc.total?100*rc.succeeded/rc.total:0;
 $('rh-detail').textContent=r.id?`${r.id} · ${r.phase||''} · ${num(rc.succeeded)} / ${num(rc.total)}`:'保持现有 RH 环境运行';$('rh-cost').textContent='RH 任务时段估算：'+money(data.rhEstimatedUsd);
 const host=data.hostMetrics,ns=data.nsResources;$('resource-state').textContent=ns.source==='not_started'?'NS 未启动':ns.source==='docker_stats'?'NS 实际采样':'NS 采样暂不可用';
 $('ns-cpu').textContent=ns.cpuPercent==null?'—':Number(ns.cpuPercent).toFixed(1)+'%';$('ns-memory').textContent=ns.memoryBytes==null?'—':(ns.memoryBytes/1024**3).toFixed(2)+' GiB';
 $('host-cpu').textContent=!host||host.stale?'数据待更新':Number(host.cpuPercent||0).toFixed(1)+'%';$('host-memory').textContent=!host||host.stale?'—':Number(host.memoryPercent||0).toFixed(1)+'%';
 $('commit').textContent=s.spec.commit;$('repo').href='https://github.com/openai/NavierStokesAndEuler/tree/'+encodeURIComponent(s.spec.commit);$('toolchain').textContent=s.spec.toolchain||'Lean 4.34.0-rc2';
 $('result-state').textContent=['COMPLETED','CHECKS_COMPLETED'].includes(s.status)?'所列机器检查完成':'待验证';$('artifacts').innerHTML=s.artifacts.length?s.artifacts.map(a=>`<div class="evidence-row"><a href="/api/artifacts/${encodeURIComponent(a.name)}">${esc(a.name)}</a><code>${esc((a.sha256||'').slice(0,16))}…</code></div>`).join(''):'尚无 NS 验证产物。真实类型、公理、fresh 内核和 Comparator 检查均未执行。';
 for(const row of data.logs||[])rows.set(row.id,row);while(rows.size>1000)rows.delete(rows.keys().next().value);renderLogs();
 if(connected)$('connection').textContent=data.controllerOnline?'● SSE 已连接':'● SSE 已连接 · 调度器心跳待更新';
}
async function alerts(){try{const res=await fetch('/api/alerts');if(!res.ok)return;const list=await res.json();$('alerts').innerHTML=list.length?list.map(a=>`<div class="alert-row"><b>${esc(a.title)}</b><span>${esc(a.message)}</span><br><small>${esc({sent:'Webhook 发送已确认',accepted:'Webhook 已排队，等待投递',queued:'等待发送',retry:'发送失败，待重试'}[a.status]||a.status)} · 尝试 ${esc(a.attempts)} 次</small></div>`).join(''):'尚无告警。RH 异常、资源或预算不足时将在这里留存通知。';}catch{}}
const stream=new EventSource('/api/events');stream.addEventListener('snapshot',event=>{connected=true;$('connection').dataset.online='true';render(JSON.parse(event.data));});
stream.onerror=()=>{connected=false;$('connection').dataset.online='false';$('connection').textContent='○ 连接中断，自动重连';};
setInterval(async()=>{alerts();if(!connected){try{const res=await fetch('/api/state');if(res.ok)render(await res.json());}catch{}}},10000);alerts();
