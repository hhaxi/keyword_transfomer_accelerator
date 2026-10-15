"""Convert arbitrary FFN1 float tensors using the frozen layer configuration.

Input NPZ: x[99,64], w[64,256], b[256], optional y[99,256] floating reference.
Does not substitute precomputed values for the hardware: expected output is a checker only.
"""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'model'))
from numeric import encode,decode,linear,nrmse

def hexfile(path,values,bits):
    path.write_text(''.join(('%0'+str(bits//4)+'x\n')%(int(v)&((1<<bits)-1)) for v in values.ravel()))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path);p.add_argument('--layer',type=int,required=True,choices=range(12))
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();data=np.load(a.input,allow_pickle=False)
    cfg=json.loads((ROOT/'model/format.json').read_text())['layers'][a.layer]
    xe,we=cfg['x_exponent'],cfg['w_exponent']
    x,w,b=encode(data['x'],xe),encode(data['w'],we),encode(data['b'],xe+we,32)
    y=linear(x,w,b);decoded=decode(y,xe,we)
    a.output.mkdir(parents=True,exist_ok=True)
    hexfile(a.output/'x.hex',x,32);hexfile(a.output/'w.hex',w.T,32);hexfile(a.output/'b.hex',b,32)
    hexfile(a.output/'expected.hex',y,64)
    np.save(a.output/'decoded.npy',decoded,allow_pickle=False)
    result={'layer':a.layer,'format':cfg,'finite':bool(np.isfinite(decoded).all())}
    if 'y' in data:result['nrmse']=nrmse(decoded,data['y'])
    (a.output/'conversion.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
