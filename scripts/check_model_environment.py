"""Smoke-test the unmodified, pinned KWT-1 source and best_weights on CPU."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'assets/sources/keyword-transformer-237e4097afd4f6851e0b82f0a8d65c2dfe8eae30'
MODEL = SOURCE / 'models_data_v2_12_labels/kwt1'
DATA = ROOT / 'assets/datasets/speech_commands_v0.02'
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '2')
sys.path.insert(0, str(SOURCE))

import numpy as np
import tensorflow as tf
import tensorflow_addons as tfa
from tensorflow.core.protobuf import trackable_object_graph_pb2
from transformers import AdamWeightDecay
# Match the upstream entry point's import order (utils initializes the registry).
from kws_streaming.models import utils
from kws_streaming.models import kws_transformer, model_flags
from kws_streaming.train import base_parser

def main():
    tf.compat.v1.reset_default_graph()
    session = tf.compat.v1.Session(config=tf.compat.v1.ConfigProto(device_count={'GPU': 0}))
    tf.compat.v1.keras.backend.set_session(session)
    tf.compat.v1.keras.backend.set_learning_phase(0)
    tf.random.set_seed(1234)
    np.random.seed(1234)
    parser = base_parser.base_parser()
    kws_transformer.model_parameters(parser)
    flags = parser.parse_args([])
    vars(flags).update(json.loads((MODEL / 'flags.json').read_text()))
    flags.batch_size = 1
    flags.training = False
    flags.train = 0
    flags.data_dir = str(DATA)
    flags.data_url = ''
    flags.train_dir = str(MODEL)
    flags.use_spec_augment = 0
    flags.use_spec_cutout = 0
    flags.time_shift_ms = 0.0
    flags.resample = 0.0
    flags.volume_resample = 0.0
    flags.background_frequency = 0.0
    flags.background_volume = 0.0
    flags = model_flags.update_flags(flags)
    assert (flags.num_layers, flags.d_model, flags.mlp_dim, flags.heads) == (12, 64, 256, 1)
    assert not flags.prenorm
    model = kws_transformer.model(flags)
    status = model.load_weights(str(MODEL / 'best_weights'))
    status.assert_existing_objects_matched()
    # Training checkpoints can contain optimizer state; all inference objects must match.
    status.expect_partial()
    # Old checkpoints can warn about aliases to weightless GELU layers. Verify
    # actual model tensors against checkpoint names and values independently.
    reader = tf.train.load_checkpoint(str(MODEL / 'best_weights'))
    graph = trackable_object_graph_pb2.TrackableObjectGraph()
    graph.ParseFromString(reader.get_tensor('_CHECKPOINTABLE_OBJECT_GRAPH'))
    checkpoint_names = {a.full_name: a.checkpoint_key for node in graph.nodes for a in node.attributes}
    for weight in model.weights:
        name = weight.name.rsplit(':', 1)[0]
        assert name in checkpoint_names, 'Missing checkpoint tensor: ' + name
        np.testing.assert_array_equal(session.run(weight), reader.get_tensor(checkpoint_names[name]), err_msg=name)
    labels = (MODEL / 'labels.txt').read_text().splitlines()
    targets = set(flags.wanted_words.split(','))
    candidates = [s for s in (DATA / 'validation_list.txt').read_text().splitlines() if s.split('/')[0] in targets]
    chosen = []
    seen = set()
    for s in candidates:
        category = s.split('/')[0]
        if category not in seen:
            chosen.append(s)
            seen.add(category)
        if len(chosen) == 3:
            break
    samples = [('silence', np.zeros((1, 16000), dtype=np.float32))]
    for name in chosen:
        audio, rate = tf.audio.decode_wav(tf.io.read_file(str(DATA / name)), desired_channels=1, desired_samples=16000)
        audio_value, rate_value = session.run([audio, rate])
        assert int(rate_value) == 16000
        samples.append((name, audio_value.T))
    results = []
    for name, audio in samples:
        first = model.predict_on_batch(audio)
        second = model.predict_on_batch(audio)
        if isinstance(first, (list, tuple)):
            first, second = first[0], second[0]
        assert first.shape == (1, 12) and np.isfinite(first).all()
        np.testing.assert_array_equal(first, second)
        pred = int(np.argmax(first[0]))
        results.append({'sample': name, 'prediction': labels[pred], 'logits': first[0].tolist(), 'repeat_max_abs_difference': float(np.max(np.abs(first - second)))})
        print(name, '->', labels[pred], flush=True)
    feature_model = tf.keras.Model(model.input, model.layers[1].output)
    features = feature_model.predict_on_batch(samples[1][1])
    assert tuple(features.shape) == (1, 98, 40)
    result = {
        'status': 'passed', 'python': sys.version, 'tensorflow': tf.__version__,
        'numpy': np.__version__, 'tensorflow_addons': tfa.__version__,
        'source_commit': '237e4097afd4f6851e0b82f0a8d65c2dfe8eae30',
        'weights': 'models_data_v2_12_labels/kwt1/best_weights',
        'all_model_objects_matched': True, 'model_parameters': model.count_params(),
        'checkpoint_tensors_verified_exactly': len(model.weights),
        'feature_shape': list(features.shape), 'samples': results,
        'limitation': 'TensorFlow 2.4.0 is a development fallback for unavailable 2.4.0rc1; smoke testing is not full accuracy or official reference equivalence validation.'
    }
    out = ROOT / 'output/environment'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'model-smoke.json').write_text(json.dumps(result, indent=2) + '\n')
    print('MODEL_ENVIRONMENT_PASS', flush=True)
    session.close()

if __name__ == '__main__':
    main()
