"""Cross-process transactional SQLite state and durable event/log ledger."""
import contextlib
import json
import sqlite3
import os
import time
from pathlib import Path
from .model import initial_state, derived


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'observatory.sqlite3'
        with self.db() as db:
            db.executescript('''
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, state TEXT NOT NULL, created REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT, run TEXT, ts REAL, level TEXT, stage TEXT, message TEXT);
              CREATE INDEX IF NOT EXISTS logs_run ON logs(run,id);
              CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, run TEXT, ts REAL, kind TEXT, payload TEXT);
              CREATE TABLE IF NOT EXISTS samples(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, payload TEXT);
              CREATE INDEX IF NOT EXISTS samples_ts ON samples(ts);
              CREATE TABLE IF NOT EXISTS modules(run TEXT, module TEXT, PRIMARY KEY(run,module));
            ''')
        if self.path.stat().st_mode & 0o777 != 0o660:
            os.chmod(self.path,0o660)

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=30000')
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, mode='mock', scenario='success', jobs=60):
        if mode not in ('mock', 'real') or scenario not in ('success', 'failure', 'interruption', 'resource'):
            raise ValueError('无效的模式或场景')
        if type(jobs) is not int or not 1 <= jobs <= 60:
            raise ValueError('并发必须在 1 到 60 之间')
        s = initial_state(mode)
        s.update(scenario=scenario, status='queued')
        s['compile']['jobs'] = jobs
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute('SELECT state FROM runs'):
                if json.loads(row[0])['status'] in ('queued', 'running', 'paused'):
                    raise ValueError('已有活动任务，请先取消或等待完成')
            db.execute('INSERT INTO runs VALUES(?,?,?)', (s['id'], json.dumps(s), time.time()))
            db.execute('INSERT INTO events(run,ts,kind,payload) VALUES(?,?,?,?)', (s['id'], time.time(), 'created', json.dumps({'mode': mode})))
        (self.root / 'runs' / s['id']).mkdir(parents=True, exist_ok=True)
        self.log(s['id'], 'info', f'创建 {mode.upper()} 任务；所有结果以该任务实际检查为准。')
        return s

    def raw(self, run=None):
        with self.db() as db:
            row = db.execute('SELECT state FROM runs WHERE id=?', (run,)).fetchone() if run else db.execute('SELECT state FROM runs ORDER BY created DESC LIMIT 1').fetchone()
            return json.loads(row[0]) if row else None

    def snapshot(self, run=None):
        s = self.raw(run)
        if not s:
            s = initial_state()
            s['id'] = None
        return derived(s)

    def mutate(self, run, fn, event=None):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM runs WHERE id=?', (run,)).fetchone()
            if not row:
                raise ValueError('任务不存在')
            s = json.loads(row[0])
            fn(s)
            s['updatedAt'] = time.time()
            db.execute('UPDATE runs SET state=? WHERE id=?', (json.dumps(s), run))
            if event:
                db.execute('INSERT INTO events(run,ts,kind,payload) VALUES(?,?,?,?)', (run, time.time(), event, json.dumps({'status': s['status'], 'phase': s['phase']})))
            return s

    def runs(self):
        with self.db() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT state FROM runs ORDER BY created DESC LIMIT 30')]

    def run_summaries(self):
        # Operational acceptance needs the complete ledger, not the UI's 30-row
        # detail window. Project only small fields rather than loading all states.
        with self.db() as db:
            return [dict(row) for row in db.execute("SELECT id,json_extract(state,'$.mode') AS mode,json_extract(state,'$.status') AS status,json_extract(state,'$.startedAt') AS startedAt FROM runs ORDER BY created DESC")]

    def active_runs(self):
        with self.db() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT state FROM runs WHERE json_extract(state,'$.status') IN ('queued','running','paused') ORDER BY created")]

    def control(self, run, action):
        allowed = {'pause': ('running', 'queued'), 'resume': ('paused', 'interrupted', 'resource_exhausted', 'failed'), 'cancel': ('queued', 'running', 'paused', 'interrupted', 'resource_exhausted', 'failed')}
        def change(s):
            if action not in allowed or s['status'] not in allowed[action]:
                raise ValueError('当前状态不支持该操作')
            s['desired'] = {'pause': 'paused', 'resume': 'running', 'cancel': 'cancelled'}[action]
            if action == 'resume' and s['status'] not in ('paused',):
                if any(x['id'] != run for x in self.active_runs()):
                    raise ValueError('另一个任务正在运行')
                if s['status']=='resource_exhausted':
                    s['compile']['jobs']=max(1,s['compile']['jobs']//2)
                s.update(status='queued', error=None, finishedAt=None)
                if s['mode'] == 'mock':
                    s['scenario'] = 'success'
            elif s['status'] != 'running' or s['mode'] == 'mock':
                s['status'] = s['desired']
        s = self.mutate(run, change, 'control:' + action)
        self.log(run, 'info', '操作请求: ' + action)
        return s

    def log(self, run, level, message, stage='system'):
        with self.db() as db:
            db.execute('INSERT INTO logs(run,ts,level,stage,message) VALUES(?,?,?,?,?)', (run, time.time(), level, stage, message[:16000]))

    def logs(self, run, after=None, limit=300, query=''):
        limit = max(1, min(1000, limit))
        with self.db() as db:
            if after is not None:
                rows = db.execute('SELECT * FROM logs WHERE run=? AND id>? AND message LIKE ? ORDER BY id LIMIT ?', (run, after, '%'+query+'%', limit))
                return [dict(r) for r in rows]
            rows = db.execute('SELECT * FROM logs WHERE run=? AND message LIKE ? ORDER BY id DESC LIMIT ?', (run, '%'+query+'%', limit))
            return list(reversed([dict(r) for r in rows]))

    def sample(self, payload):
        with self.db() as db:
            db.execute('INSERT INTO samples(ts,payload) VALUES(?,?)', (time.time(), json.dumps(payload)))
            db.execute('DELETE FROM samples WHERE ts < ?', (time.time()-86400*7,))

    def history(self, limit=1801, run=None):
        with self.db() as db:
            if run:
                return list(reversed([json.loads(x[0]) for x in db.execute("SELECT payload FROM samples WHERE json_extract(payload,'$.runId')=? ORDER BY id DESC LIMIT ?",(run,min(limit,1801)))]))
            return list(reversed([json.loads(x[0]) for x in db.execute('SELECT payload FROM samples ORDER BY id DESC LIMIT ?', (min(limit, 1801),))]))

    def module_done(self, run, module):
        with self.db() as db:
            cur = db.execute('INSERT OR IGNORE INTO modules VALUES(?,?)', (run, module))
            return cur.rowcount == 1

    def module_count(self, run):
        with self.db() as db:
            return db.execute('SELECT count(*) FROM modules WHERE run=?', (run,)).fetchone()[0]
