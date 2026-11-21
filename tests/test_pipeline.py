import tempfile
import unittest
from pathlib import Path
from backend.pipeline import validate_project, audit_source, parse_build_module, audit_program
from backend.model import MATHLIB, THEOREMS


class PipelineTests(unittest.TestCase):
    def test_control_side_termination_is_not_reported_as_memory_exhaustion(self):
        from backend.pipeline import Pipeline
        from backend.runner import CommandError
        from backend.store import Store
        for cause,expected in [('operator_interruption','interrupted'),('timeout','failed'),('runner_error','failed'),(None,'resource_exhausted')]:
            with self.subTest(cause=cause),tempfile.TemporaryDirectory() as d:
                store=Store(Path(d));run=store.create('real');pipeline=Pipeline(store,run['id'])
                def fail():raise CommandError('fixture termination',-9,terminationCause=cause)
                pipeline.download=fail;pipeline.run()
                self.assertEqual(store.raw(run['id'])['status'],expected)
                self.assertEqual(store.raw(run['id'])['stages'][0]['exitCode'],-9)

    def test_a_review_list_can_never_authorize_an_added_axiom(self):
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'Bad.lean';p.write_text('axiom bad : False\n')
            reviewed={'Bad.lean':{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'hits':[{'line':1,'token':'axiom'}]}}
            self.assertFalse(audit_source(root,reviewed=reviewed)[0]['approved'])

    def test_bad_archive_invalidates_download_cache_for_explicit_resume(self):
        from backend.pipeline import Pipeline
        from backend.store import Store
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d));run=store.create('real');pipeline=Pipeline(store,run['id'])
            (pipeline.root/'lean.tar.gz').write_bytes(b'<html>not the archive</html>')
            (pipeline.root/'lean.tar.gz.part01').write_bytes(b'corrupt')
            store.mutate(run['id'],lambda s:s['stages'][0].update(status='passed',exitCode=0))
            with self.assertRaises(ValueError):pipeline.integrity()
            self.assertEqual(store.raw(run['id'])['stages'][0]['status'],'pending')
            self.assertFalse((pipeline.root/'lean.tar.gz.part01').exists())
            self.assertFalse((pipeline.root/'lean.tar.gz').exists())

    def test_reviewed_extension_is_allowed_only_for_exact_bytes(self):
        from backend.pipeline import audit_source
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'Extension.lean';text='macro "fixture" : tactic => `(tactic| trivial)\n';p.write_text(text)
            reviewed={'Extension.lean':{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'hits':[{'line':1,'token':'macro'}]}}
            findings=audit_source(root,reviewed=reviewed)
            self.assertTrue(findings[0]['approved'])
            p.write_text(text+'axiom fake : False\n')
            self.assertTrue(all(not x['approved'] for x in audit_source(root,reviewed=reviewed)))

    def project(self, root):
        (root/'lean-toolchain').write_text('leanprover/lean4:v4.33.1\n')
        (root/'lakefile.toml').write_text('name="tree"\nsrcDir="src"\n[[require]]\nname="mathlib"\ngit="https://github.com/leanprover-community/mathlib4"\nrev="'+MATHLIB+'"\n')
        (root/'lake-manifest.json').write_text('{"packages":[{"name":"mathlib","rev":"'+MATHLIB+'"}]}')
        (root/'src').mkdir(); (root/'src/Main.lean').write_text('theorem t : True := True.intro')

    def test_pin_and_inventory(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); self.project(root)
            info=validate_project(root,expected_count=1)
            self.assertEqual(info['modules'],{'Main'})
            (root/'lean-toolchain').write_text('leanprover/lean4:nightly')
            with self.assertRaises(ValueError): validate_project(root,expected_count=1)

    def test_scan_catches_escapes_and_preserves_config(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); self.project(root)
            (root/'src/Main.lean').write_text('axiom fake : False\ntheorem x : False := by sorry\n')
            findings=audit_source(root/'src')
            self.assertTrue(any(x['token']=='sorry' for x in findings))
            self.assertTrue(any(x['token']=='axiom' for x in findings))

    def test_progress_only_matches_source_modules(self):
        modules={'Main','Foo.Bar'}
        self.assertEqual(parse_build_module('✔ [30/50] Built Foo.Bar (0.4s)',modules),'Foo.Bar')
        self.assertIsNone(parse_build_module('✔ [30/50] Built Foo.Bar:c.o (1s)',modules))
        self.assertIsNone(parse_build_module('✔ [30/50] Built Mathlib.Foo (1s)',modules))
        self.assertIsNone(parse_build_module('✖ [30/50] Building Foo.Bar',modules))

    def test_audit_program_checks_exact_expected_types(self):
        code=audit_program()
        for name,typ in THEOREMS:
            self.assertIn(f'example : {typ} := {name}',code)
            self.assertIn(f'#print axioms {name}',code)
        self.assertIn('import Main',code)

    def test_failed_file_accounting_ignores_non_source_jobs(self):
        from backend.pipeline import parse_failed_module
        self.assertEqual(parse_failed_module('✖ [9/20] Building Foo.Bar (1s)',{'Foo.Bar'}),'Foo.Bar')
        self.assertIsNone(parse_failed_module('✖ [9/20] Building Foo.Bar:c.o (1s)',{'Foo.Bar'}))
        self.assertIsNone(parse_failed_module('✖ [9/20] Building Mathlib.Foo (1s)',{'Foo.Bar'}))
