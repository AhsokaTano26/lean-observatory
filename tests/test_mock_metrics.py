import unittest
from backend.mock import metrics, tick
from backend.model import initial_state

class MockMetricsTests(unittest.TestCase):
    def test_host_history_uses_sample_time_after_task_completion(self):
        s=initial_state('mock');s.update(startedAt=1000,status='checks_completed',mockTicks=50)
        a=metrics(s,now=1100);b=metrics(s,now=1117)
        self.assertEqual(a['sampledAt'],1100)
        self.assertEqual(a['source'],'mock_host')
        self.assertNotEqual(a['cpuPercent'],b['cpuPercent'])
        self.assertGreaterEqual(a['cpuPercent'],0);self.assertLessEqual(a['cpuPercent'],100)
        self.assertGreater(a['networkTxBytesPerSec'],0)

    def test_slow_demo_progress_keeps_throughput_consistent(self):
        s=initial_state('mock');s.update(status='running',mockTicks=20,mockStepTicks=20)
        tick(s,1);before=s['compile']['succeeded'];tick(s,1)
        self.assertAlmostEqual(s['compile']['rate'],s['compile']['succeeded']-before,places=1)
        self.assertLess(s['mockTicks'],21)
