"""Observe frozen arithmetic in a private module instance; never patch the oracle."""
import importlib.util
from pathlib import Path
import numpy as np

STAGES = ('q', 'k', 'v', 'score', 'context', 'attention', 'residual1',
          'ln1_center', 'ln1_affine', 'ffn_input', 'gelu', 'residual2',
          'ln2_center', 'ln2_affine')


class EncoderObserver:
    def __init__(self):
        spec = importlib.util.spec_from_file_location(
            '_observed_encoder', Path(__file__).with_name('encoder_numeric.py'))
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        original_sat = self.module.sat32
        original_dot = self.module.dot
        original_ln = self.module.layernorm

        def sat(values):
            stage = self.stage
            if self.ln_active:
                stage = 'ln%d_%s' % (self.ln_count, 'center' if self.ln_calls % 2 == 0 else 'affine')
                self.ln_calls += 1
            self.record(stage, values, 32)
            return original_sat(values)

        def dot(a, b, bias=None, shift=16):
            self.stage = STAGES[self.dot_count]
            self.dot_count += 1
            # The oracle's exact Python-integer fallback clips internally,
            # bypassing sat32. Observe that rare path before its clipping too.
            bound = int(np.max(np.abs(a))) * int(np.max(np.abs(b))) * a.shape[-1]
            if bias is not None:
                bound += int(np.max(np.abs(bias))) * 65536
            if bound >= 2**63:
                raw = a.astype(object) @ b.astype(object)
                if bias is not None:
                    raw += np.asarray(bias, dtype=object) * 65536

                def rounded(v):
                    q, r = divmod(abs(int(v)), 1 << shift)
                    q += r > (1 << (shift - 1)) or (r == (1 << (shift - 1)) and q & 1)
                    return -q if v < 0 else q

                self.record(self.stage, np.frompyfunc(rounded, 1, 1)(raw), 32)
            result = original_dot(a, b, bias, shift)
            self.stage = 'residual1'
            return result

        def ln(x, gamma, beta):
            self.ln_count += 1
            self.ln_calls = 0
            self.ln_active = True
            try:
                return original_ln(x, gamma, beta)
            finally:
                self.ln_active = False
                self.stage = 'residual2'

        self.module.sat32 = sat
        self.module.dot = dot
        self.module.layernorm = ln

    def record(self, stage, values, bits):
        values = np.asarray(values)
        entry = self.stats[stage]
        entry['elements'] += int(values.size)
        entry['saturated'] += int(np.count_nonzero(
            (values < -(1 << (bits - 1))) | (values > (1 << (bits - 1)) - 1)))

    def run(self, x, params, first, second):
        self.stats = {s: dict(elements=0, saturated=0) for s in STAGES}
        self.dot_count = self.ln_count = 0
        self.ln_active = False
        self.stage = 'residual1'
        out, trace = self.module.encoder_layer(x, params, first, second)
        if (self.dot_count, self.ln_count) != (6, 2):
            raise RuntimeError('Frozen encoder call structure changed')
        self.record('ffn_input', self.module.rshift_even(trace['z'], 16 + first['x_exponent']), 16)
        self.stats['gelu'] = dict(elements=int(trace['gelu'].size), saturated=int(trace['gelu_saturation']))
        delta = trace['score'].max(axis=1, keepdims=True) - trace['score']
        cutoff = int(np.count_nonzero(delta >= 16 * 65536))
        return out, trace, self.stats, cutoff
