# VCamdroid Linux Client

Python client for Linux that receives the VCamdroid Android RTSP stream and exposes it as a virtual webcam using `v4l2loopback` and `ffmpeg`.

## Prerequisites

- **Python 3.10+** with `tkinter` and `Pillow`
- **FFmpeg** (`ffmpeg` in `PATH`)
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

The packages install the sources under `/usr/lib/vcamdroid` and a launcher at
`/usr/bin/vcamdroid` that uses the system Python (needed for tkinter). `ffmpeg`
is a hard dependency; `adb`, `v4l2loopback` and `qrcode` are recommended.

Install examples:

```bash
sudo dnf install linux/dist/vcamdroid-*.rpm
sudo apt install ./linux/dist/vcamdroid_*.deb
```
