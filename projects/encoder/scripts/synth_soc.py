"""Synthesize pinned E203 integration, preserving all SRAM technology boundaries."""
import shlex
from run_design import ROOT,OUT,CONFIG,RTL,linux,sim
from build_soc import SOC,source_files,firmware


def simulate_netlist(ffn=False):
    firmware()
    models=[str((SOC/'rtl/e203/general'/f).relative_to(ROOT)).replace('\\','/') for f in ['sirv_gnrl_ram.v','sirv_sim_ram.v']]
    top='tb_soc_ffn' if ffn else 'tb_soc'
    text=sim(top,models+['rtl/kwt_sram16.sv','integration/kwt_shared_sram.sv','output/design/kwt_soc_netlist.v','tests/'+top+'.sv'],
             ['+incdir+output/design/firmware'],label=top+'_netlist',run_args=['+profile'])
    if 'SOC_PASS' not in text:raise RuntimeError('SoC netlist simulation failed')

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    include=str((SOC/'rtl/e203/core').relative_to(ROOT)).replace('\\','/')
    files=[f for f in source_files() if not f.endswith('/sirv_gnrl_ram.v')]
    files+=['rtl/kwt_gelu.sv','rtl/kwt_mac40.sv','rtl/kwt_accel.sv','rtl/kwt_dma.sv','integration/kwt_bus_fabric.sv',
            'integration/kwt_system_bus.sv','integration/kwt_soc.sv']
    script='\n'.join([
        'read_verilog -sv -D KWT_SRAM_BLACKBOX rtl/kwt_sram16.sv integration/kwt_shared_sram.sv integration/e203_ram_boundary.v',
        'read_verilog -sv -I'+include+' '+' '.join(files),
        'synth -top kwt_soc -flatten',
        'check -assert',
        'tee -o output/design/soc-synthesis-stat.json stat -json',
        'write_verilog -noattr output/design/kwt_soc_netlist.v',
        'write_json output/design/kwt_soc_netlist.json',
    ])+'\n'
    (OUT/'synth_soc.ys').write_text(script)
    linux('soc-synthesis',shlex.quote(CONFIG.get('wsl_yosys','yosys'))+' -Q -T -s output/design/synth_soc.ys',1200)
    simulate_netlist()
    simulate_netlist(ffn=True)

if __name__=='__main__':main()
