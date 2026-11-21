import copy
import gzip
import hashlib
import io
import json
import tarfile
import tempfile
import unittest
import urllib.error
from pathlib import Path

from ns_queue.store import QueueStore
from ns_queue.controller import Controller, controller_lease
from tests.test_ns_queue import complete_rh, NS_SPEC, RH_ID


class RHClientFixture:
    def __init__(self):
        self.data = complete_rh()
        self.result = json.dumps({'run': copy.deepcopy(self.data['run'])}).encode()
        entry = self.data['run']['artifacts'][0]
        entry.update(sha256=hashlib.sha256(self.result).hexdigest(), bytes=len(self.result))
        self.other_active = False
        self.corrupt = False
        self.downloads = 0
    def snapshot(self, run): return copy.deepcopy(self.data)
    def ledger(self):
        return [{'id': 'another', 'status': 'running'}] if self.other_active else []
    def result_bytes(self, run): return b'corrupt' if self.corrupt else self.result
    def download_logs(self, run, path):
        self.downloads += 1
        with tarfile.open(path, 'w:gz') as tar:
            for name in ['events.ndjson', 'snapshot.json']:
                data = b'{}\n'; item = tarfile.TarInfo(name); item.size = len(data)
                tar.addfile(item, io.BytesIO(data))


