"""Generate five isolated candidates from the verified q64_bank1_fmt1 archive."""
import argparse,hashlib,json,shutil,tarfile
from pathlib import Path
from variant_rtl import once,result_queue,mac_core,formatter
ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT.parent/'q64_area_power/output/ffn1_q64_area_power_2026-11-06.tar.gz'
ARCHIVE_SHA='0157190ad78cccbd302968dc3016bedb6a64b8ad3ab61285b3bdba0b9ad03652'
CASES=[dict(name='fmt1_ref',result=False,mac=False,formatter=False),
 dict(name='fmt1_cg_result',result=True,mac=False,formatter=False),
 dict(name='fmt1_cg_mac',result=False,mac=True,formatter=False),
 dict(name='fmt1_cg_formatter',result=False,mac=False,formatter=True),
 dict(name='fmt1_cg_combined',result=True,mac=True,formatter=True)]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,t):p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(t.encode('utf-8'))
def save(p,j):write(p,json.dumps(j,indent=2,ensure_ascii=False)+'\n')

def gate_paths(design):
 base='dut.bus.accelerator';core=base+'.tile_engine.core';g=[]
 if design['result']:
  g += [('result_r%d'%i,core+'.result_queue.banks[0].clock_groups[%d].u_gate'%i,320) for i in range(4)]
 if design['mac']:
  g += [('mac_r%d'%i,core+'.mac_clock_groups[%d].u_gate'%i,320) for i in range(4)]
 if design['formatter']:
  g += [('partial%d'%i,base+'.formatter.partial_groups[%d].u_gate'%i,55 if i==0 else 40) for i in range(3)]
  g += [('completed',base+'.formatter.completed_groups[0].u_gate',176)]
 return g

def monitor(design):
 gates=gate_paths(design);n=max(1,len(gates))
 lines=['// Generated scoreboard: strict task window, no DUT traffic changes.',
  'bit cg_active=0; longint cg_root_edges=0; longint cg_last_root_fs=0;',
  'longint cg_seen[0:%d]; longint cg_expected[0:%d];'%(n-1,n-1),
  'task automatic cg_begin; begin cg_root_edges=0;',
  'for(integer i=0;i<%d;i++)begin cg_seen[i]=0;cg_expected[i]=0;end'%n,
  'cg_active=1; end endtask',
  'always @(posedge clk)begin',
  'cg_last_root_fs=measurement_clock.now_fs();',
  'if(cg_active)begin cg_root_edges++;']
 for i,(_,path,_) in enumerate(gates):
  lines+=['if(%s.en || %s.test_en) cg_expected[%d]++;'%(path,path,i)]
 lines+=['#0.000001;']
 for i,(name,_,_) in enumerate(gates):
  lines+=['if(cg_seen[%d]!=cg_expected[%d])$fatal(1,"Missing/extra gated edge: %s");'%(i,i,name)]
 lines+=['end end']
 for i,(name,path,_) in enumerate(gates):
  lines+=['always @(posedge %s.gclk)begin'%path,
   'if(clk!==1\'b1 || measurement_clock.now_fs()!=cg_last_root_fs)$fatal(1,"Off-edge gate pulse: %s");'%name,
   'if(cg_active)cg_seen[%d]++;end'%i]
 lines+=['task automatic cg_end;begin #0.000001; cg_active=0;',
  '$display("CG_WINDOW task=%0d root_edges=%0d gates='+str(len(gates))+'",taskid,cg_root_edges);']
 for i,(name,_,bits) in enumerate(gates):
  lines+=['$display("CG_ACTIVITY task=%0d gate='+name+' edges=%0d expected=%0d root_edges=%0d bits='+str(bits)+'",taskid,cg_seen['+str(i)+'],cg_expected['+str(i)+'],cg_root_edges);']
 lines+=['end endtask']
 return '\n'.join(lines)+'\n'

