"""Export frozen full-encoder parameters, integer traces and classification evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import export_vectors as ev
np,tf,ROOT=ev.np,ev.tf,ev.ROOT
from numeric import encode
from encoder_numeric import q16,encoder_layer
from pack_vectors import pack


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split',choices=['training','validation','testing'],default='validation')
    parser.add_argument('--samples',type=int,default=0)
    parser.add_argument('--sample-list',type=Path,help='Explicit JSON array of dataset-relative audio paths (or silence)')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.samples<0:raise ValueError('--samples must be nonnegative')
    if args.split=='testing' and not args.sample_list:raise ValueError('Testing requires an explicit official/evaluation sample list')
    if args.sample_list:
        names=json.loads(args.sample_list.read_text(encoding='utf-8-sig'))
        if not isinstance(names,list) or not names or not all(isinstance(n,str) for n in names):raise ValueError('Expected a nonempty path array')
        selection=[dict(file=n) for n in names]
    else:
        selection=json.loads((ROOT/('output/vectors' if args.split=='validation' else 'output/calibration')/'numeric-report.json').read_text())['samples']
    if args.samples:selection=selection[:args.samples]
    default={'validation':'encoder-vectors','training':'encoder-calibration','testing':'encoder-testing'}[args.split]
    out=args.output or ROOT/'output'/default;out.mkdir(parents=True,exist_ok=True)
    # Re-exporting fewer samples into an existing result directory could retain
    # stale task vectors. Require a fresh destination rather than deleting data.
    previous=out/'numeric-report.json'
    if previous.exists() and json.loads(previous.read_text())['samples']!=len(selection):
        raise ValueError('Sample count changed; use --output with a fresh destination')
    sess,flags,model,tr,taps=ev.load_reference()
    if flags.prenorm or flags.heads!=1 or flags.approximate_gelu:raise ValueError('Unsupported reference architecture')
    c1=json.loads((ROOT/'model/format.json').read_text())['layers']
    c2=json.loads((ROOT/'model/ffn-format.json').read_text())['layers']
    params=[];refnodes=[];x=taps[0]
    for li,b in enumerate(tr.enc_layers):
        p={}
        for key,dense in [('wq',b.att.query_dense),('wk',b.att.key_dense),('wv',b.att.value_dense),('wo',b.att.combine_heads)]:
            p[key]=q16(dense.get_weights()[0])
        p['bo']=q16(b.att.combine_heads.get_weights()[1])
        for key,ln in [('1',b.layernorm1),('2',b.layernorm2)]:
            if ln.epsilon!=1e-6:raise ValueError('LayerNorm epsilon changed')
            g,n=ln.get_weights();p['g'+key]=q16(g);p['n'+key]=q16(n)
        w,bias=b.ffn.layers[0].get_weights();w2,b2=b.ffn.layers[2].get_weights()
        p.update(w1=encode(w,c1[li]['w_exponent']),b1=encode(bias,c1[li]['x_exponent']+c1[li]['w_exponent'],32),
                 w2=encode(w2,c2[li]['w2_exponent']),b2=encode(b2,c2[li]['output_exponent'],32))
        params.append(p)
        d=out/('layer_%02d'%li);d.mkdir(exist_ok=True)
        # Four output columns per vector, k varies before the column group.
        words=[]
        for key in ['wq','wk','wv','wo']:words.extend(p[key].reshape(64,16,4).transpose(1,0,2).ravel())
        for key in ['bo','g1','n1','g2','n2']:words.extend(p[key])
        ev.hexfile(d/'params.hex',words,32)
        ev.hexfile(d/'w1.hex',pack([int(v)&0xffffffff for v in p['w1'].T.ravel()]),32)
        ev.hexfile(d/'w2.hex',pack([int(v)&0xffffffff for v in p['w2'].T.ravel()]),32)
        ev.hexfile(d/'b1.hex',p['b1'],32);ev.hexfile(d/'b2.hex',p['b2'],32)
        ev.hexfile(d/'config.hex',[c2[li]['gelu_input_shift']|(c2[li]['gelu_output_shift']<<8),
                   ((16+c1[li]['x_exponent'])<<8)|((-c2[li]['output_exponent']-16)<<16)],32)
        x,_=b(x,training=False);refnodes.append(x)
    frozen={'version':1,'activation_and_attention_parameter_exponent':-16,'probability_exponent':-24,
            'rounding':'dense and affine RNE; mean, variance, reciprocal and normalized value floor',
            'saturation':'signed int32 at dense, residual, centered difference and affine; unchanged int16 FFN input',
            'epsilon_q32':4295,'exp2_table':'257 mathematical entries Q24, step 1/256, linear interpolation',
            'exp_cutoff_q16':16*65536,'log2e_q16':94548,'inverse_std_numerator':2**36,
            'layers':12,'tokens':99,'features':64,'attention_heads':1,'scale_source':'fixed mathematical format, no sample fitting'}
    fmt=ROOT/'model/encoder-format.json'
    if fmt.exists() and json.loads(fmt.read_text())!=frozen:raise ValueError('Frozen encoder configuration changed')
    fmt.write_text(json.dumps(frozen,indent=2)+'\n')
    flags.pick_deterministically=True;ap=ev.AudioProcessor(flags)
    lookup={Path(v['file']).relative_to(ev.upstream.DATA).as_posix():i for i,v in enumerate(ap.data_index[args.split]) if v['label']!='_silence_'}
    from kws_streaming.data.input_data import which_set
    for sample in selection:
        name=sample['file']
        if name!='silence':
            path=(ev.upstream.DATA/name).resolve()
            if ev.upstream.DATA.resolve() not in path.parents:raise ValueError('Audio path outside dataset')
        if name!='silence' and name not in lookup:
            path=ev.upstream.DATA/name
            if not path.is_file() or which_set(str(path),flags.validation_percentage,flags.testing_percentage)!=args.split:raise ValueError('Wrong split')
            lookup[name]=len(ap.data_index[args.split]);ap.data_index[args.split].append({'label':Path(name).parts[0],'file':str(path)})
    silence=next(i for i,v in enumerate(ap.data_index[args.split]) if v['label']=='_silence_')
    head=model.layers[-1];head_input=tf.compat.v1.placeholder(tf.float32,[1,64]);head_output=head(head_input)
    sse=np.zeros(12);energy=np.zeros(12);correct=0;refcorrect=0;agree=0;tasks=[];sat=0
    for si,sample in enumerate(selection):
        idx=silence if sample['file']=='silence' else lookup[sample['file']]
        audio,label=ap.get_data(1,idx,flags,0.,0.,0,args.split,0.,0.,sess=sess)
        initial,refs,original=sess.run([taps[0],refnodes,model.output],feed_dict={model.input:audio})
        if isinstance(original,list):original=original[0]
        xi=q16(initial[0])
        if si<12:
            dest=out/('task_%02d'%si);dest.mkdir(exist_ok=True);ev.hexfile(dest/'input.hex',xi,32)
        for li,p in enumerate(params):
            xi,trace=encoder_layer(xi,p,c1[li],c2[li]);sat+=trace['gelu_saturation']
            yf=refs[li][0].astype(np.float64);yd=xi/65536.
            sse[li]+=np.sum((yd-yf)**2);energy[li]+=np.sum(yf*yf)
            if si<12:
                ld=dest/('layer_%02d'%li);ld.mkdir(exist_ok=True)
                ev.hexfile(ld/'expected.hex',xi,32)
                ev.hexfile(ld/'ffn_input.hex',pack([int(v)&0xffffffff for v in trace['ffn_input'].ravel()]),32)
                ev.hexfile(ld/'ffn.hex',trace['ffn'],64)
                if si==0:
                    np.savez_compressed(ld/'trace.npz',**trace)
                    for name in ['q','k','v','score','prob','context','attention','residual1','z','residual2']:
                        ev.hexfile(ld/(name+'.hex'),trace[name],32)
        pred=int(np.argmax(sess.run(head_output,feed_dict={head_input:(xi[0:1]/65536.).astype(np.float32)})))
        refpred=int(np.argmax(original));truth=int(label[0]);correct+=pred==truth;refcorrect+=refpred==truth;agree+=pred==refpred
        tasks.append(dict(sample=sample,label=truth,predicted=pred,reference_predicted=refpred))
        if si<12:ev.hexfile(dest/'expected.hex',xi,32)
        print(args.split,si+1,'/',len(selection),'pred/ref/label',pred,refpred,truth,flush=True)
    n=len(selection);errors=np.sqrt(sse/np.maximum(energy,1e-16));drop=100*(refcorrect-correct)/n
    report=dict(split=args.split,samples=n,tasks=tasks,float_correct=refcorrect,integer_correct=correct,
                agreement=agree,accuracy_drop_percentage_points=drop,layer_nrmse=errors.tolist(),
                max_layer_nrmse=float(max(errors)),gelu_saturation_count=sat,passed=drop<=2,
                official_evaluation=False,checkpoint_tensors_verified=162,
                sample_list_sha256=hashlib.sha256(args.sample_list.read_bytes()).hexdigest() if args.sample_list else None,
                precision_gate='local <=2 percentage point classification drop; official platform acceptance not asserted')
    (out/'numeric-report.json').write_text(json.dumps(report,indent=2)+'\n')
    manifest={p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*.hex'))}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='tasks'},indent=2),flush=True)
    sess.close()
    if not report['passed']:raise RuntimeError('Encoder precision gate failed')


if __name__=='__main__':main()
