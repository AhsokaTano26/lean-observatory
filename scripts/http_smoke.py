import json,urllib.request,urllib.error
base='http://nginx:8080'
def req(path): return urllib.request.urlopen(base+path,timeout=10)
assert json.load(req('/healthz'))['ok']
p=json.load(req('/api/state'))
assert p['capabilities']=={'readOnly':True}
before=[s['id'] for s in json.load(req('/api/runs'))]
for method in ['POST','PUT','PATCH','DELETE']:
    for path in ['/api/runs','/api/control']:
        request=urllib.request.Request(base+path,data=json.dumps({'mode':'mock','run':p['run']['id'],'action':'cancel'}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer local-compose-test-only'},method=method)
        try: urllib.request.urlopen(request,timeout=10)
        except urllib.error.HTTPError as e:
            assert e.code==405 and e.headers['Allow']=='GET'
            e.close()
        else: raise AssertionError('Web task mutation was allowed')
assert before==[s['id'] for s in json.load(req('/api/runs'))]
report=json.load(req('/api/report.json'))
assert report['run']['proofAccepted'] is False
with req('/api/events') as stream: lines=[stream.readline().decode() for _ in range(4)]
assert 'event: snapshot\n' in lines
if p['run']['id']:
    with req('/api/logs/download?run='+p['run']['id']) as f: assert len(f.read())>0
print(json.dumps({'nginx':'passed','health':'passed','allTaskWrites':'405','readOnly':True,'sse':'passed','reports':'passed','realProof':'NOT_RUN'}))
