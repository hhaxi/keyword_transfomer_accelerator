"""Package verified encoder sources/artifacts; retain historical FFN archives."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
from build_soc import source_files,SOC
from collect_encoder import main as collect

ROOT=Path(__file__).resolve().parents[1]


def main():
    collect()  # Refuse a package with missing/failing tests or stale vectors.
    # Package version-controlled sources; unrelated untracked drafts stay local.
    # Stage new project files before packaging.
    names=subprocess.check_output(['git','ls-files','--cached','-z'],cwd=ROOT).decode().split('\0')
    files={n:ROOT/n for n in names if n and (ROOT/n).is_file()}
    for name in source_files():files[name]=ROOT/name
    for folder in [SOC,ROOT/'assets/sources/keyword-transformer-237e4097afd4f6851e0b82f0a8d65c2dfe8eae30']:
        for p in folder.glob('LICENSE*'):files[p.relative_to(ROOT).as_posix()]=p
    for folder in ['output/encoder-vectors','output/encoder-calibration','output/encoder-math',
                   'output/vectors','output/ffn-vectors','output/ffn-calibration','output/ffn-edges']:
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and p.suffix in ['.hex','.json','.npz','.vh','.txt']:files[p.relative_to(ROOT).as_posix()]=p
    for folder in ['output/design','output/encoder-design']:
        for p in (ROOT/folder).glob('*'):
            if p.is_file() and p.suffix in ['.log','.v','.json','.ys']:files[p.relative_to(ROOT).as_posix()]=p
        for p in (ROOT/folder/'firmware').glob('*'):
            if p.is_file():files[p.relative_to(ROOT).as_posix()]=p
    for name in ['encoder-validation-export.log','encoder-training-export.log']:
        p=ROOT/'output'/name
        if p.exists():files[p.relative_to(ROOT).as_posix()]=p
    for name in files:
        if any(part in ['.git','.tools','.venv-model','__pycache__'] for part in Path(name).parts) or name.endswith('local-tools.json'):
            raise RuntimeError('Local environment leaked into package: '+name)
    manifest={n:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for n,p in sorted(files.items())}
    dest=ROOT/'deliverables';dest.mkdir(exist_ok=True)
    target=dest/'undergraduate-encoder-local-submission.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,p in sorted(files.items()):z.write(p,name)
        z.writestr('submission-manifest.json',json.dumps(manifest,indent=2)+'\n')
        z.writestr('SUBMISSION-STATUS.txt',
            'LOCAL FULL ENCODER EXTENSION; NOT OFFICIAL ACCEPTANCE\n'
            'See docs/full-encoder.md and docs/encoder-validation.json.\n'
            'Original FFN entry points and v8 reports remain as a separately identified baseline.\n'
            'Official cell/SRAM timing/area/power libraries and official sample/platform evaluation remain pending.\n'
            'Toolchains, audio dataset, caches and credentials are excluded.\n')
    with zipfile.ZipFile(target) as z:
        if z.testzip() is not None:raise RuntimeError('ZIP CRC failed')
        for name,d in manifest.items():
            if hashlib.sha256(z.read(name)).hexdigest()!=d['sha256']:raise RuntimeError('ZIP hash mismatch '+name)
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    (dest/'encoder-submission-sha256.txt').write_text(digest+'  '+target.name+'\n')
    print(str(target),target.stat().st_size,'bytes;',len(files),'verified files;',digest)


if __name__=='__main__':main()
