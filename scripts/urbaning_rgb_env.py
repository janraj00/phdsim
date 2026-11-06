"""Start deterministic Python, load private torchvision, then run the entrypoint."""
import importlib.metadata
import os
from pathlib import Path
import runpy
import subprocess
import sys


def main():
    # Entrypoints re-exec Python when the hash seed is unset/different. Do this
    # HERE first: a later re-exec would lose our in-process sys.path additions
    # and skip this bootstrap, making the private torchvision target disappear.
    if os.environ.get('PYTHONHASHSEED') != '0':
        os.environ['PYTHONHASHSEED'] = '0'
        os.execv(sys.executable, [sys.executable, '-u', *sys.argv])
    dependencies = Path(sys.argv[1]).resolve()
    entrypoint = Path(sys.argv[2]).resolve()
    arguments = sys.argv[3:]
    import torch
    import numpy
    if torch.__version__ != '2.6.0+cpu' or numpy.__version__ != '1.26.4':
        raise RuntimeError('Expected existing CPU torch2.6.0+cpu / NumPy1.26.4; shared venv is not modified')
    dependencies.mkdir(parents=True, exist_ok=True)
    installed = {d.metadata['Name'].lower(): d.version for d in importlib.metadata.distributions(path=[str(dependencies)])}
    if installed.get('torchvision') != '0.21.0+cpu':
        print('INSTALL isolated torchvision0.21.0+cpu --no-deps:', dependencies, flush=True)
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps', '--only-binary=:all:',
                        '--disable-pip-version-check', '--target', str(dependencies),
                        '--index-url', 'https://download.pytorch.org/whl/cpu', 'torchvision==0.21.0+cpu'], check=True)
    sys.path.insert(0, str(dependencies))
    sys.path.insert(0, str(entrypoint.parents[1]/'src'))
    import torchvision
    if torchvision.__version__ != '0.21.0+cpu':
        raise RuntimeError('Unexpected torchvision runtime')
    if not Path(torchvision.__file__).resolve().is_relative_to(dependencies):
        raise RuntimeError('torchvision did not load from the private dependency target')
    print('VERIFIED isolated RGB runtime:', {'torch':torch.__version__,
          'numpy':numpy.__version__,'torchvision':torchvision.__version__,
          'torchvision_file':torchvision.__file__,'PYTHONHASHSEED':os.environ['PYTHONHASHSEED']},flush=True)
    os.environ['SLURM_CPUS_PER_TASK'] = os.environ.get('SLURM_CPUS_PER_TASK', '8')
    sys.argv = [str(entrypoint), *arguments]
    runpy.run_path(str(entrypoint), run_name='__main__')


if __name__ == '__main__':
    main()
