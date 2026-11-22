#!/usr/bin/env python3
"""Build a read-only, offline result archive solely from saved local evidence."""
import argparse,collections,datetime,gzip,hashlib,io,json,shutil,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
LABELS={'download':'下载源码','integrity':'完整性校验','source':'源码校验','dependencies':'依赖准备',
        'compile':'完整编译','audit':'定理与公理审计','kernel':'内核重放','replay':'内核重放',
        'independent':'独立检查','persist':'结果归档'}
def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024**2),b''):h.update(chunk)
    return h.hexdigest()
def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def require(condition,message):
    if not condition:raise ValueError(message)
def script_data(value):
    text=json.dumps(value,ensure_ascii=False,separators=(',',':'))
    for old,new in [('<','\\u003c'),('>','\\u003e'),('&','\\u0026'),('\u2028','\\u2028'),('\u2029','\\u2029')]:text=text.replace(old,new)
    return 'window.LEAN_OBSERVATORY_RESULTS='+text+';\n'
def project(key,run,captured,logs):
    stages=[]
    for row in run['stages']:
        records=[c for c in run['commands'] if c.get('stage')==row['id']]
        seconds=sum(max(0,(c.get('finishedAt') or captured)-c['startedAt']) for c in records)
        stages.append({**row,'label':LABELS.get(row['id'],row['id']),
                       'commandSeconds':round(seconds,1) if records and all(c.get('finishedAt') for c in records) else None})
    spec=run.get('spec',{});preview=[]
    for row in list(logs)[-300:]:
        message=str(row.get('message',''));preview.append({k:row.get(k) for k in ['id','ts','stage','level']})
        preview[-1]['ts']=row.get('ts') or row.get('at')
        preview[-1]['message']=message[:1600]+('…' if len(message)>1600 else '')
    status=run['status'];passed=sum(str(r['status']).lower()=='passed' for r in stages)
    is_rh=key=='rh';partial=is_rh and status=='paused'
    env=run.get('environment',{})
    item={'id':key,'runId':run['id'],'name':'黎曼猜想' if is_rh else 'Navier–Stokes',
          'englishName':'Riemann Hypothesis' if is_rh else 'Navier–Stokes Equations',
          'status':status,'outcome':'PARTIAL' if partial else 'MACHINE_CHECKS_PASSED',
          'headline':'本机重放已暂停' if partial else '机器检查通过','phase':run['phase'],
          'passedStages':passed,'totalStages':len(stages),'stages':stages,'compile':run['compile'],
          'audits':[{**a,'independent':a.get('independent',run.get('independentChecker','NOT_RUN'))} for a in run['audits']],'startedAt':run.get('startedAt'),'finishedAt':run.get('finishedAt'),
          'elapsedSeconds':run.get('elapsedSeconds') if is_rh else round(run['finishedAt']-run['startedAt'],1),
          'proofAccepted':False,'semanticReview':'NOT_RUN','localReplay':'PAUSED' if partial else 'PASSED',
          'capturedAt':captured,'logs':preview,'logPreviewLimited':True,'commandCount':len(run['commands']),
          'source':{'url':'https://alpo.ge/' if is_rh else 'https://github.com/'+spec['repo'],
                    'commit':None if is_rh else spec['commit'],
                    'archiveSha256':run.get('provenance',{}).get('sha256') if is_rh else spec['archiveSha256'],
                    'lean':env.get('lean') if is_rh else spec['toolchain'].split(':')[-1],
                    'mathlib':env.get('actualMathlib') if is_rh else next(d['rev'] for d in spec['dependencies'] if d['name']=='mathlib')},
          'downloads':[]}
    if partial:
        item['externalVerification']={'status':'REFERENCED','name':'Andrew Sutherland（MIT）公开验证记录',
            'url':'https://math.mit.edu/~drew/grh/','pageUpdatedAt':'2026-11-22T04:35:00Z',
            'note':'用户采用外部验证依据；本机重放未完成，未改为通过。'}
    return item

