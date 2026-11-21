import copy
import tempfile
import json
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch
from backend.readiness import validate_online_receipt,require_online_gate

SHA='1'*64
def receipt():
    return {'passed':True,'productionEligible':True,'checkedAt':100,'sourceSha256':SHA,'url':'https://lean.tano.asia','checks':{k:True for k in ['tls','source','resources','metrics','clean','readOnly','methods','sse']}}

class ReadinessTests(unittest.TestCase):
    def test_all_online_checks_and_matching_source_are_required(self):
        self.assertEqual(validate_online_receipt(receipt(),SHA,now=120)['sourceSha256'],SHA)
        for field,value in [('passed',False),('productionEligible',False),('sourceSha256','2'*64),('checkedAt',-90000),('url','http://lean.tano.asia')]:
            r=receipt();r[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):validate_online_receipt(r,SHA,now=120)
        r=receipt();r['checks']['sse']=False
        with self.assertRaises(ValueError):validate_online_receipt(r,SHA,now=120)

    def test_real_host_receipt_is_loaded_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'online.json'
            with patch.dict(os.environ,{'ONLINE_RECEIPT':str(path),'SOURCE_SHA256':SHA}):
                with self.assertRaises(ValueError):require_online_gate()
                r=receipt();r['checkedAt']=time.time();path.write_text(json.dumps(r))
                self.assertTrue(require_online_gate()['productionEligible'])

    def test_resume_acceptance_cannot_authorize_a_different_or_new_task(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'online.json';r=receipt();r.update(checkedAt=time.time(),resumeRun='expected-run');path.write_text(json.dumps(r))
            with patch.dict(os.environ,{'ONLINE_RECEIPT':str(path),'SOURCE_SHA256':SHA}):
                with self.assertRaises(ValueError):require_online_gate()
                with self.assertRaises(ValueError):require_online_gate('other-run')
                self.assertTrue(require_online_gate('expected-run')['productionEligible'])
