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

def main():
    numeric=read_json(ROOT/'output/vectors/numeric-report.json')
    checks=[check('accelerator RTL','tb_accel-run.log','ACCEL_PASS'),
            check('accelerator netlist','tb_accel_netlist-run.log','ACCEL_PASS'),
            check('E203 RTL integration','tb_soc-run.log','SOC_PASS'),
            check('E203 netlist integration','tb_soc_netlist-run.log','SOC_PASS'),
            check('Icarus four-state accelerator','icarus-accel.log','ACCEL_PASS',1)]
    components={}
    for name,marker in [('numeric-tests.log','OK'),('mac-icarus.log','MAC_PASS')]:
        p=OUT/name
        if marker not in p.read_text():raise RuntimeError('Component check missing: '+name)
        components[name]={'passed':True,'sha256':sha(p)}
    for a,b in [(checks[0],checks[1]),(checks[2],checks[3])]:
        if a['tasks']!=b['tasks']:raise RuntimeError('Pre/post synthesis task/cycle mismatch')
    total=sum(t['cycles'] for t in checks[2]['tasks'])
    sources={}
    for dirname in ['rtl','integration','firmware','model','tests','constraints','scripts']:
        for p in sorted((ROOT/dirname).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix in ['.sv','.v','.c','.h','.S','.ld','.json','.py','.sdc']:
                sources[p.relative_to(ROOT).as_posix()]=hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    artifacts={}
    for name in ['kwt_accel_netlist.v','kwt_soc_netlist.v','firmware/kwt.elf','mac.vcd','soc.fst','soc.vcd.gz']:
        p=OUT/name
        if p.exists():artifacts[name]={'bytes':p.stat().st_size,'sha256':sha(p)}
    report={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'scope':'Local undergraduate implementation; official acceptance pending',
            'numeric':{'validation_samples':numeric['sample_count'],'layers':12,'layer_nrmse':numeric['layer_nrmse'],
                       'maximum_layer_nrmse':numeric['maximum_layer_nrmse'],'performance_tasks':numeric['performance_tasks'],
                       'official_600_sample_evaluation':False},
            'checks':checks,'component_tests':components,'performance':{'total_tasks':12,'total_cycles':total,'target_clock_hz':150000000,
                                          'nominal_tasks_per_second':12*150000000/total,'timing_closed':False,
                                          'window':'Host load to shared SRAM through E203 output writeback and completion observation'},
            'ppa':read_json(OUT/'ppa-status.json'),
            'generic_synthesis':{'accelerator':read_json(OUT/'synthesis-stat.json')['design'],
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
    (ROOT/'docs/design-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    (ROOT/'docs/numeric-validation.json').write_text(json.dumps(numeric,indent=2)+'\n')
    print('Saved verified local results; official physical metrics remain unverified.')

if __name__=='__main__':main()
