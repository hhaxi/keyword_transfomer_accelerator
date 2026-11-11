#!/usr/bin/env python3
"""Independent exact W16 decoder stimulus and Icarus regression.

The source defaults to the frozen q128 baseline, then falls back to this case's
vectors when used from an extracted delivery. Generated files remain under tests.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess

CASE = Path(__file__).resolve().parents[1]

def source_w16(word: int) -> int:
    value = word - 0x100000000 if word & 0x80000000 else word
    assert -32768 <= value <= 32767, f'source is not signed W16: {word:08x}'
    return value

def signed_width(value: int) -> int:
    return next(width for width in range(1, 17)
                if -(1 << (width - 1)) <= value < (1 << (width - 1)))

def compress(values: list[int], forced_width: int | None = None) -> tuple[list[int], list[int]]:
    assert len(values) == 16384
    widths = [forced_width or max(map(signed_width, values[c*64:(c+1)*64]))
              for c in range(256)]
    words = [sum((widths[c+i]-1) << (4*i) for i in range(8))
             for c in range(0, 256, 8)]
    # Independent scalar walk of adjacent columns, then adjacent K values.
    # There is no alignment between quads, even when column widths differ.
    reservoir = bits = 0
    expected = []
    for col in range(0, 256, 2):
        for k in range(0, 64, 2):
            quad = 0
            for lane, (c, row) in enumerate(((col, k), (col, k+1),
                                            (col+1, k), (col+1, k+1))):
                value, width = values[c*64+row], widths[c]
                assert -(1 << (width-1)) <= value < (1 << (width-1))
                quad |= (value & 0xffff) << (lane*16)
                reservoir |= (value & ((1 << width)-1)) << bits
                bits += width
                while bits >= 32:
                    words.append(reservoir & 0xffffffff)
                    reservoir >>= 32
                    bits -= 32
            expected.append(quad)
    assert bits == 0 and reservoir == 0
    assert len(expected) == 4096
    assert len(words) == 32 + 2*sum(widths)
    return words, expected

def write_hex(path: Path, words: list[int], digits: int = 8) -> None:
    path.write_text(''.join(f'{word:0{digits}x}\n' for word in words), encoding='ascii')

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iverilog', default=shutil.which('iverilog') or 'D:/softwares/iverilog/bin/iverilog.exe')
    parser.add_argument('--vvp', default=shutil.which('vvp') or 'D:/softwares/iverilog/bin/vvp.exe')
    parser.add_argument('--vectors', type=Path)
    parser.add_argument('--synthetic-only', action='store_true')
    parser.add_argument('--legacy-red', action='store_true',
                        help='adapt the original one-pair RTL to prove the quad test fails')
    args = parser.parse_args()
    generated = CASE / 'tests/decoder_generated'
    generated.mkdir(parents=True, exist_ok=True)
    sim = generated / 'decoder.vvp'
    rtl = CASE / 'rtl/kwt_weight_unpack.sv'
    if args.legacy_red:
        legacy = generated / 'legacy_decoder.sv'
        original = CASE.parents[1] / 'q128_low_power_combo/case/rtl/kwt_weight_unpack.sv'
        legacy.write_text(original.read_text().replace('module kwt_weight_unpack (',
                                                       'module legacy_weight_unpack ('))
        rtl = generated / 'legacy_adapter.sv'
        rtl.write_text('''`timescale 1ns/1ps
module kwt_weight_unpack(input clk,rst_n,clear,in_valid,x_mode,
output in_ready,input [31:0] in_word,output out_valid,input out_ready,
output [63:0] out_quad,output [11:0] out_index,output metadata_valid,
output [13:0] expected_words,output done,fault,input [3:0] x_query_tile,
output [8:0] x_query_words,output [67:0] out_residual);
assign x_query_words=0;assign out_residual=0;
wire [31:0] out_pair; wire [12:0] pair_index;
assign out_quad={32'b0,out_pair}; assign out_index=pair_index[11:0];
legacy_weight_unpack old(.clk(clk),.rst_n(rst_n),.clear(clear),.in_valid(in_valid),
.in_ready(in_ready),.in_word(in_word),.out_valid(out_valid),.out_ready(out_ready),
.out_pair(out_pair),.out_index(pair_index),.metadata_valid(metadata_valid),
.expected_words(expected_words),.done(done),.fault(fault)); endmodule
''')
        extra_sources = [str(legacy)]
    else:
        extra_sources = []
    subprocess.run([args.iverilog, '-g2012', '-Wall', '-s', 'decoder_tb', '-o', str(sim),
                    str(CASE / 'tests/decoder_tb.sv'), str(rtl)] + extra_sources, check=True)
    rng = random.Random(0x57443136)
    datasets: list[tuple[str, list[int], int | None, Path | None]] = []
    for width in range(1, 17):
        low, high = -(1 << (width-1)), (1 << (width-1))-1
        values = [([low, high, -1, 0][k % 4] if k < 4 else rng.randint(low, high))
                  for col in range(256) for k in range(64)]
        datasets.append((f'width_{width:02d}', values, width, None))
    mixed = []
    for col in range(256):
        width = col % 16 + 1
        low, high = -(1 << (width-1)), (1 << (width-1))-1
        mixed.extend([low, high, -1, 0] + [rng.randint(low, high) for _ in range(60)])
    datasets.append(('mixed_widths', mixed, None, None))
    unequal = []
    for col in range(256):
        width = 1 if col % 2 == 0 else 16
        low, high = -(1 << (width-1)), (1 << (width-1))-1
        unequal.extend([low, high, -1, 0] + [rng.randint(low, high) for _ in range(60)])
    datasets.append(('unequal_01_16', unequal, None, None))
    if not args.synthetic_only:
        frozen = CASE.parents[1] / 'q128_ppa/tmp/cases/baseline/vectors'
        vector_dir = args.vectors or (frozen if frozen.exists() else CASE / 'vectors')
        for task in range(12):
            path = vector_dir / f'task_{task:02d}' / 'w.hex'
            values = [source_w16(int(line, 16)) for line in path.read_text().splitlines() if line.strip()]
            datasets.append((f'task_{task:02d}', values, None, path))
    total = 0
    results = []
    logs = []
    for ordinal, (name, values, width, source) in enumerate(datasets):
        compressed, expected = compress(values, width)
        if source and source.with_name('w_packed.hex').exists():
            packed = [int(line, 16) for line in source.with_name('w_packed.hex').read_text().splitlines() if line.strip()]
            # The frozen reference is column-major pair order. Reorder it
            # independently, and compare every original halfword to the quad.
            reordered = [packed[c*32+k] | (packed[(c+1)*32+k] << 32)
                         for c in range(0, 256, 2) for k in range(32)]
            assert reordered == expected, f'original w_packed order mismatch: {source}'
        stream_path = generated / f'{name}_compressed.hex'
        expected_path = generated / f'{name}_expected.hex'
        write_hex(stream_path, compressed)
        write_hex(expected_path, expected, 16)
        cmd = [args.vvp, sim.name, f'+INPUT={stream_path.name}',
               f'+EXPECTED={expected_path.name}', f'+COUNT={len(compressed)}',
               f'+SEED={0x12345000 + ordinal}', f'+NAME={name}']
        # Abort incomplete metadata, clear buffered output during a stall,
        # and asynchronously reset immediately before the last output quads.
        if name == 'mixed_widths':
            cmd += ['+RESTARTS=1']
        completed = subprocess.run(cmd, cwd=generated, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        logs.append(completed.stdout)
        if args.legacy_red:
            (generated / 'legacy_red.log').write_text(completed.stdout)
            assert completed.returncode and 'quad=0 expected=' in completed.stdout, completed.stdout
            print('DECODER_LEGACY_RED_CONFIRMED ' + completed.stdout.strip())
            return
        if completed.returncode:
            print(completed.stdout, end='')
            completed.check_returncode()
        selected = [line for line in completed.stdout.splitlines() if line.startswith('DECODER_')]
        assert len(selected) == 2, f'missing pass markers: {name}'
        print('\n'.join(selected))
        result = dict(name=name, compressed_words=len(compressed), signed_values=len(values),
                      quad_words=len(expected), pass_markers=selected)
        if source:
            result['original_w16_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
        results.append(result)
        total += len(values)
    summary = dict(datasets=len(datasets), signed_values=total,
                   actual_values=196608 if not args.synthetic_only else 0,
                   rtl_sha256=hashlib.sha256((CASE / 'rtl/kwt_weight_unpack.sv').read_bytes()).hexdigest(),
                   results=results)
    (generated / 'results.json').write_text(json.dumps(summary, indent=2) + '\n')
    (generated / 'simulator.log').write_text(''.join(logs))
    print(f'DECODER_REGRESSION_PASS datasets={len(datasets)} signed_values={total} actual_values={summary["actual_values"]}')

if __name__ == '__main__':
    main()
