"""Extract real PostNorm FFN1 tensors; freeze analytic scales; validate and export."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import check_model_environment as upstream

np, tf = upstream.np, upstream.tf
ROOT = upstream.ROOT
sys.path.insert(0, str(ROOT / 'model'))
from numeric import encode, decode, linear, exponent_for_bound, nrmse
from kws_streaming.data.input_data import AudioProcessor, which_set


def load_reference():
    tf.compat.v1.reset_default_graph()
    sess = tf.compat.v1.Session(config=tf.compat.v1.ConfigProto(device_count={'GPU': 0}))
    tf.compat.v1.keras.backend.set_session(sess)
    tf.compat.v1.keras.backend.set_learning_phase(0)
    parser = upstream.base_parser.base_parser()
    upstream.kws_transformer.model_parameters(parser)
    flags = parser.parse_args([])
    vars(flags).update(json.loads((upstream.MODEL / 'flags.json').read_text()))
    for key, val in dict(batch_size=1, training=False, train=0, data_dir=str(upstream.DATA), data_url='',
                         train_dir=str(upstream.MODEL), use_spec_augment=0, use_spec_cutout=0,
                         time_shift_ms=0., resample=0., volume_resample=0.,
                         background_frequency=0., background_volume=0.).items():
        setattr(flags, key, val)
    flags = upstream.model_flags.update_flags(flags)
    model = upstream.kws_transformer.model(flags)
    status = model.load_weights(str(upstream.MODEL/'best_weights'))
    status.assert_existing_objects_matched()
    status.expect_partial()
    reader = tf.train.load_checkpoint(str(upstream.MODEL/'best_weights'))
    graph = upstream.trackable_object_graph_pb2.TrackableObjectGraph()
    graph.ParseFromString(reader.get_tensor('_CHECKPOINTABLE_OBJECT_GRAPH'))
    names = {a.full_name: a.checkpoint_key for node in graph.nodes for a in node.attributes}
    for weight in model.weights:
        np.testing.assert_array_equal(sess.run(weight), reader.get_tensor(names[weight.name.rsplit(':',1)[0]]))
    transformer = next(layer for layer in model.layers if hasattr(layer, 'enc_layers'))
    features = model.layers[1].output
    x = transformer.patch_proj(features)
    x = tf.concat([transformer.class_emb, x], axis=1) + transformer.pos_emb
    taps = [x]
    for block in transformer.enc_layers:
        a, _ = block.att(x)
        z = block.layernorm1(x + block.dropout1(a, training=False))
        y = block.ffn.layers[0](z)
        taps.extend([z,y])
        x, _ = block(x, training=False)
    taps.append(x[:,0,:])
    return sess, flags, model, transformer, taps


def hexfile(path, values, bits=32):
    mask=(1<<bits)-1
    path.write_text(''.join(('{:0'+str(bits//4)+'x}\n').format(int(v)&mask) for v in np.asarray(values).ravel()))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=120)
    parser.add_argument('--split', choices=['training','validation','testing'], default='validation')
    parser.add_argument('--output',type=Path,default=ROOT/'output/vectors')
    parser.add_argument('--sample-list',type=Path,help='JSON list of paths relative to the dataset, or "silence"; must belong to the selected upstream split')
    parser.add_argument('--save-all',action='store_true',help='Save every floating task and an evaluate_numeric manifest')
    args=parser.parse_args()
    if args.samples<12: raise ValueError('At least 12 balanced samples required')
    fixed=ROOT/'model'/(args.split+'-samples.json')
    if not args.sample_list and fixed.exists() and args.samples==len(json.loads(fixed.read_text())):
        args.sample_list=fixed
    out=args.output.resolve(); out.mkdir(parents=True,exist_ok=True)
    sess,flags,model,tr,taps=load_reference()
    flags.pick_deterministically=True
    ap=AudioProcessor(flags)
    labels=(upstream.MODEL/'labels.txt').read_text().splitlines()
    # Round-robin labels, preserving upstream index ordering and unknown selection.
    buckets=[[] for _ in labels]
    for idx,sample in enumerate(ap.data_index[args.split]):
        buckets[ap.word_to_index[sample['label']]].append(idx)
    selected=[]
    if args.sample_list:
        lookup={Path(s['file']).relative_to(upstream.DATA).as_posix():i for i,s in enumerate(ap.data_index[args.split]) if s['label']!='_silence_'}
        for name in json.loads(args.sample_list.read_text(encoding='utf-8')):
            if name!='silence' and name not in lookup:
                path=upstream.DATA/name
                if not path.is_file() or which_set(str(path),flags.validation_percentage,flags.testing_percentage)!=args.split:
                    raise ValueError('Sample outside selected split: '+name)
                lookup[name]=len(ap.data_index[args.split])
                ap.data_index[args.split].append({'label':Path(name).parts[0],'file':str(path)})
            if name=='silence':selected.append(buckets[0][0])
            elif name in lookup:selected.append(lookup[name])
            else:raise ValueError('Sample is outside the selected upstream split/label index: '+str(name))
        if len(selected)<12:raise ValueError('At least 12 listed samples required')
    else:
        for n in range(args.samples):
            category=n%12; nth=n//12
            if nth>=len(buckets[category]): raise ValueError('Requested too many samples for a label')
            selected.append(buckets[category][nth])
    params=[]; config=[]
    for li,block in enumerate(tr.enc_layers):
        w,b=block.ffn.layers[0].get_weights()
        gamma,beta=block.layernorm1.get_weights()
        bound=float(np.max(np.abs(gamma)*np.sqrt(63.)+np.abs(beta)))
        xe=exponent_for_bound(bound); we=exponent_for_bound(float(np.max(np.abs(w))))
        qw=encode(w,we); qb=encode(b,xe+we,32)
        if np.max(np.abs(np.ldexp(b.astype(np.float64),-xe-we)))>=2**31:
            raise ValueError('Bias exceeds frozen hardware format')
        config.append(dict(layer=li,x_exponent=xe,w_exponent=we,x_analytic_bound=bound,
                           weight_max=float(np.max(np.abs(w))),rounding='nearest_ties_even',
                           scale_source='checkpoint weights and LayerNorm analytic bound; no evaluation samples'))
        params.append((qw,qb))
    sse=np.zeros(12); energy=np.zeros(12); count=0; samples=[]; task_reports=[]
    input_max=np.zeros(12);saturated=np.zeros(12,dtype=np.int64)
    all_tasks=[]
    for si,idx in enumerate(selected):
        audio,label=ap.get_data(1,idx,flags,0.,0.,0,args.split,0.,0.,sess=sess)
        values=sess.run(taps,feed_dict={model.input:audio})
        # Verify tapped reconstruction against the original model classification head.
        head=model.layers[-1]
        original=model.predict_on_batch(audio)
        if isinstance(original,list): original=original[0]
        reconstructed=sess.run(head(tf.constant(values[-1])))
        np.testing.assert_allclose(original,reconstructed,rtol=2e-5,atol=2e-5)
        sample=ap.data_index[args.split][idx]
        record=dict(index=idx,label=labels[int(label[0])],file=('silence' if int(label[0])==0 else Path(sample['file']).relative_to(upstream.DATA).as_posix()))
        samples.append(record)
        for li in range(12):
            xf,yf=values[1+2*li][0],values[2+2*li][0]
            cfg=config[li]; qw,qb=params[li]
            input_max[li]=max(input_max[li],float(np.max(np.abs(xf))))
            raw=np.rint(np.ldexp(xf.astype(np.float64),-cfg['x_exponent']))
            saturated[li]+=int(np.sum((raw < -32768) | (raw > 32767)))
            qx=encode(xf,cfg['x_exponent'])
            yi=linear(qx,qw,qb); yd=decode(yi,cfg['x_exponent'],cfg['w_exponent'])
            sse[li]+=np.sum((yd-yf.astype(np.float64))**2)
            energy[li]+=np.sum(yf.astype(np.float64)**2)
            if args.save_all:
                target=out/('sample_%04d'%si)/('layer_%02d.npz'%li)
                target.parent.mkdir(exist_ok=True)
                wf,bf=tr.enc_layers[li].ffn.layers[0].get_weights()
                np.savez_compressed(target,x=xf,w=wf,b=bf,y=yf)
                all_tasks.append({'layer':li,'npz':target.relative_to(out).as_posix()})
            if si==li:
                d=out/('task_%02d'%li); d.mkdir(exist_ok=True)
                hexfile(d/'x.hex',qx); hexfile(d/'w.hex',qw.T); hexfile(d/'b.hex',qb)
                hexfile(d/'expected.hex',yi,64)
                from pack_vectors import pack_directory
                pack_directory(d)
                np.savez_compressed(d/'reference.npz',x=xf,w=tr.enc_layers[li].ffn.layers[0].get_weights()[0],
                                    b=tr.enc_layers[li].ffn.layers[0].get_weights()[1],y=yf,
                                    encoder_input=values[0][0],xq=qx,wq=qw,bq=qb,yq=yi)
                task_reports.append(dict(task=li,layer=li,sample=record,nrmse=nrmse(yd,yf)))
        count+=99*256
        if (si+1)%12==0: print('Validated',si+1,'samples x 12 layers',flush=True)
    errors=np.sqrt(sse/count)/np.maximum(np.sqrt(energy/count),1e-8)
    report=dict(split=args.split,sample_count=len(samples),samples=samples,layer_nrmse=errors.tolist(),
                layer_input_max_abs=input_max.tolist(),layer_saturated_input_count=saturated.tolist(),
                maximum_layer_nrmse=float(max(errors)),threshold=.03,passed=bool(max(errors)<=.03),
                performance_tasks=task_reports,checkpoint_tensors_verified=162,
                reference='unmodified pinned KWT-1 best_weights, TensorFlow 2.4.0 development fallback',
                official_evaluation=False)
    (out/'numeric-report.json').write_text(json.dumps(report,indent=2)+'\n')
    cfg={'version':1,'layers':config,'x_bits':16,'w_bits':16,'bias_bits':32,'accumulator_bits':40,'output_bits':64}
    frozen=ROOT/'model/format.json'
    if frozen.exists():
        if json.loads(frozen.read_text())!=cfg: raise ValueError('Frozen configuration mismatch')
    else:
        frozen.write_text(json.dumps(cfg,indent=2)+'\n')
    packed={d.name:pack_directory(d) for d in sorted(out.glob('task_*'))}
    (out/'packed-manifest.json').write_text(json.dumps(packed,indent=2)+'\n')
    hashes={str(p.relative_to(out)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in out.glob('task_*/*.hex') if not p.stem.endswith('_packed')}
    (out/'manifest.json').write_text(json.dumps(hashes,indent=2)+'\n')
    if args.save_all:
        (out/'evaluation-manifest.json').write_text(json.dumps(all_tasks,indent=2)+'\n')
    print('Maximum aggregate layer NRMSE:',max(errors),flush=True)
    if not report['passed'] or any(t['nrmse']>.03 for t in task_reports): raise RuntimeError('Numeric threshold failed')
    sess.close()

if __name__=='__main__': main()
