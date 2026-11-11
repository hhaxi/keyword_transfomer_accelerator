"""Run gate candidates with a strict functional/cycle check before launching DC."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'study/tools'))
import quick_screen,vcs_power
from optional_options import read as read_options
from gate_metrics import parse,equal
GROUPS={'all':[],
 'result':['fmt1_ref','fmt1_cg_result'],'mac':['fmt1_ref','fmt1_cg_mac'],
 'formatter':['fmt1_ref','fmt1_cg_formatter'],'combined':['fmt1_ref','fmt1_cg_combined']}

def validate_captures(study,names):
 if 'fmt1_ref' not in names:raise ValueError('Same-run reference required')
 records={};gates={}
 for name in names:
  case=study/'cases'/name
  _,receipt=vcs_power.power_server.validate_capture(case)
  if receipt.get('simulator')!='VCS':raise ValueError('Fresh VCS capture required')
  text=(case/receipt['simulation_log']).read_text()
  windows,profiles=vcs_power.validate_simulation(text,read_options(case),receipt['task_count'])
  records[name]=dict(windows=windows,profiles=profiles)
  gates[name]=parse(name,text,windows)
 for name in names:equal(records['fmt1_ref'],records[name],name)
 frozen=json.loads((ROOT/'reports/qualification_fmt1_ref.json').read_text())['modes']['reset']
 n=len(records['fmt1_ref']['windows'])
 expected=dict(windows=frozen['windows'][:n],profiles={str(i):frozen['profiles'][str(i)] for i in range(n)})
 equal(expected,records['fmt1_ref'],'VCS vs qualified reference')
 vcs_power.power_server.save(study/'server/clock_gating_frontend_acceptance.json',dict(
  passed=True,per_task_cycles_identical=True,profiles_identical=True,cases=names,clock_edges=gates,
  icg_mapping_review_required=True,postmapping_equivalence_required=True,power_coverage_review_required=True))
 print('PRE_DC_CLOCK_GATING_ACCEPTANCE_PASS',len(names),'cases',flush=True)

def main():
 ap=argparse.ArgumentParser(description=__doc__,add_help=False)
 mode=ap.add_mutually_exclusive_group();mode.add_argument('--quick',action='store_true');mode.add_argument('--full',action='store_true')
 ap.add_argument('--group',choices=sorted(GROUPS),default='all')
 args,remaining=ap.parse_known_args()
 if '--help' in remaining or '-h' in remaining:ap.print_help();return vcs_power.main(['--help'])
 if any(x=='--tasks' or x.startswith('--tasks=') for x in remaining):ap.error('Use --quick or --full')
 if any(x=='--study' or x.startswith('--study=') or x=='--source-study' or x.startswith('--source-study=') for x in remaining):
  ap.error('Use this package study; custom studies require explicit requalification')
 selection=[]
 explicit=[remaining[i+1] for i,x in enumerate(remaining[:-1]) if x=='--case']+[x.split('=',1)[1] for x in remaining if x.startswith('--case=')]
 if explicit:
  if 'fmt1_ref' not in explicit:selection+=['--case','fmt1_ref']
 else:
  for name in GROUPS[args.group]:selection+=['--case',name]
 study=ROOT/('study' if args.full else 'vcs_quick_study')
 original=vcs_power.power_server.main
 def guarded(argv):
  names=[argv[i+1] for i,x in enumerate(argv[:-1]) if x=='--case']
  validate_captures(study,names)
  return original(argv)
 vcs_power.power_server.main=guarded
 try:
  if args.full:return vcs_power.main(['--study',str(study),'--tasks','12']+selection+remaining)
  return quick_screen.main(['--source-study',str(ROOT/'study'),'--study',str(study)]+selection+remaining)
 finally:vcs_power.power_server.main=original
if __name__=='__main__':sys.exit(main())
