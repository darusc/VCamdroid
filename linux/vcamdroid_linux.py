#!/usr/bin/python3
"""VCamdroid Linux Client entry point (GUI and headless CLI)."""

from __future__ import annotations

import argparse
import logging
import os
import platform
import shutil
import signal
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from vcamdroid.adb_manager import AdbManager
from vcamdroid.protocol import StreamOptions, build_resolution_packet
from vcamdroid.rtsp_receiver import RtspReceiver
from vcamdroid.server import ClientSession, ControlServer
from vcamdroid.v4l2_manager import find_v4l2loopback_devices, get_modprobe_command


LOG_DIR_NAME = "vcamdroid"
LOG_FILE_NAME = "vcamdroid.log"


def log_file_path() -> Path:
    """Return the per-user log file path, honouring XDG_STATE_HOME."""
    state_home = os.environ.get("XDG_STATE_HOME")
    base = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
    return base / LOG_DIR_NAME / LOG_FILE_NAME


def setup_logging(verbose: bool = False) -> Path | None:
    """Log to stderr and to a rotating per-user file.

    Returns the log file path, or None when the file could not be created.
    """
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    path: Path | None = None

    try:
        path = log_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
        )
    except (OSError, RuntimeError):
        path = None

    for handler in handlers:
        handler.setFormatter(formatter)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        handlers=handlers,
        force=True,
    )
    return path


def install_exception_hooks(log_path: Path | None) -> None:
    """Log uncaught exceptions from the main thread and from worker threads."""
    logger = logging.getLogger("vcamdroid")

    def handle(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            return
        logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
        if log_path is not None:
            print(f"VCamdroid crashed. Log saved to {log_path}", file=sys.stderr)

    def handle_thread(args: threading.ExceptHookArgs) -> None:
        handle(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = handle
    threading.excepthook = handle_thread


def log_runtime_environment() -> None:
    """Log details that help diagnose platform-specific startup failures."""
    logger = logging.getLogger("vcamdroid")
    logger.info(
        "Starting VCamdroid Linux client (Python %s, %s)",
        platform.python_version(),
        platform.platform(),
    )
    logger.info(
        "Session: type=%s display=%s wayland=%s",
        os.environ.get("XDG_SESSION_TYPE", "unknown"),
        os.environ.get("DISPLAY", "unset"),
        os.environ.get("WAYLAND_DISPLAY", "unset"),
    )
    for tool in ("ffmpeg", "adb", "systemctl", "modprobe"):
        logger.info("Tool %s: %s", tool, shutil.which(tool) or "not found")


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

    log_path = setup_logging(verbose=args.verbose)
    install_exception_hooks(log_path)
    log_runtime_environment()
    if log_path is not None:
        logging.getLogger("vcamdroid").info("Log file: %s", log_path)

    if args.headless:
        return run_headless(args.port, args.device, args.resolution, args.fps)

    try:
        import tkinter as tk
        from vcamdroid.gui import VCamdroidApp
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if missing in ("tkinter", "_tkinter"):
            logging.error(
                "Tkinter is not available in this Python interpreter (%s).\n"
                "Install it with: sudo apt install python3-tk     # Debian/Ubuntu\n"
                "                 sudo dnf install python3-tkinter  # Fedora\n"
                "Or run in CLI mode: python3 %s --headless",
                sys.executable,
                sys.argv[0],
            )
            return 1
        if missing == "PIL" or missing.startswith("PIL."):
            logging.error(
                "Pillow is not available in this Python interpreter (%s).\n"
                "Install it with: sudo apt install python3-pil       # Debian/Ubuntu\n"
                "                 sudo dnf install python3-pillow    # Fedora",
                sys.executable,
            )
            return 1
        raise

    # Match the desktop entry's StartupWMClass instead of Tk's default "Tk".
    try:
        root = tk.Tk(className="vcamdroid")
    except tk.TclError as exc:
        logging.error(
            "Could not open a graphical window (%s).\n"
            "Run this from a desktop session, or use --headless for CLI mode.",
            exc,
        )
        return 1
    VCamdroidApp(root, port=args.port, default_v4l2=args.device)
    root.mainloop()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception:
        logging.getLogger("vcamdroid").critical("Fatal error", exc_info=True)
        try:
            hint = f"\nLog: {log_file_path()}"
        except RuntimeError:
            hint = ""
        print(f"VCamdroid failed to start.{hint}", file=sys.stderr)
        sys.exit(1)
