"""Docker mutation boundaries and additive installation, with no real Docker calls."""
import hashlib
import importlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_ns_queue import complete_rh


PROJECT = 'lean-observatory-ns'
RUN = 'ns-f9e8bc5b38b6'
NAME = PROJECT + '-' + RUN


class FakeDocker:
    def __init__(self, container=None):
        self.container = container
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if argv[:3] == ['docker', 'container', 'inspect']:
            if self.container:
                return subprocess.CompletedProcess(argv, 0, json.dumps([self.container]), '')
            return subprocess.CompletedProcess(argv, 1, '', 'Error: No such container: ' + argv[-1])
        if 'run' in argv:
            self.container = own_container()
        if argv[:3] == ['docker', 'container', 'start']:
            self.container['State']['Running'] = True
        return subprocess.CompletedProcess(argv, 0, '', '')


def own_container():
    return {'Id': 'container-ns', 'Name': '/' + NAME, 'Image': 'sha256:' + 'c' * 64,
            'State': {'Running': True, 'ExitCode': 0, 'StartedAt': '2026-11-22T00:00:00Z'},
            'Config': {'Labels': {'com.docker.compose.project': PROJECT,
                                  'io.lean-observatory.ns.run': RUN,
                                  'io.lean-observatory.ns.commit': 'f9e8bc5b38b6e212696e8a30e3e91517af887bbd'}}}


