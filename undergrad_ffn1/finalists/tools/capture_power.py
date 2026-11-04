"""Capture real E203 task activity in isolated copies; canonical cases stay frozen."""
import argparse,concurrent.futures,hashlib,json,os,re,shutil,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STUDY=ROOT/'power_study'
CANDIDATES=(
 'flat_f0_p0_o0_w0_b1_d1_h0',
 'flat_f0_p0_o0_w1_b1_d1_h0',
 'dual32_f1_p0_o0_w2_b1_d1_h0',
 'dual32_f0_p0_o1_w1_b1_d1_h0')
CLOCK_FS=6666667

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as source:
  for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
 return h.hexdigest()

def signature(values):return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()

def make_overlay(original):
 changes={
  '`timescale 1ns/1ps':'`timescale 1ns/1fs',
  'reg clk=0;always #3.333 clk=~clk;':'reg clk=0;always begin #3.333333 clk=1; #3.333334 clk=0; end',
  'kwt_ffn1_soc dut(.*);':'''kwt_ffn1_soc dut(.*);
    bit power_seen=0,power_started=0;
    always @(posedge h_valid) begin
        if(measuring && !power_started) begin
            if(h_read || h_addr!=32'ha0010000) $fatal(1,"Unexpected first Host load");
            power_started=1;
            $display("POWER_BEGIN task=%0d time_fs=%0.0f cycle=%0d",taskid,$realtime*1000000.0,cycles);
            $fflush();
        end
    end
    // Observe the last actual DMA write response, not later Host mailbox polling.
    always @(posedge clk) begin
        if(measuring && power_started && !power_seen && dut.bus.accelerator.retire &&
           dut.bus.accelerator.phase==4 && !dut.bus.accelerator.outstanding_read &&
           dut.bus.accelerator.write_received==`KWT_OUTPUT_WORDS-1 &&
           !dut.bus.accelerator.stopping) begin
            power_seen=1;
            $display("POWER_END task=%0d time_fs=%0.0f cycle=%0d",taskid,$realtime*1000000.0,cycles);
            $fflush();
        end
    end''',
  'start_cycle=cycles;':'start_cycle=cycles; power_seen=0; power_started=0;',
  'task_cycles=cycles-start_cycle;total_cycles+=task_cycles;':'if(!power_seen) $fatal(1,"Final DMA write-response boundary missing");\n            task_cycles=cycles-start_cycle;total_cycles+=task_cycles;'}
 result=original
 for before,after in changes.items():
  if result.count(before)!=1:raise ValueError('Canonical TB template changed: '+before[:60])
  result=result.replace(before,after)
 return result

def parse_windows(text,tasks):
 begins={};ends={}
 for kind,task,timestamp,cycle in re.findall(r'POWER_(BEGIN|END) task=(\d+) time_fs=(\d+) cycle=(\d+)',text):
  group=begins if kind=='BEGIN' else ends;t=int(task)
  if t in group:raise ValueError('Duplicate activity boundary')
  group[t]=(int(timestamp),int(cycle))
 legacy={int(t):int(c) for t,c in re.findall(r'SOC_TASK_PASS task=(\d+) cycles=(\d+) outputs=25344',text)}
 if set(begins)!=set(range(tasks)) or set(ends)!=set(begins) or set(legacy)!=set(begins):
  raise ValueError('Incomplete activity windows or functional task results')
 windows=[];last=-1
 for task in range(tasks):
  start,bc=begins[task];end,ec=ends[task]
  if end<=start or start<=last:raise ValueError('Invalid task interval')
  windows.append(dict(task=task,start_fs=start,end_fs=end,duration_fs=end-start,
      cycles=(end-start)/CLOCK_FS,legacy_cycles=legacy[task],begin_cycle=bc,end_cycle=ec))
  last=end
 return windows

