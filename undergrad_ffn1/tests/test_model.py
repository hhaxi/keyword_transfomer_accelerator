import sys,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'model'))
from software_model import parameters,evaluate
from numeric import linear

def signed(text,bits):
    v=int(text,16);return v-(1<<bits) if v&(1<<(bits-1)) else v

class ModelTest(unittest.TestCase):
    def test_all_twelve_parameter_sets_and_vectors(self):
        for i in range(12):
            p=ROOT/'vectors'/f'task_{i:02d}';cfg,w,b=parameters(i)
            raww=np.array([signed(v,32) for v in (p/'w.hex').read_text().splitlines()]).reshape(256,64).T
            np.testing.assert_array_equal(w,raww)
            np.testing.assert_array_equal(b,[signed(v,32) for v in (p/'b.hex').read_text().splitlines()])
            x=np.array([signed(v,32) for v in (p/'x.hex').read_text().splitlines()]).reshape(99,64)
            expected=np.array([signed(v,64) for v in (p/'expected.hex').read_text().splitlines()],dtype=np.int64).reshape(99,256)
            np.testing.assert_array_equal(linear(x,w,b),expected)
            actual,_=evaluate(np.ldexp(x.astype(float),cfg['x_exponent']),i)
            np.testing.assert_array_equal(actual,expected)

if __name__=='__main__':unittest.main()