def make_results(rh_api,ns_api,rh_logs,ns_logs):
    rh=rh_api['run'];ns=ns_api['queue']
    require(rh['status']=='paused' and rh['phase']=='replay','RH snapshot must retain the actual pause')
    require(rh['compile']['succeeded']==175187 and rh['compile']['failed']==0,'RH compile evidence missing')
    require(sum(s['status']=='passed' and s['exitCode']==0 for s in rh['stages'])==5,'RH checks differ')
    require(len(rh['audits'])==5 and all(a['type']=='passed' and a['axioms']=='passed' for a in rh['audits']),'RH audit evidence missing')
    require(ns['status']=='CHECKS_COMPLETED' and len(ns['stages'])==7,'NS final status missing')
    require(all(s['status']=='PASSED' and type(s['exitCode']) is int and s['exitCode']==0 for s in ns['stages']),'NS incomplete/failed stage')
    require(ns['spec']['repo']=='openai/NavierStokesAndEuler' and ns['spec']['commit']=='f9e8bc5b38b6e212696e8a30e3e91517af887bbd','NS fixed source differs')
    require({x['id'] for x in ns['stages']}=={'source','dependencies','compile','audit','kernel','independent','persist'},'NS required stage missing')
    require(ns['compile']['succeeded']==2659 and ns['compile']['failed']==0,'NS compile differs')
    require(len(ns['audits'])==2 and all(all(a.get(k)=='PASSED' for k in ['type','axioms','kernel','independent']) for a in ns['audits']),'NS target audit incomplete')
    command=ns['commands'][-1]
    require(command['stage']=='independent' and command['status']=='PASSED' and command['exitCode']==0,'NS independent exit missing')
    require(command['argv']==['lake','env','/work/ns/tools/comparator/.lake/build/bin/comparator','ComparatorChallenges/NavierStokes.json'],'NS checker command differs')
    for run in [rh,ns]:
        require(all(set(a.get('dependencies',[]))<={'propext','Classical.choice','Quot.sound'} for a in run['audits']),'Unpermitted proof axiom')
    require(ns.get('proofAccepted') is False and rh.get('proofAccepted') is False,'Machine checks are not a semantic-review certificate')
    captured=max(rh_api['serverTime'],ns_api['serverTime'])
    return {'schemaVersion':1,'static':True,'capturedAt':captured,'title':'Lean Observatory · 验证结果存档',
            'projects':[project('rh',rh,rh_api['serverTime'],rh_logs),project('ns',ns,ns_api['serverTime'],ns_logs)],
            'cost':{'currency':'USD','serverEstimatedUsd':ns_api.get('serverEstimatedUsd'),
                    'hourlyUsd':ns['budget'].get('hourlyUsd'),'capturedAt':ns_api['serverTime'],
                    'actualInvoiceAvailable':False,'scope':'Shared server estimate at capture, not a final invoice'},
            'disclosure':'RH 本机重放未完成；NS 已完成列明目标的机器检查。人工数学语义复核未进行。'}

def recent_rows(stream):
    rows=collections.deque(maxlen=300)
    for line in stream:
        value=json.loads(line)
        if 'message' in value:rows.append(value)
    return list(rows)

def validate_evidence(root, manifest):
    root=Path(root).resolve()
    for row in manifest['files']:
        p=root/row['path']
        require(p.resolve().is_relative_to(root) and p.is_file() and
                not any(item.is_symlink() for item in (p,*p.parents)), 'Invalid evidence path')
        require(p.stat().st_size==row['bytes'] and digest(p)==row['sha256'], 'Evidence hash differs: '+row['path'])

