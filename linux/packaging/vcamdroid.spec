Name:           vcamdroid
Version:        0.1.0
Release:        1%{?dist}
Summary:        Use an Android phone as a virtual webcam on Linux

License:        MIT
URL:            https://github.com/darusc/VCamdroid
Source0:        vcamdroid-%{version}.tar.gz

BuildArch:      noarch

Requires:       python3 >= 3.10
Requires:       python3-tkinter
Requires:       python3-pillow
Requires:       python3-qrcode
Requires:       ffmpeg
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

%files
%license LICENSE
%doc README.md
%{_bindir}/vcamdroid
%{_prefix}/lib/vcamdroid
%{_datadir}/applications/vcamdroid.desktop

%changelog
* Fri Nov 20 2026 VCamdroid <https://github.com/darusc/VCamdroid> - 0.1.0-1
- Initial Linux client package.