class DockerDriverTests(unittest.TestCase):
    def setUp(self):
        self.Driver = importlib.import_module('ns_queue.driver').DockerDriver
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.fake = FakeDocker()
        self.driver = self.Driver(self.root / 'deployment', self.root / 'data', executor=self.fake, rh_barrier=lambda: True)
        self.state = {'id': RUN, 'rhRunId': '20565ace60c2', 'status': 'QUEUED',
                      'spec': {'commit': 'f9e8bc5b38b6e212696e8a30e3e91517af887bbd'},
                      'budget': {'capUsd': 1, 'hourlyUsd': 3.36, 'minStartSeconds': 300},
                      'rhEvidence': {'persisted': True, 'runId': '20565ace60c2'}}
        self.data = self.root / 'data'
        self.data.mkdir()
        result = json.dumps(complete_rh()).encode()
        (self.data / 'result.json').write_bytes(result)
        (self.data / 'logs.tar.gz').write_bytes(b'complete-log-archive')
        self.state['rhEvidence'].update(resultPath='result.json', resultBytes=len(result),
                                        resultSha256=hashlib.sha256(result).hexdigest(),
                                        logsPath='logs.tar.gz', logsBytes=20,
                                        logsSha256=hashlib.sha256(b'complete-log-archive').hexdigest())
        self.resources = {'cpuCount': 64, 'memoryAvailableBytes': 224 * 1024**3,
                          'diskFreeBytes': 100 * 1024**3}
        self.driver.resources = lambda: self.resources

    def test_zero_budget_rejects_before_resources_or_docker_calls(self):
        self.state['budget']['capUsd'] = 0
        self.driver.resources = lambda: self.fail('budget zero must not inspect resources')
        with self.assertRaisesRegex(ValueError, 'budget'):
            self.driver.launch(self.state)
        self.assertEqual(self.fake.calls, [])

    def test_durable_dependency_identity_required_before_docker_mutation(self):
        self.state['rhEvidence']['runId'] = 'wrong'
        with self.assertRaises(ValueError):
            self.driver.launch(self.state)
        self.assertEqual(self.fake.calls, [])

    def test_inspect_adopts_only_matching_ns_job_without_mutation(self):
        self.fake.container = own_container()
        info = self.driver.inspect(self.state)
        self.assertTrue(info['running'])
        self.assertEqual(info['containerId'], 'container-ns')
        self.assertEqual(self.fake.calls[0][0], ['docker', 'container', 'inspect', NAME])
        self.fake.container['Config']['Labels']['com.docker.compose.project'] = 'lean-observatory'
        with self.assertRaises(RuntimeError):
            self.driver.inspect(self.state)
        self.assertTrue(all(argv[:3] == ['docker', 'container', 'inspect'] for argv, _ in self.fake.calls))

    def test_stop_refuses_foreign_container_and_stops_only_owned_ns_name(self):
        self.fake.container = own_container()
        self.driver.stop(self.state)
        self.assertEqual(self.fake.calls[-1][0], ['docker', 'container', 'stop', '--time', '30', NAME])
        self.fake.container['Config']['Labels']['io.lean-observatory.ns.run'] = 'another-run'
        count = len(self.fake.calls)
        with self.assertRaises(RuntimeError):
            self.driver.stop(self.state)
        self.assertEqual(len(self.fake.calls), count + 1)

    def test_metrics_are_collected_only_for_owned_running_container(self):
        self.fake.container=own_container()
        original=self.fake
        def execute(argv,**kwargs):
            if argv[:2]==['docker','stats']:
                original.calls.append((argv,kwargs))
                return subprocess.CompletedProcess(argv,0,'{"CPUPerc":"125.50%","MemUsage":"1.5GiB / 208GiB"}','')
            return original(argv,**kwargs)
        self.driver.executor=execute
        info=self.driver.metrics(self.state)
        self.assertEqual(info['cpuPercent'],125.5)
        self.assertEqual(info['memoryBytes'],int(1.5*1024**3))
        self.assertEqual(self.fake.calls[-1][0][-1],NAME)
        self.fake.container['Config']['Labels']['io.lean-observatory.ns.run']='foreign'
        count=len(self.fake.calls)
        with self.assertRaises(RuntimeError):self.driver.metrics(self.state)
        self.assertEqual(len(self.fake.calls),count+1)

    def test_rh_worker_detection_only_uses_readonly_inspect(self):
        self.fake.container = own_container()
        self.assertTrue(self.driver.rh_running())
        self.assertEqual(self.fake.calls[-1][0], ['docker', 'container', 'inspect', 'lean-observatory-worker-1'])

    def test_launch_builds_and_starts_only_new_project_and_deterministic_ns_service(self):
        info = self.driver.launch(self.state)
        self.assertTrue(info['running'])
        mutations = [(argv, kw) for argv, kw in self.fake.calls if argv[:3] != ['docker', 'container', 'inspect']]
        self.assertEqual(len(mutations), 2)
        for argv, kw in mutations:
            self.assertEqual(argv[:4], ['docker', 'compose', '-p', PROJECT])
            self.assertIn(str(self.root / 'deployment' / 'compose.ns-worker.yaml'), argv)
            self.assertEqual(argv[-1], 'ns-worker')
            self.assertEqual(kw['env']['NS_CONTAINER_NAME'], NAME)
            self.assertEqual(kw['env']['NS_DATA_ROOT'], str(self.data))
        self.assertIn('build', mutations[0][0])
        self.assertIn('run', mutations[1][0])
        self.assertIn('--name', mutations[1][0])
        self.assertIn(NAME, mutations[1][0])
        self.assertNotIn('up', mutations[1][0])
        self.assertNotIn('--remove-orphans', mutations[1][0])

    def test_existing_container_is_adopted_without_building_or_starting_again(self):
        self.fake.container = own_container()
        self.driver.launch(self.state)
        self.assertTrue(all(argv[:3] == ['docker', 'container', 'inspect'] for argv, _ in self.fake.calls))

    def test_resume_starts_only_owned_stopped_container_after_gates_without_rebuild(self):
        self.fake.container = own_container()
        self.fake.container['State'].update(Running=False, ExitCode=137)
        result = self.driver.launch(self.state)
        self.assertTrue(result['running'])
        mutations = [argv for argv, _ in self.fake.calls if argv[:3] != ['docker', 'container', 'inspect']]
        self.assertEqual(mutations, [['docker', 'container', 'start', NAME]])

    def test_changed_durable_evidence_or_missing_bytes_prevents_any_docker_mutation(self):
        (self.data / 'result.json').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.driver.launch(self.state)
        self.assertEqual(self.fake.calls, [])

    def test_resource_gate_is_rechecked_before_build(self):
        self.resources['memoryAvailableBytes'] = 1
        with self.assertRaisesRegex(ValueError, 'memory'):
            self.driver.launch(self.state)
        self.assertTrue(all(argv[:3] == ['docker', 'container', 'inspect'] for argv, _ in self.fake.calls))

    def test_rh_is_rechecked_after_image_build_and_before_resume(self):
        self.driver.rh_barrier=lambda: False
        with self.assertRaisesRegex(ValueError,'rh_active'):
            self.driver.launch(self.state)
        self.assertFalse(any('run' in argv for argv,_ in self.fake.calls))
        self.fake.container=own_container();self.fake.container['State']['Running']=False
        self.fake.calls.clear()
        with self.assertRaisesRegex(ValueError,'rh_active'):
            self.driver.launch(self.state)
        self.assertFalse(any(argv[:3]==['docker','container','start'] for argv,_ in self.fake.calls))

    def test_build_time_counts_against_budget_before_starting_worker(self):
        with patch('ns_queue.driver.time.monotonic', side_effect=[0, 900]):
            with self.assertRaisesRegex(ValueError, 'budget'):
                self.driver.launch(self.state)
        self.assertFalse(any('run' in argv for argv, _ in self.fake.calls))
        build = next(kw for argv, kw in self.fake.calls if 'build' in argv)
        self.assertLessEqual(build['timeout'], 1071)


