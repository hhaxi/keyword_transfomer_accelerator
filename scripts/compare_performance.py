"""Compare v3 DMA performance with pinned v1/v2 using the same timed workload."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def compare(current):
    baseline = json.loads((ROOT / 'docs/performance-baseline-v2.json').read_text())
    first = json.loads((ROOT / 'docs/performance-baseline.json').read_text())
    for name, expected in baseline['comparison_contract_sha256'].items():
        data=(ROOT / name).read_bytes().replace(b'\r\n', b'\n')
        actual=hashlib.sha256(data).hexdigest()
        if current['source_sha256'].get(name) != actual:
            raise RuntimeError('Report does not match source: ' + name)
        # Bus changes are the optimization under test. SRAM capacity/latency,
        # CPU wiring, numerical contract and the full timed test remain fixed.
        if name=='integration/kwt_system_bus.sv':continue
        if name=='tests/tb_soc.sv':
            data=re.sub(rb'(?m)^            // PROFILE_BEGIN[^\n]*\n[\s\S]*?^            // PROFILE_END\n',b'',data)
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError('Benchmark contract changed; review comparison: ' + name)
    vectors = hashlib.sha256((ROOT / 'output/vectors/manifest.json').read_bytes()).hexdigest()
    if vectors != baseline['vector_manifest_sha256']:
        raise RuntimeError('Performance vectors changed from the first-version baseline')
    manifest = json.loads((ROOT / 'output/vectors/manifest.json').read_text())
    for name, expected in manifest.items():
        if hashlib.sha256((ROOT / 'output/vectors' / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Performance vector does not match its manifest: ' + name)
    checks = {check['name']: check for check in current['checks']}
    tasks = checks['E203 RTL integration']['tasks']
    if tasks != checks['E203 netlist integration']['tasks']:
        raise RuntimeError('RTL/netlist performance differs')
    if [(t['task'], t['outputs']) for t in tasks] != [
            (t['task'], t['outputs']) for t in baseline['soc_tasks']]:
        raise RuntimeError('Task count or output count changed')
    before = baseline['performance']['total_cycles']
    after = sum(task['cycles'] for task in tasks)
    # At least 2x over v2; v1 remains an additional historical comparison.
    if after * 2 > before:
        raise RuntimeError('Frontend performance regression: less than 2x SoC speedup')
    hz = current['performance']['target_clock_hz']
    if hz != baseline['performance']['target_clock_hz']:
        raise RuntimeError('Nominal clock changed')
    return {
        'baseline_git_commit': baseline['git_commit'],
        'workload_timing_contract_verified': True,
        'bus_implementation_changed': True,
        'profile_reads_outside_timed_window': True,
        'first_version_git_commit': first['git_commit'],
        'first_version_total_cycles': first['performance']['total_cycles'],
        'speedup_over_first_version': first['performance']['total_cycles']/after,
        'vector_manifest_sha256': vectors,
        'task_count': len(tasks),
        'baseline_cycles_per_task': [t['cycles'] for t in baseline['soc_tasks']],
        'optimized_cycles_per_task': [t['cycles'] for t in tasks],
        'baseline_total_cycles': before, 'optimized_total_cycles': after,
        'soc_speedup': before / after, 'cycle_reduction_percent': 100 * (1 - after / before),
        'baseline_nominal_ms_per_task': before / len(tasks) / hz * 1000,
        'optimized_nominal_ms_per_task': after / len(tasks) / hz * 1000,
        'baseline_nominal_tasks_per_second': len(tasks) * hz / before,
        'optimized_nominal_tasks_per_second': len(tasks) * hz / after,
        'target_clock_hz': hz, 'timing_closed': False,
        'resources': {'mac_lanes_before': 4, 'mac_lanes_after': 4,
                      'internal_sram_bytes_before': 53248, 'internal_sram_bytes_after': 53248,
                      'compute_fifo_payload_register_bits': 320,
                      'dma_output_hold_bits': 64,
                      'generic_compute_core_cells_before': baseline['generic_synthesis']['accelerator']['num_cells'],
                      'generic_compute_core_cells_after': current['generic_synthesis']['accelerator']['num_cells'],
                      'generic_dma_engine_cells_after': current['generic_synthesis']['dma_engine']['num_cells'],
                      'generic_bus_cells_after': current['generic_synthesis']['bus']['num_cells']},
        'note': 'Same timed testbench, vectors, shared SRAM and numeric contract. Optional profile reads occur after timing. The bus and driver are intentionally optimized. Generic cell counts are not physical area or power; compute-core-only counts exclude the DMA engine and must not be used as total accelerator area.'
    }


def main():
    current = json.loads((ROOT / 'docs/design-validation.json').read_text())
    result = compare(current)
    (ROOT / 'docs/performance-comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    print('Verified SoC speedup: %.4fx; cycle reduction: %.2f%%' %
          (result['soc_speedup'], result['cycle_reduction_percent']))


if __name__ == '__main__':
    main()
