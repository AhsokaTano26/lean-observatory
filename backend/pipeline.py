"""Reproduce the original submission without importing published project artifacts."""
import hashlib
import json
import os
import platform
import re
import shutil
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from .model import EXPECTED_HASH, EXPECTED_BYTES, MATHLIB, THEOREMS, audit_axioms
from .integrity import sha256, verify_archive, safe_extract
from .runner import CommandRunner, CommandError

@dataclass(frozen=True)
class Submission:
    # The worker and CLI always use this original submission. Alternative values
    # are injected only by the local integration fixture, never by HTTP/input files.
    archive_hash: str = EXPECTED_HASH
    archive_bytes: int = EXPECTED_BYTES
    file_count: int = 175187
    part_sizes: tuple = (18000000,)*13+(5275554,)
    origin: str = 'https://alpo.ge'
    min_free_bytes: int = 200*1024**3
    cache_targets: tuple = ()


def validate_project(root, expected_count=175187):
    root=Path(root)
    if (root/'lean-toolchain').read_text().strip() != 'leanprover/lean4:v4.33.1':
        raise ValueError('Lean 工具链与指定 v4.33.1 不匹配')
    cfg=tomllib.loads((root/'lakefile.toml').read_text())
    if (root/'lakefile.lean').exists(): raise ValueError('拒绝未审计的替代 lakefile.lean')
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


def audit_source(src, reviewed=None):
    if reviewed is None:
        policy=json.loads(Path(__file__).with_name('reviewed_extensions.json').read_text())
        if policy['expectedOriginalArchiveSha256']!=EXPECTED_HASH: raise ValueError('扩展审查对应其他原始归档')
        reviewed={f['sourceRelativePath']:f for f in policy['files'] if f['decision']=='approve_exact_bytes_for_pipeline_execution_only'}
    permitted={'macro','syntax','elab','run_tac','run_cmd','axioms'}
    pattern=re.compile(r'(?<![\w])(sorry|sorryAx|#eval|#reduce|macro|syntax|run_tac|run_cmd|eval_tactic|admit|axiom|axioms|native_decide|unsafe|implemented_by|extern|run_elab|elab|initialize|ofReduceBool|set_option\s+debug\.skipKernelTC)\b')
    findings=[]
    for p in sorted(Path(src).rglob('*.lean')):
        relative=str(p.relative_to(src));entry=reviewed.get(relative,{})
        exact=bool(entry) and sha256(p)==entry.get('sha256')
        accepted={(h['line'],h['token']) for h in entry.get('hits',[])}
        for number,line in enumerate(p.read_text().splitlines(),1):
            for m in pattern.finditer(line):
                approved=exact and m[0] in permitted and (number,m[0]) in accepted
                findings.append(dict(file=relative,line=number,token=m[0],text=line[:500],approved=approved,reason='已审阅扩展，原始字节完全匹配；仍需正常内核与公理检查' if approved else '未审阅、字节不匹配或禁止的绕过能力'))
    return findings


def parse_build_module(line, modules):
    match=re.search(r'\bBuilt\s+([A-Za-z_][A-Za-z0-9_.\u0080-\uffff]*)\s*(?:\(|$)',line)
    return match[1] if match and match[1] in modules else None


def parse_failed_module(line, modules):
    if not line.lstrip().startswith('✖'): return None
    match=re.search(r'\bBuilding\s+([A-Za-z_][A-Za-z0-9_.\u0080-\uffff]*)\s*(?:\(|$)',line)
    return match[1] if match and match[1] in modules else None


def audit_program():
    lines=['import Main', 'set_option pp.universes true']
    for name,typ in THEOREMS:
        lines += [f'example : {typ} := {name}',f'#check {name}',f'#print {name}',f'#print axioms {name}']
    # Capture definitions too. A name of a Prop alone does not establish its mathematical meaning.
    lines += [f'#print {t}' for _,t in THEOREMS]
    return '\n'.join(lines)+'\n'


