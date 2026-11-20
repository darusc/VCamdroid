Name:           vcamdroid
Version:        0.1.0
Release:        5%{?dist}
Summary:        Use an Android phone as a virtual webcam on Linux

License:        MIT
URL:            https://github.com/darusc/VCamdroid
Source0:        vcamdroid-%{version}.tar.gz

BuildArch:      noarch

Requires:       python3 >= 3.10
Requires:       python3-tkinter
Requires:       python3-pillow
Requires:       python3-qrcode
# Fedora ships ffmpeg-free; RPM Fusion's ffmpeg conflicts with it. Accept either.
Requires:       (ffmpeg-free or ffmpeg)
Suggests:       adb
Suggests:       v4l2loopback

%description
VCamdroid turns an Android phone into a virtual webcam on Linux. It receives
the phone's RTSP stream with FFmpeg, writes it to a v4l2loopback device and
provides a Tkinter control panel plus a headless CLI.

%prep
%setup -q

%build

%install
rm -rf %{buildroot}
install -d %{buildroot}%{_bindir}
install -d %{buildroot}%{_prefix}/lib/vcamdroid
install -d %{buildroot}%{_datadir}/applications
install -m 0755 vcamdroid-launcher %{buildroot}%{_bindir}/vcamdroid
install -m 0644 vcamdroid_linux.py README.md requirements.txt %{buildroot}%{_prefix}/lib/vcamdroid/
cp -a vcamdroid %{buildroot}%{_prefix}/lib/vcamdroid/
install -m 0644 vcamdroid.desktop %{buildroot}%{_datadir}/applications/vcamdroid.desktop
install -d %{buildroot}%{_datadir}/icons
cp -a icons/hicolor %{buildroot}%{_datadir}/icons/

%files
%license LICENSE
%doc README.md
%{_bindir}/vcamdroid
%{_prefix}/lib/vcamdroid
%{_datadir}/applications/vcamdroid.desktop
%{_datadir}/icons/hicolor

%post
gtk-update-icon-cache -qf %{_datadir}/icons/hicolor 2>/dev/null || :
update-desktop-database -q %{_datadir}/applications 2>/dev/null || :

%postun
gtk-update-icon-cache -qf %{_datadir}/icons/hicolor 2>/dev/null || :
update-desktop-database -q %{_datadir}/applications 2>/dev/null || :

%changelog
* Fri Nov 20 2026 VCamdroid <https://github.com/darusc/VCamdroid> - 0.1.0-5
- Add a WirePlumber refresh helper for GNOME camera detection.

* Fri Nov 20 2026 VCamdroid <https://github.com/darusc/VCamdroid> - 0.1.0-4
- Use standard hicolor size directories and set the Tk window icon.

* Fri Nov 20 2026 VCamdroid <https://github.com/darusc/VCamdroid> - 0.1.0-3
- Add application icon to the desktop entry and hicolor icon theme.

* Fri Nov 20 2026 VCamdroid <https://github.com/darusc/VCamdroid> - 0.1.0-2
- Accept either ffmpeg-free or ffmpeg as a dependency.

* Fri Nov 20 2026 VCamdroid <https://github.com/darusc/VCamdroid> - 0.1.0-1
- Initial Linux client package.
