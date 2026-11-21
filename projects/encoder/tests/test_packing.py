"""Transport format invariants, independent of accelerator arithmetic."""
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from pack_vectors import pack


class PackingTests(unittest.TestCase):
    def test_all_signed_values_round_trip_and_order(self):
        values = [value & 0xffffffff for value in range(-32768, 32768)]
        words = pack(values)
        unpacked = []
        for word in words:
            for shift in (0, 16):
                value = (word >> shift) & 0xffff
                unpacked.append(value if value < 32768 else value | 0xffff0000)
        self.assertEqual(unpacked, values)
        self.assertEqual(pack([0xffff8000, 0x7fff, 0xffffffff, 0]), [0x7fff8000, 0x0000ffff])

    def test_reject_truncation_and_odd_length(self):
        for values in ([1], [0x8000, 0], [0x10000, 0], [-1, 0]):
            with self.assertRaises(ValueError):
                pack(values)

    def test_real_vectors_match_canonical_manifest(self):
        base = ROOT / 'output/vectors'
        manifest = json.loads((base / 'manifest.json').read_text())
        for name, digest in manifest.items():
            self.assertEqual(hashlib.sha256((base / name).read_bytes()).hexdigest(), digest)
        tasks = sorted(base.glob('task_*'))
        self.assertEqual(len(tasks), 12)
        for task in tasks:
            for name, count in [('x', 6336), ('w', 16384)]:
                values = [int(v, 16) for v in (task / (name + '.hex')).read_text().split()]
                actual = [int(v, 16) for v in (task / (name + '_packed.hex')).read_text().split()]
                self.assertEqual(len(values), count)
                self.assertEqual(actual, pack(values))


if __name__ == '__main__':
    unittest.main()
