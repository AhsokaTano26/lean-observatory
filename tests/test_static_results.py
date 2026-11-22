import copy,hashlib,importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('static_results_export',ROOT/'scripts/build_static_results.py')
export=importlib.util.module_from_spec(spec)
try:spec.loader.exec_module(export)
except FileNotFoundError:export=None

class StaticResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rh=json.loads((ROOT/'result_snapshots/2026-11-22/rh-api.json').read_text())
        cls.ns=json.loads((ROOT/'result_snapshots/2026-11-22/ns-api.json').read_text())
    def test_rh_pause_stays_partial_and_ns_is_machine_checks_only(self):
        self.assertIsNotNone(export,'static exporter missing')
        data=export.make_results(self.rh,self.ns,[],[])
        rh,ns=data['projects']
        self.assertEqual(rh['outcome'],'PARTIAL');self.assertEqual(rh['passedStages'],5)
        self.assertEqual(rh['localReplay'],'PAUSED');self.assertFalse(rh['proofAccepted'])
        self.assertEqual(ns['outcome'],'MACHINE_CHECKS_PASSED');self.assertEqual(ns['passedStages'],7)
        self.assertEqual(ns['semanticReview'],'NOT_RUN');self.assertFalse(ns['proofAccepted'])
        self.assertEqual(ns['source']['lean'],'v4.34.0-rc2');self.assertEqual(ns['source']['url'],'https://github.com/openai/NavierStokesAndEuler')
        self.assertIsNone(rh['stages'][-1]['commandSeconds'])
        self.assertTrue(data['static']);self.assertEqual(data['cost']['actualInvoiceAvailable'],False)
    def test_ns_incomplete_or_failed_checks_cannot_be_exported_as_success(self):
        self.assertIsNotNone(export,'static exporter missing')
        for part in ('stage','command','audit','axiom','checker','proofAccepted'):
            bad=copy.deepcopy(self.ns);q=bad['queue']
            if part=='stage':q['stages'][-2]['exitCode']=1
            elif part=='command':q['commands'][-1]['exitCode']=1
            elif part=='audit':q['audits'][0]['independent']='PENDING'
            elif part=='axiom':q['audits'][0]['dependencies'].append('sorryAx')
            elif part=='checker':q['commands'][-1]['argv']=['true']
            else:q['proofAccepted']=True
            with self.subTest(part=part),self.assertRaises(ValueError):export.make_results(self.rh,bad,[],[])
    def test_log_preview_is_bounded_and_carries_truncation_metadata(self):
        self.assertIsNotNone(export,'static exporter missing')
        logs=[{'id':i,'ts':1,'stage':'compile','message':'x'*2000,'level':'info'} for i in range(700)]
        data=export.make_results(self.rh,self.ns,logs,logs)
        for p in data['projects']:
            self.assertEqual(len(p['logs']),300);self.assertTrue(p['logPreviewLimited'])
            self.assertTrue(all(len(row['message'])<=1601 for row in p['logs']))
    def test_script_data_escapes_markup_and_does_not_execute_text(self):
        self.assertIsNotNone(export,'static exporter missing')
        js=export.script_data({'message':'</script><img onerror=alert(1)>\u2028'})
        self.assertNotIn('</script>',js);self.assertIn('\\u003c',js)

    def test_changed_or_escaped_evidence_cannot_be_exported(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'evidence';root.mkdir();p=root/'report.json';p.write_bytes(b'{"status":"PASSED"}')
            row={'path':'report.json','bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
            export.validate_evidence(root,{'files':[row]})
            p.write_bytes(b'{"status":"FAILED"}')
            with self.assertRaises(ValueError):export.validate_evidence(root,{'files':[row]})
            row['path']='../report.json'
            with self.assertRaises(ValueError):export.validate_evidence(root,{'files':[row]})

    def test_ns_log_at_timestamp_is_preserved(self):
        data=export.make_results(self.rh,self.ns,[],[{'at':123.5,'stage':'independent','message':'accepted'}])
        self.assertEqual(data['projects'][1]['logs'][0]['ts'],123.5)