class AddonInstallerTests(unittest.TestCase):
    def setUp(self):
        location = Path(__file__).resolve().parents[1] / 'deploy/ns/install.py'
        module_spec = importlib.util.spec_from_file_location('ns_installer', location)
        self.installer = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(self.installer)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for relative in ['ns_queue/a.py', 'deploy/ns/install.py', 'compose.ns.yaml', 'compose.ns-worker.yaml']:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture')

    def receipt(self):
        (self.root / 'reports').mkdir(exist_ok=True)
        report = {'sourceSha256': self.installer.source_fingerprint(self.root),
                  'checks': {name: {'exitCode': 0} for name in ['unit', 'browser', 'compose', 'compile']}}
        (self.root / 'reports/ns-local-acceptance.json').write_text(json.dumps(report))

    def test_missing_and_stale_acceptance_receipt_rejects_before_any_write(self):
        with self.assertRaises(RuntimeError):
            self.installer.install(self.root)
        self.receipt()
        (self.root / 'ns_queue/a.py').write_text('changed')
        with self.assertRaises(RuntimeError):
            self.installer.install(self.root)

    def test_default_dryrun_has_no_side_effects_and_plan_only_starts_lightweight_ns_ui(self):
        self.receipt()
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        plan = self.installer.install(self.root)
        self.assertEqual(plan['budgetCapUsd'], 0)
        self.assertTrue(plan['dryRun'])
        commands = plan['commands']
        compose = [cmd for cmd in commands if cmd[:2] == ['docker', 'compose']]
        self.assertEqual(len(compose), 1)
        self.assertEqual(compose[0][2:4], ['-p', 'lean-observatory-ns'])
        self.assertEqual(compose[0][-2:], ['api', 'nginx'])
        self.assertFalse(any('ns-worker' in cmd or 'lean-observatory-worker-1' in cmd for cmd in commands))
        after = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_execute_refuses_any_directory_other_than_new_fixed_deployment_root(self):
        self.receipt()
        with self.assertRaisesRegex(RuntimeError, '/opt/lean-observatory-ns'):
            self.installer.install(self.root, execute=True)
        self.assertFalse((self.root / '.env').exists())


if __name__ == '__main__':
    unittest.main()
