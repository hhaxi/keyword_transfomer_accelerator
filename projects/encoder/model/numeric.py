"""Frozen integer arithmetic contract. No inference outputs or sample-dependent tuning."""
import numpy as np

ROWS, INNER, COLS = 99, 64, 256


def exponent_for_bound(bound):
    if not np.isfinite(bound) or bound < 0:
        raise ValueError('Invalid finite bound')
    return int(np.ceil(np.log2(max(float(bound), 1e-12) / 32767.0)))


def encode(values, exponent, bits=16):
    values = np.asarray(values, dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError('Non-finite input')
    # IEEE ties-to-even, then signed saturation. All conversion is offline.
    rounded = np.rint(np.ldexp(values, -int(exponent)))
    return np.clip(rounded, -(1 << (bits-1)), (1 << (bits-1))-1).astype(np.int64)


def linear(x, w, b):
    x, w, b = [np.asarray(a, dtype=np.int64) for a in (x, w, b)]
    if x.shape != (ROWS, INNER) or w.shape != (INNER, COLS) or b.shape != (COLS,):
        raise ValueError('Expected X[99,64], W[64,256], b[256]')
    for a in (x, w):
        if np.any(a < -32768) or np.any(a > 32767):
            raise ValueError('Operand outside signed 16-bit range')
    if np.any(b < -(1 << 31)) or np.any(b >= (1 << 31)):
        raise ValueError('Bias outside signed 32-bit range')
    # Bound < 2**37; 40-bit RTL accumulator cannot overflow on legal inputs.
    return x @ w + b


def decode(values, x_exp, w_exp):
    return np.ldexp(np.asarray(values, dtype=np.float64), int(x_exp + w_exp))


def nrmse(decoded, reference):
    ref = np.asarray(reference, dtype=np.float64)
    out = np.asarray(decoded, dtype=np.float64)
    if not np.isfinite(out).all():
        raise ValueError('Non-finite decoded output')
    return float(np.sqrt(np.mean((out-ref)**2)) / max(np.sqrt(np.mean(ref**2)), 1e-8))
