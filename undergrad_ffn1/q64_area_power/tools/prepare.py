"""Build new q64 variants from the committed, verified previous handoff archive."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
from variant_rtl import transform

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT.parent/'frontend_candidates/output/ffn1_frontend_candidates_2026-11-05.tar.gz'
ARCHIVE_SHA='106db8ff129f25aa1ab64da32fda3557141f95e3a791a4db222fc906bb36d637'
CASES=[
 dict(name='q64_ref',queue='reference',narrow=False,isolate=False,parent=None),
 dict(name='q64_seq',queue='sequence',narrow=False,isolate=False,parent='q64_ref'),
 dict(name='q64_bank2',queue='bank2',narrow=False,isolate=False,parent='q64_seq'),
 dict(name='q64_bank1',queue='bank1',narrow=False,isolate=False,parent='q64_bank2'),
 dict(name='q64_bank1_mac38',queue='bank1',narrow=True,isolate=False,parent='q64_bank1'),
 dict(name='q64_bank1_fmt1',queue='bank1',narrow=False,isolate=False,formatter_depth=1,parent='q64_bank1'),
 dict(name='q64_lean',queue='bank1',narrow=True,isolate=False,formatter_depth=1,parent='q64_bank1_mac38'),
 dict(name='q64_lean_earlyfree',queue='bank1',narrow=True,isolate=False,formatter_depth=1,early_free=True,parent='q64_lean'),
]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,text):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(text.encode('utf-8'))
def save(path,value):write(path,json.dumps(value,indent=2,ensure_ascii=False)+'\n')

def prepare():
 if sha(ARCHIVE)!=ARCHIVE_SHA:raise ValueError('Prior qualified archive mismatch')
 study=ROOT/'study';reference=ROOT/'tmp/frozen_q64'
 if (study/'cases').exists():raise ValueError('Refusing to overwrite candidate workspaces')
 with tarfile.open(ARCHIVE) as tar:
  manifest=json.load(tar.extractfile('ffn1_frontend_candidates/package_manifest.json'))
  for name,digest in manifest.items():
   target=None
   prefix='study/cases/q64_fused_pause/'
   if name.startswith(prefix):target=reference/name[len(prefix):]
   elif name.startswith('study/tools/') or name.startswith('study/script/'):target=ROOT/name
   if target is not None:
    data=tar.extractfile('ffn1_frontend_candidates/'+name).read()
    if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Archive entry mismatch: '+name)
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
 source_hashes={p.relative_to(reference).as_posix():sha(p) for p in reference.rglob('*') if p.is_file()}
 entries=[]
 for design in CASES:
  case=study/'cases'/design['name']
  for folder in ('rtl','tech','vendor','firmware','filelists','config','script','tests','vectors','output/firmware'):
   shutil.copytree(reference/folder,case/folder)
  core=case/'rtl/kwt_tile_core.sv'
  if design['queue']!='reference' or design['isolate']:write(core,transform(core.read_text(),design))
  extra=[]
  if design['queue']!='reference':extra.append('kwt_output_sequence.sv')
  if design['queue'] in ('bank1','bank2'):extra.append('kwt_group_queue.sv')
  for filename in extra:shutil.copyfile(ROOT/'rtl'/filename,case/'rtl'/filename)
  if extra:
   for name in ('soc.f','accelerator.f'):
    filelist=case/'filelists'/name
    write(filelist,filelist.read_text().rstrip()+'\n'+''.join('rtl/'+n+'\n' for n in extra))
  if design['narrow']:shutil.copyfile(ROOT/'rtl/kwt_tile_mac.sv',case/'rtl/kwt_tile_mac.sv')
  if design.get('formatter_depth')==1:shutil.copyfile(ROOT/'rtl/kwt_output_formatter.sv',case/'rtl/kwt_output_formatter.sv')
  original=json.loads((reference/'case.json').read_text())
  original.update(name=design['name'],frontend=design,source_reference='q64_fused_pause')
  save(case/'case.json',original)
  entries.append(dict(name=design['name'],path='cases/'+design['name']))
 save(study/'activity_manifest.json',dict(schema_version=1,cases=entries,clock_period_fs=6666667,
     official_vectors=False,description='q64 area/power candidates, fixed pause64 firmware, same 12 vectors'))
 save(ROOT/'reports/source_reference.json',dict(archive=ARCHIVE.name,archive_sha256=ARCHIVE_SHA,
     original_case='q64_fused_pause',source_sha256=source_hashes))
 save(ROOT/'reports/designs.json',CASES)
 baseline=ROOT.parent/'verification/baseline.json'
 save(ROOT/'reports/historical_baseline.json',dict(source='undergrad_ffn1/verification/baseline.json',
     sha256=sha(baseline),data=json.loads(baseline.read_text()),
     note='Legacy task_cycles use an older measurement/configuration; not a like-for-like strict-window speedup.'))
 save(ROOT/'reports/server_reference_task00.json',dict(source='User supplied server summary, 2026-11-06; raw reports not supplied',
     case='q64_fused_pause',added_area_library_units=362794,soc_area_library_units=2601145.2,
     strict_cycles=55364.5,dynamic_mw=170.533,leakage_mw=4.23,total_mw=174.763,energy_uj=64.504444,
     setup_wns_ns=0,hold_wns_ss_only_ns=-0.19,coverage_review='required',sample='task_00_only'))
 print('PREPARED',len(entries),'q64 candidates',flush=True)

if __name__=='__main__':
 argparse.ArgumentParser(description=__doc__).parse_args();prepare()
