"""Materialize and compare all 16 authorized modes, with four DC hardware groups."""
import argparse,concurrent.futures,csv,hashlib,itertools,json,os,re,shutil,subprocess,sys,uuid,threading
from pathlib import Path
from options import KEYS,configure,inventory,options
from snapshots import capture,freeze_manifest,digest
ROOT=Path(__file__).resolve().parents[1]
STATUS_LOCK=threading.Lock()
SIM_RESULTS=[]
CHECKPOINTS={'00_baseline':'i0_h0_x0_b0','01_itcm':'i1_h0_x0_b0','02_host':'i1_h1_x0_b0',
             '03_small_x':'i1_h1_x1_b0','04_bias':'i1_h1_x1_b1'}

def cases():
    result=[]
    for bits in itertools.product((False,True),repeat=4):
        opts=dict(zip(KEYS,bits));i,h,x,b=map(int,bits)
        result.append(dict(name=f'i{i}_h{h}_x{x}_b{b}',options=opts,hardware_key=f'x{x}_b{b}'))
    return result

def prepare():
    root=ROOT/'experiments/cases';root.mkdir(parents=True,exist_ok=True)
    for item in cases():
        target=root/item['name']
        if target.exists():
            if not (target/'case.json').exists():raise ValueError('Unrecognized existing case '+str(target))
            continue
        capture(ROOT,target,item['name'],include_logs=False)
        configure(target,item['options'])
        (target/'checkpoint.json').write_text(json.dumps(dict(label=item['name'],options=item['options'],
            dc_entry='script/dc_'+item['name']+'.tcl'),indent=2)+'\n')
        # Exact original datapath for the reference hardware group, not just a
        # new implementation with false switches. Bias-only retains original DMA.
        baseline=ROOT/'experiments/baseline'
        if not item['options']['small_x']:
            shutil.copy2(baseline/'rtl/kwt_ffn1_dma.sv',target/'rtl/kwt_ffn1_dma.sv')
            if not item['options']['small_bias']:
                shutil.copy2(baseline/'rtl/kwt_ffn1_core.sv',target/'rtl/kwt_ffn1_core.sv')
                shutil.copy2(baseline/'tech/kwt_sram16.sv',target/'tech/kwt_sram16.sv')
        for name in ('reset_tasks','continuous','components','structure'):
            p=target/f'verification/{name}.json'
            if p.exists():p.unlink()
        (target/'case.json').write_text(json.dumps(item,indent=2)+'\n')
        freeze_manifest(target)
    (ROOT/'experiments/matrix.json').write_text(json.dumps(dict(cases=cases(),checkpoints=CHECKPOINTS,
        axes=list(KEYS),official_platform=False),indent=2)+'\n')
    dc=ROOT/'dc';dc.mkdir(exist_ok=True)
    for name,case in CHECKPOINTS.items():
        (dc/(name+'.tcl')).write_bytes((f'# {name}: {case}\n'+dc_entry(case)).encode('utf-8'))
    for item in cases():
        (dc/(item['name']+'.tcl')).write_bytes(dc_entry(item['name']).encode('utf-8'))
    print('SWEEP_PREPARED 16 cases, 5 checkpoint entries, 4 hardware groups',flush=True)

def dc_entry(case):
    return ('set comparison_root [file normalize [file join [file dirname [info script]] ..]]\n'
            'if {![info exists env(KWT_GLOBAL_LOCAL_CONFIG)]} {\n'
            '    set env(KWT_GLOBAL_LOCAL_CONFIG) [file join $comparison_root config local_config.tcl]\n}\n'
            f'source [file join $comparison_root experiments cases {case} script run_all.tcl]\n')

