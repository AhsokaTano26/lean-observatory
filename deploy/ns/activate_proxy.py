#!/usr/bin/env python3
"""Add root entrance and /rh/, /ns/ routes by graceful reload, preserving RH jobs."""
import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
from pathlib import Path

NAME='lean-observatory-nginx-1'
NETWORK='lean-observatory-ns_default'
MARKER='# lean-observatory project routes'
UPSTREAM='  upstream observatory_ns { zone observatory_ns 64k; server lean-observatory-ns-api-1:8792 resolve; keepalive 8; }\n'
ROUTES='''    # lean-observatory project routes
    location = / { proxy_pass http://observatory_ns/entry; proxy_set_header Host $http_host; }
    location = /rh { return 308 /rh/$is_args$args; }
    location ^~ /rh/ {
      proxy_pass http://observatory/;
      proxy_http_version 1.1;
      proxy_set_header Host $http_host;
      proxy_set_header Connection "";
      proxy_buffering off;
      proxy_read_timeout 1h;
    }
    location = /ns { return 308 /ns/$is_args$args; }
    location ^~ /ns/ {
      proxy_pass http://observatory_ns;
      proxy_http_version 1.1;
      proxy_set_header Host $http_host;
      proxy_set_header Connection "";
      proxy_buffering off;
      proxy_cache off;
      proxy_read_timeout 1h;
      add_header X-Accel-Buffering no;
    }
'''
OVERRIDE='services:\n  nginx:\n    networks: [default, ns_addon]\nnetworks:\n  ns_addon:\n    external: true\n    name: lean-observatory-ns_default\n'


def sha(value):return hashlib.sha256(value).hexdigest()


def render(source):
    if MARKER in source:
        if all(s in source for s in ['server lean-observatory-api-1:8787 resolve',UPSTREAM.strip(),ROUTES.strip()]):return source
        raise ValueError('Existing project route differs; refusing overwrite')
    if re.search(r'location\s+(?:\^~\s+|=\s+)?/(?:ns|rh)(?:/|\s)',source):raise ValueError('Project path already in use')
    if source.count('server api:8787 resolve')+source.count('server lean-observatory-api-1:8787 resolve')!=1:raise ValueError('Unknown RH upstream')
    source=source.replace('server api:8787 resolve','server lean-observatory-api-1:8787 resolve')
    source=re.sub(r'(?m)^worker_processes\s+\S+;', 'worker_processes 1;',source)
    line=re.search(r'(?m)^\s*upstream observatory \{.*\}\s*$',source)
    location=re.search(r'(?m)^    location /api/events \{',source)
    if not line or not location:raise ValueError('Unknown TLS route layout')
    source=source[:location.start()]+ROUTES+source[location.start():]
    line=re.search(r'(?m)^\s*upstream observatory \{.*\}\s*$',source)
    return source[:line.end()]+'\n'+UPSTREAM+source[line.end():]


def identity(row):
    return {'id':row['Id'],'pid':row['State']['Pid'],'startedAt':row['State']['StartedAt'],
            'image':row['Image'],'configSha256':sha(json.dumps(row['Config'],sort_keys=True).encode()),
            'mountsSha256':sha(json.dumps(row.get('Mounts',[]),sort_keys=True).encode())}


def inplace(path,data):
    with path.open('r+b') as file:file.write(data);file.truncate();file.flush();os.fsync(file.fileno())


