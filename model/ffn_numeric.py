"""Full FFN integer contract: frozen FFN1, interpolated GELU, 256-term FFN2."""
import math
import numpy as np
from numeric import linear

# GELU(x) = max(x,0) - h(abs(x)), h(a)=a*Phi(-a).
# Samples at 1/32 from 0 to 8, Q16, ties-to-even. Fixed mathematical table;
# independent of weights or evaluation data. Tail correction is zero beyond 8.
GELU_TABLE = np.array([round((i/32.)*.5*math.erfc((i/32.)/math.sqrt(2))*65536)
                       for i in range(257)], dtype=np.int64)


def rshift_even(values, shift):
    if not 0 <= shift <= 31:
        raise ValueError('Right shift must be in [0,31]')
    values = np.asarray(values, dtype=np.int64)
    if shift == 0:
        return values.copy()
    magnitude = np.abs(values)
    q, rem = magnitude >> shift, magnitude & ((1 << shift)-1)
    q += ((rem > (1 << (shift-1))) | ((rem == (1 << (shift-1))) & ((q & 1) != 0)))
    return np.where(values < 0, -q, q)


def gelu(values, input_shift, output_shift):
    values = np.asarray(values, dtype=np.int64)
    if np.any(values < -(1 << 39)) or np.any(values >= (1 << 39)):
        raise ValueError('GELU input outside int40')
    z = rshift_even(values, input_shift)
    a = np.abs(z)
    index = np.minimum(a >> 11, 255)
    frac = a & 2047
    # Arithmetic floor division matches signed >>> in RTL.
    corr = GELU_TABLE[index] + ((GELU_TABLE[index+1]-GELU_TABLE[index])*frac >> 11)
    corr = np.where(a >= 8*65536, 0, corr)
    raw = rshift_even(np.maximum(z, 0)-corr, output_shift)
    return np.clip(raw, -32768, 32767), int(np.sum((raw < -32768) | (raw > 32767)))


def second_linear(g, w, b):
    g, w, b = [np.asarray(v, dtype=np.int64) for v in (g, w, b)]
    if g.shape != (99,256) or w.shape != (256,64) or b.shape != (64,):
        raise ValueError('Expected G[99,256], W2[256,64], b2[64]')
    for v in (g,w):
        if np.any(v < -32768) or np.any(v > 32767):
            raise ValueError('Operand outside int16')
    if np.any(b < -(1 << 31)) or np.any(b >= (1 << 31)):
        raise ValueError('Bias outside int32')
    # 256 products + int32 bias have magnitude <2**39, so int40 is exact.
    return g @ w + b


def ffn(x,w,b,w2,b2,input_shift,output_shift):
    z=linear(x,w,b)
    g,saturated=gelu(z,input_shift,output_shift)
    return second_linear(g,w2,b2),g,saturated
