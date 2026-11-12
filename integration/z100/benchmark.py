"""Measure warm WAV-to-result latency on the fixed KWT validation set."""

import argparse
import json
import statistics
import time
from contextlib import ExitStack
from pathlib import Path

from board import Board
from model_data import Model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM8", help="COM port or board TCP address")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--new-connection", action="store_true", help="Connect for each WAV, like the desktop app")
    parser.add_argument("--passes", type=int, default=1, help="Number of passes through the fixed WAV list")
    args = parser.parse_args()
    if args.passes < 1:
        parser.error("--passes must be positive")

    root = Path(__file__).resolve().parents[2]
    names = json.loads((root / "model/validation-samples.json").read_text(encoding="utf-8"))
    names = [name for name in names if name != "silence"][:12]
    model = Model()
    model.validation()
    rows = []
    with ExitStack() as stack:
        board = stack.enter_context(Board(args.port))
        audio, _ = model.validation_audio(names[0])
        board.infer(model.encode(audio))
        if args.new_connection:
            stack.close()
        run_start = time.perf_counter()
        for name in names * args.passes:
            start = time.perf_counter()
            audio, label = model.validation_audio(name)
            features = model.encode(audio)
            encoded = time.perf_counter()
            if args.new_connection:
                with Board(args.port) as connection:
                    result = connection.infer(features)
            else:
                result = board.infer(features)
            finished = time.perf_counter()
            total = finished - start
            row = dict(file=name, preprocess_ms=(encoded - start) * 1000,
                       transport_and_board_ms=result.elapsed * 1000,
                       board_ms=result.cycles * 1000 / result.frequency,
                       end_to_end_ms=total * 1000, prediction=result.label, label=label)
            rows.append(row)
        wall_seconds = finished - run_start
    for row in rows:
        print(row, flush=True)
    metrics = ("preprocess_ms", "transport_and_board_ms", "board_ms", "end_to_end_ms")
    median = {key: statistics.median(row[key] for row in rows) for key in metrics}
    throughput = dict(requests=len(rows), passes=args.passes, wall_seconds=wall_seconds,
                      end_to_end_per_second=len(rows) / wall_seconds)
    args.output.write_text(json.dumps(dict(median=median, throughput=throughput, samples=rows),
                                      indent=2) + "\n", encoding="utf-8")
    print(median)
    print(throughput)


if __name__ == "__main__":
    main()
