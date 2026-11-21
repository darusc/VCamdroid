"""v4l2loopback virtual webcam detection and helpers."""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class V4L2Device:
    path: str
    label: str


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def find_v4l2loopback_devices() -> list[V4L2Device]:
    """Return available v4l2loopback devices (e.g. /dev/video10)."""
    devices: dict[str, V4L2Device] = {}
    virtual_root = "/sys/devices/virtual/video4linux"
    class_root = "/sys/class/video4linux"

    # Virtual devices created by modprobe v4l2loopback are listed here directly.
    if os.path.isdir(virtual_root):
        for entry in sorted(os.listdir(virtual_root)):
            if not entry.startswith("video"):
                continue
            dev_path = f"/dev/{entry}"
            if not os.path.exists(dev_path):
                continue
            label = _read_text(os.path.join(virtual_root, entry, "name")) or entry
            devices[dev_path] = V4L2Device(path=dev_path, label=label)

    # Some kernels only expose loopback devices through /sys/class/video4linux.
    # Verify via uevent so real cameras are not mistaken for virtual ones.
    if os.path.isdir(class_root):
        for entry in sorted(os.listdir(class_root)):
            if not entry.startswith("video"):
                continue
            dev_path = f"/dev/{entry}"
            if not os.path.exists(dev_path) or dev_path in devices:
                continue
            sys_path = os.path.join(class_root, entry)
            uevent = _read_text(os.path.join(sys_path, "device", "uevent"))
            uevent += _read_text(os.path.join(sys_path, "uevent"))
            if "v4l2loopback" not in uevent.lower() and "v4l2 loopback" not in uevent.lower():
                continue
            label = _read_text(os.path.join(sys_path, "name")) or entry
            devices[dev_path] = V4L2Device(path=dev_path, label=label)

    if devices:
        return list(devices.values())

    # Fallback: probe /dev/video* with v4l2-ctl if sysfs didn't list virtual devices
    v4l2_ctl = shutil.which("v4l2-ctl")
    if v4l2_ctl:
        for dev_path in sorted(glob.glob("/dev/video*")):
            try:
                proc = subprocess.run(
                    [v4l2_ctl, "--device", dev_path, "--info"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if "v4l2loopback" not in proc.stdout.lower() and "v4l2 loopback" not in proc.stdout.lower():
                    continue
                label = dev_path
                for line in proc.stdout.splitlines():
                    if "Card type" in line:
                        label = line.split(":", 1)[1].strip()
                        break
                devices[dev_path] = V4L2Device(path=dev_path, label=label)
            except Exception:
                continue

    return list(devices.values())


def get_modprobe_command(video_nr: int = 10, label: str = "VCamdroid") -> str:
    return f'sudo modprobe v4l2loopback devices=1 video_nr={video_nr} card_label="{label}" exclusive_caps=1'


def refresh_pipewire_cameras() -> tuple[bool, str]:
    """Restart WirePlumber so PipeWire re-enumerates video devices.

    With ``exclusive_caps=1``, v4l2loopback only advertises capture
    capabilities while a producer is writing. If WirePlumber started before
    the stream, it can cache the device as output-only; the GNOME camera portal
    then reports that no camera is present.
    """
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "restart", "wireplumber.service"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        return False, detail or f"systemctl exited with code {proc.returncode}"
    return True, ""
