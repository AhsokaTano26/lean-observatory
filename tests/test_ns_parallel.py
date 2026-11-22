"""Explicit replay overlap never constitutes RH success or bypasses proof checks."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from tests.test_ns_queue import complete_rh, RH_ID, NS_SPEC
from tests.test_ns_controller import RHClientFixture, DriverFixture
from ns_queue.store import QueueStore
from ns_queue.controller import Controller


def replay_rh():
    payload=complete_rh(); run=payload['run']
    run.update(status='running',phase='replay',finishedAt=None)
    run['stages'][-1].update(status='running',exitCode=None,finishedAt=None)
    for audit in run['audits']:audit['replay']='pending'
    run['commands'][-1].update(status='running',exitCode=None,finishedAt=None,
        argv=['lake','-f','lakefile.toml','env','leanchecker','--fresh','Main'])
    run['artifacts']=[];payload['workerRunning']=True
    return payload


class ParallelGateTests(unittest.TestCase):
    def test_replay_admission_requires_explicit_mode_and_complete_compile_audit(self):
        from ns_queue.admission import dependency_gate, validate_admission
        data=replay_rh();state={'rhRunId':RH_ID}
        self.assertEqual(dependency_gate(data,[],state)['decision'],'WAIT')
        state['schedulingMode']='parallel_replay'
        self.assertEqual(dependency_gate(data,[],state)['decision'],'READY')
        validate_admission({'payload':data,'ledger':[]},RH_ID)
        for change in ('compile','audit','replay','command','pin','worker','ledger'):
            altered=copy.deepcopy(data); ledger=[]
            if change=='compile':altered['run']['compile']['succeeded']-=1
            if change=='audit':altered['run']['audits'][0]['axioms']='pending'
            if change=='replay':altered['run']['stages'][-1]['exitCode']=0
            if change=='command':altered['run']['commands'][-1]['argv']=['true']
            if change=='pin':altered['run']['environment']['actualMathlib']='bad'
            if change=='worker':altered['workerRunning']=False
            if change=='ledger':ledger=[{'id':'other','status':'running'}]
            self.assertNotEqual(dependency_gate(altered,ledger,state)['decision'],'READY',change)

    def test_durable_overlap_evidence_is_separate_hash_checked_and_mode_bound(self):
        from ns_queue.admission import verify_parallel
        from ns_queue.gates import start_gate
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'admission.json';blob=json.dumps({'payload':replay_rh(),'ledger':[]}).encode();path.write_bytes(blob)
            state={'rhRunId':RH_ID,'schedulingMode':'parallel_replay','rhEvidence':{'persisted':False},
                'budget':{'capHours':1,'hourlyUsd':3.36},'parallelAdmission':{
                'kind':'rh_replay','runId':RH_ID,'snapshotPath':'admission.json','snapshotBytes':len(blob),
                'snapshotSha256':hashlib.sha256(blob).hexdigest(),'finalSuccess':False}}
            verify_parallel(root,state)
            self.assertTrue(start_gate(state,{'rhActive':True,'cpuCount':64,'memoryAvailableBytes':240*1024**3,'diskFreeBytes':200*1024**3})['allowed'])
            state['schedulingMode']='serial'
            with self.assertRaises(ValueError):verify_parallel(root,state)
            state['schedulingMode']='parallel_replay';path.write_bytes(blob+b' ')
            with self.assertRaises(ValueError):verify_parallel(root,state)


class ParallelControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=QueueStore(self.temp.name);self.store.initialize(NS_SPEC,RH_ID,{'capHours':5,'hourlyUsd':3.36})
        self.store.mutate(lambda s:s.update(schedulingMode='parallel_replay'))
        self.rh=RHClientFixture();self.rh.data=replay_rh();self.driver=DriverFixture()
        self.driver.promotions=0
        def promote(state):self.driver.promotions+=1
        self.driver.promote=promote
        self.controller=Controller(self.store,self.rh,self.driver,notifier=lambda *a:{'status':'sent'},clock=lambda:1800000000.)

    def test_launch_parallel_and_recover_without_claiming_rh_success(self):
        self.controller.tick();state=self.store.snapshot()
        self.assertEqual(state['status'],'RUNNING')
        self.assertEqual(self.driver.launches,1);self.assertEqual(self.rh.downloads,0)
        self.assertFalse(state['rhEvidence']['persisted']);self.assertFalse(state['parallelAdmission']['finalSuccess'])
        self.assertEqual(state['resourceProfile']['memoryBytes'],220000000000)
        self.controller.tick();self.assertEqual(self.driver.launches,1)
        self.assertEqual(self.driver.stops,0)

    def test_rh_failure_stops_only_ns_and_alerts(self):
        self.controller.tick();self.rh.data['run']['status']='failed';self.controller.tick()
        self.assertEqual(self.driver.stops,1)
        self.assertEqual(self.store.snapshot()['reason'],'rh_failed')
        self.assertFalse(self.store.snapshot()['rhEvidence']['persisted'])

    def test_actual_rh_completion_persists_final_evidence_and_promotes_ns(self):
        self.controller.tick();self.rh=RHClientFixture();self.controller.rh=self.rh;self.controller.tick()
        state=self.store.snapshot()
        self.assertTrue(state['rhEvidence']['persisted']);self.assertEqual(self.rh.downloads,1)
        self.assertEqual(self.driver.promotions,1)
        self.assertEqual(state['resourceProfile']['memoryBytes'],250000000000)
        self.assertEqual(self.driver.launches,1)

    def test_transient_observation_does_not_stop_either_job(self):
        import urllib.error
        self.controller.tick()
        def offline(run):raise urllib.error.URLError('offline')
        self.rh.snapshot=offline;self.controller.tick()
        self.assertEqual(self.store.snapshot()['status'],'RUNNING');self.assertEqual(self.driver.stops,0)

class ParallelDriverWorkerTests(unittest.TestCase):
    def test_driver_and_worker_require_identical_durable_admission(self):
        from ns_queue.driver import DockerDriver
        from ns_queue.ns_worker import durable_rh
        from tests.test_ns_driver import FakeDocker, NAME
        with tempfile.TemporaryDirectory() as root:
            store=QueueStore(root);store.initialize(NS_SPEC,RH_ID,{'capHours':5,'hourlyUsd':3.36})
            store.mutate(lambda s:s.update(schedulingMode='parallel_replay'))
            rh=RHClientFixture();rh.data=replay_rh();fake=DriverFixture()
            controller=Controller(store,rh,fake,notifier=lambda *a:{'status':'sent'})
            controller.tick();state=store.snapshot();self.assertTrue(durable_rh(root,state))
            docker=FakeDocker();driver=DockerDriver(Path(root)/'deploy',root,executor=docker,rh_barrier=lambda:True)
            driver.resources=fake.resources;driver.launch(state)
            run=next((args,kw) for args,kw in docker.calls if 'run' in args)
            self.assertEqual(run[1]['env']['NS_MEMORY_BYTES'],'220000000000')
            self.assertEqual(run[1]['env']['NS_CONTAINER_NAME'],NAME)
            self.assertFalse(any('lean-observatory-worker-1' in args for args,kw in docker.calls))
            (Path(root)/state['parallelAdmission']['snapshotPath']).write_text('{}')
            self.assertFalse(durable_rh(root,state))
            docker.calls.clear()
            with self.assertRaises(ValueError):driver.launch(state)
            self.assertEqual(docker.calls,[])

    def test_host_cli_records_explicit_authorization_and_locks_after_start(self):
        from ns_queue.control import main
        import contextlib,io
        with tempfile.TemporaryDirectory() as root:
            store=QueueStore(root);store.initialize(NS_SPEC,RH_ID,{'capHours':0})
            with contextlib.redirect_stdout(io.StringIO()):
                main(['--root',root,'set-scheduling','--mode','parallel-replay'])
            self.assertEqual(store.snapshot()['schedulingMode'],'parallel_replay')
            self.assertIsNotNone(store.snapshot()['schedulingAuthorizedAt'])
            store.mutate(lambda s:s.update(startedAt=1800000000.))
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                main(['--root',root,'set-scheduling','--mode','serial'])

class ParallelTerminalTests(ParallelControllerTests):
    def test_final_rh_is_archived_after_ns_completes_or_pauses(self):
        for status in ('CHECKS_COMPLETED','PAUSED','FAILED'):
            with self.subTest(status=status):
                self.setUp();self.controller.tick()
                self.store.mutate(lambda s:s.update(status=status))
                self.controller.rh=RHClientFixture();self.controller.tick()
                self.assertTrue(self.store.snapshot()['rhEvidence']['persisted'])
                self.assertEqual(self.store.snapshot()['rh']['status'],'checks_completed')
                self.assertEqual(self.store.snapshot()['status'],status)

    def test_later_rh_failure_preserves_ns_terminal_result(self):
        self.controller.tick();self.store.mutate(lambda s:s.update(status='CHECKS_COMPLETED'))
        self.rh.data['run']['status']='failed';self.controller.tick()
        self.assertEqual(self.store.snapshot()['status'],'CHECKS_COMPLETED')
        self.assertEqual(self.driver.stops,0)

    def test_resource_promotion_cannot_use_pending_admission(self):
        from ns_queue.driver import DockerDriver
        from tests.test_ns_driver import FakeDocker
        self.controller.tick();docker=FakeDocker()
        driver=DockerDriver(self.temp.name,self.temp.name,executor=docker)
        with self.assertRaisesRegex(ValueError,'final evidence'):driver.promote(self.store.snapshot())
        self.assertEqual(docker.calls,[])

    def test_unreachable_and_stopped_rh_preserves_ns_terminal_result(self):
        import urllib.error
        self.controller.tick();self.store.mutate(lambda s:s.update(status='CHECKS_COMPLETED'))
        def offline(run):raise urllib.error.URLError('offline')
        self.rh.snapshot=offline;self.driver.rh_running=lambda:False;self.controller.tick()
        self.assertEqual(self.store.snapshot()['status'],'CHECKS_COMPLETED')
        self.assertEqual(self.driver.stops,0)

    def test_hard_budget_pause_still_archives_later_rh_success(self):
        from tests.test_ns_budget import server_budget
        self.controller.tick();self.store.mutate(lambda s:s.update(budget=server_budget()))
        self.controller.rh=RHClientFixture();self.controller.tick()
        self.assertTrue(self.store.snapshot()['rhEvidence']['persisted'])
        self.assertEqual(self.driver.stops,1)
        self.assertEqual(self.store.snapshot()['status'],'PAUSED')

class ParallelLaunchFailureTests(ParallelControllerTests):
    def test_image_build_failure_does_not_label_valid_rh_admission_failed(self):
        def fail(state):raise RuntimeError('NS image build failed: plugin unavailable')
        self.driver.launch=fail;self.controller.tick()
        state=self.store.snapshot()
        self.assertEqual(state['status'],'PAUSED')
        self.assertEqual(state['reason'],'launch_error')
        self.assertFalse(state['rhEvidence']['persisted'])
        self.assertFalse(state['parallelAdmission']['finalSuccess'])
