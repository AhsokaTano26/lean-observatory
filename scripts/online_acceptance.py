#!/usr/bin/env python3
"""Read-only, CA-verified production acceptance. Never queues proof work."""
import argparse
import hashlib
import json
import math
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode, urlsplit

if __package__:
    from .gates import ROOT, fingerprint, require_local_gate
else:
    from gates import ROOT, fingerprint, require_local_gate

URL='https://lean.tano.asia'
CHECKS=('tls','source','resources','metrics','clean','readOnly','methods','sse')
GIB=1024**3
APPARMOR_PROFILE="lean-observatory-worker"


def validate_url(url):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname!='lean.tano.asia' or parsed.port not in (None,443) or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:
        raise ValueError('acceptance requires the exact production HTTPS origin')


def validate_state(data, runs, source_sha, now=None, resume_run=None):
    now=time.time() if now is None else now
    if not re.fullmatch('[0-9a-f]{64}',source_sha) or data.get('deployment',{}).get('sourceSha256')!=source_sha:
        raise ValueError('deployed source fingerprint mismatch')
    if data.get('capabilities',{}).get('readOnly') is not True:
        raise ValueError('readOnly capability missing')
    run=data.get('run',{})
    if resume_run is None:
        if runs!=[] or 'id' not in run or run['id'] is not None or run.get('mode')!='real' or run.get('status')!='waiting' or run.get('commands')!=[] or run.get('artifacts')!=[]:
            raise ValueError('clean production data volume required; no mock history or active task')
    else:
        if not re.fullmatch('[A-Za-z0-9_-]{1,64}',resume_run) or not isinstance(runs,list):
            raise ValueError('invalid resume run')
        stopped={'paused','interrupted','failed','resource_exhausted'}
        matches=[item for item in runs if item.get('id')==resume_run]
        if run.get('id')!=resume_run or run.get('mode')!='real' or run.get('status') not in stopped or len(matches)!=1 or matches[0].get('status')!=run.get('status'):
            raise ValueError('resume requires the exact stopped real run')
        if any(item.get('mode')!='real' or (item.get('id')!=resume_run and item.get('status') in {'queued','running','paused'}) for item in runs):
            raise ValueError('resume requires no mock history or other active run')
    m=data.get('metrics',{})
    stamp=m.get('sampledAt')
    if m.get('source')!='host_agent' or m.get('stale') is not False or type(stamp) not in (int,float) or not -60<=now-stamp<20:
        raise ValueError('fresh host_agent metrics required')
    for key,minimum in [('cpuCount',64),('memoryTotalBytes',240*GIB),('diskTotalBytes',500*GIB)]:
        if type(m.get(key)) not in (int,float) or not math.isfinite(m[key]) or m[key]<minimum:
            raise ValueError('insufficient host resource: '+key)
    used=m.get('diskUsedBytes')
    if type(used) not in (int,float) or not math.isfinite(used) or used<0 or used>m['diskTotalBytes'] or m['diskTotalBytes']-used<500*GIB:
        raise ValueError('at least 500 GiB free host disk required')
    return data


def validate_resources(containers, source_sha):
    services={}
    for c in containers:
        labels=c.get('Config',{}).get('Labels',{})
        if labels.get('com.docker.compose.project')!='lean-observatory':
            raise ValueError('unexpected Compose project')
        name=labels.get('com.docker.compose.service')
        if name in services: raise ValueError('duplicate Compose service')
        services[name]=c
    if set(services)!={'api','nginx','worker'}: raise ValueError('only api, nginx and verification worker must run')
    for name,cpus,memory in [('api',2,2*GIB),('nginx',1,256*1024**2),('worker',60,250000000000)]:
        c=services[name];h=c.get('HostConfig',{})
        if c.get('State',{}).get('Running') is not True or h.get('NanoCpus')!=cpus*10**9 or h.get('Memory')!=memory:
            raise ValueError('container resource limits mismatch: '+name)
        if name in ('api','worker'):
            if c.get('ImageLabels',{}).get('io.lean-observatory.source-sha256')!=source_sha:
                raise ValueError('built image source mismatch: '+name)
            env=dict(item.split('=',1) for item in c['Config'].get('Env',[]) if '=' in item)
            if env.get('SOURCE_SHA256')!=source_sha: raise ValueError('container source mismatch: '+name)
            if name=='worker':
                if c.get('AppArmorProfile')!=APPARMOR_PROFILE:
                    raise ValueError('production worker requires the exact enforcing AppArmor profile')
                if env.get('ENABLE_REAL')!='0' or h.get('CpusetCpus')!='4-63' or h.get('MemorySwap')!=250000000000 or h.get('PidsLimit')!=1024:
                    raise ValueError('worker must stay disabled with bounded CPUs, RAM, swap and processes')
                if not any(m.get('Destination')=='/approval' and m.get('RW') is False for m in c.get('Mounts',[])):
                    raise ValueError('worker receipt mount must be read-only')
    return services


