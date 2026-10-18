"""Build and verify the full encoder extension while retaining the v8 FFN flow."""
import argparse
import hashlib
import json
import shlex
import sys
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from run_design import ROOT,OUT,CONFIG,RTL,SYSTEM_RTL,run,linux
from build_soc import SOC,source_files

ENC_RTL=['rtl/kwt_vecmem32.sv','rtl/kwt_udiv64.sv','rtl/kwt_isqrt64.sv',
         'rtl/kwt_exp_negative.sv','rtl/kwt_encoder.sv']
ENC_BUS=['rtl/kwt_result_fifo.sv','integration/kwt_dma_arbiter.sv','integration/kwt_extended_system_bus.sv']
DEST=ROOT/'output/encoder-design'


def sim(top,files,extra=None,label=None,run_args=None,shards=None):
    """Long encoder regressions have a separate timeout from small FFN tests."""
    label=label or top
    command=[CONFIG.get('wsl_verilator','verilator'),'--binary','--timing','--build-jobs','4','-Wno-fatal',
             '--top-module',top,'--Mdir','output/design/build_'+label]+(extra or [])+files
    linux(label+'-build',' '.join(shlex.quote(s) for s in command),1800)
    if shards:
        def run_shard(item):
            first,count=item
            name=label+'_shard'+str(first)
            text=linux(name+'-run','output/design/build_'+label+'/V'+top+' +first='+str(first)+' +tasks='+str(count)+' +baseline=0 '+ ' '.join(shlex.quote(s) for s in (run_args or []) if s.startswith(('+transport=','+layers=','+input_stream='))),14400)
            rows=re.findall(r'ENC_SOC_TASK_PASS task=(\d+) cycles=(\d+) baseline=0 outputs=6336',text)
            if [int(t) for t,c in rows]!=list(range(first,first+count)) or 'ENC_SOC_PASS tasks='+str(count) not in text:
                raise RuntimeError('Incomplete shard '+name)
            return text,sum(int(c) for t,c in rows)
        with ThreadPoolExecutor(max_workers=len(shards)) as pool:results=list(pool.map(run_shard,shards))
        text='\n'.join(t for t,c in results)+'\nENC_SOC_SHARDS_PASS tasks='+str(sum(c for f,c in shards))+' total_cycles='+str(sum(c for t,c in results))+'\n'
        (OUT/(label+'-run.log')).write_text(text)
        return text
    return linux(label+'-run','output/design/build_'+label+'/V'+top+' '+
                 ' '.join(shlex.quote(s) for s in (run_args or [])),14400)