class DriverFixture:
    def __init__(self): self.job = None; self.launches = 0; self.stops = 0
    def rh_running(self): return True
    def resources(self):
        return dict(cpuCount=64, memoryAvailableBytes=240*1024**3, diskFreeBytes=1000*1024**3)
    def inspect(self, state): return self.job
    def launch(self, state):
        self.launches += 1
        self.job = dict(running=True, exitCode=0, containerId='own-ns-container')
        return self.job
    def stop(self, state): self.stops += 1; self.job['running'] = False


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = QueueStore(self.temp.name); self.store.initialize(NS_SPEC, RH_ID, {'capUsd': 0})
        self.rh = RHClientFixture(); self.driver = DriverFixture(); self.notices = []
        self.now = 1800000000.
        def notify(url, alert): self.notices.append(alert); return {'status': 'accepted', 'error': None}
        self.notify = notify
        self.controller = Controller(self.store, self.rh, self.driver, notifier=notify, clock=lambda: self.now)

    def test_running_rh_remains_queued_without_downloading_or_launching_ns(self):
        self.rh.data['run']['status'] = 'running'
        for _ in range(3): self.controller.tick()
        self.assertEqual(self.store.snapshot()['status'], 'QUEUED')
        self.assertEqual(self.rh.downloads, 0); self.assertEqual(self.driver.launches, 0)

    def test_complete_rh_is_persisted_then_zero_budget_pauses_and_alerts_once(self):
        self.controller.tick()
        state = self.store.snapshot()
        self.assertEqual((state['status'], state['reason']), ('PAUSED', 'budget'))
        self.assertTrue(state['rhEvidence']['persisted'])
        self.assertTrue((Path(self.temp.name)/state['rhEvidence']['resultPath']).is_file())
        self.assertEqual(self.driver.launches, 0)
        self.controller.tick(); self.controller.tick()
        self.assertEqual(self.rh.downloads, 1); self.assertEqual(len(self.notices), 1)
        self.assertEqual(self.store.outbox(), [])

    def test_failed_rh_pauses_ns_and_persists_one_notification(self):
        self.rh.data['run']['status'] = 'failed'
        self.controller.tick(); self.controller.tick()
        self.assertEqual(self.store.snapshot()['reason'], 'rh_failed')
        self.assertEqual(len(self.notices), 1); self.assertEqual(self.driver.launches, 0)

    def test_unreachable_api_and_stopped_rh_pauses_and_notifies(self):
        def unavailable(run):raise urllib.error.URLError('offline')
        self.rh.snapshot=unavailable;self.driver.rh_running=lambda:False
        self.controller.tick()
        self.assertEqual(self.store.snapshot()['reason'],'rh_interrupted')
        self.assertEqual(len(self.notices),1)
        self.assertEqual(self.driver.launches,0)

    def test_paused_controller_keeps_liveness_without_advancing_work(self):
        self.store.mutate(lambda s:s.update(status='PAUSED',reason='budget'))
        self.controller.tick()
        state=self.store.snapshot()
        self.assertEqual(state['controllerHeartbeat'],self.now)
        self.assertEqual(state['status'],'PAUSED')
        self.assertEqual(self.driver.launches,0)

    def test_bad_result_hash_blocks_without_launching(self):
        self.rh.corrupt = True
        self.controller.tick()
        self.assertEqual(self.store.snapshot()['status'], 'PAUSED')
        self.assertFalse(self.store.snapshot()['rhEvidence']['persisted'])
        self.assertEqual(self.driver.launches, 0)

    def test_restart_adopts_existing_job_without_repeating_successful_steps(self):
        self.store.mutate(lambda s:s['budget'].update(capHours=10))
        self.controller.tick()
        self.assertEqual(self.driver.launches, 1)
        self.store.mutate(lambda s:s['stages'][0].update(status='PASSED', exitCode=0))
        restarted = Controller(QueueStore(self.temp.name), self.rh, self.driver,
                               notifier=self.notify, clock=lambda:self.now)
        restarted.tick()
        self.assertEqual(self.driver.launches, 1)
        self.assertEqual(self.store.snapshot()['stages'][0]['status'], 'PASSED')

    def test_another_run_appearing_during_persistence_blocks_start(self):
        self.store.mutate(lambda s:s['budget'].update(capHours=10))
        original = self.rh.download_logs
        def download(run, path): original(run, path); self.rh.other_active = True
        self.rh.download_logs = download
        self.controller.tick()
        self.assertEqual(self.driver.launches, 0)
        self.assertEqual(self.store.snapshot()['status'], 'QUEUED')

    def test_budget_stop_targets_only_own_worker(self):
        self.store.mutate(lambda s:s['budget'].update(capHours=1/12))
        self.controller.tick(); self.now += 400; self.controller.tick()
        self.assertEqual(self.driver.stops, 1)
        self.assertEqual(self.store.snapshot()['reason'], 'budget')

    def test_shared_rental_budget_warns_and_expires_while_rh_keeps_running(self):
        from tests.test_ns_budget import START,server_budget
        self.rh.data['run']['status']='running'
        self.store.mutate(lambda s:s.update(budget=server_budget()))
        self.now=START+19.5*3600
        self.controller.tick();self.controller.tick()
        self.assertEqual(len(self.notices),1)
        self.assertEqual(self.store.snapshot()['budget']['remainingHours'],0.5)
        self.now=START+19.9*3600;self.controller.tick()
        self.assertEqual(len(self.notices),2)
        self.now=START+20*3600;self.controller.tick();self.controller.tick()
        state=self.store.snapshot()
        self.assertEqual((state['status'],state['reason']),('PAUSED','budget_deadline'))
        self.assertEqual(len(self.notices),3)
        self.assertEqual(self.driver.stops,0);self.assertEqual(self.driver.launches,0)

    def test_shared_deadline_stops_only_own_running_ns(self):
        from tests.test_ns_budget import START,server_budget
        self.driver.job={'running':True,'containerId':'own-ns'}
        self.store.mutate(lambda s:s.update(status='RUNNING',budget=server_budget(),startedAt=START+3600))
        self.now=START+20*3600
        self.controller.tick();self.controller.tick()
        self.assertEqual(self.driver.stops,1)
        self.assertEqual(self.store.snapshot()['reason'],'budget_deadline')
        self.assertEqual(len(self.notices),1)

    def test_notify_only_expired_window_automatically_starts_ns_once_after_rh(self):
        from tests.test_ns_budget import START,server_budget
        self.store.mutate(lambda s:s.update(budget={**server_budget(),'enforcement':'notify_only'}))
        self.now=START+21*3600
        self.rh.data['run']['status']='running';self.controller.tick()
        self.assertEqual(self.store.snapshot()['status'],'QUEUED')
        self.assertEqual(self.driver.stops,0)
        self.rh.data['run']['status']='checks_completed'
        self.driver.resources=lambda:{'cpuCount':1,'memoryAvailableBytes':1,'diskFreeBytes':1}
        self.controller.tick();self.controller.tick()
        self.assertEqual(self.store.snapshot()['status'],'RUNNING')
        self.assertEqual(self.driver.launches,1);self.assertEqual(self.driver.stops,0)
        restarted=Controller(QueueStore(self.temp.name),self.rh,self.driver,notifier=self.notify,clock=lambda:self.now)
        restarted.tick()
        self.assertEqual(self.driver.launches,1);self.assertEqual(self.driver.stops,0)
        self.assertEqual(self.store.snapshot()['budget']['rentalStartedAt'],START)

    def test_timer_refresh_cannot_overwrite_concurrent_admin_hours_change(self):
        from tests.test_ns_budget import START,server_budget
        self.store.mutate(lambda s:s.update(budget={**server_budget(),'enforcement':'notify_only'}))
        self.now=START+3600
        original=self.store.mutate;changed=[False]
        def race(fn,event='updated'):
            if not changed[0]:
                changed[0]=True;original(lambda s:s['budget'].update(capHours=24))
            return original(fn,event)
        self.store.mutate=race
        self.controller.budget_tick()
        self.assertEqual(self.store.snapshot()['budget']['capHours'],24)

    def test_advisory_sampler_failure_cannot_block_handoff(self):
        from tests.test_ns_budget import START,server_budget
        self.store.mutate(lambda s:s.update(budget={**server_budget(),'enforcement':'notify_only'}))
        self.now=START+21*3600
        def unavailable():raise OSError('disk sampler unavailable')
        self.driver.resources=unavailable
        self.controller.tick()
        self.assertEqual(self.driver.launches,1)
        self.assertEqual(self.store.snapshot()['status'],'RUNNING')

    def test_single_controller_lease_is_exclusive(self):
        with controller_lease(self.temp.name):
            with self.assertRaises(RuntimeError):
                with controller_lease(self.temp.name): pass

    def test_lost_launch_ack_adopts_instead_of_starting_a_duplicate(self):
        self.store.mutate(lambda s:s['budget'].update(capHours=10))
        launch=self.driver.launch
        def ambiguous(state): launch(state); raise TimeoutError('client acknowledgement lost')
        self.driver.launch=ambiguous
        self.controller.tick(); self.controller.tick()
        self.assertEqual(self.driver.launches,1)
        self.assertEqual(self.store.snapshot()['status'],'RUNNING')

    def test_worker_persisted_failure_is_not_silently_skipped(self):
        self.store.mutate(lambda s:s.update(status='PAUSED',reason='worker_failed',
                            execution='INCOMPLETE',startedAt=self.now,error='kernel rejected proof'))
        self.controller.tick(); self.controller.tick()
        self.assertEqual(len(self.notices),1)
        self.assertIn('kernel rejected proof',self.notices[0]['message'])


if __name__ == '__main__': unittest.main()
