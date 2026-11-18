"""Shared KWT-1 model input, validation split and Z100 parameter export."""

import argparse
import hashlib
import json
import struct
import sys
import zlib
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import export_vectors as ev
from encoder_numeric import q16

LAYERS = 12
PARAMETERS = (("params", 16704), ("w1", 8192), ("b1", 256),
              ("w2", 8192), ("b2", 64), ("config", 2))


class NotValidationAudio(ValueError):
    """The requested file does not belong to the frozen validation split."""


class Model:
    def __init__(self):
        self.session, self.flags, self.model, _, taps = ev.load_reference()
        self.embedding = taps[0]
        self.labels = (ev.upstream.MODEL / "labels.txt").read_text().splitlines()
        self.dataset = ev.upstream.DATA
        self.flags.pick_deterministically = True
        self.processor = None
        self.validation_index = None

    def validation(self):
        if self.validation_index is None:
            self.processor = ev.AudioProcessor(self.flags)
            items = self.processor.data_index["validation"]
            self.validation_index = {
                ("silence" if item["label"] == "_silence_" else
                 Path(item["file"]).relative_to(self.dataset).as_posix()): index
                for index, item in enumerate(items)
            }
        return self.validation_index

    def validation_audio(self, name):
        lookup = self.validation()
        if name not in lookup:
            path = (self.dataset / name).resolve()
            if (self.dataset.resolve() not in path.parents or not path.is_file() or
                ev.which_set(str(path), self.flags.validation_percentage,
                             self.flags.testing_percentage) != "validation"):
                raise NotValidationAudio(f"请选择验证集中的 WAV。当前文件为 {name}")
            items = self.processor.data_index["validation"]
            lookup[name] = len(items)
            items.append({"file": str(path), "label": path.parent.name})
        index = lookup[name]
        sample = self.processor.data_index["validation"][index]
        label = self.processor.word_to_index[sample["label"]]
        count = self.flags.desired_samples
        if sample["label"] == "_silence_":
            return np.zeros(count, dtype=np.float32), label
        # Validation has unit gain and no augmentation. Decode the PCM once,
        # preserving decode_wav's zero padding and first-second truncation.
        try:
            with wave.open(sample["file"], "rb") as wav:
                if (wav.getsampwidth() == 2 and wav.getnchannels() == 1 and
                        wav.getframerate() == self.flags.sample_rate and wav.getcomptype() == "NONE"):
                    pcm = np.frombuffer(wav.readframes(count), dtype="<i2")
                    audio = np.zeros(count, dtype=np.float32)
                    np.multiply(pcm, 1.0 / 32768, out=audio[:pcm.size])
                    return audio, label
        except wave.Error:
            pass
        audio, label = self.processor.get_data(1, index, self.flags, 0., 0., 0.,
                                               "validation", 0., 0., sess=self.session)
        return audio[0], int(label[0])

    def encode(self, audio):
        features = self.session.run(self.embedding, feed_dict={self.model.input: audio[None, :]})
        return q16(features[0]).astype("<i4").tobytes()

    def export(self, vector_dir, output):
        manifest = json.loads((vector_dir / "manifest.json").read_text())
        chunks = []
        for layer in range(LAYERS):
            for name, count in PARAMETERS:
                relative = f"layer_{layer:02d}/{name}.hex"
                data = (vector_dir / relative).read_bytes()
                if hashlib.sha256(data).hexdigest() != manifest[relative]:
                    raise ValueError(f"Frozen vector digest mismatch: {relative}")
                words = [int(line, 16) for line in data.splitlines()]
                if len(words) != count:
                    raise ValueError(f"Wrong size: {relative}")
                chunks.append(struct.pack(f"<{count}I", *words))
        weights, bias = self.model.layers[-1].get_weights()
        if weights.shape != (64, 12) or bias.shape != (12,) or len(self.labels) != 12:
            raise ValueError("Unexpected KWT-1 classification head")
        chunks.extend([weights.astype("<f4").tobytes(), bias.astype("<f4").tobytes()])
        payload = b"".join(chunks)
        output.write_bytes(struct.pack("<4sIII", b"KWTZ", 1, len(payload), zlib.crc32(payload)) + payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vectors", type=Path, default=ROOT / "output" / "encoder-vectors")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "z100" / "kwt.bin")
    args = parser.parse_args()
    Model().export(args.vectors, args.output)
    print(f"{args.output} ({args.output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
