"""Read-only project page, on a separate listener from the running RH dashboard."""
import argparse
import json
import mimetypes
import os
import time
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .store import QueueStore
from .budget import normalize

ASSETS=Path(__file__).with_name('web')


def payload(store, host_file=None):
    state=store.snapshot()
    if state is None: raise ValueError('NS queue has not been initialized')
    now=time.time(); state['budget']=normalize(state['budget'],now); rh=state.get('rh') or {}; rate=state['budget']['hourlyUsd']
    ns_seconds=max(0,(state.get('finishedAt') or state.get('pausedAt') or now)-state['startedAt']) if state.get('startedAt') else 0
    rh_seconds=max(0,(rh.get('finishedAt') or now)-rh['startedAt']) if rh.get('startedAt') else None
    host=None
    if host_file:
        try:
            host=json.loads(Path(host_file).read_text())
            host['stale']=not isinstance(host.get('sampledAt'),(int,float)) or not -60<=now-host['sampledAt']<20
            if host.get('source')!='host_agent':host=None
        except (OSError,ValueError,TypeError):pass
    ns_resources=state.get('worker',{}).get('resources') or ({'source':'not_started','cpuPercent':0,'memoryBytes':0} if not state.get('startedAt') else {'source':'unavailable','cpuPercent':None,'memoryBytes':None})
    return dict(queue=state,rh=rh,hostMetrics=host,nsResources=ns_resources,serverTime=now,
                deployment={'sourceSha256':os.environ.get('NS_SOURCE_SHA256')},
                controllerOnline=bool(state.get('controllerHeartbeat') and now-state['controllerHeartbeat']<45),
                actualInvoiceAvailable=False,rhEstimatedUsd=rh_seconds/3600*rate if rh_seconds is not None else None,
                serverEstimatedUsd=state['budget']['estimatedUsd'] if state['budget']['scope']=='server' else None,
                nsEstimatedUsd=ns_seconds/3600*rate,readOnly=True)


def make_server(store, address, host_file=None):
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def respond(self,status,body,content_type='application/json',download=None):
            if not isinstance(body,bytes):body=json.dumps(body,ensure_ascii=False).encode()
            self.send_response(status); self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; connect-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
            if download:self.send_header('Content-Disposition','attachment; filename="'+download+'"')
            self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            path=urllib.parse.urlsplit(self.path)
            if path.path.startswith('/ns/'):path=path._replace(path=path.path[3:])
            q=urllib.parse.parse_qs(path.query)
            try:
                if path.path=='/entry':return self.respond(200,(ASSETS/'entry.html').read_bytes(),'text/html; charset=utf-8')
                if path.path=='/healthz':return self.respond(200,{'ok':True,'service':'lean-observatory-ns'})
                if path.path in ('/','/ns','/ns/','/projects'):return self.respond(200,(ASSETS/'index.html').read_bytes(),'text/html; charset=utf-8')
                if path.path in ('/assets/app.css','/assets/app.js','/assets/entry.css','/assets/entry.js'):
                    name=path.path.rsplit('/',1)[1];mime='text/css' if name.endswith('.css') else 'text/javascript'
                    return self.respond(200,(ASSETS/name).read_bytes(),mime+'; charset=utf-8')
                if path.path in ('/api/state','/api/report.json'):
                    return self.respond(200,payload(store,host_file),download='ns-status-report.json' if path.path.endswith('.json') else None)
                if path.path=='/api/logs':return self.respond(200,store.logs(int(q.get('after',['0'])[0]),200))
                if path.path=='/api/events':return self.events(q)
                if path.path=='/api/alerts':
                    with store.db(readonly=True) as db:
                        rows=[dict(r) for r in db.execute('SELECT id,title,message,level,status,attempts,createdAt,updatedAt,lastError FROM alerts ORDER BY id DESC LIMIT 50')]
                    return self.respond(200,rows)
                if path.path=='/api/logs/export':
                    with store.db(readonly=True) as db: end=db.execute('SELECT COALESCE(MAX(id),0) FROM logs').fetchone()[0]
                    self.send_response(200);self.send_header('Content-Type','application/x-ndjson');self.send_header('Content-Disposition','attachment; filename="ns-events.ndjson"');self.send_header('Connection','close');self.end_headers()
                    cursor=0
                    while cursor<end:
                        batch=store.logs(cursor,1000)
                        if not batch:break
                        for row in batch:
                            if row['id']<=end:self.wfile.write((json.dumps(row,ensure_ascii=False)+'\n').encode())
                        cursor=batch[-1]['id']
                    self.close_connection=True;return
                if path.path.startswith('/api/artifacts/'):
                    state=store.snapshot();name=urllib.parse.unquote(path.path.rsplit('/',1)[-1])
                    item=next((a for a in state.get('artifacts',[]) if a.get('name')==name),None)
                    if item:
                        file=(store.root/item.get('path',item['name'])).resolve()
                        if file.is_relative_to(store.root) and file.is_file():
                            self.send_response(200);self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Length',str(file.stat().st_size));self.end_headers()
                            with file.open('rb') as stream:
                                for chunk in iter(lambda:stream.read(65536),b''):self.wfile.write(chunk)
                            return
                    return self.respond(404,{'error':'证据尚未生成'})
                return self.respond(404,{'error':'Not found'})
            except (BrokenPipeError,ConnectionResetError):pass
            except (ValueError,KeyError,TypeError) as error:self.respond(400,{'error':str(error)})

        def events(self,q):
            after=max(0,int(q.get('after',['0'])[0]),int(self.headers.get('Last-Event-ID','0')))
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Cache-Control','no-cache');self.send_header('Connection','keep-alive');self.end_headers()
            try:
                while not self.server.closing.is_set():
                    data=payload(store,host_file);rows=store.logs(after,200)
                    if rows:after=rows[-1]['id']
                    data['logs']=rows
                    packet=f'id: {after}\nevent: snapshot\ndata: '+json.dumps(data,ensure_ascii=False)+'\n\n'
                    self.wfile.write(packet.encode());self.wfile.flush();time.sleep(2)
            except (BrokenPipeError,ConnectionResetError,OSError):pass

        def reject(self):
            self.send_response(405);self.send_header('Allow','GET');self.send_header('Content-Length','0');self.send_header('Connection','close');self.end_headers();self.close_connection=True
        do_POST=do_PUT=do_PATCH=do_DELETE=do_OPTIONS=reject
        def log_message(self,*args):pass
    class Server(ThreadingHTTPServer):
        daemon_threads=True
        def server_close(self):
            self.closing.set();super().server_close()
    server=Server(address,Handler);server.closing=threading.Event();return server


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8792)
    args=parser.parse_args();server=make_server(QueueStore.readonly(args.root),(args.host,args.port),os.environ.get('NS_HOST_METRICS'))
    print(f'NS read-only page listening on {args.host}:{args.port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
