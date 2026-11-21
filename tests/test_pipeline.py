import tempfile
import unittest
from pathlib import Path
from backend.pipeline import validate_project, audit_source, parse_build_module, audit_program
from backend.model import MATHLIB, THEOREMS


class PipelineTests(unittest.TestCase):
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