def activate(expected_id,config,ops_dir,execute=False,executor=subprocess.run):
    def run(argv,timeout=30):return executor(argv,capture_output=True,text=True,check=True,timeout=timeout)
    def inspect():
        row=json.loads(run(['docker','inspect',expected_id]).stdout)[0]
        labels=row['Config'].get('Labels',{})
        if row['Id']!=expected_id or row.get('Name')!='/'+NAME or labels.get('com.docker.compose.project')!='lean-observatory' or labels.get('com.docker.compose.service')!='nginx' or not row['State'].get('Running'):
            raise ValueError('RH router identity mismatch')
        return row
    before=inspect();config=Path(config);ops=Path(ops_dir)
    if config.is_symlink() or ops.is_symlink():raise ValueError('Symlinked configuration refused')
    original=config.read_bytes();candidate=render(original.decode()).encode()
    report={'dryRun':not execute,'before':identity(before),'oldConfigSha256':sha(original),'newConfigSha256':sha(candidate)}
    if not execute:return report
    ops.mkdir(parents=True,exist_ok=True)
    candidate_path=ops/('nginx-projects-'+sha(candidate)[:12]+'.conf');backup=ops/('nginx-before-projects-'+sha(original)[:12]+'.conf')
    for path,data in [(candidate_path,candidate),(backup,original)]:
        if path.is_symlink() or path.exists() and path.read_bytes()!=data:raise ValueError('Existing operation file changed')
        if not path.exists():path.write_bytes(data);path.chmod(0o644)
    # Syntax-only validation uses the original trusted image; no live server or
    # private key is copied and no existing service is restarted.
    run(['docker','run','--rm','--network','lean-observatory_default','--read-only','--cpus','0.2','--memory','64m','--pids-limit','32',
         '--tmpfs','/var/run','--tmpfs','/var/cache/nginx','--tmpfs','/tmp','--cap-drop','ALL','--cap-add','CHOWN',
         '-v',str(candidate_path)+':/etc/nginx/nginx.conf:ro','-v','/etc/letsencrypt:/etc/letsencrypt:ro',
         '--entrypoint','nginx',before['Image'],'-t'],60)
    if config.read_bytes()!=original:raise ValueError('Live configuration changed during validation')
    was_connected=NETWORK in before['NetworkSettings']['Networks'];connected=False;written=False
    try:
        inspect();inplace(config,candidate);written=True
        run(['docker','exec',expected_id,'nginx','-t'])
        # Unique RH hostname is active before a second network adds another api alias.
        run(['docker','exec',expected_id,'nginx','-s','reload'])
        if not was_connected:run(['docker','network','connect',NETWORK,expected_id]);connected=True
        after=inspect()
        if identity(before)!=identity(after):raise RuntimeError('Router process identity changed unexpectedly')
        if NETWORK not in after['NetworkSettings']['Networks']:raise RuntimeError('NS network attachment failed')
        override=ops/'compose.ns-route.runtime.yaml'
        if override.is_symlink() or override.exists() and override.read_text()!=OVERRIDE:raise ValueError('Route network override differs')
        if not override.exists():override.write_text(OVERRIDE);override.chmod(0o644)
        report.update(after=identity(after),network=NETWORK,networkAdded=not was_connected)
        (ops/'projects-route-update.json').write_text(json.dumps(report,indent=2)+'\n')
        return report
    except Exception:
        if not was_connected:
            try:connected=NETWORK in inspect()['NetworkSettings']['Networks']
            except Exception:pass
        if connected:run(['docker','network','disconnect',NETWORK,expected_id])
        if written and config.read_bytes()==candidate:
            inplace(config,original);run(['docker','exec',expected_id,'nginx','-t']);run(['docker','exec',expected_id,'nginx','-s','reload'])
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--expected-id');p.add_argument('--execute',action='store_true');a=p.parse_args()
    if a.execute and (os.geteuid()!=0 or platform.system()!='Linux'):p.error('execute requires root on Linux')
    row=json.loads(subprocess.check_output(['docker','inspect',a.expected_id or NAME],text=True))[0]
    mount=next(m for m in row['Mounts'] if m['Destination']=='/etc/nginx/nginx.conf')
    config=Path(mount['Source'])
    allowed=[Path('/opt/lean-observatory/.data/ops/nginx-tls.conf'),Path('/opt/lean-observatory/deploy/nginx-tls.conf')]
    if config not in allowed:raise SystemExit('Unknown RH Nginx mount; refusing modification')
    try:report=activate(a.expected_id or row['Id'],config,'/opt/lean-observatory/.data/ops',a.execute)
    except subprocess.CalledProcessError as error:raise SystemExit('Nginx validation/update failed: '+(error.stderr or str(error)))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
