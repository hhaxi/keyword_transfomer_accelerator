"""Compare the same full-FFN workload against preserved v7 evidence."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def compare(current):
    baseline=json.loads((ROOT/'docs/performance-baseline-v7.json').read_text())
    old=baseline['ffn'];new=current['optional_ffn']
    contracts=['model/format.json','model/numeric.py','model/ffn-format.json','model/ffn_numeric.py',
               'rtl/kwt_gelu.sv','rtl/kwt_mac40.sv','rtl/kwt_sram16.sv','rtl/kwt_dma.sv',
               'integration/kwt_bus_fabric.sv','integration/kwt_shared_sram.sv',
               'integration/kwt_system_bus.sv','integration/kwt_soc.sv',
               'firmware/kwt_driver.c','firmware/kwt_driver.h','firmware/main.c','tests/tb_soc.sv']
    for name in contracts:
        data=(ROOT/name).read_bytes().replace(b'\r\n',b'\n')
        if hashlib.sha256(data).hexdigest()!=current['source_sha256'][name]:raise RuntimeError('Stale source hash: '+name)
        digest=hashlib.sha256(data).hexdigest()
        if digest!=baseline['source_sha256'][name]:
            raise RuntimeError('Full FFN contract changed: '+name)
    # Only the post-timing expected overlap count changes. All benchmark
    # transactions, timing boundaries and firmware remain identical to v7.
    tb=(ROOT/'tests/tb_soc_ffn.sv').read_bytes().replace(b'\r\n',b'\n')
    restored=tb.replace(b'rd!=25240',b'rd!=22085')
    if hashlib.sha256(restored).hexdigest()!=baseline['source_sha256']['tests/tb_soc_ffn.sv']:
        raise RuntimeError('Full FFN benchmark changed beyond post-timing diagnostics')
    region=baseline['timed_firmware_region']
    firmware=(ROOT/'output/design/firmware/kwt.bin').read_bytes()
    if hashlib.sha256(firmware[region['start_offset']:region['end_offset']]).hexdigest()!=region['sha256']:
        raise RuntimeError('Timed driver/dispatch machine code changed')
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
            'timed_driver_machine_code_unchanged':True,'dma_implementation_changed':False,
            'baseline_cycles_per_task':[t['cycles'] for t in old['tasks']],
            'optimized_cycles_per_task':[t['cycles'] for t in new['tasks']],
            'baseline_total_cycles':before,'optimized_total_cycles':after,
            'speedup':before/after,'cycle_reduction_percent':100*(1-after/before),
            'throughput_increase_percent':100*(before/after-1),
            'baseline_nominal_tasks_per_second':count*hz/before,
            'optimized_nominal_tasks_per_second':count*hz/after,
            'baseline_nominal_ms_per_task':before/count/hz*1000,
            'optimized_nominal_ms_per_task':after/count/hz*1000,
            'mac_units_before':16,'mac_units_after':16,'output_columns_parallel':8,
            'k_terms_per_cycle_before':2,'k_terms_per_cycle_after':2,
            'internal_sram_bytes_before':90624,'internal_sram_bytes_after':90624,
            'sram_macros_before':40,'sram_macros_after':40,
            'generic_cells':cells,'target_clock_hz':hz,'timing_closed':False,
            'note':'Same 16 MAC units and 90624-byte SRAM. Next-group read/init overlaps L1 MERGE or L2 FIFO acceptance; merge register preserved. No measured power/energy or physical area claim. Mandatory FFN1 remains a separate workload.'}
    (ROOT/'docs/ffn-performance-comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    print(json.dumps(compare(json.loads((ROOT/'docs/design-validation.json').read_text())),indent=2))
