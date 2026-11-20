"""TCP control server for VCamdroid Android clients."""

from __future__ import annotations

import logging
import socket
import threading
from dataclasses import dataclass, field
from typing import Callable

from .protocol import (
    DeviceDescriptor,
    ErrorReport,
    TruncatedDescriptorError,
    TruncatedErrorReportError,
)

logger = logging.getLogger(__name__)

MAX_PENDING_BYTES = 65536


@dataclass
class ClientSession:
    client_id: int
    sock: socket.socket
    address: tuple[str, int]
    descriptor: DeviceDescriptor
    send_lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)


class ControlServer:
    """Listens for Android control connections on TCP port 6969."""

    def __init__(
        self,
        port: int = 6969,
        on_device_connected: Callable[[ClientSession], None] | None = None,
        on_device_disconnected: Callable[[ClientSession], None] | None = None,
        on_error_reported: Callable[[ClientSession, ErrorReport], None] | None = None,
    ) -> None:
        self.port = port
        self.on_device_connected = on_device_connected
        self.on_device_disconnected = on_device_disconnected
        self.on_error_reported = on_error_reported

        self._server_sock: socket.socket | None = None
        self._running = False
        self._accept_thread: threading.Thread | None = None
        self._client_threads: set[threading.Thread] = set()
        self._sessions: dict[int, ClientSession] = {}
        self._lock = threading.Lock()
        self._next_id = 0

    @staticmethod
    def get_local_ip() -> str:
        """Detect the active LAN IPv4 address without sending external traffic."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"

    def get_host_info(self) -> tuple[str, str, int]:
        return socket.gethostname(), self.get_local_ip(), self.port

    def start(self) -> bool:
        """Start listening. Returns False (with a log message) if bind fails."""
        if self._running:
            return True

        sock: socket.socket | None = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", self.port))
            sock.listen(5)
            sock.settimeout(0.5)
        except OSError as exc:
            logger.error("[SERVER] Cannot listen on 0.0.0.0:%d: %s", self.port, exc)
            if sock is not None:
                sock.close()
            return False

        self._server_sock = sock
        self._running = True
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        logger.info("[SERVER] Listening on 0.0.0.0:%d", self.port)
        return True

    def stop(self) -> None:
        self._running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass
            self._server_sock = None

        with self._lock:
            sessions = list(self._sessions.values())
            threads = list(self._client_threads)
            self._sessions.clear()

        for session in sessions:
            try:
                # close() alone does not always wake a thread blocked in recv().
                session.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                session.sock.close()
            except OSError:
                pass

        if self._accept_thread and self._accept_thread.is_alive():
            self._accept_thread.join(timeout=2.0)
        for thread in threads:
            if thread is not threading.current_thread() and thread.is_alive():
                thread.join(timeout=2.0)
        logger.info("[SERVER] Stopped.")

    def send(self, client_id: int, data: bytes) -> bool:
        with self._lock:
            session = self._sessions.get(client_id)
        if not session:
            return False
        try:
            # A packet must be written atomically or interleaving sendall()
            # calls from multiple threads would corrupt the command stream.
            with session.send_lock:
                session.sock.sendall(data)
            return True
        except OSError as exc:
            logger.warning("[SERVER] Send failed for client %d: %s", client_id, exc)
            return False

    def get_sessions(self) -> list[ClientSession]:
        with self._lock:
            return list(self._sessions.values())

    def _accept_loop(self) -> None:
        while self._running and self._server_sock:
            try:
                conn, addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            thread = threading.Thread(
                target=self._handle_client,
                args=(conn, addr),
                daemon=True,
            )
            with self._lock:
                self._client_threads.add(thread)
            thread.start()

    def _handle_client(self, conn: socket.socket, addr: tuple[str, int]) -> None:
        logger.info("[SERVER] Accepted TCP connection from %s:%d", addr[0], addr[1])
        session: ClientSession | None = None
        try:
            buf = bytearray()
            descriptor: DeviceDescriptor | None = None
            consumed = 0
            while self._running:
                chunk = conn.recv(4096)
                if not chunk:
                    logger.info("[SERVER] Connection closed by %s:%d before DeviceDescriptor", addr[0], addr[1])
                    return
                buf.extend(chunk)
                logger.debug(
                    "[SERVER] Received %d bytes (%d total) %r from %s:%d",
                    len(chunk),
                    len(buf),
                    bytes(chunk),
                    addr[0],
                    addr[1],
                )
                try:
                    descriptor, consumed = DeviceDescriptor.deserialize_with_offset(bytes(buf))
                    break
                except TruncatedDescriptorError as exc:
                    logger.debug("[SERVER] Waiting for more DeviceDescriptor bytes (%s)", exc)
                    if len(buf) > MAX_PENDING_BYTES:
                        raise
                    continue

            if descriptor is None:
                return

            # ErrorReports may follow the descriptor in the same TCP segment.
            del buf[:consumed]

            with self._lock:
                client_id = self._next_id
                self._next_id += 1
                session = ClientSession(
                    client_id=client_id,
                    sock=conn,
                    address=addr,
                    descriptor=descriptor,
                )
                self._sessions[client_id] = session

            logger.info(
                "[SERVER] Connected: %s (%s) from %s:%d [id=%d]",
                descriptor.name,
                descriptor.rtsp_url,
                addr[0],
                addr[1],
                client_id,
            )
            if self.on_device_connected:
                self.on_device_connected(session)

            # Read loop for incoming ErrorReports and disconnect detection.
            # Android sends each report with a separate send(), but TCP gives
            # us a byte stream: buffer partial reports and drain every complete
            # one from each chunk.
            while self._running:
                data = conn.recv(4096)
                if not data:
                    break
                buf.extend(data)

                offset = 0
                while offset < len(buf):
                    try:
                        report, report_end = ErrorReport.deserialize_with_offset(bytes(buf), offset)
                    except TruncatedErrorReportError as exc:
                        logger.debug("[SERVER] Waiting for more ErrorReport bytes (%s)", exc)
                        break
                    except ValueError as exc:
                        logger.debug("[SERVER] Unparsed packet from %s: %s", descriptor.name, exc)
                        offset += 1
                        continue
                    offset = report_end
                    logger.warning(
                        "[DEVICE %s] %s: %s",
                        descriptor.name,
                        report.error,
                        report.description,
                    )
                    if self.on_error_reported:
                        self.on_error_reported(session, report)

                if offset:
                    del buf[:offset]
                if len(buf) > MAX_PENDING_BYTES:
                    logger.warning("[SERVER] Discarding oversized unparsed buffer from %s", descriptor.name)
                    buf.clear()

        except Exception as exc:
            logger.warning("[SERVER] Client %s error: %s", addr, exc)
        finally:
            with self._lock:
                self._client_threads.discard(threading.current_thread())
            if session is not None:
                with self._lock:
                    self._sessions.pop(session.client_id, None)
                logger.info("[SERVER] Disconnected: %s [id=%d]", session.descriptor.name, session.client_id)
                if self.on_device_disconnected:
                    self.on_device_disconnected(session)
            try:
                conn.close()
            except OSError:
                pass
