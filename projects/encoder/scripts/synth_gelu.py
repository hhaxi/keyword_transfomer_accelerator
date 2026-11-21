"""Check the synthesized GELU over all directed/random arithmetic vectors."""
import shlex
from run_design import OUT,CONFIG,linux,sim

def main():
    (OUT/'synth_gelu.ys').write_text('\n'.join([
        'read_verilog -sv rtl/kwt_gelu.sv', 'synth -top kwt_gelu -flatten',
        'check -assert', 'tee -o output/design/gelu-synthesis-stat.json stat -json',
        'write_verilog -noattr output/design/kwt_gelu_netlist.v'])+'\n')
    linux('gelu-synthesis',shlex.quote(CONFIG.get('wsl_yosys','yosys'))+' -Q -T -s output/design/synth_gelu.ys')
    result=sim('tb_gelu',['output/design/kwt_gelu_netlist.v','tests/tb_gelu.sv'],label='tb_gelu_netlist')
    if 'GELU_PASS' not in result:raise RuntimeError('GELU netlist failed')

if __name__=='__main__':main()