def report_metrics(folder):
    folder=Path(folder)
    def read(name):
        p=folder/name
        return p.read_text(errors='replace') if p.exists() else ''
    def number(pattern,text):
        m=re.search(pattern,text,re.I)
        return float(m.group(1)) if m else None
    area=number(r'Total cell area:\s*([\d.eE+-]+)',read('area.rpt'))
    slack=number(r'slack\s*\([^)]*\)\s*([\d.eE+-]+)',read('timing_setup.rpt'))
    power=read('power_vectorless_NOT_OFFICIAL.rpt')
    def watts(label):
        m=re.search(label+r'\s*=\s*([\d.eE+-]+)\s*([munp]?W)\b',power,re.I)
        return float(m.group(1))*{'W':1,'mW':1e-3,'uW':1e-6,'nW':1e-9,'pW':1e-12}.get(m.group(2),1) if m else None
    return dict(cell_area=area,setup_slack=slack,dynamic_power_w=watts('Total Dynamic Power'),
                leakage_power_w=watts('Cell Leakage Power'),power_method='vectorless_NOT_OFFICIAL',report=str(folder))

def command(case,label,args):
    logs=case/'output/sweep';logs.mkdir(parents=True,exist_ok=True)
    with (logs/(label+'.log')).open('wb') as f:
        code=subprocess.run([sys.executable]+args,cwd=case,stdout=f,stderr=subprocess.STDOUT).returncode
    if code:raise RuntimeError(f'{case.name}: {label} failed; {logs/(label+".log")}')

def build_ready(case):
    exe=case/'tmp/sim'/('Vtb_soc.exe' if os.name=='nt' else 'Vtb_soc')
    manifest=case/'output/build.json'
    if not manifest.exists() or not exe.exists():return False
    saved=json.loads(manifest.read_text())
    return digest(exe)==saved['executable_sha256'] and all((case/p).is_file() and digest(case/p)==h
        for p,h in {**saved['sources'],**saved['firmware']}.items())

def reuse_build(source,target):
    # Every source/header signature is checked again by verify --skip-build.
    if not build_ready(source):return False
    saved=json.loads((source/'output/build.json').read_text())
    if not all((target/name).is_file() and digest(target/name)==value for name,value in saved['sources'].items()):
        return False
    (target/'output/firmware').mkdir(parents=True,exist_ok=True)
    for p in (source/'output/firmware').iterdir():shutil.copy2(p,target/'output/firmware'/p.name)
    (target/'tmp/sim').mkdir(parents=True,exist_ok=True)
    exe='Vtb_soc.exe' if os.name=='nt' else 'Vtb_soc'
    shutil.copy2(source/'tmp/sim'/exe,target/'tmp/sim'/exe)
    saved['reused_from']=source.name
    (target/'output/build.json').write_text(json.dumps(saved,indent=2)+'\n')
    return True

def run_sim_group(group,tasks,continuous,resume):
    prior=None;results=[]
    for item in group:
        case=ROOT/'experiments/cases'/item['name']
        try:
            done=case/'verification/continuous.json'
            reset=case/'verification/reset_tasks.json'
            cached=resume and reset.exists() and (not continuous or done.exists())
            if cached:
                for path in (reset,done) if continuous else (reset,):
                    record=json.loads(path.read_text())
                    cached=cached and len(record.get('vector_sha256',{}))==72 and record['passed'] and record['tasks']==tasks and record['options']==item['options'] and all(
                        (case/p).is_file() and digest(case/p)==h for p,h in {**record['sources'],**record.get('harness',{}),**record['vector_sha256']}.items())
            if not cached:
                for path in (reset,done):
                    if path.exists():path.unlink()
                reused=build_ready(case) or (prior is not None and reuse_build(prior,case))
                command(case,'verify',['tools/verify.py','--tasks',str(tasks)]+(['--skip-build'] if reused else []))
                if continuous:command(case,'continuous',['tools/verify.py','--tasks',str(tasks),'--continuous','--skip-build'])
            prior=case
            results.append(dict(case=item['name'],passed=True))
            print('SWEEP_SIM_PASS',item['name'],flush=True)
        except Exception as error:
            results.append(dict(case=item['name'],passed=False,error=str(error)))
            print('SWEEP_SIM_FAILED',item['name'],error,flush=True)
        with STATUS_LOCK:
            SIM_RESULTS.append(results[-1])
            out=ROOT/'experiments/results';out.mkdir(exist_ok=True)
            (out/'simulation_status.json').write_text(json.dumps(SIM_RESULTS,indent=2)+'\n')
    return results

