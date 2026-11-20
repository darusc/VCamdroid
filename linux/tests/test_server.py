"""Integration tests for TCP framing in the control server."""

from __future__ import annotations

import socket
import struct
import threading
import time
import unittest

from vcamdroid.protocol import ErrorReport, ErrorSeverity
from vcamdroid.server import ControlServer


def _be_str(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


def _descriptor_bytes() -> bytes:
    return _be_str("Pixel 8") + _be_str("rtsp://127.0.0.1:8554/") + struct.pack(">HHH", 0, 0, 0)


def _error_bytes(name: str) -> bytes:
    return bytes([ErrorSeverity.WARNING]) + _be_str(name) + _be_str("description")


class ServerTests(unittest.TestCase):
    def test_reports_are_framed_across_tcp_chunks(self) -> None:
        connected = threading.Event()
        reports: list[ErrorReport] = []

        def on_connected(_session: object) -> None:
            connected.set()

        def on_error(_session: object, report: ErrorReport) -> None:
            reports.append(report)

        server = ControlServer(
            port=0,
            on_device_connected=on_connected,
            on_error_reported=on_error,
        )
        self.assertTrue(server.start())
        try:
            assert server._server_sock is not None
            port = server._server_sock.getsockname()[1]
            with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
                first = _error_bytes("First")
                second = _error_bytes("Second")
                third = _error_bytes("Third")
                # Descriptor and first report arrive in a single segment.
                sock.sendall(_descriptor_bytes() + first)
                self.assertTrue(connected.wait(2))

                # Second report is split, third follows in the next segment.
                sock.sendall(second[:4])
                time.sleep(0.05)
                sock.sendall(second[4:] + third)

                deadline = time.time() + 2
                while len(reports) < 3 and time.time() < deadline:
                    time.sleep(0.01)
                self.assertEqual([report.error for report in reports], ["First", "Second", "Third"])
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
