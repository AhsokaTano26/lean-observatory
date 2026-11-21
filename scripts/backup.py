#!/usr/bin/env python3
"""Consistent evidence + SQLite backup. Default is a read-only dry run."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
import time
from pathlib import Path


def file_hash(file):
    digest=hashlib.sha256()
    with file.open('rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''):digest.update(part)
    return digest.hexdigest()


def inventory(root):
    files={}
    for path in sorted(root.rglob('*')):
        relative=str(path.relative_to(root))
        kind=path.lstat().st_mode
        if stat.S_ISLNK(kind):raise ValueError('symlink is not backup evidence: '+relative)
        if stat.S_ISDIR(kind):continue
        if not stat.S_ISREG(kind):raise ValueError('unsupported evidence file: '+relative)
        if relative in ('worker.lock','observatory.sqlite3','observatory.sqlite3-wal','observatory.sqlite3-shm'):continue
        files[relative]={'bytes':path.stat().st_size,'sha256':file_hash(path)}
    return files


def validate_artifacts(db, files):
    for row in db.execute('SELECT id,state FROM runs'):
        run,state=row[0],json.loads(row[1])
        for artifact in state.get('artifacts',[]):
            name=artifact.get('name','')
            relative='runs/'+run+'/'+name
            if Path(name).name!=name or not name or files.get(relative)!={'bytes':artifact.get('bytes'),'sha256':artifact.get('sha256')}:
                raise RuntimeError('registered artifact does not match evidence: '+relative)


@contextlib.contextmanager
def worker_lock(root, execute):
    path=root/'worker.lock'
    if path.is_symlink():raise ValueError('worker lock may not be a symlink')
    if not execute and not path.exists():
        yield;return
    descriptor=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o660) if execute else os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        try:fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:raise RuntimeError('Worker still holds its lock; stop Worker before backup') from error
        yield
    finally:os.close(descriptor)


def create_backup(data, output, execute=False):
    raw_data=Path(data);raw_output=Path(output)
    if raw_data.is_symlink() or raw_output.is_symlink():raise ValueError('backup paths cannot be symlinks')
    root=raw_data.resolve();destination=raw_output.resolve()
    if destination==root or destination.is_relative_to(root) or destination.exists():raise ValueError('backup destination must be new and outside the data volume')
    database=root/'observatory.sqlite3'
    if not database.is_file() or database.is_symlink():raise ValueError('existing regular SQLite database required')
    with worker_lock(root,execute):
        # Dry run stays read-only and creates neither output nor worker.lock.
        before=inventory(root)
        if not execute:
            return {'executed':False,'data':str(root),'output':str(destination),'files':len(before),'note':'Stop Worker; execute holds Worker and SQLite write locks throughout snapshot'}
        destination.parent.mkdir(parents=True,exist_ok=True)
        staging=Path(tempfile.mkdtemp(prefix='.'+destination.name+'-',dir=destination.parent))
        try:
            # This blocks API sampling/CLI mutations, while a separate read connection uses backup().
            with contextlib.closing(sqlite3.connect(database,timeout=3)) as blocker:
                blocker.execute('BEGIN IMMEDIATE')
                before=inventory(root)
                validate_artifacts(blocker,before)
                with contextlib.closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as source,contextlib.closing(sqlite3.connect(staging/'observatory.sqlite3')) as target:
                    source.backup(target)
                    if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('backup database integrity check failed')
                for relative in before:
                    target=staging/relative;target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(root/relative,target)
                    os.chmod(target,0o600)
                if inventory(root)!=before or inventory(staging)!=before:raise RuntimeError('evidence changed while backup was being captured')
                manifest={'schemaVersion':1,'capturedAt':time.time(),'data':str(root),'workerLockHeld':True,'sqliteBackupAPI':True,
                          'databaseSha256':file_hash(staging/'observatory.sqlite3'),'files':before,
                          'buildVolumeIncluded':False,'note':'build-data must be separately archived with worker stopped'}
                (staging/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
                os.chmod(staging/'observatory.sqlite3',0o600);os.chmod(staging/'manifest.json',0o600)
                if destination.exists():raise ValueError('backup destination appeared during snapshot')
                staging.rename(destination)
                blocker.rollback()
            return {'executed':True,'output':str(destination),'files':len(before),'databaseSha256':manifest['databaseSha256']}
        except BaseException:
            shutil.rmtree(staging,ignore_errors=True)
            raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    group=parser.add_mutually_exclusive_group();group.add_argument('--execute',action='store_true');group.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    try:print(json.dumps(create_backup(args.data,args.output,args.execute),indent=2))
    except (OSError,ValueError,RuntimeError,sqlite3.Error) as error:
        print('Backup rejected: '+str(error),file=sys.stderr);return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
