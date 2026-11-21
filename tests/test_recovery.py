import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from backend.store import Store
from backend.runner import CommandRunner, CommandError
from backend.integrity import safe_extract

class RecoveryTests(unittest.TestCase):
    def test_restart_marks_unfinished_evidence_without_inventing_exit(self):
        from backend.worker import work
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d));run=store.create('real')
            completed=dict(argv=['completed'],stage='dependencies',startedAt=1,finishedAt=2,exitCode=0)
            previously_interrupted=dict(argv=['earlier interruption'],stage='compile',startedAt=2,
                                        finishedAt=None,exitCode=None,status='interrupted',
                                        observedStoppedAt=3,terminationCause='worker_restart_exit_unknown')
            unfinished=dict(argv=['unfinished'],stage='compile',startedAt=3,finishedAt=None,exitCode=None)
            def running(state):
                state.update(status='running',phase='compile',workerHeartbeat=1,
                             commands=[completed,previously_interrupted,unfinished])
                state['stages'][3].update(status='running',startedAt=3,finishedAt=None,exitCode=None)
            store.mutate(run['id'],running)
            stop=threading.Event();stop.set()
            work(store,stop=stop)
            recovered=store.raw(run['id']);command=recovered['commands'][2]
            self.assertEqual(recovered['commands'][0],completed)
            self.assertEqual(recovered['commands'][1],previously_interrupted)
            self.assertEqual(command.get('status'),'interrupted')
            self.assertEqual(command.get('terminationCause'),'worker_restart_exit_unknown')
            self.assertIsInstance(command.get('observedStoppedAt'),(int,float))
            self.assertIsNone(command['exitCode'])
            self.assertIsNone(command['finishedAt'])
            stage=recovered['stages'][3]
            self.assertEqual(stage['status'],'interrupted')
            self.assertIsNone(stage['exitCode'])
            self.assertIsNone(stage['finishedAt'])

    def test_cancel_during_restart_scan_is_not_resurrected(self):
        from backend.worker import work
        for status in ('running','paused'):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as d:
                store=Store(Path(d));run=store.create('mock')
                store.mutate(run['id'],lambda state:state.update(status=status))
                original=store.active_runs;selected=False
                def cancel_after_read():
                    nonlocal selected
                    result=original()
                    if not selected:
                        selected=True
                        store.control(run['id'],'cancel')
                    return result
                stop=threading.Event();stop.set()
                with patch.object(store,'active_runs',side_effect=cancel_after_read):
                    work(store,stop=stop)
                recovered=store.raw(run['id'])
                self.assertEqual(recovered['status'],'cancelled')
                self.assertEqual(recovered['desired'],'cancelled')

    def test_cancel_between_scheduler_read_and_tick_cannot_resurrect_mock(self):
        from backend.worker import work
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d));s=store.create('mock');stop=threading.Event()
            original=store.active_runs;calls=0
            def stale_selection():
                nonlocal calls
                calls+=1;selected=original()
                if calls==2:
                    store.control(s['id'],'cancel')
                    stop.set()
                return selected
            with patch.object(store,'active_runs',side_effect=stale_selection):
                work(store,stop=stop,interval=.01)
            cancelled=store.raw(s['id'])
            self.assertEqual(cancelled['status'],'cancelled')
            self.assertEqual(cancelled['mockTicks'],0)
            self.assertIsNotNone(store.create('mock')['id'])

    def test_cancel_kills_command_and_records_actual_exit(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)); s=store.create('real'); errors=[]
            def run():
                try: CommandRunner(store,s['id']).run([sys.executable,'-c','import time;print("started",flush=True);time.sleep(60)'],Path(d),'compile')
                except CommandError as e: errors.append(e)
            thread=threading.Thread(target=run);thread.start()
            deadline=time.time()+5
            while not store.logs(s['id'],query='started') and time.time()<deadline: time.sleep(.02)
            store.control(s['id'],'cancel');thread.join(12)
            self.assertFalse(thread.is_alive());self.assertTrue(errors)
            self.assertNotEqual(store.raw(s['id'])['commands'][-1]['exitCode'],0)

    def test_worker_restart_requires_explicit_resume(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d));s=store.create('mock')
            store.mutate(s['id'],lambda x:x.update(status='running',workerHeartbeat=1))
            worker=subprocess.Popen([sys.executable,'-m','backend.worker','--data',d,'--interval','.02'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                deadline=time.time()+5
                while store.raw(s['id'])['status']!='interrupted' and time.time()<deadline:time.sleep(.02)
                self.assertEqual(store.raw(s['id'])['status'],'interrupted')
                self.assertIn('Worker 重启',store.raw(s['id'])['error'])
                self.assertEqual(store.raw(s['id'])['compile']['succeeded'],0)
            finally: worker.terminate();out,err=worker.communicate(timeout=5)
            self.assertEqual(err,b'')

    def test_resource_resume_lowers_concurrency_without_losing_progress(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d));s=store.create('real',jobs=48)
            def exhaust(x):
                x['status']='resource_exhausted';x['compile']['succeeded']=1500
            store.mutate(s['id'],exhaust)
            r=store.control(s['id'],'resume')
            self.assertEqual(r['compile']['jobs'],24)
            self.assertEqual(r['compile']['succeeded'],1500)
            self.assertEqual(r['status'],'queued')
