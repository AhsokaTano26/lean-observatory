import os,json,urllib.request,urllib.error
base='http://nginx:8080'
def req(path,data=None,authorized=False):
    headers={'Content-Type':'application/json'}
    if authorized:headers['Authorization']='Bearer '+os.environ['ADMIN_TOKEN']
    return urllib.request.urlopen(urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers),timeout=10)
assert json.load(req('/healthz'))['ok']
try:req('/api/runs',{'mode':'mock'})
except urllib.error.HTTPError as e:assert e.code==401;e.close()
else:raise AssertionError('Mutation allowed without token')
p=json.load(req('/api/state'));old=p['run']
assert old['id'] is None or old['mode']=='mock','Refusing to mutate a real verification run in local smoke tests'
if old['id'] and old['status'] in ('queued','running','paused','interrupted','failed','resource_exhausted'):req('/api/control',{'run':old['id'],'action':'cancel'},True).close()
s=json.load(req('/api/runs',{'mode':'mock','scenario':'success'},True))
req('/api/control',{'run':s['id'],'action':'pause'},True).close()
r=json.load(req('/api/report.json?run='+s['id']));assert r['run']['mode']=='mock' and r['run']['proofAccepted'] is False
with req('/api/events') as stream:
    lines=[stream.readline().decode() for _ in range(4)]
assert 'event: snapshot\n' in lines
with req('/api/logs/download?run='+s['id']) as f: assert len(f.read())>0
req('/api/control',{'run':s['id'],'action':'resume'},True).close()
print(json.dumps({'nginx':'passed','health':'passed','unauthorizedMutation':'401','mockCreatePauseResume':'passed','sse':'passed','reportAndFullLogs':'passed','realProof':'NOT_RUN'}))
