# VCamdroid Linux Client

Python client for Linux that receives the VCamdroid Android RTSP stream and exposes it as a virtual webcam using `v4l2loopback` and `ffmpeg`.

## Prerequisites

- **Python 3.10+** with `tkinter` and `Pillow`
- **FFmpeg** (`ffmpeg` in `PATH`): on Fedora, either `ffmpeg-free` or RPM Fusion's `ffmpeg`; on Debian/Ubuntu, the official `ffmpeg` package
- **v4l2loopback** kernel module
- *(Optional)* **ADB** (`adb` in `PATH`) for wired USB mode
- *(Optional)* `qrcode` (`pip install -r requirements.txt`) or `qrencode` for rendering the Wi-Fi pairing QR code

## Create the Virtual Webcam

Load `v4l2loopback` before starting the client (using `exclusive_caps=1` so Zoom, OBS, Chrome, and Discord detect it):

```bash
sudo modprobe v4l2loopback devices=1 video_nr=10 card_label="VCamdroid" exclusive_caps=1
```

## Usage

### GUI Mode
```bash
python3 vcamdroid_linux.py
```

### Headless CLI Mode
```bash
python3 vcamdroid_linux.py --headless --device /dev/video10 --resolution 1280x720 --fps 30
```

## Tests

From this directory:

```bash
python3 -m unittest discover -s tests -v
```

Or install the package first to import `vcamdroid` from anywhere:

```bash
python3 -m pip install -e .
python3 -m unittest discover -s linux/tests -v   # from the repository root
```

## Native packages (RPM / DEB)

From the repository root:

```bash
/usr/bin/python3 linux/packaging/build_packages.py          # both packages
/usr/bin/python3 linux/packaging/build_packages.py --rpm    # RPM only
/usr/bin/python3 linux/packaging/build_packages.py --deb    # DEB only
```

Requires `rpmbuild` for the RPM and `ar`/`tar` for the DEB. Artifacts are written
to `linux/dist/` (git-ignored).

The packages install the sources under `/usr/lib/vcamdroid`, a launcher at
`/usr/bin/vcamdroid` that uses the system Python (needed for tkinter), and the
application icon in the hicolor theme. On Fedora the RPM requires
`ffmpeg-free` **or** `ffmpeg` (so it will not replace your `ffmpeg-free` with
RPM Fusion's `ffmpeg`); on Debian/Ubuntu the DEB requires the regular `ffmpeg`
package. `python3-qrcode` is required by the RPM and recommended by the DEB;
`adb` and `v4l2loopback` are recommended on both.

Install from a local build:

```bash
sudo dnf install ./linux/dist/vcamdroid-0.1.0-7.fc44.noarch.rpm
sudo apt install ./linux/dist/vcamdroid_0.1.0_all.deb
```

Or from the committed artifacts:

```bash
sudo dnf install ./releases/vcamdroid-0.1.0-7.fc44.noarch.rpm
sudo apt install ./releases/vcamdroid_0.1.0_all.deb
```

Upgrade or remove the RPM with:

```bash
sudo dnf upgrade ./releases/vcamdroid-0.1.0-7.fc44.noarch.rpm
sudo dnf remove vcamdroid
```

If the launcher icon looks stale, refresh the caches (the packages already do
this on install) and log out/in:

```bash
sudo gtk-update-icon-cache -f -t /usr/share/icons/hicolor
sudo update-desktop-database /usr/share/applications
```

## Troubleshooting

### The app fails to start

Run it from a terminal to see the error:

```bash
vcamdroid
```

The client also writes a rotating log to
`~/.local/state/vcamdroid/vcamdroid.log` (or
`$XDG_STATE_HOME/vcamdroid/vcamdroid.log` when that variable is set). Include
that file when reporting a startup problem. When launched from the desktop, the
same output is available in the user journal:

```bash
journalctl --user -b | grep -i vcamdroid | tail -50
```

Use `vcamdroid -v` for debug-level output. Common causes: missing `python3-tk`
or `python3-pil`, `adb` not installed (Wi-Fi mode still works), and no graphical
session (`--headless` works over SSH).

### GNOME Camera / Snapshot does not list the virtual camera

With `exclusive_caps=1`, `v4l2loopback` only advertises capture capabilities
while a producer is writing. If WirePlumber started before the stream, it can
keep the device as output-only and the GNOME camera portal reports that no
camera is present. With VCamdroid streaming, run:

```bash
systemctl --user restart wireplumber
```

Then reopen Camera/Snapshot and select **Virtual Camera (V4L2)**. The GUI's
**Setup v4l2 → Refresh Camera Detection** button runs the same command.

This is only needed when the device was enumerated before the stream started
(typically once per boot). If you prefer the device to be visible without this
step, load `v4l2loopback` with `exclusive_caps=0`; that always advertises
capture, but some Chromium/WebRTC applications may then ignore the device.
