"""Install this job's pinned wheels separately, verify them, then run the pilot.

Invoke with the existing container Python, not the login-node Python. This
bootstrap imports no scientific packages until its private target is first on
sys.path. pip --target never changes packages in the existing shared venv.
"""
import argparse
import importlib
from importlib.metadata import version
import json
from pathlib import Path
import runpy
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dependency-dir', required=True)
    parser.add_argument('pilot_arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    pilot_args = args.pilot_arguments
    if pilot_args[:1] == ['--']:
        pilot_args = pilot_args[1:]
    if not pilot_args:
        parser.error('Pass pilot arguments after -- (or -- --help for a smoke check)')
    target = Path(args.dependency_dir).resolve()
    repository = Path(__file__).resolve().parents[1]
    requirements = repository / 'requirements' / 'urbaning-tree-pilot.txt'
    expected = dict(line.split('==') for line in requirements.read_text().splitlines()
                    if line and not line.startswith('#'))
    imports = {'scikit-learn': 'sklearn', **{n: n for n in expected if n != 'scikit-learn'}}
    if any(name in sys.modules for name in imports.values()):
        raise RuntimeError('Run this bootstrap in a fresh container Python process')
    # One new directory per Slurm job; failed installations are preserved.
    target.mkdir(parents=True, exist_ok=False)
    print('INSTALL isolated pilot dependencies:', target, flush=True)
    subprocess.run([sys.executable, '-m', 'pip', '--disable-pip-version-check', 'install',
                    '--only-binary=:all:', '--no-deps', '--no-cache-dir',
                    '--target', str(target), '-r', str(requirements)], check=True)
    sys.path.insert(0, str(target))
    importlib.invalidate_caches()
    runtime = {}
    for distribution, name in imports.items():
        module = importlib.import_module(name)
        location = Path(module.__file__).resolve()
        actual = version(distribution)
        if actual != expected[distribution] or not location.is_relative_to(target):
            raise RuntimeError('Isolated dependency mismatch: ' + distribution)
        runtime[distribution] = {'version': actual, 'file': str(location)}
    from sklearn.ensemble import GradientBoostingRegressor
    model = GradientBoostingRegressor(n_estimators=2, random_state=42).fit([[0.], [1.]], [0., 1.])
    if len(model.predict([[.5]])) != 1:
        raise RuntimeError('Isolated model smoke check failed')
    (target / 'verified-runtime.json').write_text(json.dumps(runtime, indent=2) + '\n')
    print('VERIFIED isolated runtime:', {n: r['version'] for n, r in runtime.items()}, flush=True)
    pilot = repository / 'scripts' / 'urbaning_tree_pilot.py'
    sys.argv = [str(pilot)] + pilot_args
    runpy.run_path(str(pilot), run_name='__main__')


if __name__ == '__main__':
    main()
