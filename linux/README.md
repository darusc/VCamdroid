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
sudo dnf install ./linux/dist/vcamdroid-0.1.0-4.fc44.noarch.rpm
sudo apt install ./linux/dist/vcamdroid_0.1.0_all.deb
```

Or from the committed artifacts:

```bash
sudo dnf install ./releases/vcamdroid-0.1.0-4.fc44.noarch.rpm
sudo apt install ./releases/vcamdroid_0.1.0_all.deb
```

Upgrade or remove the RPM with:

```bash
sudo dnf upgrade ./releases/vcamdroid-0.1.0-4.fc44.noarch.rpm
sudo dnf remove vcamdroid
```

If the launcher icon looks stale, refresh the caches (the packages already do
this on install) and log out/in:

```bash
sudo gtk-update-icon-cache -f -t /usr/share/icons/hicolor
sudo update-desktop-database /usr/share/applications
```
