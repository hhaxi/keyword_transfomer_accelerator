"""Validate the realtime path with a paced recording, a Z100 and its physical UART."""
import argparse
import json
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from board import DEMO_TCP
from model_data import Model, ROOT
from realtime import RATE, listen, read_wav


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=DEMO_TCP)
    parser.add_argument("--uart", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    model = Model()
    model.encode(np.zeros(RATE, np.float32))
    candidates = json.loads((ROOT / "model/validation-samples.json").read_text())
    pieces = []
    segments = []
    def add(source, audio):
        offset = sum(len(piece) for piece in pieces) / RATE
        pieces.append(audio)
        segments.append(dict(source=source, start_s=offset, end_s=offset+len(audio)/RATE))
    def quiet(duration):
        add("silence", np.zeros(round(duration*RATE), np.float32))

    quiet(1.13)
    for name in ("_background_noise_/doing_the_dishes.wav", "three", "yes", "no", "stop", "go", "yes"):
        relative = name if "/" in name else next(n for n in candidates if n.startswith(name+"/"))
        audio = read_wav(model.dataset / relative)
        add(relative, audio[:2*RATE])
        quiet(1.2)
    expected = [s for s in segments if s["source"].split("/")[0] in model.labels[2:]]
    events = []
    gaps = 0
    epoch = None
    def observe(kind, data):
        nonlocal gaps, epoch
        if kind == "keyword":
            line, com = data
            _, stamp, label = line.split()
            events.append(dict(line=line, port=com, label=label, timestamp=stamp))
        if kind == "window":
            gaps = data[-1]
            if epoch is None:
                epoch = datetime.fromisoformat(data[-2]) - timedelta(seconds=.2)

    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "stream.wav"
        wavfile.write(path, RATE, np.rint(np.concatenate(pieces)*32767).astype("<i2"))
        started = time.monotonic()
        windows, hits = listen(model, args.port, args.uart, [path], threading.Event(), observe)
        elapsed = time.monotonic() - started
    for item in events:
        item["offset_s"] = (datetime.fromisoformat(item["timestamp"]) - epoch).total_seconds()
    ok = len(expected) == hits and gaps == 0 and all(
        event["label"] == seg["source"].split("/")[0] and seg["start_s"] <= event["offset_s"] <= seg["end_s"]+.8
        for event, seg in zip(events, expected))
    report = dict(passed=ok, board=args.port, uart=args.uart, uart_baud=115200, windows=windows,
                  hits=hits, elapsed_s=elapsed, gaps=gaps, events=events, segments=segments)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(f"windows={windows} hits={hits} gaps={gaps} passed={ok}", flush=True)
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
