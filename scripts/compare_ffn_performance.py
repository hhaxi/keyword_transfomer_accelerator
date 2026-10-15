"""Compare the same full-FFN workload against preserved v5 evidence."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def compare(current):
    baseline=json.loads((ROOT/'docs/performance-baseline-v5.json').read_text())
    old=baseline['ffn'];new=current['optional_ffn']
    contracts=['model/format.json','model/numeric.py','model/ffn-format.json','model/ffn_numeric.py',
               'rtl/kwt_gelu.sv','rtl/kwt_dma.sv','rtl/kwt_mac40.sv','rtl/kwt_sram16.sv',
               'integration/kwt_bus_fabric.sv','integration/kwt_shared_sram.sv',
               'integration/kwt_system_bus.sv','integration/kwt_soc.sv',
               'firmware/kwt_driver.c','firmware/kwt_driver.h','firmware/main.c','tests/tb_soc.sv']
    for name in contracts:
        digest=hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
        if digest!=baseline['source_sha256'][name] or digest!=current['source_sha256'][name]:
            raise RuntimeError('Full FFN contract changed: '+name)
    # Only expected MAC counter values change; timing, reset, host loading,
    # response polling, input paths and output checks must remain identical.
    tb=(ROOT/'tests/tb_soc_ffn.sv').read_bytes().replace(b'\r\n',b'\n')
    restored=tb.replace(b'j==4 && rd!=202752',b'j==4 && rd!=405504').replace(
        b'j==0 && rd!=101376',b'j==0 && rd!=202752')
    if hashlib.sha256(restored).hexdigest()!=baseline['source_sha256']['tests/tb_soc_ffn.sv']:
        raise RuntimeError('Full FFN benchmark changed beyond expected counter assertions')
    if new['ffn_vector_manifest_sha256']!=old['ffn_vector_manifest_sha256']:
        raise RuntimeError('Full FFN tensors changed')
    if new['numeric']!=old['numeric'] or new['calibration']!=old['calibration']:
        raise RuntimeError('Full FFN numeric evidence changed')
    if [(t['task'],t['outputs']) for t in new['tasks']]!=[(t['task'],t['outputs']) for t in old['tasks']]:
        raise RuntimeError('Full FFN task/output set changed')
    if new['performance']['target_clock_hz']!=old['performance']['target_clock_hz']:
        raise RuntimeError('Nominal frequency changed')
    before=old['performance']['total_cycles'];after=new['performance']['total_cycles']
    if after>=before:raise RuntimeError('Full FFN has not improved')
    cells={name:{'before':baseline['generic_synthesis'][name]['num_cells'],
                 'after':current['generic_synthesis'][name]['num_cells']}
           for name in ['accelerator','dma_engine','bus','soc']}
    hz=new['performance']['target_clock_hz'];count=len(new['tasks'])
    result={'baseline_git_commit':baseline['git_commit'],
            'same_workload_and_timing_verified':True,'numeric_contract_unchanged':True,
            'baseline_cycles_per_task':[t['cycles'] for t in old['tasks']],
            'optimized_cycles_per_task':[t['cycles'] for t in new['tasks']],
            'baseline_total_cycles':before,'optimized_total_cycles':after,
            'speedup':before/after,'cycle_reduction_percent':100*(1-after/before),
            'throughput_increase_percent':100*(before/after-1),
            'baseline_nominal_tasks_per_second':count*hz/before,
            'optimized_nominal_tasks_per_second':count*hz/after,
            'baseline_nominal_ms_per_task':before/count/hz*1000,
            'optimized_nominal_ms_per_task':after/count/hz*1000,
            'mac_units_before':8,'mac_units_after':16,'output_columns_parallel':8,
            'k_terms_per_cycle_before':1,'k_terms_per_cycle_after':2,
            'internal_sram_bytes_before':87040,'internal_sram_bytes_after':87040,
            'sram_macros_before':40,'sram_macros_after':40,
            'generic_cells':cells,'target_clock_hz':hz,'timing_closed':False,
            'note':'More arithmetic hardware and simultaneous bank activity; no measured power/energy or physical area claim. Mandatory FFN1 remains a separate workload.'}
    (ROOT/'docs/ffn-performance-comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    print(json.dumps(compare(json.loads((ROOT/'docs/design-validation.json').read_text())),indent=2))
