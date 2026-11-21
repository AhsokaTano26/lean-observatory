"""Reproduce the original submission without importing published project artifacts."""
import hashlib
import json
import os
import platform
import re
import shutil
import time
import tomllib
from pathlib import Path
from .model import EXPECTED_HASH, EXPECTED_BYTES, MATHLIB, THEOREMS, audit_axioms
from .integrity import sha256, verify_archive, safe_extract
from .runner import CommandRunner, CommandError


def validate_project(root, expected_count=175187):
    root=Path(root)
    if (root/'lean-toolchain').read_text().strip() != 'leanprover/lean4:v4.33.1':
        raise ValueError('Lean 工具链与指定 v4.33.1 不匹配')
    cfg=tomllib.loads((root/'lakefile.toml').read_text())
    dep=next((x for x in cfg.get('require',[]) if x.get('name')=='mathlib'),None)
    if not dep or dep.get('rev')!=MATHLIB or dep.get('git','').rstrip('/').removesuffix('.git')!='https://github.com/leanprover-community/mathlib4':
        raise ValueError('原始 Mathlib 依赖配置不匹配')
    manifest=json.loads((root/'lake-manifest.json').read_text())
    pinned=next((x for x in manifest.get('packages',[]) if x.get('name')=='mathlib'),None)
    if not pinned or pinned.get('rev')!=MATHLIB: raise ValueError('Mathlib manifest 锁定版本不匹配')
    src=(root/cfg.get('srcDir','.')).resolve()
    if not src.is_relative_to(root.resolve()): raise ValueError('srcDir 越界')
    files=sorted(src.rglob('*.lean'))
    files=[p for p in files if '.lake' not in p.relative_to(src).parts]
    if len(files)!=expected_count: raise ValueError(f'源码数量不匹配: {len(files)} != {expected_count}')
    modules={'.'.join(p.relative_to(src).with_suffix('').parts) for p in files}
    if 'Main' not in modules: raise ValueError('缺少 Main 模块')
    return dict(src=src, files=files, modules=modules, config=cfg)


def audit_source(src):
    pattern=re.compile(r'\b(sorry|admit|axiom|native_decide|unsafe|implemented_by|extern|run_elab|elab|initialize|set_option\s+debug\.skipKernelTC)\b')
    findings=[]
    for p in sorted(Path(src).rglob('*.lean')):
        for number,line in enumerate(p.read_text().splitlines(),1):
            for m in pattern.finditer(line):
                findings.append(dict(file=str(p.relative_to(src)),line=number,token=m[0],text=line[:500]))
    return findings


def parse_build_module(line, modules):
    match=re.search(r'\bBuilt\s+([A-Za-z_][A-Za-z0-9_.\u0080-\uffff]*)\s*(?:\(|$)',line)
    return match[1] if match and match[1] in modules else None


def audit_program():
    lines=['import Main', 'set_option pp.universes true']
    for name,typ in THEOREMS:
        lines += [f'example : {typ} := {name}',f'#check {name}',f'#print {name}',f'#print axioms {name}']
    # Capture definitions too. A name of a Prop alone does not establish its mathematical meaning.
    lines += [f'#print {t}' for _,t in THEOREMS]
    return '\n'.join(lines)+'\n'


