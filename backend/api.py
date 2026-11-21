"""Small read-oriented HTTP/SSE API. Heavy work only happens in worker.py."""
import argparse
import hashlib
import hmac
import json
import mimetypes
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from .store import Store
from .metrics import collect, read_host_file


def make_server(store, address, token='', frontend=None, allow_real=False, host_metrics=None):
    frontend=Path(frontend or 'frontend/dist').resolve()
    stream_slots=threading.BoundedSemaphore(24)
    stopping=threading.Event()
    class Server(ThreadingHTTPServer):
        daemon_threads=True
        def shutdown(self):
            stopping.set()
            super().shutdown()

    def metrics():
        if host_metrics: return read_host_file(host_metrics)
        history=store.history(1)
        if history and time.time()-history[-1]['sampledAt'] < 20:
            return history[-1]
        m=collect(store.root); m['stale']=False
        return m

    def payload(run=None):
        s=store.snapshot(run)
        heartbeat=s['workerHeartbeat']
        return dict(run=s, metrics=metrics(), serverTime=time.time(),
                    workerOnline=bool(heartbeat and time.time()-heartbeat < 15),
                    capabilities=dict(realEnabled=allow_real, authRequired=bool(token)))

    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'

        def log_message(self, fmt, *args):
            pass

        def respond(self, status, value, content_type='application/json; charset=utf-8', download=None):
            raw=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode() if isinstance(value,(dict,list)) else value
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(raw)))
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
                if path=='/api/history': return self.respond(200,store.history())
                if path=='/api/logs': return self.respond(200,store.logs(run or store.snapshot()['id'],int(q.get('after',[0])[0]),int(q.get('limit',[300])[0]),q.get('q',[''])[0]))
                if path=='/api/events': return self.events(run)
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
                    # Chunked iteration through SQLite, not a bounded UI log window.
                    self.send_response(200); self.send_header('Content-Type','application/x-ndjson'); self.send_header('Content-Disposition','attachment; filename="full-logs.ndjson"'); self.send_header('Connection','close'); self.end_headers()
                    after=0
                    while True:
                        rows=store.logs(s['id'],after=after,limit=1000)
                        if not rows: break
                        for row in rows: self.wfile.write((json.dumps(row,ensure_ascii=False)+'\n').encode())
                        after=rows[-1]['id']
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

        def events(self, run):
            if not stream_slots.acquire(False): return self.respond(503,{'error':'实时连接已达上限，请重试'})
            try:
                self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.send_header('Cache-Control','no-cache'); self.send_header('X-Accel-Buffering','no'); self.end_headers()
                # Every reconnect receives an authoritative snapshot. Logs replay from durable IDs.
                try: after=max(0,int(self.headers.get('Last-Event-ID','0')))
                except ValueError: after=0
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

        def do_POST(self):
            # JSON-only + same-origin prevents cross-site form and fetch mutations.
            origin=self.headers.get('Origin')
            if origin and urlparse(origin).netloc != self.headers.get('Host'):
                return self.respond(403,{'error':'跨域操作被拒绝'})
            if token and not hmac.compare_digest(self.headers.get('Authorization',''), 'Bearer '+token):
                return self.respond(401,{'error':'需要管理员令牌'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if size>8192: return self.respond(413,{'error':'请求过大'})
                if not self.headers.get('Content-Type','').startswith('application/json'):
                    return self.respond(415,{'error':'仅支持 JSON'})
                data=json.loads(self.rfile.read(size))
                if self.path=='/api/runs':
                    mode=data.get('mode','mock')
                    if mode=='real' and not allow_real:
                        return self.respond(403,{'error':'真实任务尚未通过部署验收门禁'})
                    s=store.create(mode,data.get('scenario','success'),data.get('jobs',48))
                    return self.respond(201,s)
                if self.path=='/api/control':
                    return self.respond(200,store.control(data.get('run'),data.get('action')))
                return self.respond(404,{'error':'接口不存在'})
            except (ValueError,KeyError,TypeError) as e:
                return self.respond(409 if '已有活动' in str(e) or '另一个任务' in str(e) else 400,{'error':str(e)})

    server=Server(address,Handler)
    return server


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--host',default='127.0.0.1'); parser.add_argument('--port',type=int,default=8787); parser.add_argument('--data',default='.data')
    a=parser.parse_args(); token=os.environ.get('ADMIN_TOKEN','')
    if a.host not in ('127.0.0.1','localhost') and not token:
        raise SystemExit('公网或容器监听必须设置 ADMIN_TOKEN')
    make_server(Store(Path(a.data)),(a.host,a.port),token,allow_real=os.environ.get('ENABLE_REAL')=='1',host_metrics=os.environ.get('HOST_METRICS')).serve_forever()


if __name__=='__main__': main()
