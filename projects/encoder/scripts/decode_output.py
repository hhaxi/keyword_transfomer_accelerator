"""Decode 25344 sign-extended 40-bit results stored as one 64-bit hex word per line."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'model'))
from numeric import decode,nrmse

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path);p.add_argument('--layer',type=int,required=True,choices=range(12))
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--reference',type=Path,help='Optional NPZ containing floating y[99,256]')
    p.add_argument('--ffn',action='store_true',help='Decode optional full FFN output [99,64] with ffn-format.json')
    a=p.parse_args();values=[]
    cols=64 if a.ffn else 256
    for line in a.input.read_text().splitlines():
        line=line.strip()
        if not line:continue
        if len(line)!=16 or any(c not in '0123456789abcdefABCDEF' for c in line):raise ValueError('Expected 16 hex digits per output')
        value=int(line,16)
        if value>=2**63:value-=2**64
        if not -2**39<=value<2**39:raise ValueError('Output is not a sign-extended 40-bit result')
        values.append(value)
    if len(values)!=99*cols:raise ValueError('Wrong result count for selected mode')
    cfg=json.loads((ROOT/('model/ffn-format.json' if a.ffn else 'model/format.json')).read_text())['layers'][a.layer]
    exponent=cfg['output_exponent'] if a.ffn else cfg['x_exponent']+cfg['w_exponent']
    result=decode(np.asarray(values,dtype=np.int64).reshape(99,cols),exponent,0)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('wb') as f:np.save(f,result,allow_pickle=False)
    summary={'layer':a.layer,'finite':bool(np.isfinite(result).all()),'shape':list(result.shape)}
    if a.reference:
        with np.load(a.reference,allow_pickle=False) as ref:
            if ref['y'].shape!=(99,cols):raise ValueError('Reference shape mismatch')
            summary['nrmse']=nrmse(result,ref['y'])
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
