import datetime
import importlib
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

START=datetime.datetime.fromisoformat('2026-11-21T14:42:36+00:00').timestamp()


def server_budget():
    return {'scope':'server','capHours':20,'rentalStartedAt':START,'hourlyUsd':3.36,'minStartSeconds':300}


class BudgetTests(unittest.TestCase):
    def model(self):return importlib.import_module('ns_queue.budget')

    def test_rental_window_counts_rh_and_idle_time_without_resetting(self):
        b=self.model().normalize(server_budget(),now=START+3.25*3600)
        self.assertEqual(b['unit'],'hours');self.assertEqual(b['capHours'],20)
        self.assertEqual(b['usedHours'],3.25);self.assertEqual(b['remainingHours'],16.75)
        self.assertEqual(b['deadlineAt'],START+20*3600)
        self.assertAlmostEqual(b['estimatedUsd'],10.92)
        restored=json.loads(json.dumps(b))
        after=self.model().normalize(restored,now=START+4*3600)
        self.assertEqual(after['rentalStartedAt'],START);self.assertEqual(after['remainingHours'],16)

    def test_price_changes_do_not_change_authorized_time(self):
        model=self.model()
        for rate in [1,3.36,100]:
            self.assertEqual(model.available_seconds({**server_budget(),'hourlyUsd':rate},now=START+3600),19*3600)
        b=model.normalize({**server_budget(),'capUsd':0},now=START+3600)
        self.assertEqual(b['capHours'],20);self.assertEqual(b['capUsd'],67.2)

    def test_legacy_zero_remains_zero_and_bad_inputs_fail_closed(self):
        model=self.model();self.assertEqual(model.normalize({'capUsd':0})['capHours'],0)
        for key,value in [('capHours',-1),('capHours',math.nan),('capHours',True),('rentalStartedAt',math.inf),('rentalStartedAt',START+100)]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):model.normalize({**server_budget(),key:value},now=START)

    def test_notify_only_mode_allows_handoff_after_time_and_resource_warnings(self):
        from ns_queue.gates import start_gate
        from ns_queue.ns_worker import budget_available
        budget={**server_budget(),'enforcement':'notify_only'}
        now=START+21*3600
        state={'budget':budget,'rhEvidence':{'persisted':True}}
        self.assertTrue(start_gate(state,{'rhActive':False,'memoryAvailableBytes':1},now=now)['allowed'])
        self.assertTrue(budget_available(budget,now=now))
        self.assertFalse(start_gate(state,{'rhActive':True},now=now)['allowed'])
        self.assertFalse(start_gate({**state,'rhEvidence':{'persisted':False}},{'rhActive':False},now=now)['allowed'])

    def test_expiry_and_five_minute_reserve_are_shared_by_all_gates(self):
        from ns_queue.gates import start_gate
        from ns_queue.ns_worker import budget_available
        self.model()
        state={'budget':server_budget(),'rhEvidence':{'persisted':True}}
        resources={'rhActive':False,'cpuCount':64,'memoryAvailableBytes':240*1024**3,'diskFreeBytes':200*1024**3}
        deadline=START+20*3600
        self.assertTrue(start_gate(state,resources,now=deadline-300)['allowed'])
        self.assertTrue(budget_available(state['budget'],now=deadline-300))
        for now in [deadline-299,deadline,deadline+10]:
            self.assertFalse(start_gate(state,resources,now=now)['allowed'])
            self.assertFalse(budget_available(state['budget'],now=now))
        self.assertEqual(self.model().normalize(state['budget'],now=deadline+3600)['remainingHours'],0)
