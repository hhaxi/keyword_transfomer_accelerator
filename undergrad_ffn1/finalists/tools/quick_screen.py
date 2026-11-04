"""Isolated task00 screening of the four fixed FFN1 candidates (Python3.6)."""
from __future__ import print_function
import argparse
from pathlib import Path
import shutil
import sys
import vcs_power as vcs

ROOT=Path(__file__).resolve().parents[1]

def clone_case(source,target):
 source,target=Path(source).resolve(),Path(target).resolve()
 if source==target:raise ValueError('quick study must be separate from full study')
 seed=vcs.verify_seed(source)
 names=set(seed['source_sha256'])|set(seed['vector_sha256'])|{'case.json','vcs_seed.json','output/firmware/kwt.hex'}
 if (source/'output/firmware/size.vh').is_file():names.add('output/firmware/size.vh')
 for folder in ('rtl','tech','vendor','firmware','filelists','config','script','tests'):
  for p in (source/folder).rglob('*'):
   if p.is_file() and not any(n in p.parts for n in ('__pycache__','tmp','run','.git')) and p.suffix not in ('.pyc','.db','.lib','.vcd','.gz','.vvp','.exe','.o'):
    names.add(p.relative_to(source).as_posix())
 if target.exists():
  vcs.verify_seed(target)
  for n in names:
   if not (target/n).is_file() or vcs.sha(source/n)!=vcs.sha(target/n):
    raise ValueError('existing quick seed differs; use a fresh --study directory: '+n)
  return
 target.mkdir(parents=True)
 for n in sorted(names):
  p=source/n;p.resolve().relative_to(source)
  dst=target/n;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(str(p),str(dst))
 vcs.verify_seed(target)

def prepare_study(source,study):
 source,study=Path(source).resolve(),Path(study).resolve()
 if source==study or source in study.parents or study in source.parents:
  raise ValueError('quick study must not be inside the full study')
 original=vcs.load(source/'activity_manifest.json')
 for item in original['cases']:
  seed=vcs.confined(source,item['path']);target=vcs.confined(study,item['path'])
  if seed.name!=item['name']:raise ValueError('manifest seed name/path mismatch')
  clone_case(seed,target)
 manifest=dict(original,quick_screen=True,sample='task_00_only',task_count=1)
 vcs.save(study/'activity_manifest.json',manifest)
 print('QUICK_STUDY_READY %s; same task_00 for all %s candidates' % (study,len(original['cases'])),flush=True)

def main(argv=None):
 parser=argparse.ArgumentParser(description=__doc__,add_help=False)
 parser.add_argument('--source-study',type=Path,default=ROOT/'vcs_power_study')
 parser.add_argument('--study',type=Path,default=ROOT/'vcs_quick_study')
 args,remaining=parser.parse_known_args(argv)
 if any(a=='--tasks' or a.startswith('--tasks=') for a in remaining):
  parser.error('quick screening always uses task00 only; full mode uses run_vcs_power.sh')
 if '--help' in remaining or '-h' in remaining:
  parser.print_help();return vcs.main(['--help'])
 prepare_study(args.source_study,args.study)
 return vcs.main(['--study',str(args.study),'--tasks','1']+remaining)

if __name__=='__main__':
 try:sys.exit(main())
 except (OSError,ValueError,KeyError,RuntimeError) as e:
  print('QUICK_SCREEN_FAILED: %s'%e,file=sys.stderr,flush=True);sys.exit(1)
