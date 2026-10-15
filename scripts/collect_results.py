"""Collect observed pass markers, cycles, provenance and explicit PPA limitations."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/design'

def read_json(path):return json.loads(path.read_text())
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def check(name,filename,marker,count=12):
    path=OUT/filename;text=path.read_text()
    if marker not in text:raise RuntimeError('Missing '+marker+' in '+filename)
    tasks=[{'task':int(a),'cycles':int(b),'outputs':int(c)} for a,b,c in
           re.findall(r'(?:ACCEL|SOC)_TASK_PASS task=(\d+) cycles=(\d+) outputs=(\d+)',text)]
    if len(tasks)!=count or [t['task'] for t in tasks]!=list(range(count)):
        raise RuntimeError('Missing task results: '+filename)
    return dict(name=name,passed=True,tasks=tasks,log=path.relative_to(ROOT).as_posix(),log_sha256=sha(path))

PROFILE_NAMES=['dma_total','load','compute_writeback','control','mac_active','fifo_full_wait',
               'core_elapsed','dma_request_wait','dma_response_wait','dma_read_commands',
               'dma_write_commands','first_output','last_output','last_write_ack','producer_wait']

def profiles(filename):
    text=(OUT/filename).read_text()
    rows={}
    for t,i,v in re.findall(r'SOC_PROFILE task=(\d+) index=(\d+) value=(\d+)',text):
        row=rows.setdefault(int(t),{})
        if int(i) in row:raise RuntimeError('Duplicate profile counter')
        row[int(i)]=int(v)
    if sorted(rows)!=list(range(12)):raise RuntimeError('Incomplete cycle profiles')
    result=[]
    starts={int(t):int(c) for t,c in re.findall(r'MEASURE_BEGIN task=(\d+) time_ps=\d+ cycle=(\d+)',text)}
    loaded={int(t):int(c) for t,c in re.findall(r'SOC_TASK_START task=(\d+) pc=[0-9a-f]+ cycle=(\d+)',text)}
    totals={int(t):int(c) for t,c in re.findall(r'SOC_TASK_PASS task=(\d+) cycles=(\d+)',text)}
    for t,row in sorted(rows.items()):
        if sorted(row)!=list(range(15)):raise RuntimeError('Incomplete counters for task '+str(t))
        values=dict(zip(PROFILE_NAMES,[row[i] for i in range(15)]))
        if row[0]!=sum(row[i] for i in [1,2,3]) or row[4]!=202752 or row[9]!=11616 or row[10]!=50688:
            raise RuntimeError('Counter conservation/operation count failed')
        if not (row[1]<row[11]<=row[12]<row[13]==row[0]):raise RuntimeError('Invalid completion timing')
        values['host_load_and_ready_notification']=loaded[t]-starts[t]
        values['cpu_setup_and_completion_observation']=totals[t]-values['host_load_and_ready_notification']-row[0]
        if values['cpu_setup_and_completion_observation']<0:raise RuntimeError('Inconsistent timing window')
        result.append(dict(task=t,cycles=values))
    return result

def main():
    numeric=read_json(ROOT/'output/vectors/numeric-report.json')
    checks=[check('accelerator RTL','tb_accel-run.log','ACCEL_PASS'),
            check('accelerator netlist','tb_accel_netlist-run.log','ACCEL_PASS'),
            check('E203 RTL integration','tb_soc-run.log','SOC_PASS'),
            check('E203 netlist integration','tb_soc_netlist-run.log','SOC_PASS'),
            check('Icarus four-state accelerator','icarus-accel.log','ACCEL_PASS',1)]
    components={}
    for name,marker in [('numeric-tests.log','OK'),('packing-tests.log','OK'),('mac-icarus.log','MAC_PASS'),
                        ('tb_dma-run.log','DMA_PASS'),('tb_dma_netlist-run.log','DMA_PASS'),
                        ('tb_bus-run.log','BUS_PASS'),('tb_bus_netlist-run.log','BUS_PASS'),
                        ('icarus-tb_dma.log','DMA_PASS'),('icarus-tb_bus.log','BUS_PASS')]:
        p=OUT/name
        if marker not in p.read_text():raise RuntimeError('Component check missing: '+name)
        components[name]={'passed':True,'sha256':sha(p)}
    for a,b in [(checks[0],checks[1]),(checks[2],checks[3])]:
        if a['tasks']!=b['tasks']:raise RuntimeError('Pre/post synthesis task/cycle mismatch')
    dma_profiles=[]
    for name in ['tb_dma-run.log','tb_dma_netlist-run.log','icarus-tb_dma.log']:
        values=re.findall(r'DMA_PROFILE index=(\d+) value=(\d+)',(OUT/name).read_text())
        if len(values)!=15:raise RuntimeError('Incomplete DMA stress profile: '+name)
        dma_profiles.append(values)
    if not all(p==dma_profiles[0] for p in dma_profiles):raise RuntimeError('DMA stress profile differs between simulators/netlist')
    for name in ['tb_bus-run.log','tb_bus_netlist-run.log','icarus-tb_bus.log']:
        if 'BUS_THROUGHPUT_PASS requests=128 cycles=129 consecutive_accepts=128' not in (OUT/name).read_text():
            raise RuntimeError('Bus throughput regression: '+name)
    total=sum(t['cycles'] for t in checks[2]['tasks'])
    sources={}
    for dirname in ['rtl','integration','firmware','model','tests','constraints','scripts']:
        for p in sorted((ROOT/dirname).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix in ['.sv','.v','.c','.h','.S','.ld','.json','.py','.sdc']:
                sources[p.relative_to(ROOT).as_posix()]=hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    artifacts={}
    for name in ['kwt_accel_netlist.v','kwt_dma_netlist.v','kwt_bus_netlist.v','kwt_soc_netlist.v',
                 'firmware/kwt.elf','mac.vcd','soc.fst','soc.vcd.gz']:
        p=OUT/name
        if p.exists():artifacts[name]={'bytes':p.stat().st_size,'sha256':sha(p)}
    report={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'scope':'Local undergraduate implementation; official acceptance pending',
            'numeric':{'validation_samples':numeric['sample_count'],'layers':12,'layer_nrmse':numeric['layer_nrmse'],
                       'maximum_layer_nrmse':numeric['maximum_layer_nrmse'],'performance_tasks':numeric['performance_tasks'],
                       'official_600_sample_evaluation':False},
            'checks':checks,'component_tests':components,'performance':{'total_tasks':12,'total_cycles':total,'target_clock_hz':150000000,
                                          'nominal_tasks_per_second':12*150000000/total,'timing_closed':False,
                                          'window':'Host load to shared SRAM through DMA output writeback, E203 completion notification and host observation'},
            'ppa':read_json(OUT/'ppa-status.json'),
            'generic_synthesis':{'accelerator':read_json(OUT/'synthesis-stat.json')['design'],
                                 'dma_engine':read_json(OUT/'dma-synthesis-stat.json')['design'],
                                 'bus':read_json(OUT/'bus-synthesis-stat.json')['design'],
                                 'soc':read_json(OUT/'soc-synthesis-stat.json')['design']},
            'activity':{'full_soc_tasks_captured':0,
                        'official_mapping_coverage_checked':False,'sram_power_model_available':False,
                        'note':'Local activity only; not a twelve-task official power or energy result'},
            'source_hash_convention':'text bytes with CRLF normalized to LF',
            'source_sha256':sources,'artifacts':artifacts}
    calibration=ROOT/'output/calibration/numeric-report.json'
    if calibration.exists():
        report['calibration']=read_json(calibration)
    activity=OUT/'activity-manifest.json'
    if activity.exists():
        metadata=read_json(activity)
        if metadata['status']!='complete':raise RuntimeError('Activity recording incomplete')
        if metadata['firmware_sha256']!=sha(OUT/'firmware/kwt.elf'):raise RuntimeError('Activity used a different firmware build')
        report['activity']['full_soc_tasks_captured']=metadata['tasks']
        report['activity']['capture']=metadata
    cycle_profiles=profiles('tb_soc-run.log')
    if cycle_profiles!=profiles('tb_soc_netlist-run.log'):raise RuntimeError('Pre/post synthesis profile mismatch')
    report['cycle_analysis']={'tasks':cycle_profiles,
        'additive_phases':['host_load_and_ready_notification','load','compute_writeback','control','cpu_setup_and_completion_observation'],
        'note':'Other counters are overlapping activity/wait diagnostics; do not add them to the phase total. All timestamps are relative to DMA start. Profiles are read after the measured interval.'}
    report['ppa']['area_scope']='DMA engine including compute core/internal SRAM plus added bus/interface logic; never core-only'
    report['ppa']['synthesis']='Generic compute-core, DMA-engine, bus and E203 netlists; SRAM leaves preserved'
    report['ppa']['post_synthesis_simulation']='12 full compute-core and E203 tasks; DMA fault/recovery and bus throughput regressions passed'
    (OUT/'ppa-status.json').write_text(json.dumps(report['ppa'],indent=2)+'\n')
    from collect_ffn import collect as collect_ffn
    report['optional_ffn']=collect_ffn()
    # Compare the same workload; bus/DMA changes are the optimization under test.
    from compare_performance import compare
    comparison=compare(report)
    report['performance']['baseline_speedup']=comparison['soc_speedup']
    report['performance']['baseline_version']='v4'
    report['performance']['first_version_speedup']=comparison['speedup_over_first_version']
    (ROOT/'docs/cycle-analysis.json').write_text(json.dumps(report['cycle_analysis'],indent=2)+'\n')
    (ROOT/'docs/performance-comparison.json').write_text(json.dumps(comparison,indent=2)+'\n')
    (ROOT/'docs/design-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    (ROOT/'docs/numeric-validation.json').write_text(json.dumps(numeric,indent=2)+'\n')
    print('Saved verified local results; official physical metrics remain unverified.')

if __name__=='__main__':main()
