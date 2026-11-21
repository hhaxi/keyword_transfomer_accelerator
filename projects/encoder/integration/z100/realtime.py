"""Realtime audio sources and the KWT monitoring loop (common to WAV and mic)."""
import math
import queue
import time
from datetime import datetime, timedelta

import numpy as np
import serial

from board import Board

RATE = 16000
HOP = 3200
HOP_SECONDS = HOP / RATE
MIN_RMS = 0.004


def read_wav(path):
    from scipy.io import wavfile
    from scipy.signal import resample_poly
    rate, data = wavfile.read(path)
    if rate <= 0 or not data.size or data.ndim not in (1, 2):
        raise ValueError(f"无效 WAV · {path.name}")
    if data.dtype.kind in "iu":
        scale = 2 ** (data.dtype.itemsize * 8 - 1)
        data = (data.astype(np.float32) - (scale if data.dtype.kind == "u" else 0)) / scale
    elif data.dtype.kind == "f":
        data = data.astype(np.float32)
    else:
        raise ValueError(f"WAV 需要 PCM 或浮点采样 · {path.name}")
    if data.ndim == 2:
        data = data.mean(axis=1)
    if not np.isfinite(data).all():
        raise ValueError(f"WAV 含无效采样 · {path.name}")
    if rate != RATE:
        divisor = math.gcd(rate, RATE)
        data = resample_poly(data, RATE // divisor, rate // divisor)
    return np.clip(data, -1, 1).astype(np.float32)


def replay_blocks(paths, stop):
    # A second of room silence separates files and drains the last window.
    chunk = np.zeros(HOP, np.float32)
    used = samples = 0
    origin = wall = None
    for path in paths:
        for audio, title in ((read_wav(path), path.name), (np.zeros(RATE, np.float32), "静音间隔")):
            if origin is None:
                origin, wall = time.monotonic(), datetime.now()
            offset = 0
            while offset < len(audio):
                count = min(HOP - used, len(audio) - offset)
                chunk[used:used+count] = audio[offset:offset+count]
                offset += count
                used += count
                if used == HOP:
                    samples += HOP
                    if stop.wait(max(0, origin + samples/RATE - time.monotonic())):
                        return
                    yield chunk, wall + timedelta(seconds=samples/RATE), title, False
                    chunk = np.zeros(HOP, np.float32)
                    used = 0
    if used and not stop.wait(max(0, origin + (samples+used)/RATE - time.monotonic())):
        yield chunk, wall + timedelta(seconds=(samples+used)/RATE), "静音间隔", False


def microphone_blocks(stop):
    import sounddevice as sd
    blocks = queue.Queue(maxsize=4)
    sequence = 0

    def capture(data, frames, timing, status):
        nonlocal sequence
        sequence += 1
        stamp = datetime.now() + timedelta(seconds=timing.inputBufferAdcTime - timing.currentTime + frames/RATE)
        record = sequence, data[:, 0].copy(), stamp, bool(status.input_overflow)
        try:
            blocks.put_nowait(record)
        except queue.Full:
            # Only the callback produces. Evict stale audio; the sequence gap
            # resets both the PC window and board debounce on the next inference.
            try:
                blocks.get_nowait()
            except queue.Empty:
                pass
            blocks.put_nowait(record)

    previous = 0
    with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=HOP, callback=capture) as stream:
        while not stop.is_set():
            try:
                seq, data, stamp, overflow = blocks.get(timeout=HOP_SECONDS)
            except queue.Empty:
                if not stream.active:
                    raise RuntimeError("麦克风输入流已中断")
                continue
            yield data, stamp, "麦克风", overflow or seq != previous+1
            previous = seq


def read_event(uart, expected):
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        line = uart.readline(128).decode("ascii", errors="replace").strip()
        if line == expected:
            return line
        if line.startswith("KWT 20"):
            raise RuntimeError(f"串口事件与板卡应答不一致 · {line}")
    raise RuntimeError(f"{uart.port} 未收到板卡事件，请核对 USB 串口与 115200 波特率")


def listen(model, endpoint, com, paths, stop, emit):
    if ":" not in endpoint:
        raise ValueError("实时监测需要板卡以太网地址，如 192.168.1.11:5001")
    if not com:
        raise ValueError("请选择板卡 USB 串口")
    if tuple(model.labels[2:]) != ("yes", "no", "up", "down", "left", "right", "on", "off", "stop", "go"):
        raise ValueError("模型标签顺序与监测固件不匹配")
    window = np.zeros(RATE, np.float32)
    windows = hits = gaps = 0
    reset = True
    with serial.Serial(com, 115200, timeout=.12) as uart, Board(endpoint) as board:
        uart.reset_input_buffer()
        source = microphone_blocks(stop) if paths is None else replay_blocks(paths, stop)
        emit("listening", f"{endpoint}  ·  {com} / 115200")
        try:
            for block, stamp, title, gap in source:
                if stop.is_set():
                    break
                if gap:
                    window.fill(0)
                    reset = True
                    gaps += 1
                window[:-HOP] = window[HOP:]
                window[-HOP:] = block
                stamp = stamp.isoformat(timespec="milliseconds")
                features = model.encode(window)
                result, fired = board.monitor(features, stamp, np.mean(window*window) >= MIN_RMS**2, reset)
                reset = False
                windows += 1
                latency = result.cycles * 1000 / result.frequency
                if fired:
                    label = model.labels[result.label]
                    raw = read_event(uart, f"KWT {stamp} {label}")
                    hits += 1
                    emit("keyword", (raw, com))
                elif uart.in_waiting:
                    line = uart.readline(128).decode("ascii", errors="replace").strip()
                    if line.startswith("KWT 20"):
                        raise RuntimeError(f"收到未确认的串口事件 · {line}")
                bands = window.reshape(160, -1)
                emit("window", (bands.min(1), bands.max(1), title, windows, hits, latency, stamp, gaps))
        finally:
            source.close()
    return windows, hits