def selected_sources(case):
 files=(case/'filelists/soc.f').read_text().splitlines()
 files+=['filelists/soc.f','tests/macro_fixtures.sv','tests/sram_config.vh','tests/tb_soc.sv',
         'tests/tb_soc_power.sv','tools/capture_power.py','rtl/kwt_options.vh','rtl/kwt_optional.vh',
         'case.json','config/optional.json','config/optimizations.json','config/optional_config.tcl','config/optimization_config.tcl']
 files += [p.relative_to(case).as_posix() for folder in ('firmware','vendor/e203/rtl/e203/core')
           for p in (case/folder).glob('*') if p.is_file()]
 return {name:sha(case/name) for name in sorted(set(files))}

def validate_snapshot(source,target):
 names=[p.relative_to(source).as_posix() for folder in ('rtl','tech','firmware','vendor','filelists','config')
        for p in (source/folder).rglob('*') if p.is_file() and p.name!='local_config.tcl' and '__pycache__' not in p.parts]
 if (source/'case.json').is_file():names.append('case.json')
 for name in names:
  if not (target/name).is_file() or sha(source/name)!=sha(target/name):
   raise ValueError('Snapshot differs from qualified original: '+name)
 return {name:sha(source/name) for name in names}

def prepare(name):
 if name not in CANDIDATES:raise ValueError('Unknown activity candidate')
 source=ROOT/'cases'/name;target=STUDY/'cases'/name
 from optional_sweep import valid_record,valid_structure
 if not valid_record(source,'reset_tasks',12) or not valid_record(source,'continuous',12) or not valid_structure(source):
  raise ValueError('Original candidate is not qualified: '+name)
 if not target.exists():
  target.mkdir(parents=True)
  for folder in ('rtl','tech','firmware','vendor','model','vectors','filelists','config','script','tests','tools','environment','verification'):
   shutil.copytree(str(source/folder),str(target/folder),ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  for p in source.iterdir():
   if p.is_file() and p.suffix in ('.json','.sh','.md'):shutil.copyfile(str(p),str(target/p.name))
  for folder in ('output/logs','output/optional_structure'):
   shutil.copytree(str(source/folder),str(target/folder))
  shutil.copyfile(str(source/'output/build.json'),str(target/'output/build.json'))
  (target/'power_source.json').write_text(json.dumps(dict(case=name,source_case='cases/'+name,
      original_source_sha256={p.relative_to(source).as_posix():sha(p) for folder in ('rtl','tech','firmware','filelists') for p in (source/folder).rglob('*') if p.is_file()}),indent=2)+'\n')
 validate_snapshot(source,target)
 # The only instrumentation is a separate TB file and its driver; no DUT edit.
 (target/'tests/tb_soc_power.sv').write_bytes(make_overlay((source/'tests/tb_soc.sv').read_text()).encode())
 shutil.copyfile(str(ROOT/'tools/capture_power.py'),str(target/'tools/capture_power.py'))
 if (ROOT/'tools/power_vcd.py').is_file():
  shutil.copyfile(str(ROOT/'tools/power_vcd.py'),str(target/'tools/power_vcd.py'))
 cfg=ROOT/'environment/local_tools.json'
 if cfg.is_file():shutil.copyfile(str(cfg),str(target/'environment/local_tools.json'))
 return target

def capture_worker(case,tasks,skip_build=False,export=True):
 case=Path(case).resolve();os.chdir(str(case));sys.path.insert(0,str(case/'tools'))
 import verify
 cfg=verify.settings();env=verify.environment(cfg)
 sources_before=selected_sources(case)
 config_names=['case.json','config/optional.json','config/optimizations.json','config/optional_config.tcl',
    'config/optimization_config.tcl','rtl/kwt_optional.vh','rtl/kwt_options.vh']
 config_hashes={n:sha(case/n) for n in config_names}
 vector_hashes=verify.vector_signature()
 out=case/'output/activity';out.mkdir(parents=True,exist_ok=True)
 receipt=out/('capture.json' if tasks==12 else 'smoke.json')
 receipt.write_text(json.dumps(dict(passed=False,stage='running',tasks=[]))+'\n')
 mdir=case/'tmp/power_sim';mdir.mkdir(parents=True,exist_ok=True)
 exe=mdir/('Vtb_soc.exe' if os.name=='nt' else 'Vtb_soc')
 stamp=mdir/'capture_build.json';receipts=[]
 if skip_build:
  saved=json.loads(stamp.read_text())
  if saved['sources']!=sources_before or sha(exe)!=saved['executable_sha256']:raise ValueError('Trace binary is stale')
  if any(sha(case/n)!=h for n,h in saved['firmware'].items()):raise ValueError('Trace firmware changed')
 else:
  receipts.append(verify.build_firmware(cfg,env))
  sources=(case/'filelists/soc.f').read_text().splitlines()+['tests/macro_fixtures.sv','tests/tb_soc_power.sv']
  _,rec=verify.run('power_elaborate',[cfg['verilator'],'--cc','--exe','--main','--timing','--trace',
    '--trace-max-array','64','--trace-max-width','4096','-Wno-fatal','--top-module','tb_soc','--Mdir','tmp/power_sim',
    '-DDISABLE_SV_ASSERTION','-Ivendor/e203/rtl/e203/core','-Ioutput/firmware','-Itests','-Irtl']+sources,env);receipts.append(rec)
  _,rec=verify.run('power_build',[cfg['make'],'-C','tmp/power_sim','-f','Vtb_soc.mk','-j4'],env);receipts.append(rec)
  stamp.write_text(json.dumps(dict(sources=sources_before,executable_sha256=sha(exe),firmware={p.relative_to(case).as_posix():sha(p) for p in (case/'output/firmware').iterdir() if p.is_file()}),indent=2)+'\n')
 args=[exe,'+tasks='+str(tasks),'+profile','+fast_checks','+host_continuous','+vcd']
 text,rec=verify.run('power_capture' if tasks==12 else 'power_smoke',args,env);receipts.append(rec)
 if 'SOC_PASS tasks='+str(tasks)+' ' not in text:raise ValueError('Whole system validation failed')
 windows=parse_windows(text,tasks)
 original=json.loads((case/'verification/reset_tasks.json').read_text())
 for w in windows:
  # Exact clock precision can change boundary phases; never silently replace old cycles.
  w['historical_reference_cycles']=original['task_cycles'][w['task']]
  w['legacy_delta_cycles']=w['legacy_cycles']-w['historical_reference_cycles']
  if abs(w['legacy_delta_cycles'])>2:raise ValueError('Unexpected historical timing change: '+str(w))
 profiles={}
 for task,index,value in re.findall(r'SOC_PROFILE task=(\d+) index=(\d+) value=(\d+)',text):profiles.setdefault(task,{})[index]=int(value)
 from optional_options import read as options
 opt=options(case);r={'flat':1,'tile16':1,'dual32':2,'os4x4':4}[opt['engine']]
 expected_mac=((99+r-1)//r)*(256//({'flat':8,'tile16':8,'dual32':8,'os4x4':4}[opt['engine']]))*(64//(1 if opt['engine']=='os4x4' else 2))
 for i in range(tasks):
  p=profiles[str(i)]
  if p['4']!=expected_mac or p['9']!=11616 or p['10']!=(31680 if opt['packed40'] else 50688):raise ValueError('Profile contract differs')
 if selected_sources(case)!=sources_before or verify.vector_signature()!=vector_hashes:raise ValueError('Capture inputs changed')
 raw=case/'output/soc.vcd'
 result=dict(schema_version=1,passed=True,real_cpu=True,rtl_activity=True,gate_level=False,
     source_sha256=sources_before,source_signature=signature(sources_before),
     config_sha256=config_hashes,config_signature=signature(config_hashes),vector_sha256=vector_hashes,
     task_count=tasks,clock_period_fs=CLOCK_FS,dut_instance='tb_soc/dut',profiles=profiles,
     timing_boundary='Host input/parameter loading start to final DMA write response; reset/readback excluded',
     legacy_timing_boundary='Historical Host-observed completion, recorded separately',
     trace_array_limit=64,trace_note='FIFO and CPU arrays included; behavioral SRAM memory arrays excluded, macro pins traced',
     raw_vcd_sha256=sha(raw),raw_vcd_bytes=raw.stat().st_size,receipts=receipts,tasks=windows,
     executable_sha256=sha(exe),firmware_sha256=sha(case/'output/firmware/kwt.hex'))
 if export:
  from power_vcd import export_windows
  exported=export_windows(raw,windows,out)
  for w,e in zip(windows,exported):w.update(e)
  raw.unlink()  # Only this generated trace, after successful hashed exports.
 result['functional_passed']=True
 result['passed']=bool(export)
 result['stage']='complete' if export else 'awaiting_verified_export'
 receipt.write_text(json.dumps(result,indent=2)+'\n')
 print('POWER_CAPTURE_PASS',case.name,tasks,'strict_fs',sum(w['duration_fs'] for w in windows),flush=True)

def export_capture(case):
 case=Path(case).resolve();receipt=case/'output/activity/capture.json'
 result=json.loads(receipt.read_text());raw=case/'output/soc.vcd'
 if not result.get('functional_passed') or len(result['tasks'])!=12:raise ValueError('Need 12 functional tasks')
 if selected_sources(case)!=result['source_sha256'] or sha(raw)!=result['raw_vcd_sha256']:
  raise ValueError('Capture source/raw VCD changed')
 if any(sha(case/n)!=h for n,h in result['config_sha256'].items()):raise ValueError('Capture config changed')
 from power_vcd import export_windows,build_native_exporter
 cfg=json.loads((ROOT/'environment/local_tools.json').read_text())
 compiler=Path(cfg['make']).with_name('g++.exe' if os.name=='nt' else 'g++')
 native=build_native_exporter(compiler,ROOT/'tmp/power_vcd_native')
 exported=export_windows(raw,result['tasks'],receipt.parent,native_executable=native)
 for w,e in zip(result['tasks'],exported):w.update(e)
 result.update(passed=True,stage='complete',exporter_sha256=sha(ROOT/'tools/power_vcd.py'),
     native_exporter_source_sha256=sha(ROOT/'tools/power_vcd_fast.cpp'),native_exporter_binary_sha256=sha(native))
 receipt.write_text(json.dumps(result,indent=2)+'\n')
 raw.unlink()
 print('POWER_EXPORT_PASS',case.name,len(exported),flush=True)

def launch(name,tasks,skip_build,defer_export=False):
 case=prepare(name)
 logs=STUDY/'logs';logs.mkdir(parents=True,exist_ok=True)
 with (logs/(name+('_smoke' if tasks!=12 else '')+'.log')).open('wb') as out:
  code=subprocess.run([sys.executable,'tools/capture_power.py','--worker','--workdir',str(case),'--tasks',str(tasks)]+(['--skip-build'] if skip_build else [])+(['--defer-export'] if defer_export else []),cwd=case,stdout=out,stderr=subprocess.STDOUT).returncode
 print('POWER_CASE',name,'PASS' if code==0 else 'FAILED',flush=True)
 return code

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--case',choices=CANDIDATES)
 ap.add_argument('--tasks',type=int,default=12);ap.add_argument('--jobs',type=int,default=2)
 ap.add_argument('--skip-build',action='store_true');ap.add_argument('--worker',action='store_true');ap.add_argument('--workdir',type=Path)
 ap.add_argument('--defer-export',action='store_true');ap.add_argument('--export-only',action='store_true')
 a=ap.parse_args()
 if not 1<=a.tasks<=12:raise ValueError('tasks must be 1..12')
 if a.worker:
  capture_worker(a.workdir,a.tasks,a.skip_build,export=a.tasks==12 and not a.defer_export);return
 names=[a.case] if a.case else list(CANDIDATES)
 if a.export_only:
  for n in names:export_capture(STUDY/'cases'/n)
  return
 STUDY.mkdir(exist_ok=True)
 (STUDY/'activity_manifest.json').write_text(json.dumps(dict(schema_version=1,cases=[dict(name=n,path='cases/'+n) for n in CANDIDATES],clock_period_fs=CLOCK_FS,official_vectors=False,description='12 existing layer-weight/synthetic-input tasks; not official post-freeze sample selection'),indent=2)+'\n')
 with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as pool:
  codes=list(pool.map(lambda n:launch(n,a.tasks,a.skip_build,a.defer_export),names))
 if any(codes):raise SystemExit('Capture failed; inspect power_study/logs')

if __name__=='__main__':main()
