#!/usr/bin/env python3
"""Run on the deployed server before enabling real tasks. Checks actual host metrics."""
import argparse,json,time,urllib.request
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8789');p.add_argument('--output',default='reports/online-acceptance.json');a=p.parse_args()
with urllib.request.urlopen(a.url+'/api/state',timeout=10) as r: data=json.load(r)
m=data['metrics']
assert m['source']=='host_agent' and not m.get('stale',True),'Live host metrics not connected'
assert time.time()-m['sampledAt']<20,'Host metrics stale'
assert m['cpuCount']>=64 and m['memoryTotalBytes']>=240*1024**3,'Wrong host/resource allocation'
assert data['run']['mode']!='mock','Switch to a clean real environment before online acceptance'
receipt={'passed':True,'checkedAt':time.time(),'host':m['hostname'],'source':'host_agent','note':'No proof verification started by this check'}
Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
