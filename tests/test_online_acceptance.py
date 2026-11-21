import unittest
from scripts import online_acceptance as online

SHA='a'*64
NOW=1700000000

def state():
    return {'deployment':{'sourceSha256':SHA},'capabilities':{'readOnly':True},
            'run':{'id':None,'mode':'real','status':'waiting','commands':[],'artifacts':[]},
            'metrics':{'source':'host_agent','stale':False,'sampledAt':NOW-3,'cpuCount':64,
                       'memoryTotalBytes':256*1024**3,'diskTotalBytes':2600*1024**3,'diskUsedBytes':20*1024**3}}

def containers():
    out=[]
    for service,cpu,memory in [('api',2,2*1024**3),('nginx',1,256*1024**2),('worker',60,250000000000)]:
        out.append({'Config':{'Labels':{'com.docker.compose.service':service,'com.docker.compose.project':'lean-observatory','io.lean-observatory.source-sha256':SHA},
                              'Env':['SOURCE_SHA256='+SHA,'ENABLE_REAL=0']},
                    'AppArmorProfile':'lean-observatory-worker','Id':'worker-container-'+service,'Image':'sha256:worker-image-'+service,'ImageLabels':{'io.lean-observatory.source-sha256':SHA},'State':{'Running':True},'HostConfig':{'NanoCpus':cpu*10**9,'Memory':memory,'MemorySwap':memory,
                    'CpusetCpus':'4-63' if service=='worker' else '', 'PidsLimit':1024 if service=='worker' else 128},
                    'Mounts':[{'Destination':'/approval','RW':False}] if service=='worker' else []})
    return out

