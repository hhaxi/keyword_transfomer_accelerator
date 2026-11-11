"""Materialize isolated frontend candidates; never mutate the original finalists."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT.parent / 'finalists'
BASE = 'dual32_f0_p0_o1_w1_b1_d1_h0'
CASES = [
    dict(name='ref32_packed_pause', queue=False, engine='dual32', fuse=False, wait=1, pipe=False, parent=None),
    dict(name='q32_pause', queue=True, engine='dual32', fuse=False, wait=1, pipe=False, parent='ref32_packed_pause'),
    dict(name='q32_fused_pause', queue=True, engine='dual32', fuse=True, wait=1, pipe=False, parent='q32_pause'),
    dict(name='q32_fused_wfi', queue=True, engine='dual32', fuse=True, wait=2, pipe=False, parent='q32_fused_pause'),
    dict(name='q64_fused_pause', queue=True, engine='quad64', fuse=True, wait=1, pipe=False, parent='q32_fused_pause'),
    dict(name='q64_fused_wfi', queue=True, engine='quad64', fuse=True, wait=2, pipe=False, parent='q64_fused_pause'),
    dict(name='q64_pipe_pause', queue=True, engine='quad64', fuse=True, wait=1, pipe=True, parent='q64_fused_pause'),
]

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode('utf-8'))

def save(path, value):
    write(path, json.dumps(value, indent=2, ensure_ascii=False)+'\n')

def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Source template changed: '+old)
    return text.replace(old, new)

def precise_measurement(case):
    """Integer-fs clock avoids Verilator 5.020's realtime-to-integer truncation."""
    path=case/'tests/tb_soc_power.sv'
    text=path.read_text()
    if 'module kwt_measure_fs;' not in text:
        text=replace_once(text,'module tb_soc;', 'module tb_soc;\n    kwt_measure_fs measurement_clock();')
        if text.count('$realtime*1000000.0')!=2:raise ValueError('Unexpected time markers')
        text=text.replace('$realtime*1000000.0','measurement_clock.now_fs()')
        text=text.replace('time_fs=%0.0f','time_fs=%0d')
        text+='\nmodule kwt_measure_fs;\n timeunit 1fs;\n timeprecision 1fs;\n function automatic time now_fs();\n  now_fs=$time;\n endfunction\nendmodule\n'
        write(path,text)
    spec=importlib.util.spec_from_file_location('server_vcs',ROOT/'study/tools/vcs_power.py')
    import sys
    sys.path.insert(0,str(ROOT/'study/tools'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    write(case/'tests/tb_soc_vcs_power.sv',module.make_overlay(text))

def prepare():
    study = ROOT/'study'
    study.mkdir(exist_ok=True)
    # Private copy of proven server drivers. Only engine geometry is extended.
    shutil.copytree(ORIGINAL/'tools', study/'tools', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ORIGINAL/'script', study/'script', dirs_exist_ok=True)
    optfile=study/'tools/optional_options.py'
    text=replace_once(optfile.read_text(), "'dual32':(2,8,2)", "'dual32':(2,8,2),'quad64':(4,8,2)")
    write(optfile,text)
    spec=importlib.util.spec_from_file_location('candidate_options',optfile)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source=ORIGINAL/'vcs_power_study/cases'/BASE
    source_files={p.relative_to(source).as_posix():sha(p) for p in source.rglob('*') if p.is_file()}
    entries=[]
    for design in CASES:
        case=study/'cases'/design['name']
        if case.exists():
            raise ValueError('Refusing to overwrite existing experiment: '+str(case))
        case.mkdir(parents=True)
        for folder in ('rtl','tech','vendor','firmware','filelists','config','script','tests','vectors'):
            shutil.copytree(source/folder,case/folder,
                            ignore=shutil.ignore_patterns('__pycache__','*.pyc','local_config.tcl'))
        shutil.copytree(source/'output/firmware',case/'output/firmware')
        precise_measurement(case)
        if design['queue']:
            shutil.copyfile(ROOT/'rtl/kwt_output_formatter.sv',case/'rtl/kwt_output_formatter.sv')
        if design['engine']=='quad64':
            core=case/'rtl/kwt_tile_core.sv'
            text=replace_once(core.read_text(),
                '(ROWS==2 && COLS==8 && KPAR==2) ||',
                '(ROWS==2 && COLS==8 && KPAR==2) ||\n               (ROWS==4 && COLS==8 && KPAR==2) ||')
            write(core,text)
        options=json.loads((source/'config/optional.json').read_text())
        options.update(engine=design['engine'],fuse=design['fuse'],
                       wait_mode=design['wait'],product_pipe=design['pipe'])
        # Baseline retains original configuration bytes and firmware exactly.
        if design['name']!='ref32_packed_pause':module.configure(case,options)
        save(case/'case.json',dict(name=design['name'],optional=options,small_bias=True,
            frontend=design,source_reference=BASE))
        entries.append(dict(name=design['name'],path='cases/'+design['name']))
    save(study/'activity_manifest.json',dict(schema_version=1,cases=entries,
         clock_period_fs=6666667,official_vectors=False,
         description='Frontend variants: identical 12 layer weights/synthetic X; no local PPA'))
    save(ROOT/'reports/source_reference.json',dict(original_case=BASE,source_sha256=source_files))
    save(ROOT/'reports/designs.json',CASES)
    print('PREPARED',len(entries),'isolated candidates',flush=True)

if __name__=='__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    prepare()
