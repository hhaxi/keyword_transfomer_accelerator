"""Optional FFN arithmetic, GELU approximation and independent hardware vectors."""
import math
from pathlib import Path
import sys
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'model'))
from ffn_numeric import gelu,rshift_even,second_linear,GELU_TABLE


def export_gelu_vectors():
    rng=np.random.RandomState(2026)
    path=ROOT/'output/ffn-vectors/gelu-tests.txt'
    path.parent.mkdir(parents=True,exist_ok=True)
    cases=[]
    # Segment boundaries, both sides of zero, tails, signed extremes, all shifts.
    base=np.concatenate([np.arange(-8*65536,8*65536+1,127),
                         np.arange(-256,257)*2048,
                         np.array([-(1<<39),(1<<39)-1,0,-1,1])]).astype(np.int64)
    for ishift,oshift in [(0,7),(0,0),(11,7),(10,8),(31,31)]:
        values=np.unique(np.concatenate([base,rng.randint(-(1<<39),(1<<39),size=2000,dtype=np.int64)]))
        for value in values:cases.append((int(value),ishift,oshift))
    for shift in range(32):
        for sign in [-1,1]:
            for m in range(8):cases.append((sign*((2*m+1)*(1<<max(shift-1,0))),shift,7))
    with path.open('w') as out:
        for v,si,so in cases:
            result,sat=gelu([v],si,so)
            out.write('%010x %02x %02x %04x %01x\n'%(v&((1<<40)-1),si,so,int(result[0])&65535,sat))
    return len(cases)


class FFNTests(unittest.TestCase):
    def test_signed_ties_even(self):
        for shift in range(1,32):
            values=np.array([i*(1<<shift)+(1<<(shift-1)) for i in range(-8,8)],dtype=np.int64)
            np.testing.assert_array_equal(rshift_even(values,shift),np.rint(values.astype(np.float64)/(1<<shift)))
        np.testing.assert_array_equal(rshift_even([-(1<<39),(1<<39)-1],0),[-(1<<39),(1<<39)-1])

    def test_gelu_against_math_erf(self):
        q16=np.arange(-8*65536,8*65536+1,64,dtype=np.int64)
        x=q16.astype(np.float64)/65536
        reference=np.array([.5*v*(1+math.erf(v/math.sqrt(2))) for v in x])
        actual,sat=gelu(q16,0,7)
        self.assertEqual(sat,0)
        self.assertLess(float(np.max(np.abs(actual/512.-reference))),.0012)
        self.assertEqual(int(GELU_TABLE[-1]),0)

    def test_second_layer_extremes_and_order(self):
        g=np.full((99,256),-32768,dtype=np.int64)
        w=np.full((256,64),-32768,dtype=np.int64)
        b=np.full(64,(1<<31)-1,dtype=np.int64)
        result=second_linear(g,w,b)
        np.testing.assert_array_equal(result,256*(32768**2)+(1<<31)-1)
        self.assertLess(int(result.max()),1<<39)
        w[:,1]=32767;b[1]=-(1<<31)
        result=second_linear(g,w,b)
        self.assertEqual(int(result[98,1]),sum(int(g[98,k])*int(w[k,1]) for k in range(256))+int(b[1]))

    def test_saturation_and_tails(self):
        result,sat=gelu([-(1<<39),(1<<39)-1,0],0,0)
        np.testing.assert_array_equal(result,[0,32767,0]);self.assertEqual(sat,1)
        with self.assertRaises(ValueError):gelu([1<<39],0,0)


if __name__=='__main__':
    print('GELU hardware vectors:',export_gelu_vectors(),flush=True)
    unittest.main()
