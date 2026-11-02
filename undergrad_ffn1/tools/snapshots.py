"""Self-contained immutable checkpoints; generated outputs stay in this workspace."""
import hashlib,json,shutil
from pathlib import Path
from options import options
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def freeze_manifest(root):
    root=Path(root)
    sources=[p for name in ('rtl','tech','firmware','model') for p in (root/name).iterdir() if p.is_file()]
    vendor={p.relative_to(root).as_posix():digest(p) for p in (root/'vendor').rglob('*') if p.is_file()}
    data=dict(scope='undergraduate FFN1 variant',options=options(root),
        snapshots=[dict(package_path=p.relative_to(root).as_posix(),sha256=digest(p)) for p in sources],
        vendor_e203=dict(revision='9f3e34f337f5d0a1236a285871ffa2032491617a',files=vendor))
    (root/'source_manifest.json').write_text(json.dumps(data,indent=2)+'\n')
def capture(root,destination,label,include_logs=True):
    root=Path(root);destination=Path(destination)
    assert not destination.exists(), 'Never overwrite a checkpoint: '+str(destination)
    dirs=('rtl','tech','firmware','model','vendor','vectors','filelists','config','script','tests','tools','environment','docs','verification')
    files=[p for folder in dirs for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts
           and p.relative_to(root).parts[:2]!=('verification','matrix')]
    files += [p for p in root.iterdir() if p.is_file() and p.suffix in ('.md','.sh')]
    if include_logs:files += list((root/'output/logs').glob('*.log'))
    for p in files:
        q=destination/p.relative_to(root);q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
    freeze_manifest(destination)
    name='dc_'+label+'.tcl'
    (destination/'script'/name).write_bytes(b'source [file join [file dirname [info script]] run_all.tcl]\n')
    (destination/'checkpoint.json').write_text(json.dumps(dict(label=label,options=options(root),dc_entry='script/'+name),indent=2)+'\n')
    print('CHECKPOINT',label,options(root),flush=True)
if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('name');a=ap.parse_args()
    root=Path(__file__).resolve().parents[1]
    capture(root,root/'experiments/checkpoints'/a.name,a.name)
