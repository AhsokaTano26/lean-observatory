#!/usr/bin/env python3
"""Live resource-only RH resize: no stop, restart, recreation or proof-file writes."""
import argparse
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path

NAME='lean-observatory-worker-1'
LIMITS={'NanoCpus':60*10**9,'CpusetCpus':'4-63','Memory':250000000000,'MemorySwap':250000000000}
OVERRIDE='services:\n  worker:\n    cpus: 60\n    cpuset: "4-63"\n    mem_limit: 250000000000\n    memswap_limit: 250000000000\n'


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def identity(row):
    return {'id':row['Id'],'pid':row['State']['Pid'],'startedAt':row['State']['StartedAt'],'image':row['Image'],
            'configSha256':digest(row['Config']),'mountsSha256':digest(row['Mounts'])}


def configure(expected_id,ops_dir,execute=False,executor=subprocess.run):
    def inspect():
        result=executor(['docker','inspect',expected_id],capture_output=True,text=True,check=True,timeout=15)
        row=json.loads(result.stdout)[0]
        labels=row['Config'].get('Labels',{})
        if row['Id']!=expected_id or row.get('Name')!='/'+NAME or labels.get('com.docker.compose.project')!='lean-observatory' or labels.get('com.docker.compose.service')!='worker' or row['State'].get('Running') is not True:
            raise ValueError('RH container identity changed; refusing update')
        return row
    before=inspect();command=['docker','update','--cpus','60','--cpuset-cpus','4-63','--memory','250000000000','--memory-swap','250000000000',expected_id]
    report={'dryRun':not execute,'command':command,'before':identity(before),'beforeLimits':{k:before['HostConfig'].get(k) for k in LIMITS}}
    if not execute:return report
    ops=Path(ops_dir);target=ops/'compose.resources.runtime.yaml'
    if ops.is_symlink() or target.is_symlink():raise ValueError('refusing symlinked operations path')
    if target.exists() and target.read_text()!=OVERRIDE:raise ValueError('existing resource override differs; refusing overwrite')
    if any(before['HostConfig'].get(k)!=v for k,v in LIMITS.items()):
        executor(command,capture_output=True,text=True,check=True,timeout=30)
    after=inspect()
    if identity(before)!=identity(after):raise RuntimeError('RH identity or configuration changed unexpectedly')
    if any(after['HostConfig'].get(k)!=v for k,v in LIMITS.items()):raise RuntimeError('resource limits did not apply')
    for key in before['HostConfig']:
        if key not in LIMITS and before['HostConfig'][key]!=after['HostConfig'].get(key):raise RuntimeError('unexpected HostConfig change: '+key)
    ops.mkdir(parents=True,exist_ok=True)
    if not target.exists():
        with target.open('x') as file:file.write(OVERRIDE)
        target.chmod(0o644)
    report.update(after=identity(after),afterLimits={k:after['HostConfig'][k] for k in LIMITS},identityPreserved=True)
    (ops/'resources-live-update.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--expected-id',required=True);parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    if args.execute and (platform.system()!='Linux' or os.geteuid()!=0):parser.error('execute requires root on Linux')
    print(json.dumps(configure(args.expected_id,'/opt/lean-observatory/.data/ops',args.execute),indent=2))


if __name__=='__main__':main()
