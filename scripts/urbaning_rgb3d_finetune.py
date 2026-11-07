"""Activate the existing private CPU runtime, then fit native RGB ROI heads."""
import argparse
import importlib.util
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'runtime', 'model-dir', 'source', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--cpu-threads', type=int, default=8)
    p.add_argument('--gate-only', action='store_true')
    p.add_argument('--activated', action='store_true')
    a = p.parse_args()
    if a.cpu_threads < 1:
        p.error('Positive CPU thread count required')
    if not a.activated or os.environ.get('PYTHONHASHSEED') != '0':
        spec = importlib.util.spec_from_file_location('rgb3d_runtime', ROOT/'scripts/urbaning_rgb3d_late.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        _, env = module.reuse(a.runtime.resolve())
        env.update({'PYTHONHASHSEED': '0', 'MPLCONFIGDIR': str(a.output.resolve()/'matplotlib-cache'),
                    'OMP_NUM_THREADS': str(a.cpu_threads), 'MKL_NUM_THREADS': str(a.cpu_threads)})
        args = [sys.executable, '-u', str(Path(__file__).resolve()), *sys.argv[1:]]
        if not a.activated:
            args.append('--activated')
        os.execve(sys.executable, args, env)
    from phdsim.experiments.urbaning_rgb3d_finetune import run
    run(a.base.resolve(), a.runtime.resolve(), a.model_dir.resolve(), a.source.resolve(),
        a.output.resolve(), a.cpu_threads, a.gate_only)


if __name__ == '__main__':
    main()
