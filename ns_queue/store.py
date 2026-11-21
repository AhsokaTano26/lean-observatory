"""Independent, transactional NS state, event ledger, and notification outbox.

Times are Unix seconds. Outbox rows retain ``nextAttemptAt`` so a controller can
select due deliveries without confusing HTTP 202 acceptance with delivery.
"""
import contextlib
import copy
import fcntl
import json
import math
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path


STAGES = ('source', 'dependencies', 'compile', 'audit', 'kernel', 'independent', 'persist')


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


class QueueStore:
    def __init__(self, root):
        self._readonly = False
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'ns-queue.sqlite3'
        self.lock_path = self.root / 'ns-queue.sqlite3.lock'
        try:
            self.lock_path.open('xb').close()
        except FileExistsError:
            pass
        with self.db() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS queue (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
                    stage TEXT NOT NULL, message TEXT NOT NULL, level TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
                    event TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL, message TEXT NOT NULL, level TEXT NOT NULL,
                    fields TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    nextAttemptAt REAL, status TEXT NOT NULL,
                    createdAt REAL NOT NULL, updatedAt REAL NOT NULL, lastError TEXT);
            ''')

    @classmethod
    def readonly(cls, root):
        """Open an existing queue without creating or changing deployment data."""
        reader = cls.__new__(cls)
        reader._readonly = True
        reader.root = Path(root).resolve()
        reader.path = reader.root / 'ns-queue.sqlite3'
        reader.lock_path = reader.root / 'ns-queue.sqlite3.lock'
        if not reader.path.is_file() or not reader.lock_path.is_file():
            raise FileNotFoundError(reader.path)
        return reader

    @contextlib.contextmanager
    def db(self, readonly=False):
        """Open one short-lived connection; every writer uses FULL durability."""
        if self._readonly and not readonly:
            raise PermissionError('queue is read-only')
        # mode=ro alone can create/modify SQLite's WAL shared-memory files.
        # A shared flock protects immutable reads while all our writers hold an
        # exclusive flock, including connection close/checkpoint. Crash-left WAL
        # is copied under that lock and recovered only in private temporary data.
        with self.lock_path.open('rb') as lock, contextlib.ExitStack() as cleanup:
            fcntl.flock(lock.fileno(), fcntl.LOCK_SH if readonly else fcntl.LOCK_EX)
            target = self.path
            if readonly:
                wal = Path(str(self.path) + '-wal')
                if wal.exists() and wal.stat().st_size:
                    temporary = Path(cleanup.enter_context(tempfile.TemporaryDirectory(prefix='ns-queue-reader-')))
                    target = temporary / self.path.name
                    shutil.copyfile(self.path, target)
                    shutil.copyfile(wal, Path(str(target) + '-wal'))
                    uri = target.as_uri() + '?mode=ro'
                else:
                    uri = target.as_uri() + '?mode=ro&immutable=1'
                db = sqlite3.connect(uri, uri=True, timeout=30)
                db.execute('PRAGMA query_only=ON')
            else:
                db = sqlite3.connect(target, timeout=30)
                db.execute('PRAGMA synchronous=FULL')
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA busy_timeout=30000')
            try:
                with db:
                    yield db
            finally:
                db.close()
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def initialize(self, spec, rh_run, budget):
        if not isinstance(spec, dict) or not isinstance(spec.get('commit'), str) or not spec['commit']:
            raise ValueError('source commit required')
        if not isinstance(rh_run, str) or not rh_run:
            raise ValueError('RH run ID required')
        limits = {'capUsd': 0, 'hourlyUsd': 3.36, 'minStartSeconds': 300, 'estimatedUsd': 0}
        limits.update(budget)
        for key in ('capUsd', 'hourlyUsd', 'minStartSeconds', 'estimatedUsd'):
            number = limits[key]
            if type(number) not in (int, float) or not math.isfinite(number) or number < 0:
                raise ValueError('invalid budget: ' + key)
        now = time.time()
        state = dict(id='ns-' + spec['commit'][:12], mode='real', spec=copy.deepcopy(spec),
                     source=copy.deepcopy(spec), rhRunId=rh_run, status='QUEUED', reason='waiting_rh',
                     phase='source', budget=limits, rhEvidence={'persisted': False},
                     createdAt=now, updatedAt=now, startedAt=None, finishedAt=None,
                     stages=[dict(id=stage, status='PENDING', exitCode=None,
                                  startedAt=None, finishedAt=None) for stage in STAGES],
                     compile=dict(expectedTotal=spec.get('expectedFileCount'), total=None,
                                  succeeded=0, failed=0, rate=0, etaSeconds=None,
                                  currentModule=None, jobs=48),
                     commands=[], artifacts=[], audits=[], proofAccepted=False)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM queue WHERE singleton=1').fetchone()
            if row:
                existing = json.loads(row['state'])
                if existing.get('spec') != spec or existing.get('rhRunId') != rh_run:
                    raise ValueError('queue already initialized for a different source or RH run')
                return existing
            db.execute('INSERT INTO queue VALUES(1,?)', (_json(state),))
            self._event(db, now, 'initialized', state)
        return state

    def snapshot(self):
        with self.db(readonly=True) as db:
            row = db.execute('SELECT state FROM queue WHERE singleton=1').fetchone()
            return json.loads(row['state']) if row else None

    @staticmethod
    def _event(db, at, event, state):
        payload = {key: state.get(key) for key in ('id', 'status', 'reason')}
        db.execute('INSERT INTO events(at,event,payload) VALUES(?,?,?)', (at, event, _json(payload)))

    def mutate(self, fn, event='updated'):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM queue WHERE singleton=1').fetchone()
            if row is None:
                raise ValueError('queue is not initialized')
            state = json.loads(row['state'])
            identity = {key: copy.deepcopy(state.get(key)) for key in ('id', 'spec', 'rhRunId')}
            fn(state)
            if any(state.get(key) != value for key, value in identity.items()):
                raise ValueError('source and dependency identity are immutable')
            now = time.time()
            state['updatedAt'] = now
            db.execute('UPDATE queue SET state=? WHERE singleton=1', (_json(state),))
            if event:
                self._event(db, now, event, state)
            return state

    def log(self, stage, message, level='info'):
        with self.db() as db:
            cursor = db.execute('INSERT INTO logs(at,stage,message,level) VALUES(?,?,?,?)',
                                (time.time(), stage, message, level))
            return cursor.lastrowid

    def logs(self, after=0, limit=200):
        with self.db(readonly=True) as db:
            return [dict(row) for row in db.execute('SELECT * FROM logs WHERE id>? ORDER BY id LIMIT ?',
                                                    (max(0, int(after)), max(1, min(1000, int(limit)))))]

    def read_events(self, after=0, limit=200):
        with self.db(readonly=True) as db:
            rows = db.execute('SELECT * FROM events WHERE id>? ORDER BY id LIMIT ?',
                              (max(0, int(after)), max(1, min(1000, int(limit)))))
            return [dict(row, payload=json.loads(row['payload'])) for row in rows]

    def alert(self, key, title, message, level='error', fields=None):
        if not isinstance(key, str) or not key:
            raise ValueError('alert deduplication key required')
        now = time.time()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('''INSERT OR IGNORE INTO alerts
                (key,title,message,level,fields,nextAttemptAt,status,createdAt,updatedAt)
                VALUES(?,?,?,?,?,?,'queued',?,?)''',
                       (key, title, message, level, _json(fields or {}), now, now, now))
            return db.execute('SELECT id FROM alerts WHERE key=?', (key,)).fetchone()['id']

    def outbox(self):
        """Return all queued/retry rows; callers compare nextAttemptAt to now."""
        with self.db(readonly=True) as db:
            rows = db.execute("SELECT * FROM alerts WHERE status IN ('queued','retry') ORDER BY id")
            return [dict(row, fields=json.loads(row['fields'])) for row in rows]

    def ack_alert(self, id, status, error=None):
        if status not in ('sent', 'accepted', 'retry'):
            raise ValueError('invalid alert acknowledgement')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM alerts WHERE id=?', (id,)).fetchone()
            if row is None:
                raise ValueError('alert does not exist')
            if row['status'] in ('sent', 'accepted'):
                return
            attempts = row['attempts'] + 1
            now = time.time()
            retry_at = now + min(3600, 5 * 2**min(attempts - 1, 10)) if status == 'retry' else None
            db.execute('''UPDATE alerts SET status=?,attempts=?,nextAttemptAt=?,
                          updatedAt=?,lastError=? WHERE id=?''',
                       (status, attempts, retry_at, now, error if status == 'retry' else None, id))
