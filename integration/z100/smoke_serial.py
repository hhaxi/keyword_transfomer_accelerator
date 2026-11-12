"""Exercise the Z100 PS UART and PL register interface."""

import argparse
import struct
import zlib

import serial

MAGIC = b"KW"
HEADER = struct.Struct("<BBII")
WORD = struct.Struct("<I")


def encode(command, request_id, payload=b""):
    body = HEADER.pack(1, command, request_id, len(payload)) + payload
    return MAGIC + body + WORD.pack(zlib.crc32(body))


def read_exact(port, count):
    value = port.read(count)
    if len(value) != count:
        raise TimeoutError(f"Timed out on {port.port} after {len(value)}/{count} bytes")
    return value


def receive_frame(port, command, request_id, max_size=32):
    window = b""
    while window != MAGIC:
        window = window[-1:] + read_exact(port, 1)
    header = read_exact(port, HEADER.size)
    version, reply, received_id, size = HEADER.unpack(header)
    if (version, reply, received_id) != (1, command | 0x80, request_id) or size > max_size:
        raise ValueError(f"Unexpected reply header: {header.hex()}")
    payload = read_exact(port, size)
    (crc,) = WORD.unpack(read_exact(port, WORD.size))
    if crc != zlib.crc32(header + payload) or not payload:
        raise ValueError("Reply CRC or length failed")
    return payload


def transact(port, command, request_id, payload=b""):
    port.write(encode(command, request_id, payload))
    result = receive_frame(port, command, request_id)
    if result[0] != 0:
        raise ValueError(f"Board returned status {result[0]}")
    return result[1:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM8")
    parser.add_argument("--baud", type=int, choices=[115200, 921600], default=115200)
    args = parser.parse_args()
    with serial.Serial(args.port, args.baud, timeout=2, write_timeout=2) as port:
        port.reset_input_buffer()
        identity, version, first_cycle = struct.unpack("<III", transact(port, 1, 1))
        if (identity, version) != (0x4B57545A, 0x00010000):
            raise ValueError(f"Unexpected PL identity/version: {identity:08x}/{version:08x}")
        print(f"PL ID=0x{identity:08x}, version=0x{version:08x}, cycles={first_cycle}")
        for request_id, pattern in enumerate((0x55AA55AA, 0xAA55AA55), 2):
            (value,) = WORD.unpack(transact(port, 2, request_id, WORD.pack(pattern)))
            if value != pattern:
                raise ValueError(f"PL scratch read 0x{value:08x}, expected 0x{pattern:08x}")
            print(f"PL scratch=0x{value:08x}")
        damaged = bytearray(encode(1, 4))
        damaged[-1] ^= 1
        port.write(damaged)
        _, _, last_cycle = struct.unpack("<III", transact(port, 1, 5))
        if not (0 < ((last_cycle - first_cycle) & 0xFFFFFFFF) < 0x80000000):
            raise ValueError("PL cycle counter did not advance")
        print(f"Z100_SMOKE_PASS cycles={last_cycle}, bad CRC ignored")


if __name__ == "__main__":
    main()
