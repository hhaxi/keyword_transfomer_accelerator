import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'model'))
from numeric import encode,decode,linear,nrmse

class NumericTests(unittest.TestCase):
    def test_round_ties_and_saturate(self):
        np.testing.assert_array_equal(encode([.5,1.5,2.5,-.5,-1.5,-2.5,1e9,-1e9],0),
                                      [0,2,2,0,-2,-2,32767,-32768])
    def test_extreme_dot_and_bias(self):
        x=np.full((99,64),-32768);w=np.full((64,256),-32768);b=np.full(256,2**31-1)
        expected=64*(32768**2)+(2**31-1)
        np.testing.assert_array_equal(linear(x,w,b),np.full((99,256),expected))
        self.assertLess(expected,2**39)
    def test_sign_and_order(self):
        rng=np.random.RandomState(19)
        x=rng.randint(-32768,32768,(99,64));w=rng.randint(-32768,32768,(64,256));b=rng.randint(-2**31,2**31,256)
        out=linear(x,w,b)
        for r,c in [(0,0),(98,255),(37,113)]:
            self.assertEqual(out[r,c],sum(int(x[r,k])*int(w[k,c]) for k in range(64))+int(b[c]))
    def test_decode_and_zero_reference(self):
        self.assertEqual(decode([1024],-5,-5)[0],1)
        self.assertEqual(nrmse([0],[0]),0)
        with self.assertRaises(ValueError):encode([np.nan],0)

if __name__=='__main__':unittest.main()
