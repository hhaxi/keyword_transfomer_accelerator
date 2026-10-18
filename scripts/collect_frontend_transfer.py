"""Collect v3 frontend evidence without claiming fresh synthesis/netlist/PPA results."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT/'output/design'
BASE = 'ccc5e72'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    checks = {}

    def evidence(name, marker):
        path = LOG/(name+'.log')
        text = path.read_text(encoding='utf-8', errors='replace')
        require(marker in text and not re.search(r'(?i)(?:fatal:|%fatal|assertion failed)', text), name+' incomplete/failed')
        checks[path.relative_to(ROOT).as_posix()] = dict(sha256=digest(path), marker=marker)
        return text

    tests = {
        'tb_accel-run': 'ACCEL_PASS 12 parameter sets',
        'tb_dma-run': 'DMA_PASS', 'tb_ffn-run': 'FFN_PASS',
        'tb_ffn_edges-run': 'FFN_EDGES_PASS cases=3',
        'tb_result_fifo-run': 'RESULT_FIFO_PASS',
        'tb_ffn_transport-run': 'abort_drain error_drain cancellation restart',
        'tb_ffn_transport_ideal-run': 'read_streak=19872 write_streak=5',
        'tb_encoder_transfers-run': 'ENCODER_PASS layers=12 constant_edge=0 transport=1',
        'tb_encoder_stream40-run': 'ENCODER_PASS layers=12 constant_edge=0 transport=2',
        'tb_encoder_faults-run': 'ENC_FAULTS_PASS',
        'tb_dma_arbiter-run': 'ENC_ARBITER_PASS',
        'icarus-accel': 'ACCEL_PASS 1 parameter sets',
        'icarus-tb_ffn_edges': 'FFN_EDGES_PASS cases=3',
        'icarus-tb_ffn': 'FFN_PASS', 'icarus-tb_dma': 'DMA_PASS',
        'icarus-tb_result_fifo': 'RESULT_FIFO_PASS',
        'icarus-tb_ffn_transport': 'abort_drain error_drain cancellation restart',
        'icarus-tb_encoder_faults': 'ENC_FAULTS_PASS',
        'icarus-tb_dma_arbiter': 'ENC_ARBITER_PASS',
        'icarus-tb_encoder_packed40': 'ENCODER_PASS layers=1 constant_edge=0 transport=1',
        'icarus-tb_encoder_stream40': 'ENCODER_PASS layers=1 constant_edge=0 transport=2',
    }
    for name, marker in tests.items():
        evidence(name, marker)
    require(not (LOG/'encoder-lint.log').read_text().strip(), 'Strict lint failed')
    checks['output/design/encoder-lint.log'] = dict(sha256=digest(LOG/'encoder-lint.log'), marker='empty strict lint log')
    independent = {}
    for mode, top, baseline in [('linear', 'tb_soc', 271678), ('ffn', 'tb_soc_ffn', 306709)]:
        text = evidence(top+'_encoder_compat-run', 'SOC_PASS tasks=12')
        rows = re.findall(r'SOC_TASK_PASS task=(\d+) cycles=(\d+) outputs=', text)
        require([int(t) for t, c in rows] == list(range(12)), 'Independent task coverage')
        cycles = [int(c) for t, c in rows]
        require(max(cycles) <= baseline, 'Independent mode regression')
        independent[mode] = dict(cycles=cycles, baseline_cycles=baseline,
                                 cycle_reduction_percent=100*(baseline-max(cycles))/baseline)

    def soc(name, transport):
        text = evidence(name, 'ENC_SOC_')
        rows = re.findall(r'ENC_SOC_TASK_PASS task=(\d+) cycles=(\d+) baseline=0 outputs=6336 transport='+str(transport), text)
        require(rows and ('ENC_SOC_PASS tasks=' in text or 'ENC_SOC_SHARDS_PASS tasks=' in text), 'Incomplete SoC '+name)
        phases = re.findall(r'ENC_PHASE task=(\d+) layer=(\d+) op=(\d+) index=(\d+) value=(\d+)', text)
        stats = re.findall(r'ENC_LAYER_STATS task=(\d+) layer=(\d+) index=(\d+) value=(\d+)', text)
        result = []
        for task, cycles in rows:
            values = {(int(l), int(i)): int(v) for t, l, i, v in stats if t == task}
            require(len(values) == 12*8, 'Missing layer telemetry')
            for li in range(12):
                require(values[li, 3] == (23040 if li == 0 else 16704)+(0 if transport == 2 else 7920 if transport == 1 else 12672), 'Encoder DMA reads')
                require(values[li, 4] == (9504 if li == 11 else 3168), 'Encoder DMA writes')
                require(values[li, 7] == 0, 'Encoder clipping')
                for op in range(2):
                    counters = [int(v) for t, l, o, i, v in phases if t == task and int(l) == li and int(o) == op]
                    require(len(counters) == 10 and sum(counters) == values[li, op], 'Phase conservation')
            read = sum(values[li, 3] for li in range(12))
            write = sum(values[li, 4] for li in range(12))
            ffn_read, ffn_write = 12*19872, 12*(0 if transport == 2 else 7920 if transport == 1 else 12672)
            result.append(dict(task=int(task), cycles=int(cycles), encoder_dma_read32=read,
                               encoder_dma_write32=write, ffn_dma_read32=ffn_read, ffn_dma_write32=ffn_write,
                               total_dma_words32=read+write+ffn_read+ffn_write,
                               phase_cycles=[dict(layer=li, front=values[li, 0], tail=values[li, 1], ffn=values[li, 2]) for li in range(12)]))
        return result

    stream = soc('tb_encoder_soc-run', 2)
    if len(stream) != 12:
        for path in sorted(LOG.glob('tb_encoder_soc_stream_shard*-run.log')):
            stream.extend(soc(path.stem, 2))
    stream.sort(key=lambda r: r['task'])
    require([r['task'] for r in stream] == list(range(12)), 'Need 12 distinct stream SoC tasks')
    legacy = soc('tb_encoder_soc_legacy64-run', 0)[0]
    packed = soc('tb_encoder_soc_packed40-run', 1)[0]
    require(legacy['task'] == packed['task'] == 0, 'A/B input mismatch')
    require(stream[0]['cycles'] < packed['cycles'] <= legacy['cycles'], 'Transport performance regression')
    frozen = {}
    for name in ['model/format.json', 'model/ffn-format.json', 'model/encoder-format.json',
                 'model/numeric.py', 'model/ffn_numeric.py', 'model/encoder_numeric.py']:
        old = subprocess.check_output(['git', 'show', BASE+':'+name], cwd=ROOT)
        current = (ROOT/name).read_bytes()
        require(old.replace(b'\r\n', b'\n') == current.replace(b'\r\n', b'\n'), 'Frozen numeric change: '+name)
        frozen[name] = digest(ROOT/name)
    sources = [p for folder in ['rtl', 'integration', 'firmware'] for p in (ROOT/folder).glob('*') if p.is_file()]
    sources += list((ROOT/'tests').glob('*.sv'))
    vector_hashes = {p.relative_to(ROOT).as_posix(): digest(p)
                     for folder in ['output/vectors', 'output/ffn-vectors', 'output/ffn-edges', 'output/encoder-vectors']
                     for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ['.hex', '.vh', '.json']}
    report = dict(version='encoder-v3/ffn-v9', scope='Frontend RTL, E203 SoC and four-state simulation; no new netlist/PPA claim',
                  baseline_commit=subprocess.check_output(['git', 'rev-parse', BASE], cwd=ROOT, text=True).strip(),
                  independent=independent, transport_comparison=dict(legacy64=legacy, packed40=packed, fifo40=stream[0]),
                  stream_soc_tasks=stream, checks=checks, frozen_numeric_sha256=frozen,
                  source_hash_method='Captured at evidence collection; source line endings normalized to LF',
                  sources_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest() for p in sources},
                  vector_sha256=vector_hashes,
                  firmware_sha256=digest(ROOT/'output/encoder-design/firmware/encoder.bin'),
                  traffic_method='Encoder counters observed in SoC; fixed FFN read/write counts verified in real DMA transport tests and multiplied by 12 layers',
                  timing_method='Matched new hardware, firmware, input and parameters; transport flags alone differ. Historical v2 used older firmware and measured 14808628 cycles.',
                  overlap='FIFO tail runs concurrently with FFN: do not add FFN command cycles to encoder tail cycles',
                  fifo_payload_bits=160, ffn_mac_lanes=16, encoder_multiply_lanes=4, gelu_units=1,
                  pending='Encoder-to-FFN packed int16 input remains via shared SRAM; synthesis/netlist/PPA to be rerun on this revision',
                  passed=True)
    output = ROOT/'docs/frontend-transfer-validation.json'
    output.write_text(json.dumps(report, indent=2)+'\n')
    print('Frontend transfer validation PASS: 12 SoC inputs, 3 transport modes, independent modes, faults and four-state checks')
    print(json.dumps({k:v['cycles'] for k,v in report['transport_comparison'].items()}, indent=2))
    return report


if __name__ == '__main__':
    main()
