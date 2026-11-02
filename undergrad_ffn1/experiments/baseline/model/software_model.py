"""Frozen FFN1 software contract and parameter/input conversion CLI.

Example: python model/software_model.py --layer 0 --input input.npy --output result.npy
Input/decoded output are floating NumPy arrays; encoded output is signed int64
containing the exact signed INT40 RTL result. No prediction/reference shortcuts.
"""
import argparse,json
from pathlib import Path
import numpy as np
from numeric import encode,linear,decode
ROOT=Path(__file__).resolve().parents[1]

def parameters(layer):
    cfg=json.loads((ROOT/'model/format.json').read_text())['layers'][layer]
    with np.load(ROOT/'model/float-parameters.npz') as a:
        w=encode(a[f'layer{layer}_w1'],cfg['w_exponent'])
        b=encode(a[f'layer{layer}_b1'],cfg['x_exponent']+cfg['w_exponent'],32)
    return cfg,w,b

def evaluate(x,layer):
    cfg,w,b=parameters(layer);q=encode(x,cfg['x_exponent']);y=linear(q,w,b)
    return y,decode(y,cfg['x_exponent'],cfg['w_exponent'])

def packed_hex(path,values):
    v=np.asarray(values,dtype=np.int64).reshape(-1)
    if len(v)%2:raise ValueError('Packed INT16 requires pairs')
    path.write_text(''.join(f'{((int(v[i+1])&65535)<<16)|(int(v[i])&65535):08x}\n' for i in range(0,len(v),2)))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--layer',type=int,required=True);ap.add_argument('--input',type=Path)
    ap.add_argument('--output',type=Path);ap.add_argument('--encoded-output',type=Path);ap.add_argument('--export',type=Path)
    a=ap.parse_args()
    if not 0<=a.layer<12:raise ValueError('Layer must be 0..11')
    cfg,w,b=parameters(a.layer)
    if a.export:
        a.export.mkdir(parents=True,exist_ok=True)
        packed_hex(a.export/'w_packed.hex',w.T)
        (a.export/'b.hex').write_text(''.join(f'{int(v)&0xffffffff:08x}\n' for v in b))
        (a.export/'format.json').write_text(json.dumps(cfg,indent=2)+'\n')
    if a.input:
        x=np.load(a.input,allow_pickle=False)
        if x.shape!=(99,64):raise ValueError('Input must have shape99x64')
        y,floating=evaluate(x,a.layer)
        if a.output:np.save(a.output,floating)
        if a.encoded_output:np.save(a.encoded_output,y)
        if a.export:packed_hex(a.export/'x_packed.hex',encode(x,cfg['x_exponent']))
        if not any((a.output,a.encoded_output,a.export)):raise ValueError('Specify output or export')
if __name__=='__main__':main()
