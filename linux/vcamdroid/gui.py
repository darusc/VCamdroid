"""Tkinter GUI for the VCamdroid Linux client."""

from __future__ import annotations

import io
import logging
import shutil
import subprocess
import tempfile
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image

from .adb_manager import AdbManager
from .device_state import device_labels, resolve_selection
from .protocol import (
    ErrorReport,
    FilterCategory,
    StreamOptions,
    build_bitrate_packet,
    build_codec_packet,
    build_correction_filter_packet,
    build_effect_filter_packet,
    build_flash_packet,
    build_flip_packet,
    build_fps_packet,
    build_resolution_packet,
    build_rotate_packet,
    build_stabilization_packet,
    build_swap_camera_packet,
    build_zoom_packet,
)
from .rtsp_receiver import RtspReceiver
from .server import ClientSession, ControlServer
from .ui_dispatch import UiDispatcher
from .v4l2_manager import (
    find_v4l2loopback_devices,
    get_modprobe_command,
    refresh_pipewire_cameras,
)

logger = logging.getLogger(__name__)


def _rgb_bytes_to_photo(rgb_bytes: bytes, width: int, height: int) -> tk.PhotoImage:
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    return tk.PhotoImage(data=header + rgb_bytes)


def _pil_to_photo(img: Image.Image) -> tk.PhotoImage:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PPM")
    return tk.PhotoImage(data=buf.getvalue())


def _load_window_icon() -> tk.PhotoImage | None:
    """Load the application icon for the Tk window from the installed theme or sources."""
    module_dir = Path(__file__).resolve().parent
    candidates = (
        Path("/usr/share/icons/hicolor/192x192/apps/vcamdroid.png"),
        module_dir.parent / "icons" / "hicolor" / "192x192" / "apps" / "vcamdroid.png",
        module_dir.parents[1] / "imgs" / "icon2.png",
    )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            icon = tk.PhotoImage(file=str(candidate))
        except Exception:
            try:
                icon = _pil_to_photo(Image.open(candidate))
            except Exception:
                logger.debug("Could not load window icon from %s", candidate, exc_info=True)
                continue
        logger.debug("Loaded window icon from %s", candidate)
        return icon
    return None


def _generate_qr_image(payload: str, size: int = 220) -> Image.Image | None:
    """Generate a PIL QR code image using qrcode or qrencode if available."""
    try:
        import qrcode  # type: ignore

        qr = qrcode.QRCode(border=2, box_size=8)
        qr.add_data(payload)
        qr.make(fit=True)
        return qr.make_image(fill_color="black", back_color="white").convert("RGB").resize((size, size))
    except Exception:
        pass

    qrencode = shutil.which("qrencode")
    if qrencode:
        try:
            with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
                subprocess.run(
                    [qrencode, "-o", tmp.name, "-s", "8", payload],
                    check=True,
                    capture_output=True,
                )
                return Image.open(tmp.name).convert("RGB").resize((size, size))
        except Exception:
            pass

    return None


