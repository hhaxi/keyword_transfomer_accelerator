"""Compile RTL and validate the real E203 SoC; no commercial tools required."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'study/tools'))
import vcs_power
from optional_options import read as read_options, inventory, ENGINES

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes((json.dumps(value,indent=2)+'\n').encode())

def files(case):
    result={}
    for folder in ('rtl','tech','vendor','firmware','filelists','config','script','tests','vectors','output/firmware'):
        for p in sorted((case/folder).rglob('*')):
            if p.is_file() and p.suffix not in ('.elf','.bin') and '__pycache__' not in p.parts:
                result[p.relative_to(case).as_posix()]=sha(p)
    result['case.json']=sha(case/'case.json')
    return result

def run(case,command,log,env=None):
    log.parent.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    with log.open('wb') as stream:
        result=subprocess.run(list(map(str,command)),cwd=case,env=env,stdout=stream,stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(str(log)+'\n'+log.read_text(errors='replace')[-3500:])
    return dict(command=list(map(str,command)),log=log.relative_to(ROOT).as_posix(),
                log_sha256=sha(log),seconds=time.monotonic()-started)

def firmware(case,gcc):
    options=read_options(case)
    if options['wait_mode']==1:return dict(mode='original qualified pause64 image; unchanged')
    gcc=Path(gcc).resolve()
    toolbin=gcc.parent
    env=os.environ.copy();env['PATH']=str(toolbin)+os.pathsep+env['PATH']
    args=[gcc,'-march=rv32imac_zicsr_zifencei','-mabi=ilp32','-O2','-ffreestanding','-fno-builtin',
          '-nostdlib','-nostartfiles','-Wl,--no-relax','-DFFN1_USE_ITCM=1',
          '-DFFN1_WAIT_MODE=2','-DFFN1_PACKED40=1','-DFFN1_POLL_PAUSE=64',
          '-T','firmware/link_itcm.ld','firmware/start.S','firmware/main.c',
          'firmware/kwt_driver.c','firmware/kwt_irq.c','-o','output/firmware/kwt.elf']
    receipt=run(case,args,ROOT/'reports/logs'/case.name/'firmware.log',env)
    run(case,[toolbin/'riscv64-unknown-elf-objcopy','-O','binary','output/firmware/kwt.elf','output/firmware/kwt.bin'],
        ROOT/'reports/logs'/case.name/'objcopy.log',env)
    binary=(case/'output/firmware/kwt.bin').read_bytes();binary+=b'\0'*((-len(binary))%4)
    (case/'output/firmware/kwt.hex').write_bytes(''.join('%08x\n'%int.from_bytes(binary[i:i+4],'little') for i in range(0,len(binary),4)).encode())
    (case/'output/firmware/size.vh').write_bytes(('`define FW_WORDS %d\n'%(len(binary)//4)).encode())
    receipt['compiler']=subprocess.check_output([gcc,'--version'],text=True).splitlines()[0]
    return receipt

def simulate(name,args):
    case=ROOT/'study/cases'/name
    logs=ROOT/'reports/logs'/name
    receipt_path=ROOT/'reports'/('qualification_'+name+'.json')
    old=json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    save(receipt_path,dict(passed=False,stage='running'))
    opt=read_options(case)
    exe=case/'tmp/sim/Vtb_soc'
    exe.parent.mkdir(parents=True,exist_ok=True)
    if args.skip_build:
        if not old or old.get('inputs')!=files(case) or old.get('executable_sha256')!=sha(exe):
            raise ValueError('Stale or missing simulation: '+name)
        fw_receipt=old['firmware'];build=old['build']
    else:
        fw_receipt=firmware(case,args.gcc)
        sources=(case/'filelists/soc.f').read_text().splitlines()+['tests/macro_fixtures.sv','tests/tb_soc_power.sv']
        command=[args.verilator,'--binary','--timing','-j',str(args.build_jobs),'-Wno-fatal',
                 '--top-module','tb_soc','--Mdir','tmp/sim','-DDISABLE_SV_ASSERTION',
                 '-Ivendor/e203/rtl/e203/core','-Ioutput/firmware','-Itests','-Irtl']+sources
        print('BUILD',name,flush=True)
        build=run(case,command,logs/'build.log')
    before=files(case)
    modes={}
    for continuous in (False,True):
        mode='continuous' if continuous else 'reset'
        command=[exe,'+tasks='+str(args.tasks),'+profile','+fast_checks','+host_continuous']
        if continuous:command+=['+continuous']
        runtime=run(case,command,logs/(mode+'.log'))
        text=(logs/(mode+'.log')).read_text()
        windows,profiles=vcs_power.validate_simulation(text,opt,args.tasks)
        for w in windows:
            expected_fs=(w['end_cycle']-w['begin_cycle'])*6666667+3333333
            if w['duration_fs']!=expected_fs:
                raise ValueError('Timestamp precision/clock phase mismatch: '+str(w))
        modes[mode]=dict(passed=True,windows=windows,profiles=profiles,receipt=runtime,
                        mean_cycles=sum(w['cycles'] for w in windows)/len(windows))
        print('PASS',name,mode,args.tasks,'cycles',modes[mode]['mean_cycles'],flush=True)
    if before!=files(case):raise ValueError('Simulation inputs changed')
    result=dict(passed=True,tasks=args.tasks,simulator=subprocess.check_output([args.verilator,'--version'],text=True).strip(),
                inputs=before,executable_sha256=sha(exe),firmware=fw_receipt,build=build,modes=modes,
                macs=__import__('functools').reduce(lambda a,b:a*b,ENGINES[opt['engine']]),
                macros=inventory(opt),backend_tested=False,
                timing_boundary='first Host load request to final DMA output write response; startup excluded')
    save(receipt_path,result)
    # Publish only source/firmware/vector bindings, never claim a VCS run occurred.
    if args.tasks==12:
        sources={k:v for k,v in before.items() if not k.startswith('vectors/')}
        vectors={k:v for k,v in before.items() if k.startswith('vectors/')}
        save(case/'vcs_seed.json',dict(schema_version=1,qualification='Verilator 12 reset + 12 continuous tasks',
            source_sha256=sources,vector_sha256=vectors,firmware_sha256=sha(case/'output/firmware/kwt.hex')))
        vcs_power.verify_seed(case)
    return result

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--case',action='append',default=[])
    ap.add_argument('--tasks',type=int,choices=(1,12),default=12)
    ap.add_argument('--jobs',type=int,default=1)
    ap.add_argument('--build-jobs',type=int,default=4)
    ap.add_argument('--skip-build',action='store_true')
    ap.add_argument('--verilator',default='verilator')
    ap.add_argument('--gcc',default=str(ROOT/'tmp/toolchain/usr/bin/riscv64-unknown-elf-gcc'))
    args=ap.parse_args()
    names=[c['name'] for c in json.loads((ROOT/'study/activity_manifest.json').read_text())['cases']]
    if set(args.case)-set(names):ap.error('Unknown case')
    names=args.case or names
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results=list(pool.map(lambda name:simulate(name,args),names))
    print('FRONTEND_PASS',len(results),'cases',flush=True)

if __name__=='__main__':main()
