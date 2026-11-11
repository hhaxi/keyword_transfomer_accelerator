"""Lossless experimental options, separate from the published four switches."""
import itertools,json
from pathlib import Path

DEFAULT=dict(engine='flat',fuse=False,product_pipe=False,packed40=False,
             wait_mode=0,poll_pause=64,dma_burst=1,host_burst=0)
ENGINES={'flat':(1,8,2),'tile16':(1,8,2),'dual32':(2,8,2),'os4x4':(4,4,1)}

def read(root):
    p=Path(root)/'config/optional.json';data=json.loads(p.read_text()) if p.exists() else {}
    if set(data)-set(DEFAULT):raise ValueError('Unknown optional flag')
    result=dict(DEFAULT,**data)
    if result['engine'] not in ENGINES:raise ValueError('Unsupported engine')
    for name in ('fuse','product_pipe','packed40'):
        if type(result[name]) is not bool:raise ValueError('Expected bool '+name)
    if result['engine']=='flat' and (result['fuse'] or result['product_pipe']):raise ValueError('Fusion/pipeline requires tile16/dual32/os4x4 engine')
    for name,allowed in [('wait_mode',(0,1,2)),('dma_burst',(1,2,4,8)),('host_burst',(0,2,4))]:
        if type(result[name]) is not int or result[name] not in allowed:raise ValueError('Invalid '+name)
    if type(result['poll_pause']) is not int or not 0<=result['poll_pause']<=4096:raise ValueError('Invalid polling pause')
    return result

def configure(root,values=None):
    root=Path(root)
    if values is not None:(root/'config/optional.json').write_text(json.dumps(values,indent=2)+'\n')
    opt=read(root);r,c,k=ENGINES[opt['engine']]
    fields=dict(USE_TILE=int(opt['engine']!='flat'),TILE_ROWS=r,TILE_COLS=c,TILE_KPAR=k,
                FUSE=int(opt['fuse']),PRODUCT_PIPE=int(opt['product_pipe']),PACKED40=int(opt['packed40']),
                IRQ=int(opt['wait_mode']==2),DMA_BURST=opt['dma_burst'],HOST_BURST=opt['host_burst'],
                OUTPUT_WORDS=31680 if opt['packed40'] else 50688,
                EXPECTED_MAC_CYCLES=((99+r-1)//r)*(256//c)*(64//k))
    (root/'rtl/kwt_optional.vh').write_bytes(('// Lossless experiment configuration.\n'+''.join('`define KWT_%s %d\n'%(name,value) for name,value in fields.items())).encode())
    (root/'config/optional_config.tcl').write_bytes(('set optional_engine '+opt['engine']+'\n'+''.join('set optional_%s %d\n'%(name.lower(),value) for name,value in fields.items())).encode())
    return opt

def inventory(opt,small_bias=True,scope='accelerator'):
    rows=ENGINES[opt['engine']][0]
    return {name:count for name,count in dict(RAMSP128X16=4*rows+4*int(small_bias),
        RAMSP1024X16=16+2*int(not small_bias),RAMSP4096X16=80*int(scope=='soc')).items() if count}

def matrix(arbitration=False):
    result=[]
    for engine,fuse,pipe,packed,wait,bias in itertools.product(ENGINES,(False,True),(False,True),(False,True),(0,1,2),(False,True)):
        if engine=='flat' and (fuse or pipe):continue
        for dma,host in (itertools.product((1,4,8),(0,2,4)) if arbitration else [(1,0)]):
            opt=dict(DEFAULT,engine=engine,fuse=fuse,product_pipe=pipe,packed40=packed,wait_mode=wait,dma_burst=dma,host_burst=host)
            name='%s_f%d_p%d_o%d_w%d_b%d_d%d_h%d'%(engine,fuse,pipe,packed,wait,bias,dma,host)
            result.append(dict(name=name,optional=opt,small_bias=bias))
    return result

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--arbitration',action='store_true');a=ap.parse_args()
    print(json.dumps(matrix(a.arbitration),indent=2))
