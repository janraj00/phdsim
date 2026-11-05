"""Install torchvision into an isolated target, then execute the pilot."""
import importlib.metadata
import os
from pathlib import Path
import runpy
import subprocess
import sys


def main():
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
    os.environ['SLURM_CPUS_PER_TASK'] = os.environ.get('SLURM_CPUS_PER_TASK', '8')
    sys.argv = [str(entrypoint), *arguments]
    runpy.run_path(str(entrypoint), run_name='__main__')


if __name__ == '__main__':
    main()
