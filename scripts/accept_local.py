#!/usr/bin/env python3
"""Repeatable acceptance. Any failure leaves the remote gate closed."""
import json
import os
import subprocess
import time
from pathlib import Path
from gates import ROOT,fingerprint

reports=ROOT/'reports';reports.mkdir(exist_ok=True)
local_env=Path('/tmp/lean-observatory-local.env')
if not local_env.exists():
    import secrets
    local_env.write_text('ADMIN_TOKEN='+secrets.token_urlsafe(36)+'\nENABLE_REAL=0\nHTTP_PORT=8789\nMETRICS_DIR=/tmp/lean-observatory-host-metrics\n')
    local_env.chmod(0o600)
checks={}
steps=[('backend',['npm','run','test:unit']),('charts',['npm','run','test:charts']),('build',['npm','run','build']),('browser',['npm','run','test:e2e']),
       ('compose',['docker','compose','--env-file','/tmp/lean-observatory-local.env','--profile','mock','up','-d','--build','--wait']),
       ('http',['docker','compose','--env-file','/tmp/lean-observatory-local.env','run','--rm','--no-deps','-v',str(ROOT/'scripts/http_smoke.py')+':/app/http_smoke.py:ro','api','python3','http_smoke.py']),
       ('worker_image',['docker','compose','--env-file','/tmp/lean-observatory-local.env','--profile','verification','build','worker']),
       ('worker_smoke',['docker','compose','--env-file','/tmp/lean-observatory-local.env','-f','compose.yaml','-f','compose.smoke.yaml','--profile','verification','run','--rm','--no-deps','-v',str(ROOT/'scripts/container_smoke.py')+':/app/container_smoke.py:ro','worker','python3','container_smoke.py'])]
receipt=dict(generatedAt=time.time(),sourceSha256=fingerprint(),checks=checks,scope='Local fixtures only; real proof reproduction NOT_RUN',remoteConnected=False)
for name,argv in steps:
    start=time.time();log=reports/(name+'.log')
    print('Checking '+name,flush=True)
    with log.open('w') as f: code=subprocess.run(argv,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT).returncode
    checks[name]=dict(exitCode=code,seconds=round(time.time()-start,2),command=argv,log=log.name)
    receipt['passed']=code==0 and len(checks)==len(steps)
    (reports/'local-acceptance.json').write_text(json.dumps(receipt,indent=2))
    if code: raise SystemExit('Failed '+name+'; see '+str(log))
print('Local gate passed. Remote not connected.',flush=True)
