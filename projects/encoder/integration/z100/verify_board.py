"""Generate or verify the Z100 frozen and Speech Commands validation runs."""

import argparse
import gzip
import json
import statistics
import struct
from pathlib import Path

from board import Board, DEMO_BAUD, RESULT

ROOT = Path(__file__).resolve().parents[2]
VECTORS = ROOT / "output" / "encoder-vectors"
BUILD = ROOT / "output" / "z100"


def frozen_words(path):
    words = [int(line, 16) for line in path.read_text().splitlines()]
    if len(words) != 6336:
        raise ValueError(f"{path} does not contain 6336 words")
    return struct.pack("<6336I", *words)


def samples(validation):
    if not validation:
        report = json.loads((VECTORS / "numeric-report.json").read_text())
        for task in range(12):
            row = report["tasks"][task]
            vectors = VECTORS / f"task_{task:02d}"
            yield (row["sample"]["file"], row["label"], row["predicted"],
                   frozen_words(vectors / "input.hex"), frozen_words(vectors / "expected.hex"))
        return

    from model_data import Model
    model = Model()
    names = json.loads((ROOT / "model" / "validation-samples.json").read_text())
    reference = {}
    evidence = ROOT / "docs" / "evidence" / "encoder-validation-expanded.samples.jsonl.gz"
    with gzip.open(evidence, "rt", encoding="utf-8") as file:
        for line in file:
            row = json.loads(line)
            reference[row["file"]] = row["integer_predicted"]
    legacy = ROOT / "output" / "encoder-validation-expanded-legacy120" / "samples.jsonl"
    if legacy.is_file():
        with legacy.open(encoding="utf-8") as file:
            for line in file:
                row = json.loads(line)
                reference[row["file"]] = row["integer_predicted"]
    if any(name not in reference for name in names):
        raise ValueError(f"Generate the fixed 120-sample software reference at {legacy.parent}")
    for name in names:
        audio, label = model.validation_audio(name)
        yield name, label, reference[name], model.encode(audio), None


def check(expected, actual):
    if expected is None or actual == expected:
        return
    for index, (a, b) in enumerate(zip(struct.iter_unpack("<i", actual),
                                     struct.iter_unpack("<i", expected))):
        if a != b:
            raise ValueError(f"Output {index}: FPGA {a[0]}, expected {b[0]}")
    raise ValueError("Wrong encoder output length")


def report(path, rows):
    metrics = {
        "samples": len(rows),
        "reference_matches": sum(row["match"] for row in rows),
        "correct_labels": sum(row["correct"] for row in rows),
        "board_median_ms": statistics.median(row["board_ms"] for row in rows),
        "results": rows,
    }
    path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print({key: value for key, value in metrics.items() if key != "results"})
    if metrics["reference_matches"] != metrics["samples"]:
        raise SystemExit("Board predictions did not all match the software reference")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation", action="store_true")
    parser.add_argument("--port", default="COM8")
    parser.add_argument("--baud", type=int, choices=[115200, 921600], default=DEMO_BAUD)
    parser.add_argument("--prepare-jtag", action="store_true")
    parser.add_argument("--check-jtag", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    mode = "validation" if args.validation else "frozen"
    if args.prepare_jtag:
        work = BUILD / f"jtag-{mode}"
        work.mkdir(parents=True, exist_ok=True)
        manifest = []
        for index, (name, label, reference, features, expected) in enumerate(samples(args.validation)):
            (work / f"{index:03d}.input").write_bytes(features)
            if expected is not None:
                (work / f"{index:03d}.expected").write_bytes(expected)
            manifest.append(dict(sample=name, label=label, reference=reference))
        (work / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        print(work)
        return
    rows = []
    if args.check_jtag:
        work = BUILD / f"jtag-{mode}"
        manifest = json.loads((work / "manifest.json").read_text())
        for index, sample in enumerate(manifest):
            payload = (work / f"{index:03d}.reply").read_bytes()
            status, prediction, frequency, cycles, *_ = RESULT.unpack_from(payload)
            if status:
                raise ValueError(f"Board status {status} on sample {index}")
            expected = None if args.validation else (work / f"{index:03d}.expected").read_bytes()
            check(expected, payload[RESULT.size:])
            rows.append(dict(sample, prediction=prediction, match=prediction == sample["reference"],
                             correct=prediction == sample["label"], board_ms=1000 * cycles / frequency))
        report(BUILD / f"jtag-{mode}.json", rows)
        return
    with Board(args.port, args.baud) as board:
        for index, (name, label, reference, features, expected) in enumerate(samples(args.validation)):
            result = board.infer(features, verify=expected is not None)
            check(expected, result.output)
            rows.append(dict(sample=name, label=label, reference=reference, prediction=result.label,
                             match=result.label == reference, correct=result.label == label,
                             board_ms=1000 * result.cycles / result.frequency,
                             serial_ms=1000 * result.elapsed))
            print(f"{index+1} {name} board={result.label} reference={reference}", flush=True)
    transport = "tcp" if ":" in args.port else "uart"
    report(args.output or BUILD / f"{transport}-{mode}.json", rows)


if __name__ == "__main__":
    main()
