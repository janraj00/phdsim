"""Exercise the real bootstrap/entrypoint re-exec boundary in child processes.

Tiny versioned fixture packages isolate path handling; no downloads, Slurm or
shared environment edits. The entrypoint mirrors the real trainer's hash guard.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


BOOTSTRAP=Path(__file__).resolve().parents[1]/'scripts/urbaning_rgb_env.py'
ENTRYPOINT='''import os, sys, json
if os.environ.get('PYTHONHASHSEED')!='0':
    os.environ['PYTHONHASHSEED']='0'
    os.execv(sys.executable,[sys.executable,*sys.argv])
import torchvision
from private_model import VALUE
print('ENTRY_RESULT '+json.dumps({'seed':os.environ['PYTHONHASHSEED'],
    'module':torchvision.__file__, 'args':sys.argv[1:], 'value':VALUE,
    'hash':hash('urbaning-runtime-regression')}))
'''


class RGBEnvironmentTests(unittest.TestCase):
    def fixture(self,root):
        runtime=root/'runtime';runtime.mkdir()
        (runtime/'torch.py').write_text("__version__='2.6.0+cpu'\n")
        (runtime/'numpy.py').write_text("__version__='1.26.4'\n")
        private=root/'dependencies';private.mkdir()
        package=private/'torchvision';package.mkdir()
        (package/'__init__.py').write_text("__version__='0.21.0+cpu'\n")
        meta=private/'torchvision-0.21.0+cpu.dist-info';meta.mkdir()
        (meta/'METADATA').write_text('Metadata-Version: 2.1\nName: torchvision\nVersion: 0.21.0+cpu\n')
        repo=root/'checkout';(repo/'scripts').mkdir(parents=True);(repo/'src').mkdir()
        (repo/'src/private_model.py').write_text('VALUE=42\n')
        entry=repo/'scripts/train.py';entry.write_text(ENTRYPOINT)
        env={**os.environ,'PYTHONPATH':str(runtime)};env.pop('PYTHONHASHSEED',None)
        return private,entry,env

    def test_unset_nonzero_and_zero_seed_preserve_private_imports_and_arguments(self):
        results=[]
        with tempfile.TemporaryDirectory(prefix='rgb env ') as t:
            private,entry,env=self.fixture(Path(t))
            for seed in (None,'123','0'):
                child=env.copy()
                if seed is not None:child['PYTHONHASHSEED']=seed
                process=subprocess.run([sys.executable,str(BOOTSTRAP),str(private),str(entry),
                                        '--output','path with spaces'],env=child,capture_output=True,text=True,timeout=20)
                self.assertEqual(process.returncode,0,process.stdout+process.stderr)
                line=next(s for s in process.stdout.splitlines() if s.startswith('ENTRY_RESULT '))
                result=json.loads(line.removeprefix('ENTRY_RESULT '));results.append(result)
                self.assertEqual(result['seed'],'0');self.assertEqual(result['value'],42)
                self.assertEqual(result['args'],['--output','path with spaces'])
                self.assertTrue(Path(result['module']).is_relative_to(private))
                self.assertIn('VERIFIED isolated RGB runtime:',process.stdout)
            self.assertEqual(len({r['hash'] for r in results}),1)

    def test_historical_post_bootstrap_restart_loses_private_target(self):
        """The same child-process fixture must reproduce the old Ares failure."""
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);private,entry,env=self.fixture(root)
            old=root/'old_bootstrap.py'
            old.write_text('import sys, runpy\nsys.path.insert(0,sys.argv[1])\n'
                           'import torchvision\nsys.argv=sys.argv[2:]\n'
                           "runpy.run_path(sys.argv[0],run_name='__main__')\n")
            process=subprocess.run([sys.executable,str(old),str(private),str(entry)],
                                   env=env,capture_output=True,text=True,timeout=20)
            self.assertNotEqual(process.returncode,0)
            self.assertIn("No module named 'torchvision'",process.stderr)

    def test_incompatible_existing_runtime_is_rejected_before_entrypoint(self):
        with tempfile.TemporaryDirectory() as t:
            private,entry,env=self.fixture(Path(t))
            (Path(env['PYTHONPATH'])/'torch.py').write_text("__version__='wrong'\n")
            process=subprocess.run([sys.executable,str(BOOTSTRAP),str(private),str(entry)],
                                   env=env,capture_output=True,text=True,timeout=20)
            self.assertNotEqual(process.returncode,0)
            self.assertIn('Expected existing CPU torch',process.stderr)
            self.assertNotIn('ENTRY_RESULT',process.stdout)


if __name__=='__main__':unittest.main()
