"""Build the isolated firmware and run the real E203, native SP SRAM baseline."""
from pathlib import Path
import argparse,hashlib,json,os,re,shutil,subprocess,time
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output';OUT.mkdir(exist_ok=True)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def settings():
    p=ROOT/'environment/local_tools.json';cfg=json.loads(p.read_text()) if p.exists() else {}
    names=dict(verilator='verilator',make='make',gcc='riscv64-unknown-elf-gcc',iverilog='iverilog',yosys='yosys')
    return {k:Path(os.environ.get('FFN1_'+k.upper()) or cfg.get(k) or shutil.which(v) or v) for k,v in names.items()}

def environment(cfg):
    env=os.environ.copy();temp=ROOT/'tmp/temp';temp.mkdir(parents=True,exist_ok=True)
    env['TEMP']=env['TMP']=str(temp)
    search=[cfg[k].resolve().parent for k in ('make','verilator','gcc')]
    search.append(cfg['verilator'].resolve().parent.parent/'lib')
    env['PATH']=os.pathsep.join(map(str,search))+os.pathsep+env['PATH']
    vr=cfg['verilator'].resolve().parent.parent/'share/verilator'
    if vr.is_dir():env['VERILATOR_ROOT']=vr.as_posix()
    return env

def run(label,command,env):
    logs=OUT/'logs';logs.mkdir(exist_ok=True);p=logs/(label+'.log');t=time.time()
    print('RUN',label,flush=True)
    with p.open('wb') as f:result=subprocess.run([str(v) for v in command],cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT)
    text=p.read_text(encoding='utf-8',errors='replace');print(text[-1800:],flush=True)
    if result.returncode:raise RuntimeError(label+' failed: '+str(p))
    return text,dict(command=list(map(str,command)),log=p.relative_to(ROOT).as_posix(),log_sha256=sha(p),seconds=time.time()-t)

def build_firmware(cfg,env):
    p=OUT/'firmware';p.mkdir(exist_ok=True);gcc=cfg['gcc'];suffix='.exe' if os.name=='nt' else ''
    _,receipt=run('firmware',[gcc,'-march=rv32imac_zicsr_zifencei','-mabi=ilp32','-O2','-ffreestanding','-fno-builtin',
        '-nostdlib','-nostartfiles','-Wl,--no-relax','-T','firmware/link.ld','firmware/start.S','firmware/main.c','firmware/kwt_driver.c','-o','output/firmware/kwt.elf'],env)
    run('objcopy',[gcc.with_name('riscv64-unknown-elf-objcopy'+suffix),'-O','binary','output/firmware/kwt.elf','output/firmware/kwt.bin'],env)
    b=(p/'kwt.bin').read_bytes();b+=b'\0'*((-len(b))%4)
    (p/'kwt.hex').write_text(''.join(f'{int.from_bytes(b[j:j+4],"little"):08x}\n' for j in range(0,len(b),4)))
    (p/'size.vh').write_text(f'`define FW_WORDS {len(b)//4}\n')
    return receipt

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--tasks',type=int,default=12);ap.add_argument('--skip-build',action='store_true')
    ap.add_argument('--continuous',action='store_true');a=ap.parse_args()
    if not 1<=a.tasks<=12:raise ValueError('Tasks must be 1..12')
    cfg=settings();env=environment(cfg);receipts=[]
    sources=(ROOT/'filelists/soc.f').read_text().splitlines()+['tests/macro_fixtures.sv','tests/tb_soc.sv']
    mdir=ROOT/'tmp/sim';mdir.mkdir(parents=True,exist_ok=True)
    exe=mdir/('Vtb_soc.exe' if os.name=='nt' else 'Vtb_soc')
    signature={p:sha(ROOT/p) for p in sources}
    signature.update({p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT/'firmware').glob('*') if p.is_file()})
    signature.update({p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT/'vendor/e203/rtl/e203/core').glob('*.v')})
    signature['tests/sram_config.vh']=sha(ROOT/'tests/sram_config.vh')
    build=OUT/'build.json'
    if a.skip_build:
        saved=json.loads(build.read_text());assert saved['sources']==signature and sha(exe)==saved['executable_sha256'],'Sources changed; rebuild first'
        assert all(sha(ROOT/p)==h for p,h in saved['firmware'].items()),'Firmware changed; rebuild first'
    else:
        receipts.append(build_firmware(cfg,env))
        _,rec=run('elaborate',[cfg['verilator'],'--cc','--exe','--main','--timing','-Wno-fatal','--top-module','tb_soc','--Mdir','tmp/sim',
            '-DDISABLE_SV_ASSERTION','-Ivendor/e203/rtl/e203/core','-Ioutput/firmware','-Itests']+sources,env);receipts.append(rec)
        _,rec=run('build',[cfg['make'],'-C','tmp/sim','-f','Vtb_soc.mk','-j4'],env);receipts.append(rec)
        build.write_text(json.dumps(dict(sources=signature,executable_sha256=sha(exe),
            firmware={p.relative_to(ROOT).as_posix():sha(p) for p in (OUT/'firmware').iterdir() if p.is_file()}),indent=2)+'\n')
    label='continuous' if a.continuous else 'reset_tasks'
    text,rec=run(label,[exe,'+tasks='+str(a.tasks),'+profile']+(['+continuous'] if a.continuous else []),env);receipts.append(rec)
    cycles=list(map(int,re.findall(r'SOC_TASK_PASS task=\d+ cycles=(\d+)',text)))
    assert len(cycles)==a.tasks and f'SOC_PASS tasks={a.tasks} ' in text
    result=dict(passed=True,tasks=a.tasks,continuous=a.continuous,task_cycles=cycles,
        throughput_at_150MHz=a.tasks*150000000/sum(cycles),real_cpu=True,vendor_timing_model=False,dc_mapping_tested=False,
        sources=signature,receipts=receipts,vector_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT/'vectors').rglob('*.hex')})
    (ROOT/'verification'/(label+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    print('FFN1_SOC_PASS',label,cycles,flush=True)
if __name__=='__main__':main()
