import contextlib
import fcntl
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.store import Store
from scripts import backup

class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'data';self.store=Store(self.root)
        run=self.store.create('real');self.run=run['id'];self.out=Path(self.tmp.name)/'backup'
        self.file=self.root/'runs'/self.run/'evidence.txt';self.file.write_bytes(b'evidence\n')

    def test_dry_run_never_creates_files(self):
        before=sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        result=backup.create_backup(self.root,self.out)
        self.assertFalse(result['executed']);self.assertFalse(self.out.exists())
        self.assertEqual(before,sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')))

    def test_backup_api_captures_wal_and_matching_evidence(self):
        with contextlib.closing(sqlite3.connect(self.store.path)) as keeper:
            keeper.execute('PRAGMA journal_mode=WAL')
            self.store.log(self.run,'info','committed WAL evidence')
            result=backup.create_backup(self.root,self.out,execute=True)
        self.assertTrue(result['executed']);self.assertEqual((self.out/'runs'/self.run/'evidence.txt').read_bytes(),b'evidence\n')
        with contextlib.closing(sqlite3.connect(self.out/'observatory.sqlite3')) as db:
            self.assertEqual(db.execute("SELECT message FROM logs ORDER BY id DESC LIMIT 1").fetchone()[0],'committed WAL evidence')
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        manifest=json.loads((self.out/'manifest.json').read_text())
        self.assertEqual(manifest['files']['runs/'+self.run+'/evidence.txt']['bytes'],9)
        self.assertNotIn('observatory.sqlite3-wal',manifest['files'])

    def test_worker_lock_blocks_backup(self):
        with (self.root/'worker.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError,'Worker'): backup.create_backup(self.root,self.out,execute=True)
        self.assertFalse(self.out.exists())

    def test_changed_evidence_rejects_backup_without_published_output(self):
        original=__import__('shutil').copyfile
        def changing(src,dst,*args,**kwargs):
            result=original(src,dst,*args,**kwargs)
            if Path(src).resolve()==self.file.resolve():self.file.write_bytes(b'changed')
            return result
        with patch('scripts.backup.shutil.copyfile',side_effect=changing):
            with self.assertRaisesRegex(RuntimeError,'changed'): backup.create_backup(self.root,self.out,execute=True)
        self.assertFalse(self.out.exists())

    def test_symlink_and_nested_or_existing_destination_rejected(self):
        for dest in [self.root/'backup',self.root]:
            with self.assertRaises(ValueError): backup.create_backup(self.root,dest,execute=True)
        (self.root/'link').symlink_to(self.file)
        with self.assertRaises(ValueError): backup.create_backup(self.root,self.out,execute=True)
        self.assertFalse(self.out.exists())

    def test_registered_evidence_hash_mismatch_rejected(self):
        self.store.mutate(self.run,lambda s:s['artifacts'].append({'name':'evidence.txt','bytes':9,'sha256':'0'*64}))
        with self.assertRaisesRegex(RuntimeError,'artifact'): backup.create_backup(self.root,self.out,execute=True)
        self.assertFalse(self.out.exists())

if __name__=='__main__': unittest.main()