class Pipeline:
    def __init__(self, store, run, submission=None):
        self.store=store; self.id=run; self.root=store.root/'runs'/run
        self.submission=submission or Submission()
        self.runner=CommandRunner(store,run)
        self.original=self.root/'source'/'lean'
        self.project=self.original
        self.config_hashes={}

    def execute(self, argv, stage, callback=None):
        if not os.environ.get('SANDBOX_ROOT'): raise RuntimeError('真实 Lean 执行必须启用隔离文件系统')
        return self.runner.run(argv,self.project,stage,callback,sandbox=True)

    def verify_sources(self):
        for line in (self.root/'source-files.sha256').read_text().splitlines():
            digest,name=line.split('  ',1)
            for base in {self.original,self.project}:
                if sha256(base/name)!=digest: raise ValueError('源码内容发生变化: '+name)

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
        if shutil.disk_usage(self.root).free < self.submission.min_free_bytes: raise CommandError('可用磁盘不足提交所需空间',137)
        parts=[]
        for i,size in enumerate(self.submission.part_sizes,1):
            self.checkpoint(); part=self.root/f'lean.tar.gz.part{i:02}'
            if not part.exists() or part.stat().st_size!=size:
                self.runner.run(['curl','--fail','--location','--retry','5','--connect-timeout','30','--max-time','900','--output',str(part),self.submission.origin+'/'+part.name],self.root,'download')
            if part.stat().st_size!=size: raise ValueError(f'{part.name}: 大小错误，拒绝 HTTP 200 伪文件')
            parts.append(dict(name=part.name,bytes=size,sha256=sha256(part)))
            self.store.log(self.id,'info',f'原始分卷 {i}/14 已下载并记录 SHA-256','download')
        archive=self.root/'lean.tar.gz'
        with archive.open('wb') as out:
            for part in parts:
                with (self.root/part['name']).open('rb') as f: shutil.copyfileobj(f,out,1024**2)
        self.evidence('parts.json',parts)

    def integrity(self):
        archive=self.root/'lean.tar.gz'
        try: digest=verify_archive(archive,self.submission.archive_hash,self.submission.archive_bytes)
        except ValueError as error:
            self.invalidate_download(str(error))
            raise
        self.store.mutate(self.id,lambda s:s['provenance'].update(sha256=digest,bytes=archive.stat().st_size,integrity='passed'))
        self.register(archive)
        destination=self.root/'source'; staging=self.root/'source.partial'
        # A directory's existence is never a completion marker. Publish extraction atomically.
        if staging.exists(): shutil.rmtree(staging)
        safe_extract(archive,staging)
        validate_project(staging/'lean',expected_count=self.submission.file_count)
        if destination.exists(): shutil.rmtree(destination)
        staging.rename(destination)
        info=validate_project(self.original,expected_count=self.submission.file_count)
        if (self.original/'.lake').exists(): raise ValueError('原始归档包含构建缓存，拒绝复现')
        findings=audit_source(info['src']); self.evidence('pre-execution-source-scan.json',findings)
        blocked=[f for f in findings if not f['approved']]
        self.evidence('reviewed-extension-policy.json',json.loads(Path(__file__).with_name('reviewed_extensions.json').read_text()))
        if blocked: raise ValueError(f'执行前扫描发现 {len(blocked)} 个未批准的潜在绕过点，停止执行')
        self.config_hashes={n:sha256(self.original/n) for n in ['lean-toolchain','lakefile.toml','lake-manifest.json']}
        inventory=self.root/'source-files.sha256'
        with inventory.open('w') as out:
            for i,p in enumerate(info['files']):
                if i%1000==0: self.checkpoint()
                out.write(f'{sha256(p)}  {p.relative_to(self.original)}\n')
        self.register(inventory)
        self.evidence('original-config.json',self.config_hashes)
        self.store.mutate(self.id,lambda s:(s['compile'].update(total=len(info['files'])),s['provenance'].update(inventorySha256=sha256(inventory))))

    def invalidate_download(self, reason):
        archive=self.root/'lean.tar.gz'
        self.evidence('rejected-download.json',dict(reason=reason,sha256=sha256(archive) if archive.exists() else None,bytes=archive.stat().st_size if archive.exists() else None,action='invalidate all untrusted parts; explicitly resume to download again'))
        for path in [archive,*self.root.glob('lean.tar.gz.part??')]: path.unlink(missing_ok=True)
        def reset(s):
            s['phase']='integrity'
            s['provenance'].update(sha256=None,bytes=None,integrity='failed')
            for stage in s['stages']:stage.update(status='pending',exitCode=None,finishedAt=None)
            for audit in s['audits']:audit.update(type='pending',axioms='pending',replay='pending')
        self.store.mutate(self.id,reset,'download_cache_invalidated')
        self.store.log(self.id,'error','归档校验失败；不可信分卷缓存已失效，显式恢复后重新下载。','integrity')

    def unchanged(self):
        hashes=json.loads((self.root/'original-config.json').read_text())
        if any(sha256(self.project/n)!=h for n,h in hashes.items()):
            raise ValueError('原始依赖配置发生变化；拒绝继续')

    def dependencies(self):
        self.unchanged()
        output=self.execute(['lake','-f','lakefile.toml','env','lean','--version'],'dependencies')
        if not re.search(r'\bversion 4\.33\.1\b',output): raise ValueError('实际 Lean 二进制版本不匹配')
        # Qualified Mathlib executable cannot accidentally fetch root project artifacts.
        self.execute(['lake','-f','lakefile.toml','exe','mathlib/cache','get',*self.submission.cache_targets],'dependencies')
        actual=self.execute(['git','-C','.lake/packages/mathlib','rev-parse','HEAD'],'dependencies').strip()
        if actual!=MATHLIB: raise ValueError('实际 Mathlib checkout 版本不匹配')
        self.unchanged()
        environment=json.loads(self.execute(['python3','-c',"import json,platform;from pathlib import Path;print(json.dumps(dict(platform=platform.platform(),python=platform.python_version(),osRelease=Path('/etc/os-release').read_text())))"],'dependencies'))
        toolchain=Path(os.environ['SANDBOX_ROOT'])/'home/lean/.elan/toolchains/leanprover--lean4---v4.33.1'
        environment['toolchainBinarySha256']={n:sha256(toolchain/'bin'/n) for n in ['lean','lake','leanchecker']}
        environment.update(actualLean=output,actualMathlib=actual)
        self.evidence('environment.json',environment)
        self.store.mutate(self.id,lambda s:s['environment'].update(environment))

    def compile(self):
        self.unchanged(); info=validate_project(self.project,expected_count=self.submission.file_count); jobs=self.store.raw(self.id)['compile']['jobs']
        if not self.store.raw(self.id)['compile'].get('startedFresh'):
            if any((self.project/'.lake/build').rglob('*.olean')):
                raise ValueError('首次编译发现已有项目 .olean，拒绝将外部产物计为本次编译')
            self.store.mutate(self.id,lambda s:s['compile'].update(startedFresh=True))
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
        refresh_artifacts(); times=[]; last_flush=[0.]; failed_modules=set()
        self.store.mutate(self.id,lambda s:s['compile'].update(failed=0,recent=[]))
        def line(text):
            failed=parse_failed_module(text,info['modules'])
            if failed:
                failed_modules.add(failed)
                self.store.mutate(self.id,lambda s:s['compile'].update(failed=len(failed_modules)))
            name=parse_build_module(text,info['modules']); now=time.time()
            if name and self.store.module_done(self.id,name): times.append(now)
            times[:]=[t for t in times if now-t<60]
            if name and now-last_flush[0]>=.8:
                count=self.store.module_count(self.id)
                self.store.mutate(self.id,lambda s:s['compile'].update(succeeded=count,rate=round(len(times)/min(60,max(1,now-start)),2),recent=list(times),currentModule=name))
                last_flush[0]=now
        start=time.time()
        self.execute(['lake','--no-ansi','--no-cache','-f',effective_file.name,'build'],'compile',line)
        refresh_artifacts(); count=self.store.module_count(self.id)
        self.store.mutate(self.id,lambda s:s['compile'].update(succeeded=count,failed=0,rate=0))
        if count!=len(info['modules']): raise ValueError(f'编译产物覆盖不足: {count}/{len(info["modules"])}')
        self.unchanged()
        self.verify_sources()

    def audit(self):
        info=validate_project(self.project,expected_count=self.submission.file_count); findings=audit_source(info['src'])
        self.evidence('source-scan.json',findings)
        blocked=[f for f in findings if not f['approved']]
        if blocked: raise ValueError(f'静态扫描发现 {len(blocked)} 个未批准的潜在绕过点，需人工复核；不自动判定通过')
        file=self.root/'Audit.lean'; file.write_text(audit_program()); self.register(file)
        audit_dir=self.project.parent/'audit';audit_dir.mkdir(exist_ok=True)
        (audit_dir/'Audit.lean').write_text(file.read_text())
        audit_path='/'+str(audit_dir.relative_to(Path(os.environ['SANDBOX_ROOT'])))
        output=self.execute(['lake','-f','lakefile.toml','env','lean','-j1',audit_path+'/Audit.lean'],'audit')
        self.evidence('audit-output.txt',output,text=True)
        axioms_file=self.root/'Axioms.lean'
        axioms_file.write_text('import Main\n'+'\n'.join(f'#print axioms {n}' for n,_ in THEOREMS)+'\n')
        self.register(axioms_file)
        (audit_dir/'Axioms.lean').write_text(axioms_file.read_text())
        axioms_output=self.execute(['lake','-f','lakefile.toml','env','lean','-j1',audit_path+'/Axioms.lean'],'audit')
        self.evidence('axioms-output.txt',axioms_output,text=True)
        passed=True
        for name,_ in THEOREMS:
            result=audit_axioms(axioms_output,name); passed=passed and result['passed']
            def update(s):
                a=next(a for a in s['audits'] if a['name']==name)
                a.update(type='passed',axioms='passed' if result['passed'] else 'failed',dependencies=result['dependencies'],output=result['error'])
            self.store.mutate(self.id,update)
        if not passed: raise ValueError('公理审计未通过或输出缺失')

    def replay(self):
        self.unchanged()
        self.execute(['lake','-f','lakefile.toml','env','leanchecker','--fresh','Main'],'replay')
        self.verify_sources()
        self.store.mutate(self.id,lambda s:[a.update(replay='passed') for a in s['audits']])

    def run(self):
        try:
            # Resume revalidates bytes/configuration instead of trusting a completion marker.
            state=self.store.raw(self.id)
            if state['stages'][1]['status']=='passed':
                try: verify_archive(self.root/'lean.tar.gz',self.submission.archive_hash,self.submission.archive_bytes)
                except ValueError as error:
                    self.invalidate_download(str(error))
                    raise
                validate_project(self.original,expected_count=self.submission.file_count); self.unchanged(); self.verify_sources()
            for name in ['download','integrity','dependencies','compile','audit','replay']:
                if name=='dependencies':
                    if not os.environ.get('SANDBOX_ROOT'): raise RuntimeError('未配置 Lean 子进程文件系统隔离')
                    from .sandbox import prepare
                    self.project=prepare(os.environ['SANDBOX_ROOT'],self.id,self.original)
                    self.unchanged(); self.verify_sources()
                self.stage(name,getattr(self,name))
            self.store.mutate(self.id,lambda s:s.update(status='checks_completed',finishedAt=time.time(),error=None),'finished')
        except Exception as e:
            code=getattr(e,'code',1); raw=self.store.raw(self.id)
            cause=getattr(e,'terminationCause',None)
            if raw['desired']=='cancelled' or cause=='cancelled':status='cancelled'
            elif cause=='operator_interruption':status='interrupted'
            elif cause in ('timeout','runner_error'):status='failed'
            else:status='resource_exhausted' if code in (137,-9) else ('interrupted' if code<0 else 'failed')
            def fail(s):
                s.update(status=status,error=str(e),finishedAt=time.time())
                next(x for x in s['stages'] if x['id']==s['phase']).update(status=status,exitCode=code,finishedAt=time.time())
                s['compile']['rate']=0
            self.store.mutate(self.id,fail,'failed'); self.store.log(self.id,'error',str(e),raw['phase'])
        finally:
            for path in self.root.glob('command-*.log'): self.register(path)
            s=self.store.snapshot(self.id)
            self.evidence('verification-result.json',dict(run=s,generatedAt=time.time(),note='检查完成不代表数学陈述已人工复核。leanchecker 使用同一 Lean 内核；不同内核独立检查未执行。'))
