"""Low-latency FFmpeg RTSP receiver outputting to v4l2loopback and preview callback."""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from collections import deque
from typing import Callable

logger = logging.getLogger(__name__)


class RtspReceiver:
    """Receives an RTSP stream via FFmpeg, writes to v4l2loopback, and emits RGB preview frames.

    Uses a two-stage FFmpeg pipeline (`dump_extra=freq=all` -> decoder) so that
    builds using `libopenh264` (such as Fedora's `ffmpeg-free`) always receive
    in-band SPS/PPS headers from the RTSP SDP `sprop-parameter-sets`.
    """

    PREVIEW_WIDTH = 480
    PREVIEW_HEIGHT = 270

    def __init__(
        self,
        on_preview_frame: Callable[[bytes, int, int], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        self.on_preview_frame = on_preview_frame
        self.on_status = on_status

        self._running = False
        self._thread: threading.Thread | None = None
        self._demux_proc: subprocess.Popen[bytes] | None = None
        self._decode_proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._state_lock = threading.RLock()

        self._url = ""
        self._protocol = "tcp"
        self._v4l2_device: str | None = None

    def start(self, url: str, protocol: str, v4l2_device: str | None) -> None:
        with self._state_lock:
            self.stop()
            if not shutil.which("ffmpeg"):
                msg = "ffmpeg binary not found in PATH"
                logger.error("[RTSP] %s", msg)
                if self.on_status:
                    self.on_status(msg)
                return

            self._url = url
            self._protocol = protocol
            self._v4l2_device = v4l2_device
            self._running = True
            self._thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._state_lock:
            self._running = False
            self._terminate_procs()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=3.0)
            self._thread = None

    def _terminate_procs(self) -> None:
        with self._lock:
            procs = [self._demux_proc, self._decode_proc]
            self._demux_proc = None
            self._decode_proc = None
        for proc in procs:
            if proc is None:
                continue
            try:
                proc.terminate()
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=1.5)
                except Exception:
                    pass

    @staticmethod
    def _drain_stderr(proc: subprocess.Popen[bytes], tag: str, sink: deque[str]) -> None:
        """Keep FFmpeg diagnostics from filling the pipe and log the tail on failure."""
        if proc.stderr is None:
            return
        try:
            for line in proc.stderr:
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    sink.append(f"[{tag}] {text}")
        except (OSError, ValueError):
            pass

    def _build_demux_command(self) -> list[str]:
        return [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "fatal",
            "-rtsp_transport",
            self._protocol,
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-probesize",
            "32",
            "-analyzeduration",
            "0",
            "-i",
            self._url,
            "-map",
            "0:v:0",
            "-c:v",
            "copy",
            "-bsf:v",
            "dump_extra=freq=all",
            "-f",
            "mpegts",
            "pipe:1",
        ]

    def _build_decode_command(self) -> list[str]:
        cmd = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "fatal",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-probesize",
            "32768",
            "-analyzeduration",
            "0",
            "-f",
            "mpegts",
            "-i",
            "pipe:0",
        ]

        if self._v4l2_device:
            cmd.extend([
                "-map",
                "0:v:0",
                "-fps_mode",
                "passthrough",
                "-pix_fmt",
                "yuv420p",
                "-f",
                "v4l2",
                self._v4l2_device,
            ])

        if self.on_preview_frame is not None:
            pw, ph = self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT
            vf = (
                f"scale={pw}:{ph}:force_original_aspect_ratio=decrease,"
                f"pad={pw}:{ph}:(ow-iw)/2:(oh-ih)/2"
            )
            cmd.extend([
                "-map",
                "0:v:0",
                "-fps_mode",
                "passthrough",
                "-vf",
                vf,
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "pipe:1",
            ])

        return cmd

    def _worker_loop(self) -> None:
        frame_bytes = self.PREVIEW_WIDTH * self.PREVIEW_HEIGHT * 3

        while self._running:
            if not self._v4l2_device and self.on_preview_frame is None:
                logger.warning("[RTSP] Neither v4l2 device nor preview callback configured.")
                break

            demux_cmd = self._build_demux_command()
            decode_cmd = self._build_decode_command()
            logger.info("[RTSP] Starting FFmpeg pipeline for %s (%s)", self._url, self._protocol)
            if self.on_status:
                target = self._v4l2_device or "Preview only"
                self.on_status(f"Streaming ({self._protocol.upper()}) -> {target}")

            stderr_lines: deque[str] = deque(maxlen=20)
            stderr_threads: list[threading.Thread] = []
            try:
                demux_proc = subprocess.Popen(
                    demux_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                decode_proc = subprocess.Popen(
                    decode_cmd,
                    stdin=demux_proc.stdout,
                    stdout=subprocess.PIPE if self.on_preview_frame is not None else subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                # Allow demux_proc to receive SIGPIPE if decode_proc exits
                if demux_proc.stdout is not None:
                    demux_proc.stdout.close()

                with self._lock:
                    self._demux_proc = demux_proc
                    self._decode_proc = decode_proc

                for proc, tag in ((demux_proc, "demux"), (decode_proc, "decode")):
                    thread = threading.Thread(
                        target=self._drain_stderr,
                        args=(proc, tag, stderr_lines),
                        daemon=True,
                    )
                    stderr_threads.append(thread)
                    thread.start()

                if self.on_preview_frame is not None and decode_proc.stdout is not None:
                    while self._running:
                        chunk = decode_proc.stdout.read(frame_bytes)
                        if len(chunk) < frame_bytes:
                            break
                        self.on_preview_frame(chunk, self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT)
                else:
                    decode_proc.wait()

            except Exception as exc:
                if self._running:
                    logger.warning("[RTSP] Worker error: %s", exc)
            finally:
                self._terminate_procs()
                for thread in stderr_threads:
                    if thread.is_alive():
                        thread.join(timeout=1.0)
                if self._running and stderr_lines:
                    logger.warning("[RTSP] FFmpeg: %s", " | ".join(stderr_lines))

            if self._running:
                if self.on_status:
                    self.on_status("Reconnecting RTSP stream...")
                time.sleep(0.5)
