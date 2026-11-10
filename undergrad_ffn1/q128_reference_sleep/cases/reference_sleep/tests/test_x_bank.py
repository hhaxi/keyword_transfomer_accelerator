"""Actual single-port SRAM restoration, all original X tensors in both orders."""
from pathlib import Path
import argparse
import json
import os
import shutil
from decoder_x_test import CASE, datasets, run, write_hex, x_stimulus


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--legacy-red', action='store_true')
    args = ap.parse_args()
    out = CASE/'tmp/x_bank'
    out.mkdir(parents=True, exist_ok=True)
    iv = shutil.which('iverilog') or 'D:/softwares/iverilog/bin/iverilog.exe'
    vvp = shutil.which('vvp') or str(Path(iv).with_name('vvp.exe' if os.name == 'nt' else 'vvp'))
    core = CASE/'rtl/kwt_tile_core.sv'
    extra, defines = [], []
    if args.legacy_red:
        old = out/'legacy.sv'
        old.write_text((CASE.parents[1]/'q128_dual_column/case/rtl/kwt_tile_core.sv').read_text()
                       .replace('module kwt_tile_core #(', 'module legacy_core #('))
        core = out/'legacy_adapter.sv'
        core.write_text('''module kwt_tile_core #(parameter X_DELTA=0,TAIL_FIRST=0,FUSE=0,SMALL_BIAS=0)(
input clk,rst_n,dma_clear,dma_start,input dma_load_valid,input [19:0] dma_load_addr,
input [31:0] dma_load_data,output dma_load_ready,input dma_w_valid,input [63:0] dma_w_quad,
input [11:0] dma_w_index,output dma_w_ready,input dma_x_valid,input [67:0] dma_x_residual,
input [10:0] dma_x_index,output dma_x_ready,output [1:0] dma_x_free,
output dma_out_valid,output [63:0] dma_out_data,output [14:0] dma_out_index,
input dma_out_ready,output dma_done,dma_fault,output [31:0] perf_cycles,perf_mac_cycles,perf_fifo_wait);
wire load_ready;assign dma_x_ready=load_ready;assign dma_load_ready=load_ready;
legacy_core #(.FUSE(FUSE),.SMALL_BIAS(SMALL_BIAS)) legacy(.clk(clk),.rst_n(rst_n),
.dma_clear(dma_clear),.dma_start(dma_start),.dma_load_valid(dma_load_valid||dma_x_valid),
.dma_load_addr(dma_x_valid ? 20'h10000+{5'b0,dma_x_index,4'b0} : dma_load_addr),
.dma_load_data(dma_x_valid ? {dma_x_residual[33:18],dma_x_residual[15:0]} : dma_load_data),
.dma_load_ready(load_ready),.dma_w_valid(dma_w_valid),.dma_w_quad(dma_w_quad),
.dma_w_index(dma_w_index),.dma_w_ready(dma_w_ready),.dma_x_free(dma_x_free),
.dma_out_valid(dma_out_valid),.dma_out_data(dma_out_data),.dma_out_index(dma_out_index),
.dma_out_ready(dma_out_ready),.dma_done(dma_done),.dma_fault(dma_fault),
.perf_cycles(perf_cycles),.perf_mac_cycles(perf_mac_cycles),.perf_fifo_wait(perf_fifo_wait));endmodule
''')
        extra, defines = [old], ['-DCORE=dut.legacy']
    sources = ['tests/macro_fixtures.sv', 'tech/kwt_sram_clock_gate.sv', 'tech/kwt_sram16.sv',
               'rtl/kwt_tile_mac.sv', 'rtl/kwt_int16_result_queue.sv', str(core), 'tests/tb_x_bank.sv']
    records=[]
    for tail in (0, 1):
        sim=out/f'x_{tail}.vvp'
        p=run([iv,'-g2012','-Itests','-Irtl','-s','tb_x_bank',f'-Ptb_x_bank.TAIL_FIRST={tail}',
               '-o',sim]+defines+sources+extra,out/f'compile_{tail}.log')
        if p.returncode:raise RuntimeError(p.stdout)
        for name,values,source in datasets():
            _,quads,tags,_=x_stimulus(values,tail)
            prefix=out/f'{name}_{tail}'
            for suffix,data,digits in [('quads',quads,17),('tags',tags,3),('values',[v&65535 for v in values],4)]:
                write_hex(prefix.with_name(prefix.name+f'_{suffix}.hex'),data,digits)
            p=run([vvp,sim,f'+PREFIX={prefix}',f'+NAME={name}'],out/f'{name}_{tail}.log')
            if args.legacy_red:
                (out/'legacy_red.log').write_text(p.stdout)
                assert p.returncode and 'X write mapping' in p.stdout,p.stdout
                print('X_BANK_LEGACY_RED_CONFIRMED '+p.stdout.strip());return
            print(p.stdout,end='');p.check_returncode()
            assert 'X_BANK_PASS' in p.stdout
            records.append(dict(name=name,tail_first=tail,values=6336))
    (out/'results.json').write_text(json.dumps(dict(datasets=len(records),records=records),indent=2)+'\n')
    print(f'X_BANK_REGRESSION_PASS datasets={len(records)} values={len(records)*6336}')


if __name__=='__main__':main()
