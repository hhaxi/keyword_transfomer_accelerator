"""Check inherited drivers, real seed clones, dispatch and fail-closed acceptance."""
import copy,hashlib,json,sys,tarfile
from unittest.mock import patch
from prepare import ROOT,ARCHIVE,ARCHIVE_SHA,sha,save,CASES
sys.path.insert(0,str(ROOT/'study/tools'))
import quick_screen,vcs_power,server
from gate_metrics import parse,equal

def main():
 if sha(ARCHIVE)!=ARCHIVE_SHA:raise ValueError('Prior archive changed')
 drivers={};inherited={}
 with tarfile.open(ARCHIVE) as tar:
  manifest=json.load(tar.extractfile('ffn1_q64_area_power/package_manifest.json'))
  for folder in ('study/tools','study/script'):
   for p in (ROOT/folder).rglob('*'):
    if not p.is_file() or '__pycache__' in p.parts:continue
    rel=p.relative_to(ROOT).as_posix()
    if sha(p)!=manifest.get(rel):raise ValueError('Inherited driver changed: '+rel)
    drivers[rel]=sha(p)
  for label in ('server_tool_tests','server_tcl_tests','native_exporter_tests'):
   for ext in ('.json','.log'):
    rel='reports/inherited/'+label+ext;data=tar.extractfile('ffn1_q64_area_power/'+rel).read()
    if hashlib.sha256(data).hexdigest()!=manifest[rel]:raise ValueError('Inherited evidence changed')
    p=ROOT/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);inherited[rel]=sha(p)
   if not json.loads((ROOT/'reports/inherited'/(label+'.json')).read_text())['passed']:raise ValueError('Prior tests failed')
 save(ROOT/'reports/server_driver_reuse.json',dict(passed=True,archive_sha256=ARCHIVE_SHA,
  driver_sha256=drivers,inherited_evidence_sha256=inherited,note='Common drivers unchanged; inherited prior tests. New adapter/entry tested separately, no VCS/DC execution.'))
 names=[d['name'] for d in CASES];checks=[]
 for group,selection in server.GROUPS.items():
  for full in (False,True):
   with patch.object(sys,'argv',['server.py','--full' if full else '--quick','--group',group,'--check']), \
        patch.object(server.vcs_power,'main',return_value=0) as vm,patch.object(server.quick_screen,'main',return_value=0) as qm:
    server.main();call=(vm if full else qm).call_args.args[0]
    if [call[i+1] for i,x in enumerate(call) if x=='--case']!=selection:raise ValueError('Group dispatch mismatch')
    checks.append(dict(group=group,full=full,passed=True))
 with patch.object(sys,'argv',['server.py','--case','fmt1_cg_result']),patch.object(server.quick_screen,'main',return_value=0) as qm:
  server.main();call=qm.call_args.args[0]
  if [call[i+1] for i,x in enumerate(call) if x=='--case']!=['fmt1_ref','fmt1_cg_result']:raise ValueError('Reference not added')
 checks.append(dict(test='explicit_candidate_always_adds_reference',passed=True))
 clone=ROOT/'tmp/server_integration_study';quick_screen.prepare_study(ROOT/'study',clone)
 for name in names:
  for case in (ROOT/'study/cases'/name,clone/'cases'/name):vcs_power.verify_seed(case);vcs_power.prepare_case(case,check_only=True)
 reference=json.loads((ROOT/'reports/qualification_fmt1_ref.json').read_text())['modes']['reset']
 actual=json.loads((ROOT/'reports/qualification_fmt1_cg_combined.json').read_text())['modes']['reset']
 text=(ROOT/actual['receipt']['log']).read_text();equal(reference,actual,'positive')
 parse('fmt1_cg_combined',text,actual['windows'])
 def reject(label,fn):
  try:fn()
  except ValueError:checks.append(dict(test=label,passed=True));return
  raise AssertionError('Acceptance failed open: '+label)
 changed=copy.deepcopy(actual);changed['windows'][0]['duration_fs']+=6666667
 reject('one_cycle_change_rejected',lambda:equal(reference,changed,'negative'))
 changed_profile=copy.deepcopy(actual);changed_profile['profiles']['0']['5']+=1
 reject('profile_change_rejected',lambda:equal(reference,changed_profile,'negative'))
 reject('missing_clock_evidence_rejected',lambda:parse('fmt1_cg_combined','',actual['windows']))
 reject('wrong_clock_count_rejected',lambda:parse('fmt1_cg_combined',text.replace('edges=800 expected=800','edges=801 expected=800',1),actual['windows']))
 reject('missing_same_run_reference_rejected',lambda:server.validate_captures(clone,['fmt1_cg_combined']))
 # Simulate the API boundary with genuine local logs; these are NOT VCS runs.
 receipts={}
 for name in names:
  q=json.loads((ROOT/'reports'/('qualification_'+name+'.json')).read_text())['modes']['reset']
  p=clone/'cases'/name/'output/activity/mock_simulation.log';p.parent.mkdir(parents=True,exist_ok=True)
  p.write_bytes((ROOT/q['receipt']['log']).read_bytes())
  receipts[name]=dict(simulator='VCS',simulation_log='output/activity/mock_simulation.log',task_count=12)
 with patch.object(vcs_power.power_server,'validate_capture',side_effect=lambda case:(None,receipts[case.name])):
  server.validate_captures(clone,names)
 checks.append(dict(test='pre_dc_acceptance_mock_boundary',passed=True))
 inputs=['tools/server.py','tools/check_server.py','tools/gate_metrics.py','study/activity_manifest.json','run_server.sh']
 save(ROOT/'reports/server_integration.json',dict(passed=True,cases=names,checks=checks,
  inputs={p:sha(ROOT/p) for p in inputs},quick_clones_verified=True,backend_executed=False,
  note='Dispatcher/mutation tests and real seed/clone checks; mock VCS API boundary uses local Verilator logs.'))
 print('SERVER_INTEGRATION_PASS',len(names),'seeds/clones;',len(checks),'entry/acceptance checks')
if __name__=='__main__':main()
