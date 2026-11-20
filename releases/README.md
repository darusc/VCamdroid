# VCamdroid 0.1.0 release artifacts

Built on 2026-11-20. The Android APK uses the application icon from
`imgs/icon2.png`; the Linux packages install the same icon in the hicolor theme
and set it as the window icon of the Linux client.

| File | Target | Install |
| --- | --- | --- |
| `VCamdroid-0.1.0.apk` | Android (debug build, installable with `adb`) | `adb install -r VCamdroid-0.1.0.apk` |
| `vcamdroid-0.1.0-4.fc44.noarch.rpm` | Fedora / RHEL-family Linux | `sudo dnf install ./vcamdroid-0.1.0-4.fc44.noarch.rpm` |
| `vcamdroid_0.1.0_all.deb` | Debian / Ubuntu Linux | `sudo apt install ./vcamdroid_0.1.0_all.deb` |

Run these commands from inside this `releases/` directory.

## Fedora notes

The RPM accepts either `ffmpeg-free` (Fedora's default) or `ffmpeg` (RPM
Fusion), so installing it will **not** replace your existing `ffmpeg-free`.
Do not use `--allowerasing`. To upgrade or remove:

```bash
sudo dnf upgrade ./vcamdroid-0.1.0-4.fc44.noarch.rpm
sudo dnf remove vcamdroid
```

## Debian / Ubuntu notes

There is no `ffmpeg-free` package in Debian/Ubuntu; the DEB depends on the
official `ffmpeg` package, which does not conflict with anything. APT resolves
the remaining Python dependencies automatically.

## Verify downloads

```bash
sha256sum -c SHA256SUMS
```

## Before using the virtual camera

Linux packages require `python3` with tkinter (installed automatically) and
`v4l2loopback` loaded on the host:

```bash
sudo modprobe v4l2loopback devices=1 video_nr=10 card_label="VCamdroid" exclusive_caps=1
```

See [`linux/README.md`](../linux/README.md) for full details. If the launcher
icon looks stale, run:

```bash
sudo gtk-update-icon-cache -f -t /usr/share/icons/hicolor
sudo update-desktop-database /usr/share/applications
```

then log out and back in.
