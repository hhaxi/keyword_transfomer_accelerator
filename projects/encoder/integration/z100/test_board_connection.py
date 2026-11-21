"""Regressions for starting a fresh board TCP connection before WAV preprocessing."""
import socket
import unittest

from board import connect_for_audio


class BoardConnectionTest(unittest.TestCase):
    def setUp(self):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(self.listener.close)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.listener.settimeout(5)
        self.endpoint = f"127.0.0.1:{self.listener.getsockname()[1]}"

    def test_handshake_starts_before_consumer_acquires_board(self):
        with connect_for_audio(self.endpoint) as acquire:
            peer, _ = self.listener.accept()
            self.addCleanup(peer.close)
            peer.settimeout(5)
            board = acquire()
            self.assertIs(board, acquire())
            board.stream.write(b"x")
            self.assertEqual(peer.recv(1), b"x")
            peer.sendall(b"y")
            self.assertEqual(board.stream.read(1), b"y")

    def test_cleanup_when_audio_fails_before_acquire(self):
        with self.assertRaises(ValueError):
            with connect_for_audio(self.endpoint):
                peer, _ = self.listener.accept()
                self.addCleanup(peer.close)
                peer.settimeout(5)
                raise ValueError("bad WAV")
        self.assertEqual(peer.recv(1), b"")

    def test_refusal_propagates_to_the_request(self):
        # Reserve a port without listening so that nothing else can reuse it.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
            reserved.bind(("127.0.0.1", 0))
            with self.assertRaises(OSError):
                with connect_for_audio(f"127.0.0.1:{reserved.getsockname()[1]}") as acquire:
                    acquire()


if __name__ == "__main__":
    unittest.main()
