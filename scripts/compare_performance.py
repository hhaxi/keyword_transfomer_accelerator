"""Compare v4 with pinned v3; verify identical tensors and timing boundaries."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def compare(current):
    baseline = json.loads((ROOT / 'docs/performance-baseline-v3.json').read_text())
    first = json.loads((ROOT / 'docs/performance-baseline.json').read_text())
    second = json.loads((ROOT / 'docs/performance-baseline-v2.json').read_text())
    for name, expected in baseline['comparison_contract_sha256'].items():
        data=(ROOT / name).read_bytes().replace(b'\r\n', b'\n')
        actual=hashlib.sha256(data).hexdigest()
        if current['source_sha256'].get(name) != actual:
            raise RuntimeError('Report does not match source: ' + name)
        # Only explicit transport packing/checks and expected activity counts
        # may differ in the testbench. Clock, host handshake, timer boundaries,
        # CPU polling, resets and output checker must still hash to the v3 file.
        if name=='tests/tb_soc.sv':
            for tag in ['PACKED_DECL', 'PACKED_CHECK']:
                pattern=rb'(?m)^ *// '+tag.encode()+rb'_BEGIN\n[\s\S]*?^ *// '+tag.encode()+rb'_END\n'
                data,n=re.subn(pattern,b'',data)
                if n!=1:raise RuntimeError('Missing packed testbench block: '+tag)
            replacements={
                b"j<3168;j=j+1) host(0,32'ha0010000+32'(4*j),xp[j]":b"j<6336;j=j+1) host(0,32'ha0010000+32'(4*j),xv[j]",
                b"j<8192;j=j+1) host(0,32'ha0018000+32'(4*j),wp[j]":b"j<16384;j=j+1) host(0,32'ha0018000+32'(4*j),wv[j]",
                b'rd!=202752':b'rd!=405504', b'rd!=11616':b'rd!=22976'}
            for a,b in replacements.items():
                if data.count(a)!=1:raise RuntimeError('Unexpected benchmark packing change')
                data=data.replace(a,b)
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError('Benchmark contract changed; review comparison: ' + name)
    vectors = hashlib.sha256((ROOT / 'output/vectors/manifest.json').read_bytes()).hexdigest()
    if vectors != baseline['vector_manifest_sha256']:
        raise RuntimeError('Performance vectors changed from the first-version baseline')
    manifest = json.loads((ROOT / 'output/vectors/manifest.json').read_text())
    for name, expected in manifest.items():
        if hashlib.sha256((ROOT / 'output/vectors' / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Performance vector does not match its manifest: ' + name)
    from pack_vectors import pack
    packed_manifest=json.loads((ROOT/'output/vectors/packed-manifest.json').read_text())
    if sorted(packed_manifest)!=['task_%02d'%i for i in range(12)]:
        raise RuntimeError('Packed manifest task set differs')
    for task,files in packed_manifest.items():
        if sorted(files)!=['w_packed.hex','x_packed.hex']:raise RuntimeError('Packed files missing')
        for name,record in files.items():
            source=ROOT/'output/vectors'/task/name.replace('_packed','')
            target=ROOT/'output/vectors'/task/name
            if hashlib.sha256(source.read_bytes()).hexdigest()!=record['source_sha256'] or hashlib.sha256(target.read_bytes()).hexdigest()!=record['sha256']:
                raise RuntimeError('Packed provenance mismatch')
            original=[int(v,16) for v in source.read_text().split()]
            actual=[int(v,16) for v in target.read_text().split()]
            if actual!=pack(original) or len(actual)!=record['words']:
                raise RuntimeError('Packed transport is not lossless')
    checks = {check['name']: check for check in current['checks']}
    tasks = checks['E203 RTL integration']['tasks']
    if tasks != checks['E203 netlist integration']['tasks']:
        raise RuntimeError('RTL/netlist performance differs')
    if [(t['task'], t['outputs']) for t in tasks] != [
            (t['task'], t['outputs']) for t in baseline['soc_tasks']]:
        raise RuntimeError('Task count or output count changed')
    before = baseline['performance']['total_cycles']
    after = sum(task['cycles'] for task in tasks)
    # At least 2x over v3 for the selected eight-lane plus packing optimization.
    if after * 2 > before:
        raise RuntimeError('Frontend performance regression: less than 2x SoC speedup')
    hz = current['performance']['target_clock_hz']
    if hz != baseline['performance']['target_clock_hz']:
        raise RuntimeError('Nominal clock changed')
    return {
        'baseline_git_commit': baseline['git_commit'],
        'workload_timing_contract_verified': True,
        'bus_implementation_changed': False,
        'transport_packing_changed': True,
        'packed_transport_lossless_verified': True,
        'packed_manifest_sha256': hashlib.sha256((ROOT/'output/vectors/packed-manifest.json').read_bytes()).hexdigest(),
        'second_version_git_commit': second['git_commit'],
        'speedup_over_second_version': second['performance']['total_cycles']/after,
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
        'resources': {'mac_lanes_before': 4, 'mac_lanes_after': 8,
                      'internal_sram_bytes_before': 53248, 'internal_sram_bytes_after': 53248,
                      'compute_fifo_payload_register_bits': 640,
                      'bias_prefetch_register_bits': 256,
                      'sram_macros_before': 8, 'sram_macros_after': 20,
                      'dma_output_hold_bits': 64,
                      'generic_compute_core_cells_before': baseline['generic_synthesis']['accelerator']['num_cells'],
                      'generic_compute_core_cells_after': current['generic_synthesis']['accelerator']['num_cells'],
                      'generic_dma_engine_cells_after': current['generic_synthesis']['dma_engine']['num_cells'],
                      'generic_bus_cells_after': current['generic_synthesis']['bus']['num_cells']},
        'note': 'Same canonical tensors, shared SRAM, CPU wiring, bus, numeric contract and timing boundaries. X/W transport changes from sign-extended words to lossless packed pairs; both external loading and DMA remain timed. The exact testbench delta is checked, and packed files are verified against canonical vectors. Optional profile reads occur after timing. Generic cell counts are not physical area or power; compute-core-only counts exclude the DMA engine and must not be used as total accelerator area.'
    }


def main():
    current = json.loads((ROOT / 'docs/design-validation.json').read_text())
    result = compare(current)
    (ROOT / 'docs/performance-comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    print('Verified SoC speedup: %.4fx; cycle reduction: %.2f%%' %
          (result['soc_speedup'], result['cycle_reduction_percent']))


if __name__ == '__main__':
    main()
