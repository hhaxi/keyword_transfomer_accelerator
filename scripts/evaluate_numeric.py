"""Evaluate frozen numeric model on an arbitrary manifest (including future 600-sample set).

Manifest JSON is a list of {"layer": 0..11, "npz": "relative/path.npz"} records.
Each NPZ contains floating x, w, b, y. All layers must have the same number of tasks.
"""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'model'))
from numeric import encode,decode,linear

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();entries=json.loads(a.manifest.read_text())
    cfg=json.loads((ROOT/'model/format.json').read_text())['layers']
    sse=np.zeros(12);energy=np.zeros(12);elements=np.zeros(12,dtype=np.int64);tasks=np.zeros(12,dtype=np.int64)
    for item in entries:
        li=int(item['layer'])
        if li<0 or li>11:raise ValueError('Layer out of range')
        with np.load(a.manifest.parent/item['npz'],allow_pickle=False) as data:
            xe,we=cfg[li]['x_exponent'],cfg[li]['w_exponent']
            y=linear(encode(data['x'],xe),encode(data['w'],we),encode(data['b'],xe+we,32))
            decoded=decode(y,xe,we);ref=data['y'].astype(np.float64)
            if ref.shape!=(99,256) or not np.isfinite(ref).all():raise ValueError('Invalid reference')
            sse[li]+=np.sum((decoded-ref)**2);energy[li]+=np.sum(ref**2)
            elements[li]+=ref.size;tasks[li]+=1
    if min(tasks)==0 or len(set(tasks.tolist()))!=1:raise ValueError('All 12 layers require equal nonzero sample counts')
    errors=np.sqrt(sse/elements)/np.maximum(np.sqrt(energy/elements),1e-8)
    result=dict(samples_per_layer=tasks.tolist(),layer_nrmse=errors.tolist(),maximum_layer_nrmse=float(max(errors)),
                threshold=.03,passed=bool(max(errors)<=.03),format='model/format.json')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    if not result['passed']:raise SystemExit(1)

if __name__=='__main__':main()
