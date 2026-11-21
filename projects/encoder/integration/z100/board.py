"""UART and TCP client for board inference and integer output verification."""

import errno
import math
import os
import select
import socket
import struct
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

import serial

from smoke_serial import encode, receive_frame

FEATURE_BYTES = 6336 * 4
DEMO_BAUD = 921600
DEMO_TCP = "192.168.1.11:5001"
RESULT = struct.Struct("<BBII12f")


@dataclass
class Inference:
    label: int
    frequency: int
    cycles: int
    logits: tuple
    output: bytes
    elapsed: float


class TcpStream:
    def __init__(self, endpoint, *, start_ipv4=False):
        host, port = endpoint.rsplit(":", 1)
        self.port = endpoint
        self.connect_deadline = None
        self.reader = None
        if start_ipv4:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        else:
            self.socket = socket.create_connection((host, int(port)), timeout=15)
        try:
            if start_ipv4:
                self.socket.setblocking(False)
                status = self.socket.connect_ex((host, int(port)))
                if status:
                    if status not in (errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY,
                                      errno.EINTR, getattr(errno, "WSAEWOULDBLOCK", errno.EWOULDBLOCK)):
                        raise OSError(status, f"Cannot connect to {endpoint}")
                    self.connect_deadline = time.monotonic() + 15
            if self.connect_deadline is None:
                self._connected()
        except BaseException:
            self.socket.close()
            raise

    def _connected(self):
        self.socket.settimeout(15)
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.reader = self.socket.makefile("rb")
        self.connect_deadline = None

    def wait_connected(self):
        if self.connect_deadline is None:
            return
        remaining = max(0, self.connect_deadline - time.monotonic())
        _, writable, failed = select.select([], [self.socket], [self.socket], remaining)
        if not writable and not failed:
            raise TimeoutError(f"Timed out connecting to {self.port}")
        status = self.socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if status:
            raise OSError(status, f"Cannot connect to {self.port}")
        self._connected()

    def read(self, count):
        return self.reader.read(count)

    def write(self, data):
        self.socket.sendall(data)
        return len(data)

    def close(self):
        if self.reader is not None:
            self.reader.close()
        self.socket.close()


def decode_result(reply, elapsed, verify):
    size = RESULT.size + (FEATURE_BYTES if verify else 0)
    if len(reply) != size or reply[0] != 0:
        raise ValueError(f"Invalid inference response ({len(reply)} bytes)")
    _, label, frequency, cycles, *logits = RESULT.unpack_from(reply)
    if label >= len(logits) or not frequency or not all(map(math.isfinite, logits)):
        raise ValueError("板卡返回的类别、分数或时钟无效")
    return Inference(label, frequency, cycles, tuple(logits), reply[RESULT.size:], elapsed)


class Board:
    def __init__(self, port, baud=DEMO_BAUD, *, start_ipv4=False):
        if ":" in port:
            self.stream = TcpStream(port, start_ipv4=start_ipv4)
        else:
            self.stream = serial.Serial(port, baud, timeout=15, write_timeout=8)
            self.stream.reset_input_buffer()
        self.request = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stream.close()

    def infer(self, features, *, verify=False, progress=lambda _: None):
        result, _ = self._request(features, verify, progress, None)
        return result

    def monitor(self, features, timestamp, active, reset=False):
        meta = bytes([int(active) | (int(reset) << 1)]) + timestamp.encode("ascii")
        if len(meta) != 24:
            raise ValueError("Expected a local millisecond ISO timestamp")
        return self._request(features, False, lambda _: None, meta)

    def _request(self, features, verify, progress, meta):
        if len(features) != FEATURE_BYTES:
            raise ValueError("Expected 99×64 Q16 values")
        if isinstance(self.stream, TcpStream):
            self.stream.wait_connected()
        self.request = (self.request + 1) & 0xFFFFFFFF
        command = 5 if meta is not None else (4 if verify else 3)
        size = RESULT.size + (FEATURE_BYTES if verify else 0) + int(meta is not None)
        started = time.perf_counter()
        self.stream.write(encode(command, self.request, features + (meta or b"")))
        while True:
            reply = receive_frame(self.stream, command, self.request, size)
            if len(reply) == 2 and reply[0] == 0x80 and 1 <= reply[1] <= 12:
                progress(reply[1])
            elif len(reply) == 7 and reply[0] == 2:
                status = int.from_bytes(reply[3:], "little")
                if reply[2] == 0:
                    raise RuntimeError("板上模型参数缺失或校验失败")
                stage = {1: "Attention/LN1", 2: "FFN", 3: "LN2/E203", 4: "参数或输入装载"}.get(reply[2], str(reply[2]))
                raise RuntimeError(f"第 {reply[1]} 层 {stage} 失败，状态 0x{status:08X}")
            elif len(reply) == size and reply[0] == 0:
                event = False
                if meta is not None:
                    if reply[-1] not in (0, 1):
                        raise ValueError("Invalid monitor event flag")
                    event, reply = bool(reply[-1]), reply[:-1]
                return decode_result(reply, time.perf_counter() - started, verify), event
            else:
                raise ValueError(f"板卡响应无效，状态 {reply[0]}，长度 {len(reply)}")


class JtagBoard:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def infer(self, features, *, verify=False, progress=lambda _: None):
        if len(features) != FEATURE_BYTES:
            raise ValueError("Expected 99×64 Q16 values")
        xsdb = os.environ.get("Z100_XSDB", "D:/AMDDesignTools/2026.1/Vivado/bin/xsdb.bat")
        script = Path(__file__).with_name("run_jtag_verify.tcl")
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="z100-jtag-") as directory:
            folder = Path(directory)
            (folder / "000.input").write_bytes(features)
            if verify:
                (folder / "000.expected").touch()
            args = [xsdb, script.as_posix(), folder.as_posix()]
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, errors="replace", creationflags=flags) as process:
                messages = []
                for line in process.stdout:
                    if line.startswith("JTAG_LAYER "):
                        progress(int(line.split()[1]))
                    messages.append(line)
                process.wait()
                reply = folder / "000.reply"
                if process.returncode or not reply.exists():
                    detail = next((line.strip() for line in messages
                                   if "timeout" in line.lower() or "error" in line.lower()), "")
                    raise RuntimeError(f"JTAG 推理失败。{detail}")
            return decode_result(reply.read_bytes(), time.perf_counter() - started, verify)


@contextmanager
def connect_for_audio(port, baud=DEMO_BAUD):
    """Start the TCP handshake while the caller reads and encodes the WAV."""
    with ExitStack() as connections:
        if ":" in port:
            host = port.rsplit(":", 1)[0]
            try:
                socket.inet_pton(socket.AF_INET, host)
            except OSError:
                pass
            else:
                # Submit the SYN on the calling thread before decoding. The
                # first inference waits for connect completion before sending.
                board = connections.enter_context(Board(port, baud, start_ipv4=True))
                def acquire():
                    board.stream.wait_connected()
                    return board
                yield acquire
                return
            # Join the opener before unwinding connections, including when
            # decoding fails before the caller obtains the board.
            with ThreadPoolExecutor(max_workers=1) as opener:
                pending = opener.submit(lambda: connections.enter_context(Board(port, baud)))
                yield pending.result
        else:
            def open_device():
                device = JtagBoard() if port.upper() == "JTAG" else Board(port, baud)
                return connections.enter_context(device)
            yield open_device