def validate_apparmor(enabled, loaded_profiles, expected_sha, installed_sha):
    if enabled.strip()!='Y' or APPARMOR_PROFILE+' (enforce)' not in loaded_profiles.splitlines():
        raise ValueError('AppArmor must be enabled and the worker profile loaded in enforce mode')
    if not re.fullmatch('[0-9a-f]{64}',expected_sha) or installed_sha!=expected_sha:
        raise ValueError('installed AppArmor profile differs from the accepted source')


def inspect_host_apparmor(root):
    source=root/'deploy/lean-observatory-worker.apparmor'
    installed=Path('/etc/apparmor.d/lean-observatory-worker')
    expected=hashlib.sha256(source.read_bytes()).hexdigest()
    if installed.is_symlink():raise ValueError('installed AppArmor profile may not be a symlink')
    validate_apparmor(Path('/sys/module/apparmor/parameters/enabled').read_text(),
                      Path('/sys/kernel/security/apparmor/profiles').read_text(),expected,
                      hashlib.sha256(installed.read_bytes()).hexdigest())
    return expected


def validate_worker_fixture(receipt, source_sha, script_sha, profile_sha, worker, now=None):
    now=time.time() if now is None else now
    stamp=receipt.get('checkedAt')
    required={'passed':True,'productionEligible':False,'environment':'production-worker-profile','scope':'tiny-only',
              'sourceSha256':source_sha,'scriptSha256':script_sha,'profileSha256':profile_sha,
              'AppArmorProfile':APPARMOR_PROFILE,'workerContainerId':worker.get('Id'),
              'workerImageId':worker.get('Image'),'proofReproduction':'NOT_RUN','exitCode':0}
    if any(receipt.get(key)!=value for key,value in required.items()) or receipt.get('passed') is not True or receipt.get('productionEligible') is not False:
        raise ValueError('worker fixture must pass under the exact production AppArmor profile, source, script and container')
    if type(stamp) not in (int,float) or not -60<=now-stamp<=900 or not re.fullmatch('[0-9a-f]{64}',receipt.get('logSha256','')):
        raise ValueError('worker fixture is stale or lacks its evidence hash')
    return receipt


def validate_fixture_output(raw):
    text=raw.decode('utf-8')
    summaries=[]
    for match in re.finditer(r'(?m)^\{',text):
        try:summary,_=json.JSONDecoder().raw_decode(text[match.start():])
        except ValueError:continue
        if isinstance(summary,dict) and 'kernelFixture' in summary:summaries.append(summary)
    if len(summaries)!=1 or any(summaries[0].get(key)!='passed' for key in ('kernelFixture','filesystemIsolation','detachedCleanup')) or summaries[0].get('proofReproduction')!='NOT_RUN' or 'parent-death guard passed (including stopped process group)' not in text:
        raise ValueError('tiny worker fixture did not report all required isolation checks')


