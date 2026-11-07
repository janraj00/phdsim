"""Private CPU runtime bootstrap, then the eight-TRAIN-frame late-fusion pilot."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if os.environ.get('PYTHONHASHSEED') != '0':
    os.environ['PYTHONHASHSEED'] = '0'
    os.execv(sys.executable, [sys.executable, *sys.argv])
sys.path.insert(0,str(ROOT/'src'))


def prepare(directory):
    """Never pip-install into the active shared venv; all additions are private."""
    from phdsim.perception.urbaning.rgb3d_late import OMNI_COMMIT, D2_COMMIT, P3D_COMMIT, ASSETS
    import torch
    import numpy
    if torch.__version__ != '2.6.0+cpu' or numpy.__version__ != '1.26.4':
        raise RuntimeError('Use existing torch2.6.0+cpu / NumPy1.26.4 container')
    directory.mkdir(parents=True,exist_ok=True)
    if (directory/'ready.json').exists():
        raise FileExistsError('Preserve completed runtime; choose a fresh job output')
    source = directory/'sources'; source.mkdir(exist_ok=True)
    for name,repo,revision in [('omni3d','facebookresearch/omni3d',OMNI_COMMIT),
                               ('detectron2','facebookresearch/detectron2',D2_COMMIT),
                               ('pytorch3d','facebookresearch/pytorch3d',P3D_COMMIT)]:
        dest = source/name
        if dest.exists(): raise FileExistsError('Partial runtime: choose a fresh output')
        print('DOWNLOAD PINNED SOURCE',name,revision,flush=True)
        data = urllib.request.urlopen(f'https://codeload.github.com/{repo}/tar.gz/{revision}',timeout=180).read()
        unpack = source/(name+'-unpack'); unpack.mkdir()
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            t.extractall(unpack,filter='data')
        children = list(unpack.iterdir())
        if len(children) != 1 or children[0].name != name+'-'+revision:
            raise ValueError('Unexpected source archive root')
        children[0].rename(dest); unpack.rmdir()
    deps = directory/'dependencies'; deps.mkdir()
    # Existing CPU perception environment supplies NumPy/PyYAML/OpenCV/SciPy,
    # pandas/Matplotlib/Pillow. Add only isolated pinned packages, never torch.
    requirements = ['fvcore==0.1.5.post20221221','iopath==0.1.10','yacs==0.1.8',
                    'omegaconf==2.3.0','hydra-core==1.3.2','antlr4-python3-runtime==4.9.3',
                    'termcolor==2.5.0','cloudpickle==3.1.1','pycocotools==2.0.11',
                    'portalocker==3.2.0','tabulate==0.9.0','ninja==1.11.1.4',
                    'tqdm==4.67.1','tensorboard==2.19.0']
    # Existing direct dependencies come from the verified perception venv.
    # Explicit private additions do not upgrade torch/NumPy or that shared venv.
    subprocess.run([sys.executable,'-m','pip','install','--target',str(deps),
                    '--no-deps',*requirements],check=True)
    subprocess.run([sys.executable,'-m','pip','install','--target',str(deps),
                    '--no-deps','--only-binary=:all:', '--index-url',
                    'https://download.pytorch.org/whl/cpu','torchvision==0.21.0+cpu'],check=True)
    env = dict(os.environ)
    env.update({'PYTHONPATH':str(deps)+os.pathsep+env.get('PYTHONPATH',''),
                'PATH':str(deps/'bin')+os.pathsep+env['PATH'],
                'CC':'gcc','CXX':'g++','MAX_JOBS':'2','FORCE_CUDA':'0',
                'MPLCONFIGDIR':str(directory/'matplotlib-cache')})
    for name in ('detectron2','pytorch3d'):
        print('BUILD CPU EXTENSIONS',name,'MAX_JOBS=2',flush=True)
        subprocess.run([sys.executable,'-m','pip','install','--target',str(deps),
                        '--no-deps','--no-build-isolation',str(source/name)],check=True,env=env)
    model = directory/'model'; model.mkdir()
    for name, expected in ASSETS.items():
        print('DOWNLOAD OFFICIAL MODEL ASSET',name,flush=True)
        target = model/name
        urllib.request.urlretrieve('https://dl.fbaipublicfiles.com/cubercnn/omni3d/'+name,target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError('Official model asset hash changed: '+name)
    # Activate the exact dependencies for the science process. Inherited paths
    # survive this explicit exec, unlike an implicit after-import hash re-exec.
    env['PYTHONPATH'] = os.pathsep.join([str(source/'omni3d'),str(deps),str(ROOT/'src'),
                                       env.get('PYTHONPATH','')])
    child = ('import json,torch,torchvision,cv2,numpy,pandas,matplotlib,scipy; '
             'import detectron2,pytorch3d; from pytorch3d import _C; '
             'from phdsim.perception.urbaning.rgb3d_late import CubeDetector; '
             f'm=CubeDetector({str(model)!r},1); '
             'print("VERIFIED PRIVATE RGB3D CPU MODEL",torch.__version__,numpy.__version__,flush=True)')
    subprocess.run([sys.executable,'-c',child],check=True,env=env)
    (directory/'ready.json').write_text(json.dumps({'omni3d':OMNI_COMMIT,'detectron2':D2_COMMIT,
        'pytorch3d':P3D_COMMIT,'assets':ASSETS,'requirements':requirements},indent=2)+'\n')
    return model,env


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bootstrap',type=Path)
    p.add_argument('--reuse-runtime',type=Path)
    p.add_argument('--base',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--model-dir',type=Path)
    p.add_argument('--cpu-threads',type=int,default=8)
    p.add_argument('--model-variant',choices=['omni3d','outdoor'],default='omni3d')
    p.add_argument('--reference-archive',type=Path)
    a=p.parse_args()
    if a.cpu_threads < 1:p.error('Positive CPU thread count required')
    if a.bootstrap and a.reuse_runtime:p.error('Select bootstrap OR reuse-runtime')
    if a.model_variant=='outdoor' and not a.reference_archive:
        p.error('Outdoor comparison requires --reference-archive')
    if a.reference_archive and not a.reference_archive.is_file():
        p.error('Reference archive does not exist')
    if a.bootstrap or a.reuse_runtime:
        if a.bootstrap:model,env=prepare(a.bootstrap.resolve())
        else:model,env=reuse(a.reuse_runtime.resolve())
        env['MPLCONFIGDIR']=str(a.output.resolve().parent/'matplotlib-cache')
        if a.model_variant=='outdoor':
            model=download_variant(a.output.resolve().parent/'models'/'outdoor','outdoor')
        args=[sys.executable,'-u',str(Path(__file__).resolve()),'--base',str(a.base),
              '--output',str(a.output),'--model-dir',str(model),'--cpu-threads',str(a.cpu_threads),
              '--model-variant',a.model_variant]
        if a.reference_archive:args.extend(['--reference-archive',str(a.reference_archive.resolve())])
        os.execve(sys.executable,args,env)
    if not a.model_dir:p.error('--model-dir, --bootstrap or --reuse-runtime is required')
    from phdsim.experiments.urbaning_rgb3d_late import run
    run(a.base.resolve(),a.model_dir.resolve(),a.output.resolve(),a.cpu_threads,
        a.model_variant,a.reference_archive.resolve() if a.reference_archive else None)


def reuse(directory):
    """Read-only activation of a completed runtime: no installs/builds/writes."""
    from phdsim.perception.urbaning.rgb3d_late import OMNI_COMMIT, D2_COMMIT, P3D_COMMIT, ASSETS
    marker=json.loads((directory/'ready.json').read_text())
    expected={'omni3d':OMNI_COMMIT,'detectron2':D2_COMMIT,'pytorch3d':P3D_COMMIT,'assets':ASSETS}
    if any(marker.get(k)!=v for k,v in expected.items()):
        raise ValueError('Completed private runtime revision/assets differ')
    deps=directory/'dependencies'; source=directory/'sources'/'omni3d'; model=directory/'model'
    if not deps.is_dir() or not source.is_dir():raise FileNotFoundError('Incomplete private runtime')
    for name,expected_sha in ASSETS.items():
        if hashlib.sha256((model/name).read_bytes()).hexdigest()!=expected_sha:
            raise ValueError('Cannot reuse changed official model asset: '+name)
    env=dict(os.environ)
    env['PYTHONPATH']=os.pathsep.join([str(source),str(deps),str(ROOT/'src'),env.get('PYTHONPATH','')])
    env['PYTHONDONTWRITEBYTECODE']='1'
    # Put plotting caches in the NEW output, not in the reused source runtime.
    print('REUSE VERIFIED PRIVATE CPU RUNTIME (no install/build):',directory,flush=True)
    return model,env


def download_variant(directory,variant):
    """Download a complete hash-pinned official bundle into NEW output only."""
    from phdsim.perception.urbaning.rgb3d_late import model_assets
    directory.mkdir(parents=True,exist_ok=True)
    for name,expected in model_assets(variant).items():
        target=directory/name
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==expected:continue
        print('DOWNLOAD OFFICIAL',variant,name,flush=True)
        temp=target.with_suffix(target.suffix+'.part')
        urllib.request.urlretrieve('https://dl.fbaipublicfiles.com/cubercnn/'+variant+'/'+name,temp)
        if hashlib.sha256(temp.read_bytes()).hexdigest()!=expected:
            raise ValueError('Downloaded official asset hash differs: '+name)
        os.replace(temp,target)
    return directory


if __name__=='__main__':main()
