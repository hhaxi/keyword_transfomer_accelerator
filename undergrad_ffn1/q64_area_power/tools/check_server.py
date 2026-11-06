"""Validate inherited driver identity, new dispatch, and real seed/quick clones."""
import hashlib,json,sys,tarfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'study/tools'))
from prepare import ARCHIVE,ARCHIVE_SHA,sha,save
import quick_screen,vcs_power,server

def main():
 if sha(ARCHIVE)!=ARCHIVE_SHA:raise ValueError('Prior archive changed')
 drivers={}
 inherited={}
 with tarfile.open(ARCHIVE) as tar:
  manifest=json.load(tar.extractfile('ffn1_frontend_candidates/package_manifest.json'))
  for folder in ('study/tools','study/script'):
   for p in (ROOT/folder).rglob('*'):
    if not p.is_file() or '__pycache__' in p.parts:continue
    rel=p.relative_to(ROOT).as_posix()
    if sha(p)!=manifest.get(rel):raise ValueError('Inherited driver changed: '+rel)
    drivers[rel]=sha(p)
  for label in ('server_tool_tests','server_tcl_tests','native_exporter_tests'):
   for ext in ('.json','.log'):
    rel='reports/'+label+ext
    data=tar.extractfile('ffn1_frontend_candidates/'+rel).read()
    if hashlib.sha256(data).hexdigest()!=manifest[rel]:raise ValueError('Inherited evidence changed')
    dest=ROOT/'reports/inherited'/(label+ext);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
    inherited[dest.relative_to(ROOT).as_posix()]=sha(dest)
   if not json.loads((ROOT/'reports/inherited'/(label+'.json')).read_text())['passed']:
    raise ValueError('Inherited tests failed')
 save(ROOT/'reports/server_driver_reuse.json',dict(passed=True,archive=ARCHIVE.name,
  archive_sha256=ARCHIVE_SHA,driver_sha256=drivers,inherited_evidence_sha256=inherited,
  note='Prior test results inherited, not rerun. All common drivers byte-identical; no VCS/DC execution on this host.'))
 names=[e['name'] for e in json.loads((ROOT/'study/activity_manifest.json').read_text())['cases']]
 checks=[]
 for group,selection in server.GROUPS.items():
  if set(selection)-set(names):raise ValueError('Unknown dispatch case')
  for full in (False,True):
   with patch.object(sys,'argv',['server.py','--full' if full else '--quick','--group',group,'--check']), \
        patch.object(server.vcs_power,'main',return_value=0) as vm, \
        patch.object(server.quick_screen,'main',return_value=0) as qm:
    server.main();call=(vm if full else qm).call_args.args[0]
    actual=[call[i+1] for i,a in enumerate(call) if a=='--case']
    if actual!=selection or '--check' not in call:raise ValueError('Dispatch mismatch')
    if full and call[call.index('--tasks')+1]!='12':raise ValueError('Wrong task count')
    checks.append(dict(group=group,full=full,passed=True))
 with patch.object(sys,'argv',['server.py','--quick','--group','all','--case','q64_ref']), \
      patch.object(server.quick_screen,'main',return_value=0) as qm:
  server.main()
  if qm.call_args.args[0].count('--case')!=1:raise ValueError('Explicit case override failed')
 clone=ROOT/'tmp/server_integration_study'
 quick_screen.prepare_study(ROOT/'study',clone)
 for name in names:
  for case in (ROOT/'study/cases'/name,clone/'cases'/name):
   vcs_power.verify_seed(case);vcs_power.prepare_case(case,check_only=True)
 manifest=json.loads((clone/'activity_manifest.json').read_text())
 if manifest['task_count']!=1 or manifest['sample']!='task_00_only':raise ValueError('Quick metadata incorrect')
 save(ROOT/'reports/server_integration.json',dict(passed=True,cases=names,dispatch_checks=checks,
  explicit_case_override=True,quick_clones_verified=True,backend_executed=False,
  inputs={p:sha(ROOT/p) for p in ('tools/server.py','tools/check_server.py','study/activity_manifest.json','run_server.sh')}))
 print('SERVER_INTEGRATION_PASS',len(names),'case seeds and quick clones;',len(checks)+1,'dispatch checks')
if __name__=='__main__':main()
