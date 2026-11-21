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
 try:
  p=subprocess.run(a,capture_output=True,text=True,timeout=30);return {'exitCode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
 except FileNotFoundError: return {'exitCode':127,'stdout':'','stderr':'not installed: '+a[0]}
 except subprocess.TimeoutExpired: return {'exitCode':124,'stdout':'','stderr':'timed out: '+a[0]}
mem={x.split(':')[0]:int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines()}
disk=shutil.disk_usage('/var/lib' if Path('/var/lib').exists() else '/')
report={'os':Path('/etc/os-release').read_text(),'kernel':platform.release(),'architecture':platform.machine(),'cpuCount':os.cpu_count(),'memoryBytes':mem['MemTotal'],'availableMemoryBytes':mem['MemAvailable'],'diskTotalBytes':disk.total,'diskFreeBytes':disk.free,'ports':cmd(['ss','-H','-ltnp']),'docker':cmd(['docker','version','--format','{{.Server.Version}}']),'compose':cmd(['docker','compose','version','--short']),'services':cmd(['docker','ps','--format','{{.Names}}\t{{.Ports}}']),'existingInstall':Path('/opt/lean-observatory').exists() or Path('/opt/lean-observatory').is_symlink()}
report['canAdmin']=os.geteuid()==0 or cmd(['sudo','-n','true'])['exitCode']==0
report['listeningPorts']=sorted({int(line.split()[3].rsplit(':',1)[1]) for line in report['ports']['stdout'].splitlines() if len(line.split())>3 and line.split()[3].rsplit(':',1)[-1].isdigit()})
report['resourceGate']=report['cpuCount']>=64 and mem['MemTotal']>=240*1024**3 and disk.free>=500*1024**3 and '24.04' in report['os'] and report['architecture']=='x86_64'
report['portGate']=report['ports']['exitCode']==0 and not ({80,443}&set(report['listeningPorts']))
report['deployGate']=report['resourceGate'] and report['portGate'] and report['canAdmin'] and not report['existingInstall']
print(json.dumps(report))
'''


def inspect(target):
    require_local_gate()
    if not re.fullmatch(r'[a-zA-Z0-9_.@:-]+',target) or target.startswith('-'): raise ValueError('无效 SSH 目标')
    known_hosts=ROOT/'.data/ssh_known_hosts';known_hosts.parent.mkdir(exist_ok=True)
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15','-o','StrictHostKeyChecking=accept-new','-o','UserKnownHostsFile='+str(known_hosts),target,"python3 - <<'PY'\n"+REMOTE+"\nPY"],capture_output=True,text=True,check=True)
    report=json.loads(result.stdout);report['target']=target
    path=ROOT/'reports/server-preflight.json';path.write_text(json.dumps(report,indent=2))
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--target',required=True);a=p.parse_args()
    result=inspect(a.target);print(json.dumps(result,indent=2));raise SystemExit(0 if result['deployGate'] else 1)
