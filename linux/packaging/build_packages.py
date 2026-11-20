#!/usr/bin/env python3
"""Build native vcamdroid packages (RPM and DEB) from the Linux client sources.

The packages install the Python sources under /usr/lib/vcamdroid and provide a
/usr/bin/vcamdroid launcher that uses the system Python (needed for tkinter).
External tools (ffmpeg, v4l2loopback, adb) are declared as dependencies.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
from pathlib import Path

LINUX_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = LINUX_DIR.parent
DIST_DIR = LINUX_DIR / "dist"
PACKAGE_DIR = LINUX_DIR / "vcamdroid"
ICONS_DIR = LINUX_DIR / "packaging" / "icons"

LAUNCHER = """#!/bin/sh
exec /usr/bin/python3 /usr/lib/vcamdroid/vcamdroid_linux.py "$@"
"""

DESKTOP = """[Desktop Entry]
Type=Application
Name=VCamdroid
Comment=Use an Android phone as a virtual webcam
Exec=vcamdroid
Icon=vcamdroid
Terminal=false
Categories=Utility;Video;
StartupWMClass=Vcamdroid
"""

DEB_UPDATE_CACHE = """#!/bin/sh
set -e
gtk-update-icon-cache -qf /usr/share/icons/hicolor 2>/dev/null || true
update-desktop-database -q /usr/share/applications 2>/dev/null || true
"""

DEB_CONTROL = """Package: vcamdroid
Version: {version}
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-tk, python3-pil, ffmpeg
Recommends: adb, python3-qrcode, v4l2loopback-dkms
Maintainer: VCamdroid <https://github.com/darusc/VCamdroid>
Description: Use an Android phone as a virtual webcam on Linux
 VCamdroid receives the phone's RTSP stream with FFmpeg, writes it to a
 v4l2loopback device and provides a control panel plus a headless CLI.
"""


def read_version() -> str:
    with (LINUX_DIR / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def source_files() -> list[Path]:
    files = [LINUX_DIR / "vcamdroid_linux.py", LINUX_DIR / "README.md", LINUX_DIR / "requirements.txt"]
    files.extend(sorted(PACKAGE_DIR.glob("*.py")))
    files.append(REPO_DIR / "LICENSE")
    return files


def copy_sources(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / "vcamdroid").mkdir(exist_ok=True)
    for path in source_files():
        dest = target / (Path("vcamdroid") / path.name if path.parent == PACKAGE_DIR else path.name)
        shutil.copy2(path, dest)
    launcher = target / "vcamdroid-launcher"
    launcher.write_text(LAUNCHER)
    launcher.chmod(0o755)
    (target / "vcamdroid.desktop").write_text(DESKTOP)
    shutil.copytree(ICONS_DIR, target / "icons", dirs_exist_ok=True)


def make_tarball(source_dir: Path, tarball: Path, arcname: str) -> None:
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(source_dir, arcname=arcname)


def build_rpm(work: Path, version: str) -> Path:
    top = work / "rpmbuild"
    for subdir in ("BUILD", "RPMS", "SOURCES", "SPECS", "SRPMS"):
        (top / subdir).mkdir(parents=True, exist_ok=True)

    source_dir = work / "src" / f"vcamdroid-{version}"
    copy_sources(source_dir)
    make_tarball(source_dir, top / "SOURCES" / f"vcamdroid-{version}.tar.gz", f"vcamdroid-{version}")

    spec = work / "vcamdroid.spec"
    spec_text = (LINUX_DIR / "packaging" / "vcamdroid.spec").read_text()
    spec_text = re.sub(
        r"(?m)^Version:\s*\S+", f"Version:        {version}", spec_text, count=1
    )
    spec.write_text(spec_text)
    subprocess.run(
        [
            "rpmbuild",
            "-bb",
            "--define",
            f"_topdir {top}",
            "--define",
            "_buildhost localhost",
            str(spec),
        ],
        check=True,
    )
    rpms = list((top / "RPMS").rglob("*.rpm"))
    if not rpms:
        raise RuntimeError("rpmbuild did not produce an RPM")
    output = DIST_DIR / rpms[0].name
    shutil.copy2(rpms[0], output)
    return output


def _tar_info(path: Path, arcname: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(arcname)
    stat = path.stat()
    info.size = stat.st_size
    info.mode = stat.st_mode & 0o7777
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    if path.is_dir():
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        info.size = 0
    return info


def build_deb(work: Path, version: str) -> Path:
    root = work / "deb" / "root"
    copy_sources(root / "usr" / "lib" / "vcamdroid")
    # Icons belong in the hicolor theme only, not next to the sources.
    shutil.rmtree(root / "usr" / "lib" / "vcamdroid" / "icons")
    (root / "usr" / "bin").mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "usr" / "lib" / "vcamdroid" / "vcamdroid-launcher", root / "usr" / "bin" / "vcamdroid")
    (root / "usr" / "share" / "applications").mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        root / "usr" / "lib" / "vcamdroid" / "vcamdroid.desktop",
        root / "usr" / "share" / "applications" / "vcamdroid.desktop",
    )

    shutil.copytree(ICONS_DIR, root / "usr" / "share" / "icons", dirs_exist_ok=True)

    control_dir = work / "deb" / "control"
    control_dir.mkdir(parents=True, exist_ok=True)
    (control_dir / "control").write_text(DEB_CONTROL.format(version=version))
    for name in ("postinst", "postrm"):
        script = control_dir / name
        script.write_text(DEB_UPDATE_CACHE)
        script.chmod(0o755)

    control_tar = work / "deb" / "control.tar.gz"
    with tarfile.open(control_tar, "w:gz") as tf:
        for name in ("control", "postinst", "postrm"):
            path = control_dir / name
            info = tarfile.TarInfo(f"./{name}")
            info.size = path.stat().st_size
            info.mode = path.stat().st_mode & 0o7777
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            with path.open("rb") as fh:
                tf.addfile(info, fh)

    data_tar = work / "deb" / "data.tar.gz"
    with tarfile.open(data_tar, "w:gz") as tf:
        for path in sorted((root / "usr").rglob("*")):
            arcname = "./" + str(path.relative_to(root))
            info = _tar_info(path, arcname)
            if path.is_file():
                with path.open("rb") as fh:
                    tf.addfile(info, fh)
            else:
                tf.addfile(info)

    ar_dir = work / "deb" / "ar"
    ar_dir.mkdir(parents=True, exist_ok=True)
    (ar_dir / "debian-binary").write_text("2.0\n")
    for name in ("control.tar.gz", "data.tar.gz"):
        shutil.copy2(work / "deb" / name, ar_dir / name)

    output = DIST_DIR / f"vcamdroid_{version}_all.deb"
    subprocess.run(
        ["ar", "rcs", str(output), "debian-binary", "control.tar.gz", "data.tar.gz"],
        cwd=ar_dir,
        check=True,
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpm", action="store_true", help="build the RPM package")
    parser.add_argument("--deb", action="store_true", help="build the DEB package")
    args = parser.parse_args()
    build_all = not (args.rpm or args.deb)

    version = read_version()
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    built: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="vcamdroid-packaging-") as tmp:
        work = Path(tmp)
        if build_all or args.rpm:
            built.append(build_rpm(work, version))
        if build_all or args.deb:
            built.append(build_deb(work, version))
    for path in built:
        print(path)


if __name__ == "__main__":
    main()
