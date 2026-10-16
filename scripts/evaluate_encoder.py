"""Evaluate the frozen 12-layer integer encoder on the full upstream validation set.

Writes a replayable sample list, per-sample JSONL and an aggregate JSON report.
No scale fitting, parameter updates, RTL vector export or training is performed.
"""
import argparse
import collections
import hashlib
import json
import platform
import subprocess
import time
from pathlib import Path
import export_vectors as ev
from numeric import encode
from encoder_numeric import q16, encoder_layer
from encoder_observer import EncoderObserver, STAGES

np, tf, ROOT = ev.np, ev.tf, ev.ROOT


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def metric(error, reference):
    sse = float(np.sum(error * error))
    energy = float(np.sum(reference * reference))
    return dict(sse=sse, reference_energy=energy,
                nrmse=float(np.sqrt(sse / max(energy, 1e-16))),
                max_absolute_error=float(np.max(np.abs(error))))


def accuracy(rows):
    n = len(rows)
    fc = sum(r['float_predicted'] == r['label'] for r in rows)
    ic = sum(r['integer_predicted'] == r['label'] for r in rows)
    different = sum(r['float_predicted'] != r['integer_predicted'] for r in rows)
    regressions = sum(r['float_predicted'] == r['label'] and r['integer_predicted'] != r['label'] for r in rows)
    improvements = sum(r['float_predicted'] != r['label'] and r['integer_predicted'] == r['label'] for r in rows)
    return dict(samples=n, float_correct=fc, integer_correct=ic, prediction_differences=different,
                float_accuracy=fc/n if n else None, integer_accuracy=ic/n if n else None,
                accuracy_drop_percentage_points=100*(fc-ic)/n if n else None,
                regressions=regressions, improvements=improvements)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='Fresh output directory')
    parser.add_argument('--sample-list', type=Path, help='Replay dataset-relative JSON path array; silence denotes zeros')
    parser.add_argument('--samples', type=int, default=0, help='Limit for smoke checks; 0 evaluates all selected samples')
    args = parser.parse_args()
    if args.samples < 0:
        raise ValueError('--samples must be nonnegative')
    out = args.output
    if out.exists() and any(out.iterdir()):
        raise ValueError('Use a fresh output directory to avoid mixing evidence')
    out.mkdir(parents=True, exist_ok=True)
    frozen_paths = [ROOT/'model'/n for n in ('format.json', 'ffn-format.json', 'encoder-format.json',
                                          'numeric.py', 'ffn_numeric.py', 'encoder_numeric.py')]
    before = {p.relative_to(ROOT).as_posix(): sha(p) for p in frozen_paths}
    started = time.monotonic()
    sess, flags, model, tr, taps = ev.load_reference()
    if flags.prenorm or flags.heads != 1 or flags.approximate_gelu:
        raise ValueError('Unsupported reference architecture')
    labels = (ev.upstream.MODEL/'labels.txt').read_text().splitlines()
    flags.pick_deterministically = True
    ap = ev.AudioProcessor(flags)
    from kws_streaming.data.input_data import which_set
    index = ap.data_index['validation']
    names = ['silence' if s['label'] == '_silence_' else
             Path(s['file']).relative_to(ev.upstream.DATA).as_posix() for s in index]
    upstream_names = list(names)
    lookup = {name: i for i, name in enumerate(names)}
    if args.sample_list:
        names = json.loads(args.sample_list.read_text(encoding='utf-8-sig'))
        if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
            raise ValueError('Expected a nonempty JSON path array')
    if args.samples:
        names = names[:args.samples]
    for name in names:
        if name == 'silence':
            continue
        path = (ev.upstream.DATA/name).resolve()
        if ev.upstream.DATA.resolve() not in path.parents or not path.is_file():
            raise ValueError('Invalid audio path: ' + name)
        if which_set(str(path), flags.validation_percentage, flags.testing_percentage) != 'validation':
            raise ValueError('Sample outside validation split: ' + name)
        if name not in lookup:
            lookup[name] = len(index)
            index.append(dict(file=str(path), label=Path(name).parts[0]))
    dump(out/'samples.json', names)
    first = json.loads((ROOT/'model/format.json').read_text())['layers']
    second = json.loads((ROOT/'model/ffn-format.json').read_text())['layers']
    params, nodes = [], []
    x = taps[0]
    parameter_saturation = []
    for li, block in enumerate(tr.enc_layers):
        p = {}
        for key, dense in [('wq', block.att.query_dense), ('wk', block.att.key_dense),
                           ('wv', block.att.value_dense), ('wo', block.att.combine_heads)]:
            p[key] = q16(dense.get_weights()[0])
        p['bo'] = q16(block.att.combine_heads.get_weights()[1])
        for suffix, ln in [('1', block.layernorm1), ('2', block.layernorm2)]:
            if ln.epsilon != 1e-6:
                raise ValueError('LayerNorm epsilon changed')
            gamma, beta = ln.get_weights()
            p['g'+suffix], p['n'+suffix] = q16(gamma), q16(beta)
        w, b = block.ffn.layers[0].get_weights()
        w2, b2 = block.ffn.layers[2].get_weights()
        conversions = [('w1', w, first[li]['w_exponent'], 16),
                       ('b1', b, first[li]['x_exponent']+first[li]['w_exponent'], 32),
                       ('w2', w2, second[li]['w2_exponent'], 16),
                       ('b2', b2, second[li]['output_exponent'], 32)]
        clips = {}
        for key, value, exponent, bits in conversions:
            raw = np.rint(np.ldexp(value.astype(np.float64), -exponent))
            clips[key] = int(np.count_nonzero((raw < -(1 << (bits-1))) | (raw > (1 << (bits-1))-1)))
            p[key] = encode(value, exponent, bits)
        parameter_saturation.append(clips)
        params.append(p)
        x, _ = block(x, training=False)
        nodes.append(x)
    head_input = tf.compat.v1.placeholder(tf.float32, [1, 64])
    head_output = model.layers[-1](head_input)
    observer = EncoderObserver()
    layer_metrics = [[] for _ in range(12)]
    totals = [{s: dict(elements=0, saturated=0) for s in STAGES} for _ in range(12)]
    cutoff = [0]*12
    records, differences, saturation_samples = [], [], []
    confusion_float = np.zeros((12, 12), dtype=np.int64)
    confusion_integer = np.zeros((12, 12), dtype=np.int64)
    with (out/'samples.jsonl').open('w', encoding='utf-8') as stream:
        for si, name in enumerate(names):
            audio, label = ap.get_data(1, lookup[name], flags, 0., 0., 0, 'validation', 0., 0., sess=sess)
            initial, refs, logits = sess.run([taps[0], nodes, model.output], feed_dict={model.input: audio})
            if isinstance(logits, list):
                logits = logits[0]
            xi = q16(initial[0])
            per_layer, per_sat, per_cutoff = [], [], []
            for li, p in enumerate(params):
                old = xi
                xi, trace, stats, clipped_exp = observer.run(xi, p, first[li], second[li])
                # Compare all returned intermediate arrays on the first sample;
                # the frozen model remains unmodified and independently callable.
                if si == 0:
                    baseline, baseline_trace = encoder_layer(old, p, first[li], second[li])
                    np.testing.assert_array_equal(xi, baseline)
                    for key in trace:
                        np.testing.assert_array_equal(trace[key], baseline_trace[key], err_msg=key)
                reference = refs[li][0].astype(np.float64)
                m = metric(xi/65536. - reference, reference)
                layer_metrics[li].append(m)
                per_layer.append(m)
                per_sat.append(stats)
                per_cutoff.append(clipped_exp)
                cutoff[li] += clipped_exp
                for stage in STAGES:
                    for key in ('elements', 'saturated'):
                        totals[li][stage][key] += stats[stage][key]
            integer_logits = sess.run(head_output, feed_dict={head_input: (xi[:1]/65536.).astype(np.float32)})[0]
            float_logits = np.asarray(logits)[0]
            pred, refpred, truth = int(np.argmax(integer_logits)), int(np.argmax(float_logits)), int(label[0])
            sorted_float = np.sort(float_logits)
            sorted_integer = np.sort(integer_logits)
            record = dict(index=si, file=name, label=truth, float_predicted=refpred, integer_predicted=pred,
                          float_margin=float(sorted_float[-1]-sorted_float[-2]),
                          integer_margin=float(sorted_integer[-1]-sorted_integer[-2]),
                          max_logit_absolute_error=float(np.max(np.abs(integer_logits-float_logits))))
            records.append(record)
            confusion_float[truth, refpred] += 1
            confusion_integer[truth, pred] += 1
            if pred != refpred:
                differences.append(record)
            sample_sat = sum(v['saturated'] for stats in per_sat for v in stats.values())
            if sample_sat:
                saturation_samples.append(dict(index=si, file=name, count=sample_sat))
            full = dict(record, layer_errors=per_layer, saturation=per_sat, softmax_cutoff=per_cutoff,
                        float_logits=float_logits.tolist(), integer_logits=integer_logits.tolist(),
                        audio_sha256=sha(ev.upstream.DATA/name) if name != 'silence' else None)
            stream.write(json.dumps(full, separators=(',', ':'), allow_nan=False)+'\n')
            if (si+1) % 50 == 0 or si+1 == len(names):
                stream.flush()
                print('validation %d/%d; differences=%d; saturated_samples=%d; elapsed=%.1fs' %
                      (si+1, len(names), len(differences), len(saturation_samples), time.monotonic()-started), flush=True)
    layers = []
    for li, values in enumerate(layer_metrics):
        sse = sum(v['sse'] for v in values)
        energy = sum(v['reference_energy'] for v in values)
        worst = max(range(len(values)), key=lambda i: values[i]['nrmse'])
        layers.append(dict(layer=li, aggregate_nrmse=float(np.sqrt(sse/max(energy, 1e-16))),
                           rmse=float(np.sqrt(sse/(len(names)*99*64))),
                           max_absolute_error=max(v['max_absolute_error'] for v in values),
                           p95_sample_nrmse=float(np.percentile([v['nrmse'] for v in values], 95)),
                           worst_sample=dict(index=worst, file=names[worst], **values[worst]),
                           saturation=totals[li], softmax_cutoff_count=cutoff[li]))
    result = accuracy(records)
    after = {p.relative_to(ROOT).as_posix(): sha(p) for p in frozen_paths}
    if before != after:
        raise RuntimeError('Frozen numeric files changed during evaluation')
    source_paths = [Path(__file__).resolve(), ROOT/'model/encoder_observer.py', ROOT/'scripts/export_vectors.py',
                    ROOT/'scripts/check_model_environment.py']
    checkpoints = list(ev.upstream.MODEL.glob('best_weights.*')) + [ev.upstream.MODEL/'flags.json', ev.upstream.MODEL/'labels.txt']
    old_names = set(json.loads((ROOT/'model/validation-samples.json').read_text()))
    report = dict(schema_version=1, split='validation', official_evaluation=False,
                  selection='upstream full validation index' if not args.sample_list and not args.samples else 'explicit list or limited subset',
                  covers_upstream_index=collections.Counter(names) == collections.Counter(upstream_names),
                  labels=labels, classification=result, layers=layers,
                  max_layer_nrmse=max(v['aggregate_nrmse'] for v in layers),
                  prediction_differences=differences, saturation_samples=saturation_samples,
                  saturation_count=sum(v['saturated'] for stats in totals for v in stats.values()),
                  parameter_saturation=parameter_saturation,
                  non_silence=accuracy([r for r in records if r['file'] != 'silence']),
                  newly_added_audio=accuracy([r for r in records if r['file'] not in old_names]),
                  unique_audio_files=len(set(names)-{'silence'}), silence_entries=names.count('silence'),
                  duplicate_non_silence_entries=len([n for n in names if n != 'silence'])-len(set(names)-{'silence'}),
                  historical_manifest_unique_overlap=len(set(names) & old_names),
                  per_class=[dict(label=label, **accuracy([r for r in records if r['label'] == i])) for i, label in enumerate(labels)],
                  float_confusion_matrix=confusion_float.tolist(), integer_confusion_matrix=confusion_integer.tolist(),
                  frozen_files_sha256=before, evaluation_sources_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in source_paths},
                  checkpoint_files_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in checkpoints},
                  evidence_sha256={n:sha(out/n) for n in ('samples.json', 'samples.jsonl')},
                  checkpoint_tensors_verified=len(model.weights), observation_matches_oracle_first_sample=True,
                  software=dict(python=platform.python_version(), numpy=np.__version__, tensorflow=tf.__version__),
                  base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  elapsed_seconds=time.monotonic()-started, passed=result['accuracy_drop_percentage_points'] <= 2,
                  precision_gate='local classification drop <= 2 percentage points; no official acceptance asserted',
                  scope='Integer encoder with floating software embedding and classification head; no expanded RTL simulation',
                  saturation_definition='Count values strictly outside signed range BEFORE clipping; legal endpoints are not saturation. Q16 conversion overflow raises. FFN int40 accumulation is exact for legal int16 inputs.',
                  softmax_cutoff_definition='Score difference >=16 maps exp to zero by frozen design; reported separately, not arithmetic saturation',
                  silence_definition='Upstream silence entries all use identical zero input without augmentation; included with original weighting, also report non-silence separately')
    dump(out/'report.json', report)
    sess.close()
    print(json.dumps(result, indent=2), flush=True)
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
