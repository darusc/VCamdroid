"""ADB port forwarding helper for USB connections."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


class AdbManager:
    def __init__(self, control_port: int = 6969, rtsp_port: int = 8554) -> None:
        self.control_port = control_port
        self.rtsp_port = rtsp_port
        self.adb_path = shutil.which("adb") or self._find_sdk_adb()
        self._reverse_created = False
        self._forward_created = False

    @staticmethod
    def _find_sdk_adb() -> str | None:
        for base in (
            os.environ.get("ANDROID_HOME"),
            os.environ.get("ANDROID_SDK_ROOT"),
            os.path.expanduser("~/Android/Sdk"),
            os.path.expanduser("~/android-sdk"),
        ):
            if base:
                candidate = os.path.join(base, "platform-tools", "adb")
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    return candidate
        return None

    @property
    def available(self) -> bool:
        return self.adb_path is not None

    def _run(self, *args: str) -> tuple[bool, str]:
        if not self.adb_path:
            return False, "adb binary not found in PATH"
        try:
            proc = subprocess.run(
                [self.adb_path, *args],
                capture_output=True,
                text=True,
                timeout=5,
            )
            ok = proc.returncode == 0
            output = (proc.stdout or proc.stderr).strip()
            return ok, output
        except Exception as exc:
            return False, str(exc)

    def setup(self) -> bool:
        """Set up adb reverse (control) and forward (RTSP) tunnels."""
        if not self.available:
            logger.warning("[ADB] 'adb' not found in PATH. USB mode unavailable; Wi-Fi mode still works.")
            return False

        ok_rev, out_rev = self._run("reverse", f"tcp:{self.control_port}", f"tcp:{self.control_port}")
        if ok_rev:
            self._reverse_created = True
            logger.info("[ADB] Reversed tcp:%d -> tcp:%d", self.control_port, self.control_port)
        else:
            logger.warning("[ADB] Failed to reverse tcp:%d (%s)", self.control_port, out_rev)

        ok_fwd = self._setup_forward()
        return ok_rev and ok_fwd

    def _setup_forward(self) -> bool:
        ok, out = self._run("forward", f"tcp:{self.rtsp_port}", f"tcp:{self.rtsp_port}")
        if ok:
            self._forward_created = True
            logger.info("[ADB] Forwarded tcp:%d -> tcp:%d", self.rtsp_port, self.rtsp_port)
        else:
            logger.warning("[ADB] Failed to forward tcp:%d (%s)", self.rtsp_port, out)
        return ok

    def sync_rtsp_port(self, rtsp_url: str) -> None:
        """Match the ADB RTSP forward to the port advertised by a connected device."""
        try:
            port = urlsplit(rtsp_url).port
        except ValueError:
            return
        if port is None or port == self.rtsp_port or not self.available:
            return
        self._run("forward", "--remove", f"tcp:{self.rtsp_port}")
        self.rtsp_port = port
        self._setup_forward()

    def cleanup(self) -> None:
        """Remove adb port mappings created by this client."""
        if not self.available:
            return
        if self._reverse_created:
            self._run("reverse", "--remove", f"tcp:{self.control_port}")
            self._reverse_created = False
        if self._forward_created:
            self._run("forward", "--remove", f"tcp:{self.rtsp_port}")
            self._forward_created = False
        logger.info("[ADB] Cleaned up port mappings.")