def sim(tasks,jobs,continuous,resume):
    global SIM_RESULTS
    SIM_RESULTS=[]
    groups={}
    for item in cases():
        opts=item['options'];key=(opts['itcm'],opts['small_x'],opts['small_bias'])
        groups.setdefault(key,[]).append(item)
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        pending=[pool.submit(run_sim_group,g,tasks,continuous,resume) for g in groups.values()]
        for f in concurrent.futures.as_completed(pending):results+=f.result()
    out=ROOT/'experiments/results';out.mkdir(exist_ok=True)
    (out/'simulation_status.json').write_text(json.dumps(results,indent=2)+'\n')
    collect()
    if not all(r['passed'] for r in results):raise RuntimeError('Some simulations failed; inspect simulation_status.json')

def hardware_digest(case,scope):
    inputs=(case/f'filelists/{scope}.f').read_text().splitlines()
    inputs += [f'filelists/{scope}.f','script/set_constraint.tcl','script/compile.tcl','config/library_config.tcl',
               'script/read_file.tcl','script/set_env.tcl','script/common.tcl','script/run_all.tcl','script/write_file.tcl','script/area_scope.tcl']
    inputs += [p.relative_to(case).as_posix() for p in (case/'vendor/e203/rtl/e203/core').glob('*.v')]
    data={p:digest(case/p) for p in inputs}
    header=(case/'rtl/kwt_options.vh').read_text()
    data['hardware_header']='\n'.join(line for line in header.splitlines() if not line.startswith('`define KWT_ITCM '))
    opts=options(case);data['small_x']=opts['small_x'];data['small_bias']=opts['small_bias']
    for role,p in (('case_local',case/'config/local_config.tcl'),('global_local',ROOT/'config/local_config.tcl')):
        if p.exists():data[role]=digest(p)
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()

