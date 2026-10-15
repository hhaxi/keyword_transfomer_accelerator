"""Synthesize the complete DMA+compute engine and the bus, then test both netlists."""
import shlex
from run_design import OUT,CONFIG,linux,sim


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    script='\n'.join([
        'read_verilog -sv -D KWT_SRAM_BLACKBOX rtl/kwt_sram16.sv',
        'read_verilog -sv rtl/kwt_gelu.sv rtl/kwt_mac40.sv rtl/kwt_accel.sv rtl/kwt_dma.sv',
        'synth -top kwt_dma -flatten', 'check -assert',
        'tee -o output/design/dma-synthesis-stat.json stat -json',
        'write_verilog -noattr output/design/kwt_dma_netlist.v',
        'design -reset', 'read_verilog -sv integration/kwt_bus_fabric.sv',
        'synth -top kwt_bus_fabric -flatten', 'check -assert',
        'tee -o output/design/bus-synthesis-stat.json stat -json',
        'write_verilog -noattr output/design/kwt_bus_netlist.v',
    ])+'\n'
    (OUT/'synth_dma.ys').write_text(script)
    linux('dma-synthesis',shlex.quote(CONFIG.get('wsl_yosys','yosys'))+' -Q -T -s output/design/synth_dma.ys')
    result=sim('tb_dma',['rtl/kwt_sram16.sv','output/design/kwt_dma_netlist.v','tests/tb_dma.sv'],label='tb_dma_netlist')
    if 'DMA_PASS' not in result:raise RuntimeError('DMA netlist regression failed')
    result=sim('tb_ffn',['rtl/kwt_sram16.sv','output/design/kwt_dma_netlist.v','tests/tb_ffn.sv'],label='tb_ffn_netlist')
    if 'FFN_PASS' not in result:raise RuntimeError('Full FFN netlist regression failed')
    result=sim('tb_bus',['integration/kwt_shared_sram.sv','output/design/kwt_bus_netlist.v','tests/tb_bus.sv'],label='tb_bus_netlist')
    if 'BUS_PASS' not in result:raise RuntimeError('Bus netlist regression failed')


if __name__=='__main__':main()
