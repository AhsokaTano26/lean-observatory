import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def module():
    p=ROOT/'deploy/ns/activate_proxy.py';spec=importlib.util.spec_from_file_location('proxy',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


class ProxyTests(unittest.TestCase):
    def test_root_and_project_namespaces_are_isolated_and_idempotent(self):
        m=module();original=(ROOT/'deploy/nginx-tls.conf').read_text()
        patched=m.render(original)
        self.assertIn('server lean-observatory-api-1:8787 resolve',patched)
        self.assertIn('server lean-observatory-ns-api-1:8792 resolve',patched)
        self.assertIn('location = / {',patched);self.assertIn('http://observatory_ns/entry',patched)
        self.assertIn('location ^~ /rh/',patched);self.assertIn('proxy_pass http://observatory/;',patched)
        self.assertIn('location ^~ /ns/',patched);self.assertIn('proxy_buffering off',patched)
        self.assertEqual(m.render(patched),patched)

    def setup_fake(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.config=Path(self.tmp.name)/'nginx.conf';self.config.write_text((ROOT/'deploy/nginx-tls.conf').read_text())
        self.row={'Id':'nginx-id','Name':'/lean-observatory-nginx-1','Image':'image-id',
                  'Config':{'Labels':{'com.docker.compose.project':'lean-observatory','com.docker.compose.service':'nginx'}},
                  'State':{'Running':True,'Pid':300,'StartedAt':'same-start'},'NetworkSettings':{'Networks':{'lean-observatory_default':{}}}}
        self.calls=[];self.fail_validation=False
        def execute(argv,**kwargs):
            self.calls.append(argv)
            if argv[:2]==['docker','inspect']:return subprocess.CompletedProcess(argv,0,json.dumps([self.row]),'')
            if argv[:2]==['docker','run'] and self.fail_validation:raise subprocess.CalledProcessError(1,argv,'','bad configuration')
            if argv[:3]==['docker','network','connect']:self.row['NetworkSettings']['Networks']['lean-observatory-ns_default']={}
            if argv[:3]==['docker','network','disconnect']:self.row['NetworkSettings']['Networks'].pop('lean-observatory-ns_default',None)
            return subprocess.CompletedProcess(argv,0,'','')
        return execute

    def test_live_route_update_only_reloads_router_and_keeps_master_identity(self):
        execute=self.setup_fake();m=module()
        result=m.activate('nginx-id',self.config,Path(self.tmp.name)/'ops',execute=True,executor=execute)
        self.assertEqual(result['before'],result['after']);self.assertEqual(result['after']['pid'],300)
        self.assertTrue((Path(self.tmp.name)/'ops/compose.ns-route.runtime.yaml').exists())
        self.assertTrue(any(c[:3]==['docker','network','connect'] for c in self.calls))
        self.assertTrue(any(c[-3:]==['nginx','-s','reload'] for c in self.calls))
        self.assertFalse(any('restart' in c or 'stop' in c for c in self.calls))

    def test_lost_network_ack_rolls_back_attachment_before_old_config(self):
        execute=self.setup_fake();m=module();before=self.config.read_bytes()
        def ambiguous(argv,**kwargs):
            result=execute(argv,**kwargs)
            if argv[:3]==['docker','network','connect']:raise TimeoutError('ack lost')
            return result
        with self.assertRaises(TimeoutError):m.activate('nginx-id',self.config,Path(self.tmp.name)/'ops',execute=True,executor=ambiguous)
        self.assertEqual(self.config.read_bytes(),before)
        self.assertNotIn('lean-observatory-ns_default',self.row['NetworkSettings']['Networks'])

    def test_invalid_candidate_does_not_change_live_config_or_network(self):
        execute=self.setup_fake();self.fail_validation=True;m=module();before=self.config.read_bytes()
        with self.assertRaises(subprocess.CalledProcessError):m.activate('nginx-id',self.config,Path(self.tmp.name)/'ops',execute=True,executor=execute)
        self.assertEqual(self.config.read_bytes(),before)
        self.assertNotIn('lean-observatory-ns_default',self.row['NetworkSettings']['Networks'])
        self.assertFalse(any(c[-3:]==['nginx','-s','reload'] for c in self.calls))
