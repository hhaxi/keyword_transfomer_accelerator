"""Freeze optional FFN format from checkpoint bounds; validate original float FFN."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import export_vectors as ev
np,tf,ROOT=ev.np,ev.tf,ev.ROOT
from numeric import encode,decode,exponent_for_bound,nrmse
from ffn_numeric import ffn
from pack_vectors import pack


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--split',choices=['training','validation'],default='validation')
    args=p.parse_args()
    original=ROOT/('output/vectors' if args.split=='validation' else 'output/calibration')
    selection=json.loads((original/'numeric-report.json').read_text())
    out=ROOT/('output/ffn-vectors' if args.split=='validation' else 'output/ffn-calibration')
    out.mkdir(parents=True,exist_ok=True)
    sess,flags,model,tr,taps=ev.load_reference()
    if flags.approximate_gelu:raise ValueError('Expected exact-erf reference GELU')
    cfg1=json.loads((ROOT/'model/format.json').read_text())['layers']
    cfg=[];params=[];refs=[]
    for li,block in enumerate(tr.enc_layers):
        w,b=block.ffn.layers[0].get_weights();w2,b2=block.ffn.layers[2].get_weights()
        xe,we=cfg1[li]['x_exponent'],cfg1[li]['w_exponent']
        qw,qb=encode(w,we),encode(b,xe+we,32)
        # Bound the *quantized* first-layer integer output before GELU.
        xb=min(32768,int(np.ceil(np.ldexp(cfg1[li]['x_analytic_bound'],-xe)+.5)))
        zbound=float(np.ldexp(float(np.max(xb*np.sum(np.abs(qw),axis=0)+np.abs(qb))),xe+we))
        ge=exponent_for_bound(zbound+1/65536.)
        w2e=exponent_for_bound(float(np.max(np.abs(w2))))
        ishift=-(xe+we)-16;oshift=16+ge
        if not (0<=ishift<=31 and 0<=oshift<=31):raise ValueError('Unsupported shifts')
        if np.max(np.abs(np.ldexp(b2.astype(np.float64),-ge-w2e)))>=2**31:raise ValueError('b2 overflows')
        qw2,qb2=encode(w2,w2e),encode(b2,ge+w2e,32)
        cfg.append(dict(layer=li,gelu_input_shift=ishift,gelu_output_shift=oshift,
                        gelu_exponent=ge,w2_exponent=w2e,output_exponent=ge+w2e,
                        quantized_ffn1_abs_bound=zbound,scale_source='checkpoint and analytic FFN1 bounds; no sample fitting'))
        params.append((qw,qb,qw2,qb2))
        refs.extend([block.ffn.layers[1](taps[2+2*li]),block.ffn(taps[1+2*li])])
    frozen={'version':1,'gelu':'exact-erf correction table, Q16, step 1/32, linear interpolation, |z|>=8 identity/zero',
            'rounding':'rescale nearest ties even; interpolation arithmetic floor',
            'intermediate_bits':16,'accumulator_bits':40,'output_bits':64,'layers':cfg}
    path=ROOT/'model/ffn-format.json'
    if path.exists():
        if json.loads(path.read_text())!=frozen:raise ValueError('Frozen FFN format changed')
    else:path.write_text(json.dumps(frozen,indent=2)+'\n')
    flags.pick_deterministically=True
    ap=ev.AudioProcessor(flags)
    lookup={Path(v['file']).relative_to(ev.upstream.DATA).as_posix():i for i,v in enumerate(ap.data_index[args.split]) if v['label']!='_silence_'}
    from kws_streaming.data.input_data import which_set
    for sample in selection['samples']:
        name=sample['file']
        if name!='silence' and name not in lookup:
            path=ev.upstream.DATA/name
            if not path.is_file() or which_set(str(path),flags.validation_percentage,flags.testing_percentage)!=args.split:
                raise ValueError('Sample is not in the declared split: '+name)
            lookup[name]=len(ap.data_index[args.split])
            ap.data_index[args.split].append({'label':Path(name).parts[0],'file':str(path)})
    silence=next(i for i,v in enumerate(ap.data_index[args.split]) if v['label']=='_silence_')
    sse=np.zeros(12);energy=np.zeros(12);sat=np.zeros(12,dtype=np.int64);gelu_max=np.zeros(12)
    tasks=[]
    for si,sample in enumerate(selection['samples']):
        idx=silence if sample['file']=='silence' else lookup[sample['file']];entry=ap.data_index[args.split][idx]
        file='silence' if entry['label']=='_silence_' else Path(entry['file']).relative_to(ev.upstream.DATA).as_posix()
        if file!=sample['file']:raise ValueError('Upstream sample ordering changed')
        audio,_=ap.get_data(1,idx,flags,0.,0.,0,args.split,0.,0.,sess=sess)
        values,ref=sess.run([taps,refs],feed_dict={model.input:audio})
        for li,c in enumerate(cfg):
            x=encode(values[1+2*li][0],cfg1[li]['x_exponent']);qw,qb,qw2,qb2=params[li]
            y,g,n=ffn(x,qw,qb,qw2,qb2,c['gelu_input_shift'],c['gelu_output_shift'])
            yd=np.ldexp(y.astype(np.float64),c['output_exponent']);yf=ref[2*li+1][0]
            if not np.isfinite(yd).all():raise ValueError('Nonfinite output')
            sse[li]+=np.sum((yd-yf)**2);energy[li]+=np.sum(yf.astype(np.float64)**2);sat[li]+=n
            gelu_max[li]=max(gelu_max[li],float(np.max(np.abs(np.ldexp(g.astype(np.float64),c['gelu_exponent'])-ref[2*li][0]))))
            if si==li:
                if args.split=='validation':
                    with np.load(original/('task_%02d'%li)/'reference.npz') as old:
                        np.testing.assert_array_equal(x,old['xq'])
                dest=out/('task_%02d'%li);dest.mkdir(exist_ok=True)
                for name,arr,bits in [('w2',qw2.T,32),('b2',qb2,32),('gelu',g,16),('expected',y,64)]:ev.hexfile(dest/(name+'.hex'),arr,bits)
                ev.hexfile(dest/'w2_packed.hex',pack([int(v)&0xffffffff for v in qw2.T.ravel()]),32)
                ev.hexfile(dest/'config.hex',[c['gelu_input_shift']|(c['gelu_output_shift']<<8)],32)
                tasks.append({'task':li,'layer':li,'sample':sample,'nrmse':nrmse(yd,yf)})
                np.savez_compressed(dest/'reference.npz',w2=tr.enc_layers[li].ffn.layers[2].get_weights()[0],
                                    b2=tr.enc_layers[li].ffn.layers[2].get_weights()[1],y=yf,g=ref[2*li][0])
        if (si+1)%12==0:print('FFN validated',si+1,'samples x 12 layers',flush=True)
    errors=np.sqrt(sse/len(selection['samples'])/6336)/np.maximum(np.sqrt(energy/len(selection['samples'])/6336),1e-8)
    report={'split':args.split,'samples':selection['samples'],'sample_count':len(selection['samples']),
            'layer_nrmse':errors.tolist(),'maximum_layer_nrmse':float(max(errors)),
            'gelu_max_absolute_error':gelu_max.tolist(),'gelu_saturation_counts':sat.tolist(),
            'performance_tasks':tasks,'engineering_threshold':.03,'passed':bool(max(errors)<.03 and not np.any(sat)),
            'official_metric':False,'note':'Optional full FFN engineering metric, not undergraduate mandatory FFN1 score'}
    (out/'numeric-report.json').write_text(json.dumps(report,indent=2)+'\n')
    manifest={p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob('task_*/*.hex'))}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('FFN max NRMSE',max(errors),'saturations',sum(sat),flush=True)
    if not report['passed']:raise RuntimeError('FFN engineering precision gate failed')
    sess.close()


if __name__=='__main__':main()