def dc_run(scopes,repeat):
    out=ROOT/'experiments/results';out.mkdir(exist_ok=True)
    cache={};results=[];env=os.environ.copy()
    env['KWT_GLOBAL_LOCAL_CONFIG']=str(ROOT/'config/local_config.tcl')
    for scope in scopes:
        for item in cases():
            case=ROOT/'experiments/cases'/item['name'];key=(scope,hardware_digest(case,scope))
            record=dict(case=item['name'],scope=scope,hardware_key=item['hardware_key'],hardware_sha256=key[1])
            if not repeat and key in cache:
                record.update(cache[key]);record['reused']=True
                results.append(record)
                (out/'dc_status.json').write_text(json.dumps(results,indent=2)+'\n')
                print('SWEEP_DC_REUSE',item['name'],scope,flush=True);continue
            env['KWT_SYNTHESIS_SCOPE']=scope
            launch=out/f'dc_{scope}_{item["name"]}_{uuid.uuid4().hex}.log'
            with launch.open('wb') as f:
                code=subprocess.run(['bash','run_dc.sh','--'+scope],cwd=case,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
            text=launch.read_text(errors='replace')
            found=re.findall(r'KWT_DC_COMPLETED:\s*(.+)',text)
            record.update(passed=code==0 and bool(found),reused=False,launch_log=str(launch.relative_to(ROOT)))
            if record['passed']:
                report=Path(found[-1].strip())/'report'
                record.update(report_metrics(report));record['report_relative']=report.relative_to(ROOT).as_posix()
                cache[key]={k:v for k,v in record.items() if k not in ('case','scope','hardware_key')}
            results.append(record)
            (out/'dc_status.json').write_text(json.dumps(results,indent=2)+'\n')
            print('SWEEP_DC_'+('PASS' if record['passed'] else 'FAILED'),item['name'],scope,flush=True)
    collect()
    if not all(r['passed'] for r in results):raise RuntimeError('Some DC runs failed; all remaining cases were attempted')

def valid_simulation(case,label):
    p=case/f'verification/{label}.json'
    if not p.exists():return None
    r=json.loads(p.read_text())
    if not r.get('passed') or len(r.get('vector_sha256',{}))!=72 or r.get('options')!=options(case):return None
    if not all((case/p).is_file() and digest(case/p)==h for p,h in
               {**r.get('sources',{}),**r.get('harness',{}),**r['vector_sha256']}.items()):return None
    return r

def collect():
    out=ROOT/'experiments/results';out.mkdir(parents=True,exist_ok=True)
    dcfile=out/'dc_status.json';dc=json.loads(dcfile.read_text()) if dcfile.exists() else []
    statusfile=out/'simulation_status.json'
    status={r['case']:r for r in json.loads(statusfile.read_text())} if statusfile.exists() else {}
    rows=[]
    for item in cases():
        case=ROOT/'experiments/cases'/item['name']
        row=dict(case=item['name'],**item['options'],hardware_key=item['hardware_key'],
                 checkpoint=next((k for k,v in CHECKPOINTS.items() if v==item['name']),''))
        inv=inventory(item['options']);row['accelerator_sram_bytes']=sum(int(k[5:-3])*2*v for k,v in inv.items())
        for label in ('reset_tasks','continuous'):
            r=valid_simulation(case,label)
            if item['name'] in status and not status[item['name']]['passed']:r=None
            row[label+'_passed']=r is not None
            if r is not None:
                row[label+'_tasks']=r['tasks'];row[label+'_cycles']=sum(r['task_cycles'])/r['tasks']
                if label=='reset_tasks':
                    row['boot_wait_cycles']=r.get('bootstrap_cycles',[None])[0]
                    row['host_load_and_notification_cycles']=r.get('host_load_and_notification_cycles',[None])[0]
                    if r.get('bus_counts'):
                        row.update({k:v for k,v in r['bus_counts'][0].items() if k!='task'})
                    row['nominal_tasks_per_second_at_150MHz']=r['throughput_at_150MHz']
                    profile=r.get('profiles',{}).get('0',{})
                    for name,index in [('dma_total',0),('dma_load',1),('compute_writeback',2),('mac_active',4),('fifo_full_wait',5),('request_wait',7)]:
                        row[name]=profile.get(str(index))
        for d in dc:
            if d['case']==item['name']:
                if d.get('hardware_sha256')!=hardware_digest(case,d['scope']):
                    row['dc_'+d['scope']+'_passed']=False
                    row['dc_'+d['scope']+'_stale']=True
                    row['dc_'+d['scope']+'_report_relative']=d.get('report_relative')
                    continue
                for k in ('passed','cell_area','setup_slack','dynamic_power_w','leakage_power_w','power_method','report_relative','reused'):
                    row['dc_'+d['scope']+'_'+k]=d.get(k)
        rows.append(row)
    (out/'comparison.json').write_text(json.dumps(rows,indent=2)+'\n')
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with (out/'comparison.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fields);w.writeheader();w.writerows(rows)
    print('SWEEP_COMPARISON',out/'comparison.csv',flush=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=('prepare','list','sim','dc','collect'))
    ap.add_argument('--tasks',type=int,default=12);ap.add_argument('--jobs',type=int,default=2)
    ap.add_argument('--no-continuous',action='store_true');ap.add_argument('--resume',action='store_true')
    ap.add_argument('--scope',choices=('soc','accelerator','both'),default='soc');ap.add_argument('--repeat-identical-hardware',action='store_true')
    a=ap.parse_args()
    if a.action=='list':print(json.dumps(cases(),indent=2));return
    if a.action=='prepare':prepare();return
    if a.action=='collect':collect();return
    if not (ROOT/'experiments/matrix.json').exists():prepare()
    if a.action=='sim':
        if not 1<=a.tasks<=12 or a.jobs<1:raise ValueError('Invalid tasks/jobs')
        sim(a.tasks,a.jobs,not a.no_continuous,a.resume)
    else:dc_run(('soc','accelerator') if a.scope=='both' else (a.scope,),a.repeat_identical_hardware)
if __name__=='__main__':main()
