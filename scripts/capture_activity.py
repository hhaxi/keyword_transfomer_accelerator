"""Optional full-hierarchy SoC VCD capture. May require substantial disk space.

Captures one selected full task interval, including host loading and CPU movement.
Use --tasks 12 for the same local twelve-task sequence. Not an official power result.
"""
import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from run_design import ROOT,RTL,CONFIG,sim
from build_soc import SOC,source_files,firmware

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tasks',type=int,choices=range(1,13),default=1)
    p.add_argument('--netlist',action='store_true')
    p.add_argument('--compressed',action='store_true',help='Capture FST and convert to gzip VCD with GTKWave fst2vcd')
    args=p.parse_args();firmware()
    manifest={'status':'running','tasks':args.tasks,'level':'generic_netlist' if args.netlist else 'rtl',
              'firmware_sha256':hashlib.sha256((ROOT/'output/design/firmware/kwt.elf').read_bytes()).hexdigest(),
              'official_power_result':False,'mapping_coverage_verified':False}
    manifest_path=ROOT/'output/design/activity-manifest.json'
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    includes=['+incdir+output/design/firmware','--trace-fst' if args.compressed else '--trace','--trace-underscore']
    if args.netlist:
        files=[str((SOC/'rtl/e203/general'/f).relative_to(ROOT)).replace('\\','/') for f in ['sirv_gnrl_ram.v','sirv_sim_ram.v']]
        files+=['rtl/kwt_sram16.sv','integration/kwt_shared_sram.sv','output/design/kwt_soc_netlist.v','tests/tb_soc.sv']
    else:
        includes+=['+incdir+'+str((SOC/'rtl/e203/core').relative_to(ROOT)).replace('\\','/')]
        files=source_files()+RTL+['integration/kwt_shared_sram.sv','integration/kwt_system_bus.sv','integration/kwt_soc.sv','tests/tb_soc.sv']
    result=sim('tb_soc',files,includes,label='soc_activity',run_args=['+vcd','+tasks='+str(args.tasks)]+(['+fst'] if args.compressed else []))
    if 'SOC_PASS' not in result:raise RuntimeError('Activity simulation did not pass')
    if args.compressed:
        converter=Path(CONFIG.get('gtkwave_bin',''))/'fst2vcd.exe'
        if not converter.exists():raise RuntimeError('Set gtkwave_bin to a directory containing fst2vcd.exe; FST remains available')
        with gzip.open(ROOT/'output/design/soc.vcd.gz','wb',compresslevel=1) as dest:
            proc=subprocess.Popen([str(converter),str(ROOT/'output/design/soc.fst')],stdout=subprocess.PIPE)
            shutil.copyfileobj(proc.stdout,dest,1024*1024)
            if proc.wait():raise RuntimeError('fst2vcd failed')
    manifest['status']='complete'
    manifest['timing_window_log']=[line for line in result.splitlines() if line.startswith('MEASURE_')]
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')

if __name__=='__main__':main()
