"""Reproducible design checks. Run with Python 3.8+ from any working directory."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/design'
CONFIG=json.loads((ROOT/'environment/local-tools.json').read_text(encoding='utf-8-sig')) if (ROOT/'environment/local-tools.json').exists() else {}
RTL=['rtl/kwt_mac40.sv','rtl/kwt_sram16.sv','rtl/kwt_accel.sv']
SYSTEM_RTL=RTL+['rtl/kwt_dma.sv','integration/kwt_bus_fabric.sv']

def run(name,cmd,timeout=900):
    OUT.mkdir(parents=True,exist_ok=True)
    print('Running '+name,flush=True)
    log=OUT/(name+'.log')
    with log.open('wb') as stream:
        result=subprocess.run([str(x) for x in cmd],cwd=str(ROOT),stdout=stream,stderr=subprocess.STDOUT,timeout=timeout)
    text=log.read_text(encoding='utf-8',errors='replace')
    if result.returncode:
        print(text[-12000:]); raise RuntimeError(name+' failed')
    print(text[-2000:],flush=True)
    return text

def linux(name,command,timeout=900):
    wd='/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:]
    return run(name,['wsl.exe','-d',CONFIG.get('wsl_distro','Ubuntu'),'--','bash','--noprofile','--norc','-c',
                     'cd '+shlex.quote(wd)+' && '+command],timeout)

def sim(top,files,extra=None,label=None,run_args=None):
    label=label or top
    command=[CONFIG.get('wsl_verilator','verilator'),'--binary','--timing','--build-jobs','4','-Wno-fatal',
             '--top-module',top,'--Mdir','output/design/build_'+label]+(extra or [])+files
    linux(label+'-build',' '.join(shlex.quote(s) for s in command))
    return linux(label+'-run','output/design/build_'+label+'/V'+top+' '+ ' '.join(shlex.quote(s) for s in (run_args or [])),1800)

def four_state():
    directory=CONFIG.get('iverilog_bin')
    compiler=Path(directory)/'iverilog.exe' if directory else 'iverilog'
    runtime=Path(directory)/'vvp.exe' if directory else 'vvp'
    run('icarus-mac-build',[compiler,'-g2012','-s','tb_mac','-o',OUT/'mac.vvp','rtl/kwt_mac40.sv','tests/tb_mac.sv'])
    if 'MAC_PASS' not in run('mac-icarus',[runtime,OUT/'mac.vvp','+vcd']):raise RuntimeError('MAC test incomplete')
    run('icarus-accel-build',[compiler,'-g2012','-s','tb_accel','-o',OUT/'accel.vvp']+RTL+['tests/tb_accel.sv'])
    if 'ACCEL_PASS' not in run('icarus-accel',[runtime,OUT/'accel.vvp','+tasks=1']):raise RuntimeError('Accelerator test incomplete')
    for top,files,marker in [
        ('tb_dma',RTL+['rtl/kwt_dma.sv','tests/tb_dma.sv'],'DMA_PASS'),
        ('tb_bus',['integration/kwt_bus_fabric.sv','integration/kwt_shared_sram.sv','tests/tb_bus.sv'],'BUS_PASS')]:
        run('icarus-'+top+'-build',[compiler,'-g2012','-s',top,'-o',OUT/(top+'.vvp')]+files)
        if marker not in run('icarus-'+top,[runtime,OUT/(top+'.vvp')]):raise RuntimeError(top+' four-state check failed')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('task',choices=['numeric','mac','fourstate','accel','dma','bus','soc','synth','synth-dma','synth-soc','all'])
    task=p.parse_args().task
    if task in ('numeric','all'):
        run('numeric-tests',[sys.executable,'tests/test_numeric.py'])
        run('packing-tests',[sys.executable,'tests/test_packing.py'])
    if task in ('mac','all'):
        text=sim('tb_mac',['rtl/kwt_mac40.sv','tests/tb_mac.sv'])
        assert 'MAC_PASS' in text
    if task in ('fourstate','all'):
        four_state()
    if task in ('accel','all'):
        text=sim('tb_accel',RTL+['tests/tb_accel.sv'])
        assert 'ACCEL_PASS' in text
    if task in ('dma','all'):
        text=sim('tb_dma',RTL+['rtl/kwt_dma.sv','tests/tb_dma.sv'])
        assert 'DMA_PASS' in text
    if task in ('bus','all'):
        text=sim('tb_bus',['integration/kwt_bus_fabric.sv','integration/kwt_shared_sram.sv','tests/tb_bus.sv'])
        assert 'BUS_PASS' in text
    if task in ('soc','all'):
        from build_soc import build_and_simulate
        build_and_simulate()
    if task in ('synth','all'):
        from synth_design import synthesize
        synthesize()
    if task in ('synth-soc','all'):
        from synth_soc import main as synth_soc
        synth_soc()
    if task in ('synth-dma','all'):
        from synth_dma import main as synth_dma
        synth_dma()

if __name__=='__main__': main()