def prepare():
 if sha(ARCHIVE)!=ARCHIVE_SHA:raise ValueError('Frozen archive SHA mismatch')
 if (ROOT/'study/cases').exists():raise ValueError('Refusing overwrite')
 ref=ROOT/'tmp/frozen_fmt1'
 with tarfile.open(ARCHIVE) as tar:
  manifest=json.load(tar.extractfile('ffn1_q64_area_power/package_manifest.json'))
  for rel,h in manifest.items():
   target=None;prefix='study/cases/q64_bank1_fmt1/'
   if rel.startswith(prefix):target=ref/rel[len(prefix):]
   elif rel.startswith(('study/tools/','study/script/')):target=ROOT/rel
   elif rel in ('reports/qualification_q64_bank1_fmt1.json','reports/historical_baseline.json'):
    target=ROOT/'reports/frozen'/Path(rel).name
   if target is not None:
    data=tar.extractfile('ffn1_q64_area_power/'+rel).read()
    if hashlib.sha256(data).hexdigest()!=h:raise ValueError('Frozen entry mismatch')
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
 save(ROOT/'reports/source_reference.json',dict(archive=ARCHIVE.name,sha256=ARCHIVE_SHA,
  original_case='q64_bank1_fmt1',files={p.relative_to(ref).as_posix():sha(p) for p in ref.rglob('*') if p.is_file()}))
 for d in CASES:
  case=ROOT/'study/cases'/d['name']
  for folder in ('rtl','tech','vendor','firmware','filelists','config','script','tests','vectors','output/firmware'):
   shutil.copytree(ref/folder,case/folder)
  if d['result']:
   p=case/'rtl/kwt_group_queue.sv';write(p,result_queue(p.read_text()))
  if d['mac']:
   p=case/'rtl/kwt_tile_core.sv';write(p,mac_core(p.read_text()))
  if d['formatter']:
   p=case/'rtl/kwt_output_formatter.sv';write(p,formatter(p.read_text()))
  gates=gate_paths(d)
  if gates:
   shutil.copyfile(ROOT/'rtl/kwt_clock_gate.sv',case/'rtl/kwt_clock_gate.sv')
   for file in ('soc.f','accelerator.f'):
    p=case/'filelists'/file;write(p,p.read_text().rstrip()+'\nrtl/kwt_clock_gate.sv\n')
  write(case/'tests/cg_monitor.svh',monitor(d))
  for tb in ('tb_soc_power.sv','tb_soc_vcs_power.sv'):
   p=case/'tests'/tb;t=p.read_text()
   t=once(t,'    kwt_measure_fs measurement_clock();','    kwt_measure_fs measurement_clock();\n    `include "cg_monitor.svh"')
   t=once(t,'            power_started=1;','            power_started=1; cg_begin();')
   marker='$display("POWER_END task=%0d time_fs=%0d cycle=%0d",taskid,measurement_clock.now_fs(),cycles);'
   t=once(t,marker,marker+'\n            cg_end();');write(p,t)
  shutil.copyfile(ROOT/'backend/clock_gating.tcl',case/'script/clock_gating.tcl')
  write(case/'config/clock_gating_config.tcl','set kwt_cg_expected %d\n'%len(gates))
  p=case/'script/set_env.tcl';write(p,p.read_text()+'\nsource [file join $backend_root script clock_gating.tcl]\nkwt_cg_prepare\n')
  p=case/'script/read_file.tcl';t=p.read_text().replace('{SYNTHESIS DISABLE_SV_ASSERTION}','{SYNTHESIS DISABLE_SV_ASSERTION KWT_USE_LIBRARY_ICG}');write(p,t+'\nkwt_cg_validate elaborated\n')
  p=case/'script/write_file.tcl';write(p,p.read_text()+'\nkwt_cg_report\n')
  meta=json.loads((ref/'case.json').read_text());meta.update(name=d['name'],clock_gating=d,source_reference='q64_bank1_fmt1')
  save(case/'case.json',meta)
 save(ROOT/'reports/designs.json',CASES)
 save(ROOT/'study/activity_manifest.json',dict(schema_version=1,clock_period_fs=6666667,official_vectors=False,
  cases=[dict(name=d['name'],path='cases/'+d['name']) for d in CASES],description='fmt1 clock gating; exact cycles required'))
 print('PREPARED',len(CASES),'cases',flush=True)
if __name__=='__main__':argparse.ArgumentParser(description=__doc__).parse_args();prepare()
