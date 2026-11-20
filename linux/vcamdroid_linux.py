#!/usr/bin/python3
"""VCamdroid Linux Client entry point (GUI and headless CLI)."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time

from vcamdroid.adb_manager import AdbManager
from vcamdroid.protocol import StreamOptions, build_resolution_packet
from vcamdroid.rtsp_receiver import RtspReceiver
from vcamdroid.server import ClientSession, ControlServer
from vcamdroid.v4l2_manager import find_v4l2loopback_devices, get_modprobe_command


def parse_resolution(value: str) -> tuple[int, int]:
    """argparse type for a WxH resolution string."""
    try:
        parts = value.lower().split("x")
        if len(parts) != 2:
            raise ValueError
        width, height = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid resolution {value!r}; expected WxH, e.g. 1920x1080"
        ) from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("resolution dimensions must be positive")
    return width, height


def run_headless(port: int, v4l2_device: str | None, resolution: tuple[int, int], fps: int) -> int:
    devices = find_v4l2loopback_devices()
    target_dev = v4l2_device or (devices[0].path if devices else None)
    if not target_dev:
        logging.error(
            "No v4l2loopback device found. Create one with:\n  %s",
            get_modprobe_command(),
        )
        return 1

    adb = AdbManager(control_port=port, rtsp_port=8554)
    adb.setup()

    receiver = RtspReceiver()
    active_id: int | None = None
    stop_flag = False

    def on_connected(session: ClientSession) -> None:
        nonlocal active_id
        cid = session.client_id
        if active_id is not None:
            logging.info("Headless: ignoring second client %d (active: %d)", cid, active_id)
            return
        active_id = cid
        try:
            adb.sync_rtsp_port(session.descriptor.rtsp_url)
        except ValueError:
            pass

        init_opts = StreamOptions(fps=fps, resolution=(640, 480))

        def activate() -> None:
            # Do not sleep in the server callback: it would block the read loop
            # for this client and delay disconnect detection.
            time.sleep(0.4)
            if stop_flag or active_id != cid:
                return
            server.send(cid, init_opts.serialize_activation())
            if resolution != (640, 480):
                time.sleep(0.7)
                if stop_flag or active_id != cid:
                    return
                server.send(cid, build_resolution_packet(resolution[0], resolution[1]))
            time.sleep(0.7)
            if stop_flag or active_id != cid:
                return
            receiver.start(session.descriptor.rtsp_url, session.descriptor.protocol, target_dev)

        threading.Thread(target=activate, daemon=True).start()

    def on_disconnected(session: ClientSession) -> None:
        nonlocal active_id
        if active_id == session.client_id:
            receiver.stop()
            active_id = None

    server = ControlServer(
        port=port,
        on_device_connected=on_connected,
        on_device_disconnected=on_disconnected,
    )
    if not server.start():
        adb.cleanup()
        return 1
    _, ip, _ = server.get_host_info()
    logging.info("Headless mode ready. Connect Android app to %s:%d -> %s", ip, port, target_dev)

    def handle_sig(_signum: int, _frame: object) -> None:
        nonlocal stop_flag
        stop_flag = True

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    try:
        while not stop_flag:
            time.sleep(0.25)
    finally:
        receiver.stop()
        server.stop()
        adb.cleanup()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="VCamdroid Linux Client")
    parser.add_argument("--port", type=int, default=6969, help="Control TCP port (default: 6969)")
    parser.add_argument("--device", type=str, default=None, help="v4l2loopback device path (e.g. /dev/video10)")
    parser.add_argument("--headless", action="store_true", help="Run without GUI")
    parser.add_argument(
        "--resolution",
        type=parse_resolution,
        default=(1920, 1080),
        help="Initial resolution for headless mode, WxH (default: 1920x1080)",
    )
    parser.add_argument("--fps", type=int, default=30, help="Initial FPS for headless mode")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if args.headless:
        return run_headless(args.port, args.device, args.resolution, args.fps)

    try:
        import tkinter as tk
        from vcamdroid.gui import VCamdroidApp
    except ModuleNotFoundError as exc:
        if "_tkinter" in str(exc) or "tkinter" in str(exc):
            logging.error(
                "Tkinter is not available in this Python interpreter (%s).\n"
                "Run with the system Python: /usr/bin/python3 %s\n"
                "Or run in CLI mode:         python3 %s --headless",
                sys.executable,
                sys.argv[0],
                sys.argv[0],
            )
            return 1
        raise

    # Match the desktop entry's StartupWMClass instead of Tk's default "Tk".
    root = tk.Tk(className="vcamdroid")
    VCamdroidApp(root, port=args.port, default_v4l2=args.device)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
