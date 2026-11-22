#!/usr/bin/env python3
"""Run local platform checks and bind their receipt to exact add-on source bytes."""
import datetime
import importlib.util
import json
import os
import py_compile
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def execution_environment(source=None):
    env=dict(os.environ if source is None else source)
    env.pop('NODE_TEST_CONTEXT',None)
    return env


def main():
    report_dir=ROOT/'reports/ns-local';report_dir.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('ns_installer',ROOT/'deploy/ns/install.py')
    installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
    before=installer.source_fingerprint(ROOT)
    manifest=json.loads((ROOT/'ns_queue/manifest.json').read_text())
    env={**execution_environment(),'NS_CONTAINER_NAME':'lean-observatory-ns-'+manifest['id'],
         'NS_RUN_ID':manifest['id'],'NS_SOURCE_COMMIT':manifest['commit']}
    commands={
        'unit':[sys.executable,'-m','unittest','discover','-s','tests','-q'],
        'resources':['node','--test','tests/resource-profile.test.mjs'],
        'charts':['node','--test','tests/chart-math.test.ts'],
        'browser':['node','--test','tests/ns-addon-browser.test.mjs'],
        'parallelBrowser':['node','--test','tests/ns-parallel-browser.test.mjs'],
        'sandboxPermissions':['node','--test','tests/ns-supervisor-permissions.test.mjs'],
        'leanAudit':['node','--test','tests/ns-audit-lean.test.mjs'],
        'entryBrowser':['node','--test','tests/entry-browser.test.mjs'],
        'sharedHTTPS':['node','--test','tests/shared-https-browser.test.mjs'],
        'rhBrowser':['node','node_modules/@playwright/test/cli.js','test'],
        'uiBuild':['npm','run','build'],
        'compose':['docker','compose','-f','compose.ns.yaml','-f','compose.ns-worker.yaml','config','--quiet'],
    }
    checks={}
    for name,command in commands.items():
        target=report_dir/(name+'.log')
        with target.open('w') as log:
            result=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=240)
        if '--test' in command and result.returncode==0:
            output=target.read_text()
            if 'skipping running files' in output or not re.search(r'tests\s+[1-9][0-9]*',output):
                raise RuntimeError('Node tests did not execute: '+name)
        checks[name]={'command':command,'exitCode':result.returncode,'log':str(target.relative_to(ROOT))}
        print(name+': '+str(result.returncode),flush=True)
        if result.returncode:print(target.read_text()[-10000:],flush=True);return result.returncode
    target=report_dir/'compile.log'
    with target.open('w') as log:
        for directory in ('ns_queue','deploy/ns'):
            for source in (ROOT/directory).rglob('*.py'):
                py_compile.compile(str(source),doraise=True);log.write(str(source.relative_to(ROOT))+' OK\n')
    checks['compile']={'command':['py_compile','ns_queue/**/*.py','deploy/ns/**/*.py'],'exitCode':0,'log':str(target.relative_to(ROOT))}
    if before!=installer.source_fingerprint(ROOT):raise RuntimeError('Source changed during acceptance')
    receipt={'schemaVersion':1,'createdAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'sourceSha256':before,'scope':'Local platform tests only; no real NS build or proof execution; no remote connection',
             'budgetCapUsd':0,'checks':checks,'execution':'NOT_RUN','proofAccepted':False,
             'browserNote':'Browser plugin unavailable; Playwright used; NS viewports 1440/390/320'}
    (ROOT/'reports/ns-local-acceptance.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('NS local acceptance receipt: '+before,flush=True)
    return 0


if __name__=='__main__':sys.exit(main())
