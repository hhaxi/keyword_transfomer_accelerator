"""Numeric invariants and independent arithmetic vectors for encoder RTL."""
import json
import math
import random
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'model'))
import numpy as np
from encoder_numeric import softmax,exp_negative,layernorm,dot


class EncoderTests(unittest.TestCase):
    def test_uniform_and_dominant(self):
        p=softmax(np.zeros((1,99),dtype=np.int64))
        np.testing.assert_array_equal(p,np.full((1,99),(1<<24)//99))
        s=np.full((1,99),-16*65536,dtype=np.int64);s[0,7]=0
        p=softmax(s);self.assertEqual(int(p.sum()),1<<24);self.assertEqual(p[0,7],1<<24)
        np.testing.assert_array_equal(softmax(s+12345),p)

    def test_exp_accuracy(self):
        d=np.arange(0,16*65536+1,31,dtype=np.int64)
        actual=exp_negative(d)/(1<<24);reference=np.exp(-d/65536.)
        self.assertLess(float(np.max(np.abs(actual-reference))),.00002)
        self.assertTrue(np.all(actual[:-1]>=actual[1:]))

    def test_constant_layernorm(self):
        beta=np.arange(64,dtype=np.int64)-32
        for value in [0,-2**31,2**31-1,654321]:
            np.testing.assert_array_equal(layernorm(np.full((1,64),value),np.full(64,65536),beta)[0],beta)

    def test_wide_accumulator(self):
        a=np.full((1,64),2**31-1,dtype=np.int64);b=np.full((64,1),2**31-1,dtype=np.int64)
        self.assertEqual(int(dot(a,b)[0,0]),2**31-1)
        self.assertEqual(int(dot(-a,b)[0,0]),-2**31)
        b[::2]*=-1;self.assertEqual(int(dot(a,b)[0,0]),0)


def vectors():
    out=ROOT/'output/encoder-math';out.mkdir(exist_ok=True)
    rng=random.Random(20399)
    divisions=[(0,1),(2**64-1,1),(2**64-1,2**32-1),(2**48,99*2**24),(2**36,65)]
    divisions += [(rng.randrange(2**64),rng.randrange(1,2**32)) for _ in range(1024)]
    squares=[0,1,2,3,4,4295,2**64-1]+[rng.randrange(2**64) for _ in range(1024)]
    deltas=list(range(0,16*65536+1,31))+[0,1,16*65536-1,16*65536,2**32-1]+[rng.randrange(2**32) for _ in range(1024)]
    (out/'divide.hex').write_text(''.join('%016x%08x%016x\n'%(a,b,a//b) for a,b in divisions))
    (out/'sqrt.hex').write_text(''.join('%016x%08x\n'%(a,math.isqrt(a)) for a in squares))
    (out/'exp.hex').write_text(''.join('%016x%08x\n'%(d,int(exp_negative(d))) for d in deltas))
    (out/'math_size.vh').write_text('`define DIV_CASES %d\n`define SQ_CASES %d\n`define EXP_CASES %d\n'%(len(divisions),len(squares),len(deltas)))
    print('Encoder arithmetic vectors:',len(divisions),len(squares),len(deltas),flush=True)


if __name__=='__main__':vectors();unittest.main()
