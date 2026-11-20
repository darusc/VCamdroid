# VCamdroid 0.1.0 release artifacts

Built from commit `7e95156` on 2026-11-20.

| File | Target | Install |
| --- | --- | --- |
| `VCamdroid-0.1.0.apk` | Android (debug build, installable via `adb install`) | `adb install -r VCamdroid-0.1.0.apk` |
| `vcamdroid-0.1.0-1.fc44.noarch.rpm` | Fedora / RHEL-family Linux | `sudo dnf install ./vcamdroid-0.1.0-1.fc44.noarch.rpm` |
| `vcamdroid_0.1.0_all.deb` | Debian / Ubuntu Linux | `sudo apt install ./vcamdroid_0.1.0_all.deb` |

Verify the downloads with:

```bash
sha256sum -c SHA256SUMS
```

Linux packages require `ffmpeg` and `python3` with tkinter; `v4l2loopback`
must be loaded on the host to expose the virtual webcam. See
[`linux/README.md`](../linux/README.md) for details.
