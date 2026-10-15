"""Package source and verified local artifacts; keep large SoC waveforms as sidecars."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
from build_soc import source_files,SOC

ROOT=Path(__file__).resolve().parents[1]

def main():
    paths=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=str(ROOT)).decode('utf-8').split('\0')
    files={p:ROOT/p for p in paths if p and (ROOT/p).is_file()}
    # Include the upstream RTL actually instantiated, with its original license.
    for p in source_files():files[p]=ROOT/p
    for folder in [SOC,ROOT/'assets/sources/keyword-transformer-237e4097afd4f6851e0b82f0a8d65c2dfe8eae30']:
        for p in folder.glob('LICENSE*'):files[p.relative_to(ROOT).as_posix()]=p
    for p in (ROOT/'output/vectors').glob('task_*/*'):
        if p.suffix in ['.hex','.npz']:files[p.relative_to(ROOT).as_posix()]=p
    for name in ['numeric-report.json','manifest.json']:
        p=ROOT/'output/vectors'/name;files[p.relative_to(ROOT).as_posix()]=p
    for name in ['kwt_accel_netlist.v','kwt_soc_netlist.v','synthesis-stat.json','soc-synthesis-stat.json',
                 'ppa-status.json','synth.ys','synth_soc.ys','mac.vcd','firmware/kwt.elf','firmware/kwt.bin','firmware/kwt.hex',
                 'tb_accel-run.log','tb_accel_netlist-run.log','tb_soc-run.log','tb_soc_netlist-run.log','numeric-tests.log','mac-icarus.log','icarus-accel.log']:
        p=ROOT/'output/design'/name
        if not p.is_file():raise RuntimeError('Missing verified artifact: '+name)
        files[p.relative_to(ROOT).as_posix()]=p
    for name in ['soc_activity-run.log','activity-manifest.json']:
        p=ROOT/'output/design'/name
        if p.exists():files[p.relative_to(ROOT).as_posix()]=p
    assert not any(any(part in ['.git','.tools','.venv-model'] for part in Path(p).parts) or p.endswith('local-tools.json') for p in files)
    dest=ROOT/'deliverables';dest.mkdir(exist_ok=True)
    manifest={name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for name,p in sorted(files.items())}
    target=dest/'undergraduate-local-submission.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,p in sorted(files.items()):z.write(p,name)
        z.writestr('submission-manifest.json',json.dumps(manifest,indent=2)+'\n')
        z.writestr('SUBMISSION-STATUS.txt',
            'LOCAL IMPLEMENTATION, NOT OFFICIAL ACCEPTANCE\nSee docs/acceptance.md for pending official PPA/platform conditions.\n'
            'When captured, large activity sidecars remain in output/design/soc.fst and soc.vcd.gz; hashes are in docs/design-validation.json.\n'
            'Instantiated upstream E203 RTL is included; full model/audio resources can be fetched using the included resource script.\n')
    with zipfile.ZipFile(target) as z:
        if z.testzip() is not None:raise RuntimeError('ZIP verification failed')
    (dest/'submission-sha256.txt').write_text(hashlib.sha256(target.read_bytes()).hexdigest()+'  '+target.name+'\n')
    print(str(target),target.stat().st_size,'bytes; verified',len(manifest),'files')

if __name__=='__main__':main()
