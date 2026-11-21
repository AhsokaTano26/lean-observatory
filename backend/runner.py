"""Execute fixed argument vectors, capture full logs, persist actual exit codes."""
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path


class CommandError(RuntimeError):
    def __init__(self, message, code=1, reason=None, terminationCause=None):
        super().__init__(message)
        self.code=code; self.reason=reason; self.terminationCause=terminationCause


class CommandRunner:
    def __init__(self, store, run):
        self.store=store; self.run_id=run
        self.root=store.root/'runs'/run
        self.root.mkdir(parents=True, exist_ok=True)

    def run(self, argv, cwd, stage, callback=None, timeout=86400*3, sandbox=False):
        start=time.time(); index=len(self.store.raw(self.run_id)['commands'])
        filename=f'command-{index:03d}-{stage}.log'
        record=dict(argv=argv, cwd=str(cwd), stage=stage, startedAt=start, sandbox=sandbox,
                    leanThreads=self.store.raw(self.run_id)['compile']['jobs'],
                    finishedAt=None, exitCode=None, logFile=filename,
                    status='running', terminationCause=None)
        self.store.mutate(self.run_id, lambda s: s['commands'].append(record), 'command_started')
        self.store.log(self.run_id, 'info', '$ ' + ' '.join(argv), stage)
        env={**os.environ, 'NO_COLOR':'1', 'TERM':'dumb'}
        output=[]; captured=0; paused=False; last=time.monotonic(); heartbeat=0
        process=None; selector=None; code=127; reason=None; terminationCause=None
        with (self.root/filename).open('wb') as full:
            try:
                actual=argv
                if sandbox:
                    from .sandbox import command
                    actual=command(os.environ['SANDBOX_ROOT'],cwd,argv,self.store.raw(self.run_id)['compile']['jobs'],network=stage=='dependencies')
                guarded=[sys.executable,str(Path(__file__).with_name('child.py')),str(os.getpid()),*actual]
                process=subprocess.Popen(guarded, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, start_new_session=True)
                self.store.mutate(self.run_id, lambda s:s['commands'][index].update(pid=process.pid,pgid=process.pid,supervised=True))
                os.set_blocking(process.stdout.fileno(), False)
                selector=selectors.DefaultSelector(); selector.register(process.stdout, selectors.EVENT_READ)
                buffer=b''
                while True:
                    now=time.monotonic(); dt=now-last; last=now
                    if now-heartbeat >= .8:
                        state=self.store.raw(self.run_id); desired=state['desired']
                        if desired == 'cancelled':
                            reason='cancelled'; terminationCause='cancelled'
                            os.killpg(process.pid, signal.SIGTERM)
                            try: process.wait(8)
                            except subprocess.TimeoutExpired: os.killpg(process.pid, signal.SIGKILL)
                        elif desired == 'paused' and not paused:
                            os.killpg(process.pid, signal.SIGSTOP); paused=True
                        elif desired == 'running' and paused:
                            os.killpg(process.pid, signal.SIGCONT); paused=False
                        def beat(s):
                            s['workerHeartbeat']=time.time()
                            s['status']='paused' if paused else 'running'
                            s['elapsedSeconds']=round(time.time()-(s['startedAt'] or start), 1)
                            if not paused: s['activeSeconds']+=now-heartbeat if heartbeat else 0
                            if stage=='compile':
                                wall=time.time();c=s['compile']
                                c['recent']=[t for t in c['recent'] if wall-t<60]
                                began=next(x['startedAt'] for x in s['stages'] if x['id']=='compile') or wall
                                c['rate']=round(len(c['recent'])/max(1,min(60,wall-began)),2) if not paused else 0
                        self.store.mutate(self.run_id, beat)
                        heartbeat=now
                    if time.time()-start > timeout:
                        reason='timeout'; terminationCause='timeout'
                        os.killpg(process.pid, signal.SIGKILL)
                    events=selector.select(.15)
                    eof=False
                    for key, _ in events:
                        chunk=os.read(key.fd, 65536)
                        if not chunk: eof=True; continue
                        full.write(chunk); full.flush(); buffer+=chunk
                        while b'\n' in buffer:
                            line,buffer=buffer.split(b'\n',1)
                            text=line.decode('utf-8', errors='replace').rstrip('\r')
                            self.store.log(self.run_id, 'error' if 'error:' in text.lower() else 'info', text, stage)
                            if callback: callback(text)
                            if captured < 8*1024**2:
                                output.append(text); captured+=len(line)
                        if len(buffer)>1024*1024:
                            self.store.log(self.run_id, 'warning', buffer[:16000].decode(errors='replace'), stage); buffer=b''
                    if process.poll() is not None and (eof or not events): break
                if buffer:
                    text=buffer.decode(errors='replace'); self.store.log(self.run_id, 'info', text, stage)
                    if callback: callback(text)
                    if captured<8*1024**2: output.append(text)
                code=process.wait()
            except BaseException as exc:
                if process:
                    if process.poll() is None:
                        try: os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                    code=process.wait()
                reason=str(exc) or type(exc).__name__
                terminationCause=('operator_interruption' if isinstance(exc,(KeyboardInterrupt,SystemExit))
                                  else terminationCause or 'runner_error')
                full.write((reason+'\n').encode())
            finally:
                if selector is not None: selector.close()
                if process and process.stdout: process.stdout.close()
                def finish(s):
                    status=('interrupted' if terminationCause=='operator_interruption' else
                            'cancelled' if terminationCause=='cancelled' else
                            'passed' if code==0 and not reason else 'failed')
                    s['commands'][index].update(exitCode=code, finishedAt=time.time(), reason=reason,
                                                terminationCause=terminationCause,status=status)
                self.store.mutate(self.run_id, finish, 'command_finished')
        if code != 0 or reason:
            raise CommandError(f'{stage}: 命令退出 {code}' + (f' ({reason})' if reason else ''), code,
                               reason=reason,terminationCause=terminationCause)
        return '\n'.join(output)