class Pipeline:
    def __init__(self, store, run):
        self.store=store; self.id=run; self.root=store.root/'runs'/run
        self.runner=CommandRunner(store,run)
        self.project=self.root/'source'/'lean'
        self.config_hashes={}

    def evidence(self, name, value, text=False):
        path=self.root/name
        path.write_text(value if text else json.dumps(value,ensure_ascii=False,indent=2))
        self.register(path)

    def register(self, path):
        entry=dict(name=path.name,bytes=path.stat().st_size,sha256=sha256(path))
        def add(s):
            s['artifacts']=[a for a in s['artifacts'] if a['name']!=entry['name']]+[entry]
        self.store.mutate(self.id,add)

    def checkpoint(self):
        s=self.store.raw(self.id)
        while s['desired']=='paused':
            self.store.mutate(self.id,lambda x:x.update(status='paused',workerHeartbeat=time.time()))
            time.sleep(1); s=self.store.raw(self.id)
        if s['desired']=='cancelled': raise CommandError('cancelled',-15)
        self.store.mutate(self.id,lambda x:x.update(status='running',workerHeartbeat=time.time()))

    def stage(self, name, action):
        self.checkpoint()
        s=self.store.raw(self.id); prior=next(x for x in s['stages'] if x['id']==name)
        if prior['status']=='passed': return
        def start(s):
            s.update(phase=name,error=None)
            next(x for x in s['stages'] if x['id']==name).update(status='running',startedAt=time.time(),finishedAt=None,exitCode=None)
        self.store.mutate(self.id,start,'stage_started')
        self.store.log(self.id,'info','阶段开始: '+name,name)
        action()
        def finish(s):
            next(x for x in s['stages'] if x['id']==name).update(status='passed',finishedAt=time.time(),exitCode=0)
        self.store.mutate(self.id,finish,'stage_finished')

    def download(self):
        if shutil.disk_usage(self.root).free < 200*1024**3: raise CommandError('可用磁盘不足 200 GiB',137)
        parts=[]
        for i in range(1,15):
            self.checkpoint(); part=self.root/f'lean.tar.gz.part{i:02}'
            size=18000000 if i<14 else 5275554
            if not part.exists() or part.stat().st_size!=size:
                self.runner.run(['curl','--fail','--location','--retry','5','--connect-timeout','30','--max-time','900','--output',str(part),f'https://alpo.ge/{part.name}'],self.root,'download')
            if part.stat().st_size!=size: raise ValueError(f'{part.name}: 大小错误，拒绝 HTTP 200 伪文件')
            parts.append(dict(name=part.name,bytes=size,sha256=sha256(part)))
            self.store.log(self.id,'info',f'原始分卷 {i}/14 已下载并记录 SHA-256','download')
        archive=self.root/'lean.tar.gz'
        with archive.open('wb') as out:
            for part in parts:
                with (self.root/part['name']).open('rb') as f: shutil.copyfileobj(f,out,1024**2)
        self.evidence('parts.json',parts)

    def integrity(self):
        archive=self.root/'lean.tar.gz'; digest=verify_archive(archive,EXPECTED_HASH,EXPECTED_BYTES)
        self.store.mutate(self.id,lambda s:s['provenance'].update(sha256=digest,bytes=archive.stat().st_size,integrity='passed'))
        self.register(archive)
        destination=self.root/'source'
        if not self.project.exists(): safe_extract(archive,destination)
        info=validate_project(self.project)
        self.config_hashes={n:sha256(self.project/n) for n in ['lean-toolchain','lakefile.toml','lake-manifest.json']}
        inventory=self.root/'source-files.sha256'
        with inventory.open('w') as out:
            for i,p in enumerate(info['files']):
                if i%1000==0: self.checkpoint()
                out.write(f'{sha256(p)}  {p.relative_to(self.project)}\n')
        self.register(inventory)
        self.evidence('original-config.json',self.config_hashes)
        self.store.mutate(self.id,lambda s:(s['compile'].update(total=len(info['files'])),s['provenance'].update(inventorySha256=sha256(inventory))))

    def unchanged(self):
        hashes=json.loads((self.root/'original-config.json').read_text())
        if any(sha256(self.project/n)!=h for n,h in hashes.items()):
            raise ValueError('原始依赖配置发生变化；拒绝继续')

    def dependencies(self):
        self.unchanged()
        output=self.runner.run(['lake','env','lean','--version'],self.project,'dependencies')
        if not re.search(r'\bversion 4\.33\.1\b',output): raise ValueError('实际 Lean 二进制版本不匹配')
        # Qualified Mathlib executable cannot accidentally fetch root project artifacts.
        self.runner.run(['lake','exe','mathlib/cache','get'],self.project,'dependencies')
        actual=self.runner.run(['git','-C',str(self.project/'.lake/packages/mathlib'),'rev-parse','HEAD'],self.project,'dependencies').strip()
        if actual!=MATHLIB: raise ValueError('实际 Mathlib checkout 版本不匹配')
        self.unchanged()
        self.store.mutate(self.id,lambda s:s['environment'].update(actualLean=output,actualMathlib=actual,platform=platform.platform(),python=platform.python_version()))

    def compile(self):
        self.unchanged(); info=validate_project(self.project); jobs=self.store.raw(self.id)['compile']['jobs']
        # Preserve original configuration bytes and record the sole runtime-only override.
        original=(self.project/'lakefile.toml').read_text()
        pattern=re.compile(r'(?m)^moreLeanArgs\s*=\s*\[([^\]]*)\]')
        if pattern.search(original): effective=pattern.sub(lambda m:'moreLeanArgs = ['+m[1]+', "-j1"]',original,count=1)
        else: effective='moreLeanArgs = ["-j1"]\n'+original
        effective_file=self.project/'observatory-lakefile.toml'; effective_file.write_text(effective)
        self.evidence('effective-lakefile.toml',effective,text=True)
        self.store.log(self.id,'info',f'原始配置保持不变；运行配置仅追加 -j1；Lake 调度线程 {jobs}；Compose 硬限额 CPU/内存','compile')
        os.environ['LEAN_NUM_THREADS']=str(jobs)
        def refresh_artifacts():
            for path in (self.project/'.lake/build/lib/lean').rglob('*.olean'):
                name='.'.join(path.relative_to(self.project/'.lake/build/lib/lean').with_suffix('').parts)
                if name in info['modules']: self.store.module_done(self.id,name)
        refresh_artifacts(); times=[]; last_flush=[0.]
        def line(text):
            name=parse_build_module(text,info['modules']); now=time.time()
            if name and self.store.module_done(self.id,name): times.append(now)
            times[:]=[t for t in times if now-t<60]
            if name and now-last_flush[0]>=.8:
                count=self.store.module_count(self.id)
                self.store.mutate(self.id,lambda s:s['compile'].update(succeeded=count,rate=round(len(times)/min(60,max(1,now-start)),2),currentModule=name))
                last_flush[0]=now
        start=time.time()
        self.runner.run(['lake','--no-ansi','--no-cache','-f',effective_file.name,'build'],self.project,'compile',line)
        refresh_artifacts(); count=self.store.module_count(self.id)
        self.store.mutate(self.id,lambda s:s['compile'].update(succeeded=count,failed=0,rate=0))
        if count!=len(info['modules']): raise ValueError(f'编译产物覆盖不足: {count}/{len(info["modules"])}')
        self.unchanged()

    def audit(self):
        info=validate_project(self.project); findings=audit_source(info['src'])
        self.evidence('source-scan.json',findings)
        if findings: raise ValueError(f'静态扫描发现 {len(findings)} 个潜在绕过点，需人工复核；不自动判定通过')
        file=self.root/'Audit.lean'; file.write_text(audit_program()); self.register(file)
        output=self.runner.run(['lake','env','lean','-j1',str(file)],self.project,'audit')
        self.evidence('audit-output.txt',output,text=True)
        passed=True
        for name,_ in THEOREMS:
            result=audit_axioms(output,name); passed=passed and result['passed']
            def update(s):
                a=next(a for a in s['audits'] if a['name']==name)
                a.update(type='passed',axioms='passed' if result['passed'] else 'failed',dependencies=result['dependencies'],output=result['error'])
            self.store.mutate(self.id,update)
        if not passed: raise ValueError('公理审计未通过或输出缺失')

    def replay(self):
        self.unchanged()
        self.runner.run(['lake','env','leanchecker','--fresh','Main'],self.project,'replay')
        self.store.mutate(self.id,lambda s:[a.update(replay='passed') for a in s['audits']])

    def run(self):
        try:
            # Resume revalidates bytes/configuration instead of trusting a completion marker.
            state=self.store.raw(self.id)
            if state['stages'][1]['status']=='passed':
                verify_archive(self.root/'lean.tar.gz',EXPECTED_HASH,EXPECTED_BYTES)
                validate_project(self.project); self.unchanged()
                for line in (self.root/'source-files.sha256').read_text().splitlines():
                    digest,name=line.split('  ',1)
                    if sha256(self.project/name)!=digest: raise ValueError('恢复时发现源码发生变化: '+name)
            for name in ['download','integrity','dependencies','compile','audit','replay']:
                self.stage(name,getattr(self,name))
            self.store.mutate(self.id,lambda s:s.update(status='checks_completed',finishedAt=time.time(),error=None),'finished')
        except Exception as e:
            code=getattr(e,'code',1); raw=self.store.raw(self.id)
            status='cancelled' if raw['desired']=='cancelled' else ('resource_exhausted' if code in (137,-9) else ('interrupted' if code<0 else 'failed'))
            def fail(s):
                s.update(status=status,error=str(e),finishedAt=time.time())
                next(x for x in s['stages'] if x['id']==s['phase']).update(status=status,exitCode=code,finishedAt=time.time())
                s['compile']['rate']=0
            self.store.mutate(self.id,fail,'failed'); self.store.log(self.id,'error',str(e),raw['phase'])
        finally:
            for path in self.root.glob('command-*.log'): self.register(path)
            s=self.store.snapshot(self.id)
            self.evidence('verification-result.json',dict(run=s,generatedAt=time.time(),note='检查完成不代表数学陈述已人工复核。leanchecker 使用同一 Lean 内核；不同内核独立检查未执行。'))
