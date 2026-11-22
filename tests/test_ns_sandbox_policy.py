import copy,json,unittest
from ns_queue import sandbox_policy as policy


def evidence():
    return {'landlockAbi':4,'uid':10002,'gid':10002,'capEff':0,'noNewPrivs':1,'seccomp':2,
            'pid1Uid':10002,'pid1SameRoot':True,'devices':{'null':[1,3],'urandom':[1,9]},
            'noSys':True,'safeFds':True,'filesystemWriteDenied':True,'unixSocketDenied':True,
            'unixSocketpairDenied':True,'ipv4TcpDenied':True,'ipv4UdpDenied':True,
            'ipv6TcpDenied':True,'ipv6UdpDenied':True,'noIpv4Routes':True,'userNamespaceDenied':True}


class SandboxPolicyTests(unittest.TestCase):
    def output(self,record):return 'NS_SANDBOX_SCOPE|'+json.dumps(record)+'\n'
    def warning(self):return '[landrun:warn] 2026/11/22 07:46:02 '+policy.ABI4_WARNING
    def test_native_feature_warning_requires_real_layered_guard_and_is_retained(self):
        output=self.warning()+'\n'+self.output(evidence())
        report=policy.validate_probe(output,4)
        self.assertEqual(report['nativeWarnings'],[self.warning()])
        self.assertEqual(report['profile'],'landlock+namespaces+seccomp')
        self.assertEqual(report['nativeLandlockAbi'],4)
        self.assertEqual(report['devicePolicy'],'null-and-urandom-only; no-sensitive-inherited-fds')
        with self.assertRaises(ValueError):policy.validate_warnings(output,None)
    def test_any_missing_failed_or_malformed_guard_blocks(self):
        for key,value in evidence().items():
            bad=evidence();bad.pop(key)
            with self.subTest(missing=key),self.assertRaises(ValueError):policy.validate_probe(self.output(bad),4)
            bad=evidence();bad[key]=False if type(value)is bool else ('wrong' if type(value)is not dict else {})
            with self.subTest(bad=key),self.assertRaises(ValueError):policy.validate_probe(self.output(bad),4)
        with self.assertRaises(ValueError):policy.validate_probe(self.output(evidence())*2,4)
    def test_unknown_warning_and_unsafe_modes_never_get_whitelisted(self):
        report=policy.validate_probe(self.output(evidence()),4)
        for warning in ('[landrun:warn] running unsandboxed',self.warning()+' extra',
                        self.warning().replace('ABI v4','ABI v3'),'fake-landrun','best-effort'):
            with self.subTest(warning=warning),self.assertRaises(ValueError):policy.validate_warnings(warning,report)
        bad=copy.deepcopy(report);bad['nativeLandlockAbi']=6
        with self.assertRaises(ValueError):policy.validate_warnings(self.warning(),bad)

    def test_real_acceptance_allows_only_the_measured_abi4_warning(self):
        from ns_queue.ns_worker import validate_independent_output
        output = ('Running nanoda kernel on solution\nnanoda kernel accepts the solution\n'
                  'Running Lean default kernel on solution.\nLean default kernel accepts the solution\n'
                  'Your solution is okay!\n')
        report=policy.validate_probe(self.output(evidence()),4)
        validate_independent_output(output+self.warning(),report)
        with self.assertRaises(ValueError):validate_independent_output(output+self.warning())
        with self.assertRaises(ValueError):validate_independent_output(output.replace('Your solution is okay!','')+self.warning(),report)
