"""Freeze verified source hashes and create a self-contained server upload."""
import json,hashlib,tarfile,zipfile,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    for required in ('README.md','model/PROVENANCE.json','verification/baseline.json','docs/optimization-roadmap.md'):
        assert (ROOT/required).is_file(),'Missing required submission file: '+required
    for test in ('tests/test_isolation.py','tests/test_model.py'):
        subprocess.run([sys.executable,test],cwd=ROOT,check=True)
    evidence={}
    for name in ('reset_tasks','continuous','components','structure'):
        p=ROOT/f'verification/{name}.json';r=json.loads(p.read_text());assert r['passed'],name
        if 'sources' in r:
            for relative,h in r['sources'].items():assert sha(ROOT/relative)==h,('Untested source',relative)
        for value in r.get('results',{}).values():
            for relative,h in value['sources'].items():assert sha(ROOT/relative)==h,('Untested structure',relative)
        for receipt in r.get('receipts',[]):assert sha(ROOT/receipt['log'])==receipt['log_sha256']
        if name in ('reset_tasks','continuous'):
            for relative,h in r['vector_sha256'].items():assert sha(ROOT/relative)==h,relative
        evidence[name]=sha(p)
    snapshot=[p for folder in ('rtl','tech','firmware','model') for p in (ROOT/folder).iterdir() if p.is_file()]
    vendor={p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT/'vendor').rglob('*') if p.is_file()}
    manifest=dict(scope='undergraduate FFN1 only',snapshots=[dict(package_path=p.relative_to(ROOT).as_posix(),sha256=sha(p)) for p in snapshot],
        vendor_e203=dict(revision='9f3e34f337f5d0a1236a285871ffa2032491617a',files=vendor),verification=evidence)
    (ROOT/'source_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    subprocess.run([sys.executable,'tools/check_package.py'],cwd=ROOT,check=True)
    files=[p for p in ROOT.rglob('*') if p.is_file() and p.name not in ('SHA256SUMS','upload_manifest.json') and
        not any(part in ('tmp','__pycache__','.git') for part in p.relative_to(ROOT).parts) and
        (p.relative_to(ROOT).parts[0]!='output' or p.relative_to(ROOT).parts[:2]==('output','logs')) and
        p.relative_to(ROOT).as_posix() not in ('environment/local_tools.json','config/local_config.tcl') and p.suffix!='.pyc']
    assert not any(p.suffix.lower() in ('.db','.lib','.exe','.ddc','.vvp') for p in files)
    upload={p.relative_to(ROOT).as_posix():sha(p) for p in files}
    (ROOT/'upload_manifest.json').write_text(json.dumps(dict(files=upload,scope='FFN1',official_platform=False),indent=2)+'\n')
    files.append(ROOT/'upload_manifest.json')
    (ROOT/'SHA256SUMS').write_text(''.join(sha(p)+'  '+p.relative_to(ROOT).as_posix()+'\n' for p in sorted(files)))
    files.append(ROOT/'SHA256SUMS')
    out=ROOT/'output/upload';out.mkdir(parents=True,exist_ok=True)
    tarred=out/'undergrad_ffn1.tar.gz';zipped=out/'undergrad_ffn1.zip'
    with tarfile.open(tarred,'w:gz') as a:
        for p in files:a.add(p,arcname='undergrad_ffn1/'+p.relative_to(ROOT).as_posix(),recursive=False)
    with zipfile.ZipFile(zipped,'w',zipfile.ZIP_DEFLATED) as a:
        for p in files:a.write(p,'undergrad_ffn1/'+p.relative_to(ROOT).as_posix())
    expected={'undergrad_ffn1/'+p.relative_to(ROOT).as_posix():p.read_bytes() for p in files}
    with zipfile.ZipFile(zipped) as a:assert a.testzip() is None and {n:a.read(n) for n in a.namelist()}==expected
    with tarfile.open(tarred,'r:gz') as a:assert {p.name:a.extractfile(p).read() for p in a.getmembers() if p.isfile()}==expected
    (out/'archives.json').write_text(json.dumps({p.name:dict(bytes=p.stat().st_size,sha256=sha(p)) for p in (tarred,zipped)},indent=2)+'\n')
    print('FFN1_UPLOAD_PACKAGE_PASS',len(files),'files',flush=True)
if __name__=='__main__':main()
