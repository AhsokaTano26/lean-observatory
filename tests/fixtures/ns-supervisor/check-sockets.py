import subprocess,sys
child='/app/ns_queue/child.py'
probe=[sys.executable,'-c','import socket; a,b=socket.socketpair(); a.close(); b.close(); print("SOCKETPAIR_OK")']
def run(mode,*command):return subprocess.run([sys.executable,child,mode,*command],capture_output=True,text=True)
assert run('--exec-network',*probe).returncode==0,'dependency resolver wakeup socketpair must work'
assert run('--exec',*probe).returncode!=0,'offline proof commands must still deny AF_UNIX'
strict=run('--exec-network',sys.executable,child,'--probe-af-unix')
assert strict.returncode==0 and 'NS_AF_UNIX_DENIED' in strict.stdout,strict.stderr
inherited=run('--exec',sys.executable,child,'--exec-network',*probe)
assert inherited.returncode!=0,'an already inherited seccomp filter must never be removable'
print('Dependency socketpair works; strict checker and inherited filters deny AF_UNIX')
