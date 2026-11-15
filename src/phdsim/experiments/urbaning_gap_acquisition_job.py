"""Portable input packaging and safe Ares staging for validation-only replay."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import zipfile

from phdsim.experiments.urbaning_gap_acquisition import run
from phdsim.experiments.urbaning_regional_learning import sha

SCHEMA='phdsim-urbaning-gap-acquisition-inputs-v1'
MEMBERS=('pilot.zip','regional-dataset.zip','ap-export.zip')


def safe_extract(archive,destination):
    """Reject unsafe/duplicate names, links and oversized input before writing."""
    destination=Path(destination)
    with zipfile.ZipFile(archive) as z:
        names=set();size=0
        for entry in z.infolist():
            p=PurePosixPath(entry.filename)
            if (not entry.filename or p.is_absolute() or '..' in p.parts or '\\' in entry.filename
                    or ':' in entry.filename or entry.filename in names
                    or (entry.external_attr>>16)&0o170000==0o120000):
                raise ValueError('Unsafe ZIP member')
            names.add(entry.filename);size+=entry.file_size
            if size>512*1024*1024:raise ValueError('Input exceeds 512 MiB staging limit')
        if z.testzip() is not None:raise ValueError('Input CRC failure')
        z.extractall(destination)


def pack(pilot,dataset,ap_export,output):
    output=Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    sources=dict(zip(MEMBERS,map(Path,(pilot,dataset,ap_export))))
    manifest={'schema':SCHEMA,'files':{name:sha(p.read_bytes()) for name,p in sources.items()},
              'scope':'400 original train / 200 development validation; no crossing3 payloads; no refitting'}
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'x',zipfile.ZIP_STORED) as z:
        z.writestr('inputs.json',json.dumps(manifest,indent=2)+'\n')
        for name,p in sources.items():
            with zipfile.ZipFile(p) as source:
                if source.testzip() is not None:raise ValueError('Source archive CRC failure: '+str(p))
            z.write(p,name)
    print('INPUT SHA256',sha(output.read_bytes()),'bytes',output.stat().st_size,flush=True)
    print(output,flush=True)


def stage(inputs,expected_sha,destination):
    inputs,destination=Path(inputs).resolve(),Path(destination).resolve()
    if sha(inputs.read_bytes())!=expected_sha:raise ValueError('Input ZIP SHA256 differs')
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        if (destination/'input.sha256').read_text().strip()!=expected_sha:raise ValueError('Existing staging has different inputs')
        manifest=json.loads((destination/'inputs.json').read_text())
        if manifest['schema']!=SCHEMA or set(manifest['files'])!=set(MEMBERS):raise ValueError('Staged input schema differs')
        for name,h in manifest['files'].items():
            if sha((destination/name).read_bytes())!=h:raise ValueError('Staged archive changed')
        # The replay also verifies every extracted pilot member against files.json.
        return destination
    with tempfile.TemporaryDirectory(prefix=destination.name+'-',dir=destination.parent) as temp:
        temp=Path(temp)
        with zipfile.ZipFile(inputs) as z:
            if set(z.namelist())!=set(MEMBERS)|{'inputs.json'}:raise ValueError('Unexpected input members')
        safe_extract(inputs,temp)
        manifest=json.loads((temp/'inputs.json').read_text())
        if manifest['schema']!=SCHEMA or set(manifest['files'])!=set(MEMBERS):raise ValueError('Input schema differs')
        for name,h in manifest['files'].items():
            if sha((temp/name).read_bytes())!=h:raise ValueError('Embedded archive hash differs')
        safe_extract(temp/'pilot.zip',temp/'pilot')
        (temp/'input.sha256').write_text(expected_sha+'\n')
        os.rename(temp,destination)
    return destination


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('pack')
    for name in ('pilot','dataset','ap-export','output'):p.add_argument('--'+name,required=True)
    p=commands.add_parser('run')
    for name in ('inputs','inputs-sha256','output-dir'):p.add_argument('--'+name,required=True)
    p.add_argument('--resume',action='store_true')
    args=parser.parse_args(argv)
    if args.command=='pack':pack(args.pilot,args.dataset,args.ap_export,args.output)
    else:
        out=Path(args.output_dir).resolve()
        staged=stage(args.inputs,args.inputs_sha256,out.with_name(out.name+'-inputs'))
        run(staged/'pilot',staged/'regional-dataset.zip',staged/'ap-export.zip',out,args.resume)


if __name__=='__main__':main()
