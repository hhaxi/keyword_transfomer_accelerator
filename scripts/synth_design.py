"""Generic synthesis + actual netlist simulation. Physical PPA requires official libs."""
import json
import shlex
from run_design import ROOT,OUT,CONFIG,linux,sim

def synthesize():
    OUT.mkdir(parents=True,exist_ok=True)
    script='\n'.join([
        'read_verilog -sv -D KWT_SRAM_BLACKBOX rtl/kwt_sram16.sv',
        'read_verilog -sv rtl/kwt_gelu.sv rtl/kwt_mac40.sv rtl/kwt_accel.sv',
        'synth -top kwt_accel -flatten',
        'check -assert',
        'tee -o output/design/synthesis-stat.json stat -json',
        'write_verilog -noattr output/design/kwt_accel_netlist.v',
        'write_json output/design/kwt_accel_netlist.json',
    ])+'\n'
    (OUT/'synth.ys').write_text(script)
    linux('synthesis',shlex.quote(CONFIG.get('wsl_yosys','yosys'))+' -Q -T -s output/design/synth.ys')
    # SRAM black boxes are replaced by the same synchronous functional macro model.
    result=sim('tb_accel',['rtl/kwt_sram16.sv','output/design/kwt_accel_netlist.v','tests/tb_accel.sv'],label='tb_accel_netlist')
    if 'ACCEL_PASS' not in result: raise RuntimeError('Post-synthesis mismatch')
    report={'synthesis':'compute-core generic gates, SRAM leaves preserved','post_synthesis_simulation':'12 compute-core tasks bit-exact; DMA/bus/SoC checks are collected separately',
            'area_scope':'Include DMA engine and added bus/interface logic in addition to the compute core and SRAM macros',
            'clock_target_mhz':150,'timing_met':None,'standard_cell_area_mm2':None,'sram_area_mm2':None,
            'total_accelerator_area_mm2':None,'average_soc_power_w':None,'energy_per_task_j':None,
            'macro_instances':{'16x4096_SP':2,'16x1024_SP':34,'16x128_SP':4},'internal_sram_bytes':87040,
            'blocking_inputs':['official standard-cell Liberty and PVT','official SRAM macro models, Liberty and area',
                               'official clock/load/interconnect conditions and accepted PPA flow'],
            'note':'Unknown physical metrics are null, never zero. Generic gate counts are not mm^2 or timing proof.'}
    (OUT/'ppa-status.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__': synthesize()
