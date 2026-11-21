"""Convert one optional full FFN task with frozen formats, without model training.

Input NPZ: x[99,64], w[64,256], b[256], w2[256,64], b2[64], optional y[99,64].
"""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'model'))
from numeric import encode,nrmse
from ffn_numeric import ffn
from convert_task import hexfile
from pack_vectors import pack_directory,pack

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path);p.add_argument('--layer',type=int,required=True,choices=range(12))
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    c1=json.loads((ROOT/'model/format.json').read_text())['layers'][a.layer]
    c=json.loads((ROOT/'model/ffn-format.json').read_text())['layers'][a.layer]
    with np.load(a.input,allow_pickle=False) as data:
        x=encode(data['x'],c1['x_exponent']);w=encode(data['w'],c1['w_exponent'])
        b=encode(data['b'],c1['x_exponent']+c1['w_exponent'],32)
        w2=encode(data['w2'],c['w2_exponent']);b2=encode(data['b2'],c['output_exponent'],32)
        result,g,saturated=ffn(x,w,b,w2,b2,c['gelu_input_shift'],c['gelu_output_shift'])
        a.output.mkdir(parents=True,exist_ok=True)
        for name,value,bits in [('x',x,32),('w',w.T,32),('b',b,32),('w2',w2.T,32),('b2',b2,32),('gelu',g,16),('expected',result,64)]:
            hexfile(a.output/(name+'.hex'),value,bits)
        pack_directory(a.output)
        words=pack([int(v)&0xffffffff for v in w2.T.ravel()])
        hexfile(a.output/'w2_packed.hex',np.asarray(words,dtype=np.int64),32)
        hexfile(a.output/'config.hex',np.asarray([c['gelu_input_shift']|(c['gelu_output_shift']<<8)]),32)
        report={'layer':a.layer,'saturations':saturated,'format':c,'shape':list(result.shape)}
        if 'y' in data:
            if data['y'].shape!=(99,64):raise ValueError('Full FFN reference must be [99,64]')
            report['nrmse']=nrmse(np.ldexp(result.astype(np.float64),c['output_exponent']),data['y'])
        (a.output/'conversion.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))

if __name__=='__main__':main()
