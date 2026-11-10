"""Check every quad's four physical SRAM writes against original W16 tensors."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from decoder_test import compress, source_w16, write_hex

CASE = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legacy-red', action='store_true')
    args = parser.parse_args()
    out = CASE / 'tmp/w_quad'
    out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env['TEMP'] = env['TMP'] = str(out)
    iverilog = shutil.which('iverilog') or 'D:/softwares/iverilog/bin/iverilog.exe'
    vvp = shutil.which('vvp') or str(Path(iverilog).with_name('vvp.exe' if os.name == 'nt' else 'vvp'))
    core = CASE / 'rtl/kwt_tile_core.sv'
    extra = []
    defines = []
    if args.legacy_red:
        legacy = out / 'legacy_tile_core.sv'
        original = CASE.parents[1] / 'q128_low_power_combo/case/rtl/kwt_tile_core.sv'
        legacy.write_text(original.read_text().replace('module kwt_tile_core #(',
                                                      'module legacy_tile_core #('))
        core = out / 'legacy_core_adapter.sv'
        core.write_text('''module kwt_tile_core #(parameter FUSE=0,SMALL_BIAS=0)(
input clk,rst_n,dma_load_valid,input [19:0] dma_load_addr,input [31:0] dma_load_data,
output dma_load_ready,input dma_w_valid,input [63:0] dma_w_quad,input [11:0] dma_w_index,
output dma_w_ready,input dma_start,dma_clear,output [1:0] dma_x_free,
input dma_x_valid,input [67:0] dma_x_residual,input [10:0] dma_x_index,output dma_x_ready,
output dma_out_valid,output [63:0] dma_out_data,output [14:0] dma_out_index,
input dma_out_ready,output dma_done,dma_fault,output [31:0] perf_cycles,perf_mac_cycles,perf_fifo_wait);
wire ready; assign dma_x_ready=0; assign dma_w_ready=ready && rst_n && !dma_clear; assign dma_load_ready=ready;
legacy_tile_core #(.FUSE(FUSE),.SMALL_BIAS(SMALL_BIAS)) legacy(
.clk(clk),.rst_n(rst_n),.dma_load_valid((dma_load_valid || dma_w_valid) && rst_n && !dma_clear),
.dma_load_addr(dma_w_valid ? 20'h20000+{5'b0,dma_w_index,3'b0} : dma_load_addr),
.dma_load_data(dma_w_valid ? dma_w_quad[31:0] : dma_load_data),.dma_load_ready(ready),
.dma_start(dma_start),.dma_clear(dma_clear),.dma_x_free(dma_x_free),
.dma_out_valid(dma_out_valid),.dma_out_data(dma_out_data),.dma_out_index(dma_out_index),
.dma_out_ready(dma_out_ready),.dma_done(dma_done),.dma_fault(dma_fault),
.perf_cycles(perf_cycles),.perf_mac_cycles(perf_mac_cycles),.perf_fifo_wait(perf_fifo_wait));
endmodule
''')
        extra = [str(legacy)]
        defines = ['-DCORE=dut.legacy']
    sources = ['tests/macro_fixtures.sv', 'tech/kwt_sram_clock_gate.sv',
               'tech/kwt_sram16.sv', 'rtl/kwt_tile_mac.sv',
               'rtl/kwt_int16_result_queue.sv', str(core), 'tests/tb_w_quad.sv']
    executable = out / 'w_quad.vvp'
    command = [iverilog, '-g2012', '-Itests', '-Irtl', '-s', 'tb_w_quad',
               '-o', str(executable)] + defines + sources + extra
    result = subprocess.run(command, cwd=CASE, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (out / 'compile.log').write_text(result.stdout)
    if result.returncode:
        raise RuntimeError(result.stdout)
    vector_dir = CASE.parents[1] / 'q128_ppa/tmp/cases/baseline/vectors'
    if not vector_dir.exists():
        vector_dir = CASE / 'vectors'
    datasets = [('unique_banks', [(c*257+k*37+0x8000) % 65536-32768
                                 for c in range(256) for k in range(64)], None)]
    for task in range(12):
        source = vector_dir / f'task_{task:02d}/w.hex'
        values = [source_w16(int(line, 16)) for line in source.read_text().splitlines() if line.strip()]
        datasets.append((f'task_{task:02d}', values, source))
    results = []
    for name, values, source in datasets:
        _, expected = compress(values)
        if source and source.with_name('w_packed.hex').exists():
            pairs = [int(line, 16) for line in source.with_name('w_packed.hex').read_text().splitlines() if line.strip()]
            assert expected == [pairs[c*32+k] | pairs[(c+1)*32+k] << 32
                                for c in range(0, 256, 2) for k in range(32)]
        data = out / f'{name}.hex'
        write_hex(data, expected, 16)
        result = subprocess.run([vvp, str(executable), f'+INPUT={data}', f'+NAME={name}'],
                                cwd=CASE, env=env, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        (out / f'{name}.log').write_text(result.stdout)
        if args.legacy_red:
            (out / 'legacy_red.log').write_text(result.stdout)
            assert result.returncode and 'wrong bank write' in result.stdout, result.stdout
            print('W_QUAD_LEGACY_RED_CONFIRMED ' + result.stdout.strip())
            return
        print(result.stdout, end='')
        result.check_returncode()
        assert 'W_QUAD_PASS' in result.stdout
        results.append(dict(name=name, halfwords=16384,
                            original_sha256=hashlib.sha256(source.read_bytes()).hexdigest() if source else None))
    (out / 'results.json').write_text(json.dumps(dict(datasets=len(results), results=results), indent=2)+'\n')
    print(f'W_QUAD_REGRESSION_PASS datasets={len(results)} checked_halfwords={16384*len(results)}')


if __name__ == '__main__':
    main()