def write_json_atomic(output, value):
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.parent.is_symlink() or output.is_symlink() or output.parent.stat().st_uid!=0:
        raise ValueError('approval path must be root-owned and may not be a symlink')
    os.chmod(output.parent,0o755)
    temp=output.with_name(output.name+'.tmp')
    with temp.open('x') as stream:
        os.chmod(temp,0o644);json.dump(value,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    temp.replace(output)


def run_worker_fixture(root=ROOT):
    root=Path(root).resolve();require_local_gate(root)
    if os.geteuid()!=0:raise ValueError('production fixture must run as root on the deployment host')
    sha=fingerprint(root);profile_sha=inspect_host_apparmor(root)
    services=validate_resources(inspect_resources(root),sha);worker=services['worker']
    script=(root/'scripts/container_smoke.py').read_bytes();script_sha=hashlib.sha256(script).hexdigest()
    # This tiny test uses temporary evidence, never the production task ledger.
    prefix=b"import sys\nif sys.flags.optimize: raise RuntimeError('fixture assertions must be enabled')\n"
    command=['docker','compose','-p','lean-observatory','-f',str(root/'compose.yaml'),'-f',str(root/'compose.tls.yaml'),'--profile','verification','exec','-T','worker','python3','-']
    result=subprocess.run(command,cwd=root,input=prefix+script,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=300)
    output=root/'.data/approval/worker-fixture.json';log=output.with_suffix('.log')
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.parent.is_symlink() or output.parent.stat().st_uid!=0 or log.is_symlink():raise ValueError('fixture evidence directory must be root-owned')
    with log.open('wb') as stream:
        os.chmod(log,0o644);stream.write(result.stdout);stream.flush();os.fsync(stream.fileno())
    passed=result.returncode==0
    try:validate_fixture_output(result.stdout)
    except ValueError:passed=False
    receipt={'passed':passed,'productionEligible':False,'environment':'production-worker-profile','scope':'tiny-only',
             'checkedAt':time.time(),'sourceSha256':sha,'scriptSha256':script_sha,'profileSha256':profile_sha,
             'AppArmorProfile':worker['AppArmorProfile'],'workerContainerId':worker['Id'],'workerImageId':worker['Image'],
             'proofReproduction':'NOT_RUN','exitCode':result.returncode,'logSha256':hashlib.sha256(result.stdout).hexdigest()}
    if fingerprint(root)!=sha:raise ValueError('source changed during tiny worker fixture')
    current=validate_resources(inspect_resources(root),sha)['worker']
    if current.get('Id')!=worker['Id'] or current.get('Image')!=worker['Image']:raise ValueError('worker changed during fixture')
    write_json_atomic(output,receipt)
    validate_worker_fixture(receipt,sha,script_sha,profile_sha,current)
    return receipt


def validate_method(status, headers):
    if status!=405 or headers.get('Allow')!='GET': raise ValueError('HTTP mutation must return 405 Allow: GET')


def validate_sse(content_type, packet, source_sha, now=None, resume_run=None, runs=None):
    if content_type.split(';')[0].strip()!='text/event-stream': raise ValueError('SSE content type missing')
    lines=packet.decode('utf-8').replace('\r\n','\n').splitlines()
    if 'event: snapshot' not in lines: raise ValueError('SSE snapshot missing')
    raw='\n'.join(line[5:].lstrip() for line in lines if line.startswith('data:'))
    data=json.loads(raw)
    validate_state(data,[] if runs is None else runs,source_sha,now=now,resume_run=resume_run)
    return data


class ProductionHTTP:
    """Every request verifies the public CA chain and exact origin, including redirects."""
    def __init__(self, url):
        validate_url(url)
        self.url=url.rstrip('/')
        self.context=ssl.create_default_context()

    def open(self, path, method='GET', data=None):
        request=urllib.request.Request(self.url+path,data=data,method=method)
        if data is not None: request.add_header('Content-Type','application/json')
        try: response=urllib.request.urlopen(request,timeout=15,context=self.context)
        except urllib.error.HTTPError as error: response=error
        parsed=urlsplit(response.url)
        if parsed.scheme!='https' or parsed.hostname!='lean.tano.asia' or parsed.port not in (None,443):
            response.close();raise ValueError('response redirected outside verified production origin')
        return response

    def json(self,path):
        with self.open(path) as r:
            if r.status!=200: raise ValueError('GET failed: '+path)
            return json.load(r)


def inspect_resources(root):
    command=['docker','compose','-p','lean-observatory','-f',str(root/'compose.yaml'),'-f',str(root/'compose.tls.yaml'),'--profile','verification','ps','-a','-q']
    ids=subprocess.run(command,cwd=root,check=True,capture_output=True,text=True,timeout=30).stdout.split()
    if not ids: raise ValueError('deployed Compose containers absent')
    result=subprocess.run(['docker','inspect',*ids],check=True,capture_output=True,text=True,timeout=30)
    containers=json.loads(result.stdout)
    images=subprocess.run(['docker','image','inspect',*sorted({c['Image'] for c in containers})],check=True,capture_output=True,text=True,timeout=30)
    labels={image['Id']:image.get('Config',{}).get('Labels') or {} for image in json.loads(images.stdout)}
    for container in containers: container['ImageLabels']=labels.get(container['Image'],{})
    return containers


def run_acceptance(root=ROOT, url=URL, output=None, resume_run=None):
    root=Path(root).resolve();output=Path(output) if output else root/'.data/approval/online.json'
    validate_url(url);require_local_gate(root)
    sha=fingerprint(root)
    if os.geteuid()!=0: raise ValueError('receipt must be generated by the deployment assistant as root')
    client=ProductionHTTP(url)
    with client.open('/healthz') as response:
        if response.status!=200 or json.load(response).get('service')!='lean-observatory': raise ValueError('wrong HTTPS service')
    query='?'+urlencode({'run':resume_run}) if resume_run is not None else ''
    data=client.json('/api/state'+query);runs=client.json('/api/runs');validate_state(data,runs,sha,resume_run=resume_run)
    fixture=run_worker_fixture(root)
    services=validate_resources(inspect_resources(root),sha)
    fixture_path=root/'.data/approval/worker-fixture.json'
    saved_fixture=json.loads(fixture_path.read_text())
    validate_worker_fixture(saved_fixture,sha,hashlib.sha256((root/'scripts/container_smoke.py').read_bytes()).hexdigest(),inspect_host_apparmor(root),services['worker'])
    if hashlib.sha256(fixture_path.with_suffix('.log').read_bytes()).hexdigest()!=saved_fixture['logSha256']:
        raise ValueError('worker fixture evidence changed')
    with client.open('/') as response:
        if response.status!=200 or 'text/html' not in response.headers.get('Content-Type','') or not response.read(1024): raise ValueError('public page missing')
    report=client.json('/api/report.json'+query);validate_state(report,runs,sha,resume_run=resume_run)
    # Invalid values are intentional: even an older write-enabled service cannot create work.
    body=json.dumps({'mode':'invalid-acceptance-mode','run':'invalid-acceptance-run','action':'invalid-acceptance-action','jobs':0}).encode()
    for path in ('/api/runs','/api/control'):
        for method in ('POST','PUT','PATCH','DELETE'):
            with client.open(path,method,body) as response: validate_method(response.status,response.headers)
    with client.open('/api/events'+query) as response:
        if response.status!=200: raise ValueError('SSE request failed')
        packet=bytearray()
        while len(packet)<1024*1024:
            line=response.readline(65536)
            if not line: raise ValueError('SSE disconnected before first snapshot')
            packet.extend(line)
            if line in (b'\n',b'\r\n'): break
        else: raise ValueError('SSE initial packet exceeds limit')
        validate_sse(response.headers.get('Content-Type',''),bytes(packet),sha,resume_run=resume_run,runs=runs)
    validate_state(client.json('/api/state'+query),client.json('/api/runs'),sha,resume_run=resume_run)
    if fingerprint(root)!=sha: raise ValueError('source changed during acceptance')
    receipt={'passed':True,'productionEligible':True,'checkedAt':time.time(),'sourceSha256':sha,'url':URL,
             'checks':dict.fromkeys(CHECKS,True),'host':data['metrics'].get('hostname'),
             'note':'CA-verified production inspection; no proof work started','AppArmorProfile':APPARMOR_PROFILE,'workerFixture':fixture}
    if resume_run is not None:receipt['resumeRun']=resume_run
    write_json_atomic(output,receipt)
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default=URL);parser.add_argument('--output',type=Path)
    parser.add_argument('--resume-run',help='Refresh acceptance only for this stopped real run; preserves history')
    parser.add_argument('--worker-fixture-only',action='store_true',help='Run only the tiny fixture in the exact production AppArmor worker')
    args=parser.parse_args()
    try:
        if args.worker_fixture_only and (args.resume_run or args.output):raise ValueError('fixture-only may not generate an online authorization receipt')
        result=run_worker_fixture() if args.worker_fixture_only else run_acceptance(url=args.url,output=args.output,resume_run=args.resume_run)
        print(json.dumps(result,indent=2))
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        print('Online acceptance rejected: '+str(error),file=sys.stderr);return 1
    return 0

if __name__=='__main__': raise SystemExit(main())
