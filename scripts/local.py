#!/usr/bin/env python3
"""Native development/QA server; starts the worker separately from HTTP."""
import argparse
import subprocess
import sys
import threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.api import make_server
from backend.store import Store

p=argparse.ArgumentParser(); p.add_argument('--port',type=int,default=8787); p.add_argument('--data',default='.data'); p.add_argument('--interval',type=float,default=1); p.add_argument('--demo',action='store_true')
a=p.parse_args(); store=Store(Path(a.data)); worker=subprocess.Popen([sys.executable,'-m','backend.worker','--data',a.data,'--interval',str(a.interval)])
if a.demo and not store.raw(): store.create('mock','success')
server=make_server(store,('127.0.0.1',a.port))
print(f'Lean Observatory: http://127.0.0.1:{a.port}',flush=True)
try: server.serve_forever()
except KeyboardInterrupt: pass
finally:
    server.server_close(); worker.terminate()
    try: worker.wait(10)
    except subprocess.TimeoutExpired: worker.kill();worker.wait()
