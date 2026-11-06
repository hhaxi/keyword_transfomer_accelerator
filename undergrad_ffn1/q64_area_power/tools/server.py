"""Run qualified q64 frontend experiments on a VCS/DC server."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'study/tools'))
import quick_screen
import vcs_power

GROUPS={
 'recommended':['q64_ref','q64_seq','q64_bank2','q64_bank1_mac38','q64_lean'],
 'controls':['q64_ref','q64_seq','q64_bank2','q64_bank1'],
 'arithmetic':['q64_bank1','q64_bank1_mac38'],
 'formatter':['q64_bank1','q64_bank1_fmt1','q64_bank1_mac38','q64_lean'],
 'schedule':['q64_lean','q64_lean_earlyfree'],
 'all':[],
}
def main():
 ap=argparse.ArgumentParser(description=__doc__,add_help=False)
 mode=ap.add_mutually_exclusive_group()
 mode.add_argument('--quick',action='store_true');mode.add_argument('--full',action='store_true')
 ap.add_argument('--group',choices=sorted(GROUPS),default='recommended')
 args,remaining=ap.parse_known_args()
 if '--help' in remaining or '-h' in remaining:
  ap.print_help();return vcs_power.main(['--help'])
 if any(a=='--tasks' or a.startswith('--tasks=') for a in remaining):
  ap.error('Use --quick (task00) or --full (12 tasks), not --tasks')
 selection=[]
 if not any(a=='--case' or a.startswith('--case=') for a in remaining):
  for name in GROUPS[args.group]:selection+=['--case',name]
 if args.full:return vcs_power.main(['--study',str(ROOT/'study'),'--tasks','12']+selection+remaining)
 return quick_screen.main(['--source-study',str(ROOT/'study'),'--study',str(ROOT/'vcs_quick_study')]+selection+remaining)
if __name__=='__main__':sys.exit(main())
