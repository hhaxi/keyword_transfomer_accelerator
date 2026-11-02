"""Validate tested variants and package a complete, source-only server sweep."""
import hashlib,json,subprocess,sys,tarfile,zipfile
from pathlib import Path
from options import inventory,options
from snapshots import digest,freeze_manifest
from sweep import ROOT,cases,hardware_digest,collect

def evidence(case,label):
    p=case/f'verification/{label}.json';record=json.loads(p.read_text())
    assert record['passed'],p
    for key in ('sources','harness','vector_sha256'):
        for relative,value in record.get(key,{}).items():assert digest(case/relative)==value,('Stale evidence',p,relative)
    for item in record.get('results',{}).values():
        for relative,value in item['sources'].items():assert digest(case/relative)==value,(p,relative)
        assert digest(case/item['receipt']['log'])==item['receipt']['log_sha256']
    for item in record.get('receipts',[]):assert digest(case/item['log'])==item['log_sha256'],(p,item['log'])
    return record

def validate():
    frozen=json.loads((ROOT/'experiments/baseline_frozen.json').read_text())['files']
    for relative,value in frozen.items():
        p=ROOT/'experiments/baseline'/relative
        if not p.exists() and relative in ('environment/local_tools.json','config/local_config.tcl'):continue
        assert digest(p)==value,('Baseline changed',relative)
    for test in ('tests/test_isolation.py','tests/test_model.py','tests/test_sweep.py','tests/test_area_scope.py',
                 'tests/test_recover_sweep.py','tests/test_recovery_tcl.py'):
        subprocess.run([sys.executable,test],cwd=ROOT,check=True)
    for label in ('reset_tasks','continuous','components','structure'):evidence(ROOT,label)
    reference_vectors=json.loads((ROOT/'verification/reset_tasks.json').read_text())['vector_sha256']
    result=[]
    for item in cases():
        case=ROOT/'experiments/cases'/item['name']
        assert options(case)==item['options']
        for label in ('reset_tasks','continuous'):
            record=evidence(case,label)
            assert record['tasks']==12 and len(record['task_cycles'])==12
            assert len(record['vector_sha256'])==72 and record.get('vectors_checked_before_run'), 'Re-run with complete vector preflight'
            assert record['vector_sha256']==reference_vectors, 'Cases must use identical inputs, parameters and golden outputs'
            assert record['options']==item['options']
            for profile in record['profiles'].values():
                assert profile['4']==101376 and profile['9']==11616 and profile['10']==50688
        rep=ROOT/'experiments/cases'/f'i0_h0_{item["hardware_key"]}'
        assert hardware_digest(case,'soc')==hardware_digest(rep,'soc')
        for label in ('components','structure'):evidence(rep,label)
        freeze_manifest(case)
        result.append(dict(case=item['name'],hardware_evidence=rep.relative_to(ROOT).as_posix(),
            reset=digest(case/'verification/reset_tasks.json'),continuous=digest(case/'verification/continuous.json')))
    freeze_manifest(ROOT)
    (ROOT/'verification/optimization_matrix.json').write_text(json.dumps(dict(passed=True,cases=result,
        four_state_hardware_groups=4,real_cpu=True,pdk_mapping_tested=False,timing_closed=False),indent=2)+'\n')
    collect()
    return result

def selected(p):
    rel=p.relative_to(ROOT);parts=rel.parts
    if any(v in ('tmp','run','__pycache__','.git') for v in parts):return False
    if p.suffix.lower() in ('.pyc','.exe','.db','.lib','.ddc','.vvp'):return False
    if p.name in ('upload_manifest.json','SHA256SUMS') and parts[:2]!=('experiments','baseline'):return False
    if p.name in ('local_tools.json','local_config.tcl'):return False
    if 'output' in parts:
        n=parts.index('output')
        if len(parts)<=n+1 or parts[n+1] not in ('logs','sweep','structure'):return False
    return True

def main():
    validate()
    files=sorted(p for p in ROOT.rglob('*') if p.is_file() and selected(p))
    # Private machine paths are excluded. Frozen source hashes remain unmodified.
    manifest={p.relative_to(ROOT).as_posix():digest(p) for p in files}
    baseline_record=json.loads((ROOT/'experiments/baseline_frozen.json').read_text())
    baseline_record['archive_exclusions']=[name for name in baseline_record['files']
        if not selected(ROOT/'experiments/baseline'/name)]
    (ROOT/'experiments/baseline_frozen.json').write_text(json.dumps(baseline_record,indent=2)+'\n')
    # Updating the exclusion record above changes its archive hash.
    manifest['experiments/baseline_frozen.json']=digest(ROOT/'experiments/baseline_frozen.json')
    (ROOT/'upload_manifest.json').write_text(json.dumps(dict(files=manifest,cases=16,unique_hardware=4,
        private_exclusions=['environment/local_tools.json','config/local_config.tcl'],
        pdk_mapping_tested=False),indent=2)+'\n')
    files.append(ROOT/'upload_manifest.json')
    (ROOT/'SHA256SUMS').write_text(''.join(digest(p)+'  '+p.relative_to(ROOT).as_posix()+'\n' for p in files))
    files.append(ROOT/'SHA256SUMS')
    out=ROOT/'output/upload';out.mkdir(parents=True,exist_ok=True)
    tar=out/'undergrad_ffn1_sweep.tar.gz';zip=out/'undergrad_ffn1_sweep.zip'
    with tarfile.open(tar,'w:gz') as archive:
        for p in files:archive.add(p,arcname='undergrad_ffn1/'+p.relative_to(ROOT).as_posix(),recursive=False)
    with zipfile.ZipFile(zip,'w',zipfile.ZIP_DEFLATED) as archive:
        for p in files:archive.write(p,'undergrad_ffn1/'+p.relative_to(ROOT).as_posix())
    expected={'undergrad_ffn1/'+p.relative_to(ROOT).as_posix():digest(p) for p in files}
    with tarfile.open(tar,'r:gz') as archive:
        got={p.name:hashlib.sha256(archive.extractfile(p).read()).hexdigest() for p in archive if p.isfile()}
        assert got==expected
    with zipfile.ZipFile(zip) as archive:
        assert archive.testzip() is None
        assert {n:hashlib.sha256(archive.read(n)).hexdigest() for n in archive.namelist()}==expected
    (out/'sweep_archives.json').write_text(json.dumps({p.name:dict(bytes=p.stat().st_size,sha256=digest(p)) for p in (tar,zip)},indent=2)+'\n')
    print('SWEEP_UPLOAD_PASS',len(files),'files; 16 modes / 4 hardware groups',flush=True)
if __name__=='__main__':main()
