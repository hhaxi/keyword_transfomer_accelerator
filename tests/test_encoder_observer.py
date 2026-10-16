"""Check observational equivalence and pre-clip event accounting."""
import json
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'model'))
import encoder_numeric as oracle
from encoder_observer import EncoderObserver, STAGES


class ObserverTests(unittest.TestCase):
    def test_full_trace_is_unchanged(self):
        rng = np.random.RandomState(203)
        p = {k: rng.randint(-1000, 1001, (64, 64)).astype(np.int64)
             for k in ('wq', 'wk', 'wv', 'wo')}
        p.update(bo=np.zeros(64, dtype=np.int64),
                 g1=np.full(64, 65536), n1=np.zeros(64, dtype=np.int64),
                 g2=np.full(64, 65536), n2=np.zeros(64, dtype=np.int64),
                 w1=rng.randint(-100, 101, (64, 256)), b1=np.zeros(256, dtype=np.int64),
                 w2=rng.randint(-100, 101, (256, 64)), b2=np.zeros(64, dtype=np.int64))
        c1 = json.loads((ROOT/'model/format.json').read_text())['layers'][0]
        c2 = json.loads((ROOT/'model/ffn-format.json').read_text())['layers'][0]
        observed = EncoderObserver()
        original_sat = oracle.sat32
        for x in (rng.randint(-65536, 65536, (99, 64)), np.zeros((99, 64), dtype=np.int64)):
            expected, trace = oracle.encoder_layer(x, p, c1, c2)
            actual, measured, stats, cutoff = observed.run(x, p, c1, c2)
            np.testing.assert_array_equal(actual, expected)
            for key in trace:
                np.testing.assert_array_equal(trace[key], measured[key], err_msg=key)
            for stage in STAGES:
                self.assertEqual(stats[stage]['elements'], 99*(256 if stage == 'gelu' else 99 if stage == 'score' else 64))
            self.assertEqual(sum(v['saturated'] for v in stats.values()), 0)
            self.assertEqual(cutoff, 0)
        self.assertIs(oracle.sat32, original_sat)
        # Drive both affine clipping and the narrower FFN input clipping.
        p['g1'] = np.full(64, 2**31-1, dtype=np.int64)
        x = rng.randint(-65536, 65536, (99, 64))
        expected, trace = oracle.encoder_layer(x, p, c1, c2)
        actual, measured, stats, _ = observed.run(x, p, c1, c2)
        np.testing.assert_array_equal(actual, expected)
        for key in trace:
            np.testing.assert_array_equal(measured[key], trace[key])
        self.assertGreater(stats['ln1_affine']['saturated'], 0)
        self.assertGreater(stats['ffn_input']['saturated'], 0)

    def test_range_endpoints_are_not_saturation(self):
        observed = EncoderObserver()
        observed.stats = {s: dict(elements=0, saturated=0) for s in STAGES}
        observed.record('ffn_input', np.array([-32769, -32768, 32767, 32768]), 16)
        self.assertEqual(observed.stats['ffn_input'], dict(elements=4, saturated=2))

    def test_dot_normal_and_wide_clipping(self):
        for magnitude in (65536, 2**31-1):
            for sign in (-1, 1):
                observed = EncoderObserver()
                observed.stats = {s: dict(elements=0, saturated=0) for s in STAGES}
                observed.dot_count = 0
                observed.ln_active = False
                a = np.full((1, 64), sign*magnitude, dtype=np.int64)
                b = np.full((64, 1), magnitude, dtype=np.int64)
                actual = observed.module.dot(a, b, shift=1)
                np.testing.assert_array_equal(actual, oracle.dot(a, b, shift=1))
                self.assertEqual(observed.stats['q'], dict(elements=1, saturated=1))


if __name__ == '__main__':
    unittest.main()
