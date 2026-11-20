# VCamdroid 0.1.0 release artifacts

Built on 2026-11-20. The Android APK already uses the
application icon from `imgs/icon2.png`; the Linux packages install it in the
hicolor icon theme.

| File | Target | Install |
| --- | --- | --- |
| `VCamdroid-0.1.0.apk` | Android (debug build, installable via `adb install`) | `adb install -r VCamdroid-0.1.0.apk` |
| `vcamdroid-0.1.0-4.fc44.noarch.rpm` | Fedora / RHEL-family Linux | `sudo dnf install ./vcamdroid-0.1.0-4.fc44.noarch.rpm` |
| `vcamdroid_0.1.0_all.deb` | Debian / Ubuntu Linux | `sudo apt install ./vcamdroid_0.1.0_all.deb` |

Verify the downloads with:

```bash
sha256sum -c SHA256SUMS
```

Linux packages require `ffmpeg` and `python3` with tkinter; `v4l2loopback`
must be loaded on the host to expose the virtual webcam. See
[`linux/README.md`](../linux/README.md) for details.
