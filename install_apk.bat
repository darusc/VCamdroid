@echo off
setlocal
echo Installing VCamdroid apk to android device

set "ADB=%~dp0..\adb\adb.exe"
set "APK=%~dp0..\apk\app-release.apk"

if not exist "%ADB%" (
    echo [ERROR] adb.exe was not found at: %ADB%
    exit /b 1
)

if not exist "%APK%" (
    echo [ERROR] Android APK was not found at: %APK%
    exit /b 1
)

"%ADB%" install -r "%APK%"
if errorlevel 1 (
    echo [ERROR] APK installation failed.
    echo If adb reported INSTALL_FAILED_UPDATE_INCOMPATIBLE, uninstall the old
    echo com.darusc.vcamdroid package first. This removes its local app data.
    exit /b 1
)

echo [SUCCESS] VCamdroid Android client installed.
exit /b 0