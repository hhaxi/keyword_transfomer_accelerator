"""Losslessly pack consecutive signed int16 X/W elements into 32-bit bus words.

Canonical x.hex/w.hex and their manifest stay unchanged for numerical provenance.
The first element occupies bits 15:0, the second bits 31:16; no rescaling occurs.
"""
import argparse
import hashlib
import json
from pathlib import Path


def pack(values):
    if len(values) % 2:
        raise ValueError('Packed buffers require an even number of elements')
    for value in values:
        low = value & 0xffff
        extended = low if low < 0x8000 else low | 0xffff0000
        if value != extended:
            raise ValueError('Input is not a sign-extended int16 word')
    return [(values[i] & 0xffff) | ((values[i+1] & 0xffff) << 16)
            for i in range(0, len(values), 2)]


def pack_directory(directory):
    records = {}
    for name, count in [('x', 6336), ('w', 16384)]:
        source = directory / (name + '.hex')
        values = [int(line, 16) for line in source.read_text().split()]
        if len(values) != count:
            raise ValueError('Unexpected element count: ' + str(source))
        words = pack(values)
        target = directory / (name + '_packed.hex')
        target.write_text(''.join('%08x\n' % word for word in words))
        records[target.name] = {'words': len(words),
            'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    return records


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory', type=Path, nargs='?',
                   default=Path(__file__).resolve().parents[1] / 'output/vectors')
    args = p.parse_args()
    tasks = sorted(args.directory.glob('task_*'))
    if not tasks:
        raise ValueError('No task directories')
    manifest = {task.name: pack_directory(task) for task in tasks}
    (args.directory / 'packed-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Packed %d tasks losslessly' % len(tasks))


if __name__ == '__main__':
    main()
