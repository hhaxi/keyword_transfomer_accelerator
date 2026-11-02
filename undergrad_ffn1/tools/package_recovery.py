"""Build the small saved-DDC recovery update without any server results or RTL."""
import hashlib,json,subprocess,sys,tarfile,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FILES=('run_recover_compare.sh','script/area_scope.tcl','script/recover_reports.tcl',
       'tools/recover_sweep.py','tools/ppa_metrics.py','tools/package_recovery.py',
       'docs/recover-comparison.md','tests/test_area_scope.py',
       'tests/test_recover_sweep.py','tests/test_recovery_tcl.py')

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    logs=ROOT/'output/logs';logs.mkdir(parents=True,exist_ok=True)
    log=logs/'recovery_delivery_tests.log'
    with log.open('wb') as output:
        for test in ('tests/test_area_scope.py','tests/test_recover_sweep.py','tests/test_recovery_tcl.py'):
            subprocess.run([sys.executable,test],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,check=True)
    for name in FILES:
        p=ROOT/name
        if p.suffix in ('.tcl','.sh'):assert b'\r' not in p.read_bytes(),name
    manifest=dict(files={name:digest(ROOT/name) for name in FILES},
                  purpose='Recover saved DC reports; no synthesis; preserve existing run/config/RTL',
                  default_scope='soc',default_configuration_count=16,
                  python_minimum='3.6',local_dc_api_stub_tests=True,real_pdk_execution_tested=False)
    manifest_path=ROOT/'recovery_patch_manifest.json'
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    names=FILES+('recovery_patch_manifest.json',)
    out=ROOT/'output/upload';out.mkdir(parents=True,exist_ok=True)
    archives=(out/'undergrad_ffn1_recover_ppa.tar.gz',out/'undergrad_ffn1_recover_ppa.zip')
    with tarfile.open(archives[0],'w:gz') as archive:
        for name in names:archive.add(ROOT/name,arcname='undergrad_ffn1/'+name,recursive=False)
    with zipfile.ZipFile(archives[1],'w',zipfile.ZIP_DEFLATED) as archive:
        for name in names:archive.write(ROOT/name,'undergrad_ffn1/'+name)
    with tarfile.open(archives[0],'r:gz') as archive:
        assert set(archive.getnames())=={'undergrad_ffn1/'+n for n in names}
        for name in names:assert archive.extractfile('undergrad_ffn1/'+name).read()==(ROOT/name).read_bytes()
    with zipfile.ZipFile(archives[1]) as archive:
        assert archive.testzip() is None
        for name in names:assert archive.read('undergrad_ffn1/'+name)==(ROOT/name).read_bytes()
    (out/'recovery_archives.json').write_text(json.dumps({p.name:dict(bytes=p.stat().st_size,sha256=digest(p)) for p in archives},indent=2)+'\n')
    print('RECOVERY_UPDATE_PASS',len(names),'files; no RTL/PDK/config/run data; tests='+str(log),flush=True)

if __name__=='__main__':main()
