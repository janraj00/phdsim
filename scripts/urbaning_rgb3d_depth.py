"""Activate completed private CPU runtime without installation, then train/readout."""
import argparse
import importlib.util
import os
from pathlib import Path
import sys

if os.environ.get('PYTHONHASHSEED')!='0':
    os.environ['PYTHONHASHSEED']='0'
    os.execv(sys.executable,[sys.executable,'-u',*sys.argv])
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['base','runtime','model-dir','pilot','output']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--cpu-threads',type=int,default=8)
    p.add_argument('--activated',action='store_true')
    a=p.parse_args()
    if a.cpu_threads<1:p.error('Positive CPU thread count required')
    for path in [a.runtime/'ready.json',a.pilot,a.model_dir/'cubercnn_DLA34_FPN.pth']:
        if not path.is_file():p.error('Missing existing source: '+str(path))
    if not a.activated:
        spec=importlib.util.spec_from_file_location('rgb3d_runtime',ROOT/'scripts/urbaning_rgb3d_late.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        _,env=module.reuse(a.runtime.resolve())
        env['MPLCONFIGDIR']=str(a.output.resolve()/'matplotlib-cache')
        args=[sys.executable,'-u',str(Path(__file__).resolve()),*sys.argv[1:],'--activated']
        os.execve(sys.executable,args,env)
    from phdsim.experiments.urbaning_rgb3d_depth import run
    run(a.base.resolve(),a.runtime.resolve(),a.model_dir.resolve(),a.pilot.resolve(),a.output.resolve(),a.cpu_threads)


if __name__=='__main__':main()
