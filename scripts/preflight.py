#!/usr/bin/env python3
"""Read-only server inspection, available only after the complete local gate."""
import argparse
import json
import re
import subprocess
from pathlib import Path
from gates import ROOT,require_local_gate

REMOTE=r'''
import json,os,platform,shutil,subprocess
from pathlib import Path
def cmd(a):
 p=subprocess.run(a,capture_output=True,text=True);return {'exitCode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
mem={x.split(':')[0]:int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines()}
disk=shutil.disk_usage('/var/lib' if Path('/var/lib').exists() else '/')
report={'os':Path('/etc/os-release').read_text(),'kernel':platform.release(),'cpuCount':os.cpu_count(),'memoryBytes':mem['MemTotal'],'availableMemoryBytes':mem['MemAvailable'],'diskTotalBytes':disk.total,'diskFreeBytes':disk.free,'ports':cmd(['ss','-ltnp']),'docker':cmd(['docker','version','--format','{{.Server.Version}}']),'services':cmd(['docker','ps','--format','{{.Names}}\t{{.Ports}}']),'existingInstall':Path('/opt/lean-observatory').exists()}
report['resourceGate']=report['cpuCount']>=64 and mem['MemTotal']>=240*1024**3 and disk.free>=200*1024**3 and '24.04' in report['os']
print(json.dumps(report))
'''


def inspect(target):
    require_local_gate()
    if not re.fullmatch(r'[a-zA-Z0-9_.@:-]+',target) or target.startswith('-'): raise ValueError('无效 SSH 目标')
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15',target,"python3 - <<'PY'\n"+REMOTE+"\nPY"],capture_output=True,text=True,check=True)
    report=json.loads(result.stdout)
    path=ROOT/'reports/server-preflight.json';path.write_text(json.dumps(report,indent=2))
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--target',required=True);a=p.parse_args()
    result=inspect(a.target);print(json.dumps(result,indent=2));raise SystemExit(0 if result['resourceGate'] else 1)