def firmware():
    dest=DEST/'firmware';dest.mkdir(parents=True,exist_ok=True)
    tool=ROOT/'.tools/nuclei-gcc/gcc/bin'
    run('encoder-firmware-build',[tool/'riscv64-unknown-elf-gcc.exe','-march=rv32imac_zicsr_zifencei','-mabi=ilp32',
        '-O2','-ffreestanding','-fno-builtin','-nostdlib','-nostartfiles','-Wl,--no-relax','-T','firmware/link.ld',
        'firmware/start.S','firmware/main_encoder.c','firmware/kwt_driver.c','firmware/kwt_encoder_driver.c','-o',dest/'encoder.elf'])
    symbols=run('encoder-firmware-symbols',[tool/'riscv64-unknown-elf-nm.exe','-n',dest/'encoder.elf'])
    if int(next(s.split()[0] for s in symbols.splitlines() if s.endswith(' trap_entry')),16)%4:raise RuntimeError('Trap alignment')
    run('encoder-firmware-bin',[tool/'riscv64-unknown-elf-objcopy.exe','-O','binary',dest/'encoder.elf',dest/'encoder.bin'])
    data=(dest/'encoder.bin').read_bytes();data+=b'\x00'*((-len(data))%4)
    (dest/'encoder.hex').write_text(''.join('%08x\n'%int.from_bytes(data[i:i+4],'little') for i in range(0,len(data),4)))
    (dest/'encoder_size.vh').write_text('`define ENC_FW_WORDS %d\n'%(len(data)//4))


def soc(netlist=False,tasks=12,baseline=0,first=0,label=None,metrics=False,activity=False,jobs=1,transport=2,fifo_metrics=False,extra_flags=None,layers=12,input_stream=0):
    includes=['+incdir+output/encoder-design/firmware']
    if netlist:
        files=[str((SOC/'rtl/e203/general'/n).relative_to(ROOT)).replace('\\','/') for n in ['sirv_gnrl_ram.v','sirv_sim_ram.v']]
        files+=['rtl/kwt_sram16.sv','integration/kwt_shared_sram.sv','output/encoder-design/encoder_soc_netlist.v']
    else:
        files=source_files()+SYSTEM_RTL+ENC_RTL+ENC_BUS+['integration/kwt_shared_sram.sv','integration/kwt_encoder_soc.sv']
        includes+=['+incdir+'+str((SOC/'rtl/e203/core').relative_to(ROOT)).replace('\\','/'),'+define+DISABLE_SV_ASSERTION']
    label=label or ('tb_encoder_soc_netlist' if netlist else 'tb_encoder_soc')
    if not netlist:includes+=['+define+ENCODER_PHASE_METRICS']
    if metrics:includes+=['+define+ENCODER_MEMORY_METRICS','+incdir+tests']
    if fifo_metrics:includes+=['+define+ENCODER_FIFO_METRICS','+incdir+tests']
    includes+=extra_flags or []
    if activity:includes+=['--trace-fst']
    testbench='tests/tb_encoder_soc.sv'
    if netlist:
        # The new input-link observer names RTL registers. Strip that observer
        # for a flattened netlist; retain host traffic and all output/stat checks.
        source=(ROOT/testbench).read_text()
        first_observer=source.index('    integer in_words=')
        after_observer=source.index('    integer taskid,',first_observer)
        generated=DEST/'tb_encoder_soc_netlist.sv'
        generated.write_text(source[:first_observer]+source[after_observer:])
        testbench=generated.relative_to(ROOT).as_posix()
    text=sim('tb_encoder_soc',files+[testbench],includes,label=label,
             run_args=['+layers='+str(layers),'+input_stream='+str(input_stream),'+transport='+str(transport),'+tasks='+str(tasks),'+baseline='+str(baseline),'+first='+str(first)]+(['+activity'] if activity else []),
             shards=[(first+i*tasks//jobs,(i+1)*tasks//jobs-i*tasks//jobs) for i in range(jobs)] if jobs>1 else None)
    if 'ENC_SOC_PASS tasks='+str(tasks) not in text and 'ENC_SOC_SHARDS_PASS tasks='+str(tasks) not in text:raise RuntimeError('Encoder SoC incomplete')


def synthesize():
    DEST.mkdir(exist_ok=True)
    fingerprints={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n').rstrip()+b'\n').hexdigest()
                  for d in ['rtl','integration'] for p in (ROOT/d).glob('*') if p.suffix in ['.v','.sv']}
    (DEST/'synthesis-source-sha256.json').write_text(json.dumps({'capture':'Before synthesis; normalized line endings and EOF whitespace','sha256':fingerprints},indent=2)+'\n')
    include=str((SOC/'rtl/e203/core').relative_to(ROOT)).replace('\\','/')
    upstream=[f for f in source_files() if not f.endswith('/sirv_gnrl_ram.v')]
    files=upstream+[f for f in SYSTEM_RTL if f!='rtl/kwt_sram16.sv']+ENC_RTL+ENC_BUS+['integration/kwt_encoder_soc.sv']
    script='\n'.join([
        'read_verilog -sv -D KWT_SRAM_BLACKBOX rtl/kwt_sram16.sv integration/kwt_shared_sram.sv integration/e203_ram_boundary.v',
        'read_verilog -sv -I'+include+' '+' '.join(files),
        'hierarchy -top kwt_encoder_soc',
        'tee -o output/encoder-design/architecture-stat.json stat -json',
        'synth -top kwt_encoder_soc -flatten -noabc','abc -fast','clean','check -assert',
        'tee -o output/encoder-design/soc-synthesis-stat.json stat -json',
        'write_verilog -noattr output/encoder-design/encoder_soc_netlist.v',
        'write_json output/encoder-design/encoder_soc_netlist.json'])+'\n'
    (DEST/'synth.ys').write_text(script)
    linux('encoder-synthesis',shlex.quote(CONFIG.get('wsl_yosys','yosys'))+' -Q -T -s output/encoder-design/synth.ys',1800)


def compatibility(netlist=False):
    from build_soc import firmware as old_firmware
    old_firmware()
    includes=['+incdir+output/design/firmware']
    if netlist:
        wrapper=DEST/'encoder_compat_netlist.v'
        wrapper.write_text((DEST/'encoder_soc_netlist.v').read_text().replace('module kwt_encoder_soc(', 'module kwt_soc('))
        files=[str((SOC/'rtl/e203/general'/n).relative_to(ROOT)).replace('\\','/') for n in ['sirv_gnrl_ram.v','sirv_sim_ram.v']]
        files+=['rtl/kwt_sram16.sv','integration/kwt_shared_sram.sv',str(wrapper.relative_to(ROOT)).replace('\\','/')]
    else:
        wrapper=DEST/'kwt_soc_compat.sv'
        wrapper.write_text((ROOT/'integration/kwt_encoder_soc.sv').read_text().replace('module kwt_encoder_soc(', 'module kwt_soc('))
        files=source_files()+SYSTEM_RTL+ENC_RTL+ENC_BUS+['integration/kwt_shared_sram.sv',str(wrapper.relative_to(ROOT)).replace('\\','/')]
        includes+=['+incdir+'+str((SOC/'rtl/e203/core').relative_to(ROOT)).replace('\\','/'),'+define+DISABLE_SV_ASSERTION']
    for top in ['tb_soc','tb_soc_ffn']:
        label=top+'_encoder_compat'+('_netlist' if netlist else '')
        text=sim(top,files+['tests/'+top+'.sv'],includes,label=label,run_args=['+profile'])
        if 'SOC_PASS tasks=12' not in text:raise RuntimeError('Compatibility regression incomplete')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('task',choices=['transfer','transfer-profile','component','math','fourstate','faults','compat','compat-netlist','soc','profile','synth','netlist','lint'])
    p.add_argument('--tasks',type=int,default=12);p.add_argument('--first',type=int,default=0)
    p.add_argument('--jobs',type=int,default=1,help='Independent RTL task shards; each task retains identical simulated timing')
    p.add_argument('--transport',type=int,choices=[0,1,2],default=2,help='0 legacy int64, 1 packed int40, 2 FIFO int40')
    p.add_argument('--layers',type=int,choices=[1,12],default=12)
    p.add_argument('--input-stream',type=int,choices=[0,1],default=0)
    p.add_argument('--baseline',type=int,choices=[0,1],default=0)
    a=p.parse_args();DEST.mkdir(exist_ok=True)
    if a.jobs<1 or a.jobs>a.tasks or (a.jobs>1 and (a.task!='soc' or a.baseline)):
        p.error('--jobs must be 1..tasks, and sharding is supported for optimized RTL soc only')
    if a.task=='transfer-profile':
        firmware();soc(tasks=1,label='tb_encoder_soc_transport_profile',transport=2)
        for mode,label in [(0,'legacy64'),(1,'packed40')]:
            text=linux('tb_encoder_soc_'+label+'-run','output/design/build_tb_encoder_soc_transport_profile/Vtb_encoder_soc +tasks=1 +baseline=0 +transport='+str(mode),14400)
            if 'ENC_SOC_PASS tasks=1' not in text:raise RuntimeError('Transport profile incomplete')
    elif a.task=='transfer':
        for top,files,marker in [('tb_result_fifo',['rtl/kwt_result_fifo.sv'],'RESULT_FIFO_PASS'),
                                 ('tb_ffn_transport',RTL+['rtl/kwt_dma.sv'],'FFN_TRANSPORT_PASS')]:
            files=files+['tests/'+top+'.sv']
            if marker not in sim(top,files):raise RuntimeError('Transfer test failed')
            if top=='tb_ffn_transport':linux('tb_ffn_transport_ideal-run','output/design/build_tb_ffn_transport/Vtb_ffn_transport +ideal=1',1800)
            compiler=Path(CONFIG['iverilog_bin'])/'iverilog.exe';runtime=Path(CONFIG['iverilog_bin'])/'vvp.exe'
            run('icarus-'+top+'-build',[compiler,'-g2012','-s',top,'-o',DEST/(top+'.vvp')]+files)
            if marker not in run('icarus-'+top,[runtime,DEST/(top+'.vvp')],1800):raise RuntimeError('Transfer four-state failed')
        sim('tb_encoder',['rtl/kwt_sram16.sv']+ENC_RTL+['tests/tb_encoder.sv'],['+define+ENCODER_TRACE'],label='tb_encoder_transfers',run_args=['+transport=1'])
        if 'ENCODER_PASS layers=12' not in linux('tb_encoder_stream40-run','output/design/build_tb_encoder_transfers/Vtb_encoder +transport=2',14400):raise RuntimeError('Stream trace failed')
        run('icarus-tb_encoder_transfers-build',[compiler,'-g2012','-DENCODER_TRACE','-s','tb_encoder','-o',DEST/'encoder_transfers.vvp','rtl/kwt_sram16.sv']+ENC_RTL+['tests/tb_encoder.sv'])
        for mode,label in [(1,'packed40'),(2,'stream40')]:
            if 'ENCODER_PASS layers=1' not in run('icarus-tb_encoder_'+label,[runtime,DEST/'encoder_transfers.vvp','+layers=1','+transport='+str(mode)],1800):raise RuntimeError('Four-state encoder transfer failed')
    elif a.task=='component':
        text=sim('tb_encoder',['rtl/kwt_sram16.sv']+ENC_RTL+['tests/tb_encoder.sv'],['+define+ENCODER_TRACE'])
        if 'ENCODER_PASS layers=12' not in text:raise RuntimeError('Component incomplete')
        for mode in [0,1]:
            text=linux('tb_encoder_dma'+str(mode)+'-run','output/design/build_tb_encoder/Vtb_encoder +layers=1 +dma_mode='+str(mode),1800)
            if 'ENCODER_PASS layers=1' not in text:raise RuntimeError('DMA stream check incomplete')
        text=linux('tb_encoder_constant-run','output/design/build_tb_encoder/Vtb_encoder +layers=1 +constant_edge=1',1800)
        if 'ENCODER_PASS layers=1 constant_edge=1' not in text:raise RuntimeError('Constant LayerNorm/Softmax incomplete')
    elif a.task in ('math','fourstate'):
        run('encoder-numeric-tests',[sys.executable,'tests/test_encoder.py'])
        math_files=ENC_RTL[1:4]+['tests/tb_encoder_math.sv']
        if a.task=='math':
            if 'ENC_MATH_PASS' not in sim('tb_encoder_math',math_files,['+incdir+output/encoder-math']):raise RuntimeError('Math incomplete')
        else:
            compiler=Path(CONFIG['iverilog_bin'])/'iverilog.exe';runtime=Path(CONFIG['iverilog_bin'])/'vvp.exe'
            for top,files,flags,args,marker in [
                ('tb_encoder_math',math_files,['-I','output/encoder-math'],[],'ENC_MATH_PASS'),
                ('tb_encoder',['rtl/kwt_sram16.sv']+ENC_RTL+['tests/tb_encoder.sv'],['-DENCODER_TRACE'],['+layers=1'],'ENCODER_PASS layers=1')]:
                run('icarus-'+top+'-build',[compiler,'-g2012','-s',top,'-o',DEST/(top+'.vvp')]+flags+files)
                if marker not in run('icarus-'+top,[runtime,DEST/(top+'.vvp')]+args,1800):raise RuntimeError('Four-state incomplete')
    elif a.task=='faults':
        for top,files,marker in [('tb_encoder_faults',['rtl/kwt_sram16.sv']+ENC_RTL,'ENC_FAULTS_PASS'),
                                 ('tb_dma_arbiter',['integration/kwt_dma_arbiter.sv'],'ENC_ARBITER_PASS')]:
            files=files+['tests/'+top+'.sv']
            if marker not in sim(top,files):raise RuntimeError('Fault check failed')
            compiler=Path(CONFIG['iverilog_bin'])/'iverilog.exe';runtime=Path(CONFIG['iverilog_bin'])/'vvp.exe'
            run('icarus-'+top+'-build',[compiler,'-g2012','-s',top,'-o',DEST/(top+'.vvp')]+files)
            if marker not in run('icarus-'+top,[runtime,DEST/(top+'.vvp')],1800):raise RuntimeError('Four-state fault check failed')
    elif a.task in ('compat','compat-netlist'):compatibility(a.task=='compat-netlist')
    elif a.task=='profile':
        firmware();soc(tasks=1,label='tb_encoder_soc_profile',metrics=True)
        text=linux('tb_encoder_soc_baseline-run','output/design/build_tb_encoder_soc_profile/Vtb_encoder_soc +tasks=1 +baseline=1',14400)
        if 'ENC_SOC_PASS tasks=1' not in text:raise RuntimeError('Baseline incomplete')
    elif a.task=='synth':synthesize()
    elif a.task=='lint':
        linux('encoder-lint',CONFIG['wsl_verilator']+' --lint-only -Wall --top-module kwt_extended_system_bus '+
              ' '.join(SYSTEM_RTL+ENC_RTL+ENC_BUS+['integration/kwt_shared_sram.sv']))
    else:
        firmware();soc(a.task=='netlist',a.tasks,a.baseline,a.first,jobs=a.jobs,transport=a.transport,layers=a.layers,input_stream=a.input_stream)


if __name__=='__main__':main()
