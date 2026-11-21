"""Small read-oriented HTTP/SSE API. Heavy work only happens in worker.py."""
import argparse
import hashlib
import io
import json
import mimetypes
import threading
import time
import tarfile
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from .store import Store
from .metrics import collect, read_host_file


def make_server(store, address, frontend=None, host_metrics=None):
    frontend=Path(frontend or 'frontend/dist').resolve()
    stream_slots=threading.BoundedSemaphore(24)
    stopping=threading.Event()
    class Server(ThreadingHTTPServer):
        daemon_threads=True
        def shutdown(self):
            stopping.set()
            super().shutdown()

    def metrics(state):
        if state['id'] and state['mode']=='mock':
            from .mock import metrics as mock_metrics
            return mock_metrics(store.raw(state['id']))
        if host_metrics: return read_host_file(host_metrics)
        history=store.history(1)
        if history and history[-1].get('mode')!='mock' and time.time()-history[-1]['sampledAt'] < 20:
            return history[-1]
        m=collect(store.root); m['stale']=False
        return m

    def payload(run=None):
        s=store.snapshot(run)
        heartbeat=s['workerHeartbeat']
        return dict(run=s, metrics=metrics(s), serverTime=time.time(),
                    workerOnline=bool(heartbeat and time.time()-heartbeat < 15),
                    capabilities=dict(readOnly=True))

    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'

        def handle(self):
            try: super().handle()
            except (ConnectionResetError, BrokenPipeError): pass

        def log_message(self, fmt, *args):
            pass

        def respond(self, status, value, content_type='application/json; charset=utf-8', download=None):
            raw=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode() if isinstance(value,(dict,list)) else value
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(raw)))
            if status==405: self.send_header('Allow','GET')
            self.send_header('Cache-Control','no-store' if self.path.startswith('/api') else 'no-cache')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; script-src 'self'; base-uri 'self'; frame-ancestors 'none'")
            if download: self.send_header('Content-Disposition',f'attachment; filename="{download}"')
            self.end_headers(); self.wfile.write(raw)

        def do_GET(self):
            parsed=urlparse(self.path); path=parsed.path; q=parse_qs(parsed.query)
            run=q.get('run',[None])[0]
            try:
                if path=='/healthz': return self.respond(200,{'ok':True,'service':'lean-observatory'})
                if path=='/api/state': return self.respond(200,payload(run))
                if path=='/api/runs': return self.respond(200,[dict(id=s['id'],mode=s['mode'],status=s['status'],startedAt=s['startedAt']) for s in store.runs()])
                if path=='/api/history': return self.respond(200,store.history(run=run))
                if path=='/api/logs': return self.respond(200,store.logs(run or store.snapshot()['id'],int(q['after'][0]) if 'after' in q else None,int(q.get('limit',[300])[0]),q.get('q',[''])[0]))
                if path=='/api/events': return self.events(run,q.get('after',[None])[0])
                if path in ('/api/report.json','/api/report.md'):
                    report=dict(schemaVersion=1,generatedAt=time.time(),disclaimer='Mock 为合成数据；检查完成不等于数学陈述已人工复核。',**payload(run))
                    report['logs']=store.logs(report['run']['id'],limit=1000)
                    if path.endswith('.json'): return self.respond(200,report,download='verification-report.json')
                    s=report['run']
                    lines=['# Lean verification report',f"Mode: {s['mode'].upper()}",f"Status: {s['status']}",f"Run: {s['id']}",'',report['disclaimer'],'', '## Stage evidence']
                    lines += [f"- {x['label']}: {x['status']} (exit={x['exitCode']})" for x in s['stages']]
                    lines += ['', '## Reproducible machine-readable evidence', '```json',json.dumps(report,ensure_ascii=False,indent=2),'```']
                    return self.respond(200,'\n'.join(lines).encode(),'text/markdown; charset=utf-8','verification-report.md')
                if path=='/api/logs/download':
                    s=store.raw(run)
                    if not s: return self.respond(404,{'error':'任务不存在'})
                    # Raw command bytes are preserved separately from bounded UI messages.
                    # Build a finite ledger snapshot on the data disk, never in API RAM/tmpfs.
                    last=store.logs(s['id'],limit=1);end_id=last[0]['id'] if last else 0
                    with tempfile.TemporaryFile(dir=store.root) as ledger:
                        after=0
                        while after<end_id:
                            rows=store.logs(s['id'],after=after,limit=1000)
                            if not rows: break
                            for row in rows:
                                if row['id']<=end_id: ledger.write((json.dumps(row,ensure_ascii=False)+'\n').encode())
                            after=rows[-1]['id']
                        length=ledger.tell();ledger.seek(0)
                        self.send_response(200);self.send_header('Content-Type','application/gzip');self.send_header('Content-Disposition','attachment; filename="verification-logs.tar.gz"');self.send_header('Connection','close');self.end_headers()
                        with tarfile.open(fileobj=self.wfile,mode='w|gz') as archive:
                            info=tarfile.TarInfo('events.ndjson');info.size=length;archive.addfile(info,ledger)
                            snapshot=json.dumps(dict(run=store.snapshot(s['id']),capturedAt=time.time(),note='下载时刻的日志快照；原始命令输出与事件记录均包含。'),ensure_ascii=False).encode()
                            info=tarfile.TarInfo('snapshot.json');info.size=len(snapshot);archive.addfile(info,io.BytesIO(snapshot))
                            for file in sorted((store.root/'runs'/s['id']).glob('command-*.log')):
                                archive.add(file,arcname=file.name,recursive=False)
                    self.close_connection=True; return
                if path.startswith('/api/artifacts/'):
                    s=store.raw(run)
                    if not s: return self.respond(404,{'error':'任务不存在'})
                    name=path.rsplit('/',1)[1]
                    entry=next((x for x in s['artifacts'] if x['name']==name),None)
                    if not entry: return self.respond(404,{'error':'证据文件尚未生成'})
                    root=(store.root/'runs'/s['id']).resolve(); file=(root/name).resolve()
                    if not file.is_relative_to(root): return self.respond(400,{'error':'无效文件'})
                    self.send_response(200); self.send_header('Content-Type','application/octet-stream'); self.send_header('Content-Length',str(file.stat().st_size)); self.send_header('Content-Disposition',f'attachment; filename="{name}"'); self.end_headers()
                    with file.open('rb') as f:
                        for part in iter(lambda:f.read(65536),b''): self.wfile.write(part)
                    return
                if path.startswith('/api/'): return self.respond(404,{'error':'接口不存在'})
                file=(frontend/path.lstrip('/')).resolve()
                if not file.is_relative_to(frontend): return self.respond(403,{'error':'拒绝访问'})
                if not file.is_file(): file=frontend/'index.html'
                if not file.is_file(): return self.respond(503,{'error':'请先 npm run build'})
                return self.respond(200,file.read_bytes(),mimetypes.guess_type(file)[0] or 'application/octet-stream')
            except (BrokenPipeError,ConnectionResetError): pass
            except (ValueError,TypeError) as e: self.respond(400,{'error':str(e)})

        def events(self, run, cursor=None):
            if not stream_slots.acquire(False): return self.respond(503,{'error':'实时连接已达上限，请重试'})
            try:
                self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.send_header('Cache-Control','no-cache'); self.send_header('X-Accel-Buffering','no'); self.end_headers()
                # Every reconnect receives an authoritative snapshot. Logs replay from durable IDs.
                try: after=max(0,int(self.headers.get('Last-Event-ID',cursor))) if self.headers.get('Last-Event-ID',cursor) is not None else None
                except ValueError: after=None
                last_run=None; last_stamp=None
                while not stopping.is_set():
                    p=payload(run); rid=p['run']['id']
                    if last_run and last_run!=rid: after=0
                    rows=store.logs(rid,after=after,limit=400)
                    if rows: after=rows[-1]['id']
                    p['logs']=rows
                    packet=f"id: {after}\nevent: snapshot\ndata: {json.dumps(p,ensure_ascii=False,separators=(',',':'))}\n\n"
                    self.wfile.write(packet.encode()); self.wfile.flush(); last_run=rid
                    stopping.wait(1)
            except (BrokenPipeError,ConnectionResetError,TimeoutError): pass
            finally: stream_slots.release()

        def reject_write(self):
            # Close rather than interpreting an unread request body as another request.
            self.close_connection=True
            self.respond(405,{'error':'只读观测服务不接受写入操作'})

        do_POST=reject_write
        do_PUT=reject_write
        do_PATCH=reject_write
        do_DELETE=reject_write

    server=Server(address,Handler)
    return server


def main():
    import os
    parser=argparse.ArgumentParser(); parser.add_argument('--host',default='127.0.0.1'); parser.add_argument('--port',type=int,default=8787); parser.add_argument('--data',default='.data')
    a=parser.parse_args()
    make_server(Store(Path(a.data)),(a.host,a.port),host_metrics=os.environ.get('HOST_METRICS')).serve_forever()


if __name__=='__main__': main()