class OnlineAcceptanceTests(unittest.TestCase):
    def test_valid_clean_state_and_source_checked(self):
        online.validate_state(state(),[],SHA,now=NOW)
        bad=state();bad['deployment']['sourceSha256']='b'*64
        with self.assertRaisesRegex(ValueError,'source'): online.validate_state(bad,[],SHA,now=NOW)

    def test_stale_future_local_and_small_host_metrics_rejected(self):
        for change in [{'source':'local_host'},{'sampledAt':NOW-21},{'sampledAt':NOW+61}, {'stale':True},
                       {'cpuCount':63},{'cpuCount':float('nan')},{'diskUsedBytes':float('nan')},{'memoryTotalBytes':239*1024**3},{'diskUsedBytes':2400*1024**3}]:
            with self.subTest(change=change):
                bad=state();bad['metrics'].update(change)
                with self.assertRaises(ValueError): online.validate_state(bad,[],SHA,now=NOW)

    def test_mock_history_active_or_dirty_state_rejected(self):
        for change in [{'mode':'mock'},{'id':'old'},{'status':'queued'},{'commands':[{}]},{'artifacts':[{}]}]:
            with self.subTest(change=change):
                bad=state();bad['run'].update(change)
                with self.assertRaises(ValueError): online.validate_state(bad,[],SHA,now=NOW)
        with self.assertRaises(ValueError): online.validate_state(state(),[{'id':'mock','mode':'mock','status':'cancelled'}],SHA,now=NOW)
        with self.assertRaises(ValueError): online.validate_state(state(),{},SHA,now=NOW)

    def test_resume_checks_exact_stopped_real_run_without_erasing_history(self):
        data=state();data['run'].update(id='run123',status='interrupted',commands=[{'exitCode':1}],artifacts=[{'name':'log'}])
        runs=[{'id':'run123','mode':'real','status':'interrupted'},{'id':'older','mode':'real','status':'failed'}]
        online.validate_state(data,runs,SHA,now=NOW,resume_run='run123')
        for status in ['paused','failed','resource_exhausted']:
            data['run']['status']=status;runs[0]['status']=status
            online.validate_state(data,runs,SHA,now=NOW,resume_run='run123')
        for bad_runs in [runs+[{'id':'other','mode':'real','status':'running'}],runs+[{'id':'mock','mode':'mock','status':'cancelled'}],[]]:
            with self.assertRaises(ValueError):online.validate_state(data,bad_runs,SHA,now=NOW,resume_run='run123')
        with self.assertRaises(ValueError):online.validate_state(data,runs,SHA,now=NOW,resume_run='wrong')
        data['run']['status']='running'
        with self.assertRaises(ValueError):online.validate_state(data,runs,SHA,now=NOW,resume_run='run123')

    def test_resource_gate_requires_running_exact_limits_disabled_real_and_readonly_receipt(self):
        online.validate_resources(containers(),SHA)
        for key,value in [('NanoCpus',47*10**9),('Memory',207*1024**3),('CpusetCpus','0-47'),('MemorySwap',-1)]:
            bad=containers();bad[-1]['HostConfig'][key]=value
            with self.assertRaises(ValueError): online.validate_resources(bad,SHA)
        for mutate in [lambda x:x[-1]['Config'].update(Env=['SOURCE_SHA256='+SHA,'ENABLE_REAL=1']),
                       lambda x:x[-1]['Mounts'][0].update(RW=True),lambda x:x[0]['State'].update(Running=False),lambda x:x[0]['ImageLabels'].update({'io.lean-observatory.source-sha256':'b'*64})]:
            bad=containers();mutate(bad)
            with self.assertRaises(ValueError): online.validate_resources(bad,SHA)

    def test_production_requires_exact_apparmor_container_profile(self):
        for profile in ['', 'unconfined', 'docker-default', 'lean-observatory-worker (complain)']:
            data=containers();data[-1]['AppArmorProfile']=profile
            with self.assertRaisesRegex(ValueError,'AppArmor'):online.validate_resources(data,SHA)

    def test_host_apparmor_requires_enabled_enforced_and_exact_profile_bytes(self):
        online.validate_apparmor('Y', 'lean-observatory-worker (enforce)\n', 'b'*64, 'b'*64)
        for enabled,loaded,digest in [('N','lean-observatory-worker (enforce)\n','b'*64),
                                      ('Y','lean-observatory-worker (complain)\n','b'*64),
                                      ('Y','other-worker (enforce)\n','b'*64),
                                      ('Y','lean-observatory-worker (enforce)\n','c'*64)]:
            with self.assertRaises(ValueError):online.validate_apparmor(enabled,loaded,'b'*64,digest)

    def test_tiny_fixture_receipt_is_fresh_source_script_profile_and_worker_bound(self):
        worker=containers()[-1]
        fixture={'passed':True,'productionEligible':False,'environment':'production-worker-profile','scope':'tiny-only',
                 'checkedAt':NOW-3,'sourceSha256':SHA,'scriptSha256':'b'*64,'profileSha256':'c'*64,
                 'AppArmorProfile':'lean-observatory-worker','workerContainerId':'worker-container-worker',
                 'workerImageId':'sha256:worker-image-worker','proofReproduction':'NOT_RUN','exitCode':0,'logSha256':'d'*64}
        online.validate_worker_fixture(fixture,SHA,'b'*64,'c'*64,worker,now=NOW)
        for change in [{'passed':False},{'environment':'not_production'},{'scope':'full-proof'},
                       {'checkedAt':NOW-901},{'sourceSha256':'f'*64},{'scriptSha256':'f'*64},
                       {'profileSha256':'f'*64},{'AppArmorProfile':'unconfined'},
                       {'workerContainerId':'old-container'},{'workerImageId':'old-image'},{'exitCode':1}]:
            with self.subTest(change=change):
                bad=dict(fixture);bad.update(change)
                with self.assertRaises(ValueError):online.validate_worker_fixture(bad,SHA,'b'*64,'c'*64,worker,now=NOW)

    def test_fixture_output_requires_kernel_filesystem_and_both_cleanup_results(self):
        summary=b'{"kernelFixture":"passed","filesystemIsolation":"passed","detachedCleanup":"passed","proofReproduction":"NOT_RUN"}'
        ending=b'\nparent-death guard passed (including stopped process group)\n'
        online.validate_fixture_output(summary+ending)
        for output in [summary,b'{}'+ending,summary.replace(b'"filesystemIsolation":"passed"',b'"filesystemIsolation":"failed"')+ending,summary.replace(b'NOT_RUN',b'passed')+ending]:
            with self.assertRaises(ValueError):online.validate_fixture_output(output)

    def test_methods_must_be_405_allow_get(self):
        online.validate_method(405,{'Allow':'GET'})
        for status,headers in [(200,{}),(400,{}),(405,{}),(405,{'Allow':'GET, POST'})]:
            with self.assertRaises(ValueError): online.validate_method(status,headers)

    def test_sse_snapshot_checks_host_and_source(self):
        online.validate_sse('text/event-stream',b'event: snapshot\ndata: '+__import__('json').dumps(state()).encode()+b'\n\n',SHA,now=NOW)
        bad=state();bad['metrics']['source']='mock_host'
        with self.assertRaises(ValueError): online.validate_sse('text/event-stream',b'event: snapshot\ndata: '+__import__('json').dumps(bad).encode()+b'\n\n',SHA,now=NOW)
        with self.assertRaises(ValueError): online.validate_sse('application/json',b'{}',SHA,now=NOW)

    def test_only_exact_production_url_accepted(self):
        online.validate_url('https://lean.tano.asia')
        for url in ['http://lean.tano.asia','https://localhost','https://lean.tano.asia:444','https://user@lean.tano.asia','https://lean.tano.asia/x']:
            with self.assertRaises(ValueError): online.validate_url(url)

if __name__=='__main__': unittest.main()