class VCamdroidApp:
    def __init__(self, root: tk.Tk, port: int = 6969, default_v4l2: str | None = None) -> None:
        self.root = root
        self.root.title("VCamdroid Linux Client")
        # Tk does not pick up the desktop entry's icon by itself.
        self._window_icon = _load_window_icon()
        if self._window_icon is not None:
            self.root.iconphoto(True, self._window_icon)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.port = port
        self.adb = AdbManager(control_port=port, rtsp_port=8554)
        self.server = ControlServer(
            port=port,
            on_device_connected=self._on_device_connected_bg,
            on_device_disconnected=self._on_device_disconnected_bg,
            on_error_reported=self._on_error_reported_bg,
        )
        self.receiver = RtspReceiver(
            on_preview_frame=self._on_preview_frame_bg,
            on_status=self._on_status_bg,
        )

        self.sessions: dict[int, ClientSession] = {}
        self.activated_clients: set[int] = set()
        self.active_client_id: int | None = None
        self.options = StreamOptions()
        self.rotation_degrees = 0
        self.streaming = False

        self._latest_frame: tuple[bytes, int, int] | None = None
        self._frame_lock = threading.Lock()
        self._photo_ref: tk.PhotoImage | None = None
        self._default_v4l2 = default_v4l2

        # Tk may only be touched from the main thread. Background callbacks put
        # closures here; the main-thread poll loop below drains them.
        self._ui = UiDispatcher()

        self._build_ui()
        self._refresh_v4l2_devices()
        self._start_services()
        self._schedule_preview_poll()

    def _build_ui(self) -> None:
        # Top bar: v4l2loopback, device selector, connect/QR buttons
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=tk.X)

        ttk.Label(top, text="Virtual Camera:").pack(side=tk.LEFT)
        self.v4l2_var = tk.StringVar()
        self.v4l2_combo = ttk.Combobox(top, textvariable=self.v4l2_var, state="readonly", width=26)
        self.v4l2_combo.pack(side=tk.LEFT, padx=(4, 4))
        ttk.Button(top, text="Refresh", command=self._refresh_v4l2_devices).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(top, text="Setup v4l2", command=self._show_v4l2_help).pack(side=tk.LEFT, padx=(0, 14))

        ttk.Label(top, text="Device:").pack(side=tk.LEFT)
        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(top, textvariable=self.device_var, state="readonly", width=24)
        self.device_combo.pack(side=tk.LEFT, padx=(4, 6))
        self.device_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_device_selected())

        self.stream_btn = ttk.Button(top, text="Start Stream", command=self._toggle_stream, state=tk.DISABLED)
        self.stream_btn.pack(side=tk.LEFT, padx=(0, 6))

        ttk.Button(top, text="Wi-Fi QR Code", command=self._show_qr_dialog).pack(side=tk.RIGHT)

        # Main area: Preview on left, Controls on right
        main = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        main.pack(fill=tk.BOTH, expand=True)

        preview_frame = ttk.LabelFrame(main, text="Live Preview", padding=4)
        preview_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.preview_label = ttk.Label(preview_frame, text="Waiting for Android device...", anchor=tk.CENTER)
        self.preview_label.pack(fill=tk.BOTH, expand=True)
        # Set a sensible minimum preview area (960x540 16:9)
        blank = _rgb_bytes_to_photo(
            b"\x18\x18\x1c" * (RtspReceiver.PREVIEW_WIDTH * RtspReceiver.PREVIEW_HEIGHT),
            RtspReceiver.PREVIEW_WIDTH,
            RtspReceiver.PREVIEW_HEIGHT,
        )
        self._photo_ref = blank
        self.preview_label.configure(image=blank)

        controls = ttk.LabelFrame(main, text="Camera & Stream Controls", padding=8)
        controls.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))

        # Camera & orientation row
        cam_row = ttk.Frame(controls)
        cam_row.pack(fill=tk.X, pady=3)
        ttk.Button(cam_row, text="Swap Camera", command=self._swap_camera).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        ttk.Button(cam_row, text="Rotate 90°", command=self._rotate_camera).pack(side=tk.LEFT, fill=tk.X, expand=True)

        flip_row = ttk.Frame(controls)
        flip_row.pack(fill=tk.X, pady=3)
        ttk.Button(flip_row, text="Flip H", command=lambda: self._flip(True)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        ttk.Button(flip_row, text="Flip V", command=lambda: self._flip(False)).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Resolution & FPS
        res_row = ttk.Frame(controls)
        res_row.pack(fill=tk.X, pady=4)
        ttk.Label(res_row, text="Resolution:").pack(side=tk.LEFT)
        self.res_var = tk.StringVar(value="1920x1080")
        self.res_combo = ttk.Combobox(res_row, textvariable=self.res_var, state="readonly", width=12)
        self.res_combo.pack(side=tk.RIGHT)
        self.res_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_resolution_changed())

        fps_row = ttk.Frame(controls)
        fps_row.pack(fill=tk.X, pady=4)
        ttk.Label(fps_row, text="FPS:").pack(side=tk.LEFT)
        self.fps_var = tk.StringVar(value="30")
        self.fps_combo = ttk.Combobox(fps_row, textvariable=self.fps_var, values=["15", "24", "30", "60"], state="readonly", width=12)
        self.fps_combo.pack(side=tk.RIGHT)
        self.fps_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_fps_changed())

        # Toggles
        self.flash_var = tk.BooleanVar(value=False)
        self.stab_var = tk.BooleanVar(value=False)
        self.h265_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="Flash / Torch", variable=self.flash_var, command=self._on_flash_changed).pack(anchor=tk.W, pady=2)
        ttk.Checkbutton(controls, text="Stabilization", variable=self.stab_var, command=self._on_stab_changed).pack(anchor=tk.W, pady=2)
        ttk.Checkbutton(controls, text="H.265 / HEVC", variable=self.h265_var, command=self._on_h265_changed).pack(anchor=tk.W, pady=2)

        # Zoom
        ttk.Label(controls, text="Zoom (1.0x - 4.0x):").pack(anchor=tk.W, pady=(6, 0))
        self.zoom_var = tk.DoubleVar(value=1.0)
        zoom_scale = ttk.Scale(controls, from_=1.0, to=4.0, variable=self.zoom_var, command=self._on_zoom_changed)
        zoom_scale.pack(fill=tk.X, pady=2)

        # Bitrate
        ttk.Label(controls, text="Bitrate (kbps):").pack(anchor=tk.W, pady=(6, 0))
        self.bitrate_var = tk.IntVar(value=8000)
        bitrate_scale = ttk.Scale(controls, from_=500, to=25000, variable=self.bitrate_var, command=self._on_bitrate_changed)
        bitrate_scale.pack(fill=tk.X, pady=2)

        # Effect filter
        eff_row = ttk.Frame(controls)
        eff_row.pack(fill=tk.X, pady=6)
        ttk.Label(eff_row, text="Effect:").pack(side=tk.LEFT)
        self.effect_var = tk.StringVar(value="None")
        self.effect_combo = ttk.Combobox(eff_row, textvariable=self.effect_var, values=["None"], state="readonly", width=14)
        self.effect_combo.pack(side=tk.RIGHT)
        self.effect_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_effect_changed())

        # Correction filters container
        self.corr_frame = ttk.LabelFrame(controls, text="Image Adjustments", padding=4)
        self.corr_frame.pack(fill=tk.X, pady=(6, 0))
        self.corr_sliders: dict[str, tk.IntVar] = {}

        # Status bar
        self.status_var = tk.StringVar(value="Starting server...")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=(6, 3))
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def _start_services(self) -> None:
        adb_ok = self.adb.setup()
        if not self.server.start():
            self.status_var.set(f"Could not bind TCP port {self.port} (address already in use)")
            messagebox.showerror(
                "VCamdroid Linux Client",
                f"Could not listen on TCP port {self.port}.\n"
                "Another application may be using it, or try --port <other>.",
            )
            return
        _, ip, port = self.server.get_host_info()
        adb_note = "ADB ready" if adb_ok else "ADB unavailable (Wi-Fi mode only)"
        self.status_var.set(f"Listening on {ip}:{port} | {adb_note}")

    def _refresh_v4l2_devices(self) -> None:
        devices = find_v4l2loopback_devices()
        items = [f"{d.path} ({d.label})" for d in devices]
        if not items:
            items = ["Preview only (no v4l2loopback)"]
        self.v4l2_combo["values"] = items

        if self._default_v4l2:
            for item in items:
                if item.startswith(self._default_v4l2):
                    self.v4l2_var.set(item)
                    return
        self.v4l2_var.set(items[0])

    def _selected_v4l2_path(self) -> str | None:
        val = self.v4l2_var.get()
        if val.startswith("/dev/"):
            return val.split(" ", 1)[0]
        return None

    def _show_v4l2_help(self) -> None:
        cmd = get_modprobe_command()
        dlg = tk.Toplevel(self.root)
        dlg.title("v4l2loopback Setup")
        dlg.resizable(False, False)
        frame = ttk.Frame(dlg, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            frame,
            text=(
                "Run this command in a terminal to create a virtual webcam device,\n"
                "then click Refresh.\n\n"
                "If GNOME Camera/Snapshot still does not list it while streaming,\n"
                "click Refresh Camera Detection (restarts WirePlumber)."
            ),
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 8))
        entry = ttk.Entry(frame, width=78)
        entry.insert(0, cmd)
        entry.configure(state="readonly")
        entry.pack(fill=tk.X, pady=(0, 8))

        def copy_cmd() -> None:
            self.root.clipboard_clear()
            self.root.clipboard_append(cmd)

        def refresh_camera_detection() -> None:
            ok, detail = refresh_pipewire_cameras()
            if ok:
                messagebox.showinfo(
                    "VCamdroid Linux Client",
                    "WirePlumber restarted. Reopen the camera application and "
                    "select 'Virtual Camera (V4L2)'.",
                    parent=dlg,
                )
            else:
                messagebox.showwarning(
                    "VCamdroid Linux Client",
                    "Could not restart WirePlumber.\n\n"
                    f"{detail}\n\n"
                    "Try manually: systemctl --user restart wireplumber",
                    parent=dlg,
                )

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=tk.X)
        ttk.Button(btn_row, text="Copy Command", command=copy_cmd).pack(side=tk.LEFT)
        ttk.Button(
            btn_row,
            text="Refresh Camera Detection",
            command=refresh_camera_detection,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(btn_row, text="Close", command=dlg.destroy).pack(side=tk.RIGHT)

    def _show_qr_dialog(self) -> None:
        _, ip, port = self.server.get_host_info()
        payload = f"{ip}:{port}"

        dlg = tk.Toplevel(self.root)
        dlg.title("Connect via Wi-Fi")
        dlg.resizable(False, False)
        frame = ttk.Frame(dlg, padding=16)
        frame.pack()

        ttk.Label(frame, text="Scan with the VCamdroid Android app:").pack(pady=(0, 8))
        img = _generate_qr_image(payload)
        if img is not None:
            photo = _pil_to_photo(img)
            lbl = ttk.Label(frame, image=photo)
            lbl.image = photo  # keep reference
            lbl.pack(pady=(0, 8))
        else:
            ttk.Label(
                frame,
                text="(Install 'qrcode[pil]' or 'qrencode' to render QR image)",
                foreground="gray",
            ).pack(pady=(0, 6))

        ttk.Label(frame, text=payload, font=("TkDefaultFont", 12, "bold")).pack(pady=(0, 8))
        ttk.Button(frame, text="Close", command=dlg.destroy).pack()

    # --- Background callbacks marshaled to the Tkinter main thread ---

    def _enqueue_ui(self, task: Callable[[], None]) -> None:
        """Hand work to the main thread; never touch Tk from a worker thread."""
        self._ui.post(task)

    def _on_device_connected_bg(self, session: ClientSession) -> None:
        self._enqueue_ui(lambda: self._handle_device_connected(session))

    def _on_device_disconnected_bg(self, session: ClientSession) -> None:
        self._enqueue_ui(lambda: self._handle_device_disconnected(session))

    def _on_error_reported_bg(self, session: ClientSession, report: ErrorReport) -> None:
        self._enqueue_ui(
            lambda: messagebox.showwarning(
                f"{session.descriptor.name}: {report.error}", report.description
            )
        )

    def _on_status_bg(self, msg: str) -> None:
        self._enqueue_ui(lambda: self.status_var.set(msg))

    def _on_preview_frame_bg(self, rgb_bytes: bytes, width: int, height: int) -> None:
        with self._frame_lock:
            self._latest_frame = (rgb_bytes, width, height)

    def _drain_ui_queue(self) -> None:
        self._ui.drain(on_error=lambda exc: logger.error("UI callback failed: %s", exc))

    def _schedule_preview_poll(self) -> None:
        self._drain_ui_queue()
        frame = None
        with self._frame_lock:
            if self._latest_frame is not None:
                frame = self._latest_frame
                self._latest_frame = None
        if frame is not None:
            rgb_bytes, w, h = frame
            photo = _rgb_bytes_to_photo(rgb_bytes, w, h)
            self._photo_ref = photo
            self.preview_label.configure(image=photo)
        # Frames arrive at the stream FPS (usually 30); polling faster only
        # wastes main-thread time copying ~0.4 MB PPM buffers into Tk.
        self.root.after(33, self._schedule_preview_poll)

    # --- Device & stream lifecycle ---

    def _handle_device_connected(self, session: ClientSession) -> None:
        self.sessions[session.client_id] = session
        try:
            self.adb.sync_rtsp_port(session.descriptor.rtsp_url)
        except ValueError:
            pass
        first_device = self.active_client_id is None
        self._update_device_dropdown()
        if first_device and self.active_client_id == session.client_id:
            # Give Android SurfaceView 400ms to finish surfaceCreated() before ACTIVATION
            self.root.after(400, self._start_stream)

    def _handle_device_disconnected(self, session: ClientSession) -> None:
        self.sessions.pop(session.client_id, None)
        self.activated_clients.discard(session.client_id)
        if self.active_client_id == session.client_id:
            self._stop_stream()
        self._update_device_dropdown()
        if not self.sessions:
            self.stream_btn.configure(state=tk.DISABLED)
            _, ip, port = self.server.get_host_info()
            self.status_var.set(f"Device disconnected | Listening on {ip}:{port}")

    def _update_device_dropdown(self) -> None:
        previous_id = self.active_client_id
        self.device_combo["values"] = device_labels(self.sessions)
        active_id, selected = resolve_selection(previous_id, self.sessions)
        self.active_client_id = active_id
        self.device_var.set(selected)
        if active_id is not None and active_id != previous_id:
            self._select_device_in_ui(self.sessions[active_id])

    def _on_device_selected(self) -> None:
        val = self.device_var.get()
        if not val.startswith("["):
            return
        cid = int(val.split("]", 1)[0][1:])
        if cid in self.sessions and cid != self.active_client_id:
            self._stop_stream()
            self.active_client_id = cid
            self._select_device_in_ui(self.sessions[cid])

    def _select_device_in_ui(self, session: ClientSession) -> None:
        self.stream_btn.configure(state=tk.NORMAL)
        self._populate_resolutions(session)
        self._populate_filters(session)

    def _populate_resolutions(self, session: ClientSession) -> None:
        res_list = (
            session.descriptor.back_resolutions
            if self.options.back_camera_active
            else session.descriptor.front_resolutions
        )
        # Filter to hardware video encoder ceiling (1920x1080 Full HD)
        supported = [(w, h) for w, h in res_list if w <= 1920 and h <= 1080]
        if not supported:
            supported = res_list or [(1920, 1080)]
        # Sort highest pixel count first
        supported.sort(key=lambda r: r[0] * r[1], reverse=True)
        values = [f"{w}x{h}" for w, h in supported]
        self.res_combo["values"] = values
        default_res = "1920x1080" if "1920x1080" in values else values[0]
        self.res_var.set(default_res)
        w, h = map(int, default_res.split("x"))
        self.options.resolution = (w, h)

    def _populate_filters(self, session: ClientSession) -> None:
        for child in self.corr_frame.winfo_children():
            child.destroy()
        self.corr_sliders.clear()

        corr_filters = session.descriptor.filters.get(FilterCategory.CORRECTION, [])
        for fname in corr_filters:
            row = ttk.Frame(self.corr_frame)
            row.pack(fill=tk.X, pady=1)
            ttk.Label(row, text=fname, width=11).pack(side=tk.LEFT)
            var = tk.IntVar(value=50)
            self.corr_sliders[fname] = var
            scale = ttk.Scale(
                row,
                from_=0,
                to=100,
                variable=var,
                command=lambda _v, name=fname, v=var: self._on_correction_filter(name, int(v.get())),
            )
            scale.pack(side=tk.RIGHT, fill=tk.X, expand=True)

        effects = ["None"]
        for cat in (FilterCategory.EFFECT, FilterCategory.ARTISTIC, FilterCategory.DISTORTION):
            effects.extend(session.descriptor.filters.get(cat, []))
        self.effect_combo["values"] = effects
        self.effect_var.set("None")

    def _toggle_stream(self) -> None:
        if self.streaming:
            self._stop_stream()
        else:
            self._start_stream()

    def _start_stream(self) -> None:
        if self.active_client_id is None or self.active_client_id not in self.sessions:
            return
        session = self.sessions[self.active_client_id]
        self.streaming = True
        self.stream_btn.configure(text="Stop Stream")

        if session.client_id not in self.activated_clients:
            self.activated_clients.add(session.client_id)
            target_res = self.options.resolution
            if target_res != (640, 480):
                # Activate at 640x480 first to match Android's initial SurfaceView preview
                # (avoiding OpenGlView GL error 1285), then switch to target_res via RESOLUTION packet.
                init_opts = StreamOptions(
                    fps=self.options.fps,
                    resolution=(640, 480),
                    back_camera_active=self.options.back_camera_active,
                    adaptive_bitrate=self.options.adaptive_bitrate,
                    bitrate=self.options.bitrate,
                    min_bitrate=self.options.min_bitrate,
                    max_bitrate=self.options.max_bitrate,
                    stabilization_enabled=self.options.stabilization_enabled,
                    flash_enabled=self.options.flash_enabled,
                    h265_enabled=self.options.h265_enabled,
                    focus_mode=self.options.focus_mode,
                    filter_slider_values=dict(self.options.filter_slider_values),
                    active_effect_filter=self.options.active_effect_filter,
                )
                self.server.send(session.client_id, init_opts.serialize_activation())
                self.root.after(
                    700,
                    lambda cid=session.client_id, r=target_res: self._apply_initial_resolution_and_start(cid, r),
                )
            else:
                self.server.send(session.client_id, self.options.serialize_activation())
                self.root.after(
                    600,
                    lambda cid=session.client_id: self._start_receiver_for_client(cid),
                )
        else:
            self._start_receiver_for_client(session.client_id)

    def _apply_initial_resolution_and_start(self, client_id: int, resolution: tuple[int, int]) -> None:
        if not self.streaming or self.active_client_id != client_id:
            return
        self.server.send(client_id, build_resolution_packet(resolution[0], resolution[1]))
        self.root.after(
            700,
            lambda cid=client_id: self._start_receiver_for_client(cid),
        )

    def _start_receiver_for_client(self, client_id: int) -> None:
        if not self.streaming or self.active_client_id != client_id:
            return
        session = self.sessions.get(client_id)
        if not session:
            return
        self.receiver.start(
            url=session.descriptor.rtsp_url,
            protocol=session.descriptor.protocol,
            v4l2_device=self._selected_v4l2_path(),
        )

    def _stop_stream(self) -> None:
        self.receiver.stop()
        self.streaming = False
        self.stream_btn.configure(text="Start Stream")

    def _send_cmd(self, payload: bytes) -> None:
        if self.active_client_id is not None:
            self.server.send(self.active_client_id, payload)

    # --- Control handlers ---

    def _swap_camera(self) -> None:
        self.options.back_camera_active = not self.options.back_camera_active
        self._send_cmd(build_swap_camera_packet())
        if self.active_client_id in self.sessions:
            self._populate_resolutions(self.sessions[self.active_client_id])

    def _rotate_camera(self) -> None:
        self.rotation_degrees = (self.rotation_degrees + 90) % 360
        self._send_cmd(build_rotate_packet(self.rotation_degrees))

    def _flip(self, horizontal: bool) -> None:
        self._send_cmd(build_flip_packet(horizontal))

    def _on_resolution_changed(self) -> None:
        w, h = map(int, self.res_var.get().split("x"))
        self.options.resolution = (w, h)
        self._send_cmd(build_resolution_packet(w, h))
        if self.streaming and self.active_client_id is not None:
            self.receiver.stop()
            cid = self.active_client_id
            self.root.after(700, lambda: self._start_receiver_for_client(cid))

    def _on_fps_changed(self) -> None:
        fps = int(self.fps_var.get())
        self.options.fps = fps
        self._send_cmd(build_fps_packet(fps))
        if self.streaming and self.active_client_id is not None:
            self.receiver.stop()
            cid = self.active_client_id
            self.root.after(700, lambda: self._start_receiver_for_client(cid))

    def _on_flash_changed(self) -> None:
        val = self.flash_var.get()
        self.options.flash_enabled = val
        self._send_cmd(build_flash_packet(val))

    def _on_stab_changed(self) -> None:
        val = self.stab_var.get()
        self.options.stabilization_enabled = val
        self._send_cmd(build_stabilization_packet(val))

    def _on_h265_changed(self) -> None:
        val = self.h265_var.get()
        self.options.h265_enabled = val
        self._send_cmd(build_codec_packet(val))

    def _on_zoom_changed(self, _val: str) -> None:
        factor = round(self.zoom_var.get(), 2)
        self.options.zoom = factor
        self._send_cmd(build_zoom_packet(factor))

    def _on_bitrate_changed(self, _val: str) -> None:
        br = int(self.bitrate_var.get())
        self.options.bitrate = br
        self._send_cmd(build_bitrate_packet(br))

    def _on_correction_filter(self, name: str, value: int) -> None:
        self.options.filter_slider_values[name] = value
        self._send_cmd(build_correction_filter_packet(name, value))

    def _on_effect_changed(self) -> None:
        effect = self.effect_var.get()
        self.options.active_effect_filter = "" if effect == "None" else effect
        self._send_cmd(build_effect_filter_packet(self.options.active_effect_filter))

    def on_close(self) -> None:
        self._stop_stream()
        self.server.stop()
        self.adb.cleanup()
        self.root.destroy()