def build(args):
    root=Path(args.root).resolve();rh_api=json.loads((ROOT/'result_snapshots/2026-11-22/rh-api.json').read_text())
    ns_api=json.loads((ROOT/'result_snapshots/2026-11-22/ns-api.json').read_text())
    manifest=json.loads((root/'manifest.json').read_text());require(len(manifest['files'])==169,'Evidence capture differs')
    validate_evidence(root,manifest)
    # The API advertises the exact immutable final result and independent log.
    for api,is_rh in [(rh_api['run'],True),(ns_api['queue'],False)]:
        for row in api['artifacts']:
            if is_rh:p=root/'rh/evidence'/row['name']
            else:
                relative=row.get('path','')
                if relative.startswith('worker/'):p=root/'ns/evidence'/relative.removeprefix('worker/')
                elif relative=='artifacts/verification-result.json':p=root/'ns/verification-result.json'
                else:continue
            if p.is_file():require(p.stat().st_size==row['bytes'] and digest(p)==row['sha256'],'Published evidence hash differs: '+row['name'])
    final=json.loads((root/'ns/verification-result.json').read_text());require(final['status']=='CHECKS_COMPLETED' and final['proofAccepted'] is False,'Invalid final result')
    independent=json.loads((root/'ns/evidence/independent-report.json').read_text())
    from ns_queue.ns_worker import validate_independent_output
    validate_independent_output((root/'ns/evidence/logs/0071-independent.log').read_text(),independent['sandbox'])
    downloads=root/'downloads';downloads.mkdir(exist_ok=True)
    source_rh=Path(args.rh_logs).resolve();rh_archive=downloads/'rh-complete-logs.tar.gz'
    if source_rh!=rh_archive:shutil.copy2(source_rh,rh_archive)
    with tarfile.open(rh_archive) as tar:
        require(all(c['logFile'] in tar.getnames() for c in rh_api['run']['commands']),'RH complete log member missing')
        with tar.extractfile('events.ndjson') as stream:rh_logs=recent_rows(stream)
    # Verify the gzip footer, including archive bytes after tar's end marker.
    with gzip.open(rh_archive,'rb') as stream:
        while stream.read(1024**2):pass
    ns_events=Path(args.ns_events).resolve();ns_archive=downloads/'ns-complete-events.ndjson.gz'
    opener=gzip.open if ns_events.suffix=='.gz' else open
    with opener(ns_events,'rb') as stream:ns_logs=recent_rows(stream)
    if ns_events.suffix=='.gz':
        if ns_events!=ns_archive:shutil.copy2(ns_events,ns_archive)
    else:
        with ns_events.open('rb') as source,ns_archive.open('wb') as raw,gzip.GzipFile(fileobj=raw,mode='wb',mtime=0) as zipped:shutil.copyfileobj(source,zipped)
    data=make_results(rh_api,ns_api,rh_logs,ns_logs)
    for item in data['projects']:
        if item['id']=='rh':names=[('完整日志','downloads/rh-complete-logs.tar.gz'),('环境与版本','rh/evidence/environment.json'),('类型审计','rh/evidence/audit-output.txt'),('公理审计','rh/evidence/axioms-output.txt'),('源文件校验清单','rh/evidence/source-files.sha256'),('声明源码','rh/configuration/src/Main.lean')]
        else:names=[('最终验证报告','ns/verification-result.json'),('独立检查报告','ns/evidence/independent-report.json'),('完整 Comparator 日志','ns/evidence/logs/0071-independent.log'),('内核重放报告','ns/evidence/kernel-report.json'),('全部日志事件','downloads/ns-complete-events.ndjson.gz'),('类型与公理审计','ns/evidence/audit-report.json')]
        for title,name in names:
            p=root/name;require(p.is_file(),'Missing download: '+name)
            item['downloads'].append({'title':title,'path':name,'bytes':p.stat().st_size,'sha256':digest(p)})
    for name in ['index.html','app.css','app.js']:shutil.copy2(ROOT/'static_results'/name,root/name)
    write_json(root/'data/results.json',data);(root/'data.js').write_text(script_data(data))
    shutil.copy2(ROOT/'result_snapshots/2026-11-22/rh-api.json',root/'data/rh-api.json')
    shutil.copy2(ROOT/'result_snapshots/2026-11-22/ns-api.json',root/'data/ns-api.json')
    write_json(ROOT/'result_snapshots/2026-11-22/results.json',data)
    (root/'README.md').write_text('''# Lean Observatory 结果存档\n\n直接打开 index.html，或在本目录运行 python3 -m http.server 8000。所有页面资产和证据链接均为相对路径，不需要原服务器、API、WebSocket或CDN。data/results.json可供后续静态站使用，data.js支持file://直接打开。\n\nRH：编译和公理审计通过，本机重放主动暂停、未完成；外部验证依据单列。NS：列明两个目标的七阶段机器检查完成，人工数学语义复核未执行。\n\n包含169份原始证据、原始API快照、RH全部22条命令的完整日志归档、NS所有日志事件、依赖锁、脚本、哈希及迁移记录。大型证明导出、编译产物、完整源码归档、工具链、数据库和进程内存不在此精简存档内；这些文件的原始哈希/固定版本保留于报告和检查点。\n\n费用为采样时的共享服务器估算，不是最终账单。日志页面仅展示最近300条；完整日志可下载。可用 shasum -a256 -c SHA256SUMS 校验。\n''')
    sums=[]
    for p in sorted(root.rglob('*')):
        if p.is_file() and p.name!='SHA256SUMS':sums.append(digest(p)+'  '+str(p.relative_to(root)))
    (root/'SHA256SUMS').write_text('\n'.join(sums)+'\n')
    print(json.dumps({'site':str(root/'index.html'),'files':len(sums),'dataBytes':(root/'data/results.json').stat().st_size,'RH':'PARTIAL','NS':'MACHINE_CHECKS_PASSED'}))

if __name__=='__main__':
    import sys
    sys.path.insert(0,str(ROOT))
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',required=True);parser.add_argument('--rh-logs',required=True);parser.add_argument('--ns-events',required=True)
    build(parser.parse_args())
