"""Independent X residual transport and shared-decoder focused regression."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess

CASE = Path(__file__).resolve().parents[1]


def tile_order(tail):
    return [12, 1, 0, 3, 2, 5, 4, 7, 6, 9, 8, 11, 10] if tail else list(range(13))


def signed_source(path):
    vals = [int(s, 16) for s in path.read_text().split()]
    vals = [v - 2**32 if v >= 2**31 else v for v in vals]
    assert len(vals) == 6336 and all(-32768 <= v <= 32767 for v in vals)
    return vals


def x_stimulus(values, tail):
    assert len(values) == 6336
    residual = [v if r % 8 == 0 else v - values[(r-1)*64+k]
                for r in range(99) for k, v in enumerate(values[r*64:(r+1)*64])]
    widths = [next(w for w in range(1, 18)
                   if all(-(1 << (w-1)) <= v < (1 << (w-1)) for v in residual[r*64:(r+1)*64]))
              for r in range(99)]
    assert all(widths[r] <= 16 for r in range(0, 99, 8))
    header = sum((w-1) << (r*5) for r, w in enumerate(widths)) | (tail << 495) | (0x5844 << 496)
    words = [(header >> (i*32)) & 0xffffffff for i in range(16)]
    tags, quads = [], []
    bits = data = 0
    for tile in tile_order(tail):
        for local in range(0, min(8, 99-tile*8), 2):
            row = tile*8+local
            for k in range(0, 64, 2):
                quad = 0
                for lane, (r, col) in enumerate(((row, k), (row, k+1), (row+1, k), (row+1, k+1))):
                    v = residual[r*64+col] if r < 99 else 0
                    quad |= (v & 0x1ffff) << (17*lane)
                    if r < 99:
                        data |= (v & ((1 << widths[r])-1)) << bits
                        bits += widths[r]
                        while bits >= 32:
                            words.append(data & 0xffffffff)
                            data >>= 32
                            bits -= 32
                tags.append((row//2)*32+k//2)
                quads.append(quad)
        assert bits == 0
    assert len(words) == 16+2*sum(widths) and len(quads) == 1600
    tile_words = [2*sum(widths[t*8:min(t*8+8, 99)]) for t in range(16)]
    return words, quads, tags, tile_words


def datasets():
    rng = random.Random(0x5844)
    yield 'extrema', [(-32768 if (r+k) % 2 else 32767) for r in range(99) for k in range(64)], None
    yield 'zeros', [0]*6336, None
    yield 'mixed', [max(-32768, min(32767, ((r//8)*37+k*19)+(r%8)*rng.randint(-200, 200)))
                    for r in range(99) for k in range(64)], None
    vectors = CASE.parents[1] / 'q128_ppa/tmp/cases/baseline/vectors'
    if not vectors.exists():
        vectors = CASE / 'vectors'
    for t in range(12):
        p = vectors / f'task_{t:02d}/x.hex'
        yield f'task_{t:02d}', signed_source(p), p


def write_hex(path, values, digits=8):
    path.write_text(''.join(f'{v:0{digits}x}\n' for v in values))


def run(command, out, cwd=CASE):
    env = os.environ.copy()
    env['TMP'] = env['TEMP'] = str(out.parent)
    p = subprocess.run(list(map(str, command)), cwd=cwd, env=env, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out.write_text(p.stdout)
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--legacy-red', action='store_true')
    args = ap.parse_args()
    out = CASE / 'tests/decoder_x_generated'
    out.mkdir(parents=True, exist_ok=True)
    iv = shutil.which('iverilog') or 'D:/softwares/iverilog/bin/iverilog.exe'
    vvp = shutil.which('vvp') or str(Path(iv).with_name('vvp.exe' if os.name == 'nt' else 'vvp'))
    rtl = CASE / 'rtl/kwt_weight_unpack.sv'
    extra = []
    if args.legacy_red:
        old = out / 'legacy.sv'
        old.write_text((CASE.parents[1]/'q128_dual_column/case/rtl/kwt_weight_unpack.sv').read_text()
                       .replace('module kwt_weight_unpack (', 'module legacy_unpack ('))
        rtl = out / 'legacy_adapter.sv'
        rtl.write_text('''`timescale 1ns/1ps
module kwt_weight_unpack #(parameter TAIL_FIRST=0)(input clk,rst_n,clear,x_mode,
input in_valid,output in_ready,input [31:0] in_word,output out_valid,input out_ready,
output [63:0] out_quad,output [67:0] out_residual,output [11:0] out_index,
output metadata_valid,output [13:0] expected_words,output done,fault,
input [3:0] x_query_tile,output [8:0] x_query_words);
assign out_residual=0; assign x_query_words=0;
legacy_unpack old(.clk(clk),.rst_n(rst_n),.clear(clear),.in_valid(in_valid),
.in_ready(in_ready),.in_word(in_word),.out_valid(out_valid),.out_ready(out_ready),
.out_quad(out_quad),.out_index(out_index),.metadata_valid(metadata_valid),
.expected_words(expected_words),.done(done),.fault(fault)); endmodule
''')
        extra = [old]
    records = []
    for tail in (0, 1):
        sim = out / f'x_{tail}.vvp'
        p = run([iv, '-g2012', '-s', 'decoder_x_tb', f'-Pdecoder_x_tb.TAIL_FIRST={tail}',
                 '-o', sim, CASE/'tests/decoder_x_tb.sv', rtl]+extra, out/f'compile_{tail}.log')
        if p.returncode:
            raise RuntimeError(p.stdout)
        for name, values, source in datasets():
            words, quads, tags, counts = x_stimulus(values, tail)
            prefix = out / f'{name}_{tail}'
            for suffix, data, digits in [('input', words, 8), ('quads', quads, 17),
                                         ('tags', tags, 3), ('counts', counts, 3)]:
                write_hex(prefix.with_name(prefix.name+f'_{suffix}.hex'), data, digits)
            command = [vvp, sim, f'+PREFIX={prefix}', f'+COUNT={len(words)}', f'+NAME={name}']
            p = run(command, out/f'{name}_{tail}.log')
            if args.legacy_red:
                (out/'legacy_red.log').write_text(p.stdout)
                assert p.returncode and 'metadata mismatch sent=16' in p.stdout, p.stdout
                print('X_DECODER_LEGACY_RED_CONFIRMED '+p.stdout.strip())
                return
            print(p.stdout, end='')
            p.check_returncode()
            assert 'X_DECODER_PASS' in p.stdout
            records.append(dict(name=name, tail_first=tail, words=len(words),
                                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest() if source else None))
    (out/'results.json').write_text(json.dumps(dict(datasets=len(records), records=records), indent=2)+'\n')
    print(f'X_DECODER_REGRESSION_PASS datasets={len(records)} values={6336*len(records)}')


if __name__ == '__main__':
    main()
