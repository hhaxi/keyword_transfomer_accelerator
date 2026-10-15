"""Build real RV32 firmware and simulate the pinned E203 CPU plus our System Bus."""
import json
from pathlib import Path
from run_design import ROOT,OUT,RTL,run,sim

SOC=ROOT/'assets/references/e203_hbirdv2-9f3e34f337f5d0a1236a285871ffa2032491617a'

def source_files():
    files=[]
    for sub in ('core','general'):
        files.extend(str(p.relative_to(ROOT)).replace('\\','/') for p in sorted((SOC/'rtl/e203'/sub).glob('*.v')))
    files.append(str((SOC/'rtl/e203/subsys/e203_subsys_nice_core.v').relative_to(ROOT)).replace('\\','/'))
    return files

def firmware():
    dest=OUT/'firmware';dest.mkdir(parents=True,exist_ok=True)
    binpath=ROOT/'.tools/nuclei-gcc/gcc/bin'
    elf=dest/'kwt.elf'
    run('firmware-build',[binpath/'riscv64-unknown-elf-gcc.exe','-march=rv32imac_zicsr_zifencei','-mabi=ilp32',
        '-O2','-ffreestanding','-fno-builtin','-nostdlib','-nostartfiles','-Wl,--no-relax',
        '-T','firmware/link.ld','firmware/start.S','firmware/main.c','firmware/kwt_driver.c','-o',elf])
    run('firmware-elf',[binpath/'riscv64-unknown-elf-readelf.exe','-h','-A',elf])
    symbols=run('firmware-symbols',[binpath/'riscv64-unknown-elf-nm.exe','-n',elf])
    trap=int(next(line.split()[0] for line in symbols.splitlines() if line.endswith(' trap_entry')),16)
    if trap%4:raise RuntimeError('mtvec entry must be four-byte aligned')
    run('firmware-binary',[binpath/'riscv64-unknown-elf-objcopy.exe','-O','binary',elf,dest/'kwt.bin'])
    data=(dest/'kwt.bin').read_bytes();data+=b'\x00'*((-len(data))%4)
    (dest/'kwt.hex').write_text(''.join('%08x\n'%int.from_bytes(data[i:i+4],'little') for i in range(0,len(data),4)))
    (dest/'size.vh').write_text('`define FW_WORDS %d\n'%(len(data)//4))

def build_and_simulate():
    firmware()
    files=source_files()+RTL+['integration/kwt_shared_sram.sv','integration/kwt_system_bus.sv',
                             'integration/kwt_soc.sv','tests/tb_soc.sv']
    includes=['+incdir+'+str((SOC/'rtl/e203/core').relative_to(ROOT)).replace('\\','/'),
              '+incdir+output/design/firmware','+define+DISABLE_SV_ASSERTION']
    text=sim('tb_soc',files,includes)
    if 'SOC_PASS' not in text: raise RuntimeError('SoC test did not pass')

if __name__=='__main__': build_and_simulate()
