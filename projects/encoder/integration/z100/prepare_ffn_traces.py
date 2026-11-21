"""Build exact FFN1 and GELU reference vectors for the fixed encoder trace."""

import argparse
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def hex_words(path):
    return np.array([int(line, 16) for line in path.read_text().splitlines()], dtype="<u4")


def write_hex(path, data, bits):
    mask = (1 << bits) - 1
    path.write_text("".join(f"{int(value) & mask:0{bits//4}x}\n" for value in data.flat),
                    encoding="ascii")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "output" / "z100")
    args = parser.parse_args()
    vectors = ROOT / "output" / "encoder-vectors"
    for layer in range(12):
        key = f"layer_{layer:02d}"
        inputs = vectors / "task_00" / key
        weights = hex_words(vectors / key / "w1.hex").view("<i2").reshape(256, 64).T
        bias = hex_words(vectors / key / "b1.hex").view("<i4")
        x = hex_words(inputs / "ffn_input.hex").view("<i2").reshape(99, 64)
        out = args.build / "ffn-traces" / key
        out.mkdir(parents=True, exist_ok=True)
        write_hex(out / "ffn1.hex", x.astype(np.int64) @ weights.astype(np.int64) + bias, 40)
        with np.load(inputs / "trace.npz") as trace:
            write_hex(out / "gelu.hex", trace["gelu"], 16)


if __name__ == "__main__":
    main()
