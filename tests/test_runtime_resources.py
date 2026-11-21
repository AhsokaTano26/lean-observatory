import copy
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


def module():
    path=Path(__file__).resolve().parents[1]/'deploy/ns/update_resources.py'
    spec=importlib.util.spec_from_file_location('resources',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


class RuntimeResourcesTests(unittest.TestCase):
    def setUp(self):
        self.row={'Id':'worker-id','Name':'/lean-observatory-worker-1','Image':'image-id','State':{'Running':True,'Pid':123,'StartedAt':'original-start'},
                  'Config':{'Labels':{'com.docker.compose.project':'lean-observatory','com.docker.compose.service':'worker'},'Cmd':['python3','-m','backend.worker']},
                  'Mounts':[{'Destination':'/data','Source':'existing-volume'}],
                  'HostConfig':{'NanoCpus':48*10**9,'CpusetCpus':'8-55','Memory':208*1024**3,'MemorySwap':208*1024**3,'RestartPolicy':{'Name':'unless-stopped'}}}
        self.calls=[]
        def execute(argv,**kwargs):
            self.calls.append(argv)
            if argv[:2]==['docker','update']:
                self.row['HostConfig'].update(NanoCpus=60*10**9,CpusetCpus='4-63',Memory=250000000000,MemorySwap=250000000000)
                return subprocess.CompletedProcess(argv,0,'worker','')
            return subprocess.CompletedProcess(argv,0,json.dumps([self.row]),'')
        self.execute=execute
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)

    def test_live_resize_preserves_pid_image_command_mounts_and_all_other_settings(self):
        m=module();before=copy.deepcopy(self.row)
        result=m.configure('worker-id',self.temp.name,execute=True,executor=self.execute)
        self.assertEqual(result['after']['pid'],123)
        self.assertEqual(result['after']['startedAt'],'original-start')
        self.assertEqual(self.row['Config'],before['Config']);self.assertEqual(self.row['Mounts'],before['Mounts'])
        mutations=[c for c in self.calls if c[:2]==['docker','update']]
        self.assertEqual(len(mutations),1)
        self.assertEqual(mutations[0],['docker','update','--cpus','60','--cpuset-cpus','4-63','--memory','250000000000','--memory-swap','250000000000','worker-id'])
        self.assertTrue((Path(self.temp.name)/'compose.resources.runtime.yaml').is_file())
        self.assertNotIn('restart',str(self.calls));self.assertNotIn('stop',str(self.calls))

    def test_new_rh_tasks_support_sixty_compiler_threads(self):
        from backend.store import Store
        store=Store(self.temp.name)
        state=store.create('mock')
        self.assertEqual(state['compile']['jobs'],60)
        store.control(state['id'],'cancel')
        with self.assertRaises(ValueError):store.create('mock',jobs=61)
        self.assertEqual(store.create('mock',jobs=60)['compile']['jobs'],60)

    def test_wrong_identity_and_dryrun_cannot_mutate_container(self):
        m=module()
        with self.assertRaises(ValueError):m.configure('another',self.temp.name,execute=True,executor=self.execute)
        m.configure('worker-id',self.temp.name,executor=self.execute)
        self.assertTrue(all(c[:2]==['docker','inspect'] for c in self.calls))
        self.assertEqual(list(Path(self.temp.name).iterdir()),[])
